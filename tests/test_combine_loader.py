"""Verified artifact loading, using genuine tiny SDK builds and controlled faults."""

from __future__ import annotations

import hashlib
import csv
import json
from pathlib import Path
import socket

import pyarrow as pa
import pyarrow.parquet as pq
import pyoxigraph as ox
import pytest

from test_build import document, run, vocab  # genuine SDK/SHACL fixture, not a loader double
from salmongraph import combine, config, iri, provenance, review
from salmongraph.executor import AgentRun
from salmongraph.graph import GraphBuilder, L, N, RDF_REIFIES
from salmongraph.io import det


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("loader tests must be offline")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    yield
    assert attempts == []


@pytest.fixture
def built(tmp_path, vocab):
    _, _, result = run(tmp_path, vocab)
    return result.out_dir


def manifest(root):
    return json.loads((root / "manifest.json").read_text())


def save(root, value):
    det.write_json(root / "manifest.json", value)


def refresh(root):
    value = manifest(root)
    for item in value["files"]:
        payload = (root / item["path"]).read_bytes()
        item.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    save(root, value)


def caller():
    store = ox.Store()
    store.add(ox.Quad(N("https://example.test/prior"), N("rdfs:label"), L("Preserve caller fact"), ox.DefaultGraph()))
    return store


def refuses(root):
    store = caller()
    prior = set(store)
    with pytest.raises(ValueError):
        combine.load_dataset_build(store, root)
    assert set(store) == prior


@pytest.mark.parametrize("version", ["2026.10.27", "v 1/2", "..", "/absolute", "a%b"])
def test_corpus_path_uses_reserved_corpus_location_and_encoded_version(version):
    assert combine.corpus_build_dir(version) == combine.CORPUS_BUILD_DIR / iri.segment(version)
    assert combine.corpus_build_dir(version).parent == combine.CORPUS_BUILD_DIR


@pytest.mark.parametrize("version", [None, "", True, float("nan")])
def test_corpus_path_refuses_missing_or_boolean_version(version):
    with pytest.raises(ValueError):
        combine.corpus_build_dir(version)


def test_valid_build_load_return_manifest_and_repeat_are_idempotent(built):
    store = caller()
    original = set(store)
    expected = manifest(built)
    cfg = config.current()
    assert combine.load_dataset_build(store, built) == expected
    assert len(store) == 1 + sum(expected["quad_counts"].values())
    first = set(store)
    assert original <= first and combine.load_dataset_build(store, built) == expected
    assert set(store) == first and config.current() == cfg
    assert expected["publication_ready"] is False


@pytest.mark.parametrize("mutation", ["unknown-format", "legacy", "extra-key", "self-hash", "wrong-count", "config", "dataset", "date", "bool-count", "duplicate-file"])
def test_invalid_manifest_preserves_caller(built, mutation):
    value = manifest(built)
    if mutation == "unknown-format": value["schema"] = "salmongraph-build/2"
    elif mutation == "legacy": value.pop("configuration")
    elif mutation == "extra-key": value["adapter"] = "execute-me"
    elif mutation == "self-hash": value["manifest_hash"] = "pretend-self-checksum"
    elif mutation == "wrong-count": value["quad_counts"][next(iter(value["quad_counts"]))] += 1
    elif mutation == "config": value["configuration"]["base"] = "https://example.test/wrong/"
    elif mutation == "dataset": value["dataset_iri"] = "https://example.test/other-dataset"
    elif mutation == "date": value["build_date"] = "2026-02-30"
    elif mutation == "bool-count": value["observations"] = True
    else: value["files"].append(value["files"][0])
    save(built, value)
    refuses(built)


@pytest.mark.parametrize("payload", [b"{", b'{"schema":"x","schema":"y"}', b'{"x":NaN}'])
def test_malformed_manifest_json_fails_closed(built, payload):
    (built / "manifest.json").write_bytes(payload)
    refuses(built)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "sdp//double", "sdp/./dot", "sdp/../escape", "sdp\\escape", "C:drive", "manifest.json"])
def test_unsafe_inventory_paths_are_not_followed(built, name):
    value = manifest(built)
    value["files"][0]["path"] = name
    save(built, value)
    refuses(built)


