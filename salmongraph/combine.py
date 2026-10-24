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
from collections import Counter
import csv
import datetime as _dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
from itertools import chain
from typing import TYPE_CHECKING, Sequence

import pyoxigraph as ox

from . import config, iri, provenance, review
from ._stub import not_yet
from .config import ROOT
from .graph import L, N

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
    iri.corpus_graph("catalog", corpus_version)
    return CORPUS_BUILD_DIR / iri.segment(corpus_version)


def load_dataset_build(store: "ox.Store", build_dir: Path) -> dict:
    """Verify ``build_dir/manifest.json`` and load ``dataset.trig`` into ``store``.

    Only the current ``salmongraph-build/1`` format is understood. Exact
    inventories, bytes, graph identity/counts and bounded report/Parquet/queue
    consistency are checked before one transactional ``Store.extend``. Blank
    nodes are scoped deterministically to the dataset release, so repeated
    loads are idempotent and unrelated releases cannot share blank identities.
    Reified statements remain reified. No review, science, licence or public
    release approval is inferred, and the caller's configuration is untouched.
    Combined pending/live containment supports the recorded profile namespace;
    foreign current-format review-status namespaces are refused explicitly.
    """
    if not isinstance(store, ox.Store):
        raise ValueError("combine: caller must supply a pyoxigraph Store")
    root = _build_root(build_dir)
    before, directories, captured, identities = _snapshot(root, capture=True)
    manifest = _json(captured.get("manifest.json", b""), "manifest")
    cfg, graphs = _manifest(manifest)
    _inventory(manifest, before, directories)
    staged = ox.Store()
    try:
        parsed = ox.parse(input=captured["dataset.trig"], format=ox.RdfFormat.TRIG,
                          rename_blank_nodes=False)
        staged.extend(_scoped_quad(q, manifest["dataset_iri"]) for q in parsed)
    except (ValueError, SyntaxError, OSError) as exc:
        raise ValueError("combine: dataset.trig could not be parsed as a complete TriG dataset") from exc
    _dataset(staged, manifest, cfg, graphs)
    _sidecars(captured, staged, manifest, cfg)
    _caller_graphs(store, staged, graphs)
    _pending_union(store, staged, cfg)
    # All interpretation used the captured, hash-verified bytes. Detect an
    # input replacement/edit (including manifest or directory changes) before
    # the caller transaction. No parsing/import/execution follows this check.
    after, after_dirs, _, after_ids = _snapshot(root, capture=False)
    if before != after or directories != after_dirs or identities != after_ids:
        raise ValueError("combine: dataset build changed during verification")
    store.extend(staged)
    return manifest


_FORMAT = "salmongraph-build/1"
_SELF_EXCLUSION = "excluded: manifest.json cannot hash itself"
_ROOT_FILES = frozenset({"dataset.trig", "observations.parquet", "report.json", "report.md", "review-queue.csv"})
_CAPTURE = _ROOT_FILES | {"manifest.json"}
_MANIFEST_FIELDS = frozenset({"schema", "slug", "version", "build_date", "dataset_iri", "configuration",
    "manifest_hash", "spec", "sources", "parser", "vocabularies", "tools", "sdp_schema", "review_decisions",
    "quad_counts", "observations", "review_counts", "validation", "publication_ready", "publication_gaps", "files"})


def _build_root(value):
    root = Path(value).absolute()
    if ".." in root.parts or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("combine: build path must not traverse parents or symlinks")
    if not root.is_dir():
        raise ValueError("combine: dataset build must be an existing directory")
    return root


