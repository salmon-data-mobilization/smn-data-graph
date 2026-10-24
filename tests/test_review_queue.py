"""Review records and dependency counts come from tiny explicit RDF proofs."""

from __future__ import annotations

import csv
from dataclasses import replace
import socket

import pyoxigraph as ox
import pytest

from salmongraph import config, iri, provenance, review
from salmongraph.graph import GraphBuilder, L, N


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("review queue tests must be offline")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def fixture():
    builder = GraphBuilder()
    graph = iri.corpus_graph("crosswalk", "fixture")
    return builder, graph


def pending(builder, graph, name="one", *, criticality="critical", confidence="high", date=None,
            statement=True, evidence=None, agents=None, activities=None):
    target = iri.xwalk("fixture", name)
    agents = agents or [iri.model_agent("fixture-model")]
    activities = activities or [iri.activity("agent-run", "fixture-run")]
    args = {"agent": agents, "activity": activities[0],
            "evidence": evidence or ["Literal source evidence.", "https://example.test/source"],
            "criticality": criticality, "confidence": confidence, "graph": graph, "date": date}
    if statement:
        provenance.mark_statement(builder, target, iri.ident("stock", "source-a", name),
                                  "skos:closeMatch", iri.ident("stock", "source-b", name), **args)
    else:
        provenance.mark_derived(builder, target, **args)
    for activity in activities[1:]:
        builder.add(target, "prov:wasGeneratedBy", activity, graph)
    return target


def observation(builder, graph, name, *sources, typed=True):
    node = iri.obs("fixture", "v1", name)
    if typed:
        builder.type(node, "qb:Observation", graph)
        builder.type(node, "sosa:Observation", graph)
    for source in sources:
        builder.add(node, "prov:wasDerivedFrom", source, graph)
    return node


def test_pending_row_is_source_backed_and_unmarked_facts_have_no_status():
    builder, graph = fixture()
    target = pending(builder, graph)
    builder.add(iri.ident("stock", "raw-source", "7"), "rdfs:label", L("Source fact"), graph)
    rows = review.review_queue(builder.to_store())
    assert len(rows) == 1
    item = rows[0]
    assert item.target == target and item.status == "awaitingReview"
    assert (item.criticality, item.confidence) == ("critical", "high")
    assert item.statement == f"<{iri.ident('stock', 'source-a', 'one')}> <{config.STATIC_NS['skos']}closeMatch> <{iri.ident('stock', 'source-b', 'one')}> ."
    assert item.graph == graph and item.agent == iri.model_agent("fixture-model")
    assert item.activity == iri.activity("agent-run", "fixture-run")
    assert item.date == item.suggested_decision == ""
    assert item.evidence == "Literal source evidence. | https://example.test/source"
    assert item.downstream_joins == 0
    assert review.status_counts(builder) == {"awaitingReview": 1}


def test_actual_multi_agent_activity_dates_are_sorted_display_lists():
    builder, graph = fixture()
    agents = [iri.model_agent("z-model"), iri.software_agent("a-rule", "1")]
    activities = [iri.activity("agent-run", "z-run"), iri.activity("build", "a-build")]
    target = pending(builder, graph, date="2026-10-22", agents=agents, activities=activities)
    builder.add(activities[0], "dcterms:date", L("2026-10-21", "xsd:date"), graph)
    builder.add(activities[1], "dcterms:date", L("2026-10-23T01:02:03Z", "xsd:dateTime"), graph)
    item = review.review_queue(builder)[0]
    assert item.target == target
    assert item.agent == " | ".join(sorted(agents))
    assert item.activity == " | ".join(sorted(activities))
    assert item.date == "2026-10-21 | 2026-10-22 | 2026-10-23T01:02:03Z"


def test_duplicate_marks_across_graphs_and_repeated_quads_give_one_row():
    builder, graph = fixture()
    target = pending(builder, graph)
    other = iri.corpus_graph("identity", "fixture")
    copied = [ox.Quad(q.subject, q.predicate, q.object, N(other)) for q in builder.quads]
    data = builder.quads + copied + copied
    rows = review.review_queue(data)
    assert len(rows) == 1 and rows[0].target == target
    assert rows == review.review_queue(reversed(data))
    assert rows[0].graph == " | ".join(sorted([graph, other]))
    assert review.status_counts(data) == {"awaitingReview": 1}


