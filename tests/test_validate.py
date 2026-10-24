"""Offline structural SHACL and original-quad provenance gates, not science approval."""

from __future__ import annotations

import socket
from pathlib import Path

import pyoxigraph as ox
import pytest

from salmongraph import config, iri, provenance, shapes
from salmongraph.graph import GraphBuilder, N, RDF_REIFIES
from salmongraph.validate import ShaclViolationError, assert_valid, for_shacl, validate

RDF = config.STATIC_NS["rdf"]
XSD = config.STATIC_NS["xsd"]
PROV = config.STATIC_NS["prov"]
G = "https://example.test/graph/data"
META = "https://example.test/graph/metadata"
OTHER = "https://example.test/graph/other"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    # The SDK's independent default is remote-first 'auto'; SALMONGRAPH_OFFLINE
    # only controls our VocabIndex. Select its genuine local schema explicitly.
    monkeypatch.setenv("METASALMONPY_SDP_SCHEMA_SOURCE", "vendored")
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("SHACL tests must not use the network")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    yield
    assert attempts == [], "validation attempted network access even though the socket guard blocked it"


def candidate(*, confidence="high", criticality="critical"):
    b = GraphBuilder()
    agent = provenance.ai_agent(b, "fixture-model", graph=META)
    activity = iri.activity("build", "fixture")
    provenance.activity_node(b, activity, graph=META, label="fixture", date="2026-10-24")
    reifier, subject, obj = "https://example.test/assertion", "https://example.test/source", "https://example.test/target"
    provenance.mark_statement(b, reifier, subject, "skos:closeMatch", obj, graph=G,
                             agent=agent, activity=activity, evidence="Source dictionary: fixture relationship only.",
                             confidence=confidence, criticality=criticality, assert_triple=False)
    return list(b.quads), N(reifier), ox.Triple(N(subject), N("skos:closeMatch"), N(obj))


def replace_object(quads, subject, predicate, obj):
    return [ox.Quad(q.subject, q.predicate, obj, q.graph_name)
            if q.subject == subject and q.predicate == N(predicate) else q for q in quads]


def legacy(quads):
    result = []
    for q in quads:
        if q.predicate.value == RDF_REIFIES:
            t = q.object
            result.extend([ox.Quad(q.subject, N("rdf:type"), N("rdf:Statement"), q.graph_name),
                           ox.Quad(q.subject, N("rdf:subject"), t.subject, N(META)),
                           ox.Quad(q.subject, N("rdf:predicate"), t.predicate, q.graph_name),
                           ox.Quad(q.subject, N("rdf:object"), t.object, q.graph_name)])
        else:
            result.append(q)
    return result


def test_default_shape_set_is_local_nonempty_and_sorted():
    files = shapes.shape_files()
    assert files and files == sorted(files, key=lambda p: p.name)
    assert all(p.is_file() and p.suffix == ".ttl" for p in files)


def test_for_shacl_rewrites_only_reifies_object_without_shadow_assertion():
    quads, reifier, triple = candidate()
    rewritten = for_shacl(reversed(quads))
    assert rewritten == for_shacl(quads)
    assert len(rewritten) == len(quads)
    q = next(q for q in rewritten if q.predicate.value == RDF_REIFIES)
    assert q.subject == reifier and q.object == ox.Literal(f"{triple} .")
    assert all((q.subject, q.predicate, q.object) != (triple.subject, triple.predicate, triple.object) for q in rewritten)
    assert any(isinstance(q.object, ox.Triple) for q in quads)
    assert {q for q in quads if q.predicate.value != RDF_REIFIES} <= set(rewritten)


@pytest.mark.parametrize("encoding", ["rdf12", "legacy"])
def test_complete_pending_candidate_passes_structurally_without_scientific_acceptance(encoding):
    quads, _, _ = candidate()
    quads = legacy(quads) if encoding == "legacy" else quads
    report = assert_valid(quads)
    assert report.conforms and report.violations == []
    assert "Bounded structural" in report.text


