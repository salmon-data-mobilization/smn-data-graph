import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "specs/source-intake/audit_scoped_roles.py"
SCOPE = {"stream": "Alder", "signal": "adult count", "series": "Coast index",
         "edition": "first", "method": "reach expansion"}


def claim(role, assertion, evidence, first_year=2001, last_year=2003, **scope):
    return {**SCOPE, **scope, "role": role, "assertion": assertion, "evidence": evidence,
            "first_year": first_year, "last_year": last_year}


def query(return_year=2002, **scope):
    return {**SCOPE, **scope, "return_year": return_year}


class ScopedRolesTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.claims = Path(directory.name) / "claims.json"
        self.queries = Path(directory.name) / "queries.json"

    def run_cli(self):
        return subprocess.run([sys.executable, SCRIPT, self.claims, self.queries], capture_output=True, text=True)

    def check(self, claims, queries):
        self.claims.write_text(json.dumps({"version": 1, "claims": claims}), encoding="utf-8")
        self.queries.write_text(json.dumps({"version": 1, "queries": queries}), encoding="utf-8")
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(document["version"], 1)
        self.assertEqual([row["query"] for row in document["results"]], queries)
        return [row["roles"] for row in document["results"]]

    def assert_statuses(self, roles, monitoring="abstain", estimator="abstain", subset="abstain"):
        self.assertEqual({name: result["status"] for name, result in roles.items()},
                         {"monitoring": monitoring, "estimator_input": estimator, "standalone_subset": subset})

    def test_roles_do_not_follow_stream_between_products_or_methods(self):
        claims = [
            claim("monitoring", "include", "Survey log p4"),
            claim("estimator_input", "exclude", "Expansion methods p9"),
            claim("standalone_subset", "exclude", "Subset table p3"),
            claim("estimator_input", "include", "Alternate estimator p5", method="direct enumeration"),
            claim("standalone_subset", "include", "Tributary definition p2", series="Tributary index"),
            claim("monitoring", "include", "Smolt protocol p1", signal="smolt count"),
            claim("estimator_input", "include", "Revised inputs p6", edition="correction"),
            claim("estimator_input", "include", "Upper tributary inputs p8", stream="Willow"),
        ]
        results = self.check(claims, [query(), query(method="direct enumeration"), query(series="Tributary index"),
                                      query(signal="smolt count"), query(edition="correction"), query(stream="Willow")])
        self.assert_statuses(results[0], monitoring="supported", estimator="excluded", subset="excluded")
        self.assert_statuses(results[1], estimator="supported")
        self.assert_statuses(results[2], subset="supported")
        self.assert_statuses(results[3], monitoring="supported")
        self.assert_statuses(results[4], estimator="supported")
        self.assert_statuses(results[5], estimator="supported")

    def test_each_scope_dimension_and_unseen_year_withhold_membership(self):
        claims = [claim(role, "include", "Definition table p3")
                  for role in ("monitoring", "estimator_input", "standalone_subset")]
        queries = [query(**{name: "unseen"}) for name in SCOPE] + [query(2004)]
        for roles in self.check(claims, queries):
            self.assert_statuses(roles)
            for result in roles.values():
                self.assertEqual((result["include_evidence"], result["exclude_evidence"]), ([], []))

    def test_interval_boundaries_gaps_and_a_one_year_exception(self):
        claims = [claim("standalone_subset", "include", "First interval", 2001, 2003),
                  claim("standalone_subset", "exclude", "One year", 2005, 2005),
                  claim("standalone_subset", "include", "Second interval", 2006, 2007)]
        results = self.check(claims, [query(y) for y in range(2000, 2009)])
        expected = ["abstain", "supported", "supported", "supported", "abstain",
                    "excluded", "supported", "supported", "abstain"]
        self.assertEqual([roles["standalone_subset"]["status"] for roles in results], expected)

    def test_overlap_conflict_withholds_and_reports_both_sides_without_voting(self):
        claims = [claim("standalone_subset", "include", "Table B"),
                  claim("standalone_subset", "include", "Table A"),
                  claim("standalone_subset", "include", "Table B"),
                  claim("standalone_subset", "exclude", "Appendix", 2002, 2002),
                  claim("monitoring", "include", "Field log")]
        queries = [query(2002), query(2003)]
        conflict, supported = self.check(claims, queries)
        self.assertEqual(self.check(list(reversed(claims)), queries), [conflict, supported])
        self.assert_statuses(conflict, monitoring="supported", subset="contradiction")
        self.assertEqual(conflict["standalone_subset"],
                         {"status": "contradiction", "include_evidence": ["Table A", "Table B"],
                          "exclude_evidence": ["Appendix"]})
        self.assert_statuses(supported, monitoring="supported", subset="supported")

    def test_reject_invalid_register_or_query_without_partial_results(self):
        valid = claim("monitoring", "include", "Survey table")
        invalid_claims = [
            {**valid, "edition": ""}, {k: v for k, v in valid.items() if k != "method"},
            {**valid, "last_year": 2000}, {**valid, "first_year": True},
            {**valid, "role": "any"}, {**valid, "assertion": "implied"}, {**valid, "evidence": "  "},
        ]
        invalid_queries = [{**query(), "return_year": "2002"}, {**query(), "unexpected": 0},
                           {k: v for k, v in query().items() if k != "series"}]
        cases = [({"version": 1, "claims": [bad]}, {"version": 1, "queries": [query()]})
                 for bad in invalid_claims]
        cases.extend(({"version": 1, "claims": [valid]}, {"version": 1, "queries": [query(), bad]})
                     for bad in invalid_queries)
        cases.extend([({"version": True, "claims": []}, {"version": 1, "queries": []}),
                      ({"version": 1, "claims": []}, {"version": 2, "queries": []})])
        for claim_doc, query_doc in cases:
            with self.subTest(claim_doc=claim_doc, query_doc=query_doc):
                self.claims.write_text(json.dumps(claim_doc))
                self.queries.write_text(json.dumps(query_doc))
                result = self.run_cli()
                self.assertEqual((result.returncode, result.stdout), (1, ""))
                self.assertIn("Scoped role lookup failed", result.stderr)

    def test_reject_duplicate_json_keys(self):
        self.claims.write_text('{"version":1,"claims":[],"claims":[]}')
        self.queries.write_text('{"version":1,"queries":[]}')
        result = self.run_cli()
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertIn("Duplicate JSON field", result.stderr)


if __name__ == "__main__":
    unittest.main()
