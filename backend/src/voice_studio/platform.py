"""What differs between the macOS and Windows builds."""

from __future__ import annotations

import functools
import platform
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
# MLX (and so the Apple-GPU engines) exists only on Apple Silicon Macs; everywhere else the
# PyTorch engines run, on an NVIDIA GPU when there is one.
USES_MLX = sys.platform == "darwin" and platform.machine() == "arm64"

# The server runs without a console on Windows; without this flag every helper program
# (FFmpeg, nvidia-smi) would flash a console window.
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}


@functools.cache
def accelerator() -> str:
    """'apple' (Apple GPU through MLX), 'cuda' (an NVIDIA GPU is present) or 'cpu'."""
    if USES_MLX:
        return "apple"
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run(
                [smi, "-L"], capture_output=True, text=True, timeout=5, **NO_WINDOW
            )
            if out.returncode == 0 and "GPU" in out.stdout:
                return "cuda"
        except (OSError, subprocess.SubprocessError):
            pass
    return "cpu"


def reveal(path: Path) -> None:
    """Show a file in Finder or Explorer."""
    if IS_WINDOWS:
        subprocess.run(["explorer", "/select,", str(path)], check=False, timeout=10, **NO_WINDOW)
    else:
        subprocess.run(["/usr/bin/open", "-R", str(path)], check=False, timeout=10)
