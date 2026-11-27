import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rdflib import Graph

MODULE = Path(__file__).resolve().parents[1] / "specs/source-intake/audit_mapping_decisions.py"
spec = importlib.util.spec_from_file_location("audit_decisions", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class DecisionAudit(unittest.TestCase):
    def setUp(self):
        self.g = Graph().parse(data="<urn:q> <urn:p> <urn:a>, <urn:b> .", format="turtle")
        self.rows = [
            dict(id=k, status=st, table="example", claim="Test proposition", source_url="https://example.org/source",
                 locator="page 1", reason="fixture", subject="urn:q", predicate="urn:p", object="urn:"+k)
            for k, st in [("a","accepted"), ("b","accepted"), ("c","abstained"), ("d","abstained")]
        ]

    def run_audit(self, rows):
        return audit.check_decisions(self.g, rows, "example", "s1", 1)

    def test_sample_is_order_invariant_without_replacement(self):
        forward = self.run_audit(self.rows)
        self.assertEqual(forward, self.run_audit(self.rows[::-1]))
        self.assertTrue(forward["matches_export"])
        self.assertEqual(forward["population"], {"accepted": 2, "abstained": 2})

    def test_correct_rdf_action_can_have_wrong_evidentiary_reason(self):
        reference = [dict(r, evidence_verdict="Supported" if r["status"] == "accepted" else "Unsupported",
                          action="assert_scoped" if r["status"] == "accepted" else "withhold") for r in self.rows]
        self.assertTrue(audit.check_judgments(reference, reference)["matches_reference"])
        candidate = [dict(r) for r in reference]
        candidate[-1]["evidence_verdict"] = "Insufficient evidence"
        self.assertTrue(self.run_audit(candidate)["matches_export"])
        result = audit.check_judgments(candidate, reference)
        self.assertFalse(result["matches_reference"])
        self.assertEqual(result["checked"][-1]["differences"], ["evidence_verdict"])
        self.assertEqual(audit.check_judgments(candidate, reference[:-1])["ungraded_ids"], ["d"])
        candidate[0]["claim"] = "Different proposition with the same identifier"
        self.assertIn("claim", audit.check_judgments(candidate, reference)["checked"][0]["differences"])
        with self.assertRaises(ValueError):
            audit.check_judgments(candidate, [*reference, reference[-1]])

    def test_vacuous_absence_and_accidentally_asserted_rejection_fail(self):
        self.rows[3]["subject"] = "urn:missing"
        self.rows[1]["status"] = "abstained"
        result = self.run_audit(self.rows)
        self.assertEqual([r["id"] for r in result["checked"] if not r["matches_export"]], ["b","d"])

    def test_duplicate_or_impossible_draw_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_audit(self.rows + [dict(self.rows[0], id="repeat")])
        with self.assertRaises(ValueError):
            self.run_audit(self.rows[:2])

    def test_unit_can_be_used_without_redefining_the_external_label(self):
        graph = Graph().parse(data="""
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix qudt: <http://qudt.org/schema/qudt/> .
            <urn:local:passage> rdfs:label "Daily estimated fish" ; qudt:unit <http://qudt.org/vocab/unit/NUM> .
            <http://qudt.org/vocab/unit/NUM> rdfs:label "Fish passing one trap in a day" .
        """, format="turtle")
        failures = audit.foreign_labels(graph, ["urn:local:"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["subject"], "http://qudt.org/vocab/unit/NUM")

    def test_independent_scope_contract_catches_omission_leakage_and_wrong_literal_type(self):
        graph = Graph().parse(data='''
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            <urn:subset> <urn:coverage> <urn:adults> ; <urn:year> "2014"^^xsd:gYear .
            <urn:neighbor> <urn:region> <urn:area> .
        ''', format="turtle")
        age = dict(id="restricted", expect="required", subject="urn:subset", predicate="urn:coverage", object="urn:adults", only_subject=True)
        year = dict(id="year", expect="required", subject="urn:subset", predicate="urn:year", only_object=True,
                    object={"value": "2014", "datatype": "http://www.w3.org/2001/XMLSchema#gYear"})
        neighbor = dict(id="neighbor", expect="forbidden", subject="urn:neighbor", predicate="urn:coverage", object="urn:adults")
        rules = [age, year, neighbor]
        self.assertTrue(audit.check_scope(graph, rules)["matches_export"])
        self.assertFalse(audit.check_scope(graph, [dict(neighbor, subject="urn:missing")])["matches_export"])
        self.assertFalse(audit.check_scope(graph, [dict(age, object="urn:other")])["matches_export"])
        graph.parse(data='<urn:neighbor> <urn:coverage> <urn:adults> . <urn:subset> <urn:year> "2014" .', format="turtle")
        checks = audit.check_scope(graph, rules)["checked"]
        self.assertTrue(all(not check["matches_export"] for check in checks))
        self.assertEqual(checks[0]["unexpected_subjects"], ["<urn:neighbor>"])
        self.assertEqual(checks[1]["unexpected_objects"], ['"2014"'])
        for invalid in [[dict(age, only_subject="yes")], [dict(neighbor, only_object=True)], [dict(year, object={"value": "2014"})], [age, age]]:
            with self.assertRaises(ValueError):
                audit.check_scope(graph, invalid)

    def test_scope_only_cli_checks_required_proposition_even_without_mapping_register(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "profile.ttl"
            contract = Path(folder) / "contract.json"
            profile.write_text("<urn:site> <urn:type> <urn:station> .")
            rule = dict(id="age-coverage", expect="required", subject="urn:site", predicate="urn:coverage", object="urn:adults")
            contract.write_text(json.dumps([rule]))
            cmd = [sys.executable, str(MODULE), str(profile), "--scope-propositions", str(contract), "--dataset", "sample"]
            missing = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(missing.returncode, 1, missing.stderr)
            self.assertFalse(json.loads(missing.stdout)["scope"]["checked"][0]["triple_present"])
            profile.write_text("<urn:site> <urn:coverage> <urn:adults> .")
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
