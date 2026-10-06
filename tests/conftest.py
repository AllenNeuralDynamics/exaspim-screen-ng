"""Shared test fakes for the Smartsheet client and sheet objects."""

from dataclasses import dataclass, field
from typing import Any

import pytest

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
