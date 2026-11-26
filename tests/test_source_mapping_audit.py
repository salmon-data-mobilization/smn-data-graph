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
