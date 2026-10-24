"""Declarative dataset specifications: ``specs/<slug>.yaml`` (ADR-0001 D11).

A spec says everything the shared executor needs to turn a source into a
Salmon Data Package, dataset graphs and Parquet, so that agents write and
justify YAML and the executor, not the agent, writes the RDF. The YAML keys
below are the contract between this module and ``executor.py``; this module
owns parsing, defaults and validation.

File location: ``specs/<slug>.yaml`` at the repository root (one file per
dataset; ``slug`` is a kebab name, never ``corpus`` or ``vocab``).

YAML shape (``spec_version: 1``; every IRI may be a CURIE with a
``config.STATIC_NS`` prefix or ``corp:``)::

    spec_version: 1
    slug: psc-fraser-sr
    version: "2026.05.07"            # the source's version; part of every IRI
    title: "..."
    description: "..."
    source:
      publisher: "Pacific Salmon Commission"
      landing_page: https://...
      doi: 10.xxxx/yyyy                # optional
      licence: https://creativecommons.org/licenses/by/4.0/  # null only with unconfirmed redistribution
      redistribution: confirmed        # or "unconfirmed": never in a public release (D2)
      attribution: "..."
      files:
        - {name: sr_summary.csv, url: https://..., sha256: <hex>}
    parser: csv                        # csv | xlsx | "module:function" for bespoke parsing (D11)
    tables:
      - id: sr_summary
        file: sr_summary.csv
        # sheet: "Raw data"            # required only for parser: xlsx
        keys: [production_stock_code, brood_year]
        columns:
          - name: total_broodyr_EFS
            role: measure              # identifier | dimension | measure | attribute
            label: "..."
            description: "..."         # from the source; "[agent] ..." when written by the agent
            datatype: number
            concept: psc:PSC-CV-000035 # compound variable: PSC, gcdfo or corp: profile concept
            decomposition:             # I-ADOPT, only when the concept is a corp: profile concept
              property: smn:Abundance
              object_of_interest: smn:Stock
              constraints: [smn:BroodYearBasis, corp:constraint/female]   # atomic parts only
              statistical_modifier: null
            unit: unit:NUM
            year_basis: smn:broodYear  # or smn:returnYear
            age_notation: null         # smn:GilbertRichAgeNotation | smn:EuropeanAgeNotation
            estimate_type: null        # gcdfo concept, when the source states one
            method: null               # gcdfo method concept (ADR-0001 D13)
            uncertainty: {standard_error: null, cv: null, lower: null, upper: null}  # column names
            codes: {}                  # source code value -> vocabulary IRI (or null = gap)
            mark:                      # present when the semantics are agent-derived (D6)
              aspect: measure-counts   # provenance.CRITICAL_ASPECTS / NON_CRITICAL_ASPECTS
              confidence: high
              evidence: ["PSC SR documentation p. 4: ...", https://...]
    identity:
      - {table: sr_summary, column: production_stock_code, kind: stock, authority: psc-frsk,
         label_column: stock_name, species: Sockeye}
    observations:
      - table: sr_summary
        key: [production_stock_code, brood_year]   # + the measure, added by the executor
        dimensions: [production_stock_code, brood_year]
        year_column: brood_year          # explicit integer source year; no name guessing
        measures: [total_broodyr_EFS]
    cross_source_checks:
      - id: efs-vs-sasap-total
        other: sasap-sockeye-brood
        join: stock                     # via the crosswalk graph
        measure: total_broodyr_EFS
        other_measure: TotalEscapement
        tolerance: 0.005
        expect: "SASAP TotalEscapement equals PSC EFS for 18 Fraser stocks"
    term_requests:                      # atomic gaps only (smn ADR-0002 decision 6)
      - {profile_concept: corp:constraint/female, says: "...", mint_in: smn, columns: [...]}

``load_spec`` checks the local JSON schema and expands IRI slots, leaving
descriptions, evidence and source identifiers unchanged. It does not import a
bespoke parser, fetch source files, load vocabularies or decide review status.
Optional marks describe explicit agent assertions; their absence never creates
an agent, human decision or claim of review. A compound profile definition is
a proposed decomposition, not scientific approval of the concept.

Rules ``validate_spec`` enforces (each failure is a message, not an exception):
every vocabulary IRI is declared at its pin (``VocabIndex.check``); no
compound variable is given an smn or gcdfo IRI it does not have; every
measure has a unit and a year basis; every age-class column has an age
notation; ``redistribution`` is present; each ``mark`` has a known aspect, a
confidence and at least one evidence item; no ``def:`` IRI anywhere.
The age-name screen exempts only a whole lexical metadata-only spec: no
observations, identities, semantic bindings/codes or marks, and every column
an unmarked string attribute. This admits source descriptions, not age values
or age interpretations.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator

from . import config, provenance
from .config import ROOT

if TYPE_CHECKING:  # pragma: no cover
    from .vocab import VocabIndex

__all__ = ["SPEC_VERSION", "SPECS_DIR", "SpecError", "DatasetSpec", "spec_path", "load_spec",
           "validate_spec", "spec_sha256"]

SPEC_VERSION = 1
#: ``specs/`` at the repository root.
SPECS_DIR = ROOT / "specs"
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PARSER = re.compile(r"^(csv|xlsx|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*)$")
_BAD_IRI = re.compile(r'[\s<>"{}|\\^`]')
_IRI_KEYS = frozenset({"licence", "concept", "unit", "year_basis", "age_notation",
                       "estimate_type", "method", "property", "object_of_interest",
                       "statistical_modifier", "profile_concept"})


class SpecError(ValueError):
    """A spec cannot be parsed into a :class:`DatasetSpec` (malformed YAML or missing keys)."""


@dataclass(frozen=True)
class DatasetSpec:
    """A parsed spec. Field names follow the YAML keys in the module docstring.

    ``source``, ``tables``, ``identity``, ``observations``,
    ``cross_source_checks`` and ``term_requests`` stay plain mappings/lists in
    this first contract; the spec engineer may replace them with typed
    dataclasses as long as the YAML keys do not change.
    """

    spec_version: int
    slug: str
    version: str
    title: str
    description: str
    source: Mapping[str, Any]
    parser: str
    tables: tuple[Mapping[str, Any], ...]
    identity: tuple[Mapping[str, Any], ...] = ()
    observations: tuple[Mapping[str, Any], ...] = ()
    cross_source_checks: tuple[Mapping[str, Any], ...] = ()
    term_requests: tuple[Mapping[str, Any], ...] = ()
    path: Path | None = field(default=None, compare=False)
    _file_sha256: str | None = field(default=None, compare=False, repr=False)

    @property
    def public(self) -> bool:
        """True only when ``source.redistribution == "confirmed"`` (ADR-0001 D2)."""
        return self.source.get("redistribution") == "confirmed"


def spec_path(slug: str) -> Path:
    """``specs/<slug>.yaml`` for a dataset slug."""
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug) or slug in config.RESERVED_SLUGS:
        raise SpecError("slug must be a lower-case kebab name other than 'corpus' or 'vocab'")
    return SPECS_DIR / f"{slug}.yaml"


class _Loader(yaml.SafeLoader):
    """Safe YAML with no duplicate keys, aliases or implicit date objects."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise SpecError("YAML aliases are unsupported; write each value explicitly")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise SpecError("YAML mapping keys must be strings (quote numeric source codes)")
            if key in result:
                raise SpecError(f"duplicate YAML key {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


# A source date is text in this contract. Do not mutate SafeLoader globally.
_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in values if tag != "tag:yaml.org,2002:timestamp"]
    for k, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(Path(__file__).with_name("spec.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _where(parts) -> str:
    return "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in parts)


def _schema_errors(data: Any) -> list[str]:
    return sorted(f"{_where(e.absolute_path)}: {e.message}" for e in _validator().iter_errors(data))


def _expand(value: str, path: str) -> str:
    if value.startswith(("http://", "https://", "urn:")):
        if _BAD_IRI.search(value):
            raise SpecError(f"{path}: unsafe IRI {value!r}")
        if value.startswith(("http://", "https://")):
            try:
                if not urlsplit(value).hostname:
                    raise ValueError("missing host")
            except ValueError as exc:
                raise SpecError(f"{path}: malformed absolute IRI {value!r}") from exc
        elif not re.fullmatch(r"urn:[A-Za-z0-9][A-Za-z0-9-]*:.+", value):
            raise SpecError(f"{path}: malformed absolute URN {value!r}")
        return value
    prefix, sep, local = value.partition(":")
    if not sep or not local or prefix not in config.current().prefixes:
        raise SpecError(f"{path}: unknown IRI prefix or non-absolute IRI {value!r}")
    if _BAD_IRI.search(value):
        raise SpecError(f"{path}: unsafe IRI {value!r}")
    return config.current().prefixes[prefix] + local


def _normalise(data: dict) -> dict:
    """Expand only contracted IRI slots; never rewrite quoted evidence/code keys."""
    def walk(value, path="$", key=""):
        if key == "codes":
            return value
        if isinstance(value, dict):
            return {k: walk(v, f"{path}.{k}", k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, f"{path}[{i}]", "constraint" if key == "constraints" else "")
                    for i, v in enumerate(value)]
        if isinstance(value, str) and (key in _IRI_KEYS or key == "constraint"):
            return _expand(value, path)
        if isinstance(value, str) and key == "species" and value.partition(":")[0] in config.current().prefixes:
            return _expand(value, path)
        return value

    # codes is a mapping from exact source values to IRI-or-null, not field names.
    for table in data["tables"]:
        for column in table["columns"]:
            if "codes" in column:
                column["codes"] = {k: _expand(v, f"codes[{k!r}]") if v is not None else None
                                   for k, v in column["codes"].items()}
    data = walk(data)
    data.setdefault("parser", "csv")
    for key in ("identity", "observations", "cross_source_checks", "term_requests"):
        data.setdefault(key, [])
    for table in data["tables"]:
        for column in table["columns"]:
            column.setdefault("codes", {})
    return data


def load_spec(path_or_slug: str | Path) -> DatasetSpec:
    """Parse ``specs/<slug>.yaml`` (or a path) into a :class:`DatasetSpec`.

    Expands CURIEs with ``config.current().prefixes``; applies defaults;
    raises :class:`SpecError` on malformed input. Does not check vocabulary
    IRIs (that is :func:`validate_spec`).
    """
    if not isinstance(path_or_slug, (str, Path)) or not str(path_or_slug) or "\0" in str(path_or_slug):
        raise SpecError("expected a dataset slug or a YAML path")
    text = str(path_or_slug)
    path = (spec_path(text) if isinstance(path_or_slug, str) and _SLUG.fullmatch(text)
            and Path(text).suffix not in (".yaml", ".yml")
            else Path(path_or_slug))
    if path.suffix not in (".yaml", ".yml"):
        raise SpecError("a spec path must end in .yaml or .yml")
    try:
        raw = path.read_bytes()
        data = yaml.load(raw.decode("utf-8"), Loader=_Loader)
    except (OSError, UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise SpecError(f"cannot read YAML spec {path.name}: {exc}") from exc
    errors = _schema_errors(data)
    if errors:
        raise SpecError("invalid spec structure:\n" + "\n".join(errors))
    data = _normalise(data)
    return DatasetSpec(**{**data, **{k: tuple(data[k]) for k in
                         ("tables", "identity", "observations", "cross_source_checks", "term_requests")}},
                       path=path.resolve(), _file_sha256=hashlib.sha256(raw).hexdigest())


def _document(spec: DatasetSpec) -> dict:
    return {k: copy.deepcopy(getattr(spec, k)) if k not in
            ("tables", "identity", "observations", "cross_source_checks", "term_requests") else
            list(copy.deepcopy(getattr(spec, k))) for k in
            ("spec_version", "slug", "version", "title", "description", "source", "parser",
             "tables", "identity", "observations", "cross_source_checks", "term_requests")}


def _leaves(value, path="$", key=""):
    if isinstance(value, Mapping):
        for k, v in value.items():
            yield from _leaves(v, f"{path}.{k}", k)
    elif isinstance(value, (tuple, list)):
        for i, v in enumerate(value):
            yield from _leaves(v, f"{path}[{i}]", key)
    else:
        yield path, key, value


def _semantic_iris(data: Mapping[str, Any]) -> set[str]:
    """Term assertions only: cited URLs and quoted prose are evidence, not terms."""
    values = []
    for table in data["tables"]:
        for column in table["columns"]:
            values.extend(column.get(k) for k in ("concept", "unit", "year_basis", "age_notation",
                                                  "estimate_type", "method"))
            values.extend(column["codes"].values())
            decomposition = column.get("decomposition", {})
            values.extend(decomposition.get(k) for k in ("property", "object_of_interest", "statistical_modifier"))
            values.extend(decomposition.get("constraints", []))
    values.extend(request["profile_concept"] for request in data["term_requests"])
    values.extend(identity.get("species") for identity in data["identity"])
    return {v for v in values if isinstance(v, str) and not _BAD_IRI.search(v)
            and v.startswith(("http://", "https://", "urn:"))}


def _column_requires_critical_mark(column: Mapping[str, Any], *, referenced_year: bool = False) -> bool:
    """Whether the single column mark would govern a semantic interpretation.

    This does not make an assertion critical or strengthen its evidence. An
    explicitly noncritical mark in such a slot must instead be refused. Pure
    descriptive columns can still carry label/description marks.
    """
    semantic_fields = ("concept", "unit", "year_basis", "age_notation", "estimate_type", "method", "decomposition")
    return (referenced_year or column.get("role") == "measure" or bool(column.get("codes"))
            or any(column.get(name) is not None for name in semantic_fields))


def _is_lexical_metadata_only(data: Mapping[str, Any]) -> bool:
    """Recognize the whole-spec source-inventory boundary, without assigning semantics."""
    return (not data["observations"] and not data["identity"]
            and all(column["role"] == "attribute" and column["datatype"] == "string"
                    and "mark" not in column and not _column_requires_critical_mark(column)
                    for table in data["tables"] for column in table["columns"]))


def validate_spec(spec: DatasetSpec, vocab: "VocabIndex") -> list[str]:
    """Problems with ``spec``, one message each, sorted; empty means valid.

    See the module docstring for the rules. The executor refuses to build a
    spec with problems.
    """
    data = _document(spec)
    errors = _schema_errors(data)
    if errors:
        return errors
    try:
        data = _normalise(data)
    except SpecError as exc:
        return [str(exc)]
    # This also covers DatasetSpec objects constructed directly by callers.
    source, spec_tables = data["source"], data["tables"]
    lexical_metadata_only = _is_lexical_metadata_only(data)
    year_columns = {(block["table"], block["year_column"]) for block in data["observations"]}
    legacy = {config.current().legacy_ns["def"], config.DEFAULT_BASE + "def/"}
    for path, key, value in _leaves(data):
        if isinstance(value, float) and not math.isfinite(value):
            errors.append(f"{path}: must be a finite number")
        if isinstance(value, str):
            if not value.strip():
                errors.append(f"{path}: must not be blank")
            if value.startswith("def:") or any(value.startswith(ns) for ns in legacy):
                errors.append(f"{path}: legacy def: IRIs are forbidden")
    errors.extend(f"undeclared vocabulary IRI at loaded pin: {i}" for i in vocab.check(_semantic_iris(data)))
    # The canonical shape has no explicit vocabulary pins: the executor records
    # the supplied VocabIndex pins in its manifest, along with spec_sha256().
    if not _PARSER.fullmatch(spec.parser):
        errors.append("$.parser: expected csv, xlsx or module:function (no executable syntax)")
    names = [f["name"] for f in source["files"]]
    if len(names) != len(set(names)):
        errors.append("$.source.files: duplicate file names")
    tables = {}
    for ti, table in enumerate(spec_tables):
        p = f"$.tables[{ti}]"
        if table["id"] in tables:
            errors.append(f"{p}.id: duplicate table id {table['id']!r}")
        tables[table["id"]] = table
        if table["file"] not in names:
            errors.append(f"{p}.file: not present in source.files")
        columns = {c["name"]: c for c in table["columns"]}
        if len(columns) != len(table["columns"]):
            errors.append(f"{p}.columns: duplicate column names")
        for key in table.get("keys", []):
            if key not in columns:
                errors.append(f"{p}.keys: unknown column {key!r}")
        for ci, column in enumerate(table["columns"]):
            cp = f"{p}.columns[{ci}]"
            if column["role"] == "measure":
                if column["datatype"] not in ("integer", "number"):
                    errors.append(f"{cp}.datatype: a measure must be numeric")
                for required in ("concept", "unit", "year_basis"):
                    if not column.get(required):
                        errors.append(f"{cp}.{required}: required for a measure")
                if column.get("year_basis") and column["year_basis"] not in {
                        config.SMN_NS + "broodYear", config.SMN_NS + "returnYear"}:
                    errors.append(f"{cp}.year_basis: expected smn:broodYear or smn:returnYear")
            # Age-class semantics must be explicit. This lexical screen catches
            # common source names; validate_spec cannot infer biology from data.
            if (not lexical_metadata_only
                    and re.search(r"(^|[_ -])age([_ -]|[0-9]|$)|ageclass", column["name"], re.I)
                    and not column.get("age_notation")):
                errors.append(f"{cp}.age_notation: required for an age-class column")
            decomp = column.get("decomposition")
            if decomp is not None and not column.get("concept", "").startswith(config.current().profile_base):
                errors.append(f"{cp}.decomposition: only a corp: profile concept may define a decomposition")
            if column["role"] == "measure" and column.get("concept", "").startswith(config.current().profile_base) and decomp is None:
                errors.append(f"{cp}.decomposition: required for a compound corp: measure concept")
            for field, ref in (column.get("uncertainty") or {}).items():
                if ref is not None and ref not in columns:
                    errors.append(f"{cp}.uncertainty.{field}: unknown column {ref!r}")
                elif ref is not None and columns[ref]["datatype"] not in ("integer", "number"):
                    errors.append(f"{cp}.uncertainty.{field}: referenced column must be numeric")
            mark = column.get("mark")
            if (mark and _column_requires_critical_mark(column, referenced_year=(table["id"], column["name"]) in year_columns)
                    and mark["aspect"] in provenance.NON_CRITICAL_ASPECTS):
                errors.append(f"{cp}.mark.aspect: a mark governing column semantics or year basis must be critical")
    for kind in ("identity", "observations"):
        for i, block in enumerate(data[kind]):
            p = f"$.{kind}[{i}]"
            table = tables.get(block["table"])
            if table is None:
                errors.append(f"{p}.table: unknown table {block['table']!r}")
                continue
            columns = {c["name"]: c for c in table["columns"]}
            if kind == "identity":
                refs = [block["column"]] + ([block["label_column"]] if block.get("label_column") else [])
            else:
                refs = block["key"] + block["dimensions"] + block["measures"] + [block["year_column"]]
                year = block["year_column"]
                if year not in block["dimensions"]:
                    errors.append(f"{p}.year_column: must occur in this block's dimensions")
                if year in columns and columns[year]["datatype"] != "integer":
                    errors.append(f"{p}.year_column: initial writer requires an integer year column")
                for m in block["measures"]:
                    if m in columns and columns[m]["role"] != "measure":
                        errors.append(f"{p}.measures: {m!r} is not a measure column")
                for dimension in block["dimensions"]:
                    if dimension == year or dimension not in columns:
                        continue
                    identity = [i for i in data["identity"] if i["table"] == block["table"]
                                and i["column"] == dimension]
                    codes = columns[dimension]["codes"]
                    if len(identity) > 1 or (identity and codes):
                        errors.append(f"{p}.dimensions: ambiguous identity/code mapping for {dimension!r}")
                    elif not identity and not codes:
                        errors.append(f"{p}.dimensions: {dimension!r} requires an explicit identity or code mapping")
            for ref in sorted(set(refs)):
                if ref not in columns:
                    errors.append(f"{p}: unknown column {ref!r}")
    for i, check in enumerate(spec.cross_source_checks):
        if not any(check["measure"] == c["name"] and c["role"] == "measure"
                   for t in spec_tables for c in t["columns"]):
            errors.append(f"$.cross_source_checks[{i}].measure: unknown measure {check['measure']!r}")
    all_columns = {c["name"] for t in spec_tables for c in t["columns"]}
    for i, request in enumerate(data["term_requests"]):
        p = f"$.term_requests[{i}]"
        if not request["profile_concept"].startswith(config.current().profile_base):
            errors.append(f"{p}.profile_concept: must be a corp: profile concept (atomic request, not a vocabulary mint)")
        for column in request["columns"]:
            if column not in all_columns:
                errors.append(f"{p}.columns: unknown column {column!r}")
    for path, key, value in _leaves(data):
        if key == "aspect" and value not in provenance.CRITICAL_ASPECTS | provenance.NON_CRITICAL_ASPECTS:
            errors.append(f"{path}: unknown provenance aspect {value!r}")
    return sorted(set(errors))


def spec_sha256(spec: DatasetSpec) -> str:
    """sha256 of the spec file's bytes, for the build manifest and provenance."""
    if spec.path is None:
        raise SpecError("spec has no source path; load a saved YAML spec before building")
    try:
        digest = hashlib.sha256(spec.path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SpecError(f"cannot hash spec {spec.path.name}: {exc}") from exc
    if spec._file_sha256 is not None and digest != spec._file_sha256:
        raise SpecError("spec file changed since load; reload it before building")
    return digest
