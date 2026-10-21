"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .api import generation, projects, system, voices
from .catalog import ModelSpec
from .config import Settings
from .errors import StudioError
from .security import LocalAccessMiddleware
from .studio import Studio

log = logging.getLogger("voice_studio.app")


def create_app(settings: Settings, catalog: list[ModelSpec] | None = None) -> FastAPI:
    studio = Studio(settings, catalog)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        studio.start()
        log.info(
            "Voice Studio backend %s ready on %s:%s", __version__, settings.host, settings.port
        )
        try:
            yield
        finally:
            log.info("shutting down: stopping jobs and releasing the model")
            studio.stop()

    app = FastAPI(title="1PAX Voice Studio API", version=__version__, lifespan=lifespan)
    app.state.studio = studio

    @app.exception_handler(StudioError)
    async def studio_error(_: Request, exc: StudioError):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        message = first.get("msg", "Invalid request.").removeprefix("Value error, ")
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": f"{where}: {message}" if where else message,
                    "details": jsonable_errors(exc.errors()),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": f"Unexpected error: {exc}"}},
        )

    for router in (voices.router, generation.router, projects.router, system.router):
        app.include_router(router)

    # Order matters: CORS is added last so it wraps the access check and every
    # response, including rejections, carries the CORS headers the webview needs.
    app.add_middleware(
        LocalAccessMiddleware, token=settings.token, allowed_origins=settings.allowed_origins
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["authorization", "content-type", "x-studio-token"],
    )
    return app


def jsonable_errors(errors: list) -> list:
    return [
        {
            k: (v if isinstance(v, (str, int, float, list, type(None))) else str(v))
            for k, v in e.items()
        }
        for e in errors
    ]
