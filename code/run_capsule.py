"""Write a Neuroglancer link to a Smartsheet row for a given dataset.

Reads a dataset's ``data_description.json`` to determine the dataset name and
subject ID, builds a Neuroglancer link pointing at the ``neuroglancer.json`` in
S3, finds the matching row in the Smartsheet (by subject ID in the "Sample"
column), and writes the link to the "1X Screening Link" column.
"""

import argparse
import glob
import json
import os
import sys

import smartsheet

# Defaults
DEFAULT_BUCKET = "aind-open-data"
DEFAULT_SHEET_ID = 93261067669380
DEFAULT_DATA_GLOB = "/data/**/data_description.json"
NEUROGLANCER_HOST = "https://neuroglancer-demo.appspot.com"
OUTPUT_PATH =  "/results/neuroglancer_link.json"

SAMPLE_COLUMN = "Sample"
LINK_COLUMN = "1X Screening Link"


def find_data_description(explicit_path: str | None) -> str:
    """Return the path to a data_description.json file.

    If ``explicit_path`` is provided it is used directly; otherwise the default
    glob is used and must match exactly one file.
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
    """Return (dataset_name, subject_id) from a data_description.json file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    name = data.get("name")
    subject_id = data.get("subject_id")
    if not name:
        raise KeyError(f"'name' missing from {path}")
    if not subject_id:
        raise KeyError(f"'subject_id' missing from {path}")
    return str(name), str(subject_id)


def build_neuroglancer_link(bucket: str, dataset_name: str) -> str:
    """Build the Neuroglancer link for a dataset's neuroglancer.json in S3."""
    return f"{NEUROGLANCER_HOST}/#!s3://{bucket}/{dataset_name}/neuroglancer.json"


def get_column_ids(sheet) -> dict[str, int]:
    """Map column titles to column ids for a sheet."""
    return {col.title: col.id for col in sheet.columns}


def _normalize_cell_value(cell) -> str | None:
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


def find_row_for_subject(sheet, sample_column_id: int, subject_id: str):
    """Return the row whose Sample cell equals subject_id, or None."""
    for row in sheet.rows:
        for cell in row.cells:
            if cell.column_id == sample_column_id:
                if _normalize_cell_value(cell) == subject_id:
                    return row
                break
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-description",
        default=None,
        help=(
            "Path to data_description.json. Defaults to globbing "
            f"'{DEFAULT_DATA_GLOB}'."
        ),
    )
    parser.add_argument(
        "--bucket",
        default=DEFAULT_BUCKET,
        help=f"S3 bucket name (default: {DEFAULT_BUCKET}).",
    )
    parser.add_argument(
        "--sheet-id",
        type=int,
        default=DEFAULT_SHEET_ID,
        help=f"Smartsheet sheet ID (default: {DEFAULT_SHEET_ID}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve everything and print, but do not update the sheet.",
    )
    args = parser.parse_args()

    # 1-3. Read metadata and build link.
    dd_path = find_data_description(args.data_description)
    dataset_name, subject_id = load_metadata(dd_path)
    link = build_neuroglancer_link(args.bucket, dataset_name)

    print(f"Dataset:      {dataset_name}")
    print(f"Subject ID:   {subject_id}")
    print(f"Neuroglancer: {link}")

    # 4. Connect to Smartsheet.
    token = os.environ.get("CUSTOM_KEY")
    if not token:
        raise EnvironmentError("Environment variable CUSTOM_KEY is not set.")

    client = smartsheet.Smartsheet(token)
    client.errors_as_exceptions(True)

    # 5. Resolve columns.
    sheet = client.Sheets.get_sheet(args.sheet_id)
    columns = get_column_ids(sheet)
    for required in (SAMPLE_COLUMN, LINK_COLUMN):
        if required not in columns:
            raise KeyError(
                f"Column '{required}' not found in sheet {args.sheet_id}. "
                f"Available columns: {sorted(columns)}"
            )
    sample_column_id = columns[SAMPLE_COLUMN]
    link_column_id = columns[LINK_COLUMN]

    # 6. Find the row for this subject.
    row = find_row_for_subject(sheet, sample_column_id, subject_id)
    if row is None:
        raise LookupError(
            f"No row found with '{SAMPLE_COLUMN}' == '{subject_id}' "
            f"in sheet {args.sheet_id}."
        )

    print(f"Matched row id: {row.id}")

    if args.dry_run:
        print("[dry-run] Sheet not modified.")
        return 0

    # 7. Write the link and save.
    new_cell = smartsheet.models.Cell()
    new_cell.column_id = link_column_id
    new_cell.value = link

    new_row = smartsheet.models.Row()
    new_row.id = row.id
    new_row.cells.append(new_cell)

    client.Sheets.update_rows(args.sheet_id, [new_row])

    print(f"Wrote link to '{LINK_COLUMN}' for subject {subject_id}.")

    temp_dict ={"url": link}
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(temp_dict, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