@pytest.mark.parametrize("kind", ["changed-bytes", "extra-file", "empty-directory", "missing-file", "manifest-link", "file-link", "directory-link", "fifo"])
def test_file_set_hash_and_containment_faults_preserve_caller(built, tmp_path, kind):
    if kind == "changed-bytes": (built / "report.md").write_text("Changed without a new hash")
    elif kind == "extra-file": (built / "untracked.txt").write_text("Unknown")
    elif kind == "empty-directory": (built / "untracked").mkdir()
    elif kind == "missing-file": (built / "report.md").unlink()
    elif kind == "fifo": __import__("os").mkfifo(built / "pipe")
    else:
        source = built / ("manifest.json" if kind == "manifest-link" else "report.md" if kind == "file-link" else "sdp")
        target = tmp_path / "outside"
        source.rename(target)
        source.symlink_to(target, target_is_directory=kind == "directory-link")
    refuses(built)


def test_symlink_build_root_is_refused(built, tmp_path):
    path = tmp_path / "linked-build"
    path.symlink_to(built, target_is_directory=True)
    refuses(path)


@pytest.mark.parametrize("fault", ["syntax", "default-graph", "blank-graph", "foreign-graph", "dataset-identity"])
def test_rdf_faults_with_updated_hash_still_preserve_caller(built, fault):
    path = built / "dataset.trig"
    if fault == "syntax": path.write_text('GRAPH <https://example.test/g> { <broken>')
    elif fault == "default-graph": path.write_bytes(path.read_bytes() + b'\n<https://example.test/s> <https://example.test/p> "x" .\n')
    elif fault == "blank-graph": path.write_bytes(path.read_bytes() + b'\n_:graph { <https://example.test/s> <https://example.test/p> "x" . }\n')
    elif fault == "foreign-graph": path.write_bytes(path.read_bytes() + b'\n<https://example.test/g> { <https://example.test/s> <https://example.test/p> "x" . }\n')
    else:
        value = manifest(built)
        original = N(value["dataset_iri"])
        quads = [ox.Quad(N("https://example.test/replaced") if q.subject == original else q.subject,
                         q.predicate, q.object, q.graph_name)
                 for q in ox.parse(input=path.read_bytes(), format=ox.RdfFormat.TRIG, rename_blank_nodes=False)]
        path.write_bytes(det.trig_bytes(quads))
    refresh(built)
    refuses(built)


def test_report_and_parquet_counts_are_actually_read(built):
    path = built / "report.json"
    report = json.loads(path.read_text())
    report["observations"] += 1
    det.write_json(path, report)
    refresh(built)
    refuses(built)
    report["observations"] -= 1
    det.write_json(path, report)
    parquet = built / "observations.parquet"
    table = pq.read_table(parquet)
    pq.write_table(table.slice(0, 0), parquet)
    refresh(built)
    refuses(built)


def test_input_edit_during_parquet_read_is_detected_before_caller_transaction(built, monkeypatch):
    original = pq.ParquetFile
    def changing_input(*args, **kwargs):
        result = original(*args, **kwargs)
        with (built / "report.md").open("a") as stream:
            stream.write("Concurrent change")
        return result
    monkeypatch.setattr(pq, "ParquetFile", changing_input)
    refuses(built)


def test_recorded_alternate_configuration_does_not_change_callers_context(tmp_path, vocab):
    from test_build import prepare
    from salmongraph.executor import build_dataset
    cfg = config.Config(base="https://example.test/other/", profile_base="https://example.test/review/", sdpv="https://example.test/sdp/")
    with config.override(cfg):
        spec, raw = prepare(tmp_path)
    result = build_dataset(spec, build_date="2026-10-24", vocab=vocab(cfg), raw_dir=raw, out_dir=tmp_path / "alternate")
    before = config.current()
    store = caller()
    loaded = combine.load_dataset_build(store, result.out_dir)
    assert loaded["configuration"] == {"base": cfg.base, "profile_base": cfg.profile_base, "sdpv": cfg.sdpv}
    assert config.current() == before
    assert any(q.subject == N(iri.dataset(spec.slug, spec.version, cfg=cfg)) for q in store)


