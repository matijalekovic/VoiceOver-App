"""The inference worker: a child process that owns the one loaded model.

Running inference in its own process means:
- unloading a model always returns its memory to macOS (the process exits);
- a Metal out-of-memory crash takes down the worker, not the API, and is reported as an error;
- a stuck generation can be stopped by ending the process.

Messages over the pipe are plain dicts. Requests carry "op"; replies carry "type"
("ok", "progress", "result", "error").
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from ..errors import EngineError, JobCancelled
from .metal import apply_kernel_workaround

log = logging.getLogger("voice_studio.inference")


def _peak_rss_bytes() -> int:
    if sys.platform == "win32":  # no `resource` module on Windows
        import psutil

        return int(psutil.Process().memory_info().peak_wset)
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)  # macOS reports bytes, Linux KiB


def _watch_parent(parent_pid: int) -> None:
    # If the API process dies without stopping us, exit instead of holding GPU memory.
    # Windows never re-parents orphans, so check that the parent still exists.
    import psutil

    while True:
        if os.getppid() != parent_pid or not psutil.pid_exists(parent_pid):
            os._exit(0)
        time.sleep(1.0)


def worker_main(
    conn, cancel_event, parent_pid: int, log_file: str
) -> None:  # pragma: no cover - runs in the child
    # Inference must never reach the network; downloads happen in the API process.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [inference] %(message)s",
    )
    threading.Thread(target=_watch_parent, args=(parent_pid,), daemon=True).start()
    if os.environ.get("VOICE_STUDIO_DEVICE") == "cpu":
        # Run on the CPU even where a GPU exists: for machines whose GPU cannot run the
        # model, such as the virtual GPUs of CI runners. Slow, but correct.
        from ..platform import USES_MLX

        if USES_MLX:
            import mlx.core as mx

            mx.set_default_device(mx.cpu)
        log.info("VOICE_STUDIO_DEVICE=cpu: running inference on the CPU")

    import numpy as np
    import soundfile as sf

    from .engine import ChunkRequest, CloneReference, create_engine

    engine = None
    info = None

    def send(message: dict[str, Any]) -> None:
        conn.send(message)

    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            break
        op = msg.get("op")
        try:
            if op == "load":
                started = time.monotonic()
                engine = create_engine(msg["engine"])
                info = engine.load(Path(msg["model_dir"]))
                log.info("loaded %s in %.1fs", msg["model_dir"], time.monotonic() - started)
                send(
                    {
                        "type": "ok",
                        "info": info.__dict__,
                        "load_seconds": round(time.monotonic() - started, 2),
                        "memory": {**engine.memory(), "rss_peak_bytes": _peak_rss_bytes()},
                    }
                )
            elif op == "synthesize":
                if engine is None or info is None:
                    raise EngineError("model_not_loaded", "No model is loaded.")
                out_dir = Path(msg["out_dir"])
                out_dir.mkdir(parents=True, exist_ok=True)
                reference = CloneReference(**msg["reference"]) if msg.get("reference") else None
                chunks: list[str] = msg["chunks"]
                seed = msg.get("seed")
                seed_step = int(msg.get("seed_step", 1))
                engine.reset_peak_memory()
                started = time.monotonic()
                files: list[str] = []
                chunk_seconds: list[float] = []
                audio_seconds = 0.0
                for index, text in enumerate(chunks):
                    if cancel_event.is_set():
                        send({"type": "result", "cancelled": True})
                        break
                    send(
                        {
                            "type": "progress",
                            "chunk": index,
                            "chunks": len(chunks),
                            "audio_seconds": round(audio_seconds, 2),
                        }
                    )
                    chunk_started = time.monotonic()
                    audio = engine.synthesize(
                        ChunkRequest(
                            text=text,
                            language=msg["language"],
                            reference=reference,
                            seed=None if seed is None else seed + index * seed_step,
                            temperature=msg.get("temperature"),
                            top_p=msg.get("top_p"),
                            instructions=msg.get("instructions"),
                        )
                    )
                    path = out_dir / f"chunk-{index:04d}.wav"
                    sf.write(
                        str(path),
                        np.asarray(audio, dtype=np.float32),
                        info.sample_rate,
                        subtype="FLOAT",
                    )
                    files.append(str(path))
                    chunk_seconds.append(round(time.monotonic() - chunk_started, 3))
                    audio_seconds += len(audio) / info.sample_rate
                else:
                    elapsed = time.monotonic() - started
                    memory = engine.memory()
                    engine.release_cache()
                    send(
                        {
                            "type": "result",
                            "cancelled": False,
                            "files": files,
                            "sample_rate": info.sample_rate,
                            "elapsed_s": round(elapsed, 3),
                            "chunk_seconds": chunk_seconds,
                            "audio_seconds": round(audio_seconds, 3),
                            "real_time_factor": round(elapsed / audio_seconds, 3)
                            if audio_seconds
                            else None,
                            "memory": {**memory, "rss_peak_bytes": _peak_rss_bytes()},
                        }
                    )
            elif op == "transcribe":
                transcriber = create_engine(msg["engine"])
                started = time.monotonic()
                segments = transcriber.transcribe(
                    Path(msg["model_dir"]), Path(msg["audio_path"]), msg.get("language")
                )
                log.info("transcribed %s in %.1fs", msg["audio_path"], time.monotonic() - started)
                send({"type": "ok", "segments": segments})
            elif op == "memory":
                send(
                    {
                        "type": "ok",
                        "memory": {
                            **(engine.memory() if engine else {}),
                            "rss_peak_bytes": _peak_rss_bytes(),
                        },
                    }
                )
            elif op == "shutdown":
                send({"type": "ok"})
                break
            else:
                raise EngineError("bad_request", f"Unknown worker operation {op!r}.")
        except EngineError as exc:
            log.warning("%s: %s", exc.code, exc.message)
            send(
                {"type": "error", "code": exc.code, "message": exc.message, "details": exc.details}
            )
        except MemoryError:
            send(
                {
                    "type": "error",
                    "code": "out_of_memory",
                    "message": "The model ran out of memory.",
                }
            )
        except Exception as exc:  # noqa: BLE001 - every failure must reach the UI as a structured error
            log.exception("inference failure")
            send(
                {
                    "type": "error",
                    "code": "engine_failure",
                    "message": f"Inference failed: {exc}",
                    "details": traceback.format_exc()[-4000:],
                }
            )


class InferenceClient:
    """API-side handle on the worker process. All model work is serialised through it."""

    def __init__(self, log_file: Path):
        self._ctx = mp.get_context("spawn")
        self._log_file = log_file
        self._lock = threading.RLock()
        self._proc: Any = None
        self._conn: Any = None
        self._cancel: Any = None  # created with each worker process
        self._force_stopped = False
        self.loaded: dict[str, Any] | None = None
        self.state = "stopped"  # stopped | loading | ready | busy
        self.last_used = time.monotonic()
        self.last_memory: dict[str, Any] = {}

    # -- process lifecycle -------------------------------------------------
    def _start(self) -> None:
        apply_kernel_workaround()  # the spawned worker inherits the environment it sets
        self._cancel = self._ctx.Event()
        parent_conn, child_conn = self._ctx.Pipe()
        proc = self._ctx.Process(
            target=worker_main,
            args=(child_conn, self._cancel, os.getpid(), str(self._log_file)),
            name="voice-studio-inference",
            daemon=True,
        )
        proc.start()
        child_conn.close()
        self._proc, self._conn = proc, parent_conn
        self._force_stopped = False

    def _stop(self) -> None:
        proc, conn = self._proc, self._conn
        self._proc = self._conn = None
        self.loaded = None
        self.state = "stopped"
        if proc is None:
            return
        try:
            if proc.is_alive() and conn is not None:
                conn.send({"op": "shutdown"})
                if conn.poll(5):
                    conn.recv()
        except (OSError, EOFError, BrokenPipeError):
            pass
        proc.join(5)
        if proc.is_alive():
            proc.terminate()
            proc.join(3)
        if proc.is_alive():
            proc.kill()
            proc.join(2)
        if conn is not None:
            conn.close()

    def _request(self, message: dict[str, Any], on_progress=None) -> dict[str, Any]:
        assert self._proc is not None and self._conn is not None
        self._conn.send(message)
        while True:
            try:
                # On Windows poll() itself raises once the worker is gone (WinError 109).
                reply = self._conn.recv() if self._conn.poll(0.2) else None
            except (EOFError, OSError):
                reply = None
                self._proc.join(1)  # let it finish exiting, so the check below sees it
            if reply is not None:
                if reply.get("type") == "progress":
                    if on_progress:
                        on_progress(reply)
                    continue
                return reply
            if not self._proc.is_alive():
                exit_code = self._proc.exitcode
                forced = self._force_stopped
                self._stop()
                if forced:
                    raise JobCancelled()
                # A negative exit code means a signal; SIGKILL (-9) is how macOS ends a
                # process under memory pressure.
                hint = (
                    "macOS most likely stopped it for using too much memory: close other apps, "
                    "use the lightweight model, or generate shorter text."
                    if exit_code is not None and exit_code < 0
                    else "See Settings → Storage & logs → Engine for details."
                )
                raise EngineError(
                    "engine_crashed",
                    f"The inference process stopped unexpectedly (exit code {exit_code}). {hint}",
                )

    # -- public API --------------------------------------------------------
    def ensure_loaded(self, model_id: str, engine: str, model_dir: Path) -> dict[str, Any]:
        with self._lock:
            if (
                self.loaded
                and self.loaded["model_id"] == model_id
                and self._proc
                and self._proc.is_alive()
            ):
                return self.loaded
            # Never two models at once: stop the current worker before starting another.
            self._stop()
            self.state = "loading"
            self._start()
            try:
                reply = self._request({"op": "load", "engine": engine, "model_dir": str(model_dir)})
            except BaseException:
                self._stop()
                raise
            if reply["type"] == "error":
                self._stop()
                raise EngineError(reply["code"], reply["message"], reply.get("details"))
            self.loaded = {
                "model_id": model_id,
                "info": reply["info"],
                "load_seconds": reply["load_seconds"],
                "loaded_at": time.time(),
            }
            self.last_memory = reply.get("memory", {})
            self.state = "ready"
            self.last_used = time.monotonic()
            return self.loaded

    def synthesize(self, request: dict[str, Any], on_progress=None) -> dict[str, Any]:
        with self._lock:
            if not self.loaded or self._proc is None:
                raise EngineError("model_not_loaded", "No model is loaded.")
            self._cancel.clear()
            self.state = "busy"
            try:
                reply = self._request({"op": "synthesize", **request}, on_progress)
            finally:
                if self.state == "busy":
                    self.state = "ready"
                self.last_used = time.monotonic()
            if reply["type"] == "error":
                raise EngineError(reply["code"], reply["message"], reply.get("details"))
            if reply.get("cancelled"):
                raise JobCancelled()
            self.last_memory = reply.get("memory", {})
            return reply

    def transcribe(
        self, engine: str, model_dir: Path, audio_path: Path, language: str | None
    ) -> list[dict[str, Any]]:
        """Run speech-to-text in the worker. The voice model, if loaded, stays loaded."""
        with self._lock:
            if self._proc is None or not self._proc.is_alive():
                self._stop()
                self._start()
            previous = self.state
            self.state = "busy"
            try:
                reply = self._request(
                    {
                        "op": "transcribe",
                        "engine": engine,
                        "model_dir": str(model_dir),
                        "audio_path": str(audio_path),
                        "language": language,
                    }
                )
            finally:
                if self.state == "busy":
                    self.state = previous if self.loaded else "stopped"
                self.last_used = time.monotonic()
            if reply["type"] == "error":
                raise EngineError(reply["code"], reply["message"], reply.get("details"))
            return reply["segments"]

    def cancel_current(self) -> None:
        """Stop after the chunk being synthesised (keeps the model loaded)."""
        if self._cancel is not None:
            self._cancel.set()

    def force_stop(self) -> None:
        """Stop immediately by ending the worker; the model has to be loaded again."""
        self.cancel_current()
        proc = self._proc
        if proc is not None and proc.is_alive():
            self._force_stopped = True
            proc.kill()

    def unload(self) -> None:
        with self._lock:
            self._stop()

    def worker_pid(self) -> int | None:
        proc = self._proc
        return proc.pid if proc is not None and proc.is_alive() else None
