"""Checkpoints the app knows how to install and run.

Only Qwen3-TTS *Base* checkpoints are listed: they are the ones that clone from reference
audio. CustomVoice and VoiceDesign checkpoints use a different generation path and are
rejected when a folder is validated (see models.validate_model_dir).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

MLX_QWEN3_ENGINE = "voice_studio.worker.mlx_qwen3:MlxQwen3TTSEngine"

# Qwen3-TTS language names as the checkpoint's codec_language_id spells them.
QWEN3_LANGUAGES: dict[str, str] = {
    "english": "English",
    "french": "French",
    "spanish": "Spanish",
    "german": "German",
    "italian": "Italian",
    "portuguese": "Portuguese",
    "russian": "Russian",
    "chinese": "Chinese",
    "japanese": "Japanese",
    "korean": "Korean",
}


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    repo_id: str
    tier: str  # "quality" or "lightweight"
    parameters: str
    quantization: str
    approx_download_gb: float
    approx_memory_gb: float  # planning figure, replaced by measurements after validation
    engine: str
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


CATALOG: list[ModelSpec] = [
    ModelSpec(
        id="qwen3-tts-1.7b-base-bf16",
        label="Qwen3-TTS 1.7B Base",
        repo_id="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16",
        tier="quality",
        parameters="1.7B",
        quantization="bf16",
        approx_download_gb=4.5,
        approx_memory_gb=6.0,
        engine=MLX_QWEN3_ENGINE,
        notes="Primary quality mode.",
    ),
    ModelSpec(
        id="qwen3-tts-1.7b-base-8bit",
        label="Qwen3-TTS 1.7B Base (8-bit)",
        repo_id="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
        tier="quality",
        parameters="1.7B",
        quantization="8-bit",
        approx_download_gb=2.5,
        approx_memory_gb=4.0,
        engine=MLX_QWEN3_ENGINE,
        notes="Smaller and lighter. Use only after comparing it with bf16 on your own voices.",
    ),
    ModelSpec(
        id="qwen3-tts-0.6b-base-bf16",
        label="Qwen3-TTS 0.6B Base",
        repo_id="mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
        tier="lightweight",
        parameters="0.6B",
        quantization="bf16",
        approx_download_gb=2.0,
        approx_memory_gb=3.5,
        engine=MLX_QWEN3_ENGINE,
        notes="Lightweight mode for lower memory use.",
    ),
]

DEFAULT_MODEL_ID = CATALOG[0].id


def get_spec(model_id: str, catalog: list[ModelSpec] | None = None) -> ModelSpec | None:
    for spec in catalog if catalog is not None else CATALOG:
        if spec.id == model_id:
            return spec
    return None
