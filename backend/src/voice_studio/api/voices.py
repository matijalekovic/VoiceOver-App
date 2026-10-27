from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse

from .. import schemas
from ..clips import demo_script
from ..errors import StudioError
from ..generations import GenerationService
from ..studio import Studio
from ..voices import VoiceService
from .deps import discard, get_studio, save_upload

router = APIRouter(prefix="/api/voices", tags=["voices"])


def _resolve_language(language: str | None, fallback: str) -> str:
    return (language or fallback).lower()


def _model_for(studio: Studio, mode: str, requested: str | None) -> str:
    """The checkpoint this voice needs, failing at submit time rather than inside the job."""
    model_id = requested or studio.models.default_model_for(mode, studio.pref("default_model_id"))
    spec = studio.models.spec_for_mode(mode, model_id)
    if not studio.models.is_installed(model_id):
        raise StudioError(
            "model_not_installed",
            f"{spec.label} is not installed. Pick an installed model or download it in Settings → Models.",
        )
    return model_id


@router.get("", response_model=list[schemas.Voice])
def list_voices(studio: Studio = Depends(get_studio)):
    return VoiceService(studio).list()


@router.post("", response_model=schemas.Voice, status_code=201)
def create_voice(body: schemas.VoiceCreate, studio: Studio = Depends(get_studio)):
    return VoiceService(studio).create(
        body.name,
        body.description,
        body.language.lower(),
        body.consent.model_dump() if body.consent else None,
        mode=body.mode,
        instructions=body.instructions,
    )


@router.post("/import", response_model=schemas.Voice, status_code=201)
def import_voice(file: UploadFile = File(...), studio: Studio = Depends(get_studio)):
    path = save_upload(studio, file)
    try:
        return VoiceService(studio).import_zip(path)
    finally:
        discard(path)


@router.get("/{voice_id}", response_model=schemas.Voice)
def get_voice(voice_id: str, studio: Studio = Depends(get_studio)):
    return VoiceService(studio).get(voice_id)


@router.patch("/{voice_id}", response_model=schemas.Voice)
def update_voice(voice_id: str, body: schemas.VoiceUpdate, studio: Studio = Depends(get_studio)):
    return VoiceService(studio).update(voice_id, body.model_dump(exclude_unset=True))


@router.delete("/{voice_id}", status_code=204)
def delete_voice(
    voice_id: str, delete_generations: bool = False, studio: Studio = Depends(get_studio)
):
    VoiceService(studio).delete(voice_id, delete_generations)


@router.post("/{voice_id}/references", response_model=schemas.Reference, status_code=201)
def upload_reference(
    voice_id: str,
    file: UploadFile = File(...),
    transcript: str = Form(""),
    language: str | None = Form(None),
    studio: Studio = Depends(get_studio),
):
    if len(transcript) > 5000:
        raise StudioError("transcript_too_long", "The transcript is limited to 5000 characters.")
    path = save_upload(studio, file)
    try:
        return VoiceService(studio).add_reference(
            voice_id,
            path,
            file.filename or "recording.wav",
            transcript,
            language.lower() if language else None,
        )
    finally:
        discard(path)


@router.patch("/{voice_id}/references/{ref_id}", response_model=schemas.Reference)
def update_reference(
    voice_id: str, ref_id: str, body: schemas.ReferenceUpdate, studio: Studio = Depends(get_studio)
):
    return VoiceService(studio).update_reference(
        voice_id, ref_id, body.model_dump(exclude_unset=True)
    )


@router.delete("/{voice_id}/references/{ref_id}", status_code=204)
def delete_reference(voice_id: str, ref_id: str, studio: Studio = Depends(get_studio)):
    VoiceService(studio).delete_reference(voice_id, ref_id)


@router.get("/{voice_id}/references/{ref_id}/audio")
def reference_audio(
    voice_id: str,
    ref_id: str,
    which: Literal["reference", "source"] = "reference",
    studio: Studio = Depends(get_studio),
):
    path = VoiceService(studio).reference_audio_path(voice_id, ref_id, which)
    return FileResponse(path, media_type="audio/wav")


@router.post("/{voice_id}/test", response_model=schemas.JobRef, status_code=202)
def test_voice(voice_id: str, body: schemas.VoiceTest, studio: Studio = Depends(get_studio)):
    service = VoiceService(studio)
    voice = service.get(voice_id)
    origin = {"voice_id": voice_id}
    if voice["mode"] == "clone":
        language = _resolve_language(body.language, voice["language"])
        clone = service.clone_reference(
            voice_id, body.reference_id, language=language, tone=body.tone
        )
        origin["reference_id"] = clone["reference_id"]
    model_id = _model_for(studio, voice["mode"], body.model_id)
    job = studio.jobs.submit(
        "voice_test",
        {
            "text": body.text,
            **origin,
            "language": _resolve_language(body.language, voice["language"]),
            "model_id": model_id,
            "style": body.style.model_dump() if body.style else None,
            "tone": body.tone,
        },
        voice_id=voice_id,
    )
    return {"job_id": job["id"], "status": job["status"]}


