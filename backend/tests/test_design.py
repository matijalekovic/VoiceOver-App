from __future__ import annotations

import json
from pathlib import Path

from conftest import FAKE_DESIGN, FAKE_MODEL, make_voice, wait_job

from voice_studio.models import validate_model_dir


def make_design_voice(
    client, instructions: str = "A calm, low-pitched adult male narrator."
) -> dict:
    res = client.post(
        "/api/voices",
        json={
            "name": "Designed narrator",
            "language": "english",
            "mode": "design",
            "instructions": instructions,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def _checkpoint(folder: Path, model_type: str) -> Path:
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(json.dumps({"tts_model_type": model_type}))
    (folder / "model.safetensors").write_bytes(b"0")
    (folder / "tokenizer.json").write_text("{}")
    (folder / "speech_tokenizer").mkdir()
    (folder / "speech_tokenizer" / "config.json").write_text("{}")
    (folder / "speech_tokenizer" / "model.safetensors").write_bytes(b"0")
    return folder


def test_voice_design_and_cloning_checkpoints_are_valid_but_custom_voice_is_not(tmp_path):
    assert validate_model_dir(_checkpoint(tmp_path / "design", "voice_design")) == []
    assert validate_model_dir(_checkpoint(tmp_path / "base", "base")) == []
    custom = _checkpoint(tmp_path / "custom", "custom_voice")
    assert any("custom_voice" in problem for problem in validate_model_dir(custom))


def test_a_designed_voice_needs_a_description_and_a_clone_needs_consent(client):
    missing = client.post(
        "/api/voices", json={"name": "X", "language": "english", "mode": "design"}
    )
    assert missing.status_code == 422

    no_consent = client.post(
        "/api/voices", json={"name": "X", "language": "english", "mode": "clone"}
    )
    assert no_consent.status_code == 422


def test_design_a_voice_choose_a_take_and_generate(client):
    voice = make_design_voice(client)
    assert voice["mode"] == "design"
    assert voice["status"] == "draft"
    assert voice["instructions"].startswith("A calm")
    # A designed voice has no speaker to consent; the profile records that plainly.
    assert voice["consent"]["speaker"] == "Synthetic voice"

    # Creating takes needs no recordings and picks the Voice Design model by itself.
    job = client.post(f"/api/voices/{voice['id']}/create", json={}).json()
    done = wait_job(client, job["job_id"])
    assert done["status"] == "completed", done
    generation_ids = done["result"]["generation_ids"]
    assert len(generation_ids) == 3

    takes = client.get(f"/api/generations?voice_id={voice['id']}&kind=voice_test").json()
    assert takes["total"] == 3
    assert {g["id"] for g in takes["items"]} == set(generation_ids)
    assert all(g["voice_name"] == "Designed narrator" for g in takes["items"])
    assert all(g["reference_id"] is None for g in takes["items"])

    chosen = client.post(
        f"/api/voices/{voice['id']}/sample", json={"generation_id": generation_ids[1]}
    ).json()
    assert chosen["status"] == "ready"
    assert chosen["preferred_sample_generation_id"] == generation_ids[1]

    # A test line and a normal generation both run without a reference recording.
    test = client.post(
        f"/api/voices/{voice['id']}/test",
        json={"text": "How does this voice sound?", "model_id": FAKE_DESIGN},
    ).json()
    assert wait_job(client, test["job_id"])["status"] == "completed"

    gen = client.post(
        "/api/generate",
        json={
            "text": "Designed voices speak from a description.",
            "voice_id": voice["id"],
            "language": "english",
            "model_id": FAKE_DESIGN,
        },
    )
    assert gen.status_code == 202, gen.text
    finished = wait_job(client, gen.json()["job_id"])
    assert finished["status"] == "completed", finished
    generation = client.get(f"/api/generations/{finished['generation_id']}").json()
    assert generation["reference_id"] is None

    # Take seeds are distinct, but ordinary generations of the same designed voice reuse a
    # stable seed so separate segments do not re-roll the voice every time.
    take_seeds = {
        g["params"]["seed"]
        for g in client.get(f"/api/generations?voice_id={voice['id']}&kind=voice_test").json()[
            "items"
        ]
        if g["id"] in generation_ids
    }
    assert len(take_seeds) == 3
    repeat = client.post(
        "/api/generate",
        json={
            "text": "A different line for the same voice.",
            "voice_id": voice["id"],
            "language": "english",
            "model_id": FAKE_DESIGN,
        },
    )
    repeat_job = wait_job(client, repeat.json()["job_id"])
    repeated = client.get(f"/api/generations/{repeat_job['generation_id']}").json()
    assert repeated["params"]["seed"] == generation["params"]["seed"]

    # Editing the description is allowed and is what later generations use.
    updated = client.patch(
        f"/api/voices/{voice['id']}",
        json={"instructions": "A bright, fast-paced young female voice."},
    ).json()
    assert updated["instructions"].startswith("A bright")

    # A designed voice cannot run on a cloning checkpoint.
    wrong = client.post(
        "/api/generate",
        json={
            "text": "Hi",
            "voice_id": voice["id"],
            "language": "english",
            "model_id": FAKE_MODEL,
        },
    )
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"] == "wrong_model_type"


def test_designing_again_replaces_old_takes_but_keeps_the_chosen_one(client):
    voice = make_design_voice(client)
    first = client.post(f"/api/voices/{voice['id']}/create", json={}).json()
    first_ids = wait_job(client, first["job_id"])["result"]["generation_ids"]
    client.post(f"/api/voices/{voice['id']}/sample", json={"generation_id": first_ids[0]})

    again = client.post(f"/api/voices/{voice['id']}/create", json={}).json()
    second_ids = wait_job(client, again["job_id"])["result"]["generation_ids"]
    takes = client.get(f"/api/generations?voice_id={voice['id']}&kind=voice_test").json()
    remaining = {g["id"] for g in takes["items"]}
    assert set(second_ids) <= remaining
    assert first_ids[0] in remaining  # the chosen preview survives the new round
    assert not (set(first_ids[1:]) & remaining)

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["preferred_sample_generation_id"] == first_ids[0]


def test_designed_voice_exports_and_imports_with_its_description(client):
    voice = make_design_voice(client)
    archive = client.post(f"/api/voices/{voice['id']}/export").json()
    with open(archive["paths"][0], "rb") as fh:
        imported = client.post(
            "/api/voices/import", files={"file": ("voice.zip", fh, "application/zip")}
        )
    assert imported.status_code == 201, imported.text
    copy = imported.json()
    assert copy["mode"] == "design"
    assert copy["instructions"] == voice["instructions"]
    assert copy["references"] == []


def test_project_uses_a_design_checkpoint_for_a_designed_voice(client, tmp_path):
    voice = make_design_voice(client)
    project = client.post(
        "/api/projects",
        json={
            "name": "Designed project",
            "script": "One line. Another line.",
            "voice_id": voice["id"],
            "language": "english",
            "segmentation": "sentence",
        },
    ).json()
    assert project["model_id"] == FAKE_DESIGN

    jobs = client.post(f"/api/projects/{project['id']}/generate", json={}).json()
    assert len(jobs) == 2
    for job in jobs:
        assert wait_job(client, job["id"])["status"] == "completed"

    # Switching back to a cloned voice moves the project back to a cloning checkpoint.
    clone = make_voice(client, tmp_path)
    updated = client.put(f"/api/projects/{project['id']}", json={"voice_id": clone["id"]}).json()
    assert updated["model_id"] == FAKE_MODEL


def test_both_platform_catalogs_offer_one_voice_design_checkpoint():
    from voice_studio.catalog import MLX_CATALOG, TORCH_CATALOG, design_spec

    for catalog in (MLX_CATALOG, TORCH_CATALOG):
        spec = design_spec(catalog)
        assert spec is not None and spec.kind == "tts" and spec.tier == "design"
        assert sum(s.capability == "design" for s in catalog) == 1


def test_a_voice_design_checkpoint_cannot_be_the_default_model(client):
    res = client.put("/api/settings", json={"default_model_id": FAKE_DESIGN})
    assert res.status_code >= 400
    assert client.put("/api/settings", json={"default_model_id": FAKE_MODEL}).status_code == 200
