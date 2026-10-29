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
    load_source_core,
    write_derived_asset,
)

BUCKET = "aind-open-data"
START = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
END = START + timedelta(seconds=5)
PARAMS = {"bucket": BUCKET, "sheet_id": 1, "dry_run": True}
NG_URL = "https://neuroglancer-demo.appspot.com/#!s3://aind-open-data/asset/neuroglancer.json"

# Passthrough files that no aind-data-schema model accepts. acquisition lists
# active devices present in neither instrument.components nor a procedure's
# implanted_device, the cross-file combination Metadata used to reject.
BROKEN_PASSTHROUGH = {
    "procedures.json": json.dumps({"subject_procedures": [{"Injection": "incomplete"}]}),
    "instrument.json": json.dumps({"components": []}),
    "acquisition.json": json.dumps({"active_devices": ["ExASPIM", "sample-chamber"]}),
}


def write_core(path: Path, model: Processing | QualityControl, schema_version: str) -> None:
    """Write a core file with an overridden (stale) schema_version."""
    data = json.loads(model.model_dump_json())
    data["schema_version"] = schema_version
    path.write_text(json.dumps(data), encoding="utf-8")


def write_broken_passthrough(source_dir: Path) -> dict[str, str]:
    """Write unvalidatable procedures, instrument and acquisition files."""
    for name, text in BROKEN_PASSTHROUGH.items():
        (source_dir / name).write_text(text, encoding="utf-8")
    return BROKEN_PASSTHROUGH


class TestLoadSourceCore:
    def test_minimal_source(self, source_dir: Path) -> None:
        core, passthrough = load_source_core(source_dir)
        assert core["data_description"].name == SOURCE_NAME
        assert "processing" not in core
        assert "quality_control" not in core
        assert [p.name for p in passthrough] == ["subject.json"]

    def test_stale_schema_version_is_replaced(self, source_dir: Path) -> None:
        processing = build_processing(START, END, SOURCE_NAME, {})
        write_core(source_dir / "processing.json", processing, "2.0.0")
        core, _ = load_source_core(source_dir)
        assert (
            core["processing"].schema_version
            == Processing.model_fields["schema_version"].default
        )

    def test_passthrough_files_are_not_validated(self, source_dir: Path) -> None:
        broken = write_broken_passthrough(source_dir)
        core, passthrough = load_source_core(source_dir)
        assert set(core) == {"data_description"}
        assert sorted(p.name for p in passthrough) == sorted(["subject.json", *broken])

    def test_missing_data_description(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="data_description.json"):
            load_source_core(tmp_path)


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
        core, _ = load_source_core(source_dir)
        derived = build_derived_metadata(core, BUCKET, NG_URL, START, END, PARAMS)

        assert derived.name == f"{SOURCE_NAME}_processed_2025-06-01_12-00-05"
        assert derived.location == f"s3://{BUCKET}/{derived.name}"
        assert derived.data_description.name == derived.name
        assert derived.data_description.data_level == DataLevel.DERIVED
        assert derived.data_description.source_data == [SOURCE_NAME]
        assert derived.data_description.subject_id == core["data_description"].subject_id
        assert [p.name for p in derived.processing.data_processes] == [DATA_PROCESS_NAME]
        [metric] = derived.quality_control.metrics
        assert metric.reference == NG_URL

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

        core, _ = load_source_core(source_dir)
        derived = build_derived_metadata(core, BUCKET, NG_URL, START, END, PARAMS)

        names = [p.name for p in derived.processing.data_processes]
        assert names == ["earlier step", DATA_PROCESS_NAME]
        assert len(derived.quality_control.metrics) == 2


class TestWriteDerivedAsset:
    def test_writes_files(self, source_dir: Path, tmp_path: Path) -> None:
        results = tmp_path / "results"
        derived = write_derived_asset(
            source_dir, results, BUCKET, NG_URL, START, END, PARAMS
        )

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
        assert (results / "neuroglancer.json").read_bytes() == (
            source_dir / "neuroglancer.json"
        ).read_bytes()

    def test_unmatched_active_devices_do_not_fail(self, source_dir: Path, tmp_path: Path) -> None:
        """acquisition devices absent from instrument and procedures used to raise."""
        write_broken_passthrough(source_dir)
        results = tmp_path / "results"

        derived = write_derived_asset(
            source_dir, results, BUCKET, NG_URL, START, END, PARAMS
        )

        assert derived.name.startswith(f"{SOURCE_NAME}_processed_")
        assert [p.name for p in derived.processing.data_processes] == [DATA_PROCESS_NAME]
        assert {p.name for p in results.iterdir()} == {
            "data_description.json",
            "processing.json",
            "quality_control.json",
            "subject.json",
            "procedures.json",
            "instrument.json",
            "acquisition.json",
            "neuroglancer.json",
        }

    def test_passthrough_files_are_byte_identical(self, source_dir: Path, tmp_path: Path) -> None:
        write_broken_passthrough(source_dir)
        results = tmp_path / "results"

        write_derived_asset(source_dir, results, BUCKET, NG_URL, START, END, PARAMS)

        copied = ["subject.json", "procedures.json", "instrument.json", "acquisition.json"]
        for name in copied:
            assert (results / name).read_bytes() == (source_dir / name).read_bytes(), name

    def test_missing_neuroglancer_json(self, source_dir: Path, tmp_path: Path) -> None:
        (source_dir / "neuroglancer.json").unlink()
        results = tmp_path / "results"
        with pytest.raises(FileNotFoundError, match="neuroglancer.json"):
            write_derived_asset(source_dir, results, BUCKET, NG_URL, START, END, PARAMS)
        assert not results.exists()
