"""Exercise source-intake auditing through the mapper-facing command line."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

AUDIT = Path(__file__).resolve().parents[1] / "specs/source-intake/audit_join.py"


class JoinAudit(unittest.TestCase):
    def run_case(self, left, right, *args):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "left.csv", Path(directory) / "right.csv"
            a.write_text(left, encoding="utf-8")
            b.write_text(right, encoding="utf-8")
            return subprocess.run([sys.executable, str(AUDIT), str(a), str(b), *args], capture_output=True, text=True)

    def test_scoped_single_match_survives_unrelated_right_duplicates(self):
        result = self.run_case("x,y\n1,9\n1,9\n", "key,y\n1,9\n2,4\n2,4\n", "--left-key", "x", "y", "--right-key", "key", "y", "--require-single-match")
        self.assertEqual(result.returncode, 0, result.stderr)
        audit = json.loads(result.stdout)
        self.assertEqual(audit["left"]["rows_matching_once"], 2)
        self.assertEqual(audit["right"]["repeated_complete_keys"], 1)
        self.assertEqual(audit["inner_rows"], 2)

    def test_nulls_fanout_and_equal_looking_lexical_keys(self):
        result = self.run_case("x\n01\n1\n1\nNA\n", "x\n1\n1\nNA\n", "--left-key", "x", "--null-token", "NA", "--require-single-match")
        self.assertEqual(result.returncode, 1)
        audit = json.loads(result.stdout)
        self.assertEqual(audit["inner_rows"], 4)
        self.assertEqual(audit["left"]["unmatched_complete_key_rows"], 1)
        self.assertEqual(audit["left"]["rows_matching_multiple"], 2)
        self.assertEqual(audit["left"]["null_key_rows"], 1)

    def test_empty_scope_is_not_a_verified_join(self):
        self.assertEqual(self.run_case("x\n", "x\n1\n", "--left-key", "x", "--require-single-match").returncode, 1)

    def test_missing_or_ambiguous_header_ragged_row_or_mismatched_arity(self):
        for left, extra in [("x,x\n1,2\n", []), ("z\n1\n", []), ("x\n1,2\n", []), ("x\n1\n", ["--right-key", "x", "y"])]:
            with self.subTest(left=left, extra=extra):
                result = self.run_case(left, "x\n1\n", "--left-key", "x", *extra)
                self.assertEqual(result.returncode, 2)

    def test_collection_separates_equal_payload_and_conflicts_with_source_records(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "a.csv", Path(directory) / "b.csv"
            a.write_text("site,year,count,note\nA,1,3,x\nA,1,3,y\nA,2,7,x\nNA,2,0,z\n")
            b.write_text("site,year,count,note\nA,1,5,x\nA,2,7,z\n")
            args = [sys.executable, str(AUDIT), "--files", str(a), str(b), "--key", "site", "year",
                    "--null-token", "NA", "--payload", "count", "--expect-unique"]
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual([report[k] for k in ("rows", "repeated_complete_keys", "within_file_repeated_keys",
                             "across_file_repeated_keys", "consistent_repeated_keys", "discordant_repeated_keys")], [6, 2, 1, 2, 1, 1])
            self.assertEqual(report["repeats"][0]["repeated_payload_rows_beyond_first"], 1)
            self.assertEqual(report["repeats"][0]["rows"][-1], {"file": str(b), "record": 1, "payload": ["5"]})
            self.assertEqual(report["missing_keys"], [{"file": str(a), "record": 4, "key": ["NA", "2"]}])
            a.write_text("site,year,count,note\nB,2,0,z\n")
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 0)
            args[4] = str(a)
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 2)

    def test_proposed_cardinality_checks_both_sides_and_optional_files(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b, c = [Path(directory) / name for name in ("a.csv", "b.csv", "c.csv")]
            a.write_text("x\n1\n1\n")
            b.write_text("x\n1\n")
            c.write_text("x\n1\n")
            cmd = [sys.executable, str(AUDIT), str(a), str(b), "--left-key", "x", "--expect-cardinality"]
            for proposal, extra, code, fanouts in [("one-to-one", [], 1, 0), ("many-to-one", [], 0, 0),
                     ("many-to-one", ["--right-extra", str(c)], 1, 1), ("many-to-many", ["--right-extra", str(c)], 0, 1)]:
                with self.subTest(proposal=proposal, extra=extra):
                    res = subprocess.run([*cmd, proposal, *extra], capture_output=True, text=True)
                    self.assertEqual(res.returncode, code, res.stderr)
                    self.assertEqual(json.loads(res.stdout)["many_to_many_keys"], fanouts)
            a.write_text('x\n""\n1\n', encoding="utf-8")
            self.assertEqual(subprocess.run([*cmd, "many-to-one"], capture_output=True).returncode, 1)
            a.write_text("x\n2\n", encoding="utf-8")
            self.assertEqual(subprocess.run([*cmd, "one-to-one"], capture_output=True).returncode, 1)
