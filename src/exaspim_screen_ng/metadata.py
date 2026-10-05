"""Derived-asset metadata for the 1X screening capsule.

The capsule's ``/results`` folder becomes a derived data asset. This module
inherits the source asset's core metadata, appends a processing step for this
package, and adds a pending manual QC metric that links to the derived asset's
``neuroglancer.json``.
"""

import json
import platform
import shutil
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

from exaspim_screen_ng import __version__
from exaspim_screen_ng.smartsheet_link import build_neuroglancer_link

PACKAGE_NAME = "exaspim-screen-ng"
REPO_URL = "https://github.com/AllenNeuralDynamics/exaspim-screen-ng"
RUN_SCRIPT = Path("code/run")
PROCESS_NAME = "processed"
DATA_PROCESS_NAME = "1X screening neuroglancer link"
EXPERIMENTERS = ["Carson Berry"]
NEUROGLANCER_JSON = "neuroglancer.json"
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


def load_source_metadata(source_dir: Path, bucket: str) -> Metadata:
    """Load the source asset's core metadata files into a ``Metadata`` object.

    Parameters
    ----------
    source_dir : Path
        Directory containing ``data_description.json`` and any other core files.
    bucket : str
        S3 bucket holding the source asset, used to set ``location``.

    Returns
    -------
    Metadata
        Source metadata. Core files that are absent are left as None.

    Raises
    ------
    FileNotFoundError
        If ``data_description.json`` is missing.
    """
    core: dict[str, Any] = {}
    for field_name, model in CORE_MODELS.items():
        path = source_dir / model.default_filename()
        if path.is_file():
            core[field_name] = _load_core_file(path, model)

    data_description = core.get("data_description")
    if data_description is None:
        raise FileNotFoundError(f"data_description.json not found in {source_dir}")

    name = data_description.name
    return Metadata(name=name, location=f"s3://{bucket}/{name}", **core)


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
        Link to the derived asset's ``neuroglancer.json``.
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
    start: datetime,
    end: datetime,
    parameters: dict[str, Any],
) -> Metadata:
    """Derive metadata for the results asset from the source metadata.

    The derived name is computed up front with ``end`` as ``creation_time`` so
    the QC reference can point at the derived asset's ``neuroglancer.json``;
    the same ``creation_time`` is passed to ``from_metadata`` so the names
    agree.

    Parameters
    ----------
    source : Metadata
        Source asset metadata with a data description.
    bucket : str
        S3 bucket the derived asset will be stored in.
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
        new_quality_control=build_quality_control(
            build_neuroglancer_link(bucket, derived_name), end
        ),
        creation_time=end,
    )


def write_derived_asset(
    source_dir: Path,
    results_dir: Path,
    bucket: str,
    start: datetime,
    end: datetime,
    parameters: dict[str, Any],
) -> Metadata:
    """Write derived metadata and the source ``neuroglancer.json`` to ``results_dir``.

    Parameters
    ----------
    source_dir : Path
        Source asset directory containing core JSONs and ``neuroglancer.json``.
    results_dir : Path
        Output directory for the derived asset.
    bucket : str
        S3 bucket for the source and derived assets.
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

    source = load_source_metadata(source_dir, bucket)
    derived = build_derived_metadata(source, bucket, start, end, parameters)

    results_dir.mkdir(parents=True, exist_ok=True)
    derived.write_standard_files(output_directory=results_dir)
    shutil.copyfile(neuroglancer_json, results_dir / NEUROGLANCER_JSON)
    return derived
