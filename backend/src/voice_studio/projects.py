"""Long-form projects: scripts split into segments, per-segment takes, assembly and export."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import audio, text
from .db import new_id, now_iso
from .errors import NotFound, StudioError
from .generations import safe_filename, unique_path
from .jobs import ACTIVE, job_row

if TYPE_CHECKING:
    from .studio import Studio


class ProjectService:
    def __init__(self, studio: Studio):
        self.studio = studio
        self.db = studio.db
        self.paths = studio.paths

    # -- reading ---------------------------------------------------------------
    def list(self) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT p.*, "
            "(SELECT COUNT(*) FROM segments s WHERE s.project_id = p.id) AS segment_count, "
            "(SELECT COUNT(*) FROM segments s WHERE s.project_id = p.id AND s.active_generation_id IS NOT NULL) "
            "AS generated_count, "
            "(SELECT COALESCE(SUM(g.duration_s), 0) FROM segments s JOIN generations g "
            " ON g.id = s.active_generation_id WHERE s.project_id = p.id) AS duration_s "
            "FROM projects p ORDER BY p.updated_at DESC"
        )
        return rows

    def get(self, project_id: str) -> dict[str, Any]:
        project = self.db.one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not project:
            raise NotFound("Project", project_id)
        segments = self.db.all(
            "SELECT * FROM segments WHERE project_id = ? ORDER BY position", (project_id,)
        )
        takes = self.db.all(
            "SELECT id, segment_id, text, duration_s, created_at, model_id, voice_name FROM generations "
            "WHERE project_id = ? AND kind = 'segment' ORDER BY created_at",
            (project_id,),
        )
        jobs = self.db.all(
            "SELECT * FROM jobs WHERE project_id = ? AND kind = 'segment' ORDER BY created_at",
            (project_id,),
        )
        takes_by_segment: dict[str, list[dict[str, Any]]] = {}
        for take in takes:
            takes_by_segment.setdefault(take["segment_id"], []).append(take)
        job_by_segment = {j["segment_id"]: job_row(j) for j in jobs}  # latest wins
        out_segments = []
        generated = 0
        duration = 0.0
        for seg in segments:
            seg_takes = takes_by_segment.get(seg["id"], [])
            active = next((t for t in seg_takes if t["id"] == seg["active_generation_id"]), None)
            if active:
                generated += 1
                duration += active["duration_s"]
            out_segments.append(
                {
                    **seg,
                    "takes": seg_takes,
                    "active_take_stale": bool(active and active["text"] != seg["text"]),
                    "job": job_by_segment.get(seg["id"]),
                }
            )
        return {
            **project,
            "segments": out_segments,
            "segment_count": len(segments),
            "generated_count": generated,
            "duration_s": round(duration, 3),
        }

    # -- writing ---------------------------------------------------------------
    def _model_for(self, voice_id: str | None, model_id: str | None) -> str:
        """Keep the project's checkpoint compatible with how its voice was made."""
        mode = "clone"
        if voice_id:
            from .voices import VoiceService

            voice = VoiceService(self.studio).get(voice_id)
            mode = voice["mode"]
            if mode == "design" and not voice["instructions"].strip():
                raise StudioError("instructions_required", "Describe the voice before using it.")
        chosen = model_id or self.studio.models.default_model_for(
            mode, self.studio.pref("default_model_id")
        )
        self.studio.models.spec_for_mode(mode, chosen)
        return chosen

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        if len(data.get("script", "")) > self.studio.settings.max_script_chars:
            raise StudioError(
                "script_too_long", "The script is too long for one project. Split it into several."
            )
        project_id = new_id()
        stamp = now_iso()
        model_id = self._model_for(data.get("voice_id"), data.get("model_id"))
        self.db.execute(
            "INSERT INTO projects (id, name, script, voice_id, language, model_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, data["name"].strip(), data.get("script", ""), data.get("voice_id"), data["language"],
             model_id, stamp, stamp),
        )  # fmt: skip
        (self.paths.projects / project_id / "segments").mkdir(parents=True, exist_ok=True)
        if data.get("script", "").strip():
            self.resegment(project_id, data["script"], data.get("segmentation", "paragraph"))
        self._write_script_json(project_id)
        return self.get(project_id)

    def update(self, project_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        project = self.get(project_id)
        fields = {k: v for k, v in patch.items() if v is not None}
        if "voice_id" in fields or "model_id" in fields:
            voice_id = fields.get("voice_id", project["voice_id"])
            requested = fields.get("model_id")
            # Changing only the voice lets its mode pick a compatible checkpoint.
            if requested is None and "voice_id" not in fields:
                requested = project["model_id"]
            fields["model_id"] = self._model_for(voice_id, requested)
        if fields:
            fields["updated_at"] = now_iso()
            assignments = ", ".join(f"{k} = ?" for k in fields)
            self.db.execute(
                f"UPDATE projects SET {assignments} WHERE id = ?", (*fields.values(), project_id)
            )
        self._write_script_json(project_id)
        return self.get(project_id)

    def delete(self, project_id: str) -> None:
        self.get(project_id)
        self.db.execute(
            "UPDATE jobs SET cancel_requested = 1, status = CASE WHEN status = 'queued' THEN 'cancelled' "
            "ELSE status END WHERE project_id = ? AND status NOT IN ('completed', 'failed', 'cancelled')",
            (project_id,),
        )
        self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        shutil.rmtree(self.paths.projects / project_id, ignore_errors=True)

    def resegment(self, project_id: str, script: str, mode: str) -> dict[str, Any]:
        """Replace the segment list from a script. Segments whose text is unchanged keep their takes."""
        project = self.get(project_id)
        max_chars = int(self.studio.pref("max_chunk_chars"))
        pieces = text.segment_script(script, mode, max_chars)
        existing: dict[str, list[dict[str, Any]]] = {}
        for seg in project["segments"]:
            existing.setdefault(seg["text"], []).append(seg)
        stamp = now_iso()
        keep: set[str] = set()
        with self.db.write() as conn:
            for position, piece in enumerate(pieces):
                pause = (
                    project["paragraph_pause_ms"]
                    if piece.ends_paragraph
                    else project["default_pause_ms"]
                )
                reusable = existing.get(piece.text)
                if reusable:
                    seg = reusable.pop(0)
                    keep.add(seg["id"])
                    conn.execute(
                        "UPDATE segments SET position = ?, updated_at = ? WHERE id = ?",
                        (position, stamp, seg["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO segments (id, project_id, position, text, pause_after_ms, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (new_id(), project_id, position, piece.text, pause, stamp, stamp),
                    )
            removed = [s for s in project["segments"] if s["id"] not in keep]
            for seg in removed:
                conn.execute("DELETE FROM segments WHERE id = ?", (seg["id"],))
            conn.execute(
                "UPDATE projects SET script = ?, updated_at = ? WHERE id = ?",
                (script, stamp, project_id),
            )
        for seg in removed:
            self._remove_segment_files(project_id, seg["id"])
        self._write_script_json(project_id)
        return self.get(project_id)

    def add_segment(
        self, project_id: str, body: str, after_id: str | None, pause_ms: int | None
    ) -> dict[str, Any]:
        project = self.get(project_id)
        segments = project["segments"]
        position = len(segments)
        if after_id:
            index = next((i for i, s in enumerate(segments) if s["id"] == after_id), None)
            if index is None:
                raise NotFound("Segment", after_id)
            position = index + 1
        stamp = now_iso()
        with self.db.write() as conn:
            conn.execute(
                "UPDATE segments SET position = position + 1 WHERE project_id = ? AND position >= ?",
                (project_id, position),
            )
            conn.execute(
                "INSERT INTO segments (id, project_id, position, text, pause_after_ms, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_id(), project_id, position, body.strip(),
                 project["default_pause_ms"] if pause_ms is None else pause_ms, stamp, stamp),
            )  # fmt: skip
        self._touch(project_id)
        return self.get(project_id)

    def update_segment(
        self, project_id: str, segment_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        seg = self._segment(project_id, segment_id)
        fields: dict[str, Any] = {}
        if patch.get("text") is not None:
            fields["text"] = patch["text"].strip()
        if patch.get("pause_after_ms") is not None:
            fields["pause_after_ms"] = patch["pause_after_ms"]
        if patch.get("active_generation_id") is not None:
            take = self.db.one(
                "SELECT id FROM generations WHERE id = ? AND segment_id = ?",
                (patch["active_generation_id"], seg["id"]),
            )
            if not take:
                raise NotFound("Take", patch["active_generation_id"])
            fields["active_generation_id"] = patch["active_generation_id"]
        if fields:
            fields["updated_at"] = now_iso()
            assignments = ", ".join(f"{k} = ?" for k in fields)
            self.db.execute(
                f"UPDATE segments SET {assignments} WHERE id = ?", (*fields.values(), segment_id)
            )
            self._touch(project_id)
        return self.get(project_id)

    def delete_segment(self, project_id: str, segment_id: str) -> dict[str, Any]:
        self._segment(project_id, segment_id)
        self.db.execute("DELETE FROM segments WHERE id = ?", (segment_id,))
        self._remove_segment_files(project_id, segment_id)
        self._renumber(project_id)
        return self.get(project_id)

    def reorder(self, project_id: str, segment_ids: list[str]) -> dict[str, Any]:
        project = self.get(project_id)
        current = {s["id"] for s in project["segments"]}
        if set(segment_ids) != current or len(segment_ids) != len(current):
            raise StudioError(
                "invalid_order",
                "The new order must list every segment of the project exactly once.",
            )
        with self.db.write() as conn:
            for position, segment_id in enumerate(segment_ids):
                conn.execute(
                    "UPDATE segments SET position = ? WHERE id = ?", (position, segment_id)
                )
        self._touch(project_id)
        return self.get(project_id)

    def queue_generation(
        self, project_id: str, segment_ids: list[str] | None, only_missing: bool
    ) -> list[dict]:
        project = self.get(project_id)
        if not project["voice_id"]:
            raise StudioError("voice_required", "Choose a voice for the project first.")
        from .voices import VoiceService

        voice = VoiceService(self.studio).get(project["voice_id"])
        if voice["mode"] == "design":
            if not voice["instructions"].strip():
                raise StudioError(
                    "instructions_required", "Describe the voice before generating the project."
                )
        else:
            VoiceService(self.studio).clone_reference(
                project["voice_id"], None
            )  # fail early if unusable
        self.studio.models.spec_for_mode(voice["mode"], project["model_id"])
        if not self.studio.models.is_installed(project["model_id"]):
            raise StudioError(
                "model_not_installed",
                "The project's model is not installed. Download it in Settings.",
            )
        wanted = set(segment_ids) if segment_ids is not None else None
        jobs = []
        for seg in project["segments"]:
            if wanted is not None and seg["id"] not in wanted:
                continue
            if seg["job"] and seg["job"]["status"] in ("queued", *ACTIVE):
                continue
            if (
                only_missing
                and wanted is None
                and seg["active_generation_id"]
                and not seg["active_take_stale"]
            ):
                continue
            jobs.append(
                self.studio.jobs.submit(
                    "segment",
                    {
                        "voice_id": project["voice_id"],
                        "language": project["language"],
                        "model_id": project["model_id"],
                    },
                    voice_id=project["voice_id"],
                    project_id=project_id,
                    segment_id=seg["id"],
                )
            )
        return jobs

    # -- assembly and export -------------------------------------------------------
    def _assemble(self, project: dict[str, Any], target: Path) -> float:
        missing = [
            i + 1 for i, s in enumerate(project["segments"]) if not s["active_generation_id"]
        ]
        if not project["segments"]:
            raise StudioError("empty_project", "The project has no segments.")
        if missing:
            listed = ", ".join(str(n) for n in missing[:10]) + ("…" if len(missing) > 10 else "")
            raise StudioError(
                "segments_missing_audio",
                f"{len(missing)} segment(s) have no audio yet (#{listed}). Generate them first.",
                details={"positions": missing},
            )
        parts = []
        sample_rate = None
        for seg in project["segments"]:
            row = self.db.one(
                "SELECT audio_path FROM generations WHERE id = ?", (seg["active_generation_id"],)
            )
            samples, sr = audio.read_audio(self.paths.resolve(row["audio_path"]))
            if sample_rate is None:
                sample_rate = sr
            elif sr != sample_rate:
                raise StudioError(
                    "sample_rate_mismatch", "Segments were generated at different sample rates."
                )
            parts.append((samples, seg["pause_after_ms"] / 1000))
        combined = audio.join(parts, sample_rate)
        audio.write_wav(target, combined, sample_rate)
        return len(combined) / sample_rate

    def preview(self, project_id: str) -> Path:
        project = self.get(project_id)
        target = self.paths.projects / project_id / "exports" / "assembly.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        self._assemble(project, target)
        return target

    def export(
        self, project_id: str, fmt: str, bitrate: int, sample_rate: int | None, mode: str
    ) -> dict[str, Any]:
        from .generations import GenerationService

        project = self.get(project_id)
        folder = GenerationService(self.studio).output_dir() / safe_filename(project["name"])
        folder.mkdir(parents=True, exist_ok=True)
        paths: list[str] = []
        if mode in ("combined", "both"):
            master = self.preview(project_id)
            target = unique_path(folder, safe_filename(project["name"]), f".{fmt}")
            audio.export(master, target, fmt, bitrate=bitrate, sample_rate=sample_rate)
            paths.append(str(target))
        if mode in ("segments", "both"):
            seg_folder = folder / "Segments"
            seg_folder.mkdir(parents=True, exist_ok=True)
            for index, seg in enumerate(project["segments"], start=1):
                if not seg["active_generation_id"]:
                    continue
                row = self.db.one(
                    "SELECT audio_path FROM generations WHERE id = ?",
                    (seg["active_generation_id"],),
                )
                words = " ".join(seg["text"].split()[:6])
                target = unique_path(seg_folder, safe_filename(f"{index:03d} {words}"), f".{fmt}")
                audio.export(
                    self.paths.resolve(row["audio_path"]),
                    target,
                    fmt,
                    bitrate=bitrate,
                    sample_rate=sample_rate,
                )
                paths.append(str(target))
            if not paths:
                raise StudioError("segments_missing_audio", "No segment has audio yet.")
        return {"paths": paths, "folder": str(folder)}

    # -- helpers -------------------------------------------------------------------
    def _segment(self, project_id: str, segment_id: str) -> dict[str, Any]:
        seg = self.db.one(
            "SELECT * FROM segments WHERE id = ? AND project_id = ?", (segment_id, project_id)
        )
        if not seg:
            raise NotFound("Segment", segment_id)
        return seg

    def _renumber(self, project_id: str) -> None:
        rows = self.db.all(
            "SELECT id FROM segments WHERE project_id = ? ORDER BY position", (project_id,)
        )
        with self.db.write() as conn:
            for position, row in enumerate(rows):
                conn.execute("UPDATE segments SET position = ? WHERE id = ?", (position, row["id"]))
        self._touch(project_id)

    def _touch(self, project_id: str) -> None:
        self.db.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now_iso(), project_id))
        self._write_script_json(project_id)

    def _remove_segment_files(self, project_id: str, segment_id: str) -> None:
        shutil.rmtree(
            self.paths.projects / project_id / "segments" / segment_id, ignore_errors=True
        )

    def _write_script_json(self, project_id: str) -> None:
        """A readable copy of the script and segment order next to the audio (spec section 6)."""
        project = self.db.one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not project:
            return
        segments = self.db.all(
            "SELECT id, position, text, pause_after_ms, active_generation_id FROM segments "
            "WHERE project_id = ? ORDER BY position",
            (project_id,),
        )
        folder = self.paths.projects / project_id
        folder.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"project": project, "segments": segments}, indent=2, ensure_ascii=False
        )
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".json.tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, folder / "script.json")
