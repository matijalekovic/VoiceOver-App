"""Qwen3-TTS on Apple Silicon through mlx-audio (MLX / Metal).

Two checkpoint types run here:

- Base checkpoints clone a voice from a reference recording and its transcript.
- Voice Design checkpoints create a new synthetic voice from a written description.
"""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

import numpy as np

from ..errors import EngineError
from .engine import ChunkRequest, EngineInfo

MODEL_TYPES = ("base", "voice_design")


class MlxQwen3TTSEngine:
    name = "mlx-audio/qwen3-tts"

    def __init__(self) -> None:
        self._model = None
        self._model_type = "base"
        self._sample_rate = 24_000

    def load(self, model_dir: Path) -> EngineInfo:
        try:
            import mlx.core as mx
            from mlx_audio.tts.utils import load_model
        except ImportError as exc:  # not Apple Silicon, or the runtime is not installed
            raise EngineError(
                "engine_unavailable",
                "The MLX runtime is not installed. Voice Studio needs a Mac with Apple Silicon.",
                details=str(exc),
            ) from exc

        config = json.loads((model_dir / "config.json").read_text())
        model_type = config.get("tts_model_type", "base")
        if model_type not in MODEL_TYPES:
            raise EngineError(
                "wrong_checkpoint",
                f"This is a Qwen3-TTS {model_type} checkpoint. Voice Studio needs a Base "
                "(voice cloning) or Voice Design (voice from a description) checkpoint.",
            )

        model = load_model(model_dir)

        # mlx-audio downgrades some loading failures to printed warnings. Every generation
        # path needs the text tokenizer, and cloning also needs the speech-tokenizer encoder,
        # so check them here.
        if getattr(model, "tokenizer", None) is None:
            raise EngineError(
                "model_incomplete", "The checkpoint's text tokenizer could not be loaded."
            )
        speech_tokenizer = getattr(model, "speech_tokenizer", None)
        if speech_tokenizer is None:
            raise EngineError(
                "model_incomplete", "The checkpoint's speech tokenizer is missing."
            )
        if model_type == "base" and not getattr(speech_tokenizer, "has_encoder", False):
            raise EngineError(
                "model_incomplete",
                "The checkpoint's speech tokenizer encoder is missing, so it cannot clone from reference audio.",
            )

        self._model = model
        self._model_type = model_type
        self._sample_rate = int(model.sample_rate)
        languages = [lang for lang in model.get_supported_languages() if lang != "auto"]
        return EngineInfo(
            engine=self.name,
            model_dir=str(model_dir),
            sample_rate=self._sample_rate,
            languages=languages,
            details={
                "mlx_audio": metadata.version("mlx-audio"),
                "mlx": mx.__version__,
                "model_type": model_type,
            },
        )

    def synthesize(self, request: ChunkRequest) -> np.ndarray:
        if self._model is None:
            raise EngineError("model_not_loaded", "No model is loaded.")
        import mlx.core as mx

        if request.seed is not None:
            mx.random.seed(request.seed)
        sampling = {
            k: v
            for k, v in (("temperature", request.temperature), ("top_p", request.top_p))
            if v is not None
        }

        if self._model_type == "voice_design":
            instructions = (request.instructions or "").strip()
            if not instructions:
                raise EngineError(
                    "missing_instructions",
                    "This voice has no description, so the Voice Design model cannot create it.",
                )
            # mlx-audio routes instruct to its voice-design path: the text becomes a new
            # voice rather than a style applied to a reference recording.
            results = list(
                self._model.generate(
                    text=request.text,
                    lang_code=request.language,
                    instruct=instructions,
                    stream=False,
                    **sampling,
                )
            )
        else:
            reference = request.reference
            if reference is None:
                raise EngineError(
                    "reference_required",
                    "This is a Base checkpoint; it needs a reference recording to clone.",
                )
            if not reference.transcript.strip():
                raise EngineError(
                    "missing_transcript", "The reference recording needs its exact transcript."
                )
            # Passing both ref_audio and ref_text selects the in-context (ICL) cloning path.
            # mlx-audio caches the encoded reference in memory, so repeated chunks with the
            # same reference only pay for the encoding once per loaded model.
            results = list(
                self._model.generate(
                    text=request.text,
                    ref_audio=reference.audio_path,
                    ref_text=reference.transcript,
                    lang_code=request.language,
                    stream=False,
                    **sampling,
                )
            )
        if not results:
            raise EngineError("empty_output", "The model returned no audio for this text.")
        audio = np.concatenate([np.asarray(r.audio, dtype=np.float32).reshape(-1) for r in results])
        return audio

    def memory(self) -> dict:
        try:
            import mlx.core as mx
        except ImportError:
            return {}
        return {
            "gpu_active_bytes": int(mx.get_active_memory()),
            "gpu_peak_bytes": int(mx.get_peak_memory()),
            "gpu_cache_bytes": int(mx.get_cache_memory()),
        }

    def reset_peak_memory(self) -> None:
        import mlx.core as mx

        mx.reset_peak_memory()

    def release_cache(self) -> None:
        import mlx.core as mx

        mx.clear_cache()
