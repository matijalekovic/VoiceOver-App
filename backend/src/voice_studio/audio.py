"""Audio conversion, analysis, assembly and export (FFmpeg + numpy)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .errors import StudioError

MODEL_SAMPLE_RATE = 24_000
_FRAME_S = 0.02


def ffmpeg_exe() -> str:
    """FFmpeg from the environment variable, the pinned Python wheel, or Homebrew."""
    override = os.environ.get("VOICE_STUDIO_FFMPEG")
    if override:
        return override
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - fall through to the system copies
        pass
    for candidate in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if candidate and Path(candidate).exists():
            return candidate
    raise StudioError(
        "ffmpeg_missing", "FFmpeg was not found. Reinstall the app runtime.", status_code=500
    )


def _run_ffmpeg(args: list[str]) -> None:
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise StudioError(
            "audio_conversion_failed",
            "The audio file could not be read or converted. Check that it is a valid WAV, MP3, M4A or FLAC file.",
            details=proc.stderr.strip()[-2000:],
        )


def decode_to_wav(src: Path, dst: Path, *, sample_rate: int = MODEL_SAMPLE_RATE) -> None:
    """Any supported input -> mono 16-bit PCM WAV at the model sample rate."""
    tmp = dst.with_suffix(".tmp.wav")
    _run_ffmpeg(
        ["-i", str(src), "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(tmp)]
    )
    _fsync_replace(tmp, dst)


def read_audio(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, sr


def write_wav(path: Path, audio: np.ndarray, sample_rate: int, subtype: str = "PCM_16") -> None:
    """Durable write: temp file in the same folder, fsync, atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".wav.tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        sf.write(str(tmp), np.clip(audio, -1.0, 1.0), sample_rate, subtype=subtype, format="WAV")
        _fsync_replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _fsync_replace(tmp: Path, dst: Path, mode: int = 0o600) -> None:
    with open(tmp, "rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, dst)
    os.chmod(dst, mode)


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def frame_rms_db(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    frame = max(1, int(sample_rate * _FRAME_S))
    usable = len(audio) // frame * frame
    if usable == 0:
        return np.array([-180.0])
    frames = audio[:usable].reshape(-1, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9))


@dataclass
class QualityReport:
    duration_s: float
    peak_dbfs: float
    speech_level_dbfs: float
    noise_floor_dbfs: float
    snr_db: float
    clipping_ratio: float
    flags: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


def analyse(audio: np.ndarray, sample_rate: int) -> QualityReport:
    """Measurements behind the warnings shown before a reference is saved."""
    duration = len(audio) / sample_rate
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    levels = frame_rms_db(audio, sample_rate)
    speech = float(np.percentile(levels, 90))
    noise = float(np.percentile(levels, 10))
    clipping = float(np.mean(np.abs(audio) >= 0.999)) if len(audio) else 0.0
    flags: list[dict] = []

    def flag(code: str, severity: str, message: str) -> None:
        flags.append({"code": code, "severity": severity, "message": message})

    if duration < 3:
        flag(
            "too_short",
            "error",
            "The recording is under 3 seconds. Use 10–30 seconds of clean speech.",
        )
    elif duration < 10:
        flag(
            "short",
            "warning",
            "Under 10 seconds can work but usually clones less reliably. 10–30 seconds is recommended.",
        )
    elif duration > 60:
        flag("too_long", "error", "Over 60 seconds. Trim the reference to the best 10–30 seconds.")
    elif duration > 30:
        flag(
            "long",
            "warning",
            "Over 30 seconds. Longer references slow every generation; 10–30 seconds is recommended.",
        )
    if peak < 1e-4:
        flag("silent", "error", "The recording is silent.")
    if clipping > 0.0005:
        flag(
            "clipping",
            "warning",
            f"{clipping:.2%} of samples are clipped. Distortion will be copied into the voice.",
        )
    if speech < -35:
        flag(
            "quiet",
            "warning",
            "The speech is very quiet. It will be normalised, which also raises background noise.",
        )
    if speech - noise < 20:
        flag(
            "noisy",
            "warning",
            f"Background noise is high (about {speech - noise:.0f} dB below the speech). Noise and room sound will be cloned too.",
        )
    return QualityReport(
        duration_s=round(duration, 3),
        peak_dbfs=round(_db(peak), 1),
        speech_level_dbfs=round(speech, 1),
        noise_floor_dbfs=round(noise, 1),
        snr_db=round(speech - noise, 1),
        clipping_ratio=round(clipping, 6),
        flags=flags,
    )


def speech_bounds(audio: np.ndarray, sample_rate: int, pad_s: float = 0.15) -> tuple[float, float]:
    """Start and end (seconds) of the audible part, with a little padding kept."""
    levels = frame_rms_db(audio, sample_rate)
    noise = float(np.percentile(levels, 10))
    threshold = max(noise + 10.0, float(np.max(levels)) - 45.0, -60.0)
    voiced = np.nonzero(levels > threshold)[0]
    duration = len(audio) / sample_rate
    if len(voiced) == 0:
        return 0.0, duration
    start = max(0.0, voiced[0] * _FRAME_S - pad_s)
    end = min(duration, (voiced[-1] + 1) * _FRAME_S + pad_s)
    return round(start, 3), round(end, 3)


def trim_edges(audio: np.ndarray, sample_rate: int, pad_s: float = 0.08) -> np.ndarray:
    start, end = speech_bounds(audio, sample_rate, pad_s)
    return audio[int(start * sample_rate) : int(end * sample_rate)]


def normalise_peak(
    audio: np.ndarray, target_dbfs: float = -1.0, max_gain_db: float = 20.0
) -> np.ndarray:
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak < 1e-6:
        return audio
    gain_db = min(target_dbfs - _db(peak), max_gain_db)
    return (audio * (10 ** (gain_db / 20))).astype(np.float32)


def fade(audio: np.ndarray, sample_rate: int, ms: float = 8.0) -> np.ndarray:
    """Short fades so joins between chunks never click."""
    n = min(len(audio) // 2, int(sample_rate * ms / 1000))
    if n <= 1:
        return audio
    out = audio.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out


def join(parts: list[tuple[np.ndarray, float]], sample_rate: int) -> np.ndarray:
    """Concatenate (audio, pause_after_seconds) pairs; the last pause is dropped."""
    pieces: list[np.ndarray] = []
    for index, (audio, pause_s) in enumerate(parts):
        pieces.append(fade(audio.astype(np.float32), sample_rate))
        if index < len(parts) - 1 and pause_s > 0:
            pieces.append(np.zeros(int(sample_rate * pause_s), dtype=np.float32))
    return np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)


EXPORT_FORMATS = {"wav", "mp3"}
MP3_BITRATES = {192, 320}
EXPORT_SAMPLE_RATES = {24_000, 44_100, 48_000}


def export(
    src_wav: Path, dst: Path, fmt: str, *, bitrate: int = 320, sample_rate: int | None = None
) -> Path:
    """Convert a stored WAV into the requested delivery format at dst."""
    if fmt not in EXPORT_FORMATS:
        raise StudioError("invalid_format", f"Unsupported export format {fmt!r}.")
    if fmt == "mp3" and bitrate not in MP3_BITRATES:
        raise StudioError("invalid_bitrate", "MP3 exports are 192 or 320 kbps.")
    if sample_rate is not None and sample_rate not in EXPORT_SAMPLE_RATES:
        raise StudioError(
            "invalid_sample_rate", "Export sample rate must be 24000, 44100 or 48000 Hz."
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.partial")
    args = ["-i", str(src_wav), "-vn"]
    if sample_rate:
        args += ["-ar", str(sample_rate)]
    if fmt == "wav":
        args += ["-c:a", "pcm_s16le", "-f", "wav"]
    else:
        # MP3 has no 24 kHz option at 320 kbps; resample to 44.1 kHz unless told otherwise.
        if not sample_rate:
            args += ["-ar", "44100"]
        args += ["-c:a", "libmp3lame", "-b:a", f"{bitrate}k", "-f", "mp3"]
    try:
        _run_ffmpeg([*args, str(tmp)])
        # Exports are deliverables meant to be shared, unlike the private library files.
        _fsync_replace(tmp, dst, 0o644)
    finally:
        tmp.unlink(missing_ok=True)
    return dst
