import json
from pathlib import Path
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "specs/source-intake/audit_schema_projection.py"


class SchemaProjectionTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.header = self.root / "header.csv"
        self.dictionary = self.root / "dictionary.csv"
        self.receipt = self.root / "private.json"
        self.header.write_text('Year,"Origin, recorded",Age,Sample ID\n')
        self.dictionary.write_text("dataset_id,table_id,column_name\n"
                                   "fish,samples,year_sampled\nfish,samples,Sample ID\nfish,samples,Estimated\n"
                                   "fish,parents,Age\nother,samples,Age\n")

    def run_check(self, *args):
        return subprocess.run([sys.executable, SCRIPT, self.header, self.dictionary, "--source", "deposit", "Sheet 1",
                               "--native", "fish", "samples", "--output", self.receipt, *args],
                              capture_output=True, text=True)

    def test_scope_alias_and_two_directions_of_missing_evidence(self):
        result = self.run_check("--require", "Year", "--alias", "Year", "year_sampled", "--require", "Age",
                                "--require", "Estimated", "--require", "Origin, recorded")
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertEqual(stat.S_IMODE(self.receipt.stat().st_mode), 0o600)
        report = json.loads(self.receipt.read_text())
        self.assertFalse(report["semantics_verified"])
        first, missing_projection, missing_source, punctuated = report["fields"]
        self.assertEqual(first["publisher"], {"dataset_id":"deposit", "table_id":"Sheet 1", "column_name":"Year"})
        self.assertEqual(first["native"], {"dataset_id":"fish", "table_id":"samples", "column_name":"year_sampled"})
        self.assertEqual(first["name_rule"], "explicit_alias")
        self.assertEqual(first["status"], "declared_in_both")
        self.assertEqual(missing_projection["status"], "lost_in_projection")
        self.assertEqual(missing_source["status"], "absent_from_publisher_header")
        self.assertTrue(missing_source["in_native_dictionary"])
        self.assertEqual(punctuated["status"], "lost_in_projection")

    def test_success_and_existing_receipt_protected(self):
        self.assertEqual(self.run_check("--require", "Sample ID").returncode, 0)
        saved = self.receipt.read_bytes()
        self.assertEqual(self.run_check("--require", "Age").returncode, 1)
        self.assertEqual(saved, self.receipt.read_bytes())

    def test_reject_ambiguous_and_malformed_inputs(self):
        for args in [("--alias","Year","Sample ID"), ("--alias","Year","missing"),
                     ("--alias","Y","year_sampled"), ("--require","Year"),
                     ("--alias","Year","year_sampled","--alias","Year","year_sampled")]:
            with self.subTest(args=args):
                self.assertEqual(self.run_check("--require", "Year", *args).returncode, 1)
                self.assertFalse(self.receipt.exists())
        defaults = self.dictionary.read_text()
        for text in [defaults+"fish,samples,Sample ID\n", defaults+"fish,,x\n",
                     defaults+"fish,samples\n", defaults.replace("column_name","attribute"),
                     "dataset_id,table_id,column_name\nfish,wrong,x\n"]:
            self.dictionary.write_text(text)
            with self.subTest(dictionary=text):
                self.assertEqual(self.run_check("--require","Year").returncode,1)
        self.dictionary.write_text(defaults)
        for text in ["Year,Year\n", "Year,\n", "Year\n2014\n", '"Year\n']:
            self.header.write_text(text)
            with self.subTest(header=text):
                self.assertEqual(self.run_check("--require","Year").returncode,1)
        self.assertFalse(self.receipt.exists())


if __name__ == "__main__":
    unittest.main()
