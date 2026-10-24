"""Pinned legacy admission invariants, without SDK, network or scientific guesses."""
from collections import Counter
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import socket

import pyarrow as pa
import pyarrow.parquet as pq
import pyoxigraph as ox
import pytest

from salmongraph import combine, config, legacy_manifest as legacy
from salmongraph.graph import L, N
from salmongraph.io import det


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    attempted = []
    def blocked(*a, **kw):
        attempted.append(True)
        raise AssertionError("legacy admission tests must not attempt network")
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex",
                 "gethostbyaddr", "getnameinfo", "create_connection"):
        monkeypatch.setattr(socket, name, blocked)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, blocked)
    yield
    assert attempted == []


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(root, path):
    return json.loads((root / path).read_text())


def write_json(root, path, value):
    (root / path).write_bytes(det.json_bytes(value))


def seal(root):
    summary = load_json(root, legacy._SUMMARY)
    summary["graph_file_bytes"] = (root / legacy._GRAPH).stat().st_size
    summary["parquet_bytes"] = (root / legacy._PARQUET).stat().st_size
    write_json(root, legacy._SUMMARY, summary)
    return {name: digest(root / name) for name in legacy.DEFAULT_EXPECTED_FILES}


def quads(root):
    return list(ox.parse(input=gzip.decompress((root / legacy._GRAPH).read_bytes()),
                         format=ox.RdfFormat.TRIG, rename_blank_nodes=False))


def write_graph(root, values, *, counts=True):
    (root / legacy._GRAPH).write_bytes(det.gzip_bytes(det.trig_bytes(values)))
    if counts:
        unique = set(values)
        summary = load_json(root, legacy._SUMMARY)
        counter = Counter(q.graph_name.value for q in unique
                          if isinstance(q.graph_name, ox.NamedNode))
        summary["per_graph"] = {part: counter[g] for part, g in legacy._GRAPHS.items()}
        summary["quads_dataset"] = len(unique)
        summary["cube_observations"] = len({q.subject for q in unique
            if q.predicate == N("rdf:type") and q.object == N("qb:Observation")})
        write_json(root, legacy._SUMMARY, summary)
    return seal(root)


def pending(root):
    terms = legacy.provenance.terms(config.Config(base=legacy._BASE))
    for q in quads(root):
        if q.predicate.value == terms.review_status:
            return q.subject
    raise AssertionError("fixture candidate missing")


