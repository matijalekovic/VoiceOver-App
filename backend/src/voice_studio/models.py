"""Checkpoint installation: download, validation, deletion and on-disk status."""

from __future__ import annotations

import json
import logging
import multiprocessing as mp
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .catalog import CATALOG, ModelSpec, design_spec, get_spec
from .db import now_iso
from .errors import Conflict, NotFound, StudioError

log = logging.getLogger("voice_studio.models")

MARKER = ".voice-studio.json"


def dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def validate_model_dir(path: Path, kind: str = "tts") -> list[str]:
    """Problems that would stop the folder from loading as a Qwen3-TTS checkpoint
    (or, for kind "stt", as a Whisper checkpoint)."""
    problems: list[str] = []
    config_path = path / "config.json"
    if not config_path.exists():
        return ["config.json is missing"]
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError):
        return ["config.json is unreadable"]
    if kind == "stt":
        # MLX checkpoints ship safetensors plus the alignment heads (for word timings) in
        # generation_config.json; CTranslate2 ones (faster-whisper) ship model.bin.
        mlx_format = bool(list(path.glob("*.safetensors")))
        if not mlx_format and not (path / "model.bin").exists():
            problems.append("model weights are missing")
        required = ["tokenizer.json", "preprocessor_config.json"]
        if mlx_format:
            required.append("generation_config.json")
        for name in required:
            if not (path / name).exists():
                problems.append(f"{name} is missing")
        return problems
    model_type = config.get("tts_model_type", "base")
    if model_type not in ("base", "voice_design"):
        problems.append(
            f"this is a {model_type} checkpoint; Voice Studio needs a Base (cloning) or "
            "Voice Design checkpoint"
        )
    if not list(path.glob("*.safetensors")):
        problems.append("model weights (*.safetensors) are missing")
    if not ((path / "tokenizer.json").exists() or (path / "vocab.json").exists()):
        problems.append("text tokenizer files are missing")
    # Both paths decode generated speech; only Base also encodes a reference recording.
    speech = path / "speech_tokenizer"
    if not (speech / "config.json").exists() or not list(speech.glob("*.safetensors")):
        problems.append("speech_tokenizer/ is missing")
    return problems


def _download_main(
    repo_id: str, target: str, log_file: str, hf_home: str
) -> None:  # pragma: no cover - child process
    # Keep Hugging Face's own files inside the app's folder, and skip the Xet chunk cache,
    # which would otherwise keep a second multi-GB copy of the model in ~/.cache.
    os.environ["HF_HOME"] = hf_home
    os.environ["HF_XET_CHUNK_CACHE_SIZE_BYTES"] = "0"
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [download] %(message)s",
    )
    from huggingface_hub import snapshot_download

    snapshot_download(repo_id, local_dir=target, max_workers=4)


