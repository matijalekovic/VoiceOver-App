from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .. import schemas
from ..errors import StudioError
from ..studio import Studio
from ..voices import VoiceService
from .deps import discard, get_studio, save_upload

router = APIRouter(prefix="/api/voices", tags=["voices"])


def _resolve_language(language: str | None, fallback: str) -> str:
    return (language or fallback).lower()


@router.get("", response_model=list[schemas.Voice])
def list_voices(studio: Studio = Depends(get_studio)):
    return VoiceService(studio).list()


@router.post("", response_model=schemas.Voice, status_code=201)
def create_voice(body: schemas.VoiceCreate, studio: Studio = Depends(get_studio)):
    return VoiceService(studio).create(
        body.name, body.description, body.language.lower(), body.consent.model_dump()
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
    clone = service.clone_reference(voice_id, body.reference_id)
    model_id = body.model_id or studio.pref("default_model_id")
    studio.models.spec(model_id)
    job = studio.jobs.submit(
        "voice_test",
        {
            "text": body.text,
            "voice_id": voice_id,
            "reference_id": clone["reference_id"],
            "language": _resolve_language(body.language, voice["language"]),
            "model_id": model_id,
        },
        voice_id=voice_id,
    )
    return {"job_id": job["id"], "status": job["status"]}


@router.post("/{voice_id}/export")
def export_voice(voice_id: str, studio: Studio = Depends(get_studio)):
    path = VoiceService(studio).export_zip(voice_id)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        background=BackgroundTask(discard, path),
    )
