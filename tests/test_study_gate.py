import hashlib
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


TOOL = Path(__file__).resolve().parents[1] / "specs/source-intake/audit_study_gate.py"


class StudyGate(unittest.TestCase):
    def test_private_plan_receipt_pins_and_no_replacement(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            design, manifest, receipt, copy = [base / n for n in ("hypothesis.json", "DESIGN.sha256", "gate.json", "submission.json")]
            design.write_text("confidential hypothesis wording")
            manifest.write_text(f"{hashlib.sha256(design.read_bytes()).hexdigest()}  {design.name}\n")
            pin = hashlib.sha256(manifest.read_bytes()).hexdigest()

            def run(mode, *args):
                return subprocess.run([sys.executable, str(TOOL), mode, str(manifest), str(receipt),
                                       "--expected-sha256", pin, *map(str, args)], capture_output=True)

            self.assertEqual(run("witness", "--context", "rubric", "a"*64).returncode, 0)
            self.assertNotIn("hypothesis", receipt.read_text())
            self.assertNotEqual(run("witness").returncode, 0)
            copy.write_bytes(receipt.read_bytes())
            self.assertEqual(run("verify", "--submission", copy, "--context", "rubric", "a"*64).returncode, 0)
            self.assertNotEqual(run("verify", "--context", "rubric", "b"*64).returncode, 0)
            copy.write_text("{}")
            self.assertNotEqual(run("verify", "--submission", copy).returncode, 0)
            design.write_text("different outcome")
            self.assertNotEqual(run("verify").returncode, 0)
