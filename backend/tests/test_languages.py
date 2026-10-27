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


def _profile(client, voice_id: str, language: str) -> dict:
    voice = client.get(f"/api/voices/{voice_id}").json()
    return next(p for p in voice["languages"] if p["language"] == language)


def test_language_profile_takes_are_scored_and_the_closest_is_continued(client, tmp_path):
    voice = make_voice(client, tmp_path)
    vid = voice["id"]
    job = client.post(f"/api/voices/{vid}/languages", json={"language": "spanish"}).json()
    assert wait_job(client, job["job_id"])["status"] == "completed"
    profile = _profile(client, vid, "spanish")
    assert profile["accent"] == "native" and len(profile["takes"]) == 4
    ranks = [t["rank"] for t in profile["takes"]]
    assert ranks == sorted(ranks, reverse=True)
    assert profile["demo_generation_id"] == profile["takes"][0]["generation_id"]
    assert profile["takes"][0]["similarity"] == 1.0  # the fake engine's one speaker

    spanish = _generate(client, vid, "spanish")
    # Continues the chosen take, so every chunk keeps its register and accent.
    assert spanish["params"]["method"] == "anchor" and spanish["params"]["fingerprint"] is False
    english = _generate(client, vid, "english")
    assert english["params"]["method"] == "recording"
    # A tone still needs the fingerprint, the only mode that takes an instruction.
    calm = _generate(client, vid, "spanish", tone="Calm.")
    assert calm["params"]["method"] == "fingerprint"

    other = profile["takes"][2]["generation_id"]
    res = client.patch(f"/api/voices/{vid}/languages/spanish", json={"take_id": other})
    assert res.status_code == 200 and res.json()["demo_generation_id"] == other
    bad = client.patch(f"/api/voices/{vid}/languages/spanish", json={"take_id": "nope"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "unknown_take"

    # A new round replaces the old takes, except the one chosen.
    job = client.post(f"/api/voices/{vid}/languages", json={"language": "spanish"}).json()
    assert wait_job(client, job["job_id"])["status"] == "completed"
    takes = [t["generation_id"] for t in _profile(client, vid, "spanish")["takes"]]
    assert len(takes) == 5 and other in takes
    gone = profile["takes"][1]["generation_id"]
    assert client.get(f"/api/generations/{gone}").status_code == 404


def test_carried_accent_continues_the_real_recording(client, tmp_path):
    voice = make_voice(client, tmp_path)
    vid = voice["id"]
    job = client.post(
        f"/api/voices/{vid}/languages", json={"language": "french", "accent": "carried"}
    ).json()
    assert wait_job(client, job["job_id"])["status"] == "completed"
    assert _profile(client, vid, "french")["accent"] == "carried"
    french = _generate(client, vid, "french")
    assert french["params"]["method"] == "carried" and french["params"]["fingerprint"] is False

    client.patch(f"/api/voices/{vid}/languages/french", json={"accent": "native"})
    assert _generate(client, vid, "french")["params"]["method"] == "anchor"


def test_language_delivery_overrides_the_voice(client, tmp_path):
    voice = make_voice(client, tmp_path)
    vid = voice["id"]
    job = client.post(f"/api/voices/{vid}/languages", json={"language": "spanish"}).json()
    wait_job(client, job["job_id"])
    res = client.patch(f"/api/voices/{vid}/languages/spanish", json={"style": {"speed": 1.1}})
    assert res.json()["style"] == {"speed": 1.1}
    assert _generate(client, vid, "spanish")["params"]["speed"] == 1.1
    assert _generate(client, vid, "english")["params"]["speed"] == 1.0
    # The generation's own setting still wins.
    assert _generate(client, vid, "spanish", style={"speed": 0.9})["params"]["speed"] == 0.9
    client.patch(f"/api/voices/{vid}/languages/spanish", json={"style": {}})
    assert _generate(client, vid, "spanish")["params"]["speed"] == 1.0


def test_off_voice_chunks_are_generated_again(client, tmp_path):
    voice = make_voice(client, tmp_path)
    # Each sentence is one chunk of over two seconds, long enough to be measured.
    text = (
        "WOBBLE this sentence is long enough for its pitch to be measured, at about two seconds. "
        "This second sentence is also long enough for its pitch to be measured reliably."
    )
    take = _generate(client, voice["id"], "english", text=text)
    score, *rest = take["stats"]["chunk_scores"]  # the first chunk holds "WOBBLE"
    assert score["attempts"] == 2  # its first attempt came out a fifth up
    assert all(s is None or s["attempts"] == 1 for s in rest)
    assert abs(score["f0_hz"] - 220) < 5 and abs(score["register_st"]) < 4

    steady = _generate(client, voice["id"], "english", text=text.replace("WOBBLE", "Steady"))
    assert steady["stats"]["chunk_scores"][0]["attempts"] == 1
