"""Shared test fixtures: Smartsheet fakes and a source data asset."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from aind_data_schema.components.identifiers import Person
from aind_data_schema.components.subjects import MouseSubject, Sex
from aind_data_schema.core.data_description import DataDescription, Funding
from aind_data_schema.core.subject import Subject
from aind_data_schema_models.data_name_patterns import DataLevel
from aind_data_schema_models.modalities import Modality
from aind_data_schema_models.organizations import Organization
from aind_data_schema_models.species import Species, Strain

from exaspim_screen_ng import smartsheet_link


@dataclass
class FakeColumn:
    title: str
    id: int


@dataclass
class FakeCell:
    column_id: int
    value: Any = None
    display_value: Any = None


@dataclass
class FakeRow:
    id: int
    cells: list[FakeCell] = field(default_factory=list)


@dataclass
class FakeSheet:
    columns: list[FakeColumn]
    rows: list[FakeRow]


SAMPLE_ID = 1
LINK_ID = 2


def make_sheet(subject_values: list[Any], columns: list[FakeColumn] | None = None) -> FakeSheet:
    """Build a sheet with one row per value in the Sample column."""
    if columns is None:
        columns = [
            FakeColumn(smartsheet_link.SAMPLE_COLUMN, SAMPLE_ID),
            FakeColumn(smartsheet_link.LINK_COLUMN, LINK_ID),
        ]
    rows = [
        FakeRow(id=100 + i, cells=[FakeCell(LINK_ID), FakeCell(SAMPLE_ID, value=v)])
        for i, v in enumerate(subject_values)
    ]
    return FakeSheet(columns=columns, rows=rows)


class FakeSheets:
    def __init__(self, sheet: FakeSheet) -> None:
        self.sheet = sheet
        self.updates: list[tuple[int, list[Any]]] = []

    def get_sheet(self, sheet_id: int) -> FakeSheet:
        return self.sheet

    def update_rows(self, sheet_id: int, rows: list[Any]) -> None:
        self.updates.append((sheet_id, rows))


class FakeClient:
    def __init__(self, sheet: FakeSheet) -> None:
        self.Sheets = FakeSheets(sheet)
        self.raise_errors: bool | None = None

    def errors_as_exceptions(self, value: bool) -> None:
        self.raise_errors = value


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    """Patch ``smartsheet.Smartsheet`` to return a fake client for subject 787425."""
    client = FakeClient(make_sheet([111111.0, 787425.0]))
    monkeypatch.setattr(smartsheet_link.smartsheet, "Smartsheet", lambda token: client)
    return client


SOURCE_NAME = "exaSPIM_787425_2025-01-01_00-00-00"
SUBJECT_ID = "787425"


def make_data_description() -> DataDescription:
    return DataDescription(
        name=SOURCE_NAME,
        subject_id=SUBJECT_ID,
        creation_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        institution=Organization.AIND,
        funding_source=[Funding(funder=Organization.AI)],
        data_level=DataLevel.RAW,
        modalities=[Modality.SPIM],
        project_name="exaSPIM",
        investigators=[Person(name="Jane Doe")],
    )


def make_subject() -> Subject:
    return Subject(
        subject_id=SUBJECT_ID,
        subject_details=MouseSubject(
            sex=Sex.FEMALE,
            date_of_birth=date(2024, 10, 1),
            strain=Strain.C57BL_6J,
            species=Species.HOUSE_MOUSE,
            genotype="wt/wt",
            source=Organization.JAX,
        ),
    )


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    """Source asset directory with valid core JSONs and a neuroglancer.json."""
    path = tmp_path / "data" / SOURCE_NAME
    path.mkdir(parents=True)
    make_data_description().write_standard_file(output_directory=path)
    make_subject().write_standard_file(output_directory=path)
    (path / "neuroglancer.json").write_text(json.dumps({"layers": []}), encoding="utf-8")
    return path