@pytest.fixture
def built(tmp_path):
    root = tmp_path.resolve() / "legacy"
    for name in legacy.DEFAULT_EXPECTED_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture\n")
    graph = {k: N(v) for k, v in legacy._GRAPHS.items()}
    s, p, o = N(legacy._BASE + "id/cu/source"), N("skos:exactMatch"), N("https://example.test/proposed")
    r = N(legacy._BASE + "assertion/fixture")
    status = N(legacy._BASE + "profile/reviewStatus")
    values = [ox.Quad(N(legacy._DATASET), N("rdf:type"), N("dcat:Dataset"), graph["metadata"]),
              ox.Quad(N(legacy._SOURCE), N("rdf:type"), N("dcat:Dataset"), graph["provenance"])]
    for k, g in graph.items():
        values.append(ox.Quad(N(legacy._BASE + "fixture/" + k), N("rdfs:label"),
                              L("Source literal 1.2500"), g))
    for pred, obj in [("rdf:type", N("rdf:Statement")), ("rdf:subject", s),
                      ("rdf:predicate", p), ("rdf:object", o)]:
        values.append(ox.Quad(r, N(pred), obj, graph["identity"]))
    values.append(ox.Quad(r, status, N(legacy._BASE + "profile/awaitingReview"), graph["identity"]))
    obs = N(legacy._BASE + "cube/fixture/obs/1")
    for pred, obj in [("rdf:type", N("qb:Observation")),
                      ("qb:dataSet", N(legacy._BASE + "cube/fixture")),
                      (legacy._BASE + "def/spawnerAbundance", L(3.75)),
                      (legacy._BASE + "def/siteCount", L(2))]:
        values.append(ox.Quad(obs, N(pred), obj, graph["cube"]))
    columns = {name: pa.array(["https://example.test/" + name] * 2, type=pa.string())
               for name in legacy._JOIN_FIELDS}
    columns.update({"ACT_ID": pa.array([1, 2], type=pa.int64()),
                    "Year": pa.array([2000, 2000], type=pa.int64()),
                    "MAX_ESTIMATE": pa.array([1.25, 2.5], type=pa.float64())})
    pq.write_table(pa.table(columns), root / legacy._PARQUET)
    (root / legacy._CUBE).write_bytes(det.csv_bytes(legacy._CUBE_FIELDS,
        [[1, "source", "Source CU", "Pink", "Pink", 1, "Source region",
          2000, "Source class", "3.75", 2]]))
    (root / (legacy._PKG + "data/nuseds_cuid_streamid.csv")).write_bytes(
        b"ACT_ID,Year,MAX_ESTIMATE\n1,2000,1.25\n2,2000,2.5\n")
    write_json(root, legacy._BUILD, {"main_rows": 2, "cube_rows": 1})
    write_json(root, legacy._SUMMARY, {"quads_dataset": 0, "per_graph": {},
        "cube_observations": 1, "graph_file": legacy._GRAPH,
        "graph_file_bytes": 0, "parquet_bytes": 0,
        "parquet_join_keys": {name: 1 for name in legacy._JOIN_FIELDS}})
    pins = write_graph(root, values)
    return root, pins


def caller():
    store = ox.Store()
    store.add(ox.Quad(N("https://example.test/prior"), N("rdfs:label"),
                      L("Preserve prior"), ox.DefaultGraph()))
    return store


def refuses(root, pins):
    store = caller()
    prior = set(store)
    with pytest.raises(legacy.LegacyBuildError):
        legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
    assert set(store) == prior
    assert not legacy.is_legacy_nuseds_build(root, expected_files=pins)


def test_explicit_pins_are_required_and_default_map_is_immutable(built):
    root, pins = built
    assert not legacy.is_legacy_nuseds_build(root)
    with pytest.raises(TypeError):
        legacy.DEFAULT_EXPECTED_FILES[legacy._GRAPH] = "0" * 64
    assert legacy.is_legacy_nuseds_build(root, expected_files=pins)


def test_success_preserves_source_terms_values_and_repeat_is_idempotent(built):
    root, pins = built
    before = {n: (root / n).read_bytes() for n in pins}
    store = caller()
    original = set(store)
    current = config.current()
    report = legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
    assert original | set(quads(root)) == set(store)
    assert report["parquet_rows"] == 2 and report["aggregate_observations"] == 1
    assert report["total_pending_targets"] == 1 and report["scoped_identity_candidates"] == 1
    assert report["content_label"]["is_source_version_or_release"] is False
    assert report["current_format_certified"] is False
    assert report["numeric_aggregation_eligible"] is False
    assert report["publication_ready"] is False
    assert "version" not in report and "build_date" not in report
    first = set(store)
    assert legacy.load_legacy_nuseds_build(store, root, expected_files=pins) == report
    assert set(store) == first and current == config.current()
    assert {n: (root / n).read_bytes() for n in pins} == before
    assert not any(q.predicate == N("skos:exactMatch") for q in store)


def test_current_loader_is_not_implicitly_broadened(built):
    root, _ = built
    store = caller()
    before = set(store)
    with pytest.raises(ValueError):
        combine.load_dataset_build(store, root)
    assert set(store) == before


