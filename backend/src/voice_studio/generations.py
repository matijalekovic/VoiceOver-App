"""Generated audio: history, playback files, exports and deletion."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import audio
from .errors import NotFound, StudioError

if TYPE_CHECKING:
    from .studio import Studio


def generation_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if k not in ("params_json", "stats_json", "audio_path")}
    out["params"] = json.loads(row["params_json"])
    out["stats"] = json.loads(row["stats_json"])
    return out


def safe_filename(name: str, limit: int = 80) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "", name, flags=re.UNICODE).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or "audio")[:limit].rstrip(" .")


def unique_path(folder: Path, stem: str, suffix: str) -> Path:
    candidate = folder / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


class GenerationService:
    def __init__(self, studio: Studio):
        self.studio = studio
        self.db = studio.db

    def page(
        self,
        kind: str | None = None,
        voice_id: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where, params = ["1 = 1"], []
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if voice_id:
            where.append("voice_id = ?")
            params.append(voice_id)
        if query:
            where.append("(text LIKE ? OR voice_name LIKE ?)")
            params += [f"%{query}%", f"%{query}%"]
        clause = " AND ".join(where)
        total = self.db.one(f"SELECT COUNT(*) AS n FROM generations WHERE {clause}", tuple(params))[
            "n"
        ]
        rows = self.db.all(
            f"SELECT * FROM generations WHERE {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return {"items": [generation_row(r) for r in rows], "total": total}

    def row(self, generation_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM generations WHERE id = ?", (generation_id,))
        if not row:
            raise NotFound("Generation", generation_id)
        return row

    def get(self, generation_id: str) -> dict[str, Any]:
        return generation_row(self.row(generation_id))

    def audio_path(self, generation_id: str) -> Path:
        path = self.studio.paths.resolve(self.row(generation_id)["audio_path"])
        if not path.exists():
            raise StudioError(
                "audio_missing", "The audio file for this generation is missing.", status_code=410
            )
        return path

    def output_dir(self) -> Path:
        folder = Path(self.studio.pref("output_dir")).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StudioError(
                "output_dir_unwritable",
                f"Cannot write to the output folder {folder}. Choose another in Settings.",
            ) from exc
        return folder

    def export(
        self, generation_id: str, fmt: str, bitrate: int, sample_rate: int | None
    ) -> dict[str, Any]:
        row = self.row(generation_id)
        folder = self.output_dir()
        stamp = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).astimezone()
        words = " ".join(row["text"].split()[:6])
        stem = safe_filename(f"{stamp:%Y-%m-%d %H%M} {row['voice_name']} - {words}")
        target = unique_path(folder, stem, f".{fmt}")
        audio.export(
            self.audio_path(generation_id), target, fmt, bitrate=bitrate, sample_rate=sample_rate
        )
        return {"paths": [str(target)], "folder": str(folder)}

    def delete(self, generation_id: str) -> None:
        row = self.row(generation_id)
        with self.db.write() as conn:
            conn.execute(
                "UPDATE segments SET active_generation_id = NULL WHERE active_generation_id = ?",
                (generation_id,),
            )
            conn.execute(
                "UPDATE voices SET preferred_sample_generation_id = NULL WHERE preferred_sample_generation_id = ?",
                (generation_id,),
            )
            conn.execute("DELETE FROM generations WHERE id = ?", (generation_id,))
        self.studio.paths.resolve(row["audio_path"]).unlink(missing_ok=True)
