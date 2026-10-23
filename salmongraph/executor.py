"""The shared dataset executor: spec -> SDP, dataset graphs, Parquet, report. STUB.

Turns one :class:`~salmongraph.spec.DatasetSpec` plus its raw files into a
complete, deterministic dataset build (ADR-0001 D11; architecture.md 12.3).
The executor, not the agent, writes the RDF. This module includes the SDP ->
RDF compiler of ADR-0001 D3 (architecture.md 12.1 calls it ``compile.py``).

Inputs
    ``specs/<slug>.yaml``; ``data/raw/<slug>/`` (files named in the spec, with
    ``SHA256SUMS`` and ``source.json`` as ``corpuslib.fetch_source`` writes
    them; sha256 must match the spec); a :class:`~salmongraph.vocab.VocabIndex`;
    an explicit ``build_date`` (YYYY-MM-DD; never the wall clock); optionally
    the :class:`AgentRun` whose agent wrote the spec's agent-derived semantics.

Outputs, under ``build/<slug>/<version>/`` (git-ignored; ``version`` is
``iri.segment(spec.version)``)::

    dataset.trig          all five named graphs (config.DATASET_GRAPH_PARTS), sorted TriG
    observations.parquet  one row per observation, keyed by observation IRI (below)
    sdp/                  the Salmon Data Package (metasalmonpy), validated
    report.md             human report: counts, gaps, review queue summary, cross-source expectations
    report.json           the same facts, machine-readable, canonical JSON (io.det.write_json)
    review-queue.csv      review.REVIEW_QUEUE_COLUMNS, critical first
    manifest.json         every file above with bytes + sha256, the input pins (raw files,
                          spec sha256, vocab pins, tool versions), quad counts per graph

Nothing in these files depends on the wall clock or the machine: timings and
costs go to the run ledger (``ledger.py``), not to ``report.json``.

``observations.parquet`` columns (pyarrow, zstd; rows sorted by ``obs_iri``)::

    obs_iri            string, unique (iri.obs(slug, version, *key, measure))
    dataset_iri        string (iri.dataset(slug, version))
    measure_iri        string: the column's concept (PSC, gcdfo or corp: profile)
    value              float64 (rows without a value are not written)
    unit_iri           string (QUDT)
    year               int32; year_basis_iri string (smn:broodYear | smn:returnYear)
    <dimension>_iri    string, one per identity/code dimension (identity nodes via iri.ident)
    standard_error, cv, lower, upper     float64, only when the spec names the columns
    estimate_type_iri, method_iri        string, nullable
    review_status      string: the weakest status among the semantics this value depends on

Graph contents per part (architecture.md 7.1): ``metadata`` (DCAT dataset and
distributions, CSVW tables and columns, variables, licence, attribution),
``mappings`` (source codes as SKOS concepts and their mappings), ``identity``
(authority nodes this dataset mentions), ``cube`` (RDF Data Cube / SOSA
observations worth querying in RDF: aggregates, not every row), ``provenance``
(the build activity, inputs and checksums, tool versions,
``VocabIndex.provenance()``). D6 marks go in the graph of the statement they
mark.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from ._stub import not_yet
from .config import ROOT

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

    from .graph import GraphBuilder
    from .spec import DatasetSpec
    from .vocab import VocabIndex

__all__ = ["BUILD_DIR", "BUILD_FILES", "AgentRun", "BuildResult", "build_dir", "build_dataset",
           "compile_dataset_graph", "write_observations"]

#: ``build/`` at the repository root.
BUILD_DIR = ROOT / "build"
#: File names every dataset build writes (``sdp`` is a directory).
BUILD_FILES = ("dataset.trig", "observations.parquet", "sdp", "report.md", "report.json",
               "review-queue.csv", "manifest.json")


@dataclass(frozen=True)
class AgentRun:
    """The agent run whose output a build marks (ADR-0001 D6).

    ``run_id`` is the ``runs/<run-id>/`` folder name; ``model`` the exact model
    identifier; ``date`` YYYY-MM-DD of the run. The executor turns these into
    ``provenance.ai_agent`` and an ``iri.activity("agent-run", run_id)`` node.
    """

    run_id: str
    model: str
    date: str


@dataclass
class BuildResult:
    """What :func:`build_dataset` wrote."""

    slug: str
    version: str
    out_dir: Path
    files: dict[str, Path] = field(default_factory=dict)       # BUILD_FILES name -> path
    graphs: dict[str, str] = field(default_factory=dict)       # part -> named graph IRI
    quads: int = 0
    observations: int = 0
    review_counts: dict[str, int] = field(default_factory=dict)  # status token -> count
    undeclared: list[str] = field(default_factory=list)        # must be empty for a good build
    shacl_conforms: bool | None = None


def build_dir(slug: str, version: str) -> Path:
    """``build/<slug>/<segment(version)>/``."""
    raise not_yet("executor.build_dir")


def build_dataset(spec: "DatasetSpec", *, build_date: str, vocab: "VocabIndex | None" = None,
                  raw_dir: Path | None = None, out_dir: Path | None = None,
                  run: AgentRun | None = None, validate: bool = True) -> BuildResult:
    """Build one dataset release from its spec; returns what was written.

    Steps: verify raw files against the spec's sha256 -> parse tables (spec
    ``parser``) -> write and validate the SDP with metasalmonpy -> compile the
    graphs (:func:`compile_dataset_graph`) -> ``GraphBuilder.assert_vocab()``
    -> SHACL gate (``validate.assert_valid`` unless ``validate=False``) ->
    observations Parquet -> review queue -> reports -> manifest.

    Raises on undeclared vocabulary IRIs, SHACL violations, checksum
    mismatches and spec problems (``spec.validate_spec``); a failed build
    leaves no partial ``dataset.trig``.
    """
    raise not_yet("executor.build_dataset")


def compile_dataset_graph(spec: "DatasetSpec", sdp_dir: Path, *, builder: "GraphBuilder",
                          build_date: str, run: AgentRun | None = None) -> dict[str, str]:
    """SDP + spec -> quads in ``builder``, one named graph per part; returns {part: graph IRI}.

    Reads the SDP with metasalmonpy (``read_salmon_datapackage``,
    ``read_sdp_observation_structures``, ``read_sdp_measurement_decompositions``,
    ``read_sssom_mapping_set``) rather than re-deriving what the package says.
    """
    raise not_yet("executor.compile_dataset_graph")


def write_observations(spec: "DatasetSpec", frames: Mapping[str, "pd.DataFrame"], path: Path) -> int:
    """Write ``observations.parquet`` (columns in the module docstring); returns the row count."""
    raise not_yet("executor.write_observations")