def test_selected_named_graph_union_sees_activity_date_from_metadata():
    quads, reifier, _ = candidate()
    assert validate(quads, graphs=[G, META]).conforms
    report = validate(quads, graphs=[G])
    assert not report.conforms
    assert any(v.focus == reifier.value and v.graphs == (G,) for v in report.violations)
    assert validate(quads, graphs=[G, META]).text == validate(list(reversed(quads)), graphs=[META, G]).text


@pytest.mark.parametrize("predicate", ["corp:confidence", "corp:criticality", "corp:reviewStatus", "prov:wasAttributedTo", "prov:wasGeneratedBy", "prov:wasDerivedFrom"])
def test_missing_d6_mark_or_evidence_is_violation(predicate):
    quads, reifier, _ = candidate()
    quads = [q for q in quads if not (q.subject == reifier and q.predicate == N(predicate))]
    report = validate(quads)
    assert not report.conforms
    assert any(v.focus == reifier.value and v.severity == "Violation" for v in report.violations)


def test_conflicting_review_status_and_critical_agent_acceptance_fail():
    quads, reifier, _ = candidate()
    quads.append(ox.Quad(reifier, N("corp:reviewStatus"), N("corp:agentAccepted"), N(G)))
    report = validate(quads)
    assert not report.conforms
    quads = replace_object(quads, reifier, "corp:reviewStatus", N("corp:agentAccepted"))
    report = validate(quads)
    assert any("critical assertions need review" in v.message for v in report.violations)


def test_human_status_without_reviewer_evidence_cannot_supply_approval():
    quads, reifier, _ = candidate()
    quads = replace_object(quads, reifier, "corp:reviewStatus", N("corp:humanAccepted"))
    assert any("identified prov:Person" in v.message for v in validate(quads).violations)


@pytest.mark.parametrize("encoding", ["rdf12", "legacy"])
def test_pending_critical_spo_live_in_another_graph_cannot_hide_behind_selection(encoding):
    quads, reifier, triple = candidate()
    quads = legacy(quads) if encoding == "legacy" else quads
    quads.append(ox.Quad(triple.subject, triple.predicate, triple.object, N(OTHER)))
    report = validate(quads, graphs=[G, META])
    assert any(v.focus == reifier.value and v.shape.endswith("PendingStatement") for v in report.violations)
    with pytest.raises(ShaclViolationError) as caught:
        assert_valid(quads)
    assert caught.value.report.conforms is False


def test_literal_which_contains_the_same_spo_is_not_a_live_assertion():
    quads, _, triple = candidate()
    quads.append(ox.Quad(N("https://example.test/note"), N("prov:value"), ox.Literal(str(triple)), N(OTHER)))
    assert validate(quads).conforms


@pytest.mark.parametrize("kind", ["raw-literal", "missing-legacy-object", "multiple-legacy-subjects", "wrong-predicate"])
def test_unsupported_or_ambiguous_reifier_encoding_fails_closed(kind):
    quads, reifier, triple = candidate()
    if kind == "raw-literal":
        quads = replace_object(quads, reifier, RDF_REIFIES, ox.Literal(str(triple)))
    else:
        quads = legacy(quads)
        if kind == "missing-legacy-object":
            quads = [q for q in quads if q.predicate != N("rdf:object")]
        elif kind == "multiple-legacy-subjects":
            quads.append(ox.Quad(reifier, N("rdf:subject"), N("https://example.test/different"), N(G)))
        else:
            quads = replace_object(quads, reifier, "rdf:predicate", ox.Literal("not a predicate"))
    assert any(v.shape.endswith("ReifierEncoding") for v in validate(quads).violations)


