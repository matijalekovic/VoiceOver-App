"""SQLite metadata store. Audio stays on disk; rows hold relative paths."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    # 1: initial schema (specification section 6)
    """
    CREATE TABLE voices (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'ready')),
        primary_reference_id TEXT,
        preferred_sample_generation_id TEXT,
        consent_confirmed INTEGER NOT NULL CHECK (consent_confirmed = 1),
        consent_speaker TEXT NOT NULL,
        consent_scope TEXT NOT NULL,
        consent_notes TEXT NOT NULL DEFAULT '',
        consent_recorded_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE reference_recordings (
        id TEXT PRIMARY KEY,
        voice_id TEXT NOT NULL REFERENCES voices(id) ON DELETE CASCADE,
        original_filename TEXT NOT NULL,
        original_path TEXT NOT NULL,
        audio_path TEXT NOT NULL,
        transcript TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL,
        duration_s REAL NOT NULL,
        source_duration_s REAL NOT NULL,
        trim_start_s REAL NOT NULL,
        trim_end_s REAL NOT NULL,
        quality_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX reference_recordings_voice ON reference_recordings(voice_id);

    CREATE TABLE projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        script TEXT NOT NULL DEFAULT '',
        voice_id TEXT REFERENCES voices(id) ON DELETE SET NULL,
        language TEXT NOT NULL,
        model_id TEXT NOT NULL,
        default_pause_ms INTEGER NOT NULL DEFAULT 400,
        paragraph_pause_ms INTEGER NOT NULL DEFAULT 900,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE segments (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        text TEXT NOT NULL,
        pause_after_ms INTEGER NOT NULL,
        active_generation_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX segments_project ON segments(project_id, position);

    CREATE TABLE generations (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL CHECK (kind IN ('tts', 'voice_test', 'segment')),
        voice_id TEXT REFERENCES voices(id) ON DELETE SET NULL,
        voice_name TEXT NOT NULL,
        reference_id TEXT,
        project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
        segment_id TEXT REFERENCES segments(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        language TEXT NOT NULL,
        model_id TEXT NOT NULL,
        params_json TEXT NOT NULL,
        audio_path TEXT NOT NULL,
        duration_s REAL NOT NULL,
        sample_rate INTEGER NOT NULL,
        stats_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX generations_created ON generations(created_at);
    CREATE INDEX generations_segment ON generations(segment_id);

    CREATE TABLE jobs (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        progress_json TEXT NOT NULL DEFAULT '{}',
        result_json TEXT,
        error_code TEXT,
        error_message TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        voice_id TEXT,
        project_id TEXT,
        segment_id TEXT,
        generation_id TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    );
    CREATE INDEX jobs_status ON jobs(status, created_at);

    CREATE TABLE drafts (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        voice_id TEXT,
        language TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return uuid.uuid4().hex


class Database:
    """Thin wrapper over sqlite3: one short-lived connection per unit of work."""

    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for index, script in enumerate(MIGRATIONS[version:], start=version + 1):
                conn.execute("BEGIN")
                _run_script(conn, script)
                conn.execute(f"PRAGMA user_version = {index}")
                conn.execute("COMMIT")
        finally:
            conn.close()
        self.path.chmod(0o600)

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """A serialised write transaction; rolls back on error."""
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self.read() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self.read() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self.write() as conn:
            return conn.execute(sql, params).rowcount

    # Settings are small JSON values keyed by name.
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value_json FROM settings WHERE key = ?", (key,))
        return json.loads(row["value_json"]) if row else default

    def get_settings(self) -> dict[str, Any]:
        return {r["key"]: json.loads(r["value_json"]) for r in self.all("SELECT * FROM settings")}

    def set_settings(self, values: dict[str, Any]) -> None:
        stamp = now_iso()
        with self.write() as conn:
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                    "updated_at = excluded.updated_at",
                    (key, json.dumps(value), stamp),
                )


def _run_script(conn: sqlite3.Connection, script: str) -> None:
    # executescript() would commit our open transaction, so run statements one by one.
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)
