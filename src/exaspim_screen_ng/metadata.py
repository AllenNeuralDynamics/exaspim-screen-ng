"""Derived-asset metadata for the 1X screening capsule.

The capsule's ``/results`` folder becomes a derived data asset. This module
inherits the source asset's core metadata, appends a processing step for this
package, and adds a pending manual QC metric whose reference is the raw
Neuroglancer URL stored in the source ``neuroglancer.json``.
"""

import json
import platform
import shutil
import warnings
from datetime import datetime
from importlib.metadata import distribution
from pathlib import Path
from typing import Any

from aind_data_schema.base import DataCoreModel
from aind_data_schema.components.identifiers import Code, DataAsset
from aind_data_schema.core.acquisition import Acquisition
from aind_data_schema.core.data_description import DataDescription
from aind_data_schema.core.instrument import Instrument
from aind_data_schema.core.metadata import Metadata
from aind_data_schema.core.procedures import Procedures
from aind_data_schema.core.processing import DataProcess, Processing, ProcessStage
from aind_data_schema.core.quality_control import QCMetric, QCStatus, QualityControl, Stage, Status
from aind_data_schema.core.subject import Subject
from aind_data_schema.utils.inheritance import derive_data_description
from aind_data_schema_models.modalities import Modality
from aind_data_schema_models.process_names import ProcessName
from pydantic import ValidationError

from exaspim_screen_ng import __version__

PACKAGE_NAME = "exaspim-screen-ng"
REPO_URL = "https://github.com/AllenNeuralDynamics/exaspim-screen-ng"
RUN_SCRIPT = Path("code/run")
PROCESS_NAME = "processed"
DATA_PROCESS_NAME = "1X screening neuroglancer link"
EXPERIMENTERS = ["Carson Berry"]
NEUROGLANCER_JSON = "neuroglancer.json"
NG_LINK_KEY = "ng_link"
QC_METRIC_NAME = "1X screening"
QC_TAG_KEY = "screening"
QC_TAG_VALUE = "1X"

CORE_MODELS: dict[str, type[DataCoreModel]] = {
    "data_description": DataDescription,
    "subject": Subject,
    "procedures": Procedures,
    "instrument": Instrument,
    "acquisition": Acquisition,
    "processing": Processing,
    "quality_control": QualityControl,
}

# Core files allowed to fail validation if every error is inside an object of
# this type. Such files are copied through unvalidated instead of being loaded.
PASSTHROUGH_ON_KNOWN_ERRORS: dict[str, str] = {"procedures": "Injection"}


def read_neuroglancer_link(path: Path) -> str:
    """Return the raw Neuroglancer viewer URL stored in a ``neuroglancer.json``.

    Parameters
    ----------
    path : Path
        Path to ``neuroglancer.json``.

    Returns
    -------
    str
        The viewer URL.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    KeyError
        If the file has no ``ng_link`` entry.
    """
    state = json.loads(path.read_text(encoding="utf-8"))
    if NG_LINK_KEY not in state:
        raise KeyError(f"'{NG_LINK_KEY}' not found in {path}")
    return state[NG_LINK_KEY]

PASSTHROUGH_ON_KNOWN_ERRORS = {"procedures": "Injection"}  # field -> loc tag

def _is_known_issue(exc: ValidationError, tag: str) -> bool:
    return all(tag in err["loc"] for err in exc.errors())

