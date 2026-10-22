"""Qwen3-TTS Base voice cloning with PyTorch (the official qwen-tts package).

Used where MLX does not exist (Windows): on an NVIDIA GPU through CUDA when there is one,
otherwise on the CPU, which works but is far slower than real time.
"""

from __future__ import annotations

import json
import os
from importlib import metadata
from pathlib import Path

import numpy as np

from ..errors import EngineError
from .engine import ChunkRequest, EngineInfo


class TorchQwen3TTSEngine:
    name = "qwen-tts/pytorch"

    def __init__(self) -> None:
        self._model = None
        self._device = "cpu"
        self._sample_rate = 24_000
        # The encoded reference is reused for every chunk cloned from the same clip.
        self._prompt_key: tuple[str, str] | None = None
        self._prompt = None

    def load(self, model_dir: Path) -> EngineInfo:
        try:
            import torch
            from qwen_tts import Qwen3TTSModel
        except ImportError as exc:
            raise EngineError(
                "engine_unavailable",
                "The PyTorch runtime is not installed. Reinstall Voice Studio.",
                details=str(exc),
            ) from exc

        config = json.loads((model_dir / "config.json").read_text())
        if config.get("tts_model_type", "base") != "base":
            raise EngineError(
                "wrong_checkpoint",
                f"This is a Qwen3-TTS {config.get('tts_model_type')} checkpoint. Voice cloning needs a Base checkpoint.",
            )
        force_cpu = os.environ.get("VOICE_STUDIO_DEVICE") == "cpu"
        if torch.cuda.is_available() and not force_cpu:
            self._device = "cuda:0"
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        else:
            self._device = "cpu"
            dtype = torch.float32  # half precision is slow or unsupported on most CPUs
        self._model = Qwen3TTSModel.from_pretrained(
            str(model_dir), device_map=self._device, dtype=dtype
        )
        languages = [
            lang for lang in (self._model.get_supported_languages() or []) if lang != "auto"
        ]
        return EngineInfo(
            engine=self.name,
            model_dir=str(model_dir),
            sample_rate=self._sample_rate,
            languages=languages,
            details={
                "qwen_tts": metadata.version("qwen-tts"),
                "torch": torch.__version__,
                "device": torch.cuda.get_device_name(0) if self._device != "cpu" else "cpu",
            },
        )

    def synthesize(self, request: ChunkRequest) -> np.ndarray:
        if self._model is None:
            raise EngineError("model_not_loaded", "No model is loaded.")
        if not request.reference.transcript.strip():
            raise EngineError(
                "missing_transcript", "The reference recording needs its exact transcript."
            )
        import torch

        if request.seed is not None:
            torch.manual_seed(request.seed)
        key = (request.reference.audio_path, request.reference.transcript)
        if self._prompt_key != key:
            self._prompt = self._model.create_voice_clone_prompt(
                ref_audio=request.reference.audio_path, ref_text=request.reference.transcript
            )
            self._prompt_key = key
        sampling = {
            k: v
            for k, v in (("temperature", request.temperature), ("top_p", request.top_p))
            if v is not None
        }
        wavs, sample_rate = self._model.generate_voice_clone(
            text=request.text,
            language=request.language,
            voice_clone_prompt=self._prompt,
            **sampling,
        )
        if not wavs or len(wavs[0]) == 0:
            raise EngineError("empty_output", "The model returned no audio for this text.")
        self._sample_rate = int(sample_rate)
        return np.asarray(wavs[0], dtype=np.float32).reshape(-1)

    def memory(self) -> dict:
        try:
            import torch

            if torch.cuda.is_available():
                return {
                    "gpu_active_bytes": torch.cuda.memory_allocated(),
                    "gpu_peak_bytes": torch.cuda.max_memory_allocated(),
                    "gpu_cache_bytes": torch.cuda.memory_reserved(),
                }
        except Exception:  # noqa: BLE001 - memory figures are informational
            pass
        return {}

    def reset_peak_memory(self) -> None:
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
        except Exception:  # noqa: BLE001
            pass

    def release_cache(self) -> None:
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
