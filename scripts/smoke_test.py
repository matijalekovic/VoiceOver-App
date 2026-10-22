"""End-to-end check of an installed Voice Studio, run with the app's own Python runtime.

    <runtime python> scripts/smoke_test.py --reference speech.wav

It starts the engine on a scratch data folder and walks the path a new user takes:
download the lightweight voice model and speech recognition through the app's API,
create a voice from the recording (transcribe, cut takes, voice demos), keep a take,
then generate speech with it and check the audio. Used by CI after installing the built
installer; standard library only, apart from soundfile, which the runtime includes.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

TOKEN = "smoke-test"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Api:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"

    def call(self, method: str, path: str, body=None, raw: bytes | None = None, ctype=None):
        headers = {"Authorization": f"Bearer {TOKEN}"}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if ctype:
            headers["Content-Type"] = ctype
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                payload = res.read()
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode()[:500]}") from exc
        if res.headers.get("Content-Type", "").startswith("application/json"):
            return json.loads(payload)
        return payload

    def upload(self, path: str, file: Path, fields: dict[str, str]):
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in fields.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
            )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file.name}"\r\n'
            f"Content-Type: audio/wav\r\n\r\n".encode()
            + file.read_bytes()
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        return self.call(
            "POST", path, raw=b"".join(parts), ctype=f"multipart/form-data; boundary={boundary}"
        )


def wait(label: str, check, timeout_s: float, every_s: float = 3.0):
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        result = check()
        if result:
            print(f"  {label}: {time.monotonic() - started:.0f}s", flush=True)
            return result
        time.sleep(every_s)
    raise SystemExit(f"Timed out after {timeout_s:.0f}s: {label}")


def wait_job(api: Api, job_id: str, label: str, timeout_s: float) -> dict:
    def done():
        job = api.call("GET", f"/api/jobs/{job_id}")
        if job["status"] in ("failed", "cancelled"):
            raise SystemExit(f"{label} {job['status']}: {job.get('error_message')}")
        return job if job["status"] == "completed" else None

    return wait(label, done, timeout_s)


def download(api: Api, model_id: str, timeout_s: float) -> None:
    state = next(m for m in api.call("GET", "/api/models") if m["id"] == model_id)["status"]
    if state["state"] == "installed":
        print(f"  {model_id}: already installed")
        return
    api.call("POST", "/api/models/download", {"model_id": model_id})

    def installed():
        state = next(m for m in api.call("GET", "/api/models") if m["id"] == model_id)["status"]
        if state["state"] == "failed":
            raise SystemExit(f"Downloading {model_id} failed: {state.get('error')}")
        return state["state"] == "installed"

    wait(f"downloaded {model_id}", installed, timeout_s, every_s=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--model", default="qwen3-tts-0.6b-base-bf16")
    parser.add_argument("--language", default="english")
    parser.add_argument(
        "--models-from", type=Path, help="reuse already-downloaded models (local runs)"
    )
    args = parser.parse_args()

    data_dir = Path(tempfile.mkdtemp(prefix="voice-studio-smoke-"))
    if args.models_from:
        (data_dir / "models").mkdir()
        for model in args.models_from.iterdir():
            (data_dir / "models" / model.name).symlink_to(model, target_is_directory=True)
    port = free_port()
    env = {
        **os.environ,
        "VOICE_STUDIO_DATA_DIR": str(data_dir),
        "VOICE_STUDIO_TOKEN": TOKEN,
        "VOICE_STUDIO_PORT": str(port),
        "PYTHONUNBUFFERED": "1",
    }
    server = subprocess.Popen([sys.executable, "-m", "voice_studio"], env=env)
    api = Api(port)
    try:

        def healthy():
            try:
                return api.call("GET", "/api/health")
            except (OSError, SystemExit):
                return None

        print("Engine", flush=True)
        wait("engine started", healthy, 120, every_s=1)
        status = api.call("GET", "/api/system/status")
        print(
            f"  accelerator: {status['engine']['accelerator']}, runtime available: {status['engine']['runtime_available']}"
        )
        if not status["engine"]["runtime_available"]:
            raise SystemExit("The inference runtime is not installed.")

        print("Models", flush=True)
        download(api, args.model, 1800)
        download(api, "whisper-large-v3-turbo", 1800)
        api.call("PUT", "/api/settings", {"default_model_id": args.model})

        print("Voice", flush=True)
        voice = api.call(
            "POST",
            "/api/voices",
            {
                "name": "Smoke test",
                "language": args.language,
                "consent": {
                    "confirmed": True,
                    "speaker": "Synthetic test voice",
                    "scope": "Automated testing",
                },
            },
        )
        api.upload(f"/api/voices/{voice['id']}/references", args.reference, {})
        job = api.call("POST", f"/api/voices/{voice['id']}/create", {"model_id": args.model})
        wait_job(api, job["job_id"], "created voice (transcribed, cut takes, voiced demos)", 1800)
        voice = api.call("GET", f"/api/voices/{voice['id']}")
        clips = voice["clips"]
        print(f"  {len(clips)} takes; first: “{clips[0]['transcript'][:70]}”")
        if not clips or not all(c["demo_generation_id"] for c in clips):
            raise SystemExit("Creating the voice produced no takes with demos.")
        api.call("POST", f"/api/voices/{voice['id']}/clips/{clips[0]['id']}/choose")

        print("Generate", flush=True)
        job = api.call(
            "POST",
            "/api/generate",
            {
                "text": "This is an automated check that speech generation works.",
                "voice_id": voice["id"],
                "language": args.language,
            },
        )
        done = wait_job(api, job["job_id"], "generated speech", 1800)
        generation = api.call("GET", f"/api/generations/{done['generation_id']}")
        audio_path = data_dir / "check.wav"
        audio_path.write_bytes(api.call("GET", f"/api/generations/{generation['id']}/audio"))

        import numpy as np
        import soundfile as sf

        samples, sample_rate = sf.read(str(audio_path), dtype="float32")
        rms = float(np.sqrt(np.mean(samples**2)))
        stats = generation.get("stats") or {}
        print(
            f"  {len(samples) / sample_rate:.1f}s of audio, rms {20 * np.log10(rms + 1e-9):.0f} dB, "
            f"real-time factor {stats.get('real_time_factor')}"
        )
        if len(samples) / sample_rate < 1 or rms < 0.005:
            raise SystemExit("The generated audio is empty or silent.")
        print("Smoke test passed.")
    finally:
        server.terminate()
        try:
            server.wait(30)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
