"""schema.org JSON-LD per dataset release, for ODIS harvesting (ADR-0001 D8). STUB.

One ``schema:Dataset`` per dataset release, from the reviewed view of the
store: name, description, ``identifier`` (DOI when the source has one),
``url`` (landing page), ``license``, ``creator`` / ``publisher``,
``version``, ``temporalCoverage`` and ``spatialCoverage`` where the graph
states them, ``distribution`` (``schema:DataDownload`` per file), and
``variableMeasured``: one ``schema:PropertyValue`` per measure column whose
``propertyID`` is the vocabulary IRI (PSC, gcdfo, smn or corp: profile) and
whose ``unitCode`` is the QUDT unit. Written as canonical JSON
(``io.det.write_json``) to ``dist/corpus-<version>/schemaorg/<slug>/<version>.jsonld``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .._stub import not_yet

if TYPE_CHECKING:  # pragma: no cover
    import pyoxigraph as ox

__all__ = ["dataset_jsonld", "write_dataset_jsonld"]


def dataset_jsonld(store: "ox.Store", dataset_iri: str) -> dict[str, Any]:
    """The schema.org JSON-LD document (``@context`` https://schema.org/) for one dataset release."""
    raise not_yet("publish.schemaorg.dataset_jsonld")


def write_dataset_jsonld(store: "ox.Store", dataset_iri: str, path: Path) -> Path:
    """Write :func:`dataset_jsonld` as canonical JSON; returns ``path``."""
    raise not_yet("publish.schemaorg.write_dataset_jsonld")
