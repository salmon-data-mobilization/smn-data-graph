"""KNB (DataONE) publication plans: the golden path (ADR-0001 D8). STUB.

Thin wrappers over ``metasalmonpy.publish_sdp_to_knb`` in its default
**dry-run** mode, which is credential-free and network-free and writes the
exact plan (objects, EML, resource map) that a live publication must match.
This module never passes ``dry_run=False`` or ``confirm=True``: Brett runs
the live publication himself with metasalmonpy (or metasalmon), against the
plan written here. Datasets whose redistribution is unconfirmed are refused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .._stub import not_yet

__all__ = ["plan_dataset_publication", "plan_release_publication"]


def plan_dataset_publication(sdp_dir: Path, *, manifest_path: Path, eml_path: Path | None = None,
                             public: bool | None = None) -> dict[str, Any]:
    """Dry-run plan for one SDP (``publish_sdp_to_knb(..., dry_run=True)``); writes ``manifest_path``."""
    raise not_yet("publish.knb.plan_dataset_publication")


def plan_release_publication(release_dir: Path) -> dict[str, Any]:
    """Dry-run plans for every SDP in a release, plus the corpus release package with its EML."""
    raise not_yet("publish.knb.plan_release_publication")
