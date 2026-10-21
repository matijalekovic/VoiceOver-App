"""The application object: wires storage, the model manager, the worker and the job queue."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Any

from .catalog import DEFAULT_MODEL_ID, ModelSpec
from .config import Settings
from .db import Database
from .models import ModelManager
from .worker.process import InferenceClient

DEFAULT_PREFERENCES: dict[str, Any] = {
    "default_model_id": DEFAULT_MODEL_ID,
    "output_dir": str(Path.home() / "Music" / "1PAX Voice Studio"),
    "idle_unload_minutes": 15,
    "unload_on_memory_pressure": True,
    # Only languages evaluated on the target Mac are offered by default (spec 3.C).
    "enabled_languages": ["english", "french", "spanish"],
    "language_notes": {},
    "max_chunk_chars": 350,
    "sentence_pause_ms": 250,
    "paragraph_pause_ms": 700,
    "default_export_format": "wav",
    "default_mp3_bitrate": 320,
    "theme": "system",
}


def configure_logging(log_dir: Path) -> None:
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "backend.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    root.setLevel(logging.INFO)


class Studio:
    def __init__(self, settings: Settings, catalog: list[ModelSpec] | None = None):
        from .jobs import JobRunner

        self.settings = settings
        self.paths = settings.paths
        self.paths.ensure()
        self.db = Database(self.paths.database)
        self.db.migrate()
        self.models = ModelManager(
            self.paths.models,
            self.paths.logs / "downloads.log",
            hf_home=self.paths.cache / "huggingface",
            catalog=catalog,
        )
        self.inference = InferenceClient(self.paths.logs / "inference.log")
        self.jobs = JobRunner(self)

    def preferences(self) -> dict[str, Any]:
        return {**DEFAULT_PREFERENCES, **self.db.get_settings()}

    def pref(self, key: str) -> Any:
        return self.db.get_setting(key, DEFAULT_PREFERENCES.get(key))

    def start(self) -> None:
        self.jobs.start()

    def stop(self) -> None:
        self.jobs.stop()
        self.inference.unload()
        self.models.shutdown()