def custom_shape(tmp_path, severity="Violation"):
    path = tmp_path / "custom.ttl"
    path.write_text('''@prefix sh: <http://www.w3.org/ns/shacl#> .
        @prefix ex: <https://example.test/> .
        ex:Check a sh:NodeShape ; sh:targetNode ex:focus ; sh:property [
        sh:path ex:required ; sh:minCount 1 ; sh:severity sh:''' + severity + ''' ] .''')
    return path


@pytest.mark.parametrize("severity,conforms", [("Violation", False), ("Warning", True), ("Info", True)])
def test_real_pyshacl_results_keep_severity_and_original_graphs(tmp_path, severity, conforms):
    shape = custom_shape(tmp_path, severity)
    quads = [ox.Quad(N("https://example.test/focus"), N("rdf:type"), N("https://example.test/Fixture"), N(G)),
             ox.Quad(N("https://example.test/focus"), N("rdfs:label"), ox.Literal("fixture"), N(META))]
    report = validate(quads, shapes=[shape])
    assert report.conforms is conforms
    assert len(report.violations) == 1
    assert report.violations[0].severity == severity
    assert report.violations[0].graphs == (G, META)
    assert report.text == validate(reversed(quads), shapes=[shape]).text
    if conforms:
        assert assert_valid(quads, shapes=[shape]).conforms


@pytest.mark.parametrize("kind", ["empty-list", "missing", "empty-file", "no-constraints", "malformed", "imports", "js", "service", "advanced-target"])
def test_missing_empty_unsafe_or_malformed_shapes_never_certify(tmp_path, kind):
    path = tmp_path / "bad.ttl"
    text = ""
    if kind == "malformed":
        text = "<not closed"
    elif kind == "imports":
        text = "<urn:shape> <http://www.w3.org/2002/07/owl#imports> <https://example.invalid/ontology> ."
    elif kind == "js":
        text = "<urn:shape> <http://www.w3.org/ns/shacl#js> <https://example.invalid/script> ."
    elif kind == "service":
        text = '<urn:shape> <http://www.w3.org/ns/shacl#select> "SELECT * WHERE { SERVICE <https://example.invalid/> { ?s ?p ?o } }" .'
    elif kind == "no-constraints":
        text = '<urn:shape> a <http://www.w3.org/ns/shacl#NodeShape> .'
    elif kind == "advanced-target":
        text = '<urn:shape> <http://www.w3.org/ns/shacl#target> <urn:custom-target> .'
    if kind != "missing":
        path.write_text(text)
    report = validate([], shapes=[] if kind == "empty-list" else [path])
    assert not report.conforms
    assert any(v.shape.endswith("ValidationInput") for v in report.violations)


def test_missing_default_shape_set_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(shapes, "SHAPES_DIR", tmp_path)
    assert not validate([]).conforms


def test_configured_profile_placeholder_uses_separate_namespace():
    with config.override(base="https://example.test/smn-data-graph/"):
        quads, _, _ = candidate()
        assert validate(quads).conforms
        quads = [q for q in quads if q.predicate != N("corp:confidence")]
        assert not validate(quads).conforms


def test_store_and_graph_selection_do_not_include_unselected_observation_data(tmp_path):
    quads, _, _ = candidate()
    store = ox.Store()
    store.extend(quads)
    assert validate(store).conforms
    assert not validate(store, graphs=["https://example.test/missing"]).conforms


def test_triple_term_in_other_predicate_is_explicitly_unsupported():
    quads, _, triple = candidate()
    quads.append(ox.Quad(N("https://example.test/unhandled"), N("prov:value"), triple, N(G)))
    assert not validate(quads).conforms


def test_positive_noncritical_high_confidence_and_recorded_human_decision_shapes():
    quads, _, _ = candidate(criticality="non-critical")
    assert validate(quads).conforms
    quads, reifier, _ = candidate()
    quads = replace_object(quads, reifier, "corp:reviewStatus", N("corp:humanAccepted"))
    reviewer = N("https://example.test/reviewer")
    quads.extend([ox.Quad(reifier, N("pav:curatedBy"), reviewer, N(META)),
                  ox.Quad(reviewer, N("rdf:type"), N("prov:Person"), N(META)),
                  ox.Quad(reifier, N("dcterms:date"), ox.Literal("2026-10-24", datatype=N("xsd:date")), N(META))])
    assert validate(quads).conforms  # Structural evidence only, not verification of the person's decision.


