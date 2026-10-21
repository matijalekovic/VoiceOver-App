"""Typed request and response bodies for the local API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

JobStatus = Literal[
    "queued", "loading", "synthesizing", "processing", "completed", "failed", "cancelled"
]
ExportFormat = Literal["wav", "mp3"]


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


# -- voices ---------------------------------------------------------------
class Consent(Model):
    confirmed: bool = Field(
        description="The speaker authorised cloning their voice for the stated uses."
    )
    speaker: str = Field(min_length=1, max_length=200)
    scope: str = Field(
        min_length=1, max_length=2000, description="Intended uses the speaker agreed to."
    )
    notes: str = Field(default="", max_length=4000)

    @field_validator("confirmed")
    @classmethod
    def must_confirm(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Cloning requires the speaker's permission.")
        return value


class VoiceCreate(Model):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    language: str
    consent: Consent


class VoiceUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    language: str | None = None
    status: Literal["draft", "ready"] | None = None
    primary_reference_id: str | None = None
    preferred_sample_generation_id: str | None = None
    consent: Consent | None = None


class QualityFlag(Model):
    code: str
    severity: Literal["warning", "error"]
    message: str


class Quality(Model):
    duration_s: float
    peak_dbfs: float
    speech_level_dbfs: float
    noise_floor_dbfs: float
    snr_db: float
    clipping_ratio: float
    flags: list[QualityFlag]


class Reference(Model):
    id: str
    voice_id: str
    original_filename: str
    transcript: str
    language: str
    duration_s: float
    source_duration_s: float
    trim_start_s: float
    trim_end_s: float
    quality: Quality
    source_quality: Quality | None = None
    segments: list[dict[str, Any]] | None = None  # Whisper's timed transcript, once transcribed
    created_at: str
    updated_at: str


class Clip(Model):
    """A candidate reference cut from a recording; the chosen one is what the voice clones."""

    id: str
    voice_id: str
    reference_id: str
    start_s: float
    end_s: float
    transcript: str
    quality: Quality
    score: float
    demo_generation_id: str | None
    created_at: str


class ClipUpdate(Model):
    transcript: str = Field(min_length=1, max_length=2000)


class VoiceBuild(Model):
    model_id: str | None = None
    language: str | None = None
    text: str | None = Field(default=None, max_length=1000)  # demo script; a preset when empty
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)


class ReferenceUpdate(Model):
    transcript: str | None = Field(default=None, max_length=5000)
    language: str | None = None
    trim_start_s: float | None = Field(default=None, ge=0)
    trim_end_s: float | None = Field(default=None, gt=0)


class Voice(Model):
    id: str
    name: str
    description: str
    language: str
    status: Literal["draft", "ready"]
    primary_reference_id: str | None
    preferred_sample_generation_id: str | None
    clip_id: str | None = None
    consent: dict[str, Any]
    created_at: str
    updated_at: str
    references: list[Reference] = []
    clips: list[Clip] = []
    generation_count: int = 0


class VoiceTest(Model):
    text: str = Field(min_length=1, max_length=1000)
    language: str | None = None
    reference_id: str | None = None
    model_id: str | None = None


# -- generation and jobs --------------------------------------------------
class GenerateRequest(Model):
    text: str = Field(min_length=1)
    voice_id: str
    language: str
    model_id: str | None = None
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)


class Job(Model):
    id: str
    kind: str
    status: JobStatus
    progress: dict[str, Any]
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    cancel_requested: bool
    voice_id: str | None
    project_id: str | None
    segment_id: str | None
    generation_id: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    queue_position: int | None = None


class JobRef(Model):
    job_id: str
    status: JobStatus


class Generation(Model):
    id: str
    kind: Literal["tts", "voice_test", "segment"]
    voice_id: str | None
    voice_name: str
    reference_id: str | None
    project_id: str | None
    segment_id: str | None
    text: str
    language: str
    model_id: str
    params: dict[str, Any]
    duration_s: float
    sample_rate: int
    stats: dict[str, Any]
    created_at: str


class GenerationPage(Model):
    items: list[Generation]
    total: int


class ExportRequest(Model):
    format: ExportFormat = "wav"
    bitrate: Literal[192, 320] = 320
    sample_rate: Literal[24000, 44100, 48000] | None = None


class ExportResult(Model):
    paths: list[str]
    folder: str


# -- drafts ---------------------------------------------------------------
class DraftIn(Model):
    title: str = Field(default="Untitled draft", max_length=200)
    text: str = Field(default="", max_length=200_000)
    voice_id: str | None = None
    language: str | None = None


class Draft(DraftIn):
    id: str
    created_at: str
    updated_at: str


# -- projects -------------------------------------------------------------
class ProjectCreate(Model):
    name: str = Field(min_length=1, max_length=200)
    script: str = ""
    voice_id: str | None = None
    language: str = "english"
    model_id: str | None = None
    segmentation: Literal["sentence", "paragraph"] = "paragraph"


class ProjectUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    voice_id: str | None = None
    language: str | None = None
    model_id: str | None = None
    default_pause_ms: int | None = Field(default=None, ge=0, le=10_000)
    paragraph_pause_ms: int | None = Field(default=None, ge=0, le=10_000)


class Resegment(Model):
    script: str
    segmentation: Literal["sentence", "paragraph"] = "paragraph"


class SegmentCreate(Model):
    text: str = Field(min_length=1)
    after_segment_id: str | None = None
    pause_after_ms: int | None = Field(default=None, ge=0, le=10_000)


class SegmentUpdate(Model):
    text: str | None = Field(default=None, min_length=1)
    pause_after_ms: int | None = Field(default=None, ge=0, le=10_000)
    active_generation_id: str | None = None


class Reorder(Model):
    segment_ids: list[str]


class Take(Model):
    id: str
    text: str
    duration_s: float
    created_at: str
    model_id: str
    voice_name: str


class Segment(Model):
    id: str
    project_id: str
    position: int
    text: str
    pause_after_ms: int
    active_generation_id: str | None
    active_take_stale: bool
    takes: list[Take]
    job: Job | None
    created_at: str
    updated_at: str


class Project(Model):
    id: str
    name: str
    script: str
    voice_id: str | None
    language: str
    model_id: str
    default_pause_ms: int
    paragraph_pause_ms: int
    created_at: str
    updated_at: str
    segments: list[Segment] = []
    segment_count: int = 0
    generated_count: int = 0
    duration_s: float = 0.0


class ProjectGenerate(Model):
    segment_ids: list[str] | None = None
    only_missing: bool = True


class ProjectExport(ExportRequest):
    mode: Literal["combined", "segments", "both"] = "combined"


# -- models, settings, system ---------------------------------------------
class ModelAction(Model):
    model_id: str


class UnloadRequest(Model):
    force: bool = False


class Preferences(Model):
    default_model_id: str | None = None
    output_dir: str | None = None
    idle_unload_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    unload_on_memory_pressure: bool | None = None
    enabled_languages: list[str] | None = None
    language_notes: dict[str, dict[str, str]] | None = None
    max_chunk_chars: int | None = Field(default=None, ge=80, le=1500)
    sentence_pause_ms: int | None = Field(default=None, ge=0, le=5000)
    paragraph_pause_ms: int | None = Field(default=None, ge=0, le=5000)
    default_export_format: ExportFormat | None = None
    default_mp3_bitrate: Literal[192, 320] | None = None
    theme: Literal["system", "light", "dark"] | None = None


class RevealRequest(Model):
    path: str
