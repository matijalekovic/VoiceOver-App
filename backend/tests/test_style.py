from __future__ import annotations

import numpy as np
from conftest import make_voice, speech_like_wav, wait_job

from voice_studio import audio
from voice_studio.style import DEFAULT_STYLE, resolve, sampling


def test_default_expressiveness_keeps_the_model_defaults():
    assert sampling(DEFAULT_STYLE["expressiveness"]) == {"temperature": 0.9, "top_p": 1.0}
    assert sampling(0)["temperature"] < 0.9 < sampling(1)["temperature"]


def test_resolve_layers_and_clamps():
    style = resolve({"speed": 1.1, "pitch": 5}, {"speed": None, "expressiveness": 0.2})
    assert style == {"expressiveness": 0.2, "speed": 1.1, "pitch": 2.0}


def test_tempo_and_pitch_change_length_as_expected():
    sr = 24_000
    tone = (0.3 * np.sin(2 * np.pi * 220 * np.arange(sr * 4) / sr)).astype(np.float32)
    faster = audio.change_tempo_pitch(tone, sr, speed=1.25, semitones=0)
    higher = audio.change_tempo_pitch(tone, sr, speed=1.0, semitones=2)
    assert abs(len(faster) / sr - 4 / 1.25) < 0.05
    assert abs(len(higher) / sr - 4) < 0.05
    assert audio.change_tempo_pitch(tone, sr, speed=1.0, semitones=0) is tone


def _generate(client, voice_id: str, **extra) -> dict:
    res = client.post(
        "/api/generate",
        json={
            "text": "Hello there, this is a test.",
            "voice_id": voice_id,
            "language": "english",
            "seed": 3,
            **extra,
        },
    )
    assert res.status_code == 202, res.text
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "completed", job
    return client.get(f"/api/generations/{job['generation_id']}").json()


def test_voice_defaults_and_overrides_shape_the_output(client, tmp_path):
    voice = make_voice(client, tmp_path)
    plain = _generate(client, voice["id"])
    assert plain["params"]["speed"] == 1.0 and plain["params"]["expressiveness"] == 0.6

    saved = client.patch(
        f"/api/voices/{voice['id']}", json={"style": {"speed": 1.25, "pitch": -1}}
    ).json()
    assert saved["style"] == {"expressiveness": 0.6, "speed": 1.25, "pitch": -1.0}
    faster = _generate(client, voice["id"])
    assert faster["params"]["speed"] == 1.25 and faster["params"]["pitch"] == -1.0
    assert faster["duration_s"] < plain["duration_s"] * 0.9

    # A generation's own settings win over the voice's defaults.
    slower = _generate(client, voice["id"], style={"speed": 0.8, "expressiveness": 0.1})
    assert slower["params"]["speed"] == 0.8 and slower["params"]["expressiveness"] == 0.1
    assert slower["duration_s"] > plain["duration_s"]


def test_kept_takes_survive_new_takes_and_can_be_used(client, tmp_path, data_dir):
    from conftest import install_fake_stt

    install_fake_stt(data_dir / "models")
    voice = make_voice(client, tmp_path)
    with open(speech_like_wav(tmp_path / "long.wav", seconds=60), "rb") as fh:
        client.post(
            f"/api/voices/{voice['id']}/references", files={"file": ("long.wav", fh, "audio/wav")}
        )
    vid = voice["id"]
    assert (
        wait_job(client, client.post(f"/api/voices/{vid}/create", json={}).json()["job_id"])[
            "status"
        ]
        == "completed"
    )
    first, second = client.get(f"/api/voices/{vid}").json()["clips"][:2]
    client.post(f"/api/voices/{vid}/clips/{first['id']}/choose")
    kept = client.patch(
        f"/api/voices/{vid}/clips/{second['id']}", json={"name": "Energetic", "kept": True}
    ).json()
    assert kept["kept"] and kept["name"] == "Energetic"

    assert (
        wait_job(client, client.post(f"/api/voices/{vid}/create", json={}).json()["job_id"])[
            "status"
        ]
        == "completed"
    )
    ids = {c["id"] for c in client.get(f"/api/voices/{vid}").json()["clips"]}
    assert {first["id"], second["id"]} <= ids

    generation = _generate(client, vid, clip_id=second["id"])
    assert generation["reference_id"] == second["id"]
