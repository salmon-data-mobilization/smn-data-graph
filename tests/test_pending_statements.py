"""Pending assertions are reviewable evidence, not live join bridges."""

from __future__ import annotations

import socket

import pyoxigraph as ox
import pytest

from salmongraph import config, iri, provenance
from salmongraph.graph import GraphBuilder, L, N, RDF_REIFIES


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("pending-statement tests must be offline")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def fixture(cfg=None):
    builder = GraphBuilder(cfg=cfg)
    c = builder.cfg
    return builder, {
        "reifier": iri.xwalk("fixture-match", "candidate", cfg=c),
        "s": iri.ident("stock", "source-a", "001", cfg=c),
        "p": "skos:closeMatch",
        "o": iri.ident("stock", "source-b", "7", cfg=c),
        "graph": iri.corpus_graph("crosswalk", "fixture-v1", cfg=c),
        "agent": iri.model_agent("fixture-model", cfg=c),
        "activity": iri.activity("agent-run", "fixture-run", cfg=c),
        "evidence": ["Explicit candidate evidence, not scientific approval.", "https://example.test/evidence"],
        "confidence": "high", "criticality": "critical", "date": "2026-10-24",
    }


def live_quad(builder, args):
    return ox.Quad(builder.node(args["s"]), N(args["p"], cfg=builder.cfg),
                   builder.term(args["o"]), N(args["graph"], cfg=builder.cfg))


def mark(builder, args, **changes):
    return provenance.mark_statement(builder, **{**args, **changes})


def assert_pending_only(builder, args):
    assert live_quad(builder, args) not in builder.quads
    reifications = [q for q in builder if q.subject == N(args["reifier"]) and q.predicate == N(RDF_REIFIES)]
    assert len(reifications) == 1 and isinstance(reifications[0].object, ox.Triple)
    terms = provenance.terms(builder.cfg)
    statuses = [q.object.value for q in builder if q.subject == N(args["reifier"])
                and q.predicate == N(terms.review_status)]
    assert statuses == [terms.values["awaitingReview"]]
    assert builder.marked == {args["reifier"]: "awaitingReview"}


def test_critical_high_default_is_pending_without_live_triple():
    builder, args = fixture()
    assert mark(builder, args) == "awaitingReview"
    assert_pending_only(builder, args)


def test_noncritical_high_default_is_agent_accepted_and_live():
    builder, args = fixture()
    assert mark(builder, args, criticality="non-critical") == "agentAccepted"
    assert live_quad(builder, args) in builder.quads
    assert builder.marked == {args["reifier"]: "agentAccepted"}
    assert any(q.predicate == N(RDF_REIFIES) for q in builder)


@pytest.mark.parametrize("confidence", ["medium", "low"])
def test_noncritical_below_high_stays_pending(confidence):
    builder, args = fixture()
    assert mark(builder, args, criticality="non-critical", confidence=confidence) == "awaitingReview"
    assert_pending_only(builder, args)


@pytest.mark.parametrize("criticality,confidence", [("critical", "high"), ("non-critical", "low")])
def test_explicit_true_cannot_override_pending(criticality, confidence):
    builder, args = fixture()
    with pytest.raises(ValueError, match="before acceptance"):
        mark(builder, args, criticality=criticality, confidence=confidence, assert_triple=True)
    assert builder.quads == [] and builder.marked == {}


@pytest.mark.parametrize("criticality", ["critical", "non-critical"])
def test_explicit_false_never_adds_live_triple(criticality):
    builder, args = fixture()
    result = mark(builder, args, criticality=criticality, assert_triple=False)
    assert live_quad(builder, args) not in builder.quads
    assert result == ("awaitingReview" if criticality == "critical" else "agentAccepted")


def test_explicit_true_for_accepted_noncritical_statement_is_supported():
    builder, args = fixture()
    assert mark(builder, args, criticality="non-critical", assert_triple=True) == "agentAccepted"
    assert live_quad(builder, args) in builder.quads


@pytest.mark.parametrize("flag", [None, False, True])
def test_prior_live_pending_statement_is_rejected_without_removal_or_approval(flag):
    builder, args = fixture()
    builder.add(args["s"], args["p"], args["o"], args["graph"])
    before = builder.nquads()
    with pytest.raises(ValueError):
        mark(builder, args, assert_triple=flag)
    assert builder.nquads() == before
    assert builder.marked == {}
    assert live_quad(builder, args) in builder.quads


