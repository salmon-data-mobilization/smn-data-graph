import csv
import json
import subprocess
import sys
import tempfile
import unittest
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

    def run_audit(self, decisions=None, *, gate=True):
        args = [sys.executable, str(SCRIPT), str(self.package)]
        if decisions is not None:
            path = self.package / "review.json"
            path.write_text(json.dumps(decisions))
            args.extend(["--decisions", str(path)])
        if gate:
            args.append("--require-accounted")
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
