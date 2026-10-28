"""Saved private mapping evidence is not an SDK file or shared acceptance.

The source package fixture is genuine SDK output. The added saved-source rows
and other dataset RDF are explicit fictional trusted-caller evidence, not a
claim that an SDK or repository accepted those scientific relationships.
"""
import copy
import gc
import json
from pathlib import Path
import socket

import pyoxigraph as ox
import pytest

from salmongraph import contribution, discovery, provenance, review
from salmongraph.graph import GraphBuilder, L, N
from salmongraph.native_references import CONTEXT_TYPE, PENDING_TYPE

FIXTURE = Path(__file__).with_name("fixtures") / "fictional-rich-native.json"
B = "https://example.test/saved-source-discovery/"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_a, **_k):
        raise AssertionError("Saved-source discovery is offline")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


def inputs(decision="reviewed-scoped"):
    value = json.loads(FIXTURE.read_text())
    candidate, current = value["candidate"], value["current"]
    native = current["projection"]["identifiers"][0]
    side = {key: native[key] for key in ("nativeKey", "termIri", "termType", "authorityName", "authorityVersion", "vocabularyIri")}
    side["evidence"] = {"citation": "Exact fictional North authority", "sha256": None}
    target = {"nativeKey": "S-7", "termIri": B + "south/S-7", "termType": "owl_named_individual",
        "authorityName": "Fictional South Authority", "authorityVersion": "2025-2", "vocabularyIri": B + "south/2025",
        "evidence": {"citation": "Exact fictional South authority", "sha256": None}}
    row = {"index": 3, "columnOrdinal": native["columnOrdinal"], "columnName": native["columnName"],
        "source": side, "target": target, "predicateIri": B + "scoped-relation",
        "evidence": {"citation": "Explicit selected fictional mapping evidence", "sha256": "a" * 64},
        "uncertainty": "Only the stated fictional sampling frame", "scope": {"kind": "dataset-identifier", "note": "This source and stated period only"},
        "sourceDecision": decision, "origin": "current-saved-source-mapping"}
    current.update(schema="current-source-contribution/3", pendingEvidence=[copy.deepcopy(row)])
    candidate.update(schema="confirmed-source-contribution/3", columns=[], procedure=None, identifiers=[], pendingEvidence=[copy.deepcopy(row)])
    return candidate, current, row


def compile_one(candidate, current):
    preview = contribution.preview(candidate, current=current)
    compiled = contribution.admit(candidate, current=current, consent={"version": "confirmed-source-contribution-consent/3", "accepted": True, "previewSha256": preview["sha256"]})
    return preview, list(ox.parse(compiled["graphBytes"], format=ox.RdfFormat.N_QUADS))


def other_rows(row, *, version=None):
    b = GraphBuilder()
    dataset, table, schema, column, record, graph = (B + "other/" + key for key in ("dataset", "table", "schema", "column", "reference", "graph"))
    node = B + "other/code"
    b.type(dataset, "dcat:Dataset", graph); b.add(dataset, "pav:version", L("fictional-other-v1"), graph)
    b.add(dataset, "dcterms:source", B + "other/source", graph)
    b.add(dataset, "dcterms:hasPart", table, graph); b.add(table, "csvw:tableSchema", schema, graph)
    b.add(schema, "csvw:column", column, graph); b.type(column, "csvw:Column", graph); b.add(column, "csvw:number", L(1), graph)
    b.add(node, "dcterms:isPartOf", column, graph)
    target = row["target"]
    provenance.mark_statement(b, record, node, "dcterms:references", target["termIri"], graph=graph,
        agent=B + "declared-actor", activity=B + "declared-activity", evidence="Explicit fictional target reference", confidence="high", criticality="critical", assert_triple=False)
    context = {"schema": CONTEXT_TYPE, "family": "population", "field": "codes.term_iri", "scope": "code-reference", "columnOrdinal": 0,
        **{key: target[key] for key in ("nativeKey", "authorityName", "authorityVersion", "vocabularyIri", "termType")}}
    if version: context["authorityVersion"] = version
    b.add(record, "dcterms:type", L(CONTEXT_TYPE), graph); b.add(record, "prov:value", L(json.dumps(context)), graph)
    return dataset, b.quads


def store_rows(tmp_path, rows):
    path = tmp_path / "allowed-private-snapshot"
    store = ox.Store(path); store.extend(rows); store.flush(); del store; gc.collect()
    return path