@router.post("/{voice_id}/languages", response_model=schemas.JobRef, status_code=202)
def add_language(voice_id: str, body: schemas.LanguageAdd, studio: Studio = Depends(get_studio)):
    """Make (or refresh) a cloned voice's profile for another language: candidate takes spoken
    natively from the voice fingerprint, each scored against the real recordings, the closest
    chosen as the take generations in the language continue from. Posting again for a language
    that has a profile voices a new round of takes."""
    service = VoiceService(studio)
    voice = service.get(voice_id)
    if voice["mode"] != "clone":
        raise StudioError(
            "wrong_voice_mode", "A designed voice already speaks every language it supports."
        )
    language = body.language.lower()
    if language == voice["language"].lower():
        raise StudioError(
            "same_language", "That is the language of the recording; the voice already speaks it."
        )
    service.identity_audio(voice)  # fails early for a voice without recordings
    model_id = _model_for(studio, voice["mode"], body.model_id)
    service.ensure_language(voice_id, language, body.accent)
    job = studio.jobs.submit(
        "language_takes",
        {"voice_id": voice_id, "language": language, "model_id": model_id},
        voice_id=voice_id,
    )
    return {"job_id": job["id"], "status": job["status"]}


@router.patch("/{voice_id}/languages/{language}", response_model=schemas.LanguageVersion)
def update_language(
    voice_id: str, language: str, body: schemas.LanguageUpdate, studio: Studio = Depends(get_studio)
):
    return VoiceService(studio).update_language(
        voice_id, language, body.model_dump(exclude_unset=True)
    )


@router.delete("/{voice_id}/languages/{language}", status_code=204)
def delete_language(voice_id: str, language: str, studio: Studio = Depends(get_studio)):
    VoiceService(studio).delete_language_version(voice_id, language)


@router.post("/{voice_id}/export", response_model=schemas.ExportResult)
def export_voice(voice_id: str, studio: Studio = Depends(get_studio)):
    folder = GenerationService(studio).output_dir() / "Voices"
    path = VoiceService(studio).export_zip(voice_id, folder)
    return {"paths": [str(path)], "folder": str(folder)}


@router.post("/{voice_id}/create", response_model=schemas.JobRef, status_code=202)
def build_voice(voice_id: str, body: schemas.VoiceBuild, studio: Studio = Depends(get_studio)):
    """Clone: transcribe the recordings, cut clips and voice a demo with each.
    Design: voice three takes from the description for the user to compare."""
    voice = VoiceService(studio).get(voice_id)
    if voice["mode"] == "design":
        if not voice["instructions"].strip():
            raise StudioError("instructions_required", "Describe the voice before creating it.")
    elif not voice["references"]:
        raise StudioError("reference_required", "Add at least one recording first.")
    model_id = _model_for(studio, voice["mode"], body.model_id)
    job = studio.jobs.submit(
        "voice_create",
        {
            "voice_id": voice_id,
            "model_id": model_id,
            "language": _resolve_language(body.language, voice["language"]),
            "text": body.text,
            "seed": body.seed,
        },
        voice_id=voice_id,
    )
    return {"job_id": job["id"], "status": job["status"]}


@router.get("/{voice_id}/clips/{clip_id}/audio")
def clip_audio(voice_id: str, clip_id: str, studio: Studio = Depends(get_studio)):
    return FileResponse(
        VoiceService(studio).clip_audio_path(voice_id, clip_id), media_type="audio/wav"
    )


@router.patch("/{voice_id}/clips/{clip_id}", response_model=schemas.Clip)
def update_clip(
    voice_id: str, clip_id: str, body: schemas.ClipUpdate, studio: Studio = Depends(get_studio)
):
    return VoiceService(studio).update_clip(voice_id, clip_id, body.model_dump(exclude_unset=True))


@router.post("/{voice_id}/clips/{clip_id}/demo", response_model=schemas.JobRef, status_code=202)
def clip_demo(
    voice_id: str, clip_id: str, body: schemas.VoiceBuild, studio: Studio = Depends(get_studio)
):
    """Voice the demo again with this clip (after its transcript was corrected)."""
    service = VoiceService(studio)
    voice = service.get(voice_id)
    service.clip_row(voice_id, clip_id)
    model_id = _model_for(studio, "clone", body.model_id)
    language = _resolve_language(body.language, voice["language"])
    job = studio.jobs.submit(
        "voice_test",
        {
            "text": body.text or demo_script(language),
            "voice_id": voice_id,
            "reference_id": clip_id,
            "clip_id": clip_id,
            "language": language,
            "model_id": model_id,
            "seed": body.seed,
        },
        voice_id=voice_id,
    )
    return {"job_id": job["id"], "status": job["status"]}


@router.post("/{voice_id}/clips/{clip_id}/choose", response_model=schemas.Voice)
def choose_clip(voice_id: str, clip_id: str, studio: Studio = Depends(get_studio)):
    return VoiceService(studio).choose_clip(voice_id, clip_id)


@router.post("/{voice_id}/sample", response_model=schemas.Voice)
def choose_sample(voice_id: str, body: schemas.SampleChoice, studio: Studio = Depends(get_studio)):
    """Save a designed voice with the take the user picked as its preview."""
    return VoiceService(studio).choose_sample(voice_id, body.generation_id)
