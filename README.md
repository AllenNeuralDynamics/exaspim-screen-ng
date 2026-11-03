# exaspim-screen-ng

Code Ocean capsule for exaSPIM 1X screening. For a single source data asset it:

1. Builds a Neuroglancer link to the source asset's `neuroglancer.json` in S3 and writes it to the
   "1X Screening Link" column of the subject's row (matched on "Sample") in Smartsheet.
2. Writes a derived data asset to `/results`:
   - `data_description.json`: derived from the source (`<source>_processed_<datetime>`).
   - `subject.json`, `procedures.json`, `instrument.json`, `acquisition.json`: inherited from the
     source.
   - `processing.json`: source processing plus a step recording this package's version, commit
     and run parameters.
   - `quality_control.json`: source QC plus a PENDING manual Pass/Fail "1X screening" metric that
     links to the derived asset's `neuroglancer.json`.
   - `neuroglancer.json`: copied from the source asset.
   - `neuroglancer_link.json`: `{"url": ...}`, written only after a successful sheet update.
   - `pip_list.txt`: resolved environment.

The metadata is written before the Smartsheet step, and also on `--dry-run`.

## Inputs

A source asset attached under `/data` containing `data_description.json`, `neuroglancer.json` and
any other v2 core metadata files. Source `schema_version` values are replaced with the installed
aind-data-schema version.

The Smartsheet API token is read from the `CUSTOM_KEY` environment variable (a Code Ocean secret).

## Usage

```
exaspim-screen-ng [--data-description PATH] [--bucket aind-open-data]
                  [--sheet-id 93261067669380] [--results-dir /results] [--dry-run]
```

In Code Ocean, `code/run` calls `code/run_capsule.py`, a thin wrapper around
`exaspim_screen_ng.cli:main`. The package is installed from a pinned Git tag in
`environment/Dockerfile`; bump that tag when releasing.

## Development

```
uv sync
uv run ruff check
uv run pytest
```