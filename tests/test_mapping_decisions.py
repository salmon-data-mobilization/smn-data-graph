import importlib.util
from pathlib import Path
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
