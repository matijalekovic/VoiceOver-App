"""A stand-in engine for tests only. It is never in the product catalog.

It produces tones whose length depends on the text, so the queue, worker process,
assembly and export paths can be exercised on machines without Apple Silicon.
"""

from __future__ import annotations

import json
import os
import signal
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
            # What macOS does to a process using too much memory. Windows has no SIGKILL;
            # os.kill there always ends the process with TerminateProcess.
            os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))
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


class FakeTranscriber:
    """Pretends every 4 seconds of a recording is one spoken sentence."""

    def transcribe(self, model_dir: Path, audio_path: Path, language: str | None) -> list[dict]:
        import soundfile as sf

        info = sf.info(str(audio_path))
        duration = info.frames / info.samplerate
        segments = []
        start = 0.5
        while start + 3.5 <= duration:
            end = start + 3.5
            text = f"Sentence at {start:.1f}."
            tokens = text.split()
            words = [
                {
                    "start": start + k * 3.5 / len(tokens),
                    "end": start + (k + 0.9) * 3.5 / len(tokens),
                    "word": (" " if k else "") + token,
                    "probability": 0.9,
                }
                for k, token in enumerate(tokens)
            ]
            segments.append({"start": start, "end": end, "text": text, "words": words})
            start += 4.0
        return segments