def test_prior_live_check_uses_normalized_rdf_terms_and_exact_graph():
    builder, args = fixture()
    builder.add(N(args["s"]), N(args["p"]), N(args["o"]), N(args["graph"]))
    with pytest.raises(ValueError, match="already live"):
        mark(builder, args)


def test_prior_source_assertion_in_other_graph_is_preserved_not_relabelled():
    # The helper's mutation/pre-existing check is scoped to the target graph.
    # Corpus validation separately detects cross-graph pending/live bridges.
    builder, args = fixture()
    other = iri.corpus_graph("identity", "source-release")
    prior = builder.add(args["s"], args["p"], args["o"], other)
    assert mark(builder, args) == "awaitingReview"
    assert_pending_only(builder, args)
    assert prior in builder.quads
    assert not any(q.subject == N(args["reifier"]) and q.graph_name == N(other) for q in builder)


def test_pending_link_cannot_bridge_union_query_but_reifier_is_queryable():
    builder, args = fixture()
    evidence_graph = iri.corpus_graph("identity", "fixture-data")
    builder.add(args["o"], "rdfs:label", L("Target stock"), evidence_graph)
    mark(builder, args)
    store = builder.to_store()
    bridge = f"""SELECT ?label WHERE {{ <{args['s']}> <{config.STATIC_NS['skos']}closeMatch> ?target .
        ?target <{config.STATIC_NS['rdfs']}label> ?label }}"""
    assert list(store.query(bridge, use_default_graph_as_union=True)) == []
    reified = f"""SELECT ?target WHERE {{ <{args['reifier']}> <{RDF_REIFIES}>
        <<( <{args['s']}> <{config.STATIC_NS['skos']}closeMatch> ?target )>> }}"""
    assert [row["target"].value for row in store.query(reified, use_default_graph_as_union=True)] == [args["o"]]


def test_builder_config_controls_all_marks_without_global_override():
    cfg = config.Config(base="https://example.test/data/", profile_base="https://example.test/review/")
    builder, args = fixture(cfg)
    mark(builder, args)
    assert_pending_only(builder, args)
    terms = provenance.terms(cfg)
    assert any(q.predicate.value == terms.review_status and q.object.value == terms.values["awaitingReview"] for q in builder)
    assert not any(isinstance(q.predicate, ox.NamedNode) and q.predicate.value.startswith(config.DEFAULT_BASE) for q in builder)


@pytest.mark.parametrize("change", [
    {"evidence": []}, {"evidence": "  "}, {"agent": []}, {"agent": "not an iri"},
    {"activity": "not an iri"}, {"date": "yesterday"}, {"confidence": "certain"},
    {"criticality": "major"}, {"assert_triple": 1}, {"graph": "not an iri"},
    {"reifier": ox.BlankNode("unstable-review-target")}, {"s": L("not an IRI")},
    {"p": L("not a predicate")}, {"o": "not an iri"},
])
def test_invalid_input_does_not_inject_accepted_triple_or_partial_marks(change):
    builder, args = fixture()
    args["criticality"] = "non-critical"  # This would assert on success.
    builder.add(args["s"], "rdfs:label", L("Existing source record"), args["graph"])
    before = builder.nquads()
    with pytest.raises(ValueError):
        mark(builder, args, **change)
    assert builder.nquads() == before and builder.marked == {}
    assert live_quad(builder, args) not in builder.quads


def test_already_marked_reifier_cannot_assert_a_different_statement():
    builder, args = fixture()
    mark(builder, args)
    before = builder.nquads()
    with pytest.raises(ValueError, match="already marked"):
        mark(builder, args, o=iri.ident("stock", "third-source", "8"), criticality="non-critical")
    assert builder.nquads() == before
    assert_pending_only(builder, args)


def test_literal_object_can_be_pending_without_becoming_live():
    builder, args = fixture()
    args.update(p="rdfs:label", o=L("Proposed source label"), confidence="low", criticality="non-critical")
    assert mark(builder, args) == "awaitingReview"
    assert_pending_only(builder, args)
