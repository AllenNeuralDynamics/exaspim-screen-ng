import json
from pathlib import Path

import pytest
from conftest import FakeClient

from exaspim_screen_ng.cli import LINK_OUTPUT_NAME, main

DATASET = "exaSPIM_787425_2025-01-01_00-00-00"
LINK = f"https://neuroglancer-demo.appspot.com/#!s3://aind-open-data/{DATASET}/neuroglancer.json"


@pytest.fixture
def data_description(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "data_description.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"name": DATASET, "subject_id": "787425"}), encoding="utf-8")
    return path


@pytest.fixture
def results_dir(tmp_path: Path) -> Path:
    path = tmp_path / "results"
    path.mkdir()
    return path


def run(data_description: Path, results_dir: Path, *extra: str) -> int:
    return main(
        [
            "--data-description",
            str(data_description),
            "--results-dir",
            str(results_dir),
            *extra,
        ]
    )


def test_main_updates_sheet_and_writes_link(
    fake_client: FakeClient,
    data_description: Path,
    results_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_KEY", "token")
    assert run(data_description, results_dir) == 0
    assert len(fake_client.Sheets.updates) == 1
    output = json.loads((results_dir / LINK_OUTPUT_NAME).read_text(encoding="utf-8"))
    assert output == {"url": LINK}


def test_main_dry_run(
    fake_client: FakeClient,
    data_description: Path,
    results_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_KEY", "token")
    assert run(data_description, results_dir, "--dry-run") == 0
    assert fake_client.Sheets.updates == []
    assert not (results_dir / LINK_OUTPUT_NAME).exists()


def test_main_requires_token(
    data_description: Path, results_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CUSTOM_KEY", raising=False)
    with pytest.raises(OSError, match="CUSTOM_KEY"):
        run(data_description, results_dir)