@pytest.mark.parametrize("kind", ["empty", "missing", "unsafe", "bad-sha", "nonmapping"])
def test_invalid_override_never_falls_back(built, kind):
    root, pins = built
    if kind == "empty": pins = {}
    elif kind == "missing": pins.pop(legacy._GRAPH)
    elif kind == "unsafe": pins["../escape"] = pins.pop(legacy._GRAPH)
    elif kind == "bad-sha": pins[legacy._GRAPH] = "Z" * 64
    else: pins = "pretend adjacent manifest"
    refuses(root, pins)


@pytest.mark.parametrize("kind", ["changed", "missing", "extra", "empty-dir", "file-link", "dir-link", "fifo", "store-link"])
def test_inventory_containment_faults_preserve_caller(built, tmp_path, kind):
    root, pins = built
    if kind == "changed": (root / legacy._GRAPH).write_bytes(b"mutated")
    elif kind == "missing": (root / legacy._GRAPH).unlink()
    elif kind == "extra": (root / "manifest.json").write_text(json.dumps(pins))
    elif kind == "empty-dir": (root / "unknown").mkdir()
    elif kind == "fifo": os.mkfifo(root / "pipe")
    elif kind == "store-link": (root / "graph/store").symlink_to(tmp_path.resolve(), target_is_directory=True)
    else:
        path = root / (legacy._GRAPH if kind == "file-link" else legacy._PKG.rstrip("/"))
        destination = tmp_path.resolve() / "outside"
        path.rename(destination)
        path.symlink_to(destination, target_is_directory=kind == "dir-link")
    refuses(root, pins)


def test_runtime_store_exclusion_is_explicit_and_never_read(built):
    root, pins = built
    runtime = root / "graph/store"
    runtime.mkdir()
    os.mkfifo(runtime / "not-opened")
    assert legacy.is_legacy_nuseds_build(root, expected_files=pins)


def test_symlink_root_and_parent_traversal_refused(built):
    root, pins = built
    linked = root.parent / "link"
    linked.symlink_to(root, target_is_directory=True)
    refuses(linked, pins)
    refuses(root / "graph/..", pins)


@pytest.mark.parametrize("payload", [b"not gzip", gzip.compress(b"broken {"), gzip.compress(b"")[:-3]])
def test_malformed_or_truncated_graph_fails_even_with_explicit_hash(built, payload):
    root, pins = built
    (root / legacy._GRAPH).write_bytes(payload)
    refuses(root, seal(root))


@pytest.mark.parametrize("fault", ["summary-count", "bool-count", "missing-graph", "rows", "cube-rows", "join-count", "duplicate-json"])
def test_count_and_sidecar_faults_fail_after_repinning(built, fault):
    root, pins = built
    s = load_json(root, legacy._SUMMARY)
    b = load_json(root, legacy._BUILD)
    if fault == "summary-count": s["quads_dataset"] += 1
    elif fault == "bool-count": s["cube_observations"] = True
    elif fault == "missing-graph": s["per_graph"].pop("crosswalk")
    elif fault == "rows": b["main_rows"] += 1
    elif fault == "cube-rows": b["cube_rows"] += 1
    elif fault == "join-count": s["parquet_join_keys"]["cu_iri"] += 1
    write_json(root, legacy._SUMMARY, s)
    write_json(root, legacy._BUILD, b)
    if fault == "duplicate-json":
        (root / legacy._BUILD).write_text('{"main_rows":2,"main_rows":2,"cube_rows":1}')
    refuses(root, seal(root))


def test_duplicate_serialized_quad_is_counted_once(built):
    root, pins = built
    q = quads(root)[0]
    extra = ox.serialize([q], format=ox.RdfFormat.TRIG)
    raw = gzip.decompress((root / legacy._GRAPH).read_bytes())
    (root / legacy._GRAPH).write_bytes(gzip.compress(raw + extra))
    assert legacy.is_legacy_nuseds_build(root, expected_files=seal(root))


