"""Structured errors. Every failure the UI can see carries a stable code and a readable message."""

from __future__ import annotations

from typing import Any


class StudioError(Exception):
    status_code = 400

    def __init__(
        self, code: str, message: str, *, status_code: int | None = None, details: Any = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        if status_code is not None:
            self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return body


class NotFound(StudioError):
    def __init__(self, what: str, ident: str):
        super().__init__("not_found", f"{what} {ident} does not exist.", status_code=404)


class Conflict(StudioError):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(code, message, status_code=409, details=details)


class EngineError(StudioError):
    """Raised for failures inside the inference worker or while talking to it."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(code, message, status_code=503, details=details)


class JobCancelled(Exception):
    pass