def test_legacy_rdf11_statement_is_read_without_asserting_it():
    builder, graph = fixture()
    target = pending(builder, graph, statement=False)
    builder.type(target, "rdf:Statement", graph)
    builder.add(target, "rdf:subject", iri.ident("stock", "source-a", "7"), graph)
    builder.add(target, "rdf:predicate", "rdfs:label", graph)
    builder.add(target, "rdf:object", L('Proposed "source" label'), graph)
    before = builder.nquads()
    row = review.review_queue(builder)[0]
    assert row.statement.endswith('"Proposed \\"source\\" label" .')
    assert builder.nquads() == before


def test_node_target_has_blank_statement_and_preserves_nested_proof_text():
    builder, graph = fixture()
    target = pending(builder, graph, statement=False)
    outer, inner = builder.bnode("outer-proof"), builder.bnode("inner-proof")
    builder.add(target, "prov:wasDerivedFrom", outer, graph)
    builder.add(outer, "prov:wasDerivedFrom", inner, graph)
    builder.add(inner, "prov:value", L('Exact source, "quoted"\nsecond line'), graph)
    builder.add(inner, "prov:wasDerivedFrom", outer, graph)  # Cycle, with actual proof text.
    row = review.review_queue(builder)[0]
    assert row.statement == ""
    assert 'Exact source, "quoted"\nsecond line' in row.evidence
    assert "outer-proof" not in row.evidence


def test_downstream_counts_only_unique_explicit_observation_or_reifier_endpoints():
    builder, graph = fixture()
    target = pending(builder, graph, "a")
    dependent = pending(builder, graph, "b")
    builder.add(dependent, "prov:wasDerivedFrom", target, graph)
    cube = iri.named_graph("fixture", "v1", "cube")
    first = observation(builder, cube, "1", target, dependent)
    observation(builder, cube, "2", dependent)
    observation(builder, cube, "not-observed", target, typed=False)
    intermediate = iri.column("fixture", "v1", "source", "count")
    builder.add(intermediate, "prov:wasDerivedFrom", target, graph)
    builder.add(first, "prov:wasDerivedFrom", intermediate, cube)
    builder.add(target, "prov:wasDerivedFrom", dependent, graph)  # Stop cycles; exclude own target.
    rows = {row.target: row for row in review.review_queue(builder)}
    assert rows[target].downstream_joins == 3  # two observations and the actual dependent reifier
    assert rows[dependent].downstream_joins == 3  # same cycle reaches the other reifier, once


def test_source_column_fallback_requires_actual_csvw_column_type():
    builder, graph = fixture()
    source_column = iri.column("fixture", "v1", "source", "count")
    target = iri.xwalk("fixture", "column-interpretation")
    provenance.mark_statement(builder, target, source_column, "sdpv:variable", "smn:Abundance",
                              graph=graph, agent=iri.model_agent("fixture"), activity=iri.activity("agent-run", "run"),
                              evidence="Actual fixture passage", confidence="high", criticality="critical")
    observation(builder, graph, "1", source_column)
    assert review.review_queue(builder)[0].downstream_joins == 0
    builder.type(source_column, "csvw:Column", graph)
    assert review.review_queue(builder)[0].downstream_joins == 1


def test_critical_then_recorded_dependency_then_iri_sorting():
    builder, graph = fixture()
    a = pending(builder, graph, "a")
    z = pending(builder, graph, "z")
    b = pending(builder, graph, "b")
    noncritical = pending(builder, graph, "noncritical", criticality="non-critical", confidence="low")
    observation(builder, graph, "z-child", z)
    for n in range(3):
        observation(builder, graph, f"noncritical-{n}", noncritical)
    assert [row.target for row in review.review_queue(builder)] == [z, a, b, noncritical]


def test_graph_selection_keeps_full_proof_and_dependency_context():
    builder, graph = fixture()
    target = pending(builder, graph)
    other = iri.named_graph("fixture", "v1", "cube")
    observation(builder, other, "1", target)
    assert review.review_queue(builder, graphs=[graph])[0].downstream_joins == 1
    assert review.review_queue(builder, graphs=[other]) == []
    assert review.review_queue(builder, graphs=[]) == []