@pytest.mark.parametrize("encoding", ["rdf12", "rdf11"])
def test_pending_candidates_stay_unasserted_and_blank_evidence_reloads_once(tmp_path, vocab, encoding):
    data = document()
    data["tables"][0]["columns"][3]["mark"] = {"aspect": "measure-counts", "confidence": "high", "evidence": ["Fictional pending source interpretation."]}
    _, _, result = run(tmp_path, vocab, data, run=AgentRun("loader-fixture", "actual-fixture-model", "2026-10-24"))
    root = result.out_dir
    if encoding == "rdf11":
        quads = []
        for q in ox.parse(input=(root / "dataset.trig").read_bytes(), format=ox.RdfFormat.TRIG, rename_blank_nodes=False):
            if q.predicate.value == RDF_REIFIES:
                for predicate, obj in (("rdf:type", N("rdf:Statement")), ("rdf:subject", q.object.subject),
                                       ("rdf:predicate", q.object.predicate), ("rdf:object", q.object.object)):
                    quads.append(ox.Quad(q.subject, N(predicate), obj, q.graph_name))
            else: quads.append(q)
        det.write_bytes(root / "dataset.trig", det.trig_bytes(quads))
        value, report = manifest(root), json.loads((root / "report.json").read_text())
        counts = {}
        for q in quads: counts[q.graph_name.value] = counts.get(q.graph_name.value, 0) + 1
        value["quad_counts"] = report["quad_counts"] = counts
        report["quads"] = len(quads)
        det.write_json(root / "report.json", report)
        save(root, value)
        refresh(root)
    store = caller()
    combine.load_dataset_build(store, root)
    triples = [q.object for q in store if q.predicate.value == RDF_REIFIES]
    if encoding == "rdf11":
        targets = {q.subject for q in store if q.predicate == N("rdf:type") and q.object == N("rdf:Statement")}
        triples = [ox.Triple(next(store.quads_for_pattern(r, N("rdf:subject"), None, None)).object,
                            next(store.quads_for_pattern(r, N("rdf:predicate"), None, None)).object,
                            next(store.quads_for_pattern(r, N("rdf:object"), None, None)).object) for r in targets]
    assert triples and any(isinstance(q.subject, ox.BlankNode) for q in store)
    assert all(not any(store.quads_for_pattern(t.subject, t.predicate, t.object, None)) for t in triples)
    before = set(store)
    combine.load_dataset_build(store, root)
    assert set(store) == before


def test_existing_different_release_graph_is_never_silently_extended(built):
    value = manifest(built)
    store = caller()
    store.add(ox.Quad(N("https://example.test/conflict"), N("rdfs:label"), L("Existing different graph"), N(next(iter(value["quad_counts"])))))
    before = set(store)
    with pytest.raises(ValueError, match="different content"):
        combine.load_dataset_build(store, built)
    assert set(store) == before


def test_genuine_metadata_only_build_does_not_require_five_nonempty_graphs(tmp_path, vocab):
    data = document()
    data["observations"] = []
    _, _, result = run(tmp_path, vocab, data)
    value = manifest(result.out_dir)
    assert value["observations"] == 0
    assert len(value["quad_counts"]) < 5
    store = caller()
    combine.load_dataset_build(store, result.out_dir)
    assert len(store) == 1 + sum(value["quad_counts"].values())


def test_distinct_releases_cannot_accidentally_share_serialized_blank_labels(tmp_path, vocab):
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    builds = []
    for directory, slug in ((first_dir, "fictional-build"), (second_dir, "other-build")):
        data = document()
        data["slug"] = slug
        data["tables"][0]["columns"][3]["mark"] = {"aspect": "measure-counts", "confidence": "high", "evidence": ["Shared source text, separate release evidence nodes."]}
        _, _, result = run(directory, vocab, data, run=AgentRun("fixture", "actual-fixture-model", "2026-10-24"))
        quads = list(ox.parse(input=(result.out_dir / "dataset.trig").read_bytes(), format=ox.RdfFormat.TRIG, rename_blank_nodes=False))
        original = next(q.subject for q in quads if isinstance(q.subject, ox.BlankNode))
        shared = ox.BlankNode("same-serialized-label")
        quads = [ox.Quad(shared if q.subject == original else q.subject, q.predicate,
                         shared if q.object == original else q.object, q.graph_name) for q in quads]
        det.write_bytes(result.out_dir / "dataset.trig", det.trig_bytes(quads))
        refresh(result.out_dir)
        builds.append(result.out_dir)
    store = caller()
    for build in builds:
        combine.load_dataset_build(store, build)
    evidence_nodes = []
    for build in builds:
        graph = N(next(g for g in manifest(build)["quad_counts"] if g.endswith("/metadata")))
        evidence_nodes.append({q.subject for q in store.quads_for_pattern(None, N("prov:value"), None, graph)})
    assert all(evidence_nodes) and not evidence_nodes[0] & evidence_nodes[1]


