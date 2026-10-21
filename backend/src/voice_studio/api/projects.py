from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from .. import schemas
from ..projects import ProjectService
from ..studio import Studio
from .deps import get_studio

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[schemas.Project])
def list_projects(studio: Studio = Depends(get_studio)):
    return ProjectService(studio).list()


@router.post("", response_model=schemas.Project, status_code=201)
def create_project(body: schemas.ProjectCreate, studio: Studio = Depends(get_studio)):
    data = body.model_dump()
    data["language"] = data["language"].lower()
    return ProjectService(studio).create(data)


@router.get("/{project_id}", response_model=schemas.Project)
def get_project(project_id: str, studio: Studio = Depends(get_studio)):
    return ProjectService(studio).get(project_id)


@router.put("/{project_id}", response_model=schemas.Project)
def update_project(
    project_id: str, body: schemas.ProjectUpdate, studio: Studio = Depends(get_studio)
):
    patch = body.model_dump(exclude_unset=True)
    if patch.get("language"):
        patch["language"] = patch["language"].lower()
    return ProjectService(studio).update(project_id, patch)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, studio: Studio = Depends(get_studio)):
    ProjectService(studio).delete(project_id)


@router.post("/{project_id}/script", response_model=schemas.Project)
def resegment(project_id: str, body: schemas.Resegment, studio: Studio = Depends(get_studio)):
    return ProjectService(studio).resegment(project_id, body.script, body.segmentation)


@router.post("/{project_id}/segments", response_model=schemas.Project, status_code=201)
def add_segment(project_id: str, body: schemas.SegmentCreate, studio: Studio = Depends(get_studio)):
    return ProjectService(studio).add_segment(
        project_id, body.text, body.after_segment_id, body.pause_after_ms
    )


@router.patch("/{project_id}/segments/{segment_id}", response_model=schemas.Project)
def update_segment(
    project_id: str,
    segment_id: str,
    body: schemas.SegmentUpdate,
    studio: Studio = Depends(get_studio),
):
    return ProjectService(studio).update_segment(
        project_id, segment_id, body.model_dump(exclude_unset=True)
    )


@router.delete("/{project_id}/segments/{segment_id}", response_model=schemas.Project)
def delete_segment(project_id: str, segment_id: str, studio: Studio = Depends(get_studio)):
    return ProjectService(studio).delete_segment(project_id, segment_id)


@router.post("/{project_id}/reorder", response_model=schemas.Project)
def reorder(project_id: str, body: schemas.Reorder, studio: Studio = Depends(get_studio)):
    return ProjectService(studio).reorder(project_id, body.segment_ids)


@router.post("/{project_id}/generate", response_model=list[schemas.Job], status_code=202)
def generate_project(
    project_id: str, body: schemas.ProjectGenerate, studio: Studio = Depends(get_studio)
):
    return ProjectService(studio).queue_generation(project_id, body.segment_ids, body.only_missing)


@router.post("/{project_id}/preview")
def preview_project(project_id: str, studio: Studio = Depends(get_studio)):
    return FileResponse(ProjectService(studio).preview(project_id), media_type="audio/wav")


@router.post("/{project_id}/export", response_model=schemas.ExportResult)
def export_project(
    project_id: str, body: schemas.ProjectExport, studio: Studio = Depends(get_studio)
):
    return ProjectService(studio).export(
        project_id, body.format, body.bitrate, body.sample_rate, body.mode
    )