@pytest.mark.parametrize("value", ["NaN", "INF", "-INF"])
def test_nonfinite_numeric_literals_fail_original_quad_gate(value):
    quads = [ox.Quad(N("https://example.test/obs"), N("sosa:hasSimpleResult"),
                     ox.Literal(value, datatype=N("xsd:double")), N(G))]
    assert any(v.shape.endswith("NumericLiteral") for v in validate(quads).violations)


def observation(*, pending=False):
    """The approved local-column/measure-specific-DSD contract, all fictional."""
    b = GraphBuilder()
    obs, dataset, dsd = ("https://example.test/obs", "https://example.test/dataset", "https://example.test/dsd")
    measure, year, stock = ("https://example.test/column/count", "https://example.test/column/year", "https://example.test/column/stock")
    yc, mc, sc = ("https://example.test/component/year", "https://example.test/component/measure", "https://example.test/component/stock")
    for column, role in ((measure, "qb:MeasureProperty"), (year, "qb:DimensionProperty"), (stock, "qb:DimensionProperty")):
        b.type(column, "csvw:Column", META)
        b.type(column, role, META)
    b.type(obs, "qb:Observation", G)
    b.type(obs, "sosa:Observation", G)
    b.type(dataset, "qb:DataSet", META)
    b.type(dsd, "qb:DataStructureDefinition", META)
    b.add(dataset, "qb:structure", dsd, META)
    b.add(obs, "qb:dataSet", dataset, G)
    b.add(obs, "sosa:observedProperty", measure, G)
    b.add(obs, "sosa:hasSimpleResult", ox.Literal(-99.0), G)
    b.add(obs, year, ox.Literal("2000", datatype=N("xsd:gYear")), G)
    b.add(obs, stock, "https://example.test/id/stock/001", G)
    b.add(obs, "prov:wasDerivedFrom", yc, G)
    for component in (yc, mc, sc):
        b.type(component, "qb:ComponentSpecification", META)
        b.add(dsd, "qb:component", component, META)
    b.add(mc, "qb:measure", measure, META)
    b.add(sc, "qb:dimension", stock, META)
    b.add(yc, "prov:wasDerivedFrom", year, META)
    b.add(yc, "prov:wasDerivedFrom", measure, META)
    bindings = [(measure, "qb:concept", "https://example.test/vocabulary/source-count"),
                (measure, "qudt:unit", "unit:NUM"), (yc, "qb:dimension", "smn:broodYear")]
    if pending:
        agent = provenance.ai_agent(b, "fixture-model", graph=META)
        activity = iri.activity("build", "observation-fixture")
        provenance.activity_node(b, activity, graph=META, label="fixture", date="2026-10-24")
        for index, (s, p, o) in enumerate(bindings):
            provenance.mark_statement(b, f"https://example.test/assertion/{index}", s, p, o,
                graph=META, agent=agent, activity=activity, evidence="Source mapping pending fixture review.",
                confidence="high", criticality="critical")
    else:
        for s, p, o in bindings:
            b.add(s, p, o, META)
        b.add(obs, "smn:broodYear", ox.Literal("2000", datatype=N("xsd:gYear")), G)
        b.add(obs, "qudt:unit", "unit:NUM", G)
    return list(b.quads)


