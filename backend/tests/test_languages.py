from __future__ import annotations

import json

import soundfile as sf
from conftest import install_fake_stt, make_voice, speech_like_wav, wait_job


def _generate(client, voice_id: str, language: str, **extra) -> dict:
    res = client.post(
        "/api/generate",
        json={"text": "Hello there.", "voice_id": voice_id, "language": language, **extra},
    )
    assert res.status_code == 202, res.text
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "completed", job
    return client.get(f"/api/generations/{job['generation_id']}").json()


def test_other_languages_and_tones_use_the_voice_fingerprint(client, tmp_path):
    voice = make_voice(client, tmp_path)  # an English recording
    own = _generate(client, voice["id"], "english")
    assert own["params"]["fingerprint"] is False  # continues the recording, most faithful

    spanish = _generate(client, voice["id"], "spanish")
    assert spanish["params"]["fingerprint"] is True  # no English accent carried over

    cheerful = _generate(client, voice["id"], "english", tone="Cheerful and bright.")
    assert cheerful["params"]["fingerprint"] is True
    assert cheerful["params"]["tone"] == "Cheerful and bright."


def test_language_versions(client, tmp_path):
    voice = make_voice(client, tmp_path)
    vid = voice["id"]
    same = client.post(f"/api/voices/{vid}/languages", json={"language": "english"})
    assert same.status_code == 400 and same.json()["error"]["code"] == "same_language"

    job = client.post(f"/api/voices/{vid}/languages", json={"language": "Spanish"}).json()
    assert wait_job(client, job["job_id"])["status"] == "completed"
    versions = client.get(f"/api/voices/{vid}").json()["languages"]
    assert [v["language"] for v in versions] == ["spanish"]
    demo = client.get(f"/api/generations/{versions[0]['demo_generation_id']}").json()
    assert demo["language"] == "spanish" and demo["params"]["fingerprint"] is True
    assert client.get("/api/voices").json()[0]["languages"][0]["language"] == "spanish"

    assert client.delete(f"/api/voices/{vid}/languages/spanish").status_code == 204
    assert client.get(f"/api/voices/{vid}").json()["languages"] == []


def test_fingerprint_is_read_from_the_voices_takes(client, tmp_path, data_dir):
    install_fake_stt(data_dir / "models")
    voice = client.post(
        "/api/voices",
        json={
            "name": "Ana",
            "language": "english",
            "consent": {"confirmed": True, "speaker": "Ana Example", "scope": "Internal narration"},
        },
    ).json()
    vid = voice["id"]
    with open(speech_like_wav(tmp_path / "long.wav", seconds=120), "rb") as fh:
        client.post(f"/api/voices/{vid}/references", files={"file": ("long.wav", fh, "audio/wav")})
    assert (
        wait_job(client, client.post(f"/api/voices/{vid}/create", json={}).json()["job_id"])[
            "status"
        ]
        == "completed"
    )
    clips = client.get(f"/api/voices/{vid}").json()["clips"]
    client.post(f"/api/voices/{vid}/clips/{clips[0]['id']}/choose")

    _generate(client, vid, "french")
    folder = data_dir / "voices" / vid
    sources = json.loads((folder / "fingerprint.json").read_text())
    assert len(sources) == len(clips) and sources[0].endswith(f"{clips[0]['id']}.wav")
    info = sf.info(str(folder / "fingerprint.wav"))
    assert info.frames / info.samplerate <= 60.5