@pytest.mark.parametrize("fault", ["default", "foreign", "third-dataset", "blank-dataset"])
def test_unsupported_rdf_identity_scope_refused(built, fault):
    root, pins = built
    qs = quads(root)
    graph = ox.DefaultGraph() if fault == "default" else N(
        "https://example.test/foreign" if fault == "foreign" else legacy._GRAPHS["metadata"])
    obj = N("dcat:Dataset") if fault in ("third-dataset", "blank-dataset") else L("foreign")
    predicate = N("rdf:type") if fault in ("third-dataset", "blank-dataset") else N("rdfs:label")
    subject = ox.BlankNode("extra") if fault == "blank-dataset" else N("https://example.test/third")
    qs.append(ox.Quad(subject, predicate, obj, graph))
    refuses(root, write_graph(root, qs))


@pytest.mark.parametrize("fault", ["accepted", "multiple-status", "missing-encoding", "ambiguous-object", "incomplete", "live-other-graph"])
def test_pending_candidate_integrity_refused(built, fault):
    root, pins = built
    r = pending(root)
    qs = quads(root)
    status = N(legacy._BASE + "profile/reviewStatus")
    g = N(legacy._GRAPHS["metadata"])
    if fault == "accepted":
        qs = [q for q in qs if not (q.subject == r and q.predicate == status)]
        qs.append(ox.Quad(r, status, N(legacy._BASE + "profile/humanAccepted"), g))
    elif fault == "multiple-status":
        qs.append(ox.Quad(r, status, N(legacy._BASE + "profile/agentAccepted"), g))
    elif fault == "missing-encoding":
        qs = [q for q in qs if not (q.subject == r and q.predicate in {N("rdf:subject"), N("rdf:predicate"), N("rdf:object")})]
    elif fault == "incomplete":
        qs = [q for q in qs if not (q.subject == r and q.predicate == N("rdf:predicate"))]
    elif fault == "ambiguous-object":
        qs.append(ox.Quad(r, N("rdf:object"), L("An extra object"), g))
    else:
        fields = {q.predicate: q.object for q in qs if q.subject == r}
        qs.append(ox.Quad(fields[N("rdf:subject")], fields[N("rdf:predicate")],
                          fields[N("rdf:object")], g))
    refuses(root, write_graph(root, qs))


def test_incoming_pending_conflicts_with_caller_live_in_unrelated_graph(built):
    root, pins = built
    r = pending(root)
    fields = {q.predicate: q.object for q in quads(root) if q.subject == r}
    store = caller()
    store.add(ox.Quad(fields[N("rdf:subject")], fields[N("rdf:predicate")],
                      fields[N("rdf:object")], N("https://example.test/unrelated")))
    before = set(store)
    with pytest.raises(legacy.LegacyBuildError, match="awaitingReview SPO"):
        legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
    assert set(store) == before


def test_existing_caller_pending_conflicts_with_incoming_live_literal(built):
    root, pins = built
    fact = next(q for q in quads(root) if q.predicate == N("rdfs:label"))
    store = caller()
    r, g = N("https://example.test/caller-candidate"), N("https://example.test/unrelated")
    for pred, obj in [("rdf:subject", fact.subject), ("rdf:predicate", fact.predicate),
                      ("rdf:object", fact.object)]:
        store.add(ox.Quad(r, N(pred), obj, g))
    store.add(ox.Quad(r, N(legacy._BASE + "profile/reviewStatus"),
                      N(legacy._BASE + "profile/awaitingReview"), g))
    before = set(store)
    with pytest.raises(legacy.LegacyBuildError, match="awaitingReview SPO"):
        legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
    assert set(store) == before


def test_different_caller_content_under_same_legacy_graph_refused(built):
    root, pins = built
    store = caller()
    store.add(ox.Quad(N("https://example.test/other"), N("rdfs:label"), L("Conflict"),
                      N(legacy._GRAPHS["crosswalk"])))
    before = set(store)
    with pytest.raises(legacy.LegacyBuildError, match="different content"):
        legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
    assert set(store) == before


