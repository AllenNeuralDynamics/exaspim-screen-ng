"""Derived-asset metadata for the 1X screening capsule.

The capsule's ``/results`` folder becomes a derived data asset. This module
copies through the source asset's core metadata it does not change, rewrites
data description, processing and quality control, and adds a pending manual QC
metric whose reference is the raw Neuroglancer URL stored in the source
``neuroglancer.json``.
"""

import json
import platform
import shutil
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import distribution
from pathlib import Path
from typing import Any

from aind_data_schema.base import DataCoreModel
from aind_data_schema.components.identifiers import Code, DataAsset
from aind_data_schema.core.data_description import DataDescription
from aind_data_schema.core.processing import DataProcess, Processing, ProcessStage
from aind_data_schema.core.quality_control import QCMetric, QCStatus, QualityControl, Stage, Status
from aind_data_schema.utils.inheritance import derive_data_description
from aind_data_schema_models.modalities import Modality
from aind_data_schema_models.process_names import ProcessName

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

MODIFIED_MODELS: dict[str, type[DataCoreModel]] = {
    "data_description": DataDescription,
    "processing": Processing,
    "quality_control": QualityControl,
}

# Core files this capsule does not change. They are copied byte-for-byte and are
# never parsed, so schema problems in them cannot fail the run.
PASSTHROUGH_FILES: tuple[str, ...] = (
    "subject.json",
    "procedures.json",
    "instrument.json",
    "acquisition.json",
)


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


def load_source_core(source_dir: Path) -> tuple[dict[str, DataCoreModel], list[Path]]:
    """Load the core files this capsule rewrites and list the ones it copies.

    Only the files in ``MODIFIED_MODELS`` are validated against aind-data-schema.
    The files in ``PASSTHROUGH_FILES`` are never parsed, so validation problems in
    metadata this capsule does not change cannot fail the run.

    Parameters
    ----------
    source_dir : Path
        Directory containing ``data_description.json`` and any other core files.

    Returns
    -------
    dict of str to DataCoreModel
        Loaded models for the core files this capsule rewrites, keyed by field
        name. Files that are absent are omitted.
    list of Path
        Existing source files to copy through unchanged.

    Raises
    ------
    FileNotFoundError
        If ``data_description.json`` is missing.
    pydantic.ValidationError
        If one of the rewritten core files fails validation.
    """
    core: dict[str, DataCoreModel] = {}
    for field_name, model in MODIFIED_MODELS.items():
        path = source_dir / model.default_filename()
        if path.is_file():
            core[field_name] = _load_core_file(path, model)

    if "data_description" not in core:
        raise FileNotFoundError(f"data_description.json not found in {source_dir}")

    passthrough = [
        source_dir / name for name in PASSTHROUGH_FILES if (source_dir / name).is_file()
    ]
    return core, passthrough


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


@dataclass(frozen=True)
class DerivedAsset:
    """Identity of the derived asset and the core models written for it.

    Attributes
    ----------
    name : str
        Derived asset name.
    location : str
        S3 location the derived asset will be stored at.
    data_description, processing, quality_control : DataCoreModel
        The three core models this capsule writes.
    """

    name: str
    location: str
    data_description: DataDescription
    processing: Processing
    quality_control: QualityControl


def build_derived_metadata(
    source_core: dict[str, DataCoreModel],
    bucket: str,
    neuroglancer_url: str,
    start: datetime,
    end: datetime,
    parameters: dict[str, Any],
) -> DerivedAsset:
    """Build the three core models for the derived asset.

    No ``Metadata`` object is assembled, so cross-file checks over core metadata
    this capsule does not change are never run.

    Parameters
    ----------
    source_core : dict of str to DataCoreModel
        Source models from :func:`load_source_core`; ``data_description`` is
        required, ``processing`` and ``quality_control`` are optional.
    bucket : str
        S3 bucket the derived asset will be stored in.
    neuroglancer_url : str
        Raw Neuroglancer viewer URL used as the QC reference.
    start, end : datetime
        Timezone-aware start and end of the run. ``end`` is the creation time of
        the derived asset.
    parameters : dict
        Run parameters to record in processing.

    Returns
    -------
    DerivedAsset
        Derived name, location, and the derived data description, accumulated
        processing and accumulated quality control.
    """
    source_dd = source_core["data_description"]
    derived_dd = derive_data_description(source_dd, PROCESS_NAME, creation_time=end)

    processing = build_processing(start, end, source_dd.name, parameters)
    source_processing = source_core.get("processing")
    if source_processing is not None:
        processing = source_processing + processing

    quality_control = build_quality_control(neuroglancer_url, end)
    source_quality_control = source_core.get("quality_control")
    if source_quality_control is not None:
        quality_control = source_quality_control + quality_control

    return DerivedAsset(
        name=derived_dd.name,
        location=f"s3://{bucket}/{derived_dd.name}",
        data_description=derived_dd,
        processing=processing,
        quality_control=quality_control,
    )


def write_derived_asset(
    source_dir: Path,
    results_dir: Path,
    bucket: str,
    neuroglancer_url: str,
    start: datetime,
    end: datetime,
    parameters: dict[str, Any],
) -> DerivedAsset:
    """Write the derived asset's metadata and ``neuroglancer.json`` to ``results_dir``.

    The rewritten core files are written from models; every other core file is
    copied byte-for-byte from the source without being validated.

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
    DerivedAsset
        The derived asset that was written.

    Raises
    ------
    FileNotFoundError
        If ``neuroglancer.json`` or ``data_description.json`` is missing.
    """
    neuroglancer_json = source_dir / NEUROGLANCER_JSON
    if not neuroglancer_json.is_file():
        raise FileNotFoundError(f"{NEUROGLANCER_JSON} not found in {source_dir}")

    source_core, passthrough = load_source_core(source_dir)
    derived = build_derived_metadata(
        source_core, bucket, neuroglancer_url, start, end, parameters
    )

    results_dir.mkdir(parents=True, exist_ok=True)
    for model in (derived.data_description, derived.processing, derived.quality_control):
        model.write_standard_file(output_directory=results_dir)
    for path in passthrough:
        shutil.copyfile(path, results_dir / path.name)
    shutil.copyfile(neuroglancer_json, results_dir / NEUROGLANCER_JSON)
    return derived