def _identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _snapshot(root, *, capture):
    """Read through directory descriptors, never follow a symlink or FIFO.

    Descriptors anchor each traversal even if a path is swapped concurrently;
    fstat before/after detects edits. The final snapshot checks replacements as
    well as byte changes. Source trees are not locked or modified.
    """
    records, directories, payloads, identities = {}, set(), {}, {}
    flags = os.O_RDONLY | os.O_NOFOLLOW

    def walk(fd, prefix=""):
        for name in sorted(os.listdir(fd)):
            relative = prefix + name
            entry = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(entry.st_mode):
                child = os.open(name, flags | os.O_DIRECTORY, dir_fd=fd)
                try:
                    if _identity(os.fstat(child)) != _identity(entry):
                        raise ValueError("combine: dataset directory changed during verification")
                    directories.add(relative)
                    identities[relative + "/"] = _identity(entry)
                    walk(child, relative + "/")
                finally:
                    os.close(child)
            elif stat.S_ISREG(entry.st_mode):
                child = os.open(name, flags | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(child, "rb") as stream:
                    first = os.fstat(stream.fileno())
                    if not stat.S_ISREG(first.st_mode) or _identity(first) != _identity(entry):
                        raise ValueError("combine: dataset file changed during verification")
                    digest, chunks = hashlib.sha256(), []
                    keep = capture and relative in _CAPTURE
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        if keep:
                            chunks.append(chunk)
                    if _identity(os.fstat(stream.fileno())) != _identity(first):
                        raise ValueError("combine: dataset file changed during verification")
                records[relative] = {"path": relative, "bytes": first.st_size, "sha256": digest.hexdigest()}
                identities[relative] = _identity(first)
                if keep:
                    payloads[relative] = b"".join(chunks)
            else:
                raise ValueError("combine: symlink or special entry in dataset build")

    def open_root():
        # O_NOFOLLOW on the final component alone would still follow a
        # concurrently replaced ancestor. Anchor the entire absolute chain.
        fd = os.open(root.anchor, flags | os.O_DIRECTORY)
        try:
            for part in root.parts[1:]:
                child = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    try:
        fd = open_root()
        try:
            identities["/"] = _identity(os.fstat(fd))
            walk(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise ValueError("combine: cannot safely read dataset build") from exc
    return records, directories, payloads, identities


def _json(payload, kind):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("non-finite JSON constant")
    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError(f"combine: invalid {kind} JSON") from exc


def _manifest(manifest):
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_FIELDS or manifest.get("schema") != _FORMAT:
        raise ValueError("combine: unrecognized dataset build manifest; no legacy adapter is assumed")
    if manifest["manifest_hash"] != _SELF_EXCLUSION:
        raise ValueError("combine: manifest self-exclusion is not declared honestly")
    if not all(isinstance(manifest[k], str) and manifest[k] for k in ("slug", "version", "build_date", "dataset_iri")):
        raise ValueError("combine: invalid manifest dataset identity")
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", manifest["build_date"]):
            raise ValueError("invalid date")
        _dt.date.fromisoformat(manifest["build_date"])
        if not isinstance(manifest["configuration"], dict) or set(manifest["configuration"]) != {"base", "profile_base", "sdpv"}:
            raise ValueError("invalid configuration")
        if not all(isinstance(v, str) and v for v in manifest["configuration"].values()):
            raise ValueError("invalid configuration values")
        cfg = config.Config(**manifest["configuration"])
        expected = iri.dataset(manifest["slug"], manifest["version"], cfg=cfg)
        graphs = iri.dataset_graphs(manifest["slug"], manifest["version"], cfg=cfg)
    except ValueError as exc:
        raise ValueError("combine: invalid manifest namespace/dataset configuration") from exc
    if manifest["dataset_iri"] != expected:
        raise ValueError("combine: manifest dataset IRI disagrees with recorded configuration")
    counts = manifest["quad_counts"]
    if (not isinstance(counts, dict) or not counts or not set(counts) <= set(graphs.values())
            or not all(type(n) is int and n > 0 for n in counts.values())):
        raise ValueError("combine: invalid named-graph count inventory")
    if type(manifest["observations"]) is not int or manifest["observations"] < 0:
        raise ValueError("combine: invalid observation count")
    if manifest["publication_ready"] is not False:
        raise ValueError("combine: current private build format cannot certify publication readiness")
    for key in ("spec", "parser", "vocabularies", "tools", "sdp_schema", "review_decisions", "review_counts", "validation"):
        if not isinstance(manifest[key], dict):
            raise ValueError(f"combine: malformed manifest {key}")
    if any(k not in provenance.REVIEW_STATUSES or type(v) is not int or v <= 0 for k, v in manifest["review_counts"].items()):
        raise ValueError("combine: invalid review count inventory")
    if not isinstance(manifest["sources"], list) or not isinstance(manifest["publication_gaps"], list):
        raise ValueError("combine: malformed manifest source/gap inventory")
    return cfg, graphs


def _inventory(manifest, actual, directories):
    declared = manifest["files"]
    if not isinstance(declared, list) or not declared:
        raise ValueError("combine: missing file inventory")
    records = {}
    for item in declared:
        if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
            raise ValueError("combine: malformed file inventory")
        name = item["path"]
        if (not isinstance(name, str) or not name or name.startswith("/") or "\\" in name
                or any(part in ("", ".", "..") for part in name.split("/")) or ":" in name or "\0" in name):
            raise ValueError("combine: unsafe inventory path")
        if name == "manifest.json" or name in records:
            raise ValueError("combine: manifest must exclude itself and contain unique paths")
        if name not in _ROOT_FILES and not name.startswith("sdp/"):
            raise ValueError("combine: unrecognized root artifact")
        if type(item["bytes"]) is not int or item["bytes"] < 0 or not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("combine: invalid file size/hash")
        records[name] = item
    required = _ROOT_FILES | {"sdp/.sdp-package", "sdp/datapackage.json", "sdp/metadata/dataset.csv", "sdp/metadata/tables.csv", "sdp/metadata/column_dictionary.csv"}
    if not required <= set(records) or "manifest.json" not in actual:
        raise ValueError("combine: current dataset build artifacts are missing")
    expected_dirs = {parent.as_posix() for name in records for parent in Path(name).parents if parent != Path(".")}
    if {k: v for k, v in actual.items() if k != "manifest.json"} != records or directories != expected_dirs:
        raise ValueError("combine: file bytes/hash/set or directory inventory disagrees with manifest")


def _scoped_quad(q, dataset):
    if not isinstance(q.graph_name, ox.NamedNode):
        raise ValueError("combine: dataset must contain only IRI-named graphs")
    def term(value):
        if isinstance(value, ox.BlankNode):
            digest = hashlib.sha256((dataset + "\x1f" + value.value).encode()).hexdigest()
            return ox.BlankNode("b" + digest[:32])
        if isinstance(value, ox.Triple):
            return ox.Triple(term(value.subject), value.predicate, term(value.object))
        return value
    return ox.Quad(term(q.subject), q.predicate, term(q.object), q.graph_name)


def _dataset(staged, manifest, cfg, graphs):
    counts = Counter(q.graph_name.value for q in staged)
    if dict(counts) != manifest["quad_counts"]:
        raise ValueError("combine: actual RDF named graphs/counts disagree with manifest")
    dataset = ox.NamedNode(manifest["dataset_iri"])
    metadata = ox.NamedNode(graphs["metadata"])
    declared = {q.subject for q in staged if q.predicate == N("rdf:type") and q.object == N("dcat:Dataset")}
    if declared != {dataset} or ox.Quad(dataset, N("rdf:type"), N("dcat:Dataset"), metadata) not in staged:
        raise ValueError("combine: RDF dataset identity disagrees with manifest")
    for predicate, obj in (("pav:version", L(manifest["version"])), ("dcterms:created", L(manifest["build_date"], "xsd:date"))):
        values = {q.object for q in staged if q.subject == dataset and q.predicate == N(predicate)}
        if values != {obj}:
            raise ValueError("combine: RDF dataset version/build date disagrees with manifest")
    terms = provenance.terms(cfg)
    by_target = {}
    for q in staged:
        if q.predicate.value == terms.review_status:
            if not isinstance(q.subject, ox.NamedNode):
                raise ValueError("combine: current-format review targets must be IRIs")
            by_target.setdefault(q.subject, set()).add(q.object)
    tokens = {value: key for key, value in terms.values.items() if key in provenance.REVIEW_STATUSES}
    actual = Counter()
    for values in by_target.values():
        if len(values) != 1 or not all(isinstance(v, ox.NamedNode) and v.value in tokens for v in values):
            raise ValueError("combine: invalid/conflicting recorded review status")
        actual[tokens[next(iter(values)).value]] += 1
    if dict(actual) != manifest["review_counts"]:
        raise ValueError("combine: RDF review counts disagree with manifest")


def _sidecars(captured, staged, manifest, cfg):
    import pyarrow as pa
    import pyarrow.parquet as pq
    report = _json(captured["report.json"], "report")
    pairs = {"slug": "slug", "version": "version", "observations": "observations", "quad_counts": "quad_counts",
             "review_counts": "review_counts", "checks": "validation", "publication_ready": "publication_ready", "publication_gaps": "publication_gaps"}
    if (not isinstance(report, dict) or any(report.get(k) != manifest[v] for k, v in pairs.items())
            or type(report.get("observations")) is not int or type(report.get("quads")) is not int
            or report.get("quads") != len(staged)):
        raise ValueError("combine: report disagrees with manifest/RDF")
    try:
        parquet = pq.ParquetFile(pa.BufferReader(captured["observations.parquet"]))
        required = _parquet_schema(parquet.schema_arrow, pa)
        fixed = parquet.read(columns=list(required))
        if any(fixed[name].null_count for name, field in required.items() if not field.nullable):
            raise ValueError("combine: required observation fields contain null values")
        rows = fixed.select(["obs_iri", "dataset_iri"]).to_pylist()
    except (ValueError, OSError, pa.ArrowException) as exc:
        raise ValueError("combine: invalid observation Parquet") from exc
    if parquet.metadata.num_rows != manifest["observations"] or not {"obs_iri", "dataset_iri"} <= set(parquet.schema_arrow.names):
        raise ValueError("combine: Parquet observation schema/count disagrees with manifest")
    if any(not isinstance(r.get("obs_iri"), str) or not isinstance(r.get("dataset_iri"), str) for r in rows):
        raise ValueError("combine: observation identity columns must contain actual IRI strings")
    observations = {q.subject.value for q in staged if q.predicate == N("rdf:type") and q.object == N("qb:Observation") and isinstance(q.subject, ox.NamedNode)}
    if (len(observations) != manifest["observations"] or len({r.get("obs_iri") for r in rows}) != len(rows)
            or {r.get("obs_iri") for r in rows} != observations
            or any(r.get("dataset_iri") != manifest["dataset_iri"] for r in rows)):
        raise ValueError("combine: RDF/Parquet observation identities disagree")
    try:
        reader = csv.DictReader(io.StringIO(captured["review-queue.csv"].decode("utf-8")), strict=True)
        if reader.fieldnames != list(review.REVIEW_QUEUE_COLUMNS):
            raise ValueError("invalid review queue header")
        items = list(reader)
    except (ValueError, UnicodeError, csv.Error) as exc:
        raise ValueError("combine: invalid review queue CSV") from exc
    terms = provenance.terms(cfg)
    pending = {q.subject.value for q in staged if q.predicate.value == terms.review_status and q.object == ox.NamedNode(terms.values["awaitingReview"]) and isinstance(q.subject, ox.NamedNode)}
    if (len(items) != len(pending) or {r.get("target") for r in items} != pending
            or len(pending) != manifest["review_counts"].get("awaitingReview", 0)
            or any(set(r) != set(review.REVIEW_QUEUE_COLUMNS) or any(v is None for v in r.values()) for r in items)
            or any(r.get("status") != "awaitingReview" or r.get("suggested_decision") != "" for r in items)):
        raise ValueError("combine: review queue disagrees with recorded pending targets")


def _parquet_schema(schema, pa):
    """The fixed writer contract, with its permitted optional source columns."""
    required = {name: pa.field(name, dtype, nullable=nullable) for name, dtype, nullable in (
        ("obs_iri", pa.string(), False), ("dataset_iri", pa.string(), False),
        ("measure_iri", pa.string(), False), ("value", pa.float64(), False),
        ("unit_iri", pa.string(), False), ("year", pa.int32(), False),
        ("year_basis_iri", pa.string(), False), ("estimate_type_iri", pa.string(), True),
        ("method_iri", pa.string(), True), ("review_status", pa.string(), True))}
    if len(schema.names) != len(set(schema.names)) or not set(required) <= set(schema.names):
        raise ValueError("combine: missing/duplicate current writer Parquet fields")
    for field in schema:
        if field.name in required:
            expected = required[field.name]
        elif field.name in ("standard_error", "cv", "lower", "upper"):
            expected = pa.field(field.name, pa.float64())
        elif field.name.endswith("_iri") and field.name != "_iri":
            expected = pa.field(field.name, pa.string())
        else:
            raise ValueError("combine: unsupported observation Parquet field")
        if field.type != expected.type or field.nullable != expected.nullable:
            raise ValueError("combine: observation Parquet type/nullability differs from current writer")
    return required


def _pending_union(store, staged, cfg):
    """Check exact original RDF terms globally without asserting reified SPOs.

    The bounded loader has no registry of other datasets' configurations.
    Another current-format profile's reviewStatus predicate therefore fails
    closed, rather than silently leaving its pending statements unprotected.
    """
    terms = provenance.terms(cfg)
    values, live = {}, set()
    for q in chain(store, staged):
        predicate = q.predicate.value
        if predicate.endswith(("/reviewStatus", "#reviewStatus")) and predicate != terms.review_status:
            raise ValueError("combine: unsupported mixed review profile namespace")
        values.setdefault((q.subject, predicate), set()).add(q.object)
        live.add((q.subject, q.predicate, q.object))
    known = {ox.NamedNode(terms.values[token]) for token in provenance.REVIEW_STATUSES}
    pending = ox.NamedNode(terms.values["awaitingReview"])
    for (target, predicate), statuses in values.items():
        if predicate != terms.review_status:
            continue
        if not isinstance(target, ox.NamedNode) or len(statuses) != 1 or not statuses <= known:
            raise ValueError("combine: invalid/conflicting combined review target/status")
        if pending not in statuses:
            continue
        modern = values.get((target, config.STATIC_NS["rdf"] + "reifies"), set())
        legacy = [values.get((target, config.STATIC_NS["rdf"] + part), set())
                  for part in ("subject", "predicate", "object")]
        statements = set()
        if modern:
            if len(modern) != 1 or not all(isinstance(t, ox.Triple) for t in modern):
                raise ValueError("combine: malformed pending RDF 1.2 reifier")
            triple = next(iter(modern))
            statements.add((triple.subject, triple.predicate, triple.object))
        if any(legacy):
            if any(len(v) != 1 for v in legacy):
                raise ValueError("combine: incomplete/ambiguous pending RDF 1.1 reifier")
            s, p, o = (next(iter(v)) for v in legacy)
            if not isinstance(s, (ox.NamedNode, ox.BlankNode)) or not isinstance(p, ox.NamedNode):
                raise ValueError("combine: invalid pending RDF 1.1 terms")
            statements.add((s, p, o))
        if len(statements) > 1:
            raise ValueError("combine: conflicting pending statement encodings")
        if statements & live:
            raise ValueError("combine: awaitingReview SPO is live in the combined input union")


def _caller_graphs(store, staged, graphs):
    for graph in graphs.values():
        existing = set(store.quads_for_pattern(None, None, None, ox.NamedNode(graph)))
        incoming = set(staged.quads_for_pattern(None, None, None, ox.NamedNode(graph)))
        if existing and existing != incoming:
            raise ValueError("combine: caller already contains different content for this dataset graph")


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