def test_same_bytes_replaced_inode_between_snapshots_refused(built, monkeypatch):
    root, pins = built
    original = legacy._snapshot
    def replaced(path, expected, *, capture):
        if not capture:
            target = root / (legacy._PKG + "metadata/codes.csv")
            temporary = target.with_suffix(".replacement")
            temporary.write_bytes(target.read_bytes())
            temporary.replace(target)
        return original(path, expected, capture=capture)
    monkeypatch.setattr(legacy, "_snapshot", replaced)
    store = caller()
    before = set(store)
    with pytest.raises(legacy.LegacyBuildError, match="changed"):
        legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
    assert set(store) == before


def test_blank_nodes_scoped_and_repeat_stable(built):
    root, pins = built
    qs = quads(root)
    qs.append(ox.Quad(ox.BlankNode("source"), N("rdfs:label"), L("Source blank"),
                      N(legacy._GRAPHS["metadata"])))
    pins = write_graph(root, qs)
    store = caller()
    legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
    blanks = {q.subject for q in store if isinstance(q.subject, ox.BlankNode)}
    assert blanks and ox.BlankNode("source") not in blanks
    before = set(store)
    legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
    assert set(store) == before


@pytest.mark.parametrize("relation", ["skos:exactMatch", "smn:populationOf"])
def test_unmarked_live_legacy_identity_bridge_refused(built, relation):
    root, _ = built
    qs = quads(root)
    s, o, g = N("https://example.test/source-id"), N("https://example.test/cu"), N(legacy._GRAPHS["identity"])
    source_type = "smn:Population" if relation == "smn:populationOf" else "gcdfo:ConservationUnit"
    qs += [ox.Quad(s, N("rdf:type"), N(source_type), g),
           ox.Quad(o, N("rdf:type"), N("gcdfo:ConservationUnit"), g),
           ox.Quad(s, N(relation), o, g)]
    refuses(root, write_graph(root, qs))


@pytest.mark.parametrize("relation", ["skos:exactMatch", "skos:closeMatch",
    "skos:broadMatch", "skos:narrowMatch", "smn:populationOf"])
@pytest.mark.parametrize("typing", ["none", "source-only", "target-only"])
def test_native_identity_profiles_cannot_evade_guard_by_removing_types(built, relation, typing):
    root, _ = built
    target = pending(root)
    qs = [q for q in quads(root) if q.subject != target]
    kind = "population" if relation == "smn:populationOf" else "cu"
    s, o = N(legacy._BASE + "id/" + kind + "/source"), N(legacy._BASE + "id/cu/proposed")
    if typing == "source-only":
        qs.append(ox.Quad(s, N("rdf:type"), N("smn:Population" if kind == "population"
                     else "gcdfo:ConservationUnit"), N(legacy._GRAPHS["metadata"])))
    elif typing == "target-only":
        qs.append(ox.Quad(o, N("rdf:type"), N("gcdfo:ConservationUnit"),
                         N(legacy._GRAPHS["provenance"])))
    qs.append(ox.Quad(s, N(relation), o, N(legacy._GRAPHS["crosswalk"])))
    refuses(root, write_graph(root, qs))


def test_population_of_profile_fails_closed_even_with_unknown_endpoint_iris(built):
    root, _ = built
    qs = quads(root) + [ox.Quad(N("https://example.test/source"), N("smn:populationOf"),
              N("https://example.test/target"), N(legacy._GRAPHS["mappings"]))]
    refuses(root, write_graph(root, qs))


@pytest.mark.parametrize("source", ["code/nuseds/estimate-classification/source",
    "scheme/estimate-classification/source-code", "dataset/source/table/main/column/cu"])
def test_nonidentity_source_code_skos_is_preserved(built, source):
    root, _ = built
    q = ox.Quad(N(legacy._BASE + source), N("skos:exactMatch"), N("smn:SalmonIndividual"),
                N(legacy._GRAPHS["mappings"]))
    pins = write_graph(root, quads(root) + [q])
    assert legacy.is_legacy_nuseds_build(root, expected_files=pins)
    store = caller()
    legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
    assert q in store


