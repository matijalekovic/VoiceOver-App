"""Qwen3-TTS with PyTorch (the official qwen-tts package): Base checkpoints clone a voice from
a reference recording; Voice Design checkpoints create a new voice from a written description.

Used where MLX does not exist (Windows): on an NVIDIA GPU through CUDA when there is one,
otherwise on the CPU, which works but is far slower than real time.
"""

from __future__ import annotations

import contextlib
import json
import os
from importlib import metadata
from pathlib import Path

import numpy as np

from ..errors import EngineError
from .engine import ChunkRequest, EngineInfo

MODEL_TYPES = ("base", "voice_design")


class TorchQwen3TTSEngine:
    name = "qwen-tts/pytorch"

    def __init__(self) -> None:
        self._model = None
        self._model_type = "base"
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
        model_type = config.get("tts_model_type", "base")
        if model_type not in MODEL_TYPES:
            raise EngineError(
                "wrong_checkpoint",
                f"This is a Qwen3-TTS {model_type} checkpoint. Voice Studio needs a Base "
                "(voice cloning) or Voice Design (voice from a description) checkpoint.",
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
        self._model_type = model_type
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
                "model_type": model_type,
            },
        )

    def synthesize(self, request: ChunkRequest) -> np.ndarray:
        if self._model is None:
            raise EngineError("model_not_loaded", "No model is loaded.")
        import torch

        if request.seed is not None:
            torch.manual_seed(request.seed)
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
            wavs, sample_rate = self._model.generate_voice_design(
                text=request.text, instruct=instructions, language=request.language, **sampling
            )
        else:
            reference = request.reference
            if reference is None:
                raise EngineError(
                    "reference_required",
                    "This is a Base checkpoint; it needs a reference recording to clone.",
                )
            tone = (request.instructions or "").strip() or None
            fingerprint = reference.fingerprint_only
            if not fingerprint and not reference.transcript.strip():
                raise EngineError(
                    "missing_transcript", "The reference recording needs its exact transcript."
                )
            if tone and not fingerprint:
                raise EngineError(
                    "tone_needs_fingerprint", "Tone instructions need fingerprint-only cloning."
                )
            # x_vector_only_mode clones from the speaker fingerprint, not by continuing the
            # recording, so the voice can speak other languages without the recording's accent.
            key = (reference.audio_path, reference.transcript, fingerprint)
            if self._prompt_key != key:
                self._prompt = self._model.create_voice_clone_prompt(
                    ref_audio=reference.audio_path,
                    ref_text=None if fingerprint else reference.transcript,
                    x_vector_only_mode=fingerprint,
                )
                self._prompt_key = key
            with self._tone(tone):
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

    @contextlib.contextmanager
    def _tone(self, tone: str | None):
        """qwen-tts's clone call does not forward an instruction, though the model's generate
        takes one and the Base model responds to it in fingerprint mode. Pass it in for the
        duration of one generation."""
        if not tone:
            yield
            return
        wrapper = self._model
        instruct = wrapper._tokenize_texts([wrapper._build_instruct_text(tone)])[0]
        original = wrapper.model.generate

        def with_tone(*args, **kwargs):
            kwargs["instruct_ids"] = [instruct] * len(kwargs.get("input_ids") or [None])
            return original(*args, **kwargs)

        wrapper.model.generate = with_tone
        try:
            yield
        finally:
            del wrapper.model.generate  # back to the class method

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