def test_graph_selection_does_not_hide_a_malformed_pending_record():
    builder, graph = fixture()
    pending(builder, graph)
    other = iri.corpus_graph("identity", "unselected")
    target = pending(builder, other, "malformed")
    data = [q for q in builder if not (q.subject == N(target) and q.predicate == N(provenance.terms().confidence))]
    with pytest.raises(ValueError, match="missing or conflicting"):
        review.review_queue(data, graphs=[graph])


def test_status_counts_unique_targets_all_actual_statuses_and_no_approval_for_raw_facts():
    builder, graph = fixture()
    pending(builder, graph)
    terms = provenance.terms()
    for token in ("agentAccepted", "humanAccepted", "humanAmended", "rejected"):
        node = iri.xwalk("fixture", token.lower())
        builder.add(node, terms.review_status, terms.values[token], graph)
    data = builder.quads * 2
    assert review.status_counts(data) == {token: 1 for token in sorted(provenance.REVIEW_STATUSES)}
    assert len(review.review_queue(builder)) == 1
    assert review.status_counts([]) == {} and review.review_queue([]) == []


@pytest.mark.parametrize("mutation", ["unknown-status", "conflicting-status", "conflicting-confidence",
                                     "missing-criticality", "missing-agent", "missing-activity", "missing-evidence",
                                     "literal-agent", "bad-date", "malformed-reifier", "ambiguous-reifier",
                                     "incomplete-legacy", "typed-empty-statement", "empty-proof-node",
                                     "unknown-confidence", "conflicting-criticality", "blank-review-target",
                                     "literal-status", "proof-cycle-without-content", "conflicting-encodings"])
def test_ambiguous_or_malformed_records_fail_closed(mutation):
    builder, graph = fixture()
    target = pending(builder, graph, statement=mutation != "typed-empty-statement")
    data = list(builder.quads)
    terms = provenance.terms()
    prop = {"missing-criticality": terms.criticality, "missing-agent": config.STATIC_NS["prov"] + "wasAttributedTo",
            "missing-activity": config.STATIC_NS["prov"] + "wasGeneratedBy", "missing-evidence": config.STATIC_NS["prov"] + "wasDerivedFrom"}
    if mutation in prop:
        data = [q for q in data if not (q.subject == N(target) and q.predicate == N(prop[mutation]))]
    elif mutation == "unknown-status":
        data = [q for q in data if q.predicate != N(terms.review_status)]
        data.append(ox.Quad(N(target), N(terms.review_status), N(iri.profile_term("unknownStatus")), N(graph)))
    elif mutation == "conflicting-status":
        data.append(ox.Quad(N(target), N(terms.review_status), N(terms.values["rejected"]), N(iri.corpus_graph("identity", "elsewhere"))))
    elif mutation == "conflicting-confidence":
        data.append(ox.Quad(N(target), N(terms.confidence), N(terms.values["low"]), N(graph)))
    elif mutation == "unknown-confidence":
        data = [q for q in data if q.predicate != N(terms.confidence)]
        data.append(ox.Quad(N(target), N(terms.confidence), N(iri.profile_term("certain")), N(graph)))
    elif mutation == "conflicting-criticality":
        data.append(ox.Quad(N(target), N(terms.criticality), N(terms.values["non-critical"]), N(graph)))
    elif mutation == "blank-review-target":
        data.append(ox.Quad(ox.BlankNode("no-stable-review-target"), N(terms.review_status), N(terms.values["awaitingReview"]), N(graph)))
    elif mutation == "literal-status":
        data = [q for q in data if q.predicate != N(terms.review_status)]
        data.append(ox.Quad(N(target), N(terms.review_status), L("awaitingReview"), N(graph)))
    elif mutation == "literal-agent":
        data.append(ox.Quad(N(target), N("prov:wasAttributedTo"), L("guessed model"), N(graph)))
    elif mutation == "bad-date":
        data.append(ox.Quad(N(target), N("dcterms:created"), L("sometime later"), N(graph)))
    elif mutation == "malformed-reifier":
        data = [q for q in data if q.predicate != N("rdf:reifies")]
        data.append(ox.Quad(N(target), N("rdf:reifies"), L("rewritten triple text"), N(graph)))
    elif mutation == "ambiguous-reifier":
        data.append(ox.Quad(N(target), N("rdf:reifies"), ox.Triple(N(target), N("rdfs:label"), L("Other statement")), N(graph)))
    elif mutation == "incomplete-legacy":
        data.append(ox.Quad(N(target), N("rdf:subject"), N(target), N(graph)))
    elif mutation == "typed-empty-statement":
        data.append(ox.Quad(N(target), N("rdf:type"), N("rdf:Statement"), N(graph)))
    elif mutation == "empty-proof-node":
        data.append(ox.Quad(N(target), N("prov:wasDerivedFrom"), ox.BlankNode("no-proof-content"), N(graph)))
    elif mutation == "proof-cycle-without-content":
        a, b = ox.BlankNode("empty-a"), ox.BlankNode("empty-b")
        data.extend([ox.Quad(N(target), N("prov:wasDerivedFrom"), a, N(graph)),
                     ox.Quad(a, N("prov:wasDerivedFrom"), b, N(graph)),
                     ox.Quad(b, N("prov:wasDerivedFrom"), a, N(graph))])
    elif mutation == "conflicting-encodings":
        for predicate, obj in [("rdf:subject", N(target)), ("rdf:predicate", N("rdfs:label")), ("rdf:object", L("Different statement"))]:
            data.append(ox.Quad(N(target), N(predicate), obj, N(graph)))
    with pytest.raises(ValueError):
        review.review_queue(data, graphs=[graph])
    if mutation in ("unknown-status", "conflicting-status", "literal-status", "blank-review-target"):
        with pytest.raises(ValueError):
            review.status_counts(data)


