"""Unit tests of the named-graph audit using small fictional source rosters."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rdflib import Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from aggregate_coverage import QUERY, assess


def source(name, rows):
    components = []
    for atom, value in rows:
        components.append({"id": atom, "evidence": f"Source row {atom}", "resolved": True,
                           "atoms": [{"id": f"urn:fish:{atom}", "value": value, "role": "direct",
                                      "version": "register-1"}]})
    return {"graph": f"urn:source:{name}:v1", "version": "1", "year": 2000,
            "frame": "urn:partition:stocks-v1", "species": "sockeye", "statistic": "sum",
            "unit": "fish", "measure": "spawning-ground arrivals", "complete": True,
            "evidence": "Annual report, table 4 total", "reported": sum(v for _, v in rows),
            "components": components}


def fixture(shared=True):
    first = source("a", [("a", 7), ("b", 7)])
    second = source("b", [("b", 7), ("c", 3)] if shared else [("c", 3)])
    return {"sources": [first, second], "target": {
        **{key: first[key] for key in ("year", "frame", "species", "statistic", "unit", "measure")},
        "atoms": ["urn:fish:a", "urn:fish:b", "urn:fish:c"], "evidence": "Stock register, Table 1"}}


class CoverageTests(unittest.TestCase):
    def test_disjoint_and_equal_values(self):
        result = assess(fixture(False))
        self.assertEqual((result["decision"], result["union_value"]), ("add_totals", 17))
        self.assertTrue(result["directly_addable"])

    def test_rebuilt_and_sparql_replay(self):
        data = fixture()
        data["sources"][1]["components"][0]["atoms"][0]["role"] = "represented"
        with tempfile.TemporaryDirectory() as tmp:
            src, rdf = (Path(tmp) / name for name in ("input.json", "facts.trig"))
            src.write_text(json.dumps(data))
            run = subprocess.run([sys.executable, str(QUERY.with_suffix(".py")), src, "--trig", rdf],
                                 check=True, capture_output=True, text=True)
            result = json.loads(run.stdout)
            self.assertEqual(result["shared_atoms"], ["urn:fish:b"])
            self.assertEqual((result["decision"], result["union_value"]), ("rebuild_union", 17))
            self.assertFalse(result["directly_addable"])
            db = Dataset()
            db.parse(rdf, format="trig")
            matches = [r for r in db.query(QUERY.read_text()) if r.otherGraph is not None]
            self.assertEqual({str(r.role) for r in matches}, {"represented", "direct"})
            self.assertEqual(len(matches), 2)

    def test_alias_and_resolved_parent(self):
        data = fixture()
        data["target"].update(aliases={"urn:alias:b": "urn:fish:b"},
                              contains={"urn:district:bc": ["urn:fish:b", "urn:fish:c"]})
        components = data["sources"][1]["components"]
        components[0]["atoms"][0]["id"] = "urn:alias:b"
        components[0]["atoms"][0]["role"] = "represented"
        components[0]["atoms"] += components.pop(1)["atoms"]
        components[0]["id"] = "district bc"
        self.assertEqual(assess(data)["union_value"], 17)
        components[0]["atoms"] = [{"id": "urn:district:bc", "value": 10, "version": "1", "role": "direct"}]
        self.assertEqual(assess(data)["decision"], "withhold")
        data["target"]["atoms"].append("urn:district:bc")
        self.assertEqual(assess(data)["decision"], "withhold")

    def test_equal_totals_and_unequal_vintages(self):
        data = fixture()
        atom = data["sources"][1]["components"][0]["atoms"][0]
        for version in ("register-2", None, "unknown"):
            atom["version"] = version
            result = assess(data)
            self.assertEqual(result["coverage_status"], "overlap_demonstrated")
            self.assertEqual(result["decision"], "withhold")
            self.assertTrue(all(s["reconciled"] for s in result["sources"]))

    def test_discordant_estimates_and_incomplete_values(self):
        data = fixture()
        atom = data["sources"][1]["components"][0]["atoms"][0]
        atom["value"] = 8
        data["sources"][1]["reported"] = 11
        result = assess(data)
        self.assertEqual(result["shared_atoms"], ["urn:fish:b"])
        self.assertTrue(all(s["reconciled"] for s in result["sources"]))
        self.assertIsNone(result["union_value"])
        atom["value"] = None
        self.assertEqual(assess(data)["shared_atoms"], ["urn:fish:b"])

    def test_withhold_scope_unit_statistic_or_measure_mismatch(self):
        for key, addition in (("unit", "pairs"), ("measure", "effective spawners"), ("year", 1999),
                              ("species", "Chinook"), ("statistic", "mean"), ("frame", "urn:frame:number2")):
            with self.subTest(key=key):
                data = fixture()
                data["sources"][1][key] = addition
                self.assertEqual(assess(data)["decision"], "withhold")
        data = fixture()
        for entity in [data["target"], *data["sources"]]:
            entity["statistic"] = "mean"
        self.assertEqual(assess(data)["decision"], "withhold")

    def test_missing_components_reconciliation_unresolved_titles(self):
        for field, value in (("reported", 9), ("complete", False), ("components", []),
                             ("evidence", "Annual Salmon Data"), ("version", "unknown")):
            with self.subTest(field=field):
                data = fixture()
                data["sources"][0][field] = value
                self.assertEqual(assess(data)["decision"], "withhold")
        data = fixture()
        data["sources"][0]["components"][1]["evidence"] = "Report A"
        result = assess(data)
        self.assertEqual(result["shared_atoms"], [])
        self.assertEqual(result["coverage_status"], "unresolved")
        data = fixture()
        data["sources"][0]["components"][1]["resolved"] = False
        self.assertIsNone(assess(data)["union_value"])
        data = fixture()
        data["target"]["atoms"].append("urn:fish:d")
        self.assertIsNone(assess(data)["union_value"])

    def test_internal_duplication_graph_collision_and_precision(self):
        data = fixture()
        data["sources"][1]["components"][0]["atoms"] *= 2
        assessment = assess(data)
        self.assertIsNone(assessment["union_value"])
        self.assertTrue(assessment["sources"][0]["reconciled"])
        self.assertFalse(assessment["sources"][1]["reconciled"])
        data = fixture()
        data["sources"][1]["graph"] = data["sources"][0]["graph"]
        with self.assertRaisesRegex(ValueError, "distinct source graph"):
            assess(data)
        data = fixture(False)
        data["sources"][1]["reported"] = "0.00000000000000000000000000000001"
        data["sources"][1]["components"][0]["atoms"][0]["value"] = data["sources"][1]["reported"]
        self.assertEqual(assess(data)["union_value"], "14.00000000000000000000000000000001")
