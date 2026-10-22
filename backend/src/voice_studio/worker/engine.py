"""The inference adapter interface.

The UI and API never touch a model runtime directly. Every runtime sits behind this
interface and runs inside the worker process, so swapping MLX/Qwen3-TTS for another
runtime later means writing one new class, not touching the app.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np


@dataclass
class EngineInfo:
    engine: str
    model_dir: str
    sample_rate: int
    languages: list[str]
    details: dict = field(default_factory=dict)


@dataclass
class CloneReference:
    audio_path: str  # mono WAV at the engine's sample rate
    transcript: str  # exact words spoken in audio_path


@dataclass
class ChunkRequest:
    text: str
    language: str
    # A cloning reference. None for a designed voice, which is described by `instructions`.
    reference: CloneReference | None = None
    seed: int | None = None
    temperature: float | None = None  # sampling; None keeps the engine's default
    top_p: float | None = None
    # The written description a Voice Design checkpoint turns into a voice.
    instructions: str | None = None


class TTSEngine(Protocol):
    """One loaded checkpoint. Instances live only inside the worker process."""

    def load(self, model_dir: Path) -> EngineInfo: ...

    def synthesize(self, request: ChunkRequest) -> np.ndarray:
        """Return float32 mono audio at EngineInfo.sample_rate for one chunk of text.
        """
        ...

    def memory(self) -> dict:
        """Memory figures the runtime can measure (bytes); empty when it cannot."""
        ...

    def reset_peak_memory(self) -> None: ...

    def release_cache(self) -> None: ...


def create_engine(spec: str) -> TTSEngine:
    """Instantiate an engine from a "module:Class" path (catalog.ModelSpec.engine)."""
    module_name, _, class_name = spec.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)()