def _load_core_file(path: Path, model: type[DataCoreModel]) -> DataCoreModel:
    """Validate a core JSON file against the installed schema version.

    ``schema_version`` is dropped first so the object takes the installed
    version. It is declared ``SkipValidation`` in aind-data-schema, so a stale
    value would otherwise survive and break ``Processing``/``QualityControl``
    addition, which requires matching versions.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("schema_version", None)
    return model.model_validate(data)


def load_source_metadata(source_dir: Path, bucket: str) -> tuple[Metadata, list[Path]]:
    """Load the source asset's core metadata files into a ``Metadata`` object.

    Core files listed in ``PASSTHROUGH_ON_KNOWN_ERRORS`` whose only validation
    errors are known issues are left out of the ``Metadata`` and returned
    separately so they can be copied through unchanged.

    Parameters
    ----------
    source_dir : Path
        Directory containing ``data_description.json`` and any other core files.
    bucket : str
        S3 bucket holding the source asset, used to set ``location``.

    Returns
    -------
    Metadata
        Source metadata. Core files that are absent or passed through are None.
    list of Path
        Core files that failed validation only on known issues.

    Raises
    ------
    FileNotFoundError
        If ``data_description.json`` is missing.
    pydantic.ValidationError
        If a core file fails validation for reasons other than a known issue.
    """
    core: dict[str, Any] = {}
    passthrough: list[Path] = []
    for field_name, model in CORE_MODELS.items():
        path = source_dir / model.default_filename()
        if not path.is_file():
            continue
        try:
            core[field_name] = _load_core_file(path, model)
        except ValidationError as exc:
            tag = PASSTHROUGH_ON_KNOWN_ERRORS.get(field_name)
            if tag is None or not _is_known_issue(exc, tag):
                raise
            warnings.warn(
                f"{path.name}: {exc.error_count()} known {tag} validation errors; "
                "copying unvalidated.",
                stacklevel=2,
            )
            passthrough.append(path)

    data_description = core.get("data_description")
    if data_description is None:
        raise FileNotFoundError(f"data_description.json not found in {source_dir}")

    name = data_description.name
    metadata = Metadata(name=name, location=f"s3://{bucket}/{name}", **core)
    return metadata, passthrough


def _installed_commit_hash() -> str | None:
    """Return the Git commit this package was installed from, if recorded by pip."""
    direct_url = distribution(PACKAGE_NAME).read_text("direct_url.json")
    if not direct_url:
        return None
    return json.loads(direct_url).get("vcs_info", {}).get("commit_id")


def build_code(source_name: str, parameters: dict[str, Any]) -> Code:
    """Describe the code used for this processing step.

    Parameters
    ----------
    source_name : str
        Name of the input data asset.
    parameters : dict
        Run parameters to record.

    Returns
    -------
    Code
        Code identity including version, commit (when installed from Git),
        input data and parameters.
    """
    return Code(
        url=REPO_URL,
        name=PACKAGE_NAME,
        version=__version__,
        commit_hash=_installed_commit_hash(),
        run_script=RUN_SCRIPT,
        language="Python",
        language_version=platform.python_version(),
        input_data=[DataAsset(name=source_name)],
        parameters=parameters,
    )


def build_processing(
    start: datetime, end: datetime, source_name: str, parameters: dict[str, Any]
) -> Processing:
    """Build the processing record for this run.

    Parameters
    ----------
    start, end : datetime
        Timezone-aware start and end of the run.
    source_name : str
        Name of the input data asset.
    parameters : dict
        Run parameters to record.

    Returns
    -------
    Processing
        Processing with a single data process.
    """
    process = DataProcess(
        process_type=ProcessName.OTHER,
        name=DATA_PROCESS_NAME,
        stage=ProcessStage.PROCESSING,
        code=build_code(source_name, parameters),
        experimenters=EXPERIMENTERS,
        start_date_time=start,
        end_date_time=end,
        notes="Copied neuroglancer.json and wrote the 1X screening link to Smartsheet.",
    )
    return Processing.create_with_sequential_process_graph(data_processes=[process])



def build_quality_control(neuroglancer_url: str, timestamp: datetime) -> QualityControl:
    """Build a pending manual Pass/Fail 1X screening QC metric.

    Parameters
    ----------
    neuroglancer_url : str
        Raw Neuroglancer viewer URL from the source ``neuroglancer.json``; the
        same link written to Smartsheet.
    timestamp : datetime
        Timezone-aware time of the initial PENDING status.

    Returns
    -------
    QualityControl
        Quality control with one metric awaiting manual review.
    """
    metric = QCMetric(
        name=QC_METRIC_NAME,
        modality=Modality.SPIM,
        stage=Stage.RAW,
        value={
            "value": "",
            "options": ["Pass", "Fail"],
            "status": [Status.PASS.value, Status.FAIL.value],
            "type": "dropdown",
        },
        status_history=[QCStatus(evaluator="", status=Status.PENDING, timestamp=timestamp)],
        description="Manual 1X screening of the dataset in Neuroglancer.",
        reference=neuroglancer_url,
        tags={QC_TAG_KEY: QC_TAG_VALUE},
    )
    return QualityControl(metrics=[metric], default_grouping=[QC_TAG_KEY])


def build_derived_metadata(
    source: Metadata,
    bucket: str,
    neuroglancer_url: str,
    start: datetime,
    end: datetime,
    parameters: dict[str, Any],
) -> Metadata:
    """Derive metadata for the results asset from the source metadata.

    The derived name is computed up front with ``end`` as ``creation_time`` so
    ``location`` matches the name ``from_metadata`` produces.

    Parameters
    ----------
    source : Metadata
        Source asset metadata with a data description.
    bucket : str
        S3 bucket the derived asset will be stored in.
    neuroglancer_url : str
        Raw Neuroglancer viewer URL used as the QC reference.
    start, end : datetime
        Timezone-aware start and end of the run.
    parameters : dict
        Run parameters to record in processing.

    Returns
    -------
    Metadata
        Derived metadata with inherited core files, accumulated processing and
        quality control.
    """
    source_name = source.data_description.name
    derived_name = derive_data_description(
        source.data_description, PROCESS_NAME, creation_time=end
    ).name
    return Metadata.from_metadata(
        source,
        process_name=PROCESS_NAME,
        location=f"s3://{bucket}/{derived_name}",
        new_processing=build_processing(start, end, source_name, parameters),
        new_quality_control=build_quality_control(neuroglancer_url, end),
        creation_time=end,
    )


def write_derived_asset(
    source_dir: Path,
    results_dir: Path,
    bucket: str,
    neuroglancer_url: str,
    start: datetime,
    end: datetime,
    parameters: dict[str, Any],
) -> Metadata:
    """Write derived metadata and the source ``neuroglancer.json`` to ``results_dir``.

    Core files that failed validation only on known issues are copied through
    unchanged.

    Parameters
    ----------
    source_dir : Path
        Source asset directory containing core JSONs and ``neuroglancer.json``.
    results_dir : Path
        Output directory for the derived asset.
    bucket : str
        S3 bucket for the source and derived assets.
    neuroglancer_url : str
        Raw Neuroglancer viewer URL used as the QC reference.
    start, end : datetime
        Timezone-aware start and end of the run.
    parameters : dict
        Run parameters to record in processing.

    Returns
    -------
    Metadata
        The derived metadata that was written.

    Raises
    ------
    FileNotFoundError
        If ``neuroglancer.json`` or ``data_description.json`` is missing.
    """
    neuroglancer_json = source_dir / NEUROGLANCER_JSON
    if not neuroglancer_json.is_file():
        raise FileNotFoundError(f"{NEUROGLANCER_JSON} not found in {source_dir}")

    source, passthrough = load_source_metadata(source_dir, bucket)
    derived = build_derived_metadata(
        source, bucket, neuroglancer_url, start, end, parameters
    )

    results_dir.mkdir(parents=True, exist_ok=True)
    derived.write_standard_files(output_directory=results_dir)
    for path in passthrough:
        shutil.copyfile(path, results_dir / path.name)
    shutil.copyfile(neuroglancer_json, results_dir / NEUROGLANCER_JSON)
    return derived