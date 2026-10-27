"""The background job queue: one worker thread, one job at a time, persisted in SQLite.

Job states (spec 3.C): queued -> loading -> synthesizing -> processing -> completed | failed | cancelled.
Progress is reported in real units (text chunks done, seconds of audio produced),
never as an estimated percentage.
"""

from __future__ import annotations

import json
import logging
import random
import shutil
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil

from . import audio, style, text, timing
from .catalog import WHISPER_LANGUAGES, model_language
from .db import new_id, now_iso
from .errors import EngineError, JobCancelled, NotFound, StudioError

if TYPE_CHECKING:
    from .studio import Studio

log = logging.getLogger("voice_studio.jobs")

ACTIVE = ("loading", "synthesizing", "processing")
FINISHED = ("completed", "failed", "cancelled")
SYNTHESIS_KINDS = ("tts", "voice_test", "segment")


def memory_pressure_level() -> int | None:
    """macOS memory pressure: 1 normal, 2 warning, 4 critical. None where unavailable."""
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
            capture_output=True, text=True, timeout=2,
        )  # fmt: skip
        return int(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def job_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["payload"] = json.loads(out.pop("payload_json"))
    out["progress"] = json.loads(out.pop("progress_json") or "{}")
    result = out.pop("result_json")
    out["result"] = json.loads(result) if result else None
    out["cancel_requested"] = bool(out["cancel_requested"])
    return out


def _take_score(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """One take's closeness to the speaker from its chunk scores (consistency.ChunkScore)."""
    from .consistency import ChunkScore

    if not scores:  # an engine that cannot measure: every take ranks the same
        return {"similarity": None, "register_st": None, "rank": 0.0}
    parsed = [ChunkScore(**s) for s in scores]
    sims = [p.similarity for p in parsed if p.similarity is not None]
    registers = [p.register_st for p in parsed if p.register_st is not None]
    similarity = round(sum(sims) / len(sims), 3) if sims else None
    register = round(sum(registers) / len(registers), 2) if registers else None
    rank = round(sum(p.rank for p in parsed) / len(parsed), 4)
    return {"similarity": similarity, "register_st": register, "rank": rank}


class JobRunner:
    def __init__(self, studio: Studio):
        self.studio = studio
        self.db = studio.db
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._monitor: threading.Thread | None = None
        self.current_job_id: str | None = None

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        # A job that was mid-flight when the app closed cannot be resumed half-way;
        # mark it so the UI offers Retry. Queued jobs simply continue.
        self.db.execute(
            "UPDATE jobs SET status = 'failed', error_code = 'interrupted', "
            "error_message = 'Voice Studio closed while this job was running. Retry to generate it again.', "
            f"finished_at = ? WHERE status IN {ACTIVE}",
            (now_iso(),),
        )
        self.db.execute(
            "UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE status = 'queued' AND cancel_requested = 1",
            (now_iso(),),
        )
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="voice-studio-jobs", daemon=True)
        self._thread.start()
        self._monitor = threading.Thread(
            target=self._idle_monitor, name="voice-studio-idle", daemon=True
        )
        self._monitor.start()
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self.current_job_id:
            self.studio.inference.cancel_current()
        if self._thread:
            self._thread.join(timeout=15)

    # -- queue operations ------------------------------------------------------
    def submit(self, kind: str, payload: dict[str, Any], **links: str | None) -> dict[str, Any]:
        job_id = new_id()
        self.db.execute(
            "INSERT INTO jobs (id, kind, status, payload_json, voice_id, project_id, segment_id, created_at) "
            "VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)",
            (
                job_id, kind, json.dumps(payload), links.get("voice_id"), links.get("project_id"),
                links.get("segment_id"), now_iso(),
            ),
        )  # fmt: skip
        self._wake.set()
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not row:
            raise NotFound("Job", job_id)
        job = job_row(row)
        if job["status"] == "queued":
            ahead = self.db.one(
                "SELECT COUNT(*) AS n FROM jobs WHERE (status = 'queued' AND created_at < ?) "
                f"OR status IN {ACTIVE}",
                (job["created_at"],),
            )
            job["queue_position"] = ahead["n"] if ahead else 0
        return job

    def list(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status == "active":
            rows = self.db.all(
                f"SELECT * FROM jobs WHERE status IN ('queued', {', '.join(repr(s) for s in ACTIVE)}) "
                "ORDER BY created_at",
            )
        else:
            rows = self.db.all("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [job_row(r) for r in rows]

    def cancel(self, job_id: str, force: bool = False) -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] in FINISHED:
            return job
        if job["status"] == "queued":
            self.db.execute(
                "UPDATE jobs SET status = 'cancelled', cancel_requested = 1, finished_at = ? "
                "WHERE id = ? AND status = 'queued'",
                (now_iso(), job_id),
            )
        else:
            self.db.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))
            if self.current_job_id == job_id:
                if force:
                    self.studio.inference.force_stop()
                else:
                    self.studio.inference.cancel_current()
        return self.get(job_id)

    def retry(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] not in ("failed", "cancelled"):
            raise StudioError("not_retryable", "Only failed or cancelled jobs can be retried.")
        self.db.execute(
            "UPDATE jobs SET status = 'queued', cancel_requested = 0, error_code = NULL, error_message = NULL, "
            "progress_json = '{}', result_json = NULL, started_at = NULL, finished_at = NULL, created_at = ? "
            "WHERE id = ?",
            (now_iso(), job_id),
        )
        self._wake.set()
        return self.get(job_id)

    def has_pending_work(self) -> bool:
        row = self.db.one(
            f"SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued' OR status IN {ACTIVE}"
        )
        return bool(row and row["n"])

    # -- worker loop -------------------------------------------------------------
    def _next_job(self) -> dict[str, Any] | None:
        with self.db.write() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE jobs SET status = 'loading', started_at = ? WHERE id = ?",
                (now_iso(), row["id"]),
            )
            return job_row(dict(row))

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self._next_job()
            if job is None:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            self.current_job_id = job["id"]
            try:
                result = self._execute(job)
                self._finish(job["id"], "completed", result=result)
            except JobCancelled:
                self._finish(job["id"], "cancelled")
            except StudioError as exc:
                log.warning("job %s failed: %s %s", job["id"], exc.code, exc.message)
                self._finish(job["id"], "failed", error=(exc.code, exc.message))
            except Exception as exc:  # noqa: BLE001
                log.exception("job %s crashed", job["id"])
                self._finish(
                    job["id"], "failed", error=("internal_error", f"Unexpected error: {exc}")
                )
            finally:
                self.current_job_id = None
                shutil.rmtree(self.studio.paths.cache / "jobs" / job["id"], ignore_errors=True)
                self._after_job()

    def _finish(
        self,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: tuple[str, str] | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE jobs SET status = ?, result_json = ?, error_code = ?, error_message = ?, finished_at = ?, "
            "generation_id = COALESCE(?, generation_id) WHERE id = ?",
            (
                status,
                json.dumps(result) if result is not None else None,
                error[0] if error else None,
                error[1] if error else None,
                now_iso(),
                (result or {}).get("generation_id"),
                job_id,
            ),
        )

    def _set_stage(self, job_id: str, status: str, progress: dict[str, Any] | None = None) -> None:
        self.db.execute(
            "UPDATE jobs SET status = ?, progress_json = ? WHERE id = ?",
            (status, json.dumps(progress or {}), job_id),
        )

    def _check_cancel(self, job_id: str) -> None:
        row = self.db.one("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,))
        if row and row["cancel_requested"]:
            raise JobCancelled()

    def _after_job(self) -> None:
        if self.studio.pref("unload_on_memory_pressure") and (memory_pressure_level() or 0) >= 4:
            log.warning("critical memory pressure: unloading the model")
            self.studio.inference.unload()

    def _idle_monitor(self) -> None:
        inference = self.studio.inference
        while not self._stop.wait(30):
            minutes = self.studio.pref("idle_unload_minutes") or 0
            if (
                minutes
                and inference.state == "ready"
                and time.monotonic() - inference.last_used > minutes * 60
                and not self.has_pending_work()
            ):
                log.info("unloading the model after %s idle minutes", minutes)
                inference.unload()

    # -- execution -----------------------------------------------------------------
    def _execute(self, job: dict[str, Any]) -> dict[str, Any]:
        if job["kind"] == "load_model":
            return self._load_model(job, job["payload"]["model_id"])
        if job["kind"] in SYNTHESIS_KINDS:
            return self._synthesize(job)
        if job["kind"] == "voice_create":
            return self._create_voice(job)
        if job["kind"] == "language_takes":
            return self._language_takes(job)
        raise StudioError("unknown_job", f"Unknown job kind {job['kind']}.")

    def _load_model(self, job: dict[str, Any], model_id: str) -> dict[str, Any]:
        models = self.studio.models
        spec = models.voice_spec(model_id)
        if not models.is_installed(model_id):
            raise StudioError(
                "model_not_installed",
                f"{spec.label} is not installed. Download it in Settings → Models.",
            )
        inference = self.studio.inference
        if inference.loaded and inference.loaded["model_id"] == model_id:
            return {"model_id": model_id, "load_seconds": 0.0}
        if (memory_pressure_level() or 0) >= 4:
            raise StudioError(
                "memory_pressure",
                "macOS reports critical memory pressure. Close other apps before loading the model.",
            )
        self._set_stage(job["id"], "loading", {"message": f"Loading {spec.label}"})
        loaded = inference.ensure_loaded(model_id, spec.engine, models.model_dir(model_id))
        return {"model_id": model_id, "load_seconds": loaded["load_seconds"]}

    def _synthesize(self, job: dict[str, Any]) -> dict[str, Any]:
        from .voices import VoiceService

        payload = job["payload"]
        job_id = job["id"]
        studio = self.studio
        voices = VoiceService(studio)
        voice = voices.get(payload["voice_id"])
        mode = voice.get("mode", "clone")
        reference: dict[str, Any] | None = None
        instructions: str | None = None
        reference_id: str | None = None
        tone = (payload.get("tone") or "").strip() or None
        fingerprint = False
        method = "design"
        identity: list[str] | None = None
        profile = voices.language_profile(voice, payload["language"])
        if mode == "design":
            instructions = voice["instructions"].strip()
            if not instructions:
                raise StudioError(
                    "instructions_required",
                    f"“{voice['name']}” has no description, so it cannot be generated yet.",
                )
            if tone:  # a designed voice is a description; the tone extends it
                instructions = f"{instructions.rstrip('.')}. {tone}"
        else:
            clone = voices.clone_reference(
                payload["voice_id"],
                payload.get("reference_id"),
                language=payload["language"],
                tone=tone,
                force_fingerprint=bool(payload.get("fingerprint_take")),
            )
            fingerprint = bool(clone.get("fingerprint_only"))
            method = clone["method"]
            # Every take of a cloned voice is checked against the speaker's real recordings.
            identity = clone.get("identity") or [str(p) for p in voices.identity_audio(voice)]
            reference = {
                "audio_path": clone["audio_path"],
                "transcript": clone["transcript"],
                "fingerprint_only": fingerprint,
                # A generated anchor lends delivery and accent; who speaks stays the speaker.
                "identity": identity if method == "anchor" else None,
            }
            reference_id = clone["reference_id"]
            instructions = tone if fingerprint else None
        if job["kind"] == "segment":
            segment = self.db.one("SELECT * FROM segments WHERE id = ?", (job["segment_id"],))
            if not segment:
                raise StudioError(
                    "segment_deleted", "The segment was deleted before it was generated."
                )
            body = segment["text"]
        else:
            body = payload["text"]
        model_id = payload["model_id"]
        # Fail before loading the wrong checkpoint: a designed voice cannot run on Base.
        studio.models.spec_for_mode(mode, model_id)
        # The voice's delivery, then its language profile's, then this generation's.
        delivery = style.resolve(voice["style"], (profile or {}).get("style"), payload.get("style"))

        load = self._load_model(job, model_id)
        self._check_cancel(job_id)

        pieces = text.chunk_text(
            text.for_language(body, payload["language"]), int(studio.pref("max_chunk_chars"))
        )
        if not pieces:
            raise StudioError("empty_text", "There is no text to synthesise.")
        seed = payload.get("seed")
        if seed is None:
            if mode == "design":
                # The description is the identity, but a stable seed keeps separate segments
                # of the same designed voice closer together instead of re-rolling each time.
                seed = zlib.crc32(f"{voice['id']}:{voice['instructions']}".encode()) & (2**31 - 1)
            else:
                seed = random.randrange(2**31 - 1)
        work_dir = studio.paths.cache / "jobs" / job_id
        last_update = 0.0

        extra = payload.get("progress_extra") or {}

        def on_progress(message: dict[str, Any]) -> None:
            nonlocal last_update
            # Catches a cancel that arrived between loading and the start of synthesis.
            row = self.db.one("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,))
            if row and row["cancel_requested"]:
                studio.inference.cancel_current()
            if time.monotonic() - last_update < 0.4 and message["chunk"] != 0:
                return
            last_update = time.monotonic()
            self._set_stage(
                job_id,
                "synthesizing",
                {
                    "chunk": message["chunk"],
                    "chunks": message["chunks"],
                    "audio_seconds": message["audio_seconds"],
                    **extra,
                },
            )

        self._set_stage(
            job_id,
            "synthesizing",
            {"chunk": 0, "chunks": len(pieces), "audio_seconds": 0, **extra},
        )
        result = studio.inference.synthesize(
            {
                "chunks": [p.text for p in pieces],
                "language": model_language(payload["language"]),
                "reference": reference,
                "instructions": instructions,
                "identity": identity,
                "seed": seed,
                # One take, one seed: chunks differ only in their text (a retried chunk moves
                # its own seed; see consistency.py).
                "seed_step": 0,
                "out_dir": str(work_dir),
                **style.sampling(delivery["expressiveness"]),
            },
            on_progress,
        )

        self._set_stage(
            job_id,
            "processing",
            {"chunks": len(pieces), "audio_seconds": result["audio_seconds"], **extra},
        )
        sentence_gap = int(studio.pref("sentence_pause_ms")) / 1000
        paragraph_gap = int(studio.pref("paragraph_pause_ms")) / 1000
        parts = []
        sample_rate = result["sample_rate"]
        for piece, path in zip(pieces, result["files"], strict=True):
            samples, sr = audio.read_audio(Path(path))
            if sr != sample_rate:
                raise EngineError(
                    "sample_rate_mismatch", "The engine returned audio at an unexpected rate."
                )
            parts.append(
                (
                    audio.trim_edges(samples, sr),
                    paragraph_gap if piece.ends_paragraph else sentence_gap,
                )
            )
        target_s = payload.get("target_seconds")
        fitted = None
        if target_s:  # fit to a length; this replaces the speed setting
            combined, fitted = timing.fit(
                parts, sample_rate, float(target_s), pitch=delivery["pitch"]
            )
        else:
            combined = audio.join(parts, sample_rate)
            if style.needs_processing(delivery):
                combined = audio.change_tempo_pitch(
                    combined, sample_rate, speed=delivery["speed"], semitones=delivery["pitch"]
                )
        combined = audio.normalise_peak(combined, -1.0)
        if len(combined) == 0:
            raise StudioError("empty_output", "The model produced no audible speech.")

        generation_id = new_id()
        if job["kind"] == "segment":
            target = (
                studio.paths.projects
                / job["project_id"]
                / "segments"
                / job["segment_id"]
                / f"{generation_id}.wav"
            )
        else:
            target = studio.paths.generations / f"{generation_id}.wav"
        audio.write_wav(target, combined, sample_rate)

        loaded = studio.inference.loaded or {}
        stats = {
            "elapsed_s": result["elapsed_s"],
            "audio_seconds": result["audio_seconds"],
            "real_time_factor": result["real_time_factor"],
            "chunk_seconds": result["chunk_seconds"],
            "chunk_scores": result.get("chunk_scores"),
            "chunks": len(pieces),
            "load_seconds": load["load_seconds"],
            "memory": result.get("memory", {}),
            "system_available_bytes": psutil.virtual_memory().available,
            "engine": (loaded.get("info") or {}).get("engine"),
            "engine_details": (loaded.get("info") or {}).get("details"),
            "fit": fitted,
        }
        params = {
            "seed": seed,
            "max_chunk_chars": studio.pref("max_chunk_chars"),
            **delivery,
            "tone": tone,
            "target_seconds": target_s,
            "fingerprint": fingerprint,
            "method": method,
        }
        with self.db.write() as conn:
            if (
                job["kind"] == "segment"
                and not conn.execute(
                    "SELECT 1 FROM segments WHERE id = ?", (job["segment_id"],)
                ).fetchone()
            ):
                target.unlink(missing_ok=True)
                raise StudioError(
                    "segment_deleted", "The segment was deleted while it was being generated."
                )
            conn.execute(
                "INSERT INTO generations (id, kind, voice_id, voice_name, reference_id, project_id, segment_id, text, "
                "language, model_id, params_json, audio_path, duration_s, sample_rate, stats_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    generation_id, job["kind"], payload["voice_id"], voice["name"], reference_id,
                    job["project_id"], job["segment_id"], body, payload["language"], model_id,
                    json.dumps(params), studio.paths.relative(target), round(len(combined) / sample_rate, 3),
                    sample_rate, json.dumps(stats), now_iso(),
                ),
            )  # fmt: skip
            if job["kind"] == "segment":
                conn.execute(
                    "UPDATE segments SET active_generation_id = ?, updated_at = ? WHERE id = ?",
                    (generation_id, now_iso(), job["segment_id"]),
                )
        if payload.get("clip_id"):
            VoiceService(studio).set_clip_demo(
                payload["voice_id"], payload["clip_id"], generation_id
            )
        log.info(
            "generated %.1fs of audio in %.1fs (RTF %s)",
            result["audio_seconds"], result["elapsed_s"], result["real_time_factor"],
        )  # fmt: skip
        return {"generation_id": generation_id, "stats": stats}

    def _create_voice(self, job: dict[str, Any]) -> dict[str, Any]:
        """Clone: transcribe the recordings, cut clips and voice a demo with each.

        Design: read the description with a few different seeds, so takes can be compared.
        """
        from .clips import demo_script, pick_candidates
        from .voices import VoiceService

        payload = job["payload"]
        job_id = job["id"]
        voice_id = payload["voice_id"]
        language = payload["language"]
        models = self.studio.models
        voices = VoiceService(self.studio)
        voice = voices.get(voice_id)
        if voice.get("mode") == "design":
            return self._design_voice(job, voice)
        references = voice["references"]
        if not references:
            raise StudioError("reference_required", "Add at least one recording first.")

        pending = [r for r in references if r["segments"] is None]
        if pending:
            stt = next((s for s in models.catalog if s.kind == "stt"), None)
            if stt is None or not models.is_installed(stt.id):
                label = stt.label if stt else "The speech recognition model"
                raise StudioError(
                    "stt_not_installed",
                    f"{label} is needed to transcribe the recordings. Download it in Settings → Models.",
                )
            for number, ref in enumerate(pending, start=1):
                self._check_cancel(job_id)
                self._set_stage(
                    job_id,
                    "processing",
                    {
                        "step": "transcribing",
                        "message": f"Transcribing recording {number} of {len(pending)}",
                    },
                )
                segments = self.studio.inference.transcribe(
                    stt.engine,
                    models.model_dir(stt.id),
                    voices.reference_audio_path(voice_id, ref["id"], "source"),
                    WHISPER_LANGUAGES.get(ref["language"] or language),
                )
                # A clip's transcript is read by the model too (cloning continues it).
                spoken = ref["language"] or language
                for segment in segments:
                    segment["text"] = text.for_language(segment["text"], spoken)
                    for word in segment["words"]:
                        word["word"] = text.for_language(word["word"], spoken)
                voices.set_segments(voice_id, ref["id"], segments)

        self._check_cancel(job_id)
        self._set_stage(
            job_id, "processing", {"step": "choosing", "message": "Choosing the best clips"}
        )
        recordings = []
        for ref in voices.get(voice_id)["references"]:
            samples, sr = audio.read_audio(
                voices.reference_audio_path(voice_id, ref["id"], "source")
            )
            # Only speech inside the recording's trim window counts.
            segments = [
                s
                for s in ref["segments"] or []
                if s["start"] >= ref["trim_start_s"] - 0.3 and s["end"] <= ref["trim_end_s"] + 0.3
            ]
            recordings.append((ref["id"], segments, samples, sr))
        candidates = pick_candidates(recordings)
        if not candidates:
            raise StudioError(
                "no_usable_speech",
                "No usable stretch of speech was found. Add a clearer recording of at least 10 seconds.",
            )
        clips = voices.replace_candidates(voice_id, candidates)

        script = payload.get("text") or demo_script(language)
        seed = payload.get("seed")
        if seed is None:
            seed = random.randrange(2**31 - 1)  # one seed for all, so only the clip differs
        generation_ids = []
        for number, clip in enumerate(clips, start=1):
            self._check_cancel(job_id)
            demo = self._synthesize(
                {
                    **job,
                    "kind": "voice_test",
                    "payload": {
                        "text": script,
                        "voice_id": voice_id,
                        "reference_id": clip["id"],
                        "clip_id": clip["id"],
                        "language": language,
                        "model_id": payload["model_id"],
                        "seed": seed,
                        "progress_extra": {
                            "step": "demo",
                            "message": f"Voicing demo {number} of {len(clips)}",
                        },
                    },
                }
            )
            generation_ids.append(demo["generation_id"])
        return {"clip_ids": [c["id"] for c in clips], "generation_ids": generation_ids}

    # Four takes: in measurements one fingerprint take in seven came out off-voice, so four
    # nearly always include several good ones to choose from, in about a minute.
    LANGUAGE_TAKES = 4

    def _language_takes(self, job: dict[str, Any]) -> dict[str, Any]:
        """Candidate takes for a language profile: the demo script spoken natively from the
        speaker fingerprint with different seeds, each scored against the real recordings.
        The closest becomes the take every generation in the language continues from."""
        from .clips import demo_script
        from .voices import VoiceService

        payload = job["payload"]
        voice_id, language = payload["voice_id"], payload["language"]
        voices = VoiceService(self.studio)
        previous = voices.language_profile(voices.get(voice_id), language) or {}
        seed = payload.get("seed")
        if seed is None:
            seed = random.randrange(2**31 - 1)
        takes = []
        for number in range(1, self.LANGUAGE_TAKES + 1):
            self._check_cancel(job["id"])
            take = self._synthesize(
                {
                    **job,
                    "kind": "voice_test",
                    "payload": {
                        "text": demo_script(language),
                        "voice_id": voice_id,
                        "language": language,
                        "model_id": payload["model_id"],
                        "fingerprint_take": True,
                        "seed": seed + (number - 1) * 104_729,
                        "progress_extra": {
                            "step": "takes",
                            "message": f"Voicing take {number} of {self.LANGUAGE_TAKES}",
                        },
                    },
                }
            )
            scores = [s for s in take["stats"].get("chunk_scores") or [] if s]
            takes.append({"generation_id": take["generation_id"], **_take_score(scores)})
        # The take chosen before stays available to go back to; the rest of the old round goes.
        chosen = previous.get("demo_generation_id")
        kept = [t for t in previous.get("takes", []) if t["generation_id"] == chosen]
        for old in previous.get("takes", []):
            if old["generation_id"] != chosen:
                self._delete_generation(old["generation_id"])
        voices.set_language_takes(voice_id, language, takes + kept)
        return {"generation_ids": [t["generation_id"] for t in takes]}

    def _delete_generation(self, generation_id: str) -> None:
        row = self.db.one("SELECT audio_path FROM generations WHERE id = ?", (generation_id,))
        if row:
            self.studio.paths.resolve(row["audio_path"]).unlink(missing_ok=True)
            self.db.execute("DELETE FROM generations WHERE id = ?", (generation_id,))

    # Three takes is enough to hear how a description settles without a long wait.
    DESIGN_TAKES = 3

    def _design_voice(self, job: dict[str, Any], voice: dict[str, Any]) -> dict[str, Any]:
        from .clips import demo_script

        payload = job["payload"]
        language = payload["language"]
        model_id = payload["model_id"]
        self.studio.models.spec_for_mode("design", model_id)
        if not voice["instructions"].strip():
            raise StudioError("instructions_required", "Describe the voice before creating it.")
        script = payload.get("text") or demo_script(language)
        seed = payload.get("seed")
        if seed is None:
            seed = random.randrange(2**31 - 1)
        generation_ids = []
        for number in range(1, self.DESIGN_TAKES + 1):
            self._check_cancel(job["id"])
            take = self._synthesize(
                {
                    **job,
                    "kind": "voice_test",
                    "payload": {
                        "text": script,
                        "voice_id": voice["id"],
                        "language": language,
                        "model_id": model_id,
                        # The same description with different seeds gives variants to compare.
                        "seed": seed + (number - 1) * 7919,
                        "progress_extra": {
                            "step": "design",
                            "message": f"Designing take {number} of {self.DESIGN_TAKES}",
                        },
                    },
                }
            )
            generation_ids.append(take["generation_id"])
        self._prune_design_takes(voice["id"], generation_ids)
        return {"generation_ids": generation_ids}

    def _prune_design_takes(self, voice_id: str, keep: list[str]) -> None:
        """Each round of takes replaces the previous one; the chosen preview stays."""
        row = self.db.one(
            "SELECT preferred_sample_generation_id FROM voices WHERE id = ?", (voice_id,)
        )
        keep_ids = set(keep)
        if row and row["preferred_sample_generation_id"]:
            keep_ids.add(row["preferred_sample_generation_id"])
        for old in self.db.all(
            "SELECT id, audio_path FROM generations WHERE voice_id = ? AND kind = 'voice_test'",
            (voice_id,),
        ):
            if old["id"] in keep_ids:
                continue
            self.studio.paths.resolve(old["audio_path"]).unlink(missing_ok=True)
            self.db.execute("DELETE FROM generations WHERE id = ?", (old["id"],))
