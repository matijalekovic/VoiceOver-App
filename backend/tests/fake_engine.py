"""A stand-in engine for tests only. It is never in the product catalog.

It produces tones whose length depends on the text, so the queue, worker process,
assembly and export paths can be exercised on machines without Apple Silicon.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

from voice_studio.worker.engine import ChunkRequest, EngineInfo


class FakeEngine:
    def load(self, model_dir: Path) -> EngineInfo:
        config = json.loads((model_dir / "config.json").read_text())
        self.delay = float(os.environ.get("FAKE_ENGINE_DELAY", "0"))
        return EngineInfo(
            engine="fake",
            model_dir=str(model_dir),
            sample_rate=24_000,
            languages=config.get("languages", ["english", "french", "spanish"]),
        )

    def synthesize(self, request: ChunkRequest) -> np.ndarray:
        if "CRASH" in request.text:
            os._exit(9)  # simulates the OS killing the worker (e.g. out of memory)
        if self.delay:
            time.sleep(self.delay)
        seconds = 0.2 + 0.02 * len(request.text)
        t = np.arange(int(24_000 * seconds)) / 24_000
        tone = 0.3 * np.sin(2 * np.pi * 220 * t).astype(np.float32)
        silence = np.zeros(2400, dtype=np.float32)
        return np.concatenate([silence, tone, silence])

    def memory(self) -> dict:
        return {"gpu_peak_bytes": 0}

    def reset_peak_memory(self) -> None:
        pass

    def release_cache(self) -> None:
        pass