@pytest.mark.parametrize("pending,encoding", [(False, "rdf12"), (True, "rdf12"), (True, "legacy")])
def test_observation_structure_accepts_source_facts_or_complete_pending_column_interpretation(pending, encoding):
    quads = observation(pending=pending)
    if encoding == "legacy":
        quads = legacy(quads)
    before = set(quads)
    report = validate(quads)
    assert report.conforms, report.text
    assert set(quads) == before  # Validation never materializes source interpretations.
    if pending:
        assert not any(q.subject == N("https://example.test/obs") and q.predicate == N("smn:broodYear") for q in quads)


@pytest.mark.parametrize("missing", ["dataset", "result", "observed-column", "concept", "unit", "raw-year", "dimension", "year-component-trace", "structure"])
def test_missing_observation_source_slots_or_structure_fail(missing):
    quads = observation()
    subject, predicate = {
        "dataset": ("https://example.test/obs", "qb:dataSet"),
        "result": ("https://example.test/obs", "sosa:hasSimpleResult"),
        "observed-column": ("https://example.test/obs", "sosa:observedProperty"),
        "concept": ("https://example.test/column/count", "qb:concept"),
        "unit": ("https://example.test/column/count", "qudt:unit"),
        "raw-year": ("https://example.test/obs", "https://example.test/column/year"),
        "dimension": ("https://example.test/obs", "https://example.test/column/stock"),
        "year-component-trace": ("https://example.test/obs", "prov:wasDerivedFrom"),
        "structure": ("https://example.test/dataset", "qb:structure"),
    }[missing]
    quads = [q for q in quads if not (q.subject == N(subject) and q.predicate == N(predicate))]
    assert not validate(quads).conforms


@pytest.mark.parametrize("predicate,obj", [("smn:broodYear", ox.Literal("2000", datatype=N("xsd:gYear"))), ("qudt:unit", N("unit:NUM"))])
def test_pending_column_year_or_unit_cannot_be_shortcut_by_a_live_observation_binding(predicate, obj):
    quads = observation(pending=True)
    quads.append(ox.Quad(N("https://example.test/obs"), N(predicate), obj, N(G)))
    report = validate(quads)
    assert any(v.shape.endswith("Dependency") for v in report.violations)


def test_incomplete_pending_candidate_does_not_fill_required_column_slot():
    quads = observation(pending=True)
    reifier = N("https://example.test/assertion/0")
    quads = [q for q in quads if not (q.subject == reifier and q.predicate == N("corp:confidence"))]
    assert any(v.shape.endswith("ObservationSemanticSlot") for v in validate(quads).violations)


def test_conflicting_year_basis_and_wrong_year_lexical_type_fail():
    quads = observation()
    quads.append(ox.Quad(N("https://example.test/component/year"), N("qb:dimension"), N("smn:returnYear"), N(META)))
    assert any(v.shape.endswith("ObservationYearStructure") for v in validate(quads).violations)
    quads = replace_object(observation(), N("https://example.test/obs"), "https://example.test/column/year", ox.Literal(2000))
    assert any(v.shape.endswith("ObservationYear") for v in validate(quads).violations)


def test_directional_language_literal_is_explicitly_unsupported_not_silently_changed():
    value = ox.Literal("fixture", language="en", direction=ox.BaseDirection.LTR)
    quads = [ox.Quad(N("https://example.test/node"), N("rdfs:label"), value, N(G))]
    report = validate(quads)
    assert not report.conforms and any("directional RDF 1.2" in v.message for v in report.violations)


def test_optional_source_attribute_may_be_missing_but_declared_required_dimension_may_not():
    quads = observation()
    stock_component = N("https://example.test/component/stock")
    stock = N("https://example.test/column/stock")
    quads = [q for q in quads if not (q.subject == stock_component and q.predicate == N("qb:dimension"))
             and not (q.subject == N("https://example.test/obs") and q.predicate == stock)]
    quads.extend([ox.Quad(stock_component, N("qb:attribute"), stock, N(META)),
                  ox.Quad(stock_component, N("qb:componentRequired"), ox.Literal(False), N(META))])
    assert validate(quads).conforms
    required = replace_object(quads, stock_component, "qb:componentRequired", ox.Literal(True))
    assert any(v.shape.endswith("ObservationAttribute") for v in validate(required).violations)
    missing_flag = [q for q in quads if q.predicate != N("qb:componentRequired")]
    assert not validate(missing_flag).conforms


