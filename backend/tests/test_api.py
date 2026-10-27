from __future__ import annotations

import time
from pathlib import Path

import soundfile as sf
from conftest import FAKE_MODEL, make_voice, speech_like_wav, wait_job

from voice_studio.catalog import QWEN3_LANGUAGES


def test_requests_need_token_and_loopback_host(client):
    assert client.get("/api/voices", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/voices", headers={"Host": "evil.example:8765"}).status_code == 403
    assert client.get("/api/voices", headers={"Origin": "https://evil.example"}).status_code == 403
    allowed = client.get("/api/voices", headers={"Origin": "tauri://localhost"})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "tauri://localhost"


def test_voice_requires_consent(client):
    res = client.post(
        "/api/voices",
        json={
            "name": "X",
            "language": "english",
            "consent": {"confirmed": False, "speaker": "X", "scope": "Y"},
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_request"


def test_reference_is_converted_trimmed_and_analysed(client, tmp_path):
    voice = make_voice(client, tmp_path)
    ref = voice["references"][0]
    assert voice["primary_reference_id"] == ref["id"]
    assert 11.5 <= ref["source_duration_s"] <= 14.5
    assert ref["duration_s"] < ref["source_duration_s"]  # leading/trailing silence trimmed
    audio_res = client.get(f"/api/voices/{voice['id']}/references/{ref['id']}/audio")
    assert audio_res.status_code == 200
    out = tmp_path / "check.wav"
    out.write_bytes(audio_res.content)
    info = sf.info(str(out))
    assert info.samplerate == 24_000 and info.channels == 1

    trimmed = client.patch(
        f"/api/voices/{voice['id']}/references/{ref['id']}",
        json={"trim_start_s": 2.0, "trim_end_s": 8.0},
    ).json()
    assert abs(trimmed["duration_s"] - 6.0) < 0.05

    ready = client.patch(f"/api/voices/{voice['id']}", json={"status": "ready"})
    assert ready.status_code == 200 and ready.json()["status"] == "ready"


def test_voice_without_transcript_cannot_generate(client, tmp_path):
    voice = make_voice(client, tmp_path, transcript="")
    res = client.post(
        "/api/generate", json={"text": "Hi", "voice_id": voice["id"], "language": "english"}
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "transcript_required"


def test_generate_runs_through_worker_and_exports(client, tmp_path):
    voice = make_voice(client, tmp_path)
    body = "First sentence here. Second sentence here.\n\nA new paragraph follows."
    res = client.post(
        "/api/generate",
        json={"text": body, "voice_id": voice["id"], "language": "english", "seed": 7},
    )
    assert res.status_code == 202
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "completed", job
    generation_id = job["generation_id"]

    generation = client.get(f"/api/generations/{generation_id}").json()
    assert generation["voice_name"] == "Ana" and generation["params"]["seed"] == 7
    assert generation["stats"]["chunks"] >= 2 and generation["stats"]["audio_seconds"] > 0
    assert generation["duration_s"] > 1

    status = client.get("/api/system/status").json()
    assert (
        status["engine"]["state"] == "ready" and status["engine"]["loaded_model_id"] == FAKE_MODEL
    )

    history = client.get("/api/generations").json()
    assert history["total"] == 1

    wav = client.post(f"/api/generations/{generation_id}/export", json={"format": "wav"}).json()
    mp3 = client.post(
        f"/api/generations/{generation_id}/export", json={"format": "mp3", "bitrate": 192}
    ).json()
    assert Path(wav["paths"][0]).suffix == ".wav" and Path(wav["paths"][0]).stat().st_size > 1000
    assert Path(mp3["paths"][0]).suffix == ".mp3" and Path(mp3["paths"][0]).stat().st_size > 1000


def test_cancel_queued_and_running_jobs(client, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ENGINE_DELAY", "0.4")
    client.post("/api/models/unload")  # next load picks up the delay
    voice = make_voice(client, tmp_path)
    long_text = " ".join(f"Sentence number {i} is here." for i in range(30))
    first = client.post(
        "/api/generate", json={"text": long_text, "voice_id": voice["id"], "language": "english"}
    )
    second = client.post(
        "/api/generate", json={"text": "Queued.", "voice_id": voice["id"], "language": "english"}
    )
    queued = client.post(f"/api/jobs/{second.json()['job_id']}/cancel").json()
    assert queued["status"] == "cancelled"

    first_id = first.json()["job_id"]
    deadline = time.monotonic() + 30
    while client.get(f"/api/jobs/{first_id}").json()["status"] != "synthesizing":
        assert time.monotonic() < deadline
        time.sleep(0.05)
    client.post(f"/api/jobs/{first_id}/cancel")
    job = wait_job(client, first_id)
    assert job["status"] == "cancelled"
    # Cooperative cancel keeps the model loaded.
    assert client.get("/api/system/status").json()["engine"]["state"] == "ready"


def test_worker_crash_is_reported_and_retryable(client, tmp_path):
    voice = make_voice(client, tmp_path)
    res = client.post(
        "/api/generate", json={"text": "CRASH now.", "voice_id": voice["id"], "language": "english"}
    )
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "failed" and job["error_code"] == "engine_crashed"
    assert client.get("/api/system/status").json()["engine"]["state"] == "stopped"

    ok = client.post(
        "/api/generate", json={"text": "Fine.", "voice_id": voice["id"], "language": "english"}
    )
    assert wait_job(client, ok.json()["job_id"])["status"] == "completed"
    retried = client.post(f"/api/jobs/{job['id']}/retry").json()
    assert retried["status"] in ("queued", "loading", "synthesizing")


def test_project_workflow(client, tmp_path):
    voice = make_voice(client, tmp_path)
    script = "Opening line. Second line.\n\nMiddle paragraph here.\n\nClosing words."
    project = client.post(
        "/api/projects",
        json={
            "name": "Promo",
            "script": script,
            "voice_id": voice["id"],
            "language": "english",
            "segmentation": "sentence",
        },
    ).json()
    assert [s["text"] for s in project["segments"]] == [
        "Opening line.", "Second line.", "Middle paragraph here.", "Closing words.",
    ]  # fmt: skip
    pid = project["id"]

    jobs = client.post(f"/api/projects/{pid}/generate", json={}).json()
    assert len(jobs) == 4
    for job in jobs:
        assert wait_job(client, job["id"])["status"] == "completed"
    project = client.get(f"/api/projects/{pid}").json()
    assert project["generated_count"] == 4

    # Regenerate one segment only: it gains a second take; others are untouched.
    target = project["segments"][1]
    others_before = {
        s["id"]: s["active_generation_id"] for s in project["segments"] if s["id"] != target["id"]
    }
    regen = client.post(
        f"/api/projects/{pid}/generate", json={"segment_ids": [target["id"]]}
    ).json()
    assert len(regen) == 1
    wait_job(client, regen[0]["id"])
    project = client.get(f"/api/projects/{pid}").json()
    seg = next(s for s in project["segments"] if s["id"] == target["id"])
    assert len(seg["takes"]) == 2 and seg["active_generation_id"] != target["active_generation_id"]
    assert {
        s["id"]: s["active_generation_id"] for s in project["segments"] if s["id"] != target["id"]
    } == others_before

    # Pick the earlier take again, edit text (stale), adjust a pause, reorder.
    client.patch(
        f"/api/projects/{pid}/segments/{seg['id']}",
        json={"active_generation_id": seg["takes"][0]["id"]},
    )
    edited = client.patch(
        f"/api/projects/{pid}/segments/{seg['id']}",
        json={"text": "Changed line.", "pause_after_ms": 1200},
    ).json()
    seg = next(s for s in edited["segments"] if s["id"] == target["id"])
    assert seg["active_take_stale"] and seg["pause_after_ms"] == 1200
    order = [s["id"] for s in reversed(edited["segments"])]
    reordered = client.post(f"/api/projects/{pid}/reorder", json={"segment_ids": order}).json()
    assert [s["id"] for s in reordered["segments"]] == order

    preview = client.post(f"/api/projects/{pid}/preview")
    assert preview.status_code == 200 and preview.headers["content-type"] == "audio/wav"
    exported = client.post(
        f"/api/projects/{pid}/export", json={"format": "mp3", "bitrate": 320, "mode": "both"}
    ).json()
    assert len(exported["paths"]) == 5
    assert all(Path(p).exists() for p in exported["paths"])

    # Re-segmenting keeps takes for unchanged text.
    kept = client.post(
        f"/api/projects/{pid}/script",
        json={"script": "Opening line.\n\nBrand new.", "segmentation": "sentence"},
    ).json()
    assert kept["segments"][0]["active_generation_id"] is not None
    assert kept["segments"][1]["active_generation_id"] is None


def test_project_export_reports_missing_audio(client, tmp_path):
    voice = make_voice(client, tmp_path)
    project = client.post(
        "/api/projects",
        json={
            "name": "Empty",
            "script": "One. Two.",
            "voice_id": voice["id"],
            "language": "english",
        },
    ).json()
    res = client.post(f"/api/projects/{project['id']}/export", json={"format": "wav"})
    assert res.status_code == 400 and res.json()["error"]["code"] == "segments_missing_audio"


def test_interrupted_jobs_are_marked_on_restart(client, tmp_path):
    studio = client.app.state.studio
    studio.db.execute(
        "INSERT INTO jobs (id, kind, status, payload_json, created_at) VALUES ('j1', 'tts', 'synthesizing', '{}', 'x')"
    )
    studio.jobs.stop()
    studio.jobs.start()
    job = client.get("/api/jobs/j1").json()
    assert job["status"] == "failed" and job["error_code"] == "interrupted"


def test_voice_export_import_and_delete(client, tmp_path):
    voice = make_voice(client, tmp_path)
    archive = client.post(f"/api/voices/{voice['id']}/export")
    assert archive.status_code == 200
    zip_path = Path(archive.json()["paths"][0])
    assert zip_path.name == "Ana.voice.zip"
    with open(zip_path, "rb") as fh:
        imported = client.post(
            "/api/voices/import", files={"file": ("voice.zip", fh, "application/zip")}
        )
    assert imported.status_code == 201, imported.text
    copy = imported.json()
    assert copy["references"][0]["transcript"] == "This is my voice."
    assert copy["consent"]["speaker"] == "Ana Example"

    studio = client.app.state.studio
    voice_dir = studio.paths.voices / voice["id"]
    assert voice_dir.exists()
    assert client.delete(f"/api/voices/{voice['id']}").status_code == 204
    assert not voice_dir.exists()
    assert client.get(f"/api/voices/{voice['id']}").status_code == 404


def test_models_settings_languages_and_storage(client, tmp_path):
    models = client.get("/api/models").json()
    assert models[0]["status"]["state"] == "installed"
    load = client.post("/api/models/load", json={"model_id": FAKE_MODEL}).json()
    assert wait_job(client, load["job_id"])["status"] == "completed"
    assert client.get("/api/models").json()[0]["loaded"] is True
    langs = client.get("/api/languages").json()
    assert {lang["code"] for lang in langs if lang["enabled"]} == set(QWEN3_LANGUAGES)
    updated = client.put("/api/settings", json={"enabled_languages": ["english", "german"]}).json()
    assert updated["enabled_languages"] == ["english", "german"]
    assert client.put("/api/settings", json={"enabled_languages": ["klingon"]}).status_code == 400
    assert client.post("/api/models/unload").status_code == 204
    assert client.get("/api/system/status").json()["engine"]["state"] == "stopped"
    storage = client.get("/api/system/storage").json()
    assert storage["categories"]["models"] > 0


def test_upload_rejects_unsupported_and_oversized(client, tmp_path):
    voice = client.post(
        "/api/voices",
        json={
            "name": "B",
            "language": "english",
            "consent": {"confirmed": True, "speaker": "B", "scope": "Test"},
        },
    ).json()
    bad = client.post(
        f"/api/voices/{voice['id']}/references",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert bad.json()["error"]["code"] == "unsupported_file"
    object.__setattr__(client.app.state.studio.settings, "max_upload_bytes", 1000)
    big = speech_like_wav(tmp_path / "big.wav", seconds=2)
    with open(big, "rb") as fh:
        res = client.post(
            f"/api/voices/{voice['id']}/references", files={"file": ("big.wav", fh, "audio/wav")}
        )
    assert res.status_code == 413


def _upload(client, voice_id: str, path: Path):
    with open(path, "rb") as fh:
        return client.post(
            f"/api/voices/{voice_id}/references", files={"file": (path.name, fh, "audio/wav")}
        )


def test_create_voice_from_recordings_and_choose_a_clip(client, tmp_path, data_dir):
    from conftest import install_fake_stt

    voice = client.post(
        "/api/voices",
        json={
            "name": "Ana",
            "language": "english",
            "consent": {"confirmed": True, "speaker": "Ana Example", "scope": "Internal narration"},
        },
    ).json()
    vid = voice["id"]
    # Two recordings, together well over the old one-minute limit.
    assert _upload(client, vid, speech_like_wav(tmp_path / "a.wav", seconds=70)).status_code == 201
    assert _upload(client, vid, speech_like_wav(tmp_path / "b.wav", seconds=40)).status_code == 201
    # A third would pass five minutes in total.
    over = _upload(client, vid, speech_like_wav(tmp_path / "c.wav", seconds=200))
    assert over.status_code == 400 and over.json()["error"]["code"] == "recordings_too_long"

    # Long recordings cannot be cloned from directly.
    direct = client.post(
        "/api/generate", json={"text": "Hi", "voice_id": vid, "language": "english"}
    )
    assert direct.json()["error"]["code"] == "create_voice_first"

    # Creating needs the speech recognition model.
    job = client.post(f"/api/voices/{vid}/create", json={}).json()
    failed = wait_job(client, job["job_id"])
    assert failed["status"] == "failed" and failed["error_code"] == "stt_not_installed"

    install_fake_stt(data_dir / "models")
    job = client.post(f"/api/voices/{vid}/create", json={}).json()
    done = wait_job(client, job["job_id"], timeout=120)
    assert done["status"] == "completed", done
    voice = client.get(f"/api/voices/{vid}").json()
    assert all(r["segments"] for r in voice["references"])
    clips = voice["clips"]
    assert len(clips) == 3
    assert {c["reference_id"] for c in clips} == {r["id"] for r in voice["references"]}
    for clip in clips:
        assert 10 <= clip["end_s"] - clip["start_s"] <= 25
        assert clip["transcript"].startswith("Sentence at")
        assert clip["demo_generation_id"]
        assert client.get(f"/api/voices/{vid}/clips/{clip['id']}/audio").status_code == 200
    assert voice["status"] == "draft"

    # Correct a transcript and voice the demo again; the old demo is replaced.
    first = clips[0]
    client.patch(f"/api/voices/{vid}/clips/{first['id']}", json={"transcript": "Fixed words."})
    redo = client.post(f"/api/voices/{vid}/clips/{first['id']}/demo", json={}).json()
    assert wait_job(client, redo["job_id"])["status"] == "completed"
    refreshed = next(
        c for c in client.get(f"/api/voices/{vid}").json()["clips"] if c["id"] == first["id"]
    )
    assert refreshed["transcript"] == "Fixed words."
    assert refreshed["demo_generation_id"] != first["demo_generation_id"]

    saved = client.post(f"/api/voices/{vid}/clips/{first['id']}/choose").json()
    assert saved["status"] == "ready" and saved["clip_id"] == first["id"]
    assert saved["preferred_sample_generation_id"] == refreshed["demo_generation_id"]

    # Generation now clones from the chosen clip.
    gen = client.post(
        "/api/generate", json={"text": "Hello there.", "voice_id": vid, "language": "english"}
    )
    finished = wait_job(client, gen.json()["job_id"])
    assert finished["status"] == "completed"
    generation = client.get(f"/api/generations/{finished['generation_id']}").json()
    assert generation["reference_id"] == first["id"]

    # Creating again keeps the chosen clip and replaces the other candidates.
    again = client.post(f"/api/voices/{vid}/create", json={}).json()
    assert wait_job(client, again["job_id"], timeout=120)["status"] == "completed"
    after = client.get(f"/api/voices/{vid}").json()
    assert first["id"] in {c["id"] for c in after["clips"]}
    assert not {c["id"] for c in clips[1:]} & {c["id"] for c in after["clips"]}

    # Removing the recording the chosen clip came from puts the voice back in draft.
    client.delete(f"/api/voices/{vid}/references/{first['reference_id']}")
    after = client.get(f"/api/voices/{vid}").json()
    assert after["clip_id"] is None and after["status"] == "draft"
    assert all(c["reference_id"] != first["reference_id"] for c in after["clips"])


def test_whisper_cannot_be_used_as_a_voice_model(client):
    from conftest import FAKE_STT

    res = client.post("/api/models/load", json={"model_id": FAKE_STT})
    assert res.json()["error"]["code"] == "not_a_voice_model"


def test_voice_jobs_refuse_a_model_that_is_not_installed(client, tmp_path, data_dir):
    import shutil

    voice = make_voice(client, tmp_path)
    shutil.rmtree(data_dir / "models" / FAKE_MODEL)
    for path, body in (
        (f"/api/voices/{voice['id']}/create", {}),
        (f"/api/voices/{voice['id']}/test", {"text": "Hi"}),
    ):
        res = client.post(path, json=body)
        assert res.status_code == 400, res.text
        assert res.json()["error"]["code"] == "model_not_installed"
    assert client.get("/api/jobs").json() == []  # nothing was queued
