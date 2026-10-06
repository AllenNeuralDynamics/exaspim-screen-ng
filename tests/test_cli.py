import json
from pathlib import Path

import pytest
from conftest import SOURCE_NAME, FakeClient

from exaspim_screen_ng.cli import LINK_OUTPUT_NAME, main

LINK = (
    f"https://neuroglancer-demo.appspot.com/#!s3://aind-open-data/{SOURCE_NAME}/neuroglancer.json"
)
METADATA_FILES = {
    "data_description.json",
    "processing.json",
    "quality_control.json",
    "subject.json",
    "neuroglancer.json",
}


@pytest.fixture
def results_dir(tmp_path: Path) -> Path:
    path = tmp_path / "results"
    path.mkdir()
    return path


def run(source_dir: Path, results_dir: Path, *extra: str) -> int:
    return main(
        [
            "--data-description",
            str(source_dir / "data_description.json"),
            "--results-dir",
            str(results_dir),
            *extra,
        ]
    )


def written(results_dir: Path) -> set[str]:
    return {p.name for p in results_dir.iterdir()}


def test_main_updates_sheet_and_writes_outputs(
    fake_client: FakeClient,
    source_dir: Path,
    results_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_KEY", "token")
    assert run(source_dir, results_dir) == 0
    assert len(fake_client.Sheets.updates) == 1
    assert fake_client.Sheets.updates[0][1][0].cells[0].value == LINK
    assert written(results_dir) == METADATA_FILES | {LINK_OUTPUT_NAME}
    output = json.loads((results_dir / LINK_OUTPUT_NAME).read_text(encoding="utf-8"))
    assert output == {"url": LINK}


def test_main_dry_run_writes_metadata_only(
    fake_client: FakeClient,
    source_dir: Path,
    results_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_KEY", "token")
    assert run(source_dir, results_dir, "--dry-run") == 0
    assert fake_client.Sheets.updates == []
    assert written(results_dir) == METADATA_FILES


def test_main_requires_token(
    source_dir: Path, results_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CUSTOM_KEY", raising=False)
    with pytest.raises(OSError, match="CUSTOM_KEY"):
        run(source_dir, results_dir)
    assert written(results_dir) == METADATA_FILES
