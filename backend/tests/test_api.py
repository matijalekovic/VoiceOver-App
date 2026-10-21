from __future__ import annotations

import time
from pathlib import Path

import soundfile as sf
from conftest import FAKE_MODEL, make_voice, speech_like_wav, wait_job


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
    assert {lang["code"] for lang in langs if lang["enabled"]} == {"english", "french", "spanish"}
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
