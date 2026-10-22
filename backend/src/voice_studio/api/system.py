from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from collections import deque
from pathlib import Path

import psutil
from fastapi import APIRouter, Depends, Query

from .. import __version__, schemas
from ..catalog import QWEN3_LANGUAGES
from ..errors import Conflict, StudioError
from ..jobs import memory_pressure_level
from ..models import dir_size
from ..platform import USES_MLX, accelerator
from ..platform import reveal as show_in_file_manager
from ..studio import Studio
from .deps import get_studio

router = APIRouter(prefix="/api", tags=["system"])


# -- models -----------------------------------------------------------------
@router.get("/models")
def list_models(studio: Studio = Depends(get_studio)):
    loaded = studio.inference.loaded
    return [
        {**model, "loaded": bool(loaded and loaded["model_id"] == model["id"])}
        for model in studio.models.list()
    ]


@router.post("/models/download")
def download_model(body: schemas.ModelAction, studio: Studio = Depends(get_studio)):
    return studio.models.start_download(body.model_id)


@router.post("/models/download/cancel", status_code=204)
def cancel_download(body: schemas.ModelAction, studio: Studio = Depends(get_studio)):
    studio.models.cancel_download(body.model_id)


@router.post("/models/load", response_model=schemas.JobRef, status_code=202)
def load_model(body: schemas.ModelAction, studio: Studio = Depends(get_studio)):
    spec = studio.models.voice_spec(body.model_id)
    if not studio.models.is_installed(body.model_id):
        raise StudioError("model_not_installed", f"{spec.label} is not installed yet.")
    job = studio.jobs.submit("load_model", {"model_id": body.model_id})
    return {"job_id": job["id"], "status": job["status"]}


@router.post("/models/unload", status_code=204)
def unload_model(body: schemas.UnloadRequest | None = None, studio: Studio = Depends(get_studio)):
    if studio.jobs.current_job_id and not (body and body.force):
        raise Conflict(
            "engine_busy", "A job is running. Wait for it or cancel it before unloading the model."
        )
    if studio.jobs.current_job_id:
        studio.inference.force_stop()
    studio.inference.unload()


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: str, studio: Studio = Depends(get_studio)):
    loaded = studio.inference.loaded
    if loaded and loaded["model_id"] == model_id:
        raise Conflict("model_loaded", "Unload the model before deleting it.")
    studio.models.delete(model_id)


# -- settings and languages ---------------------------------------------------------
@router.get("/settings")
def get_settings(studio: Studio = Depends(get_studio)):
    return studio.preferences()


@router.put("/settings")
def update_settings(body: schemas.Preferences, studio: Studio = Depends(get_studio)):
    values = body.model_dump(exclude_unset=True, exclude_none=True)
    if "default_model_id" in values:
        studio.models.spec_for_mode("clone", values["default_model_id"])
    if "output_dir" in values:
        folder = Path(values["output_dir"]).expanduser()
        if not folder.is_absolute():
            raise StudioError("invalid_path", "The output folder must be an absolute path.")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StudioError("output_dir_unwritable", f"Cannot create {folder}.") from exc
        values["output_dir"] = str(folder)
    if "enabled_languages" in values:
        unknown = [code for code in values["enabled_languages"] if code not in QWEN3_LANGUAGES]
        if unknown:
            raise StudioError("unknown_language", f"Unknown language(s): {', '.join(unknown)}.")
    studio.db.set_settings(values)
    return studio.preferences()


@router.get("/languages")
def languages(studio: Studio = Depends(get_studio)):
    prefs = studio.preferences()
    loaded = studio.inference.loaded
    runtime = set(loaded["info"]["languages"]) if loaded else None
    notes = prefs.get("language_notes") or {}
    return [
        {
            "code": code,
            "label": label,
            "enabled": code in prefs["enabled_languages"],
            # None until a model is loaded and has reported what it supports.
            "supported_by_loaded_model": None if runtime is None else code in runtime,
            "evaluation": notes.get(code, {}),
        }
        for code, label in QWEN3_LANGUAGES.items()
    ]


# -- system -------------------------------------------------------------------------
@router.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@router.get("/system/status")
def system_status(studio: Studio = Depends(get_studio)):
    vm = psutil.virtual_memory()
    inference = studio.inference
    worker_rss = None
    pid = inference.worker_pid()
    if pid:
        try:
            worker_rss = psutil.Process(pid).memory_info().rss
        except psutil.Error:
            worker_rss = None
    current = studio.jobs.current_job_id
    queued = studio.db.one("SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued'")["n"]
    return {
        "version": __version__,
        "engine": {
            "state": inference.state,
            "loaded_model_id": inference.loaded["model_id"] if inference.loaded else None,
            "load_seconds": inference.loaded["load_seconds"] if inference.loaded else None,
            "info": inference.loaded["info"] if inference.loaded else None,
            "worker_pid": pid,
            "worker_rss_bytes": worker_rss,
            "last_memory": inference.last_memory,
            "runtime_available": importlib.util.find_spec("mlx" if USES_MLX else "torch")
            is not None,
            "accelerator": accelerator(),
        },
        "memory": {
            "total_bytes": vm.total,
            "available_bytes": vm.available,
            "pressure_level": memory_pressure_level(),
        },
        "jobs": {"current_job_id": current, "queued": queued},
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "mac_version": platform.mac_ver()[0] or None,
            "python": sys.version.split()[0],
        },
        "data_dir": str(studio.paths.root),
    }


@router.get("/system/storage")
def storage(studio: Studio = Depends(get_studio)):
    paths = studio.paths
    usage = shutil.disk_usage(paths.root)
    return {
        "data_dir": str(paths.root),
        "categories": {
            "models": dir_size(paths.models),
            "voices": dir_size(paths.voices),
            "projects": dir_size(paths.projects),
            "generations": dir_size(paths.generations),
            "cache": dir_size(paths.cache),
            "logs": dir_size(paths.logs),
            "database": dir_size(paths.database.parent),
        },
        "disk_free_bytes": usage.free,
        "disk_total_bytes": usage.total,
    }


@router.post("/system/clear-cache", status_code=204)
def clear_cache(studio: Studio = Depends(get_studio)):
    if studio.jobs.current_job_id:
        raise Conflict("engine_busy", "A job is running; clear the cache when it has finished.")
    for child in studio.paths.cache.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


@router.get("/system/logs")
def logs(
    source: str = Query(default="backend", pattern="^(backend|inference|downloads)$"),
    lines: int = Query(default=300, ge=1, le=5000),
    studio: Studio = Depends(get_studio),
):
    path = studio.paths.logs / f"{source}.log"
    if not path.exists():
        return {"source": source, "lines": []}
    with open(path, encoding="utf-8", errors="replace") as fh:
        tail = deque(fh, maxlen=lines)
    return {"source": source, "lines": [line.rstrip("\n") for line in tail]}


@router.post("/system/reveal", status_code=204)
def reveal(body: schemas.RevealRequest, studio: Studio = Depends(get_studio)):
    """Show a file in Finder. Limited to the data folder and the export folder."""
    target = Path(body.path).expanduser().resolve()
    output_dir = Path(studio.pref("output_dir")).expanduser().resolve()
    roots = [studio.paths.root.resolve(), output_dir]
    if target == output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)  # not created until the first export
    if not any(target == root or root in target.parents for root in roots):
        raise StudioError(
            "forbidden_path", "Only Voice Studio's own folders can be revealed.", status_code=403
        )
    if not target.exists():
        raise StudioError("not_found", "That file no longer exists.", status_code=404)
    show_in_file_manager(target)
