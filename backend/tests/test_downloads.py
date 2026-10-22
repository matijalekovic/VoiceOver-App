from __future__ import annotations

from conftest import fake_catalog

from voice_studio.catalog import ModelSpec
from voice_studio.models import ModelManager


def _manager(tmp_path) -> tuple[ModelManager, list[str]]:
    catalog = fake_catalog() + [
        ModelSpec(
            id=f"extra-{n}",
            label=f"Extra {n}",
            repo_id=f"example/extra-{n}",
            tier="quality",
            parameters="0",
            quantization="none",
            approx_download_gb=0,
            approx_memory_gb=0,
            engine="fake_engine:FakeEngine",
        )  # fmt: skip
        for n in (1, 2)
    ]
    manager = ModelManager(tmp_path / "models", tmp_path / "download.log", tmp_path / "hf", catalog)
    launched: list[str] = []

    def fake_launch(model_id: str) -> dict:  # stands in for the real download process
        launched.append(model_id)
        manager._downloads[model_id] = {"state": "downloading"}
        return {"state": "downloading"}

    manager._launch = fake_launch  # type: ignore[method-assign]
    return manager, launched


def test_downloads_queue_and_start_in_order(tmp_path):
    manager, launched = _manager(tmp_path)
    assert manager.start_download("fake-base")["state"] == "downloading"
    assert manager.start_download("extra-1")["state"] == "queued"
    assert manager.start_download("extra-2")["state"] == "queued"
    assert manager.status("extra-1")["state"] == "queued"

    manager.cancel_download("extra-1")  # a queued download can be dropped
    assert manager.status("extra-1")["state"] == "not_installed"

    manager._downloads.pop("fake-base")  # the first download finishes...
    manager._start_next()  # ...and the next queued one starts
    assert launched == ["fake-base", "extra-2"]


def test_shutdown_drops_the_queue(tmp_path):
    manager, launched = _manager(tmp_path)
    manager.start_download("fake-base")
    manager.start_download("extra-1")
    manager._downloads.pop("fake-base")
    manager.shutdown()
    manager._start_next()
    assert launched == ["fake-base"]


def test_cancel_while_a_download_is_starting_is_not_lost(tmp_path):
    manager = ModelManager(
        tmp_path / "models", tmp_path / "download.log", tmp_path / "hf", fake_catalog()
    )

    def size_check_during_which_the_user_cancels(repo_id: str) -> int:
        assert manager.status("fake-base")["state"] == "starting"
        manager.cancel_download("fake-base")
        return 0

    manager._remote_size = size_check_during_which_the_user_cancels  # type: ignore[method-assign]
    assert manager.start_download("fake-base")["state"] == "not_installed"
    assert manager.status("fake-base")["state"] == "not_installed"  # no process was started
