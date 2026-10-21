"""Works around GPU kernels that the installed macOS cannot compile.

MLX picks the neural-accelerator ("NAX") matmul kernels on M5-generation GPUs, but the Metal
compiler in early macOS 26 releases rejects them, so every generation fails with
"Unable to load kernel steel_gemm_fused_nax_...". Reporting the previous GPU generation to
MLX makes it use the regular kernels instead. Whether that is needed is decided by trying a
matmul in a throwaway process, since a failed kernel load cannot be undone in-process.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys

log = logging.getLogger("voice_studio.inference")

ARCH_VAR = "MLX_METAL_GPU_ARCH"

_PROBE = """
import mlx.core as mx
print(mx.metal.device_info().get("architecture", ""))
a = mx.ones((256, 512), dtype=mx.bfloat16)
try:
    mx.eval(a @ a.T)
    print("ok")
except RuntimeError as exc:
    print("nax" if "_nax_" in str(exc) else "error")
"""

_checked = False


def _fallback_arch(arch: str) -> str | None:
    """applegpu_g17g -> applegpu_g16g: same GPU class, one generation back."""
    prefix, _, rest = arch.partition("applegpu_g")
    digits = "".join(c for c in rest if c.isdigit())
    if prefix or not digits:
        return None
    return f"applegpu_g{int(digits) - 1}{rest[len(digits) :]}"


def apply_kernel_workaround() -> None:
    """Sets MLX_METAL_GPU_ARCH for worker processes when this Mac needs it. Runs once."""
    global _checked
    if _checked:
        return
    _checked = True
    if sys.platform != "darwin" or platform.machine() != "arm64" or ARCH_VAR in os.environ:
        return
    try:
        out = subprocess.run(
            [sys.executable, "-c", _PROBE], capture_output=True, text=True, timeout=120
        ).stdout.split()
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("GPU kernel check skipped: %s", exc)
        return
    if len(out) < 2 or out[1] != "nax":
        return
    fallback = _fallback_arch(out[0])
    if fallback:
        os.environ[ARCH_VAR] = fallback
        log.warning(
            "This macOS cannot compile the %s neural-accelerator kernels; running MLX as %s",
            out[0],
            fallback,
        )
