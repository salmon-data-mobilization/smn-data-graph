"""Connected discovery over an actual disposable store; all science is fictional."""

import gc
import hashlib
import json
import socket
import time
import tracemalloc

import pyoxigraph as ox
import pytest

from salmongraph import discovery, provenance, review
from salmongraph.serve.sparql_server import query
from salmongraph.graph import GraphBuilder, L, N


B = "https://example.test/fictional-discovery/"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("discovery must remain offline")
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    yield
    assert attempts == []


def inventory(path):
    return {str(p.relative_to(path)): (p.stat().st_mode, p.stat().st_size,
            p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in path.rglob("*") if p.is_file()}


@pytest.fixture
def stored(tmp_path, request):
    options = getattr(request, "param", {})
    b = GraphBuilder()
    for slug in ("project", "other", "pending", "same-name", "human", "evidence-only"):
        dataset, table, schema, column, obs = (B + slug + suffix for suffix in
            ("/dataset", "/table", "/schema", "/column", "/observation"))
        graph = B + slug + "/graph"
        b.type(dataset, "dcat:Dataset", graph)
        b.add(dataset, "pav:version", L("fictional-v1"), graph)
        b.add(dataset, "dcterms:source", B + slug + "/source", graph)
        b.add(dataset, "dcterms:hasPart", table, graph)
        b.add(table, "csvw:tableSchema", schema, graph)
        b.add(schema, "csvw:column", column, graph)
        b.type(column, "csvw:Column", graph)
        b.add(column, "csvw:name", L("temperature"), graph)
        b.add(column, "qudt:unit", B + "unit/fictional", graph)
        b.add(obs, "qb:dataSet", dataset, graph)
        population = B + ("population/authority-b" if slug == "same-name" else "population/authority-a")
        if slug == "other":
            population_slot = B + "other/population-column"
            b.type(population_slot, "qb:DimensionProperty", graph)
            b.type(population_slot, "csvw:Column", graph)
            b.add(schema, "csvw:column", population_slot, graph)
        else:
            population_slot = "prov:wasDerivedFrom" if slug == "evidence-only" else "sosa:hasFeatureOfInterest"
        b.add(obs, population_slot, population, graph)
        if slug == "pending":
            provenance.mark_statement(b, B + "proposal/measurement", column,
                "qb:concept", B + "meaning/temperature", graph=graph,
                agent=B + "fictional-agent", activity=B + "fictional-run",
                evidence="Fictional proposal only", confidence="high", criticality="critical")
            # An incorrect non-critical agent mark cannot make a method live.
            provenance.mark_statement(b, B + "proposal/agent-method", column,
                "sosa:usedProcedure", B + "procedure/fictional", graph=graph,
                agent=B + "fictional-agent", activity=B + "fictional-run",
                evidence="Fictional agent proposal", confidence="high", criticality="non-critical",
                assert_triple=False)
        elif slug == "human":
            provenance.mark_statement(b, B + "proposal/human-method", column,
                "sosa:usedProcedure", B + "procedure/fictional", graph=graph,
                agent=B + "fictional-agent", activity=B + "fictional-run",
                evidence="Fictional decision fixture", confidence="high", criticality="critical")
        else:
            meaning = B + ("meaning/different-authority" if slug == "same-name" else "meaning/temperature")
            reifier = B + slug + "/source-statement"
            b.reify(reifier, column, "qb:concept", meaning, graph, assert_triple=True)
            b.add(reifier, "dcterms:source", B + slug + "/source", graph)
            b.add(column, "sosa:usedProcedure", B + "procedure/fictional", graph)
    b.type(B + "population/authority-a", "smn:Population", B + "identity/graph")
    b.type(B + "population/authority-b", "smn:Population", B + "identity/graph")
    # Equal labels are deliberately different authority IRIs.
    for node in (B + "meaning/temperature", B + "meaning/different-authority"):
        b.add(node, "rdfs:label", L("temperature"), B + "identity/graph")
    if options.get("cross_graph_floor"):
        graph, dataset, obs, predicate = (B + "cross-floor/" + name for name in
            ("graph", "dataset", "observation", "population-slot"))
        b.type(dataset, "dcat:Dataset", graph)
        b.add(obs, "qb:dataSet", dataset, graph)
        b.type(predicate, "qb:DimensionProperty", graph)
        b.add(predicate, "rdfs:subPropertyOf", N("smn:populationOf"), B + "floor/graph")
        provenance.mark_statement(b, B + "proposal/cross-floor", obs, predicate,
            B + "population/authority-a", graph=graph, agent=B + "fictional-agent",
            activity=B + "fictional-run", evidence="Fictional cross-graph floor",
            confidence="high", criticality="non-critical", assert_triple=False)
    for i in range(options.get("noise_quads", 0)):
        b.add(B + f"unrelated/{i}", "rdfs:label", L(f"Fictional unrelated row {i}"), B + "noise/graph")
    if options.get("proof_quads"):
        b.add(B + "other/column", "prov:wasDerivedFrom", B + "other/proof", B + "other/graph")
        for i in range(options["proof_quads"]):
            b.add(B + "other/proof", "prov:value", L(f"Fictional proof item {i}"), B + "other/graph")
    if options.get("nested_proof"):
        first, second = ox.BlankNode("fictional-proof-one"), ox.BlankNode("fictional-proof-two")
        b.add(B + "other/source-statement", "prov:wasDerivedFrom", first, B + "other/graph")
        b.add(first, "prov:wasDerivedFrom", second, B + "other/graph")
        b.add(second, "prov:wasDerivedFrom", first, B + "other/graph")
        b.add(second, "prov:value", L("Fictional nested source evidence"), B + "other/graph")
    # Only a fictional test decision; never a shared or real research decision.
    ledger = tmp_path / "fictional-decisions.csv"
    review.record_decision(b.quads, B + "proposal/human-method", "humanAccepted",
        reviewer="Fictional Test Reviewer", date="2026-10-27", path=ledger)
    application = review.apply_ledger(b.quads, review.load_decisions(ledger),
                                     review_graph=B + "review/graph")
    # Pass the existing review gate before preparing the disposable query store.
    admitted = review.view_quads(application.quads)
    path = tmp_path / "admitted-store"
    store = ox.Store(path)
    store.extend(admitted); store.flush(); del store; gc.collect()
    before = inventory(path)
    yield path
    gc.collect()
    assert inventory(path) == before


def test_actual_other_dataset_three_families_and_why_match(stored):
    result = discovery.discover(stored, project_datasets=[B + "project/dataset"])
    assert result["has_more"] is False and result["scan_truncated"] is False
    paths = result["paths"]
    assert {p["family"] for p in paths} == {"measurement", "procedure", "population"}
    assert all(p["dataset"] != B + "project/dataset" for p in paths)
    measurement = next(p for p in paths if p["family"] == "measurement" and p["dataset"] == B + "other/dataset")
    assert measurement["shared_iri"] == B + "meaning/temperature"
    assert measurement["candidate"]["authority"] == "source_stated"
    assert measurement["candidate"]["graphs"] == [B + "other/graph"]
    assert measurement["candidate"]["evidence"]
    assert len(measurement["candidate"]["membership"]) == 3
    assert measurement["candidate_source"]["versions"] == ["fictional-v1"]
    assert all(p["path_state"] == "asserted" for p in paths)
    human = next(p for p in paths if p["dataset"] == B + "human/dataset" and p["family"] == "procedure")
    assert human["candidate"]["authority"] == "human_accepted"
    unmarked = next(p for p in paths if p["dataset"] == B + "other/dataset" and p["family"] == "procedure")
    assert unmarked["candidate"]["authority"] == "unmarked"


def test_pending_stays_separate_and_agent_is_not_human_acceptance(stored):
    accepted = discovery.discover(stored, project_datasets=[B + "project/dataset"],
                                 families=["measurement", "procedure"])
    assert not any(p["dataset"] == B + "pending/dataset" for p in accepted["paths"])
    all_paths = discovery.discover(stored, project_datasets=[B + "project/dataset"],
                                  include_pending=True)
    pending = [p for p in all_paths["paths"] if p["path_state"] == "awaiting_review"]
    assert {p["family"] for p in pending} == {"measurement", "procedure"}
    agent = next(p for p in pending if p["family"] == "procedure")
    assert agent["candidate"]["recorded_review_status"] == ["agentAccepted"]
    assert agent["candidate"]["asserted"] is False
    assert agent["candidate"]["authority"] == "awaiting_review"
    for predicate in ("qb:concept", "sosa:usedProcedure"):
        assert query(stored, f"ASK {{ <{B}pending/column> {N(predicate)} ?o }}")["boolean"] is False


def test_limits_filters_and_no_name_equivalence(stored):
    result = discovery.discover(stored, project_datasets=[B + "project/dataset"], limit=1)
    assert len(result["paths"]) == 1 and result["has_more"] is True
    measurement = discovery.discover(stored, project_datasets=[B + "project/dataset"],
                                    families=["measurement"])
    assert {p["dataset"] for p in measurement["paths"]} == {B + "other/dataset", B + "evidence-only/dataset"}
    filtered = discovery.discover(stored, project_datasets=[B + "project/dataset"],
                                 graphs=[B + "project/graph"])
    assert filtered["paths"] == []


def test_population_requires_exact_identity_and_an_actual_population_slot(stored):
    result = discovery.discover(stored, project_datasets=[B + "project/dataset"], families=["population"])
    assert {p["dataset"] for p in result["paths"]} == {
        B + slug + "/dataset" for slug in ("other", "pending", "human")}
    assert all(p["candidate"]["identity_types"] == [N("smn:Population").value] for p in result["paths"])
    assert next(p for p in result["paths"] if p["dataset"] == B + "other/dataset")["candidate"]["predicate"] == B + "other/population-column"


@pytest.mark.parametrize("changes", [{"families": ["unknown"]}, {"limit": True},
    {"limit": 0}, {"limit": 101}, {"graphs": ["not an IRI"]},
    {"project_datasets": ['https://example.test/x> SERVICE <https://evil.test>']},
    {"include_pending": "yes"}, {"project_datasets": []}])
def test_invalid_or_network_shaped_inputs_refused_before_store_open(tmp_path, changes):
    args = {"project_datasets": [B + "project/dataset"], **changes}
    with pytest.raises(ValueError):
        discovery.discover(tmp_path / "absent", **args)


def test_query_is_actual_local_engine_and_unknown_dataset_has_no_fallback(stored, monkeypatch):
    observed = []
    original = discovery._Reader.find
    def find(self, subject=None, predicate=None, obj=None, **kwargs):
        observed.append((subject, predicate, obj))
        yield from original(self, subject, predicate, obj, **kwargs)
    monkeypatch.setattr(discovery._Reader, "find", find)
    result = discovery.discover(stored, project_datasets=[B + "absent/dataset"])
    assert result["paths"] == [] and observed
    assert result["query_engine"] == "pyoxigraph-indexed-patterns"
    assert result["review_materialization"] == "global_O(total_store)"
    assert all(any(term is not None for term in pattern) for pattern in observed)


def test_scan_cap_reports_partial_without_paths_from_incomplete_evidence(stored, monkeypatch):
    monkeypatch.setattr(discovery, "MAX_SCAN_QUADS", 1)
    result = discovery.discover(stored, project_datasets=[B + "project/dataset"])
    assert result["scan_truncated"] is True and result["has_more"] is True
    assert result["scanned_quads"] == result["scan_limit"] == 1
    assert result["paths"] == []


@pytest.mark.parametrize("stored", [{"noise_quads": 0}, {"noise_quads": 50_020}], indirect=True)
def test_large_admitted_store_loads_only_relevant_discovery_evidence(stored):
    tracemalloc.start()
    started = time.perf_counter()
    try:
        result = discovery.discover(stored, project_datasets=[B + "project/dataset"])
        seconds, (_, python_peak) = time.perf_counter() - started, tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert {path["family"] for path in result["paths"]} == set(discovery.FAMILIES)
    assert any(path["dataset"] == B + "other/dataset" for path in result["paths"])
    assert result["scan_truncated"] is False
    assert result["scanned_quads"] < 1_000
    # Measured whole-call Python allocations INCLUDE the intentionally global
    # review index; PyOxigraph native allocations are outside tracemalloc.
    print(json.dumps({"benchmark": "fictional-discovery/1", "reviewed_quads": result["reviewed_quads"],
        "targeted_distinct_quad_reads": result["scanned_quads"], "evidence_quads": result["evidence_quads"],
        "indexed_patterns": result["read_pattern_count"], "paths": len(result["paths"]),
        "seconds": seconds, "python_peak_bytes": python_peak, "native_memory_measured": False}))


@pytest.mark.parametrize("stored", [{"cross_graph_floor": True}], indirect=True)
def test_display_filter_cannot_hide_a_cross_graph_criticality_floor(stored):
    graphs = [B + name + "/graph" for name in ("project", "cross-floor", "identity")]
    result = discovery.discover(stored, project_datasets=[B + "project/dataset"],
        graphs=graphs, families=["population"], include_pending=True)
    path = next(path for path in result["paths"] if path["dataset"] == B + "cross-floor/dataset")
    assert path["path_state"] == path["candidate"]["authority"] == "awaiting_review"
    assert path["candidate"]["recorded_review_status"] == ["agentAccepted"]
    assert path["candidate"]["asserted"] is False
    assert query(stored, f"ASK {{ <{B}cross-floor/observation> <{B}cross-floor/population-slot> ?o }}")["boolean"] is False


def test_display_graphs_do_not_strip_actual_human_review_proof(stored):
    result = discovery.discover(stored, project_datasets=[B + "project/dataset"],
        graphs=[B + "project/graph", B + "human/graph"], families=["procedure"])
    path = next(path for path in result["paths"] if path["dataset"] == B + "human/dataset")
    assert path["candidate"]["authority"] == "human_accepted"
    assert path["candidate"]["recorded_review_status"] == ["humanAccepted"]
    assert path["candidate"]["graphs"] == [B + "human/graph"]


@pytest.mark.parametrize("stored", [{"proof_quads": 1_000}], indirect=True)
def test_complete_proof_budget_refuses_instead_of_cutting_expanded_evidence(stored, monkeypatch):
    monkeypatch.setattr(discovery, "MAX_SCAN_QUADS", 400)
    result = discovery.discover(stored, project_datasets=[B + "project/dataset"])
    assert result["query_status"] == "partial_evidence_refused"
    assert result["paths"] == [] and result["evidence_quads"] == 0
    assert result["scan_truncated"] is result["has_more"] is True
    assert result["scanned_quads"] == result["scan_limit"] == 400
    assert result["partial_reason"] == "targeted_quad_limit"


def test_indexed_pattern_budget_is_separate_from_unique_quad_budget(stored, monkeypatch):
    monkeypatch.setattr(discovery, "MAX_READ_PATTERNS", 1)
    result = discovery.discover(stored, project_datasets=[B + "project/dataset"])
    assert result["query_status"] == "partial_evidence_refused"
    assert result["partial_reason"] == "targeted_pattern_limit"
    assert result["paths"] == [] and result["scan_truncated"] is True
    assert result["read_pattern_count"] == result["read_pattern_limit"] == 1


@pytest.mark.parametrize("stored", [{"nested_proof": True}], indirect=True)
def test_complete_nested_source_evidence_is_visible_without_cycle_inference(stored):
    result = discovery.discover(stored, project_datasets=[B + "project/dataset"], families=["measurement"])
    path = next(path for path in result["paths"] if path["dataset"] == B + "other/dataset")
    assert path["candidate"]["authority"] == "source_stated"
    assert '"Fictional nested source evidence"' in path["candidate"]["evidence"]