def test_read_only_native_store_refuses_final_transaction_without_change(built, tmp_path):
    path = tmp_path / "store"
    prior = next(iter(caller()))
    writable = ox.Store(path)
    writable.add(prior)
    writable.flush()
    del writable
    store = ox.Store.read_only(str(path))
    with pytest.raises(RuntimeError, match="read-write"):
        combine.load_dataset_build(store, built)
    assert set(store) == {prior}


def rdf_quads(root):
    return list(ox.parse(input=(root / "dataset.trig").read_bytes(), format=ox.RdfFormat.TRIG, rename_blank_nodes=False))


def rewrite_rdf(root, quads):
    det.write_bytes(root / "dataset.trig", det.trig_bytes(quads))
    value, report = manifest(root), json.loads((root / "report.json").read_text())
    counts = {}
    for q in quads:
        counts[q.graph_name.value] = counts.get(q.graph_name.value, 0) + 1
    value["quad_counts"] = report["quad_counts"] = counts
    report["quads"] = len(quads)
    det.write_json(root / "report.json", report)
    save(root, value)
    refresh(root)


def legacy(quads):
    output = []
    for q in quads:
        if q.predicate.value == RDF_REIFIES:
            output.extend(ox.Quad(q.subject, N(p), o, q.graph_name) for p, o in (
                ("rdf:type", N("rdf:Statement")), ("rdf:subject", q.object.subject),
                ("rdf:predicate", q.object.predicate), ("rdf:object", q.object.object)))
        else:
            output.append(q)
    return output


def pending_build(tmp_path, vocab):
    data = document()
    data["tables"][0]["columns"][3]["mark"] = {"aspect": "measure-counts", "confidence": "high", "evidence": ["Actual fictional pending source interpretation."]}
    return run(tmp_path, vocab, data, run=AgentRun("loader-review", "actual-fixture-model", "2026-10-24"))[2].out_dir


@pytest.mark.parametrize("encoding", ["rdf12", "rdf11"])
def test_incoming_pending_cannot_join_callers_live_spo_in_another_graph(tmp_path, vocab, encoding):
    root = pending_build(tmp_path, vocab)
    quads = rdf_quads(root)
    triple = next(q.object for q in quads if q.predicate.value == RDF_REIFIES)
    if encoding == "rdf11":
        rewrite_rdf(root, legacy(quads))
    store = caller()
    store.add(ox.Quad(triple.subject, triple.predicate, triple.object, N("https://example.test/unrelated-caller-graph")))
    before = set(store)
    with pytest.raises(ValueError, match="awaitingReview SPO.*combined"):
        combine.load_dataset_build(store, root)
    assert set(store) == before


@pytest.mark.parametrize("encoding", ["rdf12", "rdf11"])
@pytest.mark.parametrize("confidence,criticality", [("high", "critical"), ("low", "non-critical")])
def test_incoming_live_cannot_join_callers_pending_spo(built, encoding, confidence, criticality):
    q = next(q for q in rdf_quads(built) if q.predicate == N("sosa:hasSimpleResult"))
    graph = "https://example.test/caller-review"
    builder = GraphBuilder()
    agent = provenance.ai_agent(builder, "actual-fixture-model", graph=graph)
    activity = provenance.activity_node(builder, iri.activity("agent-run", "caller-fixture"), graph=graph,
                                         label="Recorded fixture run", date="2026-10-24", associated_with=[agent])
    provenance.mark_statement(builder, iri.xwalk("caller", "candidate"), q.subject, q.predicate, q.object,
                              graph=graph, agent=agent, activity=activity, evidence=["Recorded fixture evidence"],
                              confidence=confidence, criticality=criticality, date="2026-10-24")
    store = caller()
    store.extend(legacy(builder.quads) if encoding == "rdf11" else builder.quads)
    before = set(store)
    with pytest.raises(ValueError, match="awaitingReview SPO.*combined"):
        combine.load_dataset_build(store, built)
    assert set(store) == before


def test_rehashed_incoming_internal_pending_live_conflict_is_rejected(tmp_path, vocab):
    root = pending_build(tmp_path, vocab)
    quads = rdf_quads(root)
    reification = next(q for q in quads if q.predicate.value == RDF_REIFIES)
    triple = reification.object
    quads.append(ox.Quad(triple.subject, triple.predicate, triple.object, reification.graph_name))
    rewrite_rdf(root, quads)
    refuses(root)


