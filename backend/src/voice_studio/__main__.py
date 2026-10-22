"""Entry point used by the desktop shell: `python -m voice_studio`."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time

import psutil
import uvicorn

from .app import create_app
from .config import Settings
from .studio import configure_logging


def _exit_with_parent(parent_pid: int) -> None:
    """If the desktop shell disappears without stopping us, shut down cleanly."""
    # Not os.kill(pid, 0): on Windows that terminates the process instead of probing it.
    while True:
        time.sleep(1.0)
        if not psutil.pid_exists(parent_pid):
            logging.getLogger("voice_studio").warning("desktop shell exited; shutting down")
            # uvicorn shuts down gracefully on SIGINT everywhere, on SIGTERM only on Unix.
            signal.raise_signal(signal.SIGINT if sys.platform == "win32" else signal.SIGTERM)
            return


def main() -> None:
    os.umask(0o077)  # library files are private to the user
    settings = Settings.from_env()
    settings.paths.ensure()
    configure_logging(settings.paths.logs)
    parent = os.environ.get("VOICE_STUDIO_PARENT_PID")
    if parent and parent.isdigit():
        threading.Thread(target=_exit_with_parent, args=(int(parent),), daemon=True).start()
    app = create_app(settings)
    # The desktop shell polls GET /api/health until the server answers.
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=False,
        timeout_graceful_shutdown=10,
    )
    server = uvicorn.Server(config)
    server.run()
    sys.exit(0)


if __name__ == "__main__":
    main()
