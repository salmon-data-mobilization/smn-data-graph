"""Offline contract tests: specs are data, not executable parsers or approvals."""

from __future__ import annotations

import copy
import hashlib
import socket
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from conftest import tiny_sources
from salmongraph import config, provenance, spec as specs
from salmongraph.spec import SpecError, load_spec, spec_path, spec_sha256, validate_spec
from salmongraph.vocab import VocabIndex


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("spec tests must not use the network")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture
def vocab(tmp_path):
    """Tiny owning vocabularies, with explicit declarations for year/age slots."""
    sources = []
    for source in tiny_sources():
        path = tmp_path / f"{source.key}.ttl"
        text = source.path.read_text()
        if source.key == "smn":
            text += "\n" + "\n".join(
                f"<https://w3id.org/smn/{term}> a <http://www.w3.org/2004/02/skos/core#Concept> ."
                for term in ("broodYear", "returnYear", "GilbertRichAgeNotation", "EuropeanAgeNotation"))
        path.write_text(text)
        sources.append(replace(source, path=path))
    return VocabIndex(sources, cfg=config.Config(), offline=True)


@pytest.fixture
def document():
    return {
        "spec_version": 1, "slug": "fixture-salmon", "version": "2026.01",
        "title": "Fixture salmon records", "description": "Source-stated fixture, not biological evidence.",
        "source": {
            "publisher": "Fixture authority", "landing_page": "https://example.org/source",
            "licence": "https://creativecommons.org/licenses/by/4.0/",
            "redistribution": "confirmed", "attribution": "Fixture authority",
            "files": [{"name": "fish.csv", "url": "https://example.org/fish.csv", "sha256": "a" * 64}],
        },
        "tables": [{"id": "fish", "file": "fish.csv", "keys": ["stock", "year"], "columns": [
            {"name": "stock", "role": "identifier", "datatype": "string"},
            {"name": "year", "role": "dimension", "datatype": "integer"},
            {"name": "count", "role": "measure", "datatype": "number", "concept": "psc:PSC-CV-999999",
             "unit": "unit:NUM", "year_basis": "smn:broodYear"},
        ]}],
        "identity": [{"table": "fish", "column": "stock", "kind": "stock", "authority": "fixture", "species": "Sockeye"}],
        "observations": [{"table": "fish", "key": ["stock", "year"], "dimensions": ["stock", "year"],
                          "year_column": "year", "measures": ["count"]}],
    }