def test_optional_native_numeric_source_attribute_remains_a_literal():
    quads = observation()
    component, attribute = N("https://example.test/component/se"), N("https://example.test/column/se")
    quads.extend([ox.Quad(N("https://example.test/dsd"), N("qb:component"), component, N(META)),
                  ox.Quad(component, N("qb:attribute"), attribute, N(META)),
                  ox.Quad(component, N("qb:componentRequired"), ox.Literal(False), N(META)),
                  ox.Quad(N("https://example.test/obs"), attribute, ox.Literal(0.25), N(G))])
    assert validate(quads).conforms


def test_source_stated_sssom_assertion_retains_justification_without_invented_d6_review():
    b = GraphBuilder()
    r = "https://example.test/source-assertion"
    b.reify(r, "https://example.test/source", "skos:closeMatch", "https://example.test/target", G, assert_triple=True)
    b.add(r, "sssom:mapping_justification", "semapv:ManualMappingCuration", G)
    b.add(r, "prov:wasDerivedFrom", "https://example.test/published-mapping-set", G)
    quads = list(b.quads)
    assert validate(quads).conforms  # Source claim retained; not current human approval.
    quads = replace_object(quads, N(r), "sssom:mapping_justification", N("semapv:AgentBasedMatching"))
    assert not validate(quads).conforms
    quads = list(b.quads) + [ox.Quad(N(r), N("corp:reviewStatus"), N("corp:humanAccepted"), N(G))]
    assert not validate(quads).conforms  # Partial marks cannot use the source-fact alternative.


def dataset_metadata():
    b = GraphBuilder()
    dataset, activity, source = "https://example.test/dataset", "https://example.test/build", "https://example.test/source-file"
    b.type(dataset, "dcat:Dataset", META)
    b.add(dataset, "dcterms:license", "https://creativecommons.org/licenses/by/4.0/", META)
    b.add(dataset, "dcterms:rights", ox.Literal("Fixture attribution"), META)
    b.add(dataset, "pav:version", ox.Literal("2026.10"), META)
    b.add(dataset, "dcterms:created", ox.Literal("2026-10-24", datatype=N("xsd:date")), META)
    b.add(dataset, "prov:wasGeneratedBy", activity, META)
    b.add(activity, "prov:used", source, META)
    b.type(source, "prov:Entity", META)
    b.add(source, "prov:hadPrimarySource", "https://example.test/source.csv", META)
    b.add(source, "dcterms:identifier", ox.Literal("sha256:" + "a" * 64), META)
    return list(b.quads)


@pytest.mark.parametrize("missing", [None, "dcterms:license", "dcterms:rights", "pav:version", "dcterms:identifier"])
def test_dataset_metadata_shape_checks_assertion_structure_not_actual_licence_or_source_bytes(missing):
    quads = dataset_metadata()
    if missing:
        quads = [q for q in quads if q.predicate != N(missing)]
    assert validate(quads).conforms is (missing is None)


