import json
from pathlib import Path

import pytest
from conftest import LINK_ID, SAMPLE_ID, FakeCell, FakeClient, FakeColumn, FakeRow, make_sheet

from exaspim_screen_ng import smartsheet_link
from exaspim_screen_ng.smartsheet_link import (
    _normalize_cell_value,
    build_neuroglancer_link,
    find_data_description,
    find_row_for_subject,
    get_column_ids,
    load_metadata,
    update_smartsheet,
)


def write_dd(path: Path, **data: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestFindDataDescription:
    def test_explicit_path(self, tmp_path: Path) -> None:
        dd = write_dd(tmp_path / "data_description.json", name="x")
        assert find_data_description(str(dd)) == str(dd)

    def test_explicit_path_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            find_data_description(str(tmp_path / "missing.json"))

    def test_glob_single_match(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dd = write_dd(tmp_path / "asset" / "data_description.json", name="x")
        monkeypatch.setattr(
            smartsheet_link, "DEFAULT_DATA_GLOB", str(tmp_path / "**" / "data_description.json")
        )
        assert find_data_description(None) == str(dd)

    def test_glob_no_match(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            smartsheet_link, "DEFAULT_DATA_GLOB", str(tmp_path / "**" / "data_description.json")
        )
        with pytest.raises(FileNotFoundError, match="--data-description"):
            find_data_description(None)

    def test_glob_multiple_matches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        write_dd(tmp_path / "a" / "data_description.json", name="a")
        write_dd(tmp_path / "b" / "data_description.json", name="b")
        monkeypatch.setattr(
            smartsheet_link, "DEFAULT_DATA_GLOB", str(tmp_path / "**" / "data_description.json")
        )
        with pytest.raises(ValueError, match="Multiple"):
            find_data_description(None)


class TestLoadMetadata:
    def test_returns_name_and_subject(self, tmp_path: Path) -> None:
        dd = write_dd(tmp_path / "dd.json", name="exaSPIM_787425_2025", subject_id="787425")
        assert load_metadata(str(dd)) == ("exaSPIM_787425_2025", "787425")

    def test_missing_name(self, tmp_path: Path) -> None:
        dd = write_dd(tmp_path / "dd.json", subject_id="787425")
        with pytest.raises(KeyError, match="name"):
            load_metadata(str(dd))

    def test_missing_subject(self, tmp_path: Path) -> None:
        dd = write_dd(tmp_path / "dd.json", name="x")
        with pytest.raises(KeyError, match="subject_id"):
            load_metadata(str(dd))


def test_build_neuroglancer_link() -> None:
    assert build_neuroglancer_link("bucket", "asset") == (
        "https://neuroglancer-demo.appspot.com/#!s3://bucket/asset/neuroglancer.json"
    )


def test_get_column_ids() -> None:
    sheet = make_sheet([])
    assert get_column_ids(sheet) == {
        smartsheet_link.SAMPLE_COLUMN: SAMPLE_ID,
        smartsheet_link.LINK_COLUMN: LINK_ID,
    }


@pytest.mark.parametrize(
    ("value", "display_value", "expected"),
    [
        (787425.0, " 787425 ", "787425"),
        (787425.0, None, "787425"),
        (None, None, None),
        (" abc ", None, "abc"),
        (1.5, None, "1.5"),
    ],
)
def test_normalize_cell_value(value: object, display_value: object, expected: str | None) -> None:
    assert _normalize_cell_value(FakeCell(SAMPLE_ID, value, display_value)) == expected


class TestFindRowForSubject:
    def test_match(self) -> None:
        sheet = make_sheet([111111.0, 787425.0])
        row = find_row_for_subject(sheet, SAMPLE_ID, "787425")
        assert row is not None
        assert row.id == 101

    def test_no_match(self) -> None:
        sheet = make_sheet([111111.0])
        assert find_row_for_subject(sheet, SAMPLE_ID, "787425") is None

    def test_row_without_sample_cell(self) -> None:
        sheet = make_sheet([])
        sheet.rows.append(FakeRow(id=1, cells=[FakeCell(LINK_ID, value="787425")]))
        assert find_row_for_subject(sheet, SAMPLE_ID, "787425") is None


class TestUpdateSmartsheet:
    def test_writes_link(self, fake_client: FakeClient) -> None:
        assert update_smartsheet("token", 5, "787425", "https://link") is True
        assert fake_client.raise_errors is True
        [(sheet_id, rows)] = fake_client.Sheets.updates
        assert sheet_id == 5
        assert rows[0].id == 101
        assert rows[0].cells[0].column_id == LINK_ID
        assert rows[0].cells[0].value == "https://link"

    def test_dry_run_does_not_write(self, fake_client: FakeClient) -> None:
        assert update_smartsheet("token", 5, "787425", "https://link", dry_run=True) is False
        assert fake_client.Sheets.updates == []

    def test_missing_column(self, fake_client: FakeClient) -> None:
        fake_client.Sheets.sheet.columns = [FakeColumn(smartsheet_link.SAMPLE_COLUMN, SAMPLE_ID)]
        with pytest.raises(KeyError, match=smartsheet_link.LINK_COLUMN):
            update_smartsheet("token", 5, "787425", "https://link")

    def test_subject_not_found(self, fake_client: FakeClient) -> None:
        with pytest.raises(LookupError, match="999999"):
            update_smartsheet("token", 5, "999999", "https://link")
