"""Neuroglancer screening links and derived metadata for exaSPIM data assets."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("exaspim-screen-ng")
except PackageNotFoundError:  # pragma: no cover - only hit when running from an uninstalled tree
    __version__ = "0.0.0"