def saved(tmp_path, document, name="fixture.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_load_defaults_and_pins_exact_file_bytes(tmp_path, document, vocab):
    path = saved(tmp_path, document)
    spec = load_spec(path)
    assert spec.parser == "csv"
    assert spec.public is True
    assert spec.cross_source_checks == spec.term_requests == ()
    assert isinstance(spec.tables, tuple)
    assert spec.tables[0]["columns"][0]["codes"] == {}
    assert "mark" not in spec.tables[0]["columns"][2]
    assert spec.source == document["source"]
    assert spec_sha256(spec) == hashlib.sha256(path.read_bytes()).hexdigest()
    assert load_spec(path) == spec
    assert validate_spec(spec, vocab) == []


def test_expands_only_iri_slots_with_configured_separate_namespace(tmp_path, document):
    document["description"] = "Evidence says smn:TermA; do not rewrite this quote."
    column = document["tables"][0]["columns"][2]
    column.update(concept="corp:variable/test", codes={"unit": "smn:TermA", "unknown": None},
                  decomposition={"property": "smn:TermA", "object_of_interest": "smn:TermB",
                                 "constraints": ["corp:constraint/female"], "statistical_modifier": None})
    with config.override(base="https://example.org/smn-data-graph/"):
        spec = load_spec(saved(tmp_path, document))
    c = spec.tables[0]["columns"][2]
    assert c["concept"] == "https://example.org/smn-data-graph/profile/variable/test"
    assert c["decomposition"]["constraints"] == ["https://example.org/smn-data-graph/profile/constraint/female"]
    assert c["codes"] == {"unit": config.SMN_NS + "TermA", "unknown": None}
    assert spec.description == document["description"]
    assert spec.identity[0]["species"] == "Sockeye"


def test_unconfirmed_redistribution_is_valid_but_not_public(tmp_path, document, vocab):
    document["source"]["redistribution"] = "unconfirmed"
    spec = load_spec(saved(tmp_path, document))
    assert spec.public is False
    assert validate_spec(spec, vocab) == []


@pytest.mark.parametrize("slug", ["../x", "/tmp/x", "x/y", "corpus", "vocab", "Bad", "", "..", "a..b", "a.b"])
def test_slug_rejects_unsafe_and_reserved_names(slug):
    with pytest.raises(SpecError):
        spec_path(slug)


def test_slug_loading_uses_only_specs_dir(tmp_path, document, monkeypatch):
    monkeypatch.setattr(specs, "SPECS_DIR", tmp_path)
    saved(tmp_path, document, "fixture-salmon.yaml")
    assert load_spec("fixture-salmon").slug == "fixture-salmon"
    assert spec_path("fixture-salmon") == tmp_path / "fixture-salmon.yaml"


def test_bare_yaml_filename_is_a_path_not_a_slug(tmp_path, document, monkeypatch):
    saved(tmp_path, document)
    monkeypatch.chdir(tmp_path)
    assert load_spec("fixture.yaml").slug == document["slug"]


def test_dotted_versions_and_yaml_filenames_remain_valid(tmp_path, document, vocab):
    document["version"] = "2026.10.24.1"
    spec = load_spec(saved(tmp_path, document, "fixture.release.yaml"))
    assert spec.version == "2026.10.24.1"
    assert validate_spec(spec, vocab) == []
    document["slug"] = "fixture.salmon"
    with pytest.raises(SpecError, match="invalid spec structure"):
        load_spec(saved(tmp_path, document))


@pytest.mark.parametrize("mutate", [
    lambda d: d["source"]["files"][0].update(name="../escape.csv"),
    lambda d: d["source"]["files"][0].update(name="/tmp/escape.csv"),
    lambda d: d["tables"][0].update(file="subdir/fish.csv"),
    lambda d: d.update(parser="os:system('touch x')"),
    lambda d: d.update(parser="../parser:read"),
    lambda d: d.update(parser="my..module:read"),
    lambda d: d.update(parser="my.module:read;run"),
    lambda d: d["source"]["files"][0].update(sha256="not-pinned"),
    lambda d: d.update(variables=[]),
    lambda d: d.update(agent_run={"model": "unknown"}),
    lambda d: d["tables"][0]["columns"][2].update(assertions={}),
    lambda d: d["observations"][0].pop("year_column"),
    lambda d: d.update(spec_version=2),
])
def test_static_schema_fails_closed_on_unsupported_or_unsafe_forms(tmp_path, document, mutate):
    mutate(document)
    with pytest.raises(SpecError, match="invalid spec structure"):
        load_spec(saved(tmp_path, document))


def test_valid_bespoke_parser_is_data_not_imported(tmp_path, document, monkeypatch):
    document["parser"] = "nonexistent.fixture_parser:read_table"
    spec = load_spec(saved(tmp_path, document))
    assert spec.parser == document["parser"]


@pytest.mark.parametrize("text", [
    "!!python/object/apply:os.system ['false']",
    "slug: first\nslug: second\n",
    "one: &a [1]\ntwo: *a\n",
    "one: &a [*a]\n",
    "[missing, close",
    "null\n",
    "42: unquoted numeric code\n",
])
def test_unsafe_ambiguous_or_malformed_yaml_fails(tmp_path, text):
    path = tmp_path / "broken.yaml"
    path.write_text(text)
    with pytest.raises(SpecError):
        load_spec(path)


def test_missing_invalid_utf8_and_wrong_file_type_fail_cleanly(tmp_path):
    with pytest.raises(SpecError, match="cannot read"):
        load_spec(tmp_path / "missing.yaml")
    path = tmp_path / "bad.yaml"
    path.write_bytes(b"\xff")
    with pytest.raises(SpecError, match="cannot read"):
        load_spec(path)
    with pytest.raises(SpecError, match="must end"):
        load_spec(tmp_path / "spec.py")


def test_hash_rejects_file_changed_after_load(tmp_path, document):
    path = saved(tmp_path, document)
    spec = load_spec(path)
    path.write_text(path.read_text() + "\n# changed source bytes\n")
    with pytest.raises(SpecError, match="changed since load"):
        spec_sha256(spec)
    assert spec_sha256(load_spec(path)) == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(SpecError, match="no source path"):
        spec_sha256(replace(spec, path=None))


def test_collects_sorted_vocabulary_and_semantic_errors(tmp_path, document, vocab):
    document["tables"][0]["keys"].append("absent")
    column = document["tables"][0]["columns"][2]
    column.update(concept="smn:NotDeclared", unit=None, year_basis=None,
                  uncertainty={"cv": "missing_cv"})
    document["identity"][0]["table"] = "not_a_table"
    document["observations"][0]["measures"].append("year")
    problems = validate_spec(load_spec(saved(tmp_path, document)), vocab)
    assert problems == sorted(set(problems))
    assert len(problems) == 8
    for expected in ["unknown column 'absent'", "required for a measure", "missing_cv", "not_a_table",
                     "not a measure column", "NotDeclared"]:
        assert any(expected in p for p in problems)


def test_quoted_ontology_urls_are_not_term_assertions(tmp_path, document, vocab):
    quote = "https://w3id.org/smn/UndeclaredQuotedTerm says this is a source example, not a declared concept."
    document["description"] = quote
    document["source"]["landing_page"] = "https://w3id.org/smn/UndeclaredSourceDocument"
    column = document["tables"][0]["columns"][2]
    column["description"] = quote
    column["mark"] = {"aspect": "measure-counts", "confidence": "medium", "evidence": [quote]}
    spec = load_spec(saved(tmp_path, document))
    assert spec.description == quote
    assert spec.tables[0]["columns"][2]["mark"]["evidence"] == [quote]
    assert validate_spec(spec, vocab) == []
    column["concept"] = "smn:UndeclaredActualConcept"
    problems = validate_spec(load_spec(saved(tmp_path, document)), vocab)
    assert len(problems) == 1 and "UndeclaredActualConcept" in problems[0]


@pytest.mark.parametrize("value", ["def:Thing", config.DEFAULT_BASE + "def/Thing"])
def test_legacy_def_iris_block_even_when_vocabulary_guard_exempts_them(tmp_path, document, vocab, value):
    document["tables"][0]["columns"][2]["concept"] = value
    assert any("legacy def:" in e for e in validate_spec(load_spec(saved(tmp_path, document)), vocab))


def test_unknown_curie_and_unsafe_iri_are_parse_errors(tmp_path, document):
    document["tables"][0]["columns"][2]["concept"] = "madeup:Thing"
    with pytest.raises(SpecError, match="unknown IRI prefix"):
        load_spec(saved(tmp_path, document))
    document["tables"][0]["columns"][2]["concept"] = "https://example.org/<unsafe>"
    with pytest.raises(SpecError, match="unsafe IRI"):
        load_spec(saved(tmp_path, document))


def test_marks_are_explicit_critical_candidates_never_self_approved(tmp_path, document, vocab):
    column = document["tables"][0]["columns"][2]
    column["mark"] = {"aspect": "measure-counts", "confidence": "high", "evidence": ["Source dictionary p. 4: fixture quote."]}
    spec = load_spec(saved(tmp_path, document))
    assert validate_spec(spec, vocab) == []
    mark = spec.tables[0]["columns"][2]["mark"]
    assert provenance.review_status(mark["confidence"], provenance.criticality_of(mark["aspect"])) == "awaitingReview"
    assert "review_status" not in mark and "asserted_by" not in mark
    column["mark"]["review_status"] = "humanAccepted"
    with pytest.raises(SpecError, match="Additional properties"):
        load_spec(saved(tmp_path, document))


def test_marks_reject_unknown_aspect_missing_evidence_and_downgrade(tmp_path, document, vocab):
    column = document["tables"][0]["columns"][2]
    column["mark"] = {"aspect": "label", "confidence": "high", "evidence": ["quote"]}
    assert any("must be critical" in p for p in validate_spec(load_spec(saved(tmp_path, document)), vocab))
    column["mark"]["aspect"] = "made-up-aspect"
    assert any("unknown provenance aspect" in p for p in validate_spec(load_spec(saved(tmp_path, document)), vocab))
    column["mark"]["evidence"] = []
    with pytest.raises(SpecError):
        load_spec(saved(tmp_path, document))


def test_explicit_integer_year_binding_and_basis_are_required(tmp_path, document, vocab):
    document["observations"][0]["year_column"] = "stock"
    problems = validate_spec(load_spec(saved(tmp_path, document)), vocab)
    assert any("requires an integer" in p for p in problems)
    document["observations"][0]["dimensions"].remove("stock")
    assert any("must occur" in p for p in validate_spec(load_spec(saved(tmp_path, document)), vocab))
    document["tables"][0]["columns"][2]["year_basis"] = "smn:TermA"
    assert any("expected smn:broodYear" in p for p in validate_spec(load_spec(saved(tmp_path, document)), vocab))


def test_age_and_profile_decomposition_checks(tmp_path, document, vocab):
    measure = document["tables"][0]["columns"][2]
    measure["name"] = "age_4"
    document["observations"][0]["measures"] = ["age_4"]
    assert any("age_notation: required" in p for p in validate_spec(load_spec(saved(tmp_path, document)), vocab))
    measure["age_notation"] = "smn:EuropeanAgeNotation"
    measure["concept"] = "corp:variable/age-abundance"
    assert any("required for a compound" in p for p in validate_spec(load_spec(saved(tmp_path, document)), vocab))
    measure["decomposition"] = {"property": "smn:TermA", "object_of_interest": "smn:TermB", "constraints": []}
    assert validate_spec(load_spec(saved(tmp_path, document)), vocab) == []
    measure["concept"] = "smn:TermA"
    assert any("only a corp:" in p for p in validate_spec(load_spec(saved(tmp_path, document)), vocab))


def test_duplicate_files_tables_columns_and_missing_refs_reported(tmp_path, document, vocab):
    document["source"]["files"].append(copy.deepcopy(document["source"]["files"][0]))
    document["tables"][0]["columns"].append(copy.deepcopy(document["tables"][0]["columns"][0]))
    document["tables"].append(copy.deepcopy(document["tables"][0]))
    document["tables"][0]["file"] = "missing.csv"
    problems = validate_spec(load_spec(saved(tmp_path, document)), vocab)
    assert all(any(x in p for p in problems) for x in ["duplicate file", "duplicate table", "duplicate column", "not present in source.files"])


def test_term_requests_and_expectations_are_checks_not_new_mappings(tmp_path, document, vocab):
    document["term_requests"] = [{"profile_concept": "corp:constraint/female", "says": "Source says female.", "mint_in": "smn", "columns": ["count"]}]
    document["cross_source_checks"] = [{"id": "fixture-check", "other": "other-fixture", "join": "stock", "measure": "count", "other_measure": "total", "tolerance": 0.005, "expect": "A hypothesis to test, not established equivalence."}]
    spec = load_spec(saved(tmp_path, document))
    assert validate_spec(spec, vocab) == []
    assert "matches" not in spec.term_requests[0]
    document["term_requests"][0]["columns"] = ["unknown"]
    document["cross_source_checks"][0]["measure"] = "unknown"
    problems = validate_spec(load_spec(saved(tmp_path, document)), vocab)
    assert any("unknown column" in p for p in problems)
    assert any("unknown measure" in p for p in problems)


def test_direct_dataclass_cannot_bypass_structure_or_vocabulary_checks(tmp_path, document, vocab):
    spec = load_spec(saved(tmp_path, document))
    tables = copy.deepcopy(spec.tables)
    tables[0]["columns"][2]["concept"] = "smn:MadeUp"
    assert any("MadeUp" in p for p in validate_spec(replace(spec, tables=tables), vocab))
    assert validate_spec(replace(spec, parser="os:system('x')"), vocab)


def test_codes_keep_explicit_unresolved_targets_and_reject_ambiguous_dimensions(tmp_path, document, vocab):
    document["identity"] = []
    column = document["tables"][0]["columns"][0]
    column["codes"] = {"source-code": None, "mapped-code": "smn:TermA"}
    spec = load_spec(saved(tmp_path, document))
    assert validate_spec(spec, vocab) == []
    assert spec.tables[0]["columns"][0]["codes"]["source-code"] is None
    document["identity"] = [{"table": "fish", "column": "stock", "kind": "stock", "authority": "fixture"}]
    assert any("ambiguous identity/code" in p for p in validate_spec(load_spec(saved(tmp_path, document)), vocab))
    column["codes"] = {}
    document["identity"] = []
    assert any("requires an explicit identity" in p for p in validate_spec(load_spec(saved(tmp_path, document)), vocab))


def test_critical_code_mapping_cannot_be_label_marked(tmp_path, document, vocab):
    column = document["tables"][0]["columns"][0]
    column.update(codes={"x": "smn:TermA"}, mark={"aspect": "label", "confidence": "high", "evidence": ["label quote"]})
    assert any("must be critical" in p for p in validate_spec(load_spec(saved(tmp_path, document)), vocab))


def test_nonfinite_tolerance_is_not_a_comparison_rule(tmp_path, document, vocab):
    document["cross_source_checks"] = [{"id": "bad-check", "other": "other", "join": "stock", "measure": "count", "other_measure": "count", "tolerance": float("nan"), "expect": "Unresolved expectation."}]
    assert any("must be a finite number" in p for p in validate_spec(load_spec(saved(tmp_path, document)), vocab))


def test_xlsx_requires_explicit_sheet_and_other_parsers_reject_it(tmp_path, document, vocab):
    document["parser"] = "xlsx"
    with pytest.raises(SpecError, match="sheet"):
        load_spec(saved(tmp_path, document))
    document["tables"][0]["sheet"] = "Raw observations"
    assert validate_spec(load_spec(saved(tmp_path, document)), vocab) == []
    for parser in ("csv", "pipelines.fixture:parse"):
        document["parser"] = parser
        with pytest.raises(SpecError):
            load_spec(saved(tmp_path, document))


def test_measure_and_uncertainty_datatypes_match_numeric_writer(tmp_path, document, vocab):
    document["tables"][0]["columns"][2]["datatype"] = "string"
    assert any("measure must be numeric" in message for message in validate_spec(load_spec(saved(tmp_path, document)), vocab))
    document["tables"][0]["columns"][2]["datatype"] = "number"
    document["tables"][0]["columns"][2]["uncertainty"] = {"standard_error": "stock"}
    assert any("referenced column must be numeric" in message for message in validate_spec(load_spec(saved(tmp_path, document)), vocab))


def test_unknown_licence_is_truthful_only_for_private_unconfirmed_source(tmp_path, document, vocab):
    document["source"]["licence"] = None
    with pytest.raises(SpecError):
        load_spec(saved(tmp_path, document))
    document["source"]["redistribution"] = "unconfirmed"
    spec = load_spec(saved(tmp_path, document))
    assert spec.source["licence"] is None and spec.public is False
    assert validate_spec(spec, vocab) == []


@pytest.mark.parametrize("confidence", ["high", "medium", "low"])
def test_year_column_label_evidence_cannot_govern_year_basis(tmp_path, document, vocab, confidence):
    document["tables"][0]["columns"][2]["mark"] = {
        "aspect": "measure-counts", "confidence": "high", "evidence": ["Critical count interpretation pending review."]}
    spelling = {"aspect": "label", "confidence": confidence, "evidence": ["Source field spelling only."]}
    document["tables"][0]["columns"][1]["mark"] = spelling
    spec = load_spec(saved(tmp_path, document))
    problems = validate_spec(spec, vocab)
    assert any("year basis must be critical" in p for p in problems)
    assert spec.tables[0]["columns"][1]["mark"] == spelling  # Never relabel evidence as critical.


@pytest.mark.parametrize("semantics", [
    {"concept": "smn:TermA"}, {"unit": "unit:NUM"}, {"year_basis": "smn:broodYear"},
    {"age_notation": "smn:EuropeanAgeNotation"}, {"estimate_type": "gcdfo:MethodX"},
    {"method": "gcdfo:MethodX"},
    {"concept": "corp:variable/source-attribute", "decomposition": {
        "property": "smn:TermA", "object_of_interest": "smn:TermB", "constraints": []}},
])
def test_nonmeasure_semantics_cannot_be_accepted_from_label_only_evidence(tmp_path, document, vocab, semantics):
    attribute = {"name": "source_attribute", "role": "attribute", "datatype": "number", **semantics,
                 "mark": {"aspect": "label", "confidence": "high", "evidence": ["Label spelling only."]}}
    document["tables"][0]["columns"].append(attribute)
    problems = validate_spec(load_spec(saved(tmp_path, document)), vocab)
    assert any("governing column semantics or year basis must be critical" in p for p in problems)


@pytest.mark.parametrize("aspect", ["label", "description"])
def test_descriptive_only_column_marks_remain_valid(tmp_path, document, vocab, aspect):
    document["tables"][0]["columns"].append({"name": "source_note", "role": "attribute", "datatype": "string",
        "label": "Source note", "description": "Source text.",
        "mark": {"aspect": aspect, "confidence": "high", "evidence": ["Source text evidence."]}})
    assert validate_spec(load_spec(saved(tmp_path, document)), vocab) == []


def test_explicit_critical_year_mark_remains_pending_and_valid(tmp_path, document, vocab):
    document["tables"][0]["columns"][1]["mark"] = {
        "aspect": "year-basis", "confidence": "high", "evidence": ["Calendar interpretation awaiting review."]}
    spec = load_spec(saved(tmp_path, document))
    assert validate_spec(spec, vocab) == []
    mark = spec.tables[0]["columns"][1]["mark"]
    assert provenance.review_status(mark["confidence"], provenance.criticality_of(mark["aspect"])) == "awaitingReview"
