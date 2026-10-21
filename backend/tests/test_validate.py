from __future__ import annotations

import json
from pathlib import Path

from conftest import FAKE_MODEL, fake_catalog, install_fake_model, speech_like_wav

from voice_studio import catalog, validate


def test_validation_cli_clones_reports_and_reuses(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    saved = catalog.CATALOG[:]
    catalog.CATALOG[:] = fake_catalog()
    try:
        data = tmp_path / "data"
        install_fake_model(data / "models")
        ref = speech_like_wav(tmp_path / "me.wav")
        out = tmp_path / "report"
        validate.main([
            "--reference", str(ref), "--transcript", "Hello there.", "--speaker", "Me",
            "--models", FAKE_MODEL, "--data-dir", str(data), "--out", str(out),
        ])  # fmt: skip
        report = json.loads((out / "report.json").read_text())
        assert [r["language"] for r in report["runs"]] == ["english", "french", "spanish"]
        assert all(
            r["status"] == "completed" and (out / r["file"]).exists() for r in report["runs"]
        )
        assert "Listening evaluation" in (out / "report.md").read_text()

        again = tmp_path / "again"
        validate.main([
            "--reuse-voice", report["voice"]["id"], "--models", FAKE_MODEL, "--languages", "english",
            "--data-dir", str(data), "--out", str(again),
        ])  # fmt: skip
        assert json.loads((again / "report.json").read_text())["runs"][0]["status"] == "completed"
    finally:
        catalog.CATALOG[:] = saved
