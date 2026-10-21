from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))

from voice_studio.app import create_app  # noqa: E402
from voice_studio.catalog import ModelSpec  # noqa: E402
from voice_studio.config import Paths, Settings  # noqa: E402

TOKEN = "test-token"
FAKE_MODEL = "fake-base"


def fake_catalog() -> list[ModelSpec]:
    return [
        ModelSpec(
            id=FAKE_MODEL,
            label="Fake Base",
            repo_id="example/fake-base",
            tier="quality",
            parameters="0",
            quantization="none",
            approx_download_gb=0,
            approx_memory_gb=0,
            engine="fake_engine:FakeEngine",
        )
    ]


def install_fake_model(models_dir: Path) -> None:
    folder = models_dir / FAKE_MODEL
    (folder / "speech_tokenizer").mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(json.dumps({"tts_model_type": "base"}))
    (folder / "model.safetensors").write_bytes(b"0")
    (folder / "tokenizer.json").write_text("{}")
    (folder / "speech_tokenizer" / "config.json").write_text("{}")
    (folder / "speech_tokenizer" / "model.safetensors").write_bytes(b"0")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def client(data_dir: Path, tmp_path: Path, monkeypatch):
    # The worker is a spawned process: it finds fake_engine through PYTHONPATH.
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    settings = Settings(paths=Paths(data_dir), token=TOKEN, port=8765)
    app = create_app(settings, catalog=fake_catalog())
    studio = app.state.studio
    studio.db.set_settings(
        {
            "default_model_id": FAKE_MODEL,
            "output_dir": str(tmp_path / "exports"),
            "max_chunk_chars": 120,
        }
    )
    install_fake_model(settings.paths.models)
    with TestClient(app, base_url="http://127.0.0.1:8765") as test_client:
        test_client.headers["Authorization"] = f"Bearer {TOKEN}"
        yield test_client


def speech_like_wav(path: Path, seconds: float = 12.0, sr: int = 44_100) -> Path:
    """A voiced-ish signal with silence at both ends, so trimming has something to do."""
    t = np.arange(int(sr * seconds)) / sr
    voice = 0.4 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))
    noise = 0.001 * np.random.default_rng(0).standard_normal(len(t))
    pad = np.zeros(int(sr * 1.0))
    signal = np.concatenate([pad, voice + noise, pad]).astype(np.float32)
    sf.write(str(path), signal, sr)
    return path


def wait_job(client: TestClient, job_id: str, timeout: float = 60) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish: {job}")


def make_voice(client: TestClient, tmp_path: Path, transcript: str = "This is my voice.") -> dict:
    voice = client.post(
        "/api/voices",
        json={
            "name": "Ana",
            "language": "english",
            "consent": {"confirmed": True, "speaker": "Ana Example", "scope": "Internal narration"},
        },
    ).json()
    wav = speech_like_wav(tmp_path / "ref.wav")
    with open(wav, "rb") as fh:
        res = client.post(
            f"/api/voices/{voice['id']}/references",
            files={"file": ("ref.wav", fh, "audio/wav")},
            data={"transcript": transcript},
        )
    assert res.status_code == 201, res.text
    return client.get(f"/api/voices/{voice['id']}").json()
