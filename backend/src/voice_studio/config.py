"""Runtime configuration: where data lives and how the server is reached."""

from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import APP_NAME


def default_data_dir() -> Path:
    override = os.environ.get("VOICE_STUDIO_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


@dataclass(frozen=True)
class Paths:
    """The Application Support layout from the specification (section 6)."""

    root: Path

    @property
    def database(self) -> Path:
        return self.root / "database" / "voice_studio.sqlite"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def voices(self) -> Path:
        return self.root / "voices"

    @property
    def projects(self) -> Path:
        return self.root / "projects"

    @property
    def generations(self) -> Path:
        return self.root / "generations"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        # Owner-only permissions: recordings of people's voices live here.
        for path in (
            self.root,
            self.database.parent,
            self.models,
            self.voices,
            self.projects,
            self.generations,
            self.cache,
            self.logs,
        ):
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, 0o700)

    def resolve(self, relative: str | Path) -> Path:
        """Turn a stored relative path into an absolute one that must stay inside the root."""
        candidate = (self.root / relative).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError(f"Path escapes the data directory: {relative}")
        return candidate

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()


# Origins the desktop shell and the Vite dev server load the UI from.
DEFAULT_ALLOWED_ORIGINS = (
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
)


@dataclass(frozen=True)
class Settings:
    paths: Paths
    host: str = "127.0.0.1"
    port: int = 8765
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
    max_upload_bytes: int = 100 * 1024 * 1024
    max_generate_chars: int = 20_000
    max_script_chars: int = 400_000

    @classmethod
    def from_env(cls) -> Settings:
        paths = Paths(default_data_dir())
        token = os.environ.get("VOICE_STUDIO_TOKEN") or secrets.token_urlsafe(32)
        port = int(os.environ.get("VOICE_STUDIO_PORT", "8765"))
        extra_origins = tuple(
            o.strip()
            for o in os.environ.get("VOICE_STUDIO_EXTRA_ORIGINS", "").split(",")
            if o.strip()
        )
        return cls(
            paths=paths,
            port=port,
            token=token,
            allowed_origins=DEFAULT_ALLOWED_ORIGINS + extra_origins,
        )
