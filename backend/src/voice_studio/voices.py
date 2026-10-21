"""Voice profiles and their reference recordings."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import audio
from .db import new_id, now_iso
from .errors import NotFound, StudioError
from .generations import safe_filename, unique_path

if TYPE_CHECKING:
    from .studio import Studio

ALLOWED_UPLOAD_SUFFIXES = {
    ".wav",
    ".mp3",
    ".m4a",
    ".flac",
    ".aac",
    ".ogg",
    ".webm",
    ".mp4",
    ".caf",
    ".aiff",
    ".aif",
}
EXPORT_FORMAT_VERSION = 1


def _reference_row(row: dict[str, Any]) -> dict[str, Any]:
    quality = json.loads(row["quality_json"])
    return {
        **{
            k: v for k, v in row.items() if k not in ("quality_json", "original_path", "audio_path")
        },
        "quality": quality["trimmed"],
        "source_quality": quality.get("source"),
    }


def _voice_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if not k.startswith("consent_")}
    out["consent"] = {
        "confirmed": bool(row["consent_confirmed"]),
        "speaker": row["consent_speaker"],
        "scope": row["consent_scope"],
        "notes": row["consent_notes"],
        "recorded_at": row["consent_recorded_at"],
    }
    return out


class VoiceService:
    def __init__(self, studio: Studio):
        self.studio = studio
        self.db = studio.db
        self.paths = studio.paths

    # -- profiles -----------------------------------------------------------
    def list(self) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT v.*, (SELECT COUNT(*) FROM generations g WHERE g.voice_id = v.id) AS generation_count "
            "FROM voices v ORDER BY v.updated_at DESC"
        )
        refs = self.db.all("SELECT * FROM reference_recordings ORDER BY created_at")
        by_voice: dict[str, list[dict[str, Any]]] = {}
        for ref in refs:
            by_voice.setdefault(ref["voice_id"], []).append(_reference_row(ref))
        return [{**_voice_row(r), "references": by_voice.get(r["id"], [])} for r in rows]

    def get(self, voice_id: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT v.*, (SELECT COUNT(*) FROM generations g WHERE g.voice_id = v.id) AS generation_count "
            "FROM voices v WHERE id = ?",
            (voice_id,),
        )
        if not row:
            raise NotFound("Voice", voice_id)
        refs = self.db.all(
            "SELECT * FROM reference_recordings WHERE voice_id = ? ORDER BY created_at", (voice_id,)
        )
        return {**_voice_row(row), "references": [_reference_row(r) for r in refs]}

    def create(
        self, name: str, description: str, language: str, consent: dict[str, Any]
    ) -> dict[str, Any]:
        voice_id = new_id()
        stamp = now_iso()
        self.db.execute(
            "INSERT INTO voices (id, name, description, language, status, consent_confirmed, consent_speaker, "
            "consent_scope, consent_notes, consent_recorded_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'draft', 1, ?, ?, ?, ?, ?, ?)",
            (
                voice_id, name.strip(), description, language, consent["speaker"].strip(),
                consent["scope"].strip(), consent.get("notes", ""), stamp, stamp, stamp,
            ),
        )  # fmt: skip
        (self.paths.voices / voice_id / "references").mkdir(parents=True, exist_ok=True)
        return self.get(voice_id)

    def update(self, voice_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        voice = self.get(voice_id)
        fields: dict[str, Any] = {}
        for key in ("name", "description", "language", "status"):
            if patch.get(key) is not None:
                fields[key] = patch[key]
        if "primary_reference_id" in patch and patch["primary_reference_id"] is not None:
            if not any(r["id"] == patch["primary_reference_id"] for r in voice["references"]):
                raise NotFound("Reference recording", patch["primary_reference_id"])
            fields["primary_reference_id"] = patch["primary_reference_id"]
        if (
            "preferred_sample_generation_id" in patch
            and patch["preferred_sample_generation_id"] is not None
        ):
            sample = self.db.one(
                "SELECT id FROM generations WHERE id = ? AND voice_id = ?",
                (patch["preferred_sample_generation_id"], voice_id),
            )
            if not sample:
                raise NotFound("Generation", patch["preferred_sample_generation_id"])
            fields["preferred_sample_generation_id"] = patch["preferred_sample_generation_id"]
        if patch.get("consent"):
            consent = patch["consent"]
            fields.update(
                consent_speaker=consent["speaker"],
                consent_scope=consent["scope"],
                consent_notes=consent.get("notes", ""),
                consent_recorded_at=now_iso(),
            )
        if fields.get("status") == "ready":
            self._check_ready(voice, fields.get("primary_reference_id"))
        if fields:
            fields["updated_at"] = now_iso()
            assignments = ", ".join(f"{k} = ?" for k in fields)
            self.db.execute(
                f"UPDATE voices SET {assignments} WHERE id = ?", (*fields.values(), voice_id)
            )
        return self.get(voice_id)

    def _check_ready(self, voice: dict[str, Any], primary_id: str | None) -> None:
        primary_id = primary_id or voice["primary_reference_id"]
        primary = next((r for r in voice["references"] if r["id"] == primary_id), None)
        if primary is None:
            raise StudioError(
                "reference_required", "Add a reference recording before saving the voice."
            )
        if not primary["transcript"].strip():
            raise StudioError(
                "transcript_required", "Enter the exact transcript of the reference recording."
            )
        blocking = [f for f in primary["quality"]["flags"] if f["severity"] == "error"]
        if blocking:
            raise StudioError("reference_unusable", blocking[0]["message"])

    def delete(self, voice_id: str, delete_generations: bool) -> None:
        self.get(voice_id)
        if delete_generations:
            rows = self.db.all(
                "SELECT id, audio_path FROM generations WHERE voice_id = ? AND kind != 'segment'",
                (voice_id,),
            )
            for row in rows:
                self.paths.resolve(row["audio_path"]).unlink(missing_ok=True)
            self.db.execute(
                "DELETE FROM generations WHERE voice_id = ? AND kind != 'segment'", (voice_id,)
            )
        else:
            # Test lines exist only to audition the voice; they go with it.
            rows = self.db.all(
                "SELECT audio_path FROM generations WHERE voice_id = ? AND kind = 'voice_test'",
                (voice_id,),
            )
            for row in rows:
                self.paths.resolve(row["audio_path"]).unlink(missing_ok=True)
            self.db.execute(
                "DELETE FROM generations WHERE voice_id = ? AND kind = 'voice_test'", (voice_id,)
            )
        # Source recordings and anything derived from them are removed with the profile.
        self.db.execute("DELETE FROM voices WHERE id = ?", (voice_id,))
        shutil.rmtree(self.paths.voices / voice_id, ignore_errors=True)

    # -- reference recordings ----------------------------------------------
    def _ref_dir(self, voice_id: str, ref_id: str) -> Path:
        return self.paths.voices / voice_id / "references" / ref_id

    def add_reference(
        self,
        voice_id: str,
        upload: Path,
        filename: str,
        transcript: str,
        language: str | None,
    ) -> dict[str, Any]:
        voice = self.get(voice_id)
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            raise StudioError(
                "unsupported_file",
                "Upload a WAV, MP3, M4A or FLAC recording.",
                details={"suffix": suffix},
            )
        ref_id = new_id()
        folder = self._ref_dir(voice_id, ref_id)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            original = folder / f"original{suffix}"
            shutil.move(str(upload), original)
            original.chmod(0o600)
            source = folder / "source.wav"
            audio.decode_to_wav(original, source)
            samples, sr = audio.read_audio(source)
            source_quality = audio.analyse(samples, sr)
            start, end = audio.speech_bounds(samples, sr)
            quality = self._render_reference(folder, start, end)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        (folder / "transcript.txt").write_text(transcript.strip(), encoding="utf-8")
        stamp = now_iso()
        self.db.execute(
            "INSERT INTO reference_recordings (id, voice_id, original_filename, original_path, audio_path, transcript, "
            "language, duration_s, source_duration_s, trim_start_s, trim_end_s, quality_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ref_id, voice_id, Path(filename).name[:255], self.paths.relative(original),
                self.paths.relative(folder / "reference.wav"), transcript.strip(), language or voice["language"],
                quality.duration_s, source_quality.duration_s, start, end,
                json.dumps({"trimmed": quality.to_dict(), "source": source_quality.to_dict()}), stamp, stamp,
            ),
        )  # fmt: skip
        if not voice["primary_reference_id"]:
            self.db.execute(
                "UPDATE voices SET primary_reference_id = ?, updated_at = ? WHERE id = ?",
                (ref_id, stamp, voice_id),
            )
        return self.reference(voice_id, ref_id)

    def _render_reference(self, folder: Path, start: float, end: float) -> audio.QualityReport:
        """Cut [start, end] out of source.wav, normalise it and write reference.wav."""
        samples, sr = audio.read_audio(folder / "source.wav")
        duration = len(samples) / sr
        start = max(0.0, min(start, duration))
        end = max(start, min(end, duration))
        if end - start < 1.0:
            raise StudioError(
                "trim_too_short", "The trimmed reference must be at least one second long."
            )
        clip = samples[int(start * sr) : int(end * sr)]
        clip = audio.fade(audio.normalise_peak(clip, -1.0), sr, ms=10)
        audio.write_wav(folder / "reference.wav", clip, sr)
        return audio.analyse(clip, sr)

    def reference(self, voice_id: str, ref_id: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM reference_recordings WHERE id = ? AND voice_id = ?", (ref_id, voice_id)
        )
        if not row:
            raise NotFound("Reference recording", ref_id)
        return _reference_row(row)

    def reference_row(self, voice_id: str, ref_id: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM reference_recordings WHERE id = ? AND voice_id = ?", (ref_id, voice_id)
        )
        if not row:
            raise NotFound("Reference recording", ref_id)
        return row

    def update_reference(self, voice_id: str, ref_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        row = self.reference_row(voice_id, ref_id)
        folder = self._ref_dir(voice_id, ref_id)
        fields: dict[str, Any] = {}
        if patch.get("transcript") is not None:
            fields["transcript"] = patch["transcript"].strip()
            (folder / "transcript.txt").write_text(fields["transcript"], encoding="utf-8")
        if patch.get("language") is not None:
            fields["language"] = patch["language"]
        if patch.get("trim_start_s") is not None or patch.get("trim_end_s") is not None:
            start = patch.get("trim_start_s")
            end = patch.get("trim_end_s")
            start = row["trim_start_s"] if start is None else start
            end = row["trim_end_s"] if end is None else end
            quality = self._render_reference(folder, float(start), float(end))
            stored = json.loads(row["quality_json"])
            fields.update(
                trim_start_s=start,
                trim_end_s=end,
                duration_s=quality.duration_s,
                quality_json=json.dumps({**stored, "trimmed": quality.to_dict()}),
            )
        if fields:
            fields["updated_at"] = now_iso()
            assignments = ", ".join(f"{k} = ?" for k in fields)
            self.db.execute(
                f"UPDATE reference_recordings SET {assignments} WHERE id = ?",
                (*fields.values(), ref_id),
            )
            self.db.execute("UPDATE voices SET updated_at = ? WHERE id = ?", (now_iso(), voice_id))
        return self.reference(voice_id, ref_id)

    def delete_reference(self, voice_id: str, ref_id: str) -> None:
        self.reference_row(voice_id, ref_id)
        self.db.execute("DELETE FROM reference_recordings WHERE id = ?", (ref_id,))
        shutil.rmtree(self._ref_dir(voice_id, ref_id), ignore_errors=True)
        voice = self.get(voice_id)
        if voice["primary_reference_id"] == ref_id:
            replacement = voice["references"][0]["id"] if voice["references"] else None
            self.db.execute(
                "UPDATE voices SET primary_reference_id = ?, status = CASE WHEN ? IS NULL THEN 'draft' ELSE status END, "
                "updated_at = ? WHERE id = ?",
                (replacement, replacement, now_iso(), voice_id),
            )

    def reference_audio_path(self, voice_id: str, ref_id: str, which: str) -> Path:
        row = self.reference_row(voice_id, ref_id)
        if which == "source":
            return self._ref_dir(voice_id, ref_id) / "source.wav"
        return self.paths.resolve(row["audio_path"])

    def clone_reference(self, voice_id: str, ref_id: str | None) -> dict[str, Any]:
        """The recording and transcript a generation clones from."""
        voice = self.get(voice_id)
        ref_id = ref_id or voice["primary_reference_id"]
        if not ref_id:
            raise StudioError(
                "reference_required", f"The voice “{voice['name']}” has no reference recording."
            )
        row = self.reference_row(voice_id, ref_id)
        if not row["transcript"].strip():
            raise StudioError(
                "transcript_required", f"The reference for “{voice['name']}” has no transcript yet."
            )
        path = self.paths.resolve(row["audio_path"])
        if not path.exists():
            raise StudioError(
                "reference_missing", "The reference recording file is missing from disk."
            )
        return {
            "voice": voice,
            "reference_id": ref_id,
            "audio_path": str(path),
            "transcript": row["transcript"],
        }

    # -- export / import ----------------------------------------------------
    def export_zip(self, voice_id: str, out_dir: Path) -> Path:
        """A portable backup of the profile: consent record, recordings and transcripts."""
        voice = self.get(voice_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = unique_path(out_dir, safe_filename(voice["name"]) or "voice", ".voice.zip")
        manifest = {"format": "1pax-voice", "version": EXPORT_FORMAT_VERSION, "voice": voice}
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("voice.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            for ref in voice["references"]:
                folder = self._ref_dir(voice_id, ref["id"])
                for name in ("source.wav", "reference.wav", "transcript.txt"):
                    if (folder / name).exists():
                        zf.write(folder / name, f"references/{ref['id']}/{name}")
        return target

    def import_zip(self, archive: Path) -> dict[str, Any]:
        try:
            zf = zipfile.ZipFile(archive)
        except zipfile.BadZipFile as exc:
            raise StudioError(
                "invalid_archive", "This is not a Voice Studio voice export."
            ) from exc
        with zf:
            try:
                manifest = json.loads(zf.read("voice.json"))
            except KeyError as exc:
                raise StudioError(
                    "invalid_archive", "voice.json is missing from the archive."
                ) from exc
            if manifest.get("format") != "1pax-voice":
                raise StudioError("invalid_archive", "This is not a Voice Studio voice export.")
            data = manifest["voice"]
            consent = data.get("consent") or {}
            if not consent.get("confirmed"):
                raise StudioError(
                    "consent_required", "The exported voice carries no consent record."
                )
            voice = self.create(
                name=f"{data['name']} (imported)",
                description=data.get("description", ""),
                language=data["language"],
                consent={
                    "speaker": consent["speaker"],
                    "scope": consent["scope"],
                    "notes": consent.get("notes", ""),
                },
            )
            primary_new: str | None = None
            for ref in data.get("references", []):
                member = f"references/{ref['id']}/source.wav"
                if member not in zf.namelist():
                    continue
                tmp = self.paths.cache / f"import-{new_id()}.wav"
                with zf.open(member) as src, open(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                name = f"{Path(ref.get('original_filename') or 'reference').stem}.wav"
                created = self.add_reference(
                    voice["id"], tmp, name, ref.get("transcript", ""), ref.get("language")
                )
                created = self.update_reference(
                    voice["id"], created["id"],
                    {"trim_start_s": ref.get("trim_start_s"), "trim_end_s": ref.get("trim_end_s")},
                )  # fmt: skip
                if ref["id"] == data.get("primary_reference_id"):
                    primary_new = created["id"]
            patch: dict[str, Any] = {}
            if primary_new:
                patch["primary_reference_id"] = primary_new
            if data.get("status") == "ready":
                patch["status"] = "ready"
            return self.update(voice["id"], patch) if patch else self.get(voice["id"])
