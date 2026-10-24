"""Shared deterministic dataset execution, compilation and observations.

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
import datetime as _dt
from decimal import Decimal
import math
from numbers import Integral, Real
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from . import config, iri, provenance
from .config import ROOT
from .graph import N, expand
from .io import det
from .spec import SpecError, _column_requires_critical_mark

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
    # Use the same guards as the release IRI before constructing a filesystem
    # path; source versions remain encoded rather than becoming path segments.
    iri.dataset(slug, version)
    return BUILD_DIR / slug / iri.segment(version)


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
    # Keep SDK parsing/orchestration behind a small entrypoint. The private
    # builder shares this module's observation projection and result contract.
    from ._build import build_dataset as build

    return build(spec, build_date=build_date, vocab=vocab, raw_dir=raw_dir,
                 out_dir=out_dir, run=run, validate=validate)


def compile_dataset_graph(spec: "DatasetSpec", sdp_dir: Path, *, builder: "GraphBuilder",
                          build_date: str, run: AgentRun | None = None) -> dict[str, str]:
    """SDP + spec -> quads in ``builder``, one named graph per part; returns {part: graph IRI}.

    Reads the SDP with metasalmonpy (``read_salmon_datapackage``,
    ``read_sdp_observation_structures``, ``read_sdp_measurement_decompositions``,
    ``read_sssom_mapping_set``) rather than re-deriving what the package says.
    """
    # Import lazily: the compiler shares source-code/key helpers from this
    # module, while its RDF/SDK work remains behind this small public entrypoint.
    from ._compile import compile_dataset_graph as compile_graph

    return compile_graph(spec, sdp_dir, builder=builder, build_date=build_date, run=run)


def write_observations(spec: "DatasetSpec", frames: Mapping[str, "pd.DataFrame"], path: Path) -> int:
    """Write source values as deterministic zstd Parquet; return the row count.

    ``frames`` is keyed by the spec's table id. Parsing and vocabulary-pin
    validation belong to the build orchestrator. This writer still refuses
    ambiguous/missing bindings, duplicate source keys, observation collisions,
    non-finite numbers and invalid uncertainty before touching the output.
    NaN/NA/None/empty cells are missing values, not zero or a source sentinel.

    The explicit ``year_column`` supplies an exact int32 year. Other dimensions
    resolve only through an identity declaration or a source code declaration.
    Code dimensions use source-local IRIs, including codes with null *target*
    mappings; vocabulary targets are not substituted for source codes. Marks
    on contributing columns determine the weakest status. Unmarked source
    semantics have a null status, never an invented review decision.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    # A direct projection call must enforce the same scope rule as the Spec
    # validator and compiler. Label-only evidence cannot approve a unit, code
    # mapping or year interpretation merely because its confidence is high.
    years = {(block.get("table"), block.get("year_column")) for block in spec.observations}
    for table in spec.tables:
        for column in table["columns"]:
            mark = column.get("mark")
            if (mark and _column_requires_critical_mark(
                    column, referenced_year=(table["id"], column["name"]) in years)
                    and provenance.criticality_of(mark["aspect"]) != "critical"):
                raise SpecError("observations: a mark governing column semantics or year basis must be critical")

    tables = {table["id"]: table for table in spec.tables}
    if len(tables) != len(spec.tables):
        raise SpecError("observations: duplicate table ids")
    identities = {}
    for block in spec.identity:
        key = (block["table"], block["column"])
        if key in identities:
            raise SpecError(f"observations: duplicate identity declaration for {key!r}")
        identities[key] = block

    # Establish the entire schema from the spec, including an empty release.
    # Source dimension names are retained verbatim, never sluggified together.
    dimensions, uncertainty_fields, plans = set(), set(), []
    fixed = {"obs_iri", "dataset_iri", "measure_iri", "value", "unit_iri", "year",
             "year_basis_iri", "standard_error", "cv", "lower", "upper",
             "estimate_type_iri", "method_iri", "review_status"}
    uncertainty_order = ("standard_error", "cv", "lower", "upper")
    for block in spec.observations:
        table_id = block["table"]
        if table_id not in tables or table_id not in frames:
            raise SpecError(f"observations: missing table/frame {table_id!r}")
        table, frame = tables[table_id], frames[table_id]
        columns = {column["name"]: column for column in table["columns"]}
        if len(columns) != len(table["columns"]) or not frame.columns.is_unique:
            raise SpecError(f"observations {table_id!r}: duplicate column names")
        for name in ("key", "dimensions", "measures"):
            values = block[name]
            if len(values) != len(set(values)) or (name != "dimensions" and not values):
                raise SpecError(f"observations {table_id!r}: invalid {name} columns")
        year_column = block.get("year_column")
        if (year_column not in block["dimensions"] or year_column not in columns
                or columns[year_column]["datatype"] != "integer"):
            raise SpecError(f"observations {table_id!r}: year_column must name an integer dimension")
        required = set(block["key"]) | set(block["dimensions"]) | set(block["measures"])
        measure_bindings = {}
        for measure_name in block["measures"]:
            if measure_name not in columns or columns[measure_name]["role"] != "measure":
                raise SpecError(f"observations {table_id!r}: invalid measure {measure_name!r}")
            column = columns[measure_name]
            if column["datatype"] not in ("number", "integer"):
                raise SpecError(f"observations {table_id}.{measure_name}: measure datatype must be numeric")
            bindings = {name: _obs_iri(column.get(name), f"{table_id}.{measure_name}.{name}")
                        for name in ("concept", "unit", "year_basis")}
            for name in ("method", "estimate_type"):
                bindings[name] = (_obs_iri(column[name], f"{table_id}.{measure_name}.{name}")
                                  if column.get(name) is not None else None)
            uncertainty = column.get("uncertainty", {})
            if set(uncertainty) - set(uncertainty_order):
                raise SpecError(f"observations {measure_name!r}: unknown uncertainty binding")
            for name, source in uncertainty.items():
                if source is not None:
                    if not isinstance(source, str) or not source:
                        raise SpecError(f"observations {measure_name!r}: invalid uncertainty column")
                    required.add(source)
                    uncertainty_fields.add(name)
            measure_bindings[measure_name] = bindings
        if not required <= columns.keys() or not required <= set(frame.columns):
            raise SpecError(f"observations {table_id!r}: referenced source columns are missing")
        for measure_name in block["measures"]:
            for source in columns[measure_name].get("uncertainty", {}).values():
                if source is not None and columns[source]["datatype"] not in ("number", "integer"):
                    raise SpecError(f"observations {table_id}.{source}: uncertainty datatype must be numeric")
        dim_bindings = {}
        for name in block["dimensions"]:
            if name == year_column:
                continue
            out_name = name + "_iri"
            if out_name in fixed:
                raise SpecError(f"observations {table_id!r}: dimension collides with {out_name!r}")
            identity, codes = identities.get((table_id, name)), columns[name].get("codes", {})
            if bool(identity) == bool(codes):
                raise SpecError(f"observations {table_id}.{name}: require exactly one identity or codes binding")
            dim_bindings[name] = (identity, codes)
            dimensions.add(out_name)
        plans.append((block, frame, columns, measure_bindings, dim_bindings))

    schema = pa.schema([
        pa.field("obs_iri", pa.string(), nullable=False),
        pa.field("dataset_iri", pa.string(), nullable=False),
        pa.field("measure_iri", pa.string(), nullable=False),
        pa.field("value", pa.float64(), nullable=False),
        pa.field("unit_iri", pa.string(), nullable=False),
        pa.field("year", pa.int32(), nullable=False),
        pa.field("year_basis_iri", pa.string(), nullable=False),
        *(pa.field(name, pa.string()) for name in sorted(dimensions)),
        *(pa.field(name, pa.float64()) for name in uncertainty_order if name in uncertainty_fields),
        pa.field("estimate_type_iri", pa.string()), pa.field("method_iri", pa.string()),
        pa.field("review_status", pa.string()),
    ])
    rows, observation_iris = [], set()
    dataset_iri = iri.dataset(spec.slug, spec.version)
    for block, frame, columns, measures, dim_bindings in plans:
        table_id, year_column = block["table"], block["year_column"]
        source_keys = set()
        # iterrows() can silently coerce integer keys to floats. itertuples()
        # preserves each source column's scalar values, including leading zeros.
        for values in frame.itertuples(index=False, name=None):
            source = dict(zip(frame.columns, values))
            year = _obs_integer(source[year_column], f"{table_id}.{year_column}")
            if not -(2 ** 31) <= year < 2 ** 31:
                raise SpecError(f"observations {table_id}.{year_column}: year is outside int32")
            keys = tuple(_obs_key(source[name], columns[name], f"{table_id}.{name}")
                         for name in block["key"])
            encoded_key = tuple(iri.segment(value) for value in keys)
            if encoded_key in source_keys:
                raise SpecError(f"observations {table_id!r}: duplicate source key {keys!r}")
            source_keys.add(encoded_key)
            dimension_values = {}
            for name, (identity, codes) in dim_bindings.items():
                value = _obs_scalar(source[name])
                if _obs_missing(value):
                    dimension_values[name + "_iri"] = None
                elif identity:
                    value = _obs_key(value, columns[name], f"{table_id}.{name}")
                    dimension_values[name + "_iri"] = iri.ident(
                        identity["kind"], identity["authority"], value)
                else:
                    value = _obs_key(value, columns[name], f"{table_id}.{name}")
                    iri.segment(value)  # Refuse bools/missing/empty rather than stringify them.
                    if str(value) not in codes:
                        raise SpecError(f"observations {table_id}.{name}: undeclared source code {value!r}")
                    dimension_values[name + "_iri"] = _source_code_iri(spec.slug, table_id, name, value)
            for name, bindings in measures.items():
                value = _obs_column_number(source[name], columns[name], f"{table_id}.{name}")
                if value is None:
                    continue
                observation_iri = iri.obs(spec.slug, spec.version, *keys, bindings["concept"])
                if observation_iri in observation_iris:
                    raise SpecError(f"observations: observation IRI collision {observation_iri!r}")
                observation_iris.add(observation_iri)
                row = {"obs_iri": observation_iri, "dataset_iri": dataset_iri,
                       "measure_iri": bindings["concept"], "value": value,
                       "unit_iri": bindings["unit"], "year": year,
                       "year_basis_iri": bindings["year_basis"], **dimension_values,
                       "estimate_type_iri": bindings["estimate_type"], "method_iri": bindings["method"]}
                dependencies = set(block["key"]) | set(block["dimensions"]) | {name}
                for field_name, column_name in columns[name].get("uncertainty", {}).items():
                    if column_name is not None:
                        number = _obs_column_number(source[column_name], columns[column_name], f"{table_id}.{column_name}")
                        if number is not None and field_name in ("standard_error", "cv") and number < 0:
                            raise SpecError(f"observations {table_id}.{column_name}: {field_name} must be non-negative")
                        row[field_name] = number
                        if number is not None:
                            dependencies.add(column_name)
                if row.get("lower") is not None and row.get("upper") is not None and row["lower"] > row["upper"]:
                    raise SpecError(f"observations {table_id}.{name}: lower bound exceeds upper bound")
                row["review_status"] = _obs_review_status(columns[column] for column in sorted(dependencies))
                rows.append(row)
    rows.sort(key=lambda row: row["obs_iri"])
    table = pa.Table.from_pylist(rows, schema=schema)
    buffer = pa.BufferOutputStream()
    pq.write_table(table, buffer, compression="zstd", version="2.6", write_statistics=True)
    det.write_bytes(path, buffer.getvalue().to_pybytes(), gzip=False)
    return len(rows)


