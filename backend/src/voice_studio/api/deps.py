from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import Request, UploadFile

from ..db import new_id
from ..errors import StudioError
from ..studio import Studio


def get_studio(request: Request) -> Studio:
    return request.app.state.studio


def save_upload(studio: Studio, upload: UploadFile) -> Path:
    """Stream an upload to the cache, enforcing the size limit while copying."""
    limit = studio.settings.max_upload_bytes
    target = (
        studio.paths.cache / "uploads" / f"{new_id()}{Path(upload.filename or '').suffix.lower()}"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with open(target, "wb") as out:
            while chunk := upload.file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise StudioError(
                        "file_too_large",
                        f"Files are limited to {limit // (1024 * 1024)} MB.",
                        status_code=413,
                    )
                out.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if written == 0:
        target.unlink(missing_ok=True)
        raise StudioError("empty_file", "The uploaded file is empty.")
    return target


def discard(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
