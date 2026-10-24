"""Offline compiler contracts using tiny genuine SDK packages, not salmon evidence."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
from pathlib import Path
import socket

import metasalmonpy as ms
import pandas as pd
import pyarrow.parquet as pq
import pyoxigraph as ox
import pytest
import yaml

from salmongraph import config, iri, provenance
from salmongraph._compile import compile_dataset_graph
from salmongraph.executor import AgentRun, _source_code_iri, write_observations
from salmongraph.graph import GraphBuilder, L, N, RDF_REIFIES, expand
from salmongraph.spec import DatasetSpec, SpecError, load_spec
from salmongraph.vocab import UndeclaredIRIError, VocabIndex
from conftest import tiny_sources


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv("METASALMONPY_SDP_SCHEMA_SOURCE", "vendored")
    monkeypatch.setenv("SALMONGRAPH_OFFLINE", "1")
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append(args)
        raise AssertionError("compiler contracts must remain offline")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    yield
    assert attempts == [], "a blocked network attempt must not be swallowed by a dependency"


@pytest.fixture
def compiler_vocab(tmp_path):
    def make(cfg=None):
        sources = []
        for source in tiny_sources():
            target = tmp_path / (source.key + ".ttl")
            content = source.path.read_text()
            if source.key == "smn":
                content += '\n<https://w3id.org/smn/broodYear> a <http://www.w3.org/2002/07/owl#DatatypeProperty> .\n'
                content += '<https://w3id.org/smn/returnYear> a <http://www.w3.org/2002/07/owl#DatatypeProperty> .\n'
            target.write_text(content)
            sources.append(replace(source, path=target))
        return VocabIndex(sources, cfg=cfg or config.current(), offline=True)
    return make


def document():
    return {
        "spec_version": 1, "slug": "fictional-compiler", "version": "v 1/2",
        "title": "Fictional compiler fixture", "description": "Software tests, not biological evidence.",
        "source": {"publisher": "Fixture publisher", "landing_page": "https://example.test/source",
                   "licence": "https://creativecommons.org/licenses/by/4.0/", "redistribution": "unconfirmed",
                   "attribution": "Fictional source attribution, retained verbatim.",
                   "files": [{"name": "source.csv", "url": "https://example.test/source.csv", "sha256": "a" * 64}]},
        "parser": "csv", "tables": [{"id": "source", "file": "source.csv", "keys": ["stock_id", "period"],
          "columns": [
            {"name": "stock_id", "role": "identifier", "datatype": "string"},
            {"name": "period", "role": "dimension", "datatype": "integer"},
            {"name": "phase", "role": "dimension", "datatype": "string", "codes": {"A": "gcdfo:MethodX", "gap": None}},
            {"name": "count", "role": "measure", "datatype": "number", "concept": "corp:variables/fixture-count",
             "unit": "unit:NUM", "year_basis": "smn:broodYear", "method": "gcdfo:MethodX",
             "decomposition": {"property": "smn:TermA", "object_of_interest": "smn:TermB", "constraints": []},
             "uncertainty": {"standard_error": "se", "cv": "cv", "lower": "lower", "upper": "upper"}},
            {"name": "other_count", "role": "measure", "datatype": "number", "concept": "psc:PSC-CV-999999",
             "unit": "unit:NUM", "year_basis": "smn:returnYear", "estimate_type": "gcdfo:MethodX"},
            *({"name": name, "role": "attribute", "datatype": "number"} for name in ("se", "cv", "lower", "upper")),
          ]}],
        "identity": [{"table": "source", "column": "stock_id", "kind": "stock", "authority": "fixture"}],
        "observations": [{"table": "source", "key": ["stock_id", "period"],
                          "dimensions": ["stock_id", "period", "phase"], "year_column": "period",
                          "measures": ["count", "other_count"]}],
    }


def save_spec(tmp_path, data=None):
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(data or document(), sort_keys=False))
    return load_spec(path)


def data_frame():
    return pd.DataFrame({"stock_id": ["001/α", "002"], "period": [2000, 2001], "phase": ["A", None],
                         "count": [0.0, -99.0], "other_count": [None, 4.5],
                         "se": [None, 0.25], "cv": [None, 0.0], "lower": [None, -120.0], "upper": [None, -100.0]})


def package(tmp_path, spec, frames=None, package_files=None):
    frames = frames or {"source": data_frame()}
    dictionary, tables = [], []
    for table in spec.tables:
        tables.append({"dataset_id": spec.slug, "table_id": table["id"], "file_name": (package_files or {}).get(table["id"], table["file"]),
                       "table_label": "Fixture table", "primary_key": ",".join(table["keys"])})
        for column in table["columns"]:
            dictionary.append({"dataset_id": spec.slug, "table_id": table["id"], "column_name": column["name"],
                               "column_label": column["name"], "column_description": "Source dictionary text",
                               "column_role": {"measure": "measurement", "dimension": "attribute"}.get(column["role"], column["role"]),
                               "value_type": column["datatype"], "required": column["name"] in table["keys"],
                               "term_iri": column.get("concept", ""), "unit_iri": column.get("unit", "")})
    path = tmp_path / "sdp"
    ms.write_salmon_datapackage(frames, pd.DataFrame([{"dataset_id": spec.slug, "title": spec.title,
                                "description": spec.description, "license": spec.source["licence"], "created": "2026-10-24"}]),
                                pd.DataFrame(tables), pd.DataFrame(dictionary), path=str(path))
    return path


def build(tmp_path, compiler_vocab, data=None, *, run=None, cfg=None):
    with config.override(cfg or config.Config()):
        spec = save_spec(tmp_path, data)
        root = package(tmp_path, spec)
        builder = GraphBuilder(compiler_vocab(config.current()), cfg=config.current())
        graphs = compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24", run=run)
        return spec, root, builder, graphs


def objects(builder, subject, predicate):
    return {q.object for q in builder.quads if q.subject == N(subject) and q.predicate == N(predicate)}


def live(builder, subject, predicate, target):
    return any(q.subject == N(subject) and q.predicate == N(predicate) and q.object ==
               (target if isinstance(target, ox.Literal) else N(target)) for q in builder.quads)


def pending(builder):
    return [q for q in builder.quads if q.predicate.value == RDF_REIFIES and isinstance(q.object, ox.Triple)
            and builder.marked.get(q.subject.value) == "awaitingReview"]


def test_genuine_package_projection_numeric_identity_codes_and_metadata(tmp_path, compiler_vocab):
    spec, root, builder, graphs = build(tmp_path, compiler_vocab)
    assert set(graphs) == set(config.DATASET_GRAPH_PARTS)
    assert {q.graph_name.value for q in builder.quads} == set(graphs.values())
    dataset = iri.dataset(spec.slug, spec.version)
    assert live(builder, dataset, "dcterms:rights", L(spec.source["attribution"]))
    assert live(builder, dataset, "dcterms:license", spec.source["licence"])
    assert live(builder, dataset, "dcterms:created", L("2026-10-24", "xsd:date"))
    assert live(builder, dataset, "pav:version", L(spec.version))
    assert any(q.predicate == N("dcterms:identifier") and q.object == L("sha256:" + hashlib.sha256(spec.path.read_bytes()).hexdigest()) for q in builder.quads)
    projection = tmp_path / "expected.parquet"
    write_observations(spec, ms.read_salmon_datapackage(root)["resources"], projection)
    rows = pq.read_table(projection).to_pylist()
    observations = {q.subject.value for q in builder.quads if q.predicate == N("rdf:type") and q.object == N("qb:Observation")}
    assert observations == {r["obs_iri"] for r in rows} and len(rows) == 3
    assert {float(o.value) for r in rows for o in objects(builder, r["obs_iri"], "sosa:hasSimpleResult")} == {-99.0, 0.0, 4.5}
    for row in rows:
        variable = iri.column(spec.slug, spec.version, "source", "count" if row["measure_iri"].endswith("fixture-count") else "other_count")
        assert live(builder, row["obs_iri"], "sosa:observedProperty", variable)
        assert live(builder, row["obs_iri"], "qudt:unit", row["unit_iri"])
        assert live(builder, row["obs_iri"], row["year_basis_iri"], L(str(row["year"]), "xsd:gYear"))
    source_code = _source_code_iri(spec.slug, "source", "phase", "A")
    assert live(builder, source_code, "rdf:type", "skos:Concept")
    assert not objects(builder, source_code, "skos:exactMatch")
    assert any("target-only" in q.object.value for q in builder.quads if isinstance(q.object, ox.Literal))
    assert not any("humanAccepted" in str(q) for q in builder.quads)
    assert not any("endedAtTime" in q.predicate.value for q in builder.quads)
    assert str(tmp_path) not in builder.trig().decode()


def test_optional_dimension_is_optional_qb_attribute_and_null_is_absent(tmp_path, compiler_vocab):
    spec, _, builder, _ = build(tmp_path, compiler_vocab)
    prop = iri.column(spec.slug, spec.version, "source", "phase")
    assert live(builder, prop, "rdf:type", "qb:AttributeProperty")
    assert not live(builder, prop, "rdf:type", "qb:DimensionProperty")
    components = {q.subject for q in builder.quads if q.predicate == N("qb:attribute") and q.object == N(prop)}
    assert components and all(L(False) in objects(builder, c, "qb:componentRequired") for c in components)
    node = iri.obs(spec.slug, spec.version, "002", 2001, expand("corp:variables/fixture-count"))
    assert not objects(builder, node, prop)
    assert live(builder, iri.ident("stock", "fixture", "001/α"), "dcterms:identifier", L("001/α"))


def test_compound_semantics_and_standard_uncertainty_use_declared_links(tmp_path, compiler_vocab):
    spec, _, builder, _ = build(tmp_path, compiler_vocab)
    concept = expand("corp:variables/fixture-count")
    variable = iri.column(spec.slug, spec.version, "source", "count")
    assert live(builder, variable, "iop:hasProperty", "smn:TermA")
    assert live(builder, variable, "iop:hasObjectOfInterest", "smn:TermB")
    assert not objects(builder, concept, "iop:hasProperty")
    node = iri.obs(spec.slug, spec.version, "002", 2001, concept)
    assert live(builder, node, "qudt:standardUncertainty", L(0.25))
    assert live(builder, node, "sosa:usedProcedure", "gcdfo:MethodX")
    assert live(builder, node, iri.column(spec.slug, spec.version, "source", "lower"), L(-120.0))
    assert any("estimate_type" in q.object.value for q in builder.quads if isinstance(q.object, ox.Literal))
    assert not any("/sdp/" in q.predicate.value for q in builder.quads)


def test_critical_interpretations_are_once_per_column_with_real_dependency_paths(tmp_path, compiler_vocab):
    data = document()
    data["tables"][0]["columns"][3]["mark"] = {"aspect": "measure-counts", "confidence": "high", "evidence": ["Fictional count interpretation evidence."]}
    data["tables"][0]["columns"][1]["mark"] = {"aspect": "year-basis", "confidence": "high", "evidence": ["Fictional year evidence."]}
    spec, _, builder, _ = build(tmp_path, compiler_vocab, data, run=AgentRun("compiler-fixture", "actual-fixture-model", "2026-10-23"))
    variable = iri.column(spec.slug, spec.version, "source", "count")
    assert not objects(builder, variable, "qb:concept")
    concept_marks = [q for q in pending(builder) if q.object.subject == N(variable) and q.object.predicate == N("qb:concept")]
    assert len(concept_marks) == 1
    assert len([q for q in pending(builder) if q.object.predicate == N("qb:dimension")]) == 2
    for q in pending(builder):
        assert not live(builder, q.object.subject, q.object.predicate, q.object.object)
        assert objects(builder, q.subject, "prov:wasAttributedTo") == {N(iri.model_agent("actual-fixture-model"))}
        assert objects(builder, q.subject, "dcterms:created") == {L("2026-10-23", "xsd:date")}
    for stock, year in (("001/α", 2000), ("002", 2001)):
        node = iri.obs(spec.slug, spec.version, stock, year, expand("corp:variables/fixture-count"))
        assert live(builder, node, "prov:wasDerivedFrom", concept_marks[0].subject)
        assert not objects(builder, node, "smn:broodYear")
        assert not objects(builder, node, "qudt:unit")
        assert live(builder, node, iri.column(spec.slug, spec.version, "source", "period"), L(str(year), "xsd:gYear"))
    # Two source rows share a single concept interpretation, not two reviews.
    assert len(concept_marks) < 2


def test_missing_run_and_bad_vocab_are_transactional(tmp_path, compiler_vocab):
    data = document()
    data["tables"][0]["columns"][3]["mark"] = {"aspect": "measure-counts", "confidence": "high", "evidence": ["Fixture"]}
    spec = save_spec(tmp_path, data)
    root = package(tmp_path, spec)
    builder = GraphBuilder(compiler_vocab())
    builder.type("https://example.test/existing", "prov:Entity", "https://example.test/existing-graph")
    old = builder.quads
    with pytest.raises(SpecError, match="AgentRun"):
        compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24")
    assert builder.quads == old and not builder.marked
    bad = copy.deepcopy(spec)
    bad.tables[0]["columns"][3].pop("mark")
    bad.tables[0]["columns"][3]["decomposition"]["property"] = "smn:NotDeclared"
    with pytest.raises(UndeclaredIRIError, match="NotDeclared"):
        compile_dataset_graph(bad, root, builder=builder, build_date="2026-10-24")
    assert builder.quads == old and not builder.marked


def test_alternate_base_and_repeat_bytes(tmp_path, compiler_vocab):
    cfg = config.Config(base="https://example.test/alternate/", profile_base="https://example.test/profile/")
    spec, root, first, _ = build(tmp_path, compiler_vocab, cfg=cfg)
    second = GraphBuilder(first.vocab, cfg=cfg)
    compile_dataset_graph(spec, root, builder=second, build_date="2026-10-24")
    assert first.trig() == second.trig()
    assert config.DEFAULT_BASE.encode() not in first.trig()
    assert cfg.base.encode() in first.trig()
    assert cfg.profile_base.encode() in first.trig()


@pytest.mark.parametrize("date", [None, "2026-02-30", "20261024", "2026-10-24T00:00:00Z"])
def test_explicit_real_build_date_required(tmp_path, compiler_vocab, date):
    spec = save_spec(tmp_path)
    root = package(tmp_path, spec)
    builder = GraphBuilder(compiler_vocab())
    with pytest.raises(SpecError, match="date"):
        compile_dataset_graph(spec, root, builder=builder, build_date=date)
    assert not builder.quads


def test_actual_sdk_observation_extension_is_read_and_grain_checked(tmp_path, compiler_vocab):
    spec = save_spec(tmp_path)
    root = package(tmp_path, spec)
    structures, components = [], []
    for measure in ("count", "other_count"):
        structures.append({"dataset_id": spec.slug, "table_id": "source", "observation_structure_id": measure,
                           "structure_label": measure, "structure_description": "Fixture"})
        for n, (name, role) in enumerate([("stock_id", "dimension"), ("period", "dimension"), ("phase", "attribute"), (measure, "measure")], 1):
            components.append({"dataset_id": spec.slug, "table_id": "source", "observation_structure_id": measure,
                               "component_order": n, "column_name": name, "component_role": role,
                               "component_relation_iri": "", "required_when_observed": name != "phase"})
    ms.write_sdp_observation_structures(root, pd.DataFrame(structures), pd.DataFrame(components))
    builder = GraphBuilder(compiler_vocab())
    compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24")
    changed = copy.deepcopy(spec)
    changed.observations[0]["dimensions"].remove("stock_id")
    with pytest.raises(SpecError, match="grain differs"):
        compile_dataset_graph(changed, root, builder=GraphBuilder(builder.vocab), build_date="2026-10-24")


def test_incomplete_extension_fails_instead_of_being_ignored(tmp_path, compiler_vocab):
    spec = save_spec(tmp_path)
    root = package(tmp_path, spec)
    extension = root / "metadata/structure/observation_structures.csv"
    extension.parent.mkdir(parents=True)
    extension.write_text("broken\n")
    builder = GraphBuilder(compiler_vocab())
    with pytest.raises(ValueError):
        compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24")
    assert not builder.quads


def test_source_sssom_manual_is_preserved_agent_rows_are_literal_gaps(tmp_path, compiler_vocab):
    spec = save_spec(tmp_path)
    root = package(tmp_path, spec)
    subject = _source_code_iri(spec.slug, "source", "phase", "A")
    metadata = {"sssom_version": "1.1", "mapping_set_id": "https://example.test/mappings/fixture",
                "mapping_set_version": "2026-10-23", "license": spec.source["licence"],
                "subject_source": "https://example.test/source", "subject_source_version": "fixture",
                "object_source": "https://w3id.org/gcdfo/salmon", "object_source_version": "test-gcdfo",
                "curie_map": {"gcdfo": config.GCDFO_NS}}
    rows = pd.DataFrame([
        {"subject_id": subject, "predicate_id": "skos:exactMatch", "object_id": "gcdfo:MethodX", "mapping_justification": "semapv:ManualMappingCuration"},
        {"subject_id": subject, "predicate_id": "skos:closeMatch", "object_id": "gcdfo:MethodX", "mapping_justification": "semapv:AgentBasedMatching", "comment": "Original agent source evidence retained, not claimed by this build."},
    ]).fillna("")
    ms.write_sdp_sssom(root, {"metadata": metadata, "mappings": rows})
    builder = GraphBuilder(compiler_vocab())
    compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24", run=AgentRun("different-run", "different-model", "2026-10-24"))
    assert live(builder, subject, "skos:exactMatch", "gcdfo:MethodX")
    assert not live(builder, subject, "skos:closeMatch", "gcdfo:MethodX")
    assert not any(isinstance(q.object, ox.Triple) and q.object.predicate == N("skos:closeMatch") for q in builder.quads)
    assert any("Original agent source evidence" in q.object.value for q in builder.quads if isinstance(q.object, ox.Literal))
    assert not builder.marked
    assert not any(q.predicate == N("prov:wasAttributedTo") for q in builder.quads)


def test_genuine_ordered_decomposition_preserves_matched_components_and_gaps(tmp_path, compiler_vocab):
    spec = save_spec(tmp_path)
    root = package(tmp_path, spec)
    rows = []
    for order, role, status, target, label in (
        (1, "property", "matched", expand("smn:TermA"), "Fixture property"),
        (2, "entity", "matched", expand("smn:TermB"), "Fixture entity"),
        (3, "constraint", "matched", expand("smn:TermA"), "Explicit first constraint"),
        (4, "constraint", "gap", "", "Unresolved second constraint"),
        (5, "unit", "matched", expand("unit:NUM"), "Number"),
    ):
        rows.append({"dataset_id": spec.slug, "table_id": "source", "column_name": "count",
                     "measurement_concept_iri": expand("corp:variables/fixture-count"), "component_order": order,
                     "component_role": role, "component_status": status, "component_relation": "",
                     "related_component_order": "", "component_iri": target, "component_label": label,
                     "rationale": "Explicit fictional source component or recorded gap.", "source": "Fixture dictionary",
                     "source_version": "test-1", "source_url": "https://example.test/dictionary", "provenance": "Fixture source row"})
    ms.write_sdp_measurement_decompositions(root, pd.DataFrame(rows))
    builder = GraphBuilder(compiler_vocab())
    compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24")
    variable = iri.column(spec.slug, spec.version, "source", "count")
    assert live(builder, variable, "iop:hasConstraint", "smn:TermA")
    assert any("Unresolved second constraint" in q.object.value for q in builder.quads if isinstance(q.object, ox.Literal))
    # The validated manifest is a hashed input, rather than inferred or
    # flattened away. Corrupting it must fail before extending the builder.
    artifact = root / "metadata/semantic/measurement-decompositions.csv"
    original = artifact.read_bytes()
    artifact.write_bytes(original.replace(b"Fixture property", b"Changed property"))
    unchanged = GraphBuilder(builder.vocab)
    with pytest.raises(ValueError, match="manifest"):
        compile_dataset_graph(spec, root, builder=unchanged, build_date="2026-10-24")
    assert not unchanged.quads
    artifact.write_bytes(original)
    dictionary = root / "metadata/column_dictionary.csv"
    fields = pd.read_csv(dictionary, keep_default_na=False)
    fields.loc[fields["column_name"] == "count", "term_iri"] = expand("psc:PSC-CV-999999")
    fields.to_csv(dictionary, index=False)
    # The genuine public reader independently rejects a byte-valid
    # decomposition whose measurement concept no longer matches its field.
    with pytest.raises(ValueError):
        ms.read_sdp_measurement_decompositions(root)


def test_multiple_tables_use_explicit_source_keys_without_aggregation(tmp_path, compiler_vocab):
    data = document()
    second = copy.deepcopy(data["tables"][0])
    second["id"], second["file"] = "other_source", "other.csv"
    data["tables"].append(second)
    data["source"]["files"].append({"name": "other.csv", "url": "https://example.test/other.csv", "sha256": "b" * 64})
    data["identity"].append({"table": "other_source", "column": "stock_id", "kind": "stock", "authority": "fixture"})
    block = copy.deepcopy(data["observations"][0])
    block["table"] = "other_source"
    data["observations"].append(block)
    spec = save_spec(tmp_path, data)
    other = data_frame()
    other["stock_id"] = ["second-001", "second-002"]
    root = package(tmp_path, spec, {"source": data_frame(), "other_source": other})
    builder = GraphBuilder(compiler_vocab())
    compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24")
    observations = {q.subject for q in builder.quads if q.predicate == N("rdf:type") and q.object == N("qb:Observation")}
    assert len(observations) == 6
    assert _source_code_iri(spec.slug, "source", "phase", "A") != _source_code_iri(spec.slug, "other_source", "phase", "A")
    assert {float(o.value) for node in observations for o in objects(builder, node, "sosa:hasSimpleResult")} == {-99.0, 0.0, 4.5}


def test_pending_binding_cannot_leak_through_existing_caller_graph(tmp_path, compiler_vocab):
    data = document()
    data["tables"][0]["columns"][3]["mark"] = {"aspect": "measure-counts", "confidence": "high", "evidence": ["Fictional interpretation"]}
    spec = save_spec(tmp_path, data)
    root = package(tmp_path, spec)
    builder = GraphBuilder(compiler_vocab())
    builder.add(iri.column(spec.slug, spec.version, "source", "count"), "qb:concept",
                expand("corp:variables/fixture-count"), "https://example.test/other-graph")
    old = builder.quads
    with pytest.raises(SpecError, match="already live"):
        compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24", run=AgentRun("fixture", "fixture-model", "2026-10-24"))
    assert builder.quads == old and not builder.marked


def test_source_package_semantic_disagreement_is_not_silently_overridden(tmp_path, compiler_vocab):
    spec = save_spec(tmp_path)
    root = package(tmp_path, spec)
    changed = copy.deepcopy(spec)
    changed.tables[0]["columns"][3]["unit"] = "unit:KiloGM"
    builder = GraphBuilder(compiler_vocab())
    with pytest.raises(SpecError, match="disagreement"):
        compile_dataset_graph(changed, root, builder=builder, build_date="2026-10-24")
    assert not builder.quads


def test_csvw_table_links_packaged_resource_not_differently_named_raw_input(tmp_path, compiler_vocab):
    data = document()
    data["tables"][0]["file"] = "raw.csv"
    data["source"]["files"][0]["name"] = "raw.csv"
    data["source"]["files"][0]["url"] = "https://example.test/raw.csv"
    spec = save_spec(tmp_path, data)
    root = package(tmp_path, spec, package_files={"source": "table.csv"})
    assert (root / "data/table.csv").exists()
    builder = GraphBuilder(compiler_vocab())
    compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24")
    table = iri.table(spec.slug, spec.version, "source")
    assert objects(builder, table, "csvw:url") == {L("data/table.csv")}
    assert not live(builder, table, "csvw:url", L("raw.csv"))
    assert any(q.predicate == N("prov:hadPrimarySource") and q.object == N("https://example.test/raw.csv") for q in builder.quads)


@pytest.mark.parametrize("field", ["term_iri", "unit_iri"])
def test_missing_packaged_semantic_binding_is_not_completed_from_spec(tmp_path, compiler_vocab, field):
    spec = save_spec(tmp_path)
    root = package(tmp_path, spec)
    path = root / "metadata/column_dictionary.csv"
    dictionary = pd.read_csv(path, keep_default_na=False)
    dictionary.loc[dictionary["column_name"] == "count", field] = ""
    dictionary.to_csv(path, index=False)
    builder = GraphBuilder(compiler_vocab())
    with pytest.raises(SpecError, match="disagreement"):
        compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24")
    assert not builder.quads


def test_conflicting_dictionary_and_spec_components_are_not_combined(tmp_path, compiler_vocab):
    spec = save_spec(tmp_path)
    root = package(tmp_path, spec)
    path = root / "metadata/column_dictionary.csv"
    dictionary = pd.read_csv(path, keep_default_na=False)
    dictionary.loc[dictionary["column_name"] == "count", "property_iri"] = expand("smn:TermB")
    dictionary.to_csv(path, index=False)
    builder = GraphBuilder(compiler_vocab())
    with pytest.raises(SpecError, match="decomposition property disagreement"):
        compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24")
    assert not builder.quads


def test_shared_canonical_concept_gets_no_source_decomposition_or_unit_definition(tmp_path, compiler_vocab):
    data = document()
    canonical = "psc:PSC-CV-999999"
    columns = data["tables"][0]["columns"]
    columns[3]["concept"] = canonical
    columns[4]["concept"] = canonical
    columns[4]["unit"] = "unit:KiloGM"
    # Source keys differ across separate observation blocks, so sharing a
    # concept does not introduce an observation IRI collision. A column-only
    # fixture also tests definitions independently of numeric projection.
    data["observations"] = []
    spec = save_spec(tmp_path, data)
    root = package(tmp_path, spec)
    dictionary = root / "metadata/column_dictionary.csv"
    rows = pd.read_csv(dictionary, keep_default_na=False)
    rows.loc[rows["column_name"] == "other_count", "property_iri"] = expand("smn:TermB")
    rows.loc[rows["column_name"] == "other_count", "entity_iri"] = expand("smn:TermA")
    rows.to_csv(dictionary, index=False)
    builder = GraphBuilder(compiler_vocab())
    compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24")
    first, second = (iri.column(spec.slug, spec.version, "source", name) for name in ("count", "other_count"))
    assert objects(builder, first, "qb:concept") == {N(canonical)}
    assert objects(builder, second, "qb:concept") == {N(canonical)}
    assert objects(builder, first, "qudt:unit") == {N("unit:NUM")}
    assert objects(builder, second, "qudt:unit") == {N("unit:KiloGM")}
    assert objects(builder, first, "iop:hasProperty") == {N("smn:TermA")}
    assert objects(builder, second, "iop:hasProperty") == {N("smn:TermB")}
    assert not any(q.subject == N(canonical) for q in builder.quads)


def test_null_licence_private_draft_keeps_source_rights_and_explicit_publication_gap(tmp_path, compiler_vocab):
    data = document()
    data["source"]["licence"] = None
    spec, _, builder, _ = build(tmp_path, compiler_vocab, data)
    dataset = iri.dataset(spec.slug, spec.version)
    assert not objects(builder, dataset, "dcterms:license")
    assert objects(builder, dataset, "dcterms:rights") == {L(data["source"]["attribution"])}
    assert objects(builder, dataset, "dcterms:accessRights") == {L("redistribution unconfirmed", "xsd:string")}
    assert any("publication licence" in v.value for v in objects(builder, dataset, "skos:note"))
    assert not spec.public


def test_null_licence_cannot_compile_as_confirmed_redistribution(tmp_path, compiler_vocab):
    spec = save_spec(tmp_path)
    root = package(tmp_path, spec)
    source = {**spec.source, "licence": None, "redistribution": "confirmed"}
    builder = GraphBuilder(compiler_vocab())
    with pytest.raises(SpecError, match="requires a real source.licence"):
        compile_dataset_graph(replace(spec, source=source), root, builder=builder, build_date="2026-10-24")
    assert not builder.quads


@pytest.mark.parametrize("aspect,confidence", [("label", "high"), ("description", "medium")])
def test_noncritical_year_mark_cannot_approve_critical_pending_basis(tmp_path, compiler_vocab, aspect, confidence):
    spec = save_spec(tmp_path)
    root = package(tmp_path, spec)
    # Deliberately call the compiler directly, without validate_spec(), to
    # prove the public entry point also refuses this scope error. Its source
    # package is genuine, so this cannot be hidden by reader/test doubles.
    changed = copy.deepcopy(spec)
    columns = changed.tables[0]["columns"]
    columns[3]["mark"] = {"aspect": "measure-counts", "confidence": "high",
                           "evidence": ["Critical pending interpretation of the count."]}
    columns[1]["mark"] = {"aspect": aspect, "confidence": confidence,
                           "evidence": ["Spelling/description review only; no calendar evidence."]}
    builder = GraphBuilder(compiler_vocab())
    builder.type("https://example.test/prior-source", "prov:Entity", "https://example.test/prior-graph")
    before = builder.quads
    with pytest.raises(SpecError, match="year_column mark.*must be critical"):
        compile_dataset_graph(changed, root, builder=builder, build_date="2026-10-24",
                              run=AgentRun("fixture", "actual-fixture-model", "2026-10-24"))
    assert builder.quads == before and not builder.marked


def test_attribute_unit_cannot_be_auto_accepted_by_label_only_evidence(tmp_path, compiler_vocab):
    data = document()
    column = next(c for c in data["tables"][0]["columns"] if c["name"] == "se")
    column["unit"] = "unit:NUM"
    column["mark"] = {"aspect": "label", "confidence": "high", "evidence": ["Spelling checked only."]}
    spec = save_spec(tmp_path, data)
    root = package(tmp_path, spec)
    builder = GraphBuilder(compiler_vocab())
    builder.type("https://example.test/prior-source", "prov:Entity", "https://example.test/prior-graph")
    before = builder.quads
    with pytest.raises(SpecError, match="semantic.*mark.*must be critical"):
        compile_dataset_graph(spec, root, builder=builder, build_date="2026-10-24",
                              run=AgentRun("fixture", "actual-fixture-model", "2026-10-24"))
    assert builder.quads == before and not builder.marked


def test_pure_descriptive_attribute_mark_remains_noncritical(tmp_path, compiler_vocab):
    data = document()
    column = next(c for c in data["tables"][0]["columns"] if c["name"] == "se")
    column["label"] = "Source standard error label"
    column["mark"] = {"aspect": "label", "confidence": "high", "evidence": ["Exact source label checked."]}
    spec, _, builder, _ = build(tmp_path, compiler_vocab, data,
                               run=AgentRun("fixture", "actual-fixture-model", "2026-10-24"))
    source = iri.column(spec.slug, spec.version, "source", "se")
    assert objects(builder, source, "csvw:title") == {L("Source standard error label")}
    assert not objects(builder, source, "qudt:unit")
    assert len(builder.marked) == 1 and set(builder.marked.values()) == {"agentAccepted"}