def _source_code_iri(spec_slug: str, table_id: str, column_name: str, value: object) -> str:
    """Shared compiler/writer source-code identity; null mapping targets do not change it."""
    return iri.code(f"{spec_slug}/field-{iri.stable_key(table_id, column_name)}", value)


def _obs_scalar(value):
    item = getattr(value, "item", None)
    if callable(item) and type(value).__module__.split(".")[0] in ("numpy", "pandas"):
        return item()
    return value


def _obs_missing(value) -> bool:
    value = _obs_scalar(value)
    return (value is None or type(value).__name__ in ("NAType", "NaTType")
            or isinstance(value, str) and value == ""
            or isinstance(value, float) and math.isnan(value)
            or isinstance(value, Decimal) and value.is_nan())


def _obs_number(value, where: str) -> float | None:
    value = _obs_scalar(value)
    if _obs_missing(value):
        return None
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise SpecError(f"observations {where}: expected a numeric source value")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise SpecError(f"observations {where}: value cannot be represented as float64") from exc
    if not math.isfinite(number):
        raise SpecError(f"observations {where}: non-finite numeric value")
    if isinstance(value, Integral) and int(number) != value:
        raise SpecError(f"observations {where}: integer loses precision in float64")
    if isinstance(value, Decimal) and Decimal(str(number)) != value:
        raise SpecError(f"observations {where}: decimal loses precision in float64")
    return number