def test_foreign_current_format_review_profile_fails_closed(built):
    cfg = config.Config(profile_base="https://example.test/foreign-review/")
    builder = GraphBuilder(cfg=cfg)
    graph = "https://example.test/caller-review"
    provenance.mark_statement(builder, iri.xwalk("caller", "foreign", cfg=cfg), "https://example.test/s",
                              "rdfs:label", L("Pending label"), graph=graph,
                              agent=iri.model_agent("fixture", cfg=cfg), activity=iri.activity("agent-run", "fixture", cfg=cfg),
                              evidence=["Recorded source label"], confidence="low", criticality="non-critical")
    store = caller()
    store.extend(builder)
    before = set(store)
    with pytest.raises(ValueError, match="unsupported mixed review profile"):
        combine.load_dataset_build(store, built)
    assert set(store) == before


def test_unrelated_pending_caller_statement_remains_unasserted(built):
    builder = GraphBuilder()
    provenance.mark_statement(builder, iri.xwalk("caller", "unrelated"), "https://example.test/unrelated",
                              "rdfs:label", L("Pending label"), graph="https://example.test/caller-review",
                              agent=iri.model_agent("fixture"), activity=iri.activity("agent-run", "fixture"),
                              evidence=["Recorded source label"], confidence="low", criticality="non-critical")
    store = caller()
    store.extend(builder)
    combine.load_dataset_build(store, built)
    assert not any(store.quads_for_pattern(N("https://example.test/unrelated"), N("rdfs:label"), L("Pending label"), None))


@pytest.mark.parametrize("fault", ["ids-only", "missing-status", "value-int", "year-int64", "measure-large-string", "nullable-key"])
def test_rehashed_parquet_must_match_actual_fixed_writer_fields_and_types(built, fault):
    path = built / "observations.parquet"
    table = pq.read_table(path)
    if fault == "ids-only":
        table = table.select(["obs_iri", "dataset_iri"])
    elif fault == "missing-status":
        table = table.drop(["review_status"])
    else:
        name, dtype = {"value-int": ("value", pa.int32()), "year-int64": ("year", pa.int64()),
                       "measure-large-string": ("measure_iri", pa.large_string()), "nullable-key": ("obs_iri", pa.string())}[fault]
        index = table.schema.get_field_index(name)
        field = pa.field(name, dtype, nullable=True if fault == "nullable-key" else table.schema.field(name).nullable)
        table = table.set_column(index, field, table[name].cast(dtype))
    pq.write_table(table, path)
    refresh(built)
    refuses(built)


def test_blank_pending_target_cannot_disappear_from_the_queue(tmp_path, vocab):
    root = pending_build(tmp_path, vocab)
    quads = rdf_quads(root)
    original = next(q.subject for q in quads if q.predicate.value == RDF_REIFIES)
    blank = ox.BlankNode("unstable-review-target")
    changed = [ox.Quad(blank if q.subject == original else q.subject, q.predicate,
                        blank if q.object == original else q.object, q.graph_name) for q in quads]
    rewrite_rdf(root, changed)
    with (root / "review-queue.csv").open(newline="") as stream:
        rows = [r for r in csv.DictReader(stream) if r["target"] != original.value]
    det.write_csv(root / "review-queue.csv", review.REVIEW_QUEUE_COLUMNS,
                  ([r[name] for name in review.REVIEW_QUEUE_COLUMNS] for r in rows))
    refresh(root)
    store = caller()
    before = set(store)
    with pytest.raises(ValueError, match="review targets must be IRIs"):
        combine.load_dataset_build(store, root)
    assert set(store) == before


def test_genuine_optional_uncertainty_and_dimension_columns_remain_supported(tmp_path, vocab):
    data = document()
    data["tables"][0]["columns"][3]["uncertainty"] = {"standard_error": "se", "cv": "cv", "lower": "lo", "upper": "hi"}
    data["tables"][0]["columns"].extend({"name": name, "role": "attribute", "datatype": "number"} for name in ("se", "cv", "lo", "hi"))
    source = ("stock,period,phase,count,se,cv,lo,hi,flag,date\n"
              "001,2000,NA,0,0.25,0.1,-1,1,true,2000-01-02\n"
              "NA,2001,null,-99,0.5,0.2,-100,-98,false,\n"
              "nan,2002,A,,,,,,true,2002-03-04\n")
    _, _, result = run(tmp_path, vocab, data, csv_text=source)
    store = caller()
    combine.load_dataset_build(store, result.out_dir)
    assert manifest(result.out_dir)["observations"] == 2
