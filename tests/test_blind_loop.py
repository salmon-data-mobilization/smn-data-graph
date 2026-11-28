"""Fixtures for the blind-loop draw and citation checker."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "scripts/blind_loop"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


draw = load("draw")
cc = load("check_citations")

FRAME = json.dumps({"cases": [
    {"case_id": "adfg-a-2019"}, {"case_id": "adfg-b-2019"}, {"case_id": "cdfw-c-2019"},
    {"case_id": "wdfw-d-2017"}, {"case_id": "x-e-2018", "stratum": "S1"},
]}).encode()


class DrawTest(unittest.TestCase):
    def test_repeatable_and_prefers_undrawn_strata(self):
        a = draw.draw(FRAME, "r2", ["adfg-a-2019"], 3)
        self.assertEqual(a, draw.draw(FRAME, "r2", ["adfg-a-2019"], 3))
        self.assertNotIn("ADFG", a["chosen_strata"])
        self.assertEqual(len(set(a["drawn"])), 3)

    def test_label_changes_seed(self):
        self.assertNotEqual(draw.draw(FRAME, "r2", [], 2)["seed_hex"], draw.draw(FRAME, "r3", [], 2)["seed_hex"])

    def test_too_few_strata(self):
        with self.assertRaises(ValueError):
            draw.draw(FRAME, "r2", [], 6)

    def test_skips_shared_documents(self):
        frame = json.dumps({"cases": [
            {"case_id": "a-1", "stratum": "S1", "documents": [{"url": "u1"}]},
            {"case_id": "b-1", "stratum": "S2", "documents": [{"url": "u1"}, {"url": "u2"}]},
            {"case_id": "b-2", "stratum": "S2", "documents": [{"url": "u3"}]},
            {"case_id": "c-1", "stratum": "S3", "documents": [{"url": "u1"}]}]}).encode()
        out = draw.draw(frame, "r2", ["a-1"], 1)
        self.assertEqual(out["drawn"], ["b-2"])
        with self.assertRaises(ValueError):
            draw.draw(frame, "r2", ["a-1"], 2)

    def test_case_file_hides_reported_values(self):
        case = {"case_id": "x-1", "stock": "X coho", "species": "Coho salmon", "return_year": 2021,
                "jurisdiction": "Oregon", "documents": [{"title": "T", "publisher": "P", "year": 2022, "url": "u",
                                                         "locator": "Table 6.", "reported_value": 6354,
                                                         "reported_label": "wild"}]}
        text = draw.case_file(case) + json.dumps(draw.shown(case))
        self.assertNotIn("6354", text)
        self.assertNotIn("wild", text)
        self.assertIn("The figure appears at: Table 6.\n", draw.case_file(case))


class CitationTest(unittest.TestCase):
    PAGES = [cc.tokens("Title page"), cc.tokens("The escapement of 1,234 large fish was\n"
                                              "pre-\nliminary in 2019."), cc.tokens("x")]

    def test_exact_on_cited_page_ignores_breaks_and_hyphenation(self):
        self.assertEqual(cc.locate_quote("escapement of 1,234 large fish was preliminary", self.PAGES, 2),
                         "exact_on_page")

    def test_wrong_page_and_missing(self):
        self.assertEqual(cc.locate_quote("1,234 large fish", self.PAGES, 1), "adjacent_page")
        self.assertEqual(cc.locate_quote("4,321 large fish", self.PAGES, 2), "not_found")

    def test_elided_quote_reports_worst_part(self):
        self.assertEqual(cc.locate_quote("escapement of … 9,999", self.PAGES, 2), "not_found")
        self.assertEqual(cc.locate_quote("escapement of … large fish", self.PAGES, 2), "exact_on_page")

    def test_image_page_is_unchecked_not_missing(self):
        self.assertEqual(cc.locate_quote("618,889", self.PAGES, 3), "cited_page_has_no_text")
        self.assertEqual(cc.locate_quote("1,234 large fish", self.PAGES, 3), "adjacent_page")

    def test_folder_with_text_document(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / "doc.txt").write_text("Net escapement was 618,889 sockeye.")
            (folder / "claims.json").write_text(json.dumps({
                "documents": [{"doc_id": "D1", "file": "doc.txt"}],
                "figures": [{"figure_id": "F1", "doc_id": "D1", "value": 618889, "pdf_page": 1}],
                "claims": [{"claim_id": "C1", "evidence": [{"doc_id": "D1", "pdf_page": 1,
                                                             "quote": "escapement was 618,889"}]}]}))
            out = cc.check(folder, [])
            self.assertEqual(out["quotes"], {"exact_on_page": 1})
            self.assertEqual(out["values"], {"exact_on_page": 1})


pool = load("pool")


class PoolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.r = Path(self.tmp.name)
        claims = lambda tag: {"figures": [{"figure_id": "F1", "doc_id": "D01", "page": 3, "value": 10}],
                              "claims": [{"claim_id": f"C{i}", "statement": f"{tag} claim {i}", "critical": True,
                                          "basis": "printed", "p": 0.9, "evidence": [{"doc_id": "D01", "page": 3}]}
                                         for i in (1, 2)],
                              "fitness": {"trend": {"choice": "fit", "figure_ids": ["F1"]}}}
        for tag in ("openai", "anthropic"):
            (self.r / f"{tag}.json").write_text(json.dumps(claims(tag)))
        (self.r / "planted.json").write_text(json.dumps([
            {"statement": "planted true", "truth": "true"}, {"statement": "planted false", "truth": "false"}]))
        (self.r / "packet/c1").mkdir(parents=True)
        (self.r / "packet/c1/manifest.json").write_text(json.dumps({"documents": [{"doc_id": "D01", "publisher": "ADF&G"}]}))
        pool.blind("c1", {"openai/astra": self.r / "openai.json", "anthropic/fable": self.r / "anthropic.json"},
                   self.r / "planted.json", self.r / "pool/c1", self.r / "coordinator/keys")
        self.items = json.loads((self.r / "pool/c1/items.json").read_text())["items"]
        self.key = json.loads((self.r / "coordinator/keys/c1.key.json").read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def test_blind_strips_identity_and_probability(self):
        text = (self.r / "pool/c1/items.json").read_text() + (self.r / "pool/c1/fitness.json").read_text()
        self.assertEqual(len(self.items), 6)
        for leak in ("astra", "fable", "claim_id", '"p"', "planted", "truth"):
            self.assertNotIn(leak, text.replace("planted true", "").replace("planted false", ""))

    GRADERS = {"a": "openai/sol", "b": "google/gemini", "c": "anthropic/opus"}

    def label(self, g, verdict_for):
        items = [{"item_id": i["item_id"], "verdict": verdict_for(self.key["items"][i["item_id"]], i)}
                 for i in self.items]
        (self.r / "grading" / g).mkdir(parents=True, exist_ok=True)
        (self.r / "grading" / g / "c1.labels.json").write_text(json.dumps({"items": items}))

    def label_all(self):
        honest = lambda src, it: "false" if src.get("truth") == "false" else "true"
        self.label("a", honest)
        self.label("b", honest)
        self.label("c", lambda src, it: "unsupported" if src.get("model") == "openai/astra" else honest(src, it))

    def test_score_planted_leniency_and_queues(self):
        self.label_all()
        out = pool.score(self.r, self.GRADERS)
        self.assertEqual(out["planted"]["a"]["sensitivity"]["rate"], 1.0)
        self.assertEqual(out["planted"]["c"]["specificity"]["rate"], 1.0)
        self.assertEqual(out["agreement_natural"]["items"], 4)  # planted items are never pooled in
        self.assertLess(out["agreement_natural"]["fleiss_kappa"], 1)
        self.assertEqual(out["mappers"]["openai/astra"]["precision_majority_true"]["rate"], 1.0)
        lean = out["leniency_on_contested_items"]
        self.assertLess(lean["c"]["other_family"]["mean"], 0)
        self.assertEqual(lean["c"]["same_family"], {"items": 0, "mean": None})  # not estimable, not zero
        self.assertEqual(lean["a"]["same_family"]["mean"], 0.5)
        self.assertEqual(len(out["scientist_queue"]), 2)
        self.assertEqual(len(out["audit_sample"]), 2)

    def test_custodian_questions_routed_held_and_sheeted(self):
        self.label_all()
        manifest = {"documents": [
            {"doc_id": "D01", "publisher": "Pacific Fishery Management Council", "url": "https://x/a.pdf",
             "title": "Review", "collected_by": ["Oregon Department of Fish and Wildlife",
                                                 "Confederated Tribes of the Warm Springs Reservation of Oregon"]},
            {"doc_id": "D02", "publisher": "NOAA Fisheries, Northwest Region",
             "collected_by": ["National Marine Fisheries Service"]}]}
        (self.r / "packet/c1/manifest.json").write_text(json.dumps(manifest))
        for m, qs in {"openai-astra": [{"doc_id": "D01", "page": 3, "question": "Is 4,553 final?",
                                        "answer_type": "yes_no"},
                                       {"doc_id": "D02", "page": 5, "question": "How many fish?",
                                        "answer_type": "number"}],
                      "anthropic-fable": [{"doc_id": "D01", "page": 3, "question": "Is 17,933 as printed right?",
                                           "answer_type": "choice", "choices": ["17,933", "17,993"]}]}.items():
            (self.r / "mappers" / m / "c1").mkdir(parents=True)
            (self.r / "mappers" / m / "c1" / "claims.json").write_text(json.dumps({"custodian_questions": qs}))
        authority = {"route_by_publisher": {"Pacific Fishery Management Council": "U.S. v. Oregon TAC"}}
        out = json.loads(json.dumps(pool.score(self.r, self.GRADERS, authority), default=dict))
        [d01] = out["custodian_questions_by_route"]["U.S. v. Oregon TAC"]
        self.assertEqual((d01["asked_by"], d01["errata"], len(d01["questions"])), (2, True, 2))
        self.assertEqual(d01["hold"], ["Confederated Tribes of the Warm Springs Reservation of Oregon"])
        [d02] = out["custodian_questions_by_route"]["NOAA Fisheries"]
        self.assertEqual(d02["hold"], [])  # "National" is not "nation"
        paths = pool.sheets(out, self.r, self.r / "sheets", authority)
        text = next(p for p in paths if "tac" in p.name).read_text()
        self.assertIn("https://x/a.pdf#page=3", text)
        self.assertIn("**Hold:**", text)
        self.assertLess(text.index("Possible errors"), text.index("☐ 17,993"))
        self.assertIn("☐ every year in this series", text)
        sci = (self.r / "sheets" / "assessment-scientist.md").read_text()
        self.assertEqual(sci.count("Evidence cited"), 4)  # 2 contested + 2 audited, shuffled together
        for leak in ("verdict", "unsupported", "openai/astra", "anthropic/fable"):
            self.assertNotIn(leak, sci)

    def test_holds(self):
        self.assertEqual(pool.holds(["National Marine Fisheries Service"], {}), [])
        self.assertEqual(pool.holds(["Kuskokwim Native Association"], {}), ["Kuskokwim Native Association"])
        tac = "U.S. v. Oregon Technical Advisory Committee"
        self.assertEqual(pool.holds([tac], {"includes_indigenous_members": [tac]}), [tac])

    def test_fleiss_perfect_and_chance(self):
        self.assertEqual(pool.fleiss([["true"] * 3, ["false"] * 3]), 1.0)


if __name__ == "__main__":
    unittest.main()
