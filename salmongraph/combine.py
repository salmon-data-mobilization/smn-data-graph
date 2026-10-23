"""The combine step: one corpus store, shared graphs, cross-source checks. STUB.

The only step that reads several datasets (architecture.md section 5). It
loads every dataset build into one pyoxigraph store, keeps each dataset's
named graphs, adds the vocabularies and the shared corpus graphs, and runs
the cross-source checks the specs declare.

Inputs
    ``build/<slug>/<version>/`` folders (each ``manifest.json`` is verified
    before its ``dataset.trig`` is loaded); a corpus version (e.g.
    ``2026.10.27``); an explicit ``build_date``; a ``VocabIndex``; the
    published identity sources (``identity.py``).

Outputs, under ``build/corpus/<corpus-version>/`` (``corpus`` is a reserved
slug, so this never collides with a dataset build)::

    store/                on-disk pyoxigraph store: every dataset graph, the vocab
                          graphs (VocabIndex.load_into) and the shared graphs
    shared.trig           the shared graphs only, sorted TriG
    crosswalk.sssom.tsv   the crosswalk graph as SSSOM/TSV (metasalmonpy writes the TSV)
    checks.json           cross-source check results, canonical JSON
    summary.json          quads per graph, datasets, nodes per authority, links by
                          predicate, discrepancies by explanation, top term gaps

Shared graphs written here (``iri.corpus_graph(name, corpus_version)``):
``identity`` (nodes from published identity sources), ``membership``,
``crosswalk``, ``quality`` (DQV annotations: ``dqv:QualityAnnotation`` with
``oa:hasTarget`` the observations, ``dqv:inDimension`` a concept of the
``corp:discrepancy-explanations`` profile scheme, plus a
``dqv:QualityMeasurement`` holding the relative difference), ``vocab-pins``
(``VocabIndex.provenance`` and ``provenance.profile_vocabulary``). ``review``
is written by ``review.py``; ``catalog`` by ``catalog.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from ._stub import not_yet
from .config import ROOT

if TYPE_CHECKING:  # pragma: no cover
    import pyoxigraph as ox

    from .vocab import VocabIndex

__all__ = ["CORPUS_BUILD_DIR", "CombineResult", "corpus_build_dir", "load_dataset_build",
           "combine", "run_cross_source_checks"]

#: ``build/corpus/`` at the repository root.
CORPUS_BUILD_DIR = ROOT / "build" / "corpus"


@dataclass
class CombineResult:
    """What :func:`combine` wrote."""

    corpus_version: str
    out_dir: Path
    store_dir: Path
    graphs: dict[str, str] = field(default_factory=dict)        # shared graph name -> IRI
    datasets: list[str] = field(default_factory=list)           # dataset release IRIs loaded
    quads: int = 0
    crosswalk_links: dict[str, int] = field(default_factory=dict)   # predicate CURIE -> count
    discrepancies: dict[str, int] = field(default_factory=dict)     # explanation -> count


def corpus_build_dir(corpus_version: str) -> Path:
    """``build/corpus/<segment(corpus_version)>/``."""
    raise not_yet("combine.corpus_build_dir")


def load_dataset_build(store: "ox.Store", build_dir: Path) -> dict:
    """Verify ``build_dir/manifest.json`` and load ``dataset.trig`` into ``store``.

    Returns the manifest (dict). Refuses a build whose file sha256s do not
    match its manifest.
    """
    raise not_yet("combine.load_dataset_build")


def combine(build_dirs: Sequence[Path], *, corpus_version: str, build_date: str,
            vocab: "VocabIndex | None" = None, out_dir: Path | None = None) -> CombineResult:
    """Build the combined store and the shared graphs; run the declared cross-source checks."""
    raise not_yet("combine.combine")


def run_cross_source_checks(store: "ox.Store", *, corpus_version: str, build_date: str,
                            parquet_dirs: Sequence[Path]) -> dict:
    """Evaluate every spec's ``cross_source_checks`` with DuckDB over the observation Parquet.

    Joins go through the crosswalk graph (never by name). Returns the
    results for ``checks.json``; quality annotations are written by
    :func:`combine`.
    """
    raise not_yet("combine.run_cross_source_checks")
