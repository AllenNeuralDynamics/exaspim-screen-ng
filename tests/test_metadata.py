import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from aind_data_schema.core.processing import Processing
from aind_data_schema.core.quality_control import QualityControl, Status
from aind_data_schema_models.data_name_patterns import DataLevel
from conftest import SOURCE_NAME

from exaspim_screen_ng import metadata
from exaspim_screen_ng.metadata import (
    DATA_PROCESS_NAME,
    QC_METRIC_NAME,
    build_derived_metadata,
    build_processing,
    build_quality_control,
    load_source_metadata,
    write_derived_asset,
)

BUCKET = "aind-open-data"
START = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
END = START + timedelta(seconds=5)
PARAMS = {"bucket": BUCKET, "sheet_id": 1, "dry_run": True}


def write_core(path: Path, model: Processing | QualityControl, schema_version: str) -> None:
    """Write a core file with an overridden (stale) schema_version."""
    data = json.loads(model.model_dump_json())
    data["schema_version"] = schema_version
    path.write_text(json.dumps(data), encoding="utf-8")


class TestLoadSourceMetadata:
    def test_minimal_source(self, source_dir: Path) -> None:
        source = load_source_metadata(source_dir, BUCKET)
        assert source.name == SOURCE_NAME
        assert source.location == f"s3://{BUCKET}/{SOURCE_NAME}"
        assert source.subject is not None
        assert source.processing is None

    def test_stale_schema_version_is_replaced(self, source_dir: Path) -> None:
        processing = build_processing(START, END, SOURCE_NAME, {})
        write_core(source_dir / "processing.json", processing, "2.0.0")
        source = load_source_metadata(source_dir, BUCKET)
        assert source.processing is not None
        assert source.processing.schema_version == Processing.model_fields["schema_version"].default

    def test_missing_data_description(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="data_description.json"):
            load_source_metadata(tmp_path, BUCKET)


class TestInstalledCommitHash:
    @pytest.mark.parametrize(
        ("direct_url", "expected"),
        [
            (None, None),
            (json.dumps({"url": "file:///x", "dir_info": {"editable": True}}), None),
            (json.dumps({"vcs_info": {"vcs": "git", "commit_id": "abc1234"}}), "abc1234"),
        ],
    )
    def test_direct_url(
        self, monkeypatch: pytest.MonkeyPatch, direct_url: str | None, expected: str | None
    ) -> None:
        dist = SimpleNamespace(read_text=lambda name: direct_url)
        monkeypatch.setattr(metadata, "distribution", lambda name: dist)
        assert metadata._installed_commit_hash() == expected


def test_build_processing() -> None:
    processing = build_processing(START, END, SOURCE_NAME, PARAMS)
    [process] = processing.data_processes
    assert process.name == DATA_PROCESS_NAME
    assert process.experimenters == ["Carson Berry"]
    assert process.start_date_time == START
    assert process.end_date_time == END
    assert process.code.input_data[0].name == SOURCE_NAME
    assert process.code.parameters.model_dump() == PARAMS


def test_build_quality_control() -> None:
    qc = build_quality_control("https://link", END)
    [metric] = qc.metrics
    assert metric.name == QC_METRIC_NAME
    assert metric.reference == "https://link"
    assert metric.value["type"] == "dropdown"
    assert metric.status_history[-1].status == Status.PENDING
    assert qc.key_experimenters is None
    assert qc.evaluate_status() == Status.PENDING


class TestBuildDerivedMetadata:
    def test_derived_from_raw(self, source_dir: Path) -> None:
        source = load_source_metadata(source_dir, BUCKET)
        derived = build_derived_metadata(source, BUCKET, START, END, PARAMS)

        assert derived.name == f"{SOURCE_NAME}_processed_2025-06-01_12-00-05"
        assert derived.location == f"s3://{BUCKET}/{derived.name}"
        assert derived.data_description.data_level == DataLevel.DERIVED
        assert derived.data_description.source_data == [SOURCE_NAME]
        assert derived.data_description.subject_id == source.data_description.subject_id
        assert derived.subject == source.subject
        assert [p.name for p in derived.processing.data_processes] == [DATA_PROCESS_NAME]
        [metric] = derived.quality_control.metrics
        assert metric.reference.endswith(f"s3://{BUCKET}/{derived.name}/neuroglancer.json")

    def test_accumulates_source_processing_and_qc(self, source_dir: Path) -> None:
        earlier = START - timedelta(days=1)
        [process] = build_processing(earlier, earlier, SOURCE_NAME, {}).data_processes
        source_processing = Processing.create_with_sequential_process_graph(
            data_processes=[process.model_copy(update={"name": "earlier step"})]
        )
        write_core(source_dir / "processing.json", source_processing, "2.0.0")
        write_core(
            source_dir / "quality_control.json",
            build_quality_control("https://old", earlier),
            "2.0.0",
        )

        source = load_source_metadata(source_dir, BUCKET)
        derived = build_derived_metadata(source, BUCKET, START, END, PARAMS)

        names = [p.name for p in derived.processing.data_processes]
        assert names == ["earlier step", DATA_PROCESS_NAME]
        assert len(derived.quality_control.metrics) == 2


class TestWriteDerivedAsset:
    def test_writes_files(self, source_dir: Path, tmp_path: Path) -> None:
        results = tmp_path / "results"
        derived = write_derived_asset(source_dir, results, BUCKET, START, END, PARAMS)

        written = sorted(p.name for p in results.iterdir())
        assert written == [
            "data_description.json",
            "neuroglancer.json",
            "processing.json",
            "quality_control.json",
            "subject.json",
        ]
        dd = json.loads((results / "data_description.json").read_text(encoding="utf-8"))
        assert dd["name"] == derived.name
        assert (results / "neuroglancer.json").read_text(encoding="utf-8") == (
            source_dir / "neuroglancer.json"
        ).read_text(encoding="utf-8")

    def test_missing_neuroglancer_json(self, source_dir: Path, tmp_path: Path) -> None:
        (source_dir / "neuroglancer.json").unlink()
        results = tmp_path / "results"
        with pytest.raises(FileNotFoundError, match="neuroglancer.json"):
            write_derived_asset(source_dir, results, BUCKET, START, END, PARAMS)
        assert not results.exists()
