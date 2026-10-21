from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from .. import schemas
from ..db import new_id, now_iso
from ..errors import NotFound, StudioError
from ..generations import GenerationService
from ..studio import Studio
from ..voices import VoiceService
from .deps import get_studio

router = APIRouter(prefix="/api", tags=["generation"])


@router.post("/generate", response_model=schemas.JobRef, status_code=202)
def generate(body: schemas.GenerateRequest, studio: Studio = Depends(get_studio)):
    if len(body.text) > studio.settings.max_generate_chars:
        raise StudioError(
            "text_too_long",
            f"Generate is limited to {studio.settings.max_generate_chars:,} characters. Use a project for longer scripts.",
        )
    clone = VoiceService(studio).clone_reference(body.voice_id, None)  # fail now, not in the queue
    model_id = body.model_id or studio.pref("default_model_id")
    studio.models.spec(model_id)
    job = studio.jobs.submit(
        "tts",
        {
            "text": body.text,
            "voice_id": body.voice_id,
            "reference_id": clone["reference_id"],
            "language": body.language.lower(),
            "model_id": model_id,
            "seed": body.seed,
        },
        voice_id=body.voice_id,
    )
    return {"job_id": job["id"], "status": job["status"]}


# -- jobs -----------------------------------------------------------------
@router.get("/jobs", response_model=list[schemas.Job])
def list_jobs(status: Literal["active", "all"] = "active", studio: Studio = Depends(get_studio)):
    return studio.jobs.list(None if status == "all" else "active")


@router.get("/jobs/{job_id}", response_model=schemas.Job)
def get_job(job_id: str, studio: Studio = Depends(get_studio)):
    return studio.jobs.get(job_id)


@router.post("/jobs/{job_id}/cancel", response_model=schemas.Job)
def cancel_job(job_id: str, force: bool = False, studio: Studio = Depends(get_studio)):
    return studio.jobs.cancel(job_id, force=force)


@router.post("/jobs/{job_id}/retry", response_model=schemas.Job)
def retry_job(job_id: str, studio: Studio = Depends(get_studio)):
    return studio.jobs.retry(job_id)


# -- generations (history) ----------------------------------------------------
@router.get("/generations", response_model=schemas.GenerationPage)
def list_generations(
    kind: Literal["tts", "voice_test", "segment"] | None = None,
    voice_id: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    studio: Studio = Depends(get_studio),
):
    return GenerationService(studio).page(kind, voice_id, q, limit, offset)


@router.get("/generations/{generation_id}", response_model=schemas.Generation)
def get_generation(generation_id: str, studio: Studio = Depends(get_studio)):
    return GenerationService(studio).get(generation_id)


@router.get("/generations/{generation_id}/audio")
def generation_audio(generation_id: str, studio: Studio = Depends(get_studio)):
    return FileResponse(GenerationService(studio).audio_path(generation_id), media_type="audio/wav")


@router.post("/generations/{generation_id}/export", response_model=schemas.ExportResult)
def export_generation(
    generation_id: str, body: schemas.ExportRequest, studio: Studio = Depends(get_studio)
):
    return GenerationService(studio).export(
        generation_id, body.format, body.bitrate, body.sample_rate
    )


@router.delete("/generations/{generation_id}", status_code=204)
def delete_generation(generation_id: str, studio: Studio = Depends(get_studio)):
    GenerationService(studio).delete(generation_id)


# -- drafts ---------------------------------------------------------------------
@router.get("/drafts", response_model=list[schemas.Draft])
def list_drafts(studio: Studio = Depends(get_studio)):
    return studio.db.all("SELECT * FROM drafts ORDER BY updated_at DESC")


@router.post("/drafts", response_model=schemas.Draft, status_code=201)
def create_draft(body: schemas.DraftIn, studio: Studio = Depends(get_studio)):
    draft_id, stamp = new_id(), now_iso()
    studio.db.execute(
        "INSERT INTO drafts (id, title, text, voice_id, language, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (draft_id, body.title, body.text, body.voice_id, body.language, stamp, stamp),
    )
    return studio.db.one("SELECT * FROM drafts WHERE id = ?", (draft_id,))


@router.put("/drafts/{draft_id}", response_model=schemas.Draft)
def update_draft(draft_id: str, body: schemas.DraftIn, studio: Studio = Depends(get_studio)):
    changed = studio.db.execute(
        "UPDATE drafts SET title = ?, text = ?, voice_id = ?, language = ?, updated_at = ? WHERE id = ?",
        (body.title, body.text, body.voice_id, body.language, now_iso(), draft_id),
    )
    if not changed:
        raise NotFound("Draft", draft_id)
    return studio.db.one("SELECT * FROM drafts WHERE id = ?", (draft_id,))


@router.delete("/drafts/{draft_id}", status_code=204)
def delete_draft(draft_id: str, studio: Studio = Depends(get_studio)):
    studio.db.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