def _obs_column_number(value, column, where: str) -> float | None:
    if not _obs_missing(value) and column["datatype"] == "integer":
        value = _obs_integer(value, where)
    return _obs_number(value, where)


def _obs_integer(value, where: str) -> int:
    value = _obs_scalar(value)
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    if (_obs_missing(value) or isinstance(value, bool)
            or not isinstance(value, (Real, Decimal)) or not math.isfinite(value)
            or value != int(value)):
        raise SpecError(f"observations {where}: expected an exact integral value")
    return int(value)


def _obs_key(value, column, where: str):
    value = _obs_scalar(value)
    if _obs_missing(value) or isinstance(value, bool):
        raise SpecError(f"observations {where}: missing or invalid source key")
    if column["datatype"] == "integer":
        return _obs_integer(value, where)
    if not isinstance(value, (str, Real, Decimal, _dt.date)):
        raise SpecError(f"observations {where}: source key must be scalar")
    if isinstance(value, (Real, Decimal)) and not math.isfinite(value):
        raise SpecError(f"observations {where}: non-finite source key")
    return value


def _obs_iri(value, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise SpecError(f"observations {where}: explicit IRI binding required")
    result = expand(value)
    if result is None or not result.startswith(("https://", "http://", "urn:")):
        raise SpecError(f"observations {where}: unknown prefix or non-absolute IRI")
    try:
        N(result)
    except ValueError as exc:
        raise SpecError(f"observations {where}: invalid IRI") from exc
    if value.startswith("def:") or any(result.startswith(ns) for ns in config.current().legacy_ns.values()):
        raise SpecError(f"observations {where}: legacy def: vocabulary is forbidden")
    return result


def _obs_review_status(columns) -> str | None:
    statuses = []
    for column in columns:
        if "mark" not in column:
            continue
        mark = column["mark"]
        if (not isinstance(mark, Mapping) or not isinstance(mark.get("evidence"), (list, tuple))
                or not mark["evidence"]
                or not all(isinstance(item, str) and item.strip() for item in mark["evidence"])):
            raise SpecError("observations: explicit marks require evidence")
        statuses.append(provenance.review_status(mark["confidence"], provenance.criticality_of(mark["aspect"])))
    return "awaitingReview" if "awaitingReview" in statuses else "agentAccepted" if statuses else None
