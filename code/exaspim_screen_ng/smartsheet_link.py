"""Build a Neuroglancer link for a dataset and write it to a Smartsheet row."""

import glob
import json
import os
from typing import Any

import smartsheet

DEFAULT_BUCKET = "aind-open-data"
DEFAULT_SHEET_ID = 93261067669380
DEFAULT_DATA_GLOB = "/data/**/data_description.json"
NEUROGLANCER_HOST = "https://neuroglancer-demo.appspot.com"

SAMPLE_COLUMN = "Sample"
LINK_COLUMN = "1X Screening Link"


def find_data_description(explicit_path: str | None) -> str:
    """Return the path to a data_description.json file.

    Parameters
    ----------
    explicit_path : str or None
        Path to use directly. When None, ``DEFAULT_DATA_GLOB`` is searched and
        must match exactly one file.

    Returns
    -------
    str
        Path to the data_description.json file.

    Raises
    ------
    FileNotFoundError
        If the explicit path does not exist or the glob matches nothing.
    ValueError
        If the glob matches more than one file.
    """
    if explicit_path:
        if not os.path.isfile(explicit_path):
            raise FileNotFoundError(f"data_description.json not found: {explicit_path}")
        return explicit_path

    matches = glob.glob(DEFAULT_DATA_GLOB)
    if not matches:
        raise FileNotFoundError(
            f"No data_description.json found matching '{DEFAULT_DATA_GLOB}'. "
            "Pass --data-description explicitly."
        )
    if len(matches) > 1:
        raise ValueError(
            f"Multiple data_description.json files found: {matches}. "
            "Pass --data-description to disambiguate."
        )
    return matches[0]


def load_metadata(path: str) -> tuple[str, str]:
    """Return the dataset name and subject ID from a data_description.json file.

    Parameters
    ----------
    path : str
        Path to data_description.json.

    Returns
    -------
    tuple of (str, str)
        ``(dataset_name, subject_id)``.

    Raises
    ------
    KeyError
        If ``name`` or ``subject_id`` is missing or empty.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    name = data.get("name")
    subject_id = data.get("subject_id")
    if not name:
        raise KeyError(f"'name' missing from {path}")
    if not subject_id:
        raise KeyError(f"'subject_id' missing from {path}")
    return str(name), str(subject_id)


def build_neuroglancer_link(bucket: str, dataset_name: str) -> str:
    """Build the Neuroglancer link for a dataset's neuroglancer.json in S3.

    Parameters
    ----------
    bucket : str
        S3 bucket name.
    dataset_name : str
        Data asset name (top-level S3 prefix).

    Returns
    -------
    str
        Neuroglancer URL.
    """
    return f"{NEUROGLANCER_HOST}/#!s3://{bucket}/{dataset_name}/neuroglancer.json"


def get_column_ids(sheet: Any) -> dict[str, int]:
    """Map column titles to column ids for a sheet.

    Parameters
    ----------
    sheet : smartsheet.models.Sheet
        Sheet with populated ``columns``.

    Returns
    -------
    dict of str to int
        Column title to column id.
    """
    return {col.title: col.id for col in sheet.columns}


def _normalize_cell_value(cell: Any) -> str | None:
    """Return a normalized string for a Sample cell, or None if empty.

    Smartsheet returns numeric cell values as floats (e.g. 787425.0), so prefer
    ``display_value`` (the sheet's rendered text) and fall back to stripping a
    trailing ``.0`` from an integer-valued float.
    """
    if cell.display_value is not None:
        return str(cell.display_value).strip()

    value = cell.value
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def find_row_for_subject(sheet: Any, sample_column_id: int, subject_id: str) -> Any | None:
    """Return the row whose Sample cell equals ``subject_id``, or None.

    Parameters
    ----------
    sheet : smartsheet.models.Sheet
        Sheet with populated ``rows``.
    sample_column_id : int
        Column id of the Sample column.
    subject_id : str
        Subject ID to match.

    Returns
    -------
    smartsheet.models.Row or None
        The matching row, if any.
    """
    for row in sheet.rows:
        for cell in row.cells:
            if cell.column_id == sample_column_id:
                if _normalize_cell_value(cell) == subject_id:
                    return row
                break
    return None


def update_smartsheet(
    token: str, sheet_id: int, subject_id: str, link: str, dry_run: bool = False
) -> bool:
    """Write ``link`` to the screening-link column of the subject's row.

    Parameters
    ----------
    token : str
        Smartsheet API access token.
    sheet_id : int
        Smartsheet sheet ID.
    subject_id : str
        Subject ID used to find the row by the Sample column.
    link : str
        Neuroglancer link to write.
    dry_run : bool, optional
        If True, resolve the row but do not modify the sheet.

    Returns
    -------
    bool
        True if the sheet was updated, False on dry run.

    Raises
    ------
    KeyError
        If a required column is missing from the sheet.
    LookupError
        If no row matches ``subject_id``.
    """
    client = smartsheet.Smartsheet(token)
    client.errors_as_exceptions(True)

    sheet = client.Sheets.get_sheet(sheet_id)
    columns = get_column_ids(sheet)
    for required in (SAMPLE_COLUMN, LINK_COLUMN):
        if required not in columns:
            raise KeyError(
                f"Column '{required}' not found in sheet {sheet_id}. "
                f"Available columns: {sorted(columns)}"
            )
    sample_column_id = columns[SAMPLE_COLUMN]
    link_column_id = columns[LINK_COLUMN]

    row = find_row_for_subject(sheet, sample_column_id, subject_id)
    if row is None:
        raise LookupError(
            f"No row found with '{SAMPLE_COLUMN}' == '{subject_id}' in sheet {sheet_id}."
        )

    print(f"Matched row id: {row.id}")

    if dry_run:
        print("[dry-run] Sheet not modified.")
        return False

    new_cell = smartsheet.models.Cell()
    new_cell.column_id = link_column_id
    new_cell.value = link

    new_row = smartsheet.models.Row()
    new_row.id = row.id
    new_row.cells.append(new_cell)

    client.Sheets.update_rows(sheet_id, [new_row])

    print(f"Wrote link to '{LINK_COLUMN}' for subject {subject_id}.")
    return True
