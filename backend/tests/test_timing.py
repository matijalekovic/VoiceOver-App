from __future__ import annotations

import numpy as np
from conftest import make_voice, wait_job

from voice_studio import timing

SR = 24_000


def _parts(n=4, speech_s=2.0, pause_s=0.5):
    tone = (0.3 * np.sin(2 * np.pi * 200 * np.arange(int(SR * speech_s)) / SR)).astype(np.float32)
    return [(tone, pause_s) for _ in range(n)]  # 8 s of speech, 1.5 s of pauses


def test_fit_uses_pauses_first_then_tempo():
    out, info = timing.fit(_parts(), SR, 9.0, pitch=0)  # natural 9.5 s: pauses alone fix it
    assert info["within"] and abs(len(out) / SR - 9.0) < 0.3
    assert info["pause_scale"] < 1 and abs(info["speed"] - 1.0) < 0.01

    out, info = timing.fit(_parts(), SR, 7.5, pitch=0)  # needs more than pauses can give
    assert info["within"] and info["pause_scale"] == timing.PAUSE_SCALE[0] and info["speed"] > 1

    out, info = timing.fit(_parts(), SR, 3.0, pitch=0)  # impossible without sounding rushed
    assert not info["within"] and info["speed"] == timing.FIT_SPEED[1]
    assert len(out) / SR > 3.0


def test_estimate_learns_the_voices_pace():
    assert timing.speaking_rate([], "english") == (timing.TYPICAL_WORDS_PER_S, "typical")
    history = [{"text": " ".join(["word"] * 30), "duration_s": 10.0}]
    assert timing.speaking_rate(history, "english") == (3.0, "voice")
    assert timing.units("你好世界", "chinese") == 4


def test_generate_to_a_target_length(client, tmp_path):
    voice = make_voice(client, tmp_path)
    text = "First sentence here. Second one follows. A third one ends it."
    natural = client.post(
        "/api/generate", json={"text": text, "voice_id": voice["id"], "language": "english"}
    ).json()
    job = wait_job(client, natural["job_id"])
    natural_s = client.get(f"/api/generations/{job['generation_id']}").json()["duration_s"]

    target = round(natural_s * 0.9, 2)
    res = client.post(
        "/api/generate",
        json={
            "text": text,
            "voice_id": voice["id"],
            "language": "english",
            "target_seconds": target,
        },
    ).json()
    job = wait_job(client, res["job_id"])
    gen = client.get(f"/api/generations/{job['generation_id']}").json()
    assert gen["params"]["target_seconds"] == target
    assert gen["stats"]["fit"]["within"] and abs(gen["duration_s"] - target) < 0.35

    est = client.post(
        "/api/estimate", json={"voice_id": voice["id"], "text": text, "language": "english"}
    ).json()
    assert (
        est["basis"] in ("voice", "typical")
        and est["shortest_s"] < est["seconds"] < est["longest_s"]
    )