@pytest.mark.parametrize("mode", ["live", "pending", "alternate-pending"])
def test_actual_sdk_compiler_fixture_passes_the_default_structural_gate(tmp_path, mode):
    # Keep the core gate suite runnable without optional Parquet tooling, and
    # exercise this integration with the explicit cached PyArrow runtime.
    pytest.importorskip("pyarrow", reason="actual compiler integration needs the optional PyArrow runtime")
    import test_compile as fixture
    from salmongraph.executor import AgentRun

    document = fixture.document()
    run = None
    cfg = (config.Config(base="https://example.test/separate/", profile_base="https://example.test/profile/")
           if mode == "alternate-pending" else config.Config())
    if mode != "live":
        document["tables"][0]["columns"][3]["mark"] = {
            "aspect": "measure-counts", "confidence": "high", "evidence": ["Fictional count interpretation evidence."]}
        document["tables"][0]["columns"][1]["mark"] = {
            "aspect": "year-basis", "confidence": "high", "evidence": ["Fictional year interpretation evidence."]}
        run = AgentRun("validation-fixture", "fixture-model", "2026-10-23")
    vocab_factory = fixture.compiler_vocab.__wrapped__(tmp_path)
    with config.override(cfg):
        _, _, builder, _ = fixture.build(tmp_path, vocab_factory, document, run=run, cfg=cfg)
        original = builder.quads
        report = validate(original)
    assert report.conforms, report.text
    assert report.violations == [] and builder.quads == original
    assert bool(fixture.pending(builder)) is (mode != "live")


@pytest.mark.parametrize("graph", [ox.DefaultGraph(), ox.BlankNode("graph")])
def test_unsupported_graph_names_fail_closed_instead_of_dropping_data(graph):
    quads = [ox.Quad(N("https://example.test/node"), N("rdf:type"), N("https://example.test/Class"), graph)]
    assert any(v.shape.endswith("NamedGraphs") for v in validate(quads).violations)


def test_focus_graph_context_includes_original_predicate_occurrences(tmp_path):
    path = custom_shape(tmp_path)
    quads = [ox.Quad(N("https://example.test/focus"), N("rdf:type"), N("https://example.test/Class"), N(META)),
             ox.Quad(N("https://example.test/source"), N("https://example.test/focus"), ox.Literal("source fact"), N(G))]
    report = validate(quads, shapes=[path])
    assert report.violations[0].graphs == (G, META)


def test_unconfirmed_private_dataset_may_truthfully_omit_unknown_licence():
    quads = [q for q in dataset_metadata() if q.predicate != N("dcterms:license")]
    dataset = N("https://example.test/dataset")
    quads.append(ox.Quad(dataset, N("dcterms:accessRights"), ox.Literal("redistribution unconfirmed"), N(META)))
    assert validate(quads).conforms  # Private structure is not publication or legal permission.
    confirmed = replace_object(quads, dataset, "dcterms:accessRights", ox.Literal("redistribution confirmed"))
    assert not validate(confirmed).conforms


@pytest.mark.parametrize("confidence", ["low", "medium", "high"])
@pytest.mark.parametrize("encoding", ["rdf12", "legacy"])
def test_noncritical_pending_labels_cannot_leak_across_graphs_but_reviewed_high_control_can(confidence, encoding):
    b = GraphBuilder()
    subject, reifier = iri.column("fixture", "1", "source", "name"), iri.xwalk("fixture", "label-candidate")
    proposed = ox.Literal("Unreviewed proposed label")
    # This is the actual helper boundary: its pre-existing SPO check is scoped
    # to the target graph, so the aggregate validator must catch another graph.
    b.add(subject, "rdfs:label", proposed, OTHER)
    agent = provenance.ai_agent(b, "fixture-model", graph=G)
    activity = provenance.activity_node(b, iri.activity("build", "label-fixture"), graph=G,
                                      label="Fixture", date="2026-10-24")
    status = provenance.mark_statement(b, reifier, subject, "rdfs:label", proposed,
        graph=G, agent=agent, activity=activity, evidence=["Actual fixture evidence"],
        confidence=confidence, criticality="non-critical", date="2026-10-24")
    quads = legacy(b.quads) if encoding == "legacy" else b.quads
    report = validate(quads, graphs=[G, META] if encoding == "legacy" else [G])
    if confidence == "high":
        assert status == "agentAccepted" and report.conforms, report.text
    else:
        assert status == "awaitingReview" and not report.conforms
        assert any(v.focus == reifier and v.shape.endswith("PendingStatement") for v in report.violations)
