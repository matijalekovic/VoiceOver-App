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

from .catalog import CATALOG, ModelSpec, get_spec
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


def validate_model_dir(path: Path) -> list[str]:
    """Problems that would stop the folder from loading as a Qwen3-TTS Base checkpoint."""
    problems: list[str] = []
    config_path = path / "config.json"
    if not config_path.exists():
        return ["config.json is missing"]
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError):
        return ["config.json is unreadable"]
    if config.get("tts_model_type", "base") != "base":
        problems.append(
            f"this is a {config.get('tts_model_type')} checkpoint; voice cloning needs a Base checkpoint"
        )
    if not list(path.glob("*.safetensors")):
        problems.append("model weights (*.safetensors) are missing")
    if not ((path / "tokenizer.json").exists() or (path / "vocab.json").exists()):
        problems.append("text tokenizer files are missing")
    speech = path / "speech_tokenizer"
    if not (speech / "config.json").exists() or not list(speech.glob("*.safetensors")):
        problems.append("speech_tokenizer/ (needed to encode reference audio) is missing")
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
        self._lock = threading.Lock()

    def spec(self, model_id: str) -> ModelSpec:
        spec = get_spec(model_id, self.catalog)
        if spec is None:
            raise NotFound("Model", model_id)
        return spec

    def model_dir(self, model_id: str) -> Path:
        return self.models_dir / self.spec(model_id).id

    def is_installed(self, model_id: str) -> bool:
        return self.status(model_id)["state"] == "installed"

    def status(self, model_id: str) -> dict[str, Any]:
        spec = self.spec(model_id)
        path = self.models_dir / spec.id
        with self._lock:
            download = self._downloads.get(model_id)
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
        problems = validate_model_dir(path)
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
        spec = self.spec(model_id)
        with self._lock:
            current = self._downloads.get(model_id)
            if current and current["state"] == "downloading":
                raise Conflict("download_in_progress", f"{spec.label} is already downloading.")
            if any(d["state"] == "downloading" for d in self._downloads.values()):
                raise Conflict(
                    "download_in_progress", "Another model is downloading. Wait for it to finish."
                )
        target = self.models_dir / spec.id
        target.mkdir(parents=True, exist_ok=True)
        total = self._remote_size(spec.repo_id)
        free = shutil.disk_usage(self.models_dir).free
        if total and total - dir_size(target) > free:
            raise StudioError(
                "insufficient_disk",
                f"Not enough free disk space: {total / 1e9:.1f} GB needed, {free / 1e9:.1f} GB free.",
            )
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
        proc = entry["proc"]
        proc.join()
        target = self.models_dir / spec.id
        with self._lock:
            if entry.get("cancelled"):
                self._downloads.pop(model_id, None)
                return
            if proc.exitcode == 0 and not validate_model_dir(target):
                (target / MARKER).write_text(
                    json.dumps(
                        {"repo_id": spec.repo_id, "installed_at": now_iso(), "source": "download"},
                        indent=2,
                    )
                )
                self._downloads.pop(model_id, None)
                log.info("downloaded %s", spec.repo_id)
            else:
                problems = validate_model_dir(target)
                entry["state"] = "failed"
                entry["error"] = (
                    f"Download stopped (exit code {proc.exitcode}). Retry to resume where it left off."
                    if proc.exitcode != 0
                    else "Downloaded files are incomplete: " + "; ".join(problems)
                )
                entry["downloaded_bytes"] = dir_size(target)

    def cancel_download(self, model_id: str) -> None:
        with self._lock:
            entry = self._downloads.get(model_id)
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
        for model_id in list(self._downloads):
            self.cancel_download(model_id)

    def wait_idle(self, timeout: float = 30) -> None:
        """Test helper: wait until no download is running."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not any(d["state"] == "downloading" for d in self._downloads.values()):
                    return
            time.sleep(0.1)
