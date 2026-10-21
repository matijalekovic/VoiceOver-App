"""Speech-to-text with Whisper through mlx-audio, used to transcribe reference recordings.

The word timings let the app cut clips from long recordings without splitting a word, and
give each clip the exact transcript the cloning model needs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import EngineError


class MlxWhisperTranscriber:
    def transcribe(self, model_dir: Path, audio_path: Path, language: str | None) -> list[dict]:
        """Segments as [{start, end, text, words: [{start, end, word, probability}]}]."""
        try:
            import mlx.core as mx
            from mlx_audio.stt.utils import load_model
        except ImportError as exc:
            raise EngineError(
                "engine_unavailable",
                "The MLX runtime is not installed. Voice Studio needs a Mac with Apple Silicon.",
                details=str(exc),
            ) from exc
        model = load_model(model_dir)
        try:
            output = model.generate(
                str(audio_path),
                language=language,
                word_timestamps=True,
                condition_on_previous_text=False,  # fewer runaway repetitions on long audio
                verbose=False,
            )
        finally:
            del model
            mx.clear_cache()
        return [_segment(s) for s in output.segments or [] if str(s.get("text", "")).strip()]


def _segment(raw: dict[str, Any]) -> dict[str, Any]:
    words = [
        {
            "start": round(float(w["start"]), 3),
            "end": round(float(w["end"]), 3),
            "word": str(w["word"]),
            "probability": round(float(w.get("probability", 1.0)), 3),
        }
        for w in raw.get("words") or []
    ]
    return {
        "start": round(float(raw["start"]), 3),
        "end": round(float(raw["end"]), 3),
        "text": str(raw["text"]).strip(),
        "words": words,
    }