def test_untyped_native_pending_identity_is_counted_without_assertion(built):
    root, _ = built
    target = pending(root)
    qs = [q for q in quads(root) if not (q.subject == target and q.predicate == N("rdf:object"))]
    qs.append(ox.Quad(target, N("rdf:object"), N(legacy._BASE + "id/cu/proposed"),
                      N(legacy._GRAPHS["crosswalk"])))
    pins = write_graph(root, qs)
    store = caller()
    report = legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
    assert report["total_pending_targets"] == report["scoped_identity_candidates"] == 1
    assert not any(q.predicate == N("skos:exactMatch") for q in store)


@pytest.mark.parametrize("relation", ["skos:exactMatch", "skos:closeMatch",
    "skos:broadMatch", "skos:narrowMatch", "owl:sameAs"])
@pytest.mark.parametrize("kind", ["cu", "population"])
@pytest.mark.parametrize("known_end", ["subject", "object"])
def test_one_native_identity_endpoint_cannot_link_live_to_foreign_id(built, relation, kind, known_end):
    root, _ = built
    target = pending(root)
    qs = [q for q in quads(root) if q.subject != target]
    native = N(legacy._BASE + "id/" + kind + "/source")
    foreign = N("https://foreign.example.test/untyped-id")
    s, o = (native, foreign) if known_end == "subject" else (foreign, native)
    qs.append(ox.Quad(s, N(relation), o, N(legacy._GRAPHS["mappings"])))
    refuses(root, write_graph(root, qs))


@pytest.mark.parametrize("relation", ["skos:closeMatch", "owl:sameAs"])
@pytest.mark.parametrize("kind", ["gcdfo:ConservationUnit", "smn:Population"])
def test_one_typed_identity_endpoint_outside_native_namespace_is_protected(built, relation, kind):
    root, _ = built
    qs = quads(root)
    s, o = N("https://source.example.test/typed-id"), N("https://foreign.example.test/untyped-id")
    qs.append(ox.Quad(s, N("rdf:type"), N(kind), N(legacy._GRAPHS["provenance"])))
    qs.append(ox.Quad(s, N(relation), o, N(legacy._GRAPHS["crosswalk"])))
    refuses(root, write_graph(root, qs))


def test_nonidentity_same_as_preserves_real_source_doi_self_reference(built):
    root, _ = built
    doi = N(legacy._SOURCE)
    same = ox.Quad(doi, N("owl:sameAs"), doi, N(legacy._GRAPHS["metadata"]))
    code = ox.Quad(N(legacy._BASE + "code/source/one"), N("skos:exactMatch"),
                  N("smn:SalmonIndividual"), N(legacy._GRAPHS["mappings"]))
    pins = write_graph(root, quads(root) + [same, code])
    assert legacy.is_legacy_nuseds_build(root, expected_files=pins)
    store = caller()
    legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
    assert same in store and code in store


@pytest.mark.parametrize("fault", [None, "literal-reifies", "conflicting-encodings"])
def test_rdf12_pending_encoding_and_conflicts(built, fault):
    root, _ = built
    r = pending(root)
    qs = quads(root)
    fields = {q.predicate: q.object for q in qs if q.subject == r}
    triple = ox.Triple(fields[N("rdf:subject")], fields[N("rdf:predicate")], fields[N("rdf:object")])
    if fault != "conflicting-encodings":
        qs = [q for q in qs if not (q.subject == r and q.predicate in
              {N("rdf:subject"), N("rdf:predicate"), N("rdf:object")})]
    value = L("not a triple") if fault == "literal-reifies" else triple
    if fault == "conflicting-encodings":
        value = ox.Triple(triple.subject, triple.predicate, L("Different candidate"))
    qs.append(ox.Quad(r, N("rdf:reifies"), value, N(legacy._GRAPHS["crosswalk"])))
    pins = write_graph(root, qs)
    if fault:
        refuses(root, pins)
    else:
        store = caller()
        report = legacy.load_legacy_nuseds_build(store, root, expected_files=pins)
        assert report["total_pending_targets"] == 1
        assert not any(q.subject == triple.subject and q.predicate == triple.predicate
                       and q.object == triple.object for q in store)


