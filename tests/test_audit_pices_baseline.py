"""Regression fixtures for the independent legacy-baseline artifact audit."""

from contextlib import redirect_stdout
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

import pyoxigraph as ox

SPEC = importlib.util.spec_from_file_location(
    "audit_pices_baseline", Path(__file__).resolve().parents[1] / "scripts/audit_pices_baseline.py"
)
audit_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_cli)

BASE = audit_cli.LEGACY_BASE
SLUG = audit_cli.SLUG
PREFIX = """@prefix ex: <https://example.org/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix qb: <http://purl.org/linked-data/cube#> .
@prefix smn: <https://w3id.org/smn/> .
@prefix gcdfo: <https://w3id.org/gcdfo/salmon#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix csvw: <http://www.w3.org/ns/csvw#> .
@prefix iop: <https://w3id.org/iadopt/ont/> .
"""


class BaselineAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pkg = self.root / "packages" / SLUG
        self.summary = self.pkg / "review/graph-summary.json"
        self.package = self.pkg / "datapackage.json"
        self.graph = self.root / "graph" / f"{SLUG}.trig"

    def fixture(self, *, metadata="ex:s ex:p ex:o .", identity="", cube="", fields=None,
                duplicate=False, base=BASE, extra_graph=""):
        self.graph.parent.mkdir(parents=True, exist_ok=True)
        self.summary.parent.mkdir(parents=True, exist_ok=True)
        content = PREFIX + f"<{base}graph/{SLUG}/metadata> {{ {metadata} }}\n"
        if duplicate:
            content += f"<{base}graph/{SLUG}/metadata> {{ {metadata} }}\n"
        if identity:
            content += f"<{base}graph/{SLUG}/identity> {{ {identity} }}\n"
        if cube:
            content += f"<{base}graph/{SLUG}/cube> {{ {cube} }}\n"
        content += extra_graph
        self.graph.write_text(content)
        store = ox.Store()
        store.load(input=content, format=ox.RdfFormat.TRIG)
        roles = ("metadata", "mappings", "identity", "cube", "provenance")
        counts = {role: sum(1 for q in store if q.graph_name == ox.NamedNode(f"{base}graph/{SLUG}/{role}"))
                  for role in roles}
        self.summary.write_text(json.dumps({"quads_dataset": len(store), "per_graph": counts,
                                            "graph_file": str(self.graph.relative_to(self.root))}))
        self.package.write_text(json.dumps({"resources": [
            {"name": "metadata", "schema": "https://example.org/schema"},
            {"name": "nuseds_cuid_streamid", "schema": {"fields": fields or []}},
        ]}))
        return audit_cli.audit(self.root, base)

    @staticmethod
    def check(report, name):
        return next(c for c in report["checks"] if c["id"] == name)

    def invoke(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = audit_cli.main(["--root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def test_correct_counts_and_hashes_are_repeatable(self):
        report = self.fixture()
        self.assertEqual(report, audit_cli.audit(self.root))
        self.assertEqual(self.check(report, "saved_graph_counts")["status"], "pass")
        self.assertEqual(report["status"], "scoped_checks_passed")
        self.assertEqual(len(report["inputs"]), 3)
        self.assertTrue(all(len(i["sha256"]) == 64 for i in report["inputs"]))
        self.assertEqual(self.invoke()[0], 0)

    def test_serialized_duplicate_triples_are_not_counted_as_unique_quads(self):
        report = self.fixture(duplicate=True)
        evidence = self.check(report, "saved_graph_counts")["evidence"]
        self.assertEqual(evidence["parsed_unique_dataset"], 1)
        self.assertEqual(self.check(report, "saved_graph_counts")["status"], "pass")

    def compressed_graph(self, content):
        path = self.graph.with_suffix(".trig.gz")
        path.write_bytes(content)
        summary = json.loads(self.summary.read_text())
        summary["graph_file"] = str(path.relative_to(self.root))
        self.summary.write_text(json.dumps(summary))
        return path

    def test_valid_gzip_is_parsed_but_compressed_artifact_is_hashed(self):
        self.fixture()
        content = gzip.compress(self.graph.read_bytes(), mtime=0)
        path = self.compressed_graph(content)
        code, report = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(self.check(report, "saved_graph_counts")["status"], "pass")
        evidence = next(i for i in report["inputs"] if i["path"] == str(path.relative_to(self.root)))
        self.assertEqual(evidence["bytes"], len(content))
        self.assertEqual(evidence["sha256"], hashlib.sha256(content).hexdigest())

    def test_invalid_gzip_fails_closed_with_clean_input_error(self):
        self.fixture()
        self.compressed_graph(b"not a gzip file")
        code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "input_error")
        self.assertIn("Malformed or truncated gzip graph", report["error"])

    def test_truncated_gzip_fails_closed_with_clean_input_error(self):
        self.fixture()
        self.compressed_graph(gzip.compress(self.graph.read_bytes(), mtime=0)[:-8])
        code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "input_error")
        self.assertIn("Malformed or truncated gzip graph", report["error"])

    def test_builder_add_counts_and_missing_graphs_block(self):
        self.fixture()
        summary = json.loads(self.summary.read_text())
        summary["quads_dataset"] += 2
        summary["per_graph"]["metadata"] += 1
        summary["per_graph"]["identity"] = 1
        self.summary.write_text(json.dumps(summary))
        code, report = self.invoke()
        check = self.check(report, "saved_graph_counts")
        self.assertEqual(code, 1)
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(check["evidence"]["missing_graph_roles"], ["identity"])

    def test_unknown_graph_is_not_silently_excluded(self):
        report = self.fixture(extra_graph="<https://example.org/unexpected> { ex:a ex:b ex:c . }")
        check = self.check(report, "saved_graph_counts")
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(check["evidence"]["unknown_graphs"], ["<https://example.org/unexpected>"])

    def test_valid_smu_property_use_is_not_flagged(self):
        report = self.fixture(identity="ex:smu a gcdfo:StockManagementUnit ; gcdfo:hasConservationUnit ex:cu .")
        self.assertEqual(self.check(report, "has_conservation_unit_domain")["status"], "pass")

    def test_population_site_and_derived_cube_property_across_graphs(self):
        report = self.fixture(
            metadata="""ex:countedPopulation rdfs:subClassOf smn:Population .
                ex:dim rdfs:subPropertyOf ex:middle .
                ex:middle rdfs:subPropertyOf gcdfo:hasConservationUnit .
                ex:pop a ex:countedPopulation .""",
            identity=f"""ex:pop gcdfo:hasConservationUnit ex:cu .
                ex:site a <{BASE}def/SurveySite> ; gcdfo:hasConservationUnit ex:cu .""",
            cube="ex:obs a qb:Observation ; ex:dim ex:cu .",
        )
        check = self.check(report, "has_conservation_unit_domain")
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(check["evidence"]["distinct_subjects"], 3)
        self.assertEqual(check["evidence"]["subject_predicate_type_pairs"], 3)

    def test_migrated_namespace_can_be_selected_explicitly(self):
        base = "https://w3id.org/smn-data-graph/"
        report = self.fixture(base=base, identity=f"ex:site a <{base}def/SurveySite> ; gcdfo:hasConservationUnit ex:cu .")
        self.assertEqual(self.check(report, "saved_graph_counts")["status"], "pass")
        self.assertEqual(self.check(report, "has_conservation_unit_domain")["status"], "blocker")

    def test_max_estimate_spawner_annotation_blocks_without_guessing_replacement(self):
        report = self.fixture(fields=[{"name": "MAX_ESTIMATE", "term_iri": audit_cli.GCD + "SpawnerAbundance"}])
        check = self.check(report, "max_estimate_spawner_semantics")
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(check["evidence"]["fields"][0]["field"], "MAX_ESTIMATE")

    def test_cube_max_sum_is_checked_even_when_column_annotation_removed(self):
        report = self.fixture(metadata='ex:measure a qb:MeasureProperty ; qb:concept gcdfo:SpawnerAbundance ; rdfs:comment "Sum of MAX_ESTIMATE" .')
        self.assertEqual(self.check(report, "max_estimate_spawner_semantics")["status"], "blocker")

    @staticmethod
    def candidate_parts(*, status="awaitingReview", live=False, marks=True,
                        predicate="skos:closeMatch", population=False):
        types = ("ex:a a smn:Population ." if population else "ex:a a gcdfo:ConservationUnit .")
        types += " ex:b a gcdfo:ConservationUnit ."
        core = f"ex:r a rdf:Statement ; rdf:subject ex:a ; rdf:predicate {predicate} ; rdf:object ex:b ."
        if live:
            core += f" ex:a {predicate} ex:b ."
        metadata = ""
        if marks:
            metadata = f"""ex:r prov:wasAttributedTo ex:agent ; prov:wasGeneratedBy ex:run ;
                dcterms:source <https://doi.org/10.5281/zenodo.19959144> ;
                rdfs:comment "Source row pairing, not approved membership." ;
                <{BASE}profile/confidence> <{BASE}profile/lowConfidence> ;
                <{BASE}profile/criticality> <{BASE}profile/critical> ;
                <{BASE}profile/reviewStatus> <{BASE}profile/{status}> ."""
        return types, core, metadata

    def test_valid_unasserted_candidate_marks_can_be_in_another_named_graph(self):
        types, core, marks = self.candidate_parts()
        report = self.fixture(metadata=types, identity=core,
            extra_graph=f"<{BASE}graph/{SLUG}/provenance> {{ {marks} }}")
        check = self.check(report, "critical_identity_candidate_review")
        self.assertEqual(check["status"], "pass")
        self.assertEqual(check["evidence"]["candidate_relationships"], 1)
        self.assertEqual(check["evidence"]["valid_awaiting_review_candidates"], 1)
        self.assertEqual(check["evidence"]["live_critical_bridges"], 0)

    def test_unmarked_live_mapping_is_blocked_despite_unrelated_global_marks(self):
        types, _, marks = self.candidate_parts()
        report = self.fixture(metadata=types + marks, identity="ex:a skos:exactMatch ex:b .")
        check = self.check(report, "critical_identity_candidate_review")
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(check["evidence"]["violations_by_reason"]["missing_statement_record"], 1)
        self.assertEqual(check["evidence"]["live_critical_bridges"], 1)

    def test_statement_candidate_missing_marks_cannot_disappear_from_gate(self):
        types, core, _ = self.candidate_parts(marks=False)
        report = self.fixture(metadata=types, identity=core)
        check = self.check(report, "critical_identity_candidate_review")
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(check["evidence"]["candidate_relationships"], 1)
        self.assertIn("missing_or_invalid_source_evidence", check["evidence"]["violations_by_reason"])

    def test_valid_marks_do_not_authorize_a_live_critical_join_edge(self):
        types, core, marks = self.candidate_parts(live=True)
        report = self.fixture(metadata=types + marks, identity=core)
        check = self.check(report, "critical_identity_candidate_review")
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(check["evidence"]["violations_by_reason"], {"live_unreviewed_critical_bridge": 1})

    def test_critical_agent_accepted_and_unsupported_human_decisions_block(self):
        for status in ("agentAccepted", "humanAccepted", "humanAmended", "not-a-status"):
            with self.subTest(status=status):
                types, core, marks = self.candidate_parts(status=status)
                report = self.fixture(metadata=types + marks, identity=core)
                check = self.check(report, "critical_identity_candidate_review")
                self.assertEqual(check["status"], "blocker")
                self.assertIn("missing_invalid_or_unsupported_review_status", check["evidence"]["violations_by_reason"])

    def test_conflicting_review_status_values_block(self):
        types, core, marks = self.candidate_parts()
        marks += f" ex:r <{BASE}profile/reviewStatus> <{BASE}profile/agentAccepted> ."
        report = self.fixture(metadata=types + marks, identity=core)
        check = self.check(report, "critical_identity_candidate_review")
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(check["evidence"]["valid_awaiting_review_candidates"], 0)

    def test_literal_uri_text_is_not_accepted_as_review_status(self):
        types, core, marks = self.candidate_parts()
        marks = marks.replace(f"<{BASE}profile/awaitingReview>", f'"{BASE}profile/awaitingReview"')
        report = self.fixture(metadata=types + marks, identity=core)
        self.assertEqual(self.check(report, "critical_identity_candidate_review")["status"], "blocker")

    def test_mismatched_or_ambiguous_statement_cannot_qualify_a_mapping(self):
        types, core, marks = self.candidate_parts()
        core += " ex:r rdf:object ex:c ."
        report = self.fixture(metadata=types + marks, identity=core)
        check = self.check(report, "critical_identity_candidate_review")
        self.assertEqual(check["status"], "blocker")
        self.assertIn("ambiguous_or_incorrect_statement_object", check["evidence"]["violations_by_reason"])

    def test_each_supported_cu_mapping_predicate_is_gated(self):
        for predicate in ("skos:exactMatch", "skos:closeMatch", "skos:broadMatch", "skos:narrowMatch"):
            with self.subTest(predicate=predicate):
                types, core, marks = self.candidate_parts(predicate=predicate)
                report = self.fixture(metadata=types + marks, identity=core)
                self.assertEqual(self.check(report, "critical_identity_candidate_review")["status"], "pass")

    def test_population_to_cu_statement_candidate_has_the_same_critical_gate(self):
        types, core, marks = self.candidate_parts(predicate="smn:populationOf", population=True)
        report = self.fixture(metadata=types + marks, identity=core)
        check = self.check(report, "critical_identity_candidate_review")
        self.assertEqual(check["status"], "pass")
        self.assertEqual(check["evidence"]["by_kind"], {"population_to_cu": 1})

    def test_rdf12_reifiers_are_rejected_as_outside_the_legacy_gate(self):
        report = self.fixture(identity="ex:r rdf:reifies <<( ex:a skos:closeMatch ex:b )>> .")
        check = self.check(report, "critical_identity_candidate_review")
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(check["evidence"]["unsupported_rdf_reifies_records"], 1)

    def test_max_variable_entity_spawner_context_blocks_after_term_removal(self):
        report = self.fixture(metadata=f"""ex:column csvw:name "MAX_ESTIMATE" ;
                <{BASE}def/variable> ex:variable .
            ex:variable iop:hasObjectOfInterest ex:entity .
            ex:entity iop:hasConstraint smn:SpawnerStageContext .""")
        check = self.check(report, "max_estimate_spawner_semantics")
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(len(check["evidence"]["residual_graph_spawner_contexts"]), 1)

    def test_max_package_decomposition_context_blocks_without_term_or_graph_annotation(self):
        self.fixture()
        path = self.pkg / "metadata/semantic/measurement-decompositions.csv"
        path.parent.mkdir(parents=True)
        path.write_text("table_id,column_name,component_role,component_iri\n"
                        "nuseds_cuid_streamid,MAX_ESTIMATE,constraint,https://w3id.org/smn/SpawnerStageContext\n")
        report = audit_cli.audit(self.root)
        check = self.check(report, "max_estimate_spawner_semantics")
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(len(check["evidence"]["residual_package_spawner_contexts"]), 1)

    def test_explicit_agent_manual_claim_is_a_warning_not_an_accusation_about_upstream(self):
        self.fixture()
        path = self.pkg / "metadata/semantic/mapping.sssom.tsv"
        path.parent.mkdir(parents=True)
        path.write_text("# sssom_version: '1.1'\nsubject_id\tmapping_justification\tcomment\n"
                        "ex:agent\tsemapv:ManualMappingCuration\tSource: corpus agent.\n"
                        "ex:upstream\tsemapv:ManualMappingCuration\tSource: upstream.\n")
        report = audit_cli.audit(self.root)
        check = self.check(report, "agent_mapping_curation_claim")
        self.assertEqual(check["status"], "warning")
        self.assertEqual(len(check["evidence"]["rows_needing_review"]), 1)
        self.assertEqual(len(report["inputs"]), 4)
        self.assertEqual(self.invoke()[0], 0)

    def test_missing_inputs_fail_with_input_error(self):
        code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "input_error")

    def test_malformed_json_and_trig_fail_with_input_error(self):
        self.fixture()
        self.summary.write_text("{")
        self.assertEqual(self.invoke()[0], 2)
        self.fixture()
        self.graph.write_text("This is not TriG!")
        self.assertEqual(self.invoke()[0], 2)

    def test_invalid_count_schema_and_unsafe_graph_path_fail(self):
        self.fixture()
        summary = json.loads(self.summary.read_text())
        summary["quads_dataset"] = True
        self.summary.write_text(json.dumps(summary))
        self.assertEqual(self.invoke()[0], 2)
        summary["quads_dataset"] = 1
        summary["graph_file"] = "../outside.trig"
        self.summary.write_text(json.dumps(summary))
        self.assertEqual(self.invoke()[0], 2)

    def test_output_receipt_cannot_overwrite_an_input(self):
        self.fixture()
        original = self.graph.read_bytes()
        self.assertEqual(self.invoke("--output", str(self.graph))[0], 2)
        self.assertEqual(self.graph.read_bytes(), original)

    def test_output_receipt_matches_stdout(self):
        self.fixture()
        path = self.root / "audit/receipt.json"
        code, report = self.invoke("--output", str(path))
        self.assertEqual(code, 0)
        self.assertEqual(report, json.loads(path.read_text()))


if __name__ == "__main__":
    unittest.main()
