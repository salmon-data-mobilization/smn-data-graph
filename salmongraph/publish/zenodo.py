"""Zenodo deposition metadata for corpus releases (ADR-0001 D8). STUB.

Prepares the deposition metadata (title, version, creators with ORCIDs,
licence, description, keywords, related identifiers: the source DOIs as
``isDerivedFrom``, the KNB packages, the previous release as
``isNewVersionOf``) following the PICES WG52 repository protocol, and writes
it beside the release as ``dist/corpus-<version>/zenodo.json``. It never
uploads; Brett creates the deposition and uploads the files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .._stub import not_yet

__all__ = ["deposition_metadata", "write_deposition_metadata"]


def deposition_metadata(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Zenodo ``metadata`` object for a release manifest (``release.py``)."""
    raise not_yet("publish.zenodo.deposition_metadata")


def write_deposition_metadata(release_dir: Path) -> Path:
    """Write ``zenodo.json`` (canonical JSON) into ``release_dir``; returns its path."""
    raise not_yet("publish.zenodo.write_deposition_metadata")