def test_literal_text_equal_to_an_iri_is_not_false_live_spo(built):
    root, _ = built
    r = pending(root)
    qs = quads(root)
    fields = {q.predicate: q.object for q in qs if q.subject == r}
    iri_text = fields[N("rdf:object")].value
    qs = [q for q in qs if not (q.subject == r and q.predicate == N("rdf:object"))]
    qs.append(ox.Quad(r, N("rdf:object"), L(iri_text), N(legacy._GRAPHS["crosswalk"])))
    pins = write_graph(root, qs)
    store = caller()
    store.add(ox.Quad(fields[N("rdf:subject")], fields[N("rdf:predicate")], N(iri_text),
                      N("https://example.test/caller")))
    legacy.load_legacy_nuseds_build(store, root, expected_files=pins)


@pytest.mark.parametrize("fault", ["bytes", "missing-key", "key-type"])
def test_malformed_parquet_or_join_schema_refused(built, fault):
    root, _ = built
    path = root / legacy._PARQUET
    if fault == "bytes":
        path.write_bytes(b"not parquet")
    else:
        table = pq.read_table(path)
        if fault == "missing-key":
            table = table.drop(["cu_iri"])
        else:
            at = table.schema.get_field_index("cu_iri")
            table = table.set_column(at, "cu_iri", pa.array([1, 2], type=pa.int64()))
        pq.write_table(table, path)
    refuses(root, seal(root))


@pytest.mark.parametrize("fault", ["header", "numeric", "extra-cell"])
def test_malformed_aggregate_csv_refused(built, fault):
    root, _ = built
    path = root / legacy._CUBE
    text = path.read_text()
    if fault == "header": text = text.replace("spawner_abundance", "unknown_measure", 1)
    elif fault == "numeric": text = text.replace("3.75", "NaN")
    else: text = text.rstrip("\n") + ",unexpected\n"
    path.write_text(text)
    refuses(root, seal(root))


@pytest.mark.parametrize("fault", ["missing", "duplicate-value", "wrong-type"])
def test_legacy_two_measure_grain_cannot_be_silently_changed(built, fault):
    root, _ = built
    qs = quads(root)
    measure = N(legacy._BASE + "def/spawnerAbundance")
    original = next(q for q in qs if q.predicate == measure)
    if fault == "missing":
        qs.remove(original)
    else:
        if fault == "wrong-type":
            qs.remove(original)
        qs.append(ox.Quad(original.subject, measure,
            L("Unresolved") if fault == "wrong-type" else L(4.25), original.graph_name))
    refuses(root, write_graph(root, qs))


def test_actual_reviewed_build4_default_pins_if_explicitly_supplied():
    location = os.environ.get("SALMONGRAPH_T1_BUILD_DIR")
    if not location:
        pytest.skip("Private actual build validation requires explicit local path")
    root = Path(location)
    before = {name: digest(root / name) for name in legacy.DEFAULT_EXPECTED_FILES}
    assert legacy.is_legacy_nuseds_build(root)
    store = caller()
    report = legacy.load_legacy_nuseds_build(store, root)
    assert report["parquet_rows"] == 315501 and report["aggregate_observations"] == 26141
    assert report["quads"] == 397915 and report["total_pending_targets"] == 7342
    assert report["scoped_identity_candidates"] == 7334
    first = set(store)
    assert legacy.load_legacy_nuseds_build(store, root) == report
    assert set(store) == first and len(store) == 397916
    assert {name: digest(root / name) for name in legacy.DEFAULT_EXPECTED_FILES} == before
