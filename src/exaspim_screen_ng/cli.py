"""Command-line entry point for exaSPIM 1X screening.

Reads a dataset's ``data_description.json`` to determine the dataset name and
subject ID, builds a Neuroglancer link pointing at the ``neuroglancer.json`` in
S3, finds the matching row in the Smartsheet (by subject ID in the "Sample"
column), and writes the link to the "1X Screening Link" column.
"""

import argparse
import json
import os
from pathlib import Path

from exaspim_screen_ng.smartsheet_link import (
    DEFAULT_BUCKET,
    DEFAULT_DATA_GLOB,
    DEFAULT_SHEET_ID,
    build_neuroglancer_link,
    find_data_description,
    load_metadata,
    update_smartsheet,
)

DEFAULT_RESULTS_DIR = "/results"
LINK_OUTPUT_NAME = "neuroglancer_link.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Parameters
    ----------
    argv : list of str, optional
        Arguments to parse. Defaults to ``sys.argv[1:]``.

    Returns
    -------
    argparse.Namespace
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-description",
        default=None,
        help=f"Path to data_description.json. Defaults to globbing '{DEFAULT_DATA_GLOB}'.",
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
        "--results-dir",
        default=DEFAULT_RESULTS_DIR,
        help=f"Directory to write outputs to (default: {DEFAULT_RESULTS_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve everything and print, but do not update the sheet.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the screening-link workflow.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments. Defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit code.

    Raises
    ------
    OSError
        If the ``CUSTOM_KEY`` environment variable is not set.
    """
    args = parse_args(argv)

    dd_path = find_data_description(args.data_description)
    dataset_name, subject_id = load_metadata(dd_path)
    link = build_neuroglancer_link(args.bucket, dataset_name)

    print(f"Dataset:      {dataset_name}")
    print(f"Subject ID:   {subject_id}")
    print(f"Neuroglancer: {link}")

    token = os.environ.get("CUSTOM_KEY")
    if not token:
        raise OSError("Environment variable CUSTOM_KEY is not set.")

    updated = update_smartsheet(token, args.sheet_id, subject_id, link, dry_run=args.dry_run)
    if not updated:
        return 0

    with open(Path(args.results_dir) / LINK_OUTPUT_NAME, "w", encoding="utf-8") as f:
        json.dump({"url": link}, f)
    return 0
