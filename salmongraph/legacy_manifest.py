"""Explicit hash-pinned admission of the legacy T1 NuSEDS exports.

This is NOT salmongraph-build/1. Original RDF terms/graphs and CSV/Parquet
bytes stay legacy. No measure, year basis, release/version/date, provenance,
review decision or approval is created. The content label is explicitly
derived from export hashes, not a source version. The current loader is
unchanged. Cross-source numeric aggregation eligibility remains false.

Only the 38 reviewed exported paths are recognized. graph/store/** is an
explicit optional physical-runtime exclusion, never opened/admitted. Default
pins are the repeated build-4 exports (producer f4cc4e3, public SDK943).
Future reviewed builds require an explicit caller-supplied expected_files
mapping. A self-written/adjacent manifest is never admission authority.

The caller owns one writer. Descriptor capture plus a final snapshot detects
changes without locking input trees. All gates precede one transactional
Store.extend. This is memory-bound and does not rerun SHACL or certify signed
authenticity, original-source/tool provenance truth, science, rights or release.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import csv
import gzip
import hashlib
import io
import math
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
import zlib

import pyoxigraph as ox

from . import combine, config, provenance
from .graph import N

__all__ = ["DEFAULT_EXPECTED_FILES", "LegacyBuildError",
           "is_legacy_nuseds_build", "load_legacy_nuseds_build"]

_SLUG = "psf-nuseds-cleaned"
_BASE = "https://w3id.org/salmon-demo-corpus/"
_DATASET = _BASE + "dataset/" + _SLUG
_SOURCE = "https://doi.org/10.5281/zenodo.19959144"
_PARTS = ("metadata", "mappings", "identity", "crosswalk", "cube", "provenance")
_GRAPHS = {part: _BASE + "graph/" + _SLUG + "/" + part for part in _PARTS}
_PKG = "packages/" + _SLUG + "/"
_GRAPH = "graph/" + _SLUG + ".trig.gz"
_SUMMARY = _PKG + "review/graph-summary.json"
_BUILD = _PKG + "review/build-summary.json"
_PARQUET = _PKG + "data/nuseds_cuid_streamid.iri-keyed.parquet"
_CUBE = _PKG + "data/cu_year_spawners.csv"
_CUBE_FIELDS = ("cuid", "FULL_CU_IN_PSE", "cu_name_pse", "SPECIES",
                "SPECIES_QUALIFIED", "regionid", "region", "Year",
                "ESTIMATE_CLASSIFICATION", "spawner_abundance", "n_sites")
_JOIN_FIELDS = ("cu_iri", "stream_iri", "population_iri", "site_iri",
                "species_iri", "estimate_classification_iri")
_CAPTURE = frozenset({_GRAPH, _SUMMARY, _BUILD, _PARQUET, _CUBE})
DEFAULT_EXPECTED_FILES: Mapping[str, str] = MappingProxyType({
    "graph/psf-nuseds-cleaned.trig.gz": "89291aaa37e7b49fb13586af4c7ef0698fea5612d5f9645004545c4c0a5cf960",
    "packages/psf-nuseds-cleaned/.sdp-package": "0772f8c9d22f02d76030f93b07f1706ccf4a7c69cbeff4396d69a667ee687b3a",
    "packages/psf-nuseds-cleaned/data/cu_year_spawners.csv": "1e7bdde6f8834a9d79b9d81e7edba9aefc05fbd8a68c732a514d1eb321602634",
    "packages/psf-nuseds-cleaned/data/nuseds_cuid_streamid.csv": "43e43a07de8f433d05c5203ec9feca2566a2561b49820b6f502e2c43f16fb9f5",
    "packages/psf-nuseds-cleaned/data/nuseds_cuid_streamid.iri-keyed.parquet": "e2a38b9c54d2352f4f9937a66d670b74918c1e9b4b6fd58bb95f1172ab202107",
    "packages/psf-nuseds-cleaned/datapackage.json": "cc914a522ba4e63d50f78b6503f11998c2acb63367848fdee9e1cf4bf58ef9fe",
    "packages/psf-nuseds-cleaned/metadata/codes.csv": "7d2ddfea752294f559ca490bcbed3c2be94ff3ac2fcf1db58bfbb0606e72af5f",
    "packages/psf-nuseds-cleaned/metadata/column_dictionary.csv": "3e3a5c7954b813317493f9e7e5276f13f8b37d4beb42eb183eeac4726432f1b8",
    "packages/psf-nuseds-cleaned/metadata/dataset.csv": "6842d14f09dcc4fcf9ec2853db2bc9aa002a35830512ed9bdec4289d4f19cc55",
    "packages/psf-nuseds-cleaned/metadata/semantic/mapping-sets.json": "11122a61bf20ccecb5f161dff7815a5d999f2aa98453e58fae81c42e758356d7",
    "packages/psf-nuseds-cleaned/metadata/semantic/measurement-decompositions.csv": "8217581fe32307fea4a474a6bdd04369402d46578b11ec16629ce802dcfbd3e7",
    "packages/psf-nuseds-cleaned/metadata/semantic/measurement-decompositions.json": "73794b6cbac7c5f099b5d3c5b6c0caed759b11e0c065c1d223641b737525d71b",
    "packages/psf-nuseds-cleaned/metadata/semantic/psf-nuseds-cleaned-enumeration-method.sssom.tsv": "24deda0db88ca5c435dc8bf522a4addaf82c774981b4cd5762fe1e6c82d3cab0",
    "packages/psf-nuseds-cleaned/metadata/semantic/psf-nuseds-cleaned-estimate-classification.sssom.tsv": "d360a1228244cd9613d2df9ebcedfa9bb5de8b5c217979047083eaa05d88b068",
    "packages/psf-nuseds-cleaned/metadata/semantic/psf-nuseds-cleaned-estimate-method.sssom.tsv": "5f900610227ec389a5b247f8148fa80126c5fa1e451019c7a52f12d9da955f83",
    "packages/psf-nuseds-cleaned/metadata/structure/observation_components.csv": "88675531822a014fb1a9d3d2260271e06b6e1bb5d7f6f124bfd81efbc6198ac7",
    "packages/psf-nuseds-cleaned/metadata/structure/observation_structures.csv": "6a206ab9f5cb7c7337accc424ca9283e2e72bb99767523cb28a5fc7e6bde8faa",
    "packages/psf-nuseds-cleaned/metadata/tables.csv": "dcb0ce9270462bd91f1214581ac567095234f1cf94b0757402d6eaeef19fcf5c",
    "packages/psf-nuseds-cleaned/review/build-summary.json": "c9cd6b03f4febf9ee3d00a3a4b124001293a594f68ad73582242513ac4f8b6a1",
    "packages/psf-nuseds-cleaned/review/graph-summary.json": "6a5bfc16b3cd46e4c3a4fa696e3c6b5aa17b299d72e51b30c3700ef821e32c4e",
    "packages/psf-nuseds-cleaned/review/metasalmonpy-detect-semantic-term-gaps.csv": "22789e043d3eaf23f83eb60b9b7853b3b3ac70079aa92fc8426b954e33d9d1a8",
    "packages/psf-nuseds-cleaned/review/term-gaps.csv": "fa0b74888c5607730615784c56a45870d5aa5792daa014d024d33584739a0f4a",
    "profiles/psf-nuseds-cleaned/column-profile.csv": "b9eec642f02f0b0d4950b5cfbb60125b209b49b2bd68e3bd6dc6e8bf61be26d8",
    "profiles/psf-nuseds-cleaned/profile-summary.json": "5cdf906bc1122ffde2da07e60406b251078c056624c887fff2d1bfe1ebd3e9d1",
    "queries/psf-nuseds-cleaned/01-cu-decade-coverage.csv": "fdd3a7d05acf9ab040228d85f1b9073dcf63d820c419ec163b3260e9762651dd",
    "queries/psf-nuseds-cleaned/01-cu-decade-coverage.rq": "5fd623ce15d45e2396a50c7d96ba0a6472f6f3da8d448090eae0d2e84161a971",
    "queries/psf-nuseds-cleaned/02-classification-by-decade.csv": "166e12a1a7aace861782dcc8da0be24b02083c2da1a8f88b130d2b77ed05aa24",
    "queries/psf-nuseds-cleaned/02-classification-by-decade.rq": "16379ba9ef3a77d04a0cd46eb4f228968a8de0d944ce77dc4b35569b91346735",
    "queries/psf-nuseds-cleaned/03-low-quality-cus.csv": "2023838f6144e0d40c42490913a109a37373e2b630df74e4a1e866f97570e4ff",
    "queries/psf-nuseds-cleaned/03-low-quality-cus.rq": "c664a09dbcbd649a9a798f9a3c537c3f73b2ff61642c739509629dbeb83f3e92",
    "queries/psf-nuseds-cleaned/04-columns-lacking-terms.csv": "932e4d25dc6a2cd6f84323444d3835c5b983f6a9a87ac1321008331145dd128a",
    "queries/psf-nuseds-cleaned/04-columns-lacking-terms.rq": "cfcc3e70dbb59b18daae7cbc9e28b92e3b3eef131739c837eed35e1be72a8435",
    "queries/psf-nuseds-cleaned/05-monitoring-by-year.csv": "c388ed8ecb4d8e76ab0102799270d3500a6bda9f8f7d4cfbd0c78625bdf9b45e",
    "queries/psf-nuseds-cleaned/05-monitoring-by-year.rq": "6b8dcd4eb055ac8a1bc7334032d86718af02606a20ccdb5ed218070cd6e3b00f",
    "queries/psf-nuseds-cleaned/06-cu-identity-crosswalk.csv": "80fa1713deef4339826f9a32439668a1e7601ad6ea586236e66f9e92821f1840",
    "queries/psf-nuseds-cleaned/06-cu-identity-crosswalk.rq": "cf85e769528e13a312e1280aed268230bb83a74df8f56b52b737bbd9f0775262",
    "queries/psf-nuseds-cleaned/07-mapping-evidence.csv": "0ee917bbfa296b8243ce2dd2a5500eecea8042d322c53d435e00005e880b88f4",
    "queries/psf-nuseds-cleaned/07-mapping-evidence.rq": "dd1932f696afd7a9fe3efe9ddee80e90703388ce84e10aa83690be712990eef6",
})


class LegacyBuildError(ValueError):
    """A legacy export failed scoped recognition or safe admission."""


def is_legacy_nuseds_build(build_dir: Path, *,
                          expected_files: Mapping[str, str] | None = None) -> bool:
    """Run strict scoped recognition without modifying inputs or a caller.

    Both APIs default to immutable built-in pins. An explicit reviewed override
    must cover exactly the same known 38 paths. Invalid/mutated/raced inputs
    return false, never a fallback to another format.
    """
    try:
        root, expected = _root(build_dir), _pins(expected_files)
        _, _, before = _prepare(root, expected)
        _unchanged(root, expected, before)
        return True
    except (LegacyBuildError, OSError, ValueError, TypeError):
        return False


def load_legacy_nuseds_build(store: ox.Store, build_dir: Path, *,
                            expected_files: Mapping[str, str] | None = None) -> dict:
    """Verify original exports and admit original legacy RDF in one transaction.

    Source-row Parquet is not projected into current observation Parquet.
    Equal repeated loads are idempotent; different content in the six
    unversioned graphs is refused. Reified statements are never materialized.
    """
    if not isinstance(store, ox.Store):
        raise LegacyBuildError("legacy: caller must supply a pyoxigraph Store")
    root, expected = _root(build_dir), _pins(expected_files)
    staged, report, before = _prepare(root, expected)
    try:
        combine._caller_graphs(store, staged, _GRAPHS)
        combine._pending_union(store, staged, config.Config(base=_BASE))
    except ValueError as exc:
        raise LegacyBuildError(str(exc)) from exc
    _unchanged(root, expected, before)
    store.extend(staged)
    return report


def _pins(value):
    raw = DEFAULT_EXPECTED_FILES if value is None else value
    if not isinstance(raw, Mapping) or set(raw) != set(DEFAULT_EXPECTED_FILES):
        raise LegacyBuildError("legacy: pins must cover exactly the recognized 38 export paths")
    expected = dict(raw)
    for name, digest in expected.items():
        if (not isinstance(name, str) or name.startswith("/") or "\\" in name
                or ":" in name or "\0" in name
                or any(p in ("", ".", "..") for p in name.split("/"))
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise LegacyBuildError("legacy: invalid export path or SHA256 pin")
    return expected


def _root(value):
    try:
        path = Path(value).absolute()
    except (TypeError, ValueError) as exc:
        raise LegacyBuildError("legacy: invalid build path") from exc
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise LegacyBuildError("legacy: build path must not traverse parents or symlinks")
    if not path.is_dir():
        raise LegacyBuildError("legacy: build root must be an existing directory")
    return path


def _identity(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def _snapshot(root, expected, *, capture):
    """Anchor every path component; never follow links, devices or FIFOs."""
    records, directories, payloads, identities = {}, set(), {}, {}
    allowed_dirs = {p.as_posix() for name in expected for p in Path(name).parents
                    if p != Path(".")}
    flags = os.O_RDONLY | os.O_NOFOLLOW

    def walk(fd, prefix=""):
        for name in sorted(os.listdir(fd)):
            relative = prefix + name
            item = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if relative == "graph/store" and stat.S_ISDIR(item.st_mode):
                continue  # physical runtime database is deliberately outside scope
            if stat.S_ISDIR(item.st_mode):
                if relative not in allowed_dirs:
                    raise LegacyBuildError("legacy: unexpected export directory")
                child = os.open(name, flags | os.O_DIRECTORY, dir_fd=fd)
                try:
                    if _identity(os.fstat(child)) != _identity(item):
                        raise LegacyBuildError("legacy: directory changed during verification")
                    directories.add(relative)
                    identities[relative + "/"] = _identity(item)
                    walk(child, relative + "/")
                finally:
                    os.close(child)
            elif stat.S_ISREG(item.st_mode):
                if relative not in expected:
                    raise LegacyBuildError("legacy: unexpected export file")
                child = os.open(name, flags | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(child, "rb") as stream:
                    first = os.fstat(stream.fileno())
                    if not stat.S_ISREG(first.st_mode) or _identity(first) != _identity(item):
                        raise LegacyBuildError("legacy: file changed during verification")
                    digest, chunks = hashlib.sha256(), []
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        if capture and relative in _CAPTURE:
                            chunks.append(chunk)
                    if _identity(os.fstat(stream.fileno())) != _identity(first):
                        raise LegacyBuildError("legacy: file changed during verification")
                if digest.hexdigest() != expected[relative]:
                    raise LegacyBuildError("legacy: export SHA256 pin mismatch: " + relative)
                records[relative] = {"path": relative, "bytes": first.st_size,
                                     "sha256": digest.hexdigest()}
                identities[relative] = _identity(first)
                if capture and relative in _CAPTURE:
                    payloads[relative] = b"".join(chunks)
            else:
                raise LegacyBuildError("legacy: symlink or special file in export scope")

    fd = None
    try:
        fd = os.open(root.anchor, flags | os.O_DIRECTORY)
        for part in root.parts[1:]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        identities["/"] = _identity(os.fstat(fd))
        walk(fd)
    except OSError as exc:
        raise LegacyBuildError("legacy: cannot safely read build exports") from exc
    finally:
        if fd is not None:
            os.close(fd)
    if set(records) != set(expected) or directories != allowed_dirs:
        raise LegacyBuildError("legacy: missing export or directory inventory mismatch")
    return records, directories, payloads, identities


def _unchanged(root, expected, before):
    records, dirs, _, ids = _snapshot(root, expected, capture=False)
    if (records, dirs, ids) != before:
        raise LegacyBuildError("legacy: export changed during verification")


def _json(payload, name):
    try:
        result = combine._json(payload, name)
    except ValueError as exc:
        raise LegacyBuildError(str(exc)) from exc
    if not isinstance(result, dict):
        raise LegacyBuildError("legacy: expected JSON object for " + name)
    return result


def _count(value):
    return type(value) is int and value >= 0


def _prepare(root, expected):
    records, dirs, data, ids = _snapshot(root, expected, capture=True)
    content = hashlib.sha256("\n".join(name + "\t" + expected[name]
                                     for name in sorted(expected)).encode()).hexdigest()
    source = _json(data[_SUMMARY], "legacy graph summary")
    build = _json(data[_BUILD], "legacy build summary")
    try:
        raw = gzip.decompress(data[_GRAPH])
        parsed = ox.parse(input=raw, format=ox.RdfFormat.TRIG, rename_blank_nodes=False)
        staged = ox.Store()
        scope = _DATASET + "\x1flegacy-content-sha256:" + content
        staged.extend(combine._scoped_quad(q, scope) for q in parsed)
    except (OSError, ValueError, SyntaxError, EOFError, zlib.error) as exc:
        raise LegacyBuildError("legacy: malformed/truncated gzip or complete TriG required") from exc
    counts = Counter(q.graph_name.value for q in staged)
    per_graph = source.get("per_graph")
    if (not isinstance(per_graph, dict) or set(per_graph) != set(_PARTS)
            or any(not _count(v) or v <= 0 for v in per_graph.values())
            or dict(counts) != {_GRAPHS[k]: v for k, v in per_graph.items()}
            or not _count(source.get("quads_dataset"))
            or source["quads_dataset"] != len(staged)):
        raise LegacyBuildError("legacy: actual unique graph counts disagree with summary")
    if (source.get("graph_file") != _GRAPH or not _count(source.get("graph_file_bytes"))
            or source["graph_file_bytes"] != len(data[_GRAPH])
            or not _count(source.get("parquet_bytes"))
            or source["parquet_bytes"] != len(data[_PARQUET])):
        raise LegacyBuildError("legacy: artifact summary disagrees with pinned bytes")
    dataset_terms = {q.subject for q in staged if q.predicate == N("rdf:type")
                     and q.object == N("dcat:Dataset")}
    if dataset_terms != {N(_DATASET), N(_SOURCE)} or ox.Quad(
            ox.NamedNode(_DATASET), N("rdf:type"), N("dcat:Dataset"),
            ox.NamedNode(_GRAPHS["metadata"])) not in staged:
        raise LegacyBuildError("legacy: unsupported dataset identity inventory")
    datasets = {node.value for node in dataset_terms}
    observations = {q.subject for q in staged if q.predicate == N("rdf:type")
                    and q.object == N("qb:Observation")}
    if (any(not isinstance(s, ox.NamedNode) for s in observations)
            or any(q.graph_name != N(_GRAPHS["cube"]) for q in staged
                   if q.predicate == N("rdf:type") and q.object == N("qb:Observation"))
            or not _count(source.get("cube_observations"))
            or len(observations) != source["cube_observations"]
            or not _count(build.get("cube_rows")) or build["cube_rows"] != len(observations)):
        raise LegacyBuildError("legacy: aggregate RDF observation counts disagree")
    # Preserve the actual legacy two-measure grain, without choosing either
    # value as a current observation or assigning new biological semantics.
    for observation in observations:
        for name, datatype in (("spawnerAbundance", "xsd:double"),
                               ("siteCount", "xsd:integer")):
            values = {q.object for q in staged.quads_for_pattern(
                observation, N(_BASE + "def/" + name), None, None)}
            if len(values) != 1:
                raise LegacyBuildError("legacy: missing/ambiguous original cube measure")
            value = next(iter(values))
            if not isinstance(value, ox.Literal) or value.datatype != N(datatype):
                raise LegacyBuildError("legacy: unsupported original cube measure type")
            try:
                finite = math.isfinite(float(value.value))
            except ValueError:
                finite = False
            if not finite:
                raise LegacyBuildError("legacy: non-finite original cube measure")
    row_count, cube_count, join_counts = _sidecars(data, source, build)
    pending, identity_candidates = _pending(staged)
    try:
        combine._pending_union(ox.Store(), staged, config.Config(base=_BASE))
    except ValueError as exc:
        raise LegacyBuildError(str(exc)) from exc
    recorded = sorted({q.predicate.value for q in staged
                       if q.subject == ox.NamedNode(_DATASET)
                       and q.predicate in {N("pav:version"), N("dcterms:created")}})
    report = {
        "schema": "legacy-nuseds-admission/1",
        "slug": _SLUG, "dataset_iri": _DATASET, "corpus_dataset_iri": _DATASET,
        "source_dataset_iri": _SOURCE, "dcat_dataset_iris": sorted(datasets),
        "content_sha256": content,
        "content_label": {"kind": "derived-export-content-sha256", "sha256": content,
                          "is_source_version_or_release": False},
        "files": [records[name] for name in sorted(records)],
        "excluded_scope": ["graph/store/** physical runtime files (not opened/admitted)"],
        "graphs": dict(_GRAPHS), "quad_counts": dict(sorted(counts.items())),
        "quads": len(staged), "parquet_rows": row_count,
        "aggregate_observations": cube_count, "parquet_join_keys": join_counts,
        "total_pending_targets": pending,
        "review_counts": {"awaitingReview": pending} if pending else {},
        "scoped_identity_candidates": identity_candidates,
        "scoped_identity_candidates_note": "Pending SKOS/sameAs links with at least one native/type-known CU or Population endpoint, plus populationOf candidates under the legacy producer profile; structural inventory, not identity approval or inferred endpoint types.",
        "recorded_dataset_metadata_predicates": recorded,
        "missing_current_metadata_predicates": sorted({N("pav:version").value,
            N("dcterms:created").value} - set(recorded)),
        "current_format_certified": False, "numeric_aggregation_eligible": False,
        "publication_ready": False, "scientific_approval": False,
        "validation": {"scope": "pinned hashes, legacy counts/identity, pending/live containment",
                       "current_format": False, "shacl_rerun": False},
        "limitations": [
            "Six unversioned legacy graphs, including crosswalk, remain unchanged; different releases require an approved graph-identity migration.",
            "Two dcat:Dataset nodes remain. No source release/version/date is invented; recorded dataset metadata predicates are inventory only.",
            "Missing current-format dataset metadata predicates are listed explicitly; no version/date is inferred to fill them.",
            "Source-row Parquet and aggregate RDF have different grains; each legacy cube observation carries two measures. No current observation Parquet or numeric projection is created.",
            "Exact exported bytes/counts are checked; numeric aggregation, original-source/tool provenance truth, full D6/SHACL, science, rights and publication approval are not certified.",
            "All admitted review targets remain awaitingReview; accepted legacy decision formats are unsupported.",
        ],
    }
    return staged, report, (records, dirs, ids)


def _sidecars(data, source, build):
    import pyarrow as pa
    import pyarrow.parquet as pq
    try:
        parquet = pq.ParquetFile(pa.BufferReader(data[_PARQUET]))
        schema = parquet.schema_arrow
        if len(schema.names) != len(set(schema.names)) or not set(_JOIN_FIELDS) <= set(schema.names):
            raise LegacyBuildError("legacy: missing/duplicate source-row Parquet join fields")
        if any(schema.field(name).type != pa.string() for name in _JOIN_FIELDS):
            raise LegacyBuildError("legacy: join-key Parquet fields must be strings")
        if not _count(build.get("main_rows")) or parquet.metadata.num_rows != build["main_rows"]:
            raise LegacyBuildError("legacy: source-row Parquet count disagrees")
        if not isinstance(source.get("parquet_join_keys"), dict) or set(source["parquet_join_keys"]) != set(_JOIN_FIELDS):
            raise LegacyBuildError("legacy: malformed join-key count inventory")
        join_counts = {}
        table = parquet.read(columns=list(_JOIN_FIELDS))
        for name in _JOIN_FIELDS:
            values = set(table[name].to_pylist()) - {None}
            if any(not isinstance(v, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9+.-]*:[^\s]+", v) for v in values):
                raise LegacyBuildError("legacy: non-IRI source-row join key")
            join_counts[name] = len(values)
            if not _count(source["parquet_join_keys"][name]) or join_counts[name] != source["parquet_join_keys"][name]:
                raise LegacyBuildError("legacy: actual Parquet join-key count disagrees")
        reader = csv.DictReader(io.StringIO(data[_CUBE].decode("utf-8")), strict=True)
        if reader.fieldnames != list(_CUBE_FIELDS):
            raise LegacyBuildError("legacy: unsupported aggregate CSV header")
        cube_rows = 0
        for row in reader:
            if set(row) != set(_CUBE_FIELDS) or any(v is None for v in row.values()):
                raise LegacyBuildError("legacy: malformed aggregate CSV row")
            if (not row["cuid"] or not re.fullmatch(r"-?\d+", row["Year"])
                    or not math.isfinite(float(row["spawner_abundance"]))
                    or not re.fullmatch(r"\d+", row["n_sites"])):
                raise LegacyBuildError("legacy: malformed aggregate numeric fields")
            cube_rows += 1
        if cube_rows != source["cube_observations"] or cube_rows != build["cube_rows"]:
            raise LegacyBuildError("legacy: aggregate CSV/RDF row counts disagree")
    except (ValueError, OSError, pa.ArrowException, UnicodeError, csv.Error) as exc:
        if isinstance(exc, LegacyBuildError):
            raise
        raise LegacyBuildError("legacy: malformed source-row Parquet or aggregate CSV") from exc
    return parquet.metadata.num_rows, cube_rows, join_counts


def _pending(staged):
    """Pending candidates only; never infer any human/agent acceptance."""
    terms = provenance.terms(config.Config(base=_BASE))
    targets = {}
    identities = set()
    for q in staged:
        if q.predicate.value == terms.review_status:
            targets.setdefault(q.subject, set()).add(q.object)
        if q.predicate == N("rdf:type"):
            if q.object in {N("gcdfo:ConservationUnit"), N("smn:Population")}:
                identities.add(q.subject)
    matches = {N("skos:" + name) for name in
               ("exactMatch", "closeMatch", "broadMatch", "narrowMatch")}
    def identity(node):
        # Native producer ID families are part of this reviewed legacy format,
        # not evidence that a biological identity is accepted. Missing rdf:type
        # must not turn their critical bridges into ordinary source-code links.
        prefixes = (_BASE + "id/cu/", _BASE + "id/population/")
        return (node in identities or (isinstance(node, ox.NamedNode)
                and any(node.value.startswith(p) and len(node.value) > len(p)
                        for p in prefixes)))
    def identity_pair(s, p, o):
        # populationOf is emitted only as a critical candidate by this legacy
        # producer. Fail closed on any live use, even without endpoint types or
        # native IDs. This does not add types or reinterpret a source value.
        # One known identity endpoint is sufficient: dropping a foreign
        # endpoint's types must not make an identity bridge look like harmless
        # code metadata. Nonidentity code mappings and the source DOI's
        # sameAs self-reference have no such endpoint and stay untouched.
        return (((p in matches or p == N("owl:sameAs")) and (identity(s) or identity(o)))
                or p == N("smn:populationOf"))
    # The reviewed legacy format has no accepted view/decision application.
    # An unmarked live identity edge must not evade protection merely by
    # dropping its reifier/status while updating an explicit override hash.
    if any(identity_pair(q.subject, q.predicate, q.object) for q in staged):
        raise LegacyBuildError("legacy: live critical identity bridge is unsupported")
    identity_candidates = set()
    for target, statuses in targets.items():
        if (not isinstance(target, ox.NamedNode)
                or statuses != {ox.NamedNode(terms.values["awaitingReview"])}):
            raise LegacyBuildError("legacy: conflicting/unsupported review status")
        modern = list(staged.quads_for_pattern(target, N("rdf:reifies"), None, None))
        legacy = [list(staged.quads_for_pattern(target, N("rdf:" + part), None, None))
                  for part in ("subject", "predicate", "object")]
        if not modern and not any(legacy):
            raise LegacyBuildError("legacy: pending target has no statement encoding")
        statements = set()
        if len(modern) == 1 and isinstance(modern[0].object, ox.Triple):
            t = modern[0].object
            statements.add((t.subject, t.predicate, t.object))
        values = [{q.object for q in fields} for fields in legacy]
        if all(len(fields) == 1 for fields in values):
            statements.add(tuple(next(iter(fields)) for fields in values))
        if len(statements) == 1:
            s, p, o = next(iter(statements))
            if identity_pair(s, p, o):
                identity_candidates.add(target)
        # Complete cardinality/encoding and exact live-SPO containment follow in
        # the unchanged aggregate gate; no shadow triples are ever introduced.
    return len(targets), len(identity_candidates)