def test_matching_modern_and_legacy_encodings_are_unambiguous():
    builder, graph = fixture()
    target = pending(builder, graph)
    triple = next(q.object for q in builder if q.predicate == N("rdf:reifies"))
    for part, value in zip(("subject", "predicate", "object"), (triple.subject, triple.predicate, triple.object)):
        builder.add(target, "rdf:" + part, value, graph)
    assert len(review.review_queue(builder)) == 1


def test_alternate_profile_namespace():
    with config.override(base="https://example.test/data/", profile_base="https://example.test/profile/"):
        builder, graph = fixture()
        target = pending(builder, graph)
        item = review.review_queue(builder)[0]
        assert item.target == target and item.status == "awaitingReview"
        assert item.graph.startswith("https://example.test/data/")
        assert review.status_counts(builder) == {"awaitingReview": 1}


def test_deterministic_csv_has_contract_columns_quoting_and_no_guessed_decision(tmp_path):
    builder, graph = fixture()
    pending(builder, graph, "z", evidence=['Source, "quoted"\nline 2'])
    pending(builder, graph, "a")
    rows = review.review_queue(builder)
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    assert review.write_review_queue(rows, first) == first
    assert review.write_review_queue(list(reversed(rows)), second) == second
    assert first.read_bytes() == second.read_bytes()
    with first.open(newline='') as handle:
        reader = csv.DictReader(handle)
        values = list(reader)
        assert reader.fieldnames == list(review.REVIEW_QUEUE_COLUMNS)
    assert len(values) == 2 and all(row["suggested_decision"] == "" for row in values)
    assert 'Source, "quoted"\nline 2' in values[1]["evidence"]
    empty = tmp_path / "empty.csv"
    review.write_review_queue([], empty)
    assert empty.read_text().strip() == ','.join(review.REVIEW_QUEUE_COLUMNS)


@pytest.mark.parametrize("change", [{"status": "humanAccepted"}, {"suggested_decision": "accept"},
                                    {"downstream_joins": -1}, {"confidence": "certain"}, {"agent": ""}])
def test_writer_rejects_malformed_or_decision_rows_without_output(tmp_path, change):
    builder, graph = fixture()
    pending(builder, graph)
    item = replace(review.review_queue(builder)[0], **change)
    path = tmp_path / "invalid.csv"
    with pytest.raises(ValueError):
        review.write_review_queue([item], path)
    assert not path.exists()


def test_writer_refuses_duplicate_targets(tmp_path):
    builder, graph = fixture()
    pending(builder, graph)
    rows = review.review_queue(builder)
    with pytest.raises(ValueError, match="duplicate"):
        review.write_review_queue(rows * 2, tmp_path / "invalid.csv")
