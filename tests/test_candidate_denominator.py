import csv
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

spec = spec_from_file_location("denominator", Path(__file__).resolve().parents[1] / "specs/source-intake/audit_candidate_denominator.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)


class CandidateDenominatorTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.roster = [["x", "01", "0"], ["x", "1", "1"], ["x", "2", "NA"], ["y", "1", "0"]]

    def write(self, name, rows):
        path = self.root / name
        with path.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["panel", "id", "n"])
            writer.writerows(rows)
        return path

    def check(self, selected, roster=None):
        source = self.write("candidates.csv", self.roster if roster is None else roster)
        used = self.write("selection.csv", selected)
        return module.audit(source, used, ["panel", "id"], ["panel"], "n", {"NA"})

    def test_filters_zeroes_in_one_panel(self):
        result = self.check(self.roster[1:])
        self.assertTrue(result["lost_outcome_support"])
        x, y = result["strata"]
        self.assertEqual(x["counts"]["zero"], {"retained": 0, "excluded": 1})
        self.assertEqual(x["counts"]["missing"]["retained"], 1)
        self.assertEqual(y["status"], "single_observed_outcome_class_in_roster")
        self.assertFalse(self.check(self.roster)["lost_outcome_support"])

    def test_all_removed_or_invalid_fish(self):
        self.assertTrue(self.check([])["lost_outcome_support"])
        for selected in ([self.roster[0]] * 2, [["y", "0001", "0"]]):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                self.check(selected)
        for roster in (self.roster * 2, [["x", "", "0"]], [["x", "1", "-9"]]):
            with self.subTest(roster=roster), self.assertRaises(ValueError):
                self.check([], roster)

