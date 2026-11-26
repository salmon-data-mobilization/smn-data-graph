import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "specs/source-intake/audit_measurement_types.py"
SOURCE = ["example", "samples", "reading"]
VIEW = ["example", "projection", "reading_numeric"]
UNRELATED = ["example", "samples", "depth"]


def write_csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


class MeasurementTypeAudit(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.package = Path(temp.name)
        (self.package / "metadata").mkdir()
        (self.package / "data").mkdir()
        self.columns = [
            ["example", "samples", "id", "identifier", "string", "", ""],
            ["example", "samples", "reading", "measurement", "string", "urn:example:reading", "urn:example:unit"],
            ["example", "samples", "depth", "measurement", "number", "urn:example:depth", "urn:example:m"],
            ["example", "projection", "id", "identifier", "string", "", ""],
            ["example", "projection", "reading_numeric", "measurement", "integer", "urn:example:reading", "urn:example:unit"],
        ]
        self.original = [["A", "0", "0"], ["B", "2.0", "2"], ["C", "ND", ""]]
        self.typed = [["C", ""], ["B", "2"], ["A", "0"]]
        self.write_metadata()
        self.write_data()

    def write_metadata(self):
        meta = self.package / "metadata"
        write_csv(meta / "column_dictionary.csv", ["dataset_id", "table_id", "column_name", "column_role", "value_type", "term_iri", "unit_iri"], self.columns)
        tables = []
        resources = []
        for table, missing in (("samples", ["", "ND"]), ("projection", [""])):
            path = f"data/{table}.csv"
            fields = [{"name": row[2], "type": row[4]} for row in self.columns if row[1] == table]
            tables.append(["example", table, path, "id"])
            resources.append({"name": table, "path": path, "schema": {"primaryKey": "id", "fields": fields, "missingValues": missing}})
        write_csv(meta / "tables.csv", ["dataset_id", "table_id", "file_name", "primary_key"], tables)
        (self.package / "datapackage.json").write_text(json.dumps({"resources": resources}))

    def write_data(self):
        write_csv(self.package / "data/samples.csv", ["id", "reading", "depth"], self.original)
        write_csv(self.package / "data/projection.csv", ["id", "reading_numeric"], self.typed)

    def run_audit(self, decisions=None, *, gate=True, numeric=False):
        args = [sys.executable, str(SCRIPT), str(self.package)]
        if decisions is not None:
            path = self.package / "review.json"
            path.write_text(json.dumps(decisions))
            args.extend(["--decisions", str(path)])
        if gate:
            args.append("--require-accounted")
        if numeric:
            args.append("--require-numeric")
        return subprocess.run(args, capture_output=True, text=True, check=False)

    def check_report(self, decisions, code, status):
        result = self.run_audit(decisions)
        self.assertEqual(result.returncode, code, result.stderr)
        report = json.loads(result.stdout)
        field = next(item for item in report["fields"] if item["field"] == SOURCE)
        self.assertEqual(field["status"], status)
        return report, field

    def test_only_native_measurements_count_and_views_need_an_explicit_link(self):
        report, _ = self.check_report(None, 1, "undeclared")
        self.assertEqual(report["measurement_slots"], 3)
        self.assertEqual(report["text_measurement_slots"], 1)
        self.assertEqual(report["by_status"]["declared_numeric"], 2)
        self.assertEqual(self.run_audit(gate=False).returncode, 0)

    def test_qualified_view_accepts_reordered_keys_decimals_zeros_and_source_missing(self):
        report, field = self.check_report([{"source": SOURCE, "view": VIEW}], 0, "verified_view")
        self.assertTrue(report["accounted"])
        self.assertEqual((field["rows"], field["nonmissing"]), (3, 2))

    def test_field_missing_token_isolated_from_sibling_measurement_keys_and_target(self):
        self.columns[2][4] = "string"
        self.columns.append(["example", "projection", "depth_numeric", "measurement", "number", "urn:example:depth", "urn:example:m"])
        self.write_metadata()
        write_csv(self.package / "data/samples.csv", ["id", "reading", "depth"], [["NA", "0", "2"], ["B", "NA", "NA"], ["C", "ND", "3"]])
        write_csv(self.package / "data/projection.csv", ["id", "reading_numeric", "depth_numeric"], [["NA", "0", "2"], ["B", "", ""], ["C", "", "3"]])
        evidence = {"locator": "Instrument dictionary, reading field", "rationale": "The instrument uses NA for a missed reading."}
        first = {"source": SOURCE, "view": VIEW, "source_missing_tokens": ["NA"], "source_missing_evidence": evidence}
        second = {"source": UNRELATED, "view": ["example", "projection", "depth_numeric"]}
        report, field = self.check_report([first, second], 1, "verified_view")
        self.assertEqual((field["rows"], field["nonmissing"]), (3, 1))
        self.assertEqual(field["source_missing_token_counts"], {"NA": 1})
        self.assertEqual(field["source_missing_evidence"], evidence)
        sibling = next(item for item in report["fields"] if item["field"] == UNRELATED)
        self.assertEqual(sibling["status"], "invalid_view")
        write_csv(self.package / "data/projection.csv", ["id", "reading_numeric", "depth_numeric"], [["NA", "0", "2"], ["B", "NA", ""], ["C", "", "3"]])
        self.check_report([first, second], 1, "invalid_view")

    def test_documented_negative_sentinel_is_an_exact_lexeme(self):
        self.original = [["A", "-999", "1"], ["B", "-999.0", "2"], ["C", "0", "3"]]
        self.typed = [["C", "0"], ["B", "-999"], ["A", ""]]
        self.write_data()
        decision = {"source": SOURCE, "view": VIEW, "source_missing_tokens": ["-999"],
                    "source_missing_evidence": {"locator": "Instrument export manual, reading", "rationale": "The export reserves the exact label -999 for unrecorded readings."}}
        _, field = self.check_report([decision], 0, "verified_view")
        self.assertEqual(field["source_missing_token_counts"], {"-999": 1})
        self.assertEqual(field["nonmissing"], 2)

    def test_missing_override_requires_evidence_and_rejects_ambiguous_or_repeated_tokens(self):
        evidence = {"locator": "Instrument dictionary, reading", "rationale": "Instrument flag"}
        direct = {"source": SOURCE, "view": VIEW}
        invalid = [
            {"source_missing_tokens": ["NA"]},
            {"source_missing_evidence": evidence},
            {"source_missing_tokens": ["NA"], "source_missing_evidence": {"locator": "", "rationale": "Flag"}},
            {"source_missing_tokens": ["NA"], "source_missing_evidence": {"locator": "Field", "rationale": " "}},
        ]
        for tokens in ([], [" "], ["NA", "NA"], ["0"], ["-0.00e2"], ["+4"], [0]):
            invalid.append({"source_missing_tokens": tokens, "source_missing_evidence": evidence})
        for change in invalid:
            with self.subTest(change=change):
                self.assertEqual(self.run_audit([{**direct, **change}]).returncode, 2)
        redundant = {**direct, "source_missing_tokens": ["ND"], "source_missing_evidence": evidence}
        _, field = self.check_report([redundant], 1, "invalid_view")
        self.assertIn("repeats a resource", field["reason"])

    def test_decimal_consumer_preserves_values_and_missingness_and_checks_the_hash(self):
        exact = "0.123456789012345678901234567890123456789"
        self.columns[-1][4] = "number"
        self.write_metadata()
        self.original = [["001", exact, "1"], ["002", "ND", "2"], ["003", "-0.00", "3"]]
        self.typed = [["003", "0"], ["001", exact], ["002", ""]]
        self.write_data()
        path = self.package / "decisions.json"
        path.write_text(json.dumps([{"source": SOURCE, "view": VIEW}]))
        pin = hashlib.sha256((self.package / "data/samples.csv").read_bytes()).hexdigest()
        args = [sys.executable, str(SCRIPT.with_name("read_numeric_view.py")), str(self.package), str(path), "--source", *SOURCE, "--source-sha256"]
        report = subprocess.run([*args, pin], capture_output=True, text=True, check=True)
        rows = json.loads(report.stdout)["rows"]
        self.assertEqual(rows, [[["001"], exact], [["002"], None], [["003"], "-0.00"]])
        self.assertEqual(Decimal(rows[0][1]), Decimal(exact))
        for wrong in ["0" * 64, "not-a-hash"]:
            refused = subprocess.run([*args, wrong], capture_output=True, text=True)
            self.assertEqual((refused.returncode, refused.stdout), (2, ""))
        self.typed[1][1] = "0.12345678901234568"
        self.write_data()
        refused = subprocess.run([*args, pin], capture_output=True, text=True)
        self.assertEqual((refused.returncode, refused.stdout), (2, ""))
        self.assertIn("differ in values or missingness", refused.stderr)

    def test_decimal_consumer_refuses_unresolved_or_scientifically_unrelated_fields(self):
        pin = hashlib.sha256((self.package / "data/samples.csv").read_bytes()).hexdigest()
        path = self.package / "decisions.json"
        args = [sys.executable, str(SCRIPT.with_name("read_numeric_view.py")), str(self.package), str(path), "--source", *SOURCE, "--source-sha256", pin]
        for row in [{"source": SOURCE, "unresolved": "The unit is unknown."}, {"source": SOURCE, "view": UNRELATED}]:
            path.write_text(json.dumps([row]))
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout), (2, ""))

    def test_unrelated_variable_or_wrong_unit_cannot_substitute(self):
        _, field = self.check_report([{"source": SOURCE, "view": UNRELATED}], 1, "invalid_view")
        self.assertIn("different", field["reason"])
        self.columns[-1][-1] = "urn:example:other-unit"
        self.write_metadata()
        self.check_report([{"source": SOURCE, "view": VIEW}], 1, "invalid_view")

    def test_disagreeing_resource_semantics_and_unresolved_variable_are_rejected(self):
        descriptor = self.package / "datapackage.json"
        content = json.loads(descriptor.read_text())
        content["resources"][1]["schema"]["fields"][-1]["term_iri"] = "urn:example:unrelated"
        descriptor.write_text(json.dumps(content))
        self.assertEqual(self.run_audit([{"source": SOURCE, "view": VIEW}]).returncode, 2)
        self.columns[1][-2] = self.columns[-1][-2] = "REVIEW:variable"
        self.write_metadata()
        self.check_report([{"source": SOURCE, "view": VIEW}], 1, "invalid_view")

    def test_boolean_is_not_a_numeric_target(self):
        self.columns[-1][4] = "boolean"
        self.write_metadata()
        self.check_report([{"source": SOURCE, "view": VIEW}], 1, "invalid_view")

    def test_explicit_reason_accounts_for_unresolved_without_crediting_a_numeric_view(self):
        report, _ = self.check_report([{"source": SOURCE, "unresolved": "Instrument reporting scale is undocumented."}], 0, "explicitly_unresolved")
        self.assertEqual(report["by_status"]["verified_view"], 0)
        result = self.run_audit([{"source": SOURCE, "unresolved": ""}])
        self.assertEqual(result.returncode, 2)

    def test_dropped_duplicate_wrong_or_imputed_values_are_rejected(self):
        for rows in (self.typed[:-1], self.typed + [self.typed[-1]], [["A", ""], ["B", "2"], ["C", "0"]], [["A", "0"], ["B", "2.5"], ["C", ""]]):
            with self.subTest(rows=rows):
                self.typed = rows
                self.write_data()
                self.check_report([{"source": SOURCE, "view": VIEW}], 1, "invalid_view")

    def test_numeric_gate_distinguishes_abstention_from_usable_numeric_data(self):
        abstention = self.run_audit([{"source": SOURCE, "unresolved": "Precision unresolved."}], numeric=True)
        report = json.loads(abstention.stdout)
        self.assertEqual(abstention.returncode, 1)
        self.assertTrue(report["accounted"])
        self.assertFalse(report["numeric_ready"])
        self.assertEqual(self.run_audit([{"source": SOURCE, "view": VIEW}], numeric=True).returncode, 0)
        for values in (["1", "invalid", ""], ["", "", "ND"]):
            with self.subTest(values=values):
                for row, value in zip(self.original, values):
                    row[2] = value
                self.write_data()
                self.assertEqual(self.run_audit([{"source": SOURCE, "view": VIEW}], numeric=True).returncode, 1)

    def test_descriptor_disagreement_fails_and_no_measurements_does_not_pass_gate(self):
        descriptor = self.package / "datapackage.json"
        content = json.loads(descriptor.read_text())
        content["resources"][1]["schema"]["fields"][-1]["type"] = "string"
        descriptor.write_text(json.dumps(content))
        self.assertEqual(self.run_audit().returncode, 2)
        for row in self.columns:
            row[3] = "attribute"
        self.write_metadata()
        result = self.run_audit()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["measurement_slots"], 0)


if __name__ == "__main__":
    unittest.main()
