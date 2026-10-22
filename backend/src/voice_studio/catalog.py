"""Checkpoints the app knows how to install and run.

Two kinds of voice checkpoint are listed. Qwen3-TTS *Base* checkpoints clone a voice from
reference audio; Qwen3-TTS *VoiceDesign* checkpoints create a new synthetic voice from a
written description. CustomVoice checkpoints are rejected when a folder is validated (see
models.validate_model_dir): they need a preset speaker and do not clone. One speech-to-text
checkpoint (kind "stt") transcribes recordings so clips can be cut on word boundaries.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .platform import USES_MLX

MLX_QWEN3_ENGINE = "voice_studio.worker.mlx_qwen3:MlxQwen3TTSEngine"
TORCH_QWEN3_ENGINE = "voice_studio.worker.torch_qwen3:TorchQwen3TTSEngine"

# Whisper's language codes for the same languages.
WHISPER_LANGUAGES: dict[str, str] = {
    "english": "en",
    "french": "fr",
    "spanish": "es",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
}

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
    tier: str  # "quality", "lightweight", "design" or "speech recognition"
    parameters: str
    quantization: str
    approx_download_gb: float
    approx_memory_gb: float  # planning figure, replaced by measurements after validation
    engine: str
    notes: str = ""
    kind: str = "tts"  # "tts" generates speech; "stt" transcribes recordings
    # How a voice checkpoint reaches a voice: "clone" from reference audio, or "design"
    # a new voice from a written description.
    capability: str = "clone"

    def to_dict(self) -> dict:
        return asdict(self)


# Apple Silicon: MLX conversions of the checkpoints, run on the Apple GPU.
MLX_CATALOG: list[ModelSpec] = [
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
    ModelSpec(
        id="qwen3-tts-1.7b-voice-design-bf16",
        label="Qwen3-TTS 1.7B Voice Design",
        repo_id="mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16",
        tier="design",
        parameters="1.7B",
        quantization="bf16",
        approx_download_gb=4.5,
        approx_memory_gb=6.0,
        engine=MLX_QWEN3_ENGINE,
        notes="Creates a new synthetic voice from a written description. Cannot clone recordings.",
        capability="design",
    ),
    ModelSpec(
        id="whisper-large-v3-turbo",
        label="Whisper large-v3 turbo",
        repo_id="mlx-community/whisper-large-v3-turbo-asr-fp16",
        tier="speech recognition",
        parameters="0.8B",
        quantization="fp16",
        approx_download_gb=1.6,
        approx_memory_gb=2.0,
        engine="voice_studio.worker.whisper:MlxWhisperTranscriber",
        notes="Transcribes recordings when you create a voice.",
        kind="stt",
    ),
]

# Windows (and other PCs): the original PyTorch checkpoints, on an NVIDIA GPU when there is
# one. The ids match the Mac ones, so settings and projects mean the same on both.
TORCH_CATALOG: list[ModelSpec] = [
    ModelSpec(
        id="qwen3-tts-1.7b-base-bf16",
        label="Qwen3-TTS 1.7B Base",
        repo_id="Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        tier="quality",
        parameters="1.7B",
        quantization="bf16",
        approx_download_gb=4.5,
        approx_memory_gb=6.0,
        engine=TORCH_QWEN3_ENGINE,
        notes="Primary quality mode. Needs an NVIDIA GPU with 8 GB or more to run quickly.",
    ),
    ModelSpec(
        id="qwen3-tts-0.6b-base-bf16",
        label="Qwen3-TTS 0.6B Base",
        repo_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        tier="lightweight",
        parameters="0.6B",
        quantization="bf16",
        approx_download_gb=2.5,
        approx_memory_gb=3.5,
        engine=TORCH_QWEN3_ENGINE,
        notes="Lightweight mode for smaller GPUs, and the better choice without one.",
    ),
    ModelSpec(
        id="qwen3-tts-1.7b-voice-design-bf16",
        label="Qwen3-TTS 1.7B Voice Design",
        repo_id="Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        tier="design",
        parameters="1.7B",
        quantization="bf16",
        approx_download_gb=4.5,
        approx_memory_gb=6.0,
        engine=TORCH_QWEN3_ENGINE,
        notes="Creates a new synthetic voice from a written description. Cannot clone recordings.",
        capability="design",
    ),
    ModelSpec(
        id="whisper-large-v3-turbo",
        label="Whisper large-v3 turbo",
        repo_id="mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        tier="speech recognition",
        parameters="0.8B",
        quantization="fp16",
        approx_download_gb=1.6,
        approx_memory_gb=2.0,
        engine="voice_studio.worker.faster_whisper:FasterWhisperTranscriber",
        notes="Transcribes recordings when you create a voice.",
        kind="stt",
    ),
]

CATALOG: list[ModelSpec] = MLX_CATALOG if USES_MLX else TORCH_CATALOG

DEFAULT_MODEL_ID = CATALOG[0].id
STT_MODEL_ID = "whisper-large-v3-turbo"
DESIGN_MODEL_ID = "qwen3-tts-1.7b-voice-design-bf16"


def get_spec(model_id: str, catalog: list[ModelSpec] | None = None) -> ModelSpec | None:
    for spec in catalog if catalog is not None else CATALOG:
        if spec.id == model_id:
            return spec
    return None


def design_spec(catalog: list[ModelSpec] | None = None) -> ModelSpec | None:
    """The checkpoint that designs voices from a description, if the catalog has one."""
    return next(
        (
            spec
            for spec in (catalog if catalog is not None else CATALOG)
            if spec.capability == "design"
        ),
        None,
    )