def test_exact_private_v3_preview_and_consent_preserve_pending_source_decision():
    candidate, current, row = inputs()
    before = copy.deepcopy((candidate, current))
    preview, rows = compile_one(candidate, current)
    assert (candidate, current) == before
    assert preview["schema"] == "confirmed-source-contribution-preview/3"
    assert preview["candidate"]["pendingEvidence"] == [row]
    queue = review.review_queue(rows)
    assert len(queue) == 1 and queue[0].criticality == "critical" and queue[0].status == "awaitingReview"
    assert not any(q.subject == N(row["source"]["termIri"]) and q.predicate == N(row["predicateIri"]) for q in rows)
    assert any(q.predicate == N("dcterms:type") and q.object == L(PENDING_TYPE) for q in rows)
    assert "not SDK-authored or shared-reviewed" in preview["graph"]["content"]
    with pytest.raises(contribution.ContributionError, match="exact current contribution"):
        contribution.admit(candidate, current=current, consent={"version": "confirmed-source-contribution-consent/2", "accepted": True, "previewSha256": preview["sha256"]})


@pytest.mark.parametrize("fault", ["decision", "sha", "authority", "scope", "extra", "rejected", "incomplete", "index"])
def test_saved_evidence_is_complete_closed_and_equal_to_current_row(fault):
    candidate, current, _ = inputs()
    row = candidate["pendingEvidence"][0]
    if fault == "decision": row["sourceDecision"] = "unresolved"
    elif fault == "sha": row["evidence"]["sha256"] = "b" * 64
    elif fault == "authority": row["target"]["authorityVersion"] = "2026-2"
    elif fault == "scope": row["scope"]["note"] = "Different source scope"
    elif fault == "extra": row["privateNote"] = "UNSELECTED PRIVATE CANARY"
    elif fault == "rejected": row["sourceDecision"] = "rejected"
    elif fault == "incomplete": row["evidence"]["sha256"] = None
    elif fault == "index": row["index"] = True
    with pytest.raises(contribution.ContributionError): contribution.preview(candidate, current=current)


@pytest.mark.parametrize("decision,kind", [("reviewed-scoped", "scoped_mapping"), ("unresolved", "suggestion")])
def test_actual_direct_relationship_paths_filters_direction_and_no_shared_iri(tmp_path, decision, kind):
    candidate, current, row = inputs(decision)
    _, rows = compile_one(candidate, current)
    other, target_rows = other_rows(row)
    path = store_rows(tmp_path, [*rows, *target_rows])
    kwargs = {"project_datasets": [candidate["dataset"]["iri"]], "families": ["population"], "relationship_kinds": [kind]}
    assert discovery.discover(path, **kwargs)["paths"] == []
    assert discovery.discover(path, include_pending=True, project_datasets=kwargs["project_datasets"])["paths"] == []
    result = discovery.discover(path, include_pending=True, **kwargs)
    assert result["query_status"] == "complete" and len(result["paths"]) == 1
    found = result["paths"][0]
    assert found["match"] == kind and "shared_iri" not in found
    assert found["dataset"] == other and found["path_state"] == "awaiting_review"
    assert found["relationship"]["context"] == row
    assert found["relationship"]["sharedReview"] == "awaiting_review"
    assert found["relationship"]["subject"] == row["source"]["termIri"]
    assert found["relationship"]["predicate"] == row["predicateIri"]
    assert found["relationship"]["object"] == row["target"]["termIri"]
    assert not found["project"]["asserted"] and not found["candidate"]["asserted"]
    reverse = discovery.discover(path, include_pending=True, **{**kwargs, "project_datasets": [other]})["paths"][0]
    assert reverse["dataset"] == candidate["dataset"]["iri"]
    assert reverse["relationship"] == found["relationship"]  # Actual predicate/direction are never inverted.
    excluded = "suggestion" if kind == "scoped_mapping" else "scoped_mapping"
    assert discovery.discover(path, include_pending=True, **{**kwargs, "relationship_kinds": [excluded]})["paths"] == []


def test_exact_target_iri_with_wrong_authority_version_never_matches(tmp_path):
    candidate, current, row = inputs()
    _, rows = compile_one(candidate, current)
    _, target = other_rows(row, version="different-authority-release")
    path = store_rows(tmp_path, [*rows, *target])
    assert discovery.discover(path, project_datasets=[candidate["dataset"]["iri"]], include_pending=True,
        relationship_kinds=["scoped_mapping"])["paths"] == []


def test_malformed_selected_relationship_proof_refuses_all_results(tmp_path):
    candidate, current, row = inputs()
    _, rows = compile_one(candidate, current)
    _, target = other_rows(row)
    records = {q.subject for q in rows if q.predicate == N("dcterms:type") and q.object == L(PENDING_TYPE)}
    rows = [q for q in rows if not (q.subject in records and q.predicate == N("prov:value"))]
    path = store_rows(tmp_path, [*rows, *target])
    result = discovery.discover(path, project_datasets=[candidate["dataset"]["iri"]], include_pending=True, relationship_kinds=["scoped_mapping"])
    assert result["query_status"] == "partial_evidence_refused" and result["paths"] == []