class ModelManager:
    def __init__(
        self,
        models_dir: Path,
        log_file: Path,
        hf_home: Path,
        catalog: list[ModelSpec] | None = None,
    ):
        self.models_dir = models_dir
        self.hf_home = hf_home
        self.log_file = log_file
        self.catalog = catalog if catalog is not None else CATALOG
        self._ctx = mp.get_context("spawn")
        self._downloads: dict[str, dict[str, Any]] = {}
        self._queue: list[str] = []  # waiting downloads, started one at a time
        self._lock = threading.Lock()

    def spec(self, model_id: str) -> ModelSpec:
        spec = get_spec(model_id, self.catalog)
        if spec is None:
            raise NotFound("Model", model_id)
        return spec

    def voice_spec(self, model_id: str) -> ModelSpec:
        """The spec of a model that can generate voices (not the speech recognition one)."""
        spec = self.spec(model_id)
        if spec.kind != "tts":
            raise StudioError(
                "not_a_voice_model", f"{spec.label} transcribes speech; it cannot generate voices."
            )
        return spec

    def spec_for_mode(self, mode: str, model_id: str) -> ModelSpec:
        """Check that a voice model matches how the voice was made: cloning needs Base,
        designed voices need Voice Design."""
        spec = self.voice_spec(model_id)
        wanted = "design" if mode == "design" else "clone"
        if spec.capability != wanted:
            raise StudioError(
                "wrong_model_type",
                (
                    f"{spec.label} designs voices from a description; this voice clones a "
                    "recording. Choose a Base model."
                    if wanted == "clone"
                    else f"{spec.label} clones voices from recordings; this voice was designed "
                    "from a description. Choose the Voice Design model."
                ),
            )
        return spec

    def default_model_for(self, mode: str, preferred: str | None = None) -> str:
        """The model a voice of this kind should use when the caller did not name one."""
        if mode == "design":
            spec = design_spec(self.catalog)
            if spec is None:
                raise StudioError(
                    "design_model_unavailable",
                    "No Voice Design model is in this build's catalog.",
                )
            return spec.id
        chosen = get_spec(preferred, self.catalog) if preferred else None
        if chosen and chosen.kind == "tts" and chosen.capability == "clone":
            return chosen.id
        clone = next((s for s in self.catalog if s.kind == "tts" and s.capability == "clone"), None)
        if clone is None:
            raise StudioError("no_voice_model", "No voice cloning model is in the catalog.")
        return clone.id

    def model_dir(self, model_id: str) -> Path:
        return self.models_dir / self.spec(model_id).id

    def is_installed(self, model_id: str) -> bool:
        return self.status(model_id)["state"] == "installed"

    def status(self, model_id: str) -> dict[str, Any]:
        spec = self.spec(model_id)
        path = self.models_dir / spec.id
        with self._lock:
            download = self._downloads.get(model_id)
        if download and download["state"] in ("queued", "starting"):
            return {"state": download["state"], "path": str(path)}
        if download and download["state"] in ("downloading", "failed"):
            if download["state"] == "downloading":
                download["downloaded_bytes"] = dir_size(path)
            return {
                "state": download["state"],
                "downloaded_bytes": download.get("downloaded_bytes", 0),
                "total_bytes": download.get("total_bytes"),
                "error": download.get("error"),
                "path": str(path),
            }
        if not path.exists():
            return {"state": "not_installed", "path": str(path)}
        problems = validate_model_dir(path, spec.kind)
        marker = path / MARKER
        info = json.loads(marker.read_text()) if marker.exists() else {}
        if problems:
            return {
                "state": "incomplete",
                "problems": problems,
                "size_bytes": dir_size(path),
                "path": str(path),
            }
        if not marker.exists():
            # Downloaded by hand (e.g. `hf download ... --local-dir`): record it once.
            info = {"repo_id": spec.repo_id, "installed_at": now_iso(), "source": "manual"}
            marker.write_text(json.dumps(info, indent=2))
        return {"state": "installed", "size_bytes": dir_size(path), "path": str(path), **info}

    def list(self) -> list[dict[str, Any]]:
        return [{**spec.to_dict(), "status": self.status(spec.id)} for spec in self.catalog]

    def start_download(self, model_id: str) -> dict[str, Any]:
        """Start downloading, or queue behind the download already running."""
        spec = self.spec(model_id)
        with self._lock:
            current = self._downloads.get(model_id)
            if current and current["state"] == "downloading":
                raise Conflict("download_in_progress", f"{spec.label} is already downloading.")
            if current and current["state"] == "queued":
                return {"state": "queued"}
            if any(d["state"] in ("downloading", "starting") for d in self._downloads.values()):
                self._downloads[model_id] = {"state": "queued"}
                self._queue.append(model_id)
                return {"state": "queued"}
            # Claimed before the (slow) size check, so a cancel in between is not lost.
            self._downloads[model_id] = {"state": "starting"}
        return self._launch(model_id)

    def _launch(self, model_id: str) -> dict[str, Any]:
        spec = self.spec(model_id)
        target = self.models_dir / spec.id
        target.mkdir(parents=True, exist_ok=True)
        try:
            total = self._remote_size(spec.repo_id)
            free = shutil.disk_usage(self.models_dir).free
            if total and total - dir_size(target) > free:
                raise StudioError(
                    "insufficient_disk",
                    f"Not enough free disk space: {total / 1e9:.1f} GB needed, {free / 1e9:.1f} GB free.",
                )
        except BaseException:
            with self._lock:
                self._downloads.pop(model_id, None)
            raise
        with self._lock:
            if self._downloads.get(model_id, {}).get("cancelled"):
                self._downloads.pop(model_id, None)
                if not any(target.iterdir()):
                    target.rmdir()  # nothing was downloaded
                return {"state": "not_installed"}
        proc = self._ctx.Process(
            target=_download_main,
            args=(spec.repo_id, str(target), str(self.log_file), str(self.hf_home)),
            name=f"voice-studio-download-{spec.id}",
            daemon=True,
        )
        proc.start()
        entry = {
            "state": "downloading",
            "proc": proc,
            "total_bytes": total,
            "started_at": now_iso(),
        }
        with self._lock:
            self._downloads[model_id] = entry
        threading.Thread(target=self._watch, args=(model_id, spec, entry), daemon=True).start()
        return self.status(model_id)

    def _remote_size(self, repo_id: str) -> int | None:
        try:
            from huggingface_hub import HfApi

            info = HfApi().model_info(repo_id, files_metadata=True)
            return sum((s.size or 0) for s in (info.siblings or []))
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "404" in message or "Repository Not Found" in message:
                raise StudioError(
                    "model_not_found", f"{repo_id} was not found on Hugging Face."
                ) from exc
            raise StudioError(
                "network_unavailable",
                "Could not reach Hugging Face to download the model. Check the internet connection.",
                details=message[-500:],
            ) from exc

    def _watch(self, model_id: str, spec: ModelSpec, entry: dict[str, Any]) -> None:
        entry["proc"].join()
        try:
            self._settle(model_id, spec, entry)
        finally:
            self._start_next()

    def _settle(self, model_id: str, spec: ModelSpec, entry: dict[str, Any]) -> None:
        proc = entry["proc"]
        target = self.models_dir / spec.id
        with self._lock:
            if entry.get("cancelled"):
                self._downloads.pop(model_id, None)
                return
            if proc.exitcode == 0 and not validate_model_dir(target, spec.kind):
                (target / MARKER).write_text(
                    json.dumps(
                        {"repo_id": spec.repo_id, "installed_at": now_iso(), "source": "download"},
                        indent=2,
                    )
                )
                self._downloads.pop(model_id, None)
                log.info("downloaded %s", spec.repo_id)
            else:
                problems = validate_model_dir(target, spec.kind)
                entry["state"] = "failed"
                entry["error"] = (
                    f"Download stopped (exit code {proc.exitcode}). Retry to resume where it left off."
                    if proc.exitcode != 0
                    else "Downloaded files are incomplete: " + "; ".join(problems)
                )
                entry["downloaded_bytes"] = dir_size(target)

    def _start_next(self) -> None:
        """Start the next queued download, skipping any that cannot start."""
        while True:
            with self._lock:
                if not self._queue:
                    return
                model_id = self._queue.pop(0)
                self._downloads[model_id] = {"state": "starting"}
            try:
                self._launch(model_id)
                return
            except StudioError as exc:
                with self._lock:
                    self._downloads[model_id] = {"state": "failed", "error": exc.message}

    def cancel_download(self, model_id: str) -> None:
        with self._lock:
            entry = self._downloads.get(model_id)
            if entry and entry["state"] == "queued":
                self._downloads.pop(model_id, None)
                if model_id in self._queue:
                    self._queue.remove(model_id)
                return
            if entry and entry["state"] == "starting":
                entry["cancelled"] = True  # _launch sees this before starting the process
                return
            if not entry or entry["state"] != "downloading":
                return
            entry["cancelled"] = True
            proc = entry["proc"]
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()

    def delete(self, model_id: str) -> None:
        self.cancel_download(model_id)
        path = self.models_dir / self.spec(model_id).id
        if path.exists():
            shutil.rmtree(path)
        with self._lock:
            self._downloads.pop(model_id, None)

    def shutdown(self) -> None:
        with self._lock:
            for model_id in self._queue:
                self._downloads.pop(model_id, None)
            self._queue.clear()
        for model_id in list(self._downloads):
            self.cancel_download(model_id)

    def wait_idle(self, timeout: float = 30) -> None:
        """Test helper: wait until no download is running."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not any(
                    d["state"] in ("downloading", "starting", "queued")
                    for d in self._downloads.values()
                ):
                    return
            time.sleep(0.1)
