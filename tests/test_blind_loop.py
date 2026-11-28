"""Fixtures for the blind-loop draw and citation checker."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

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


packet = load("packet")


class PacketTest(unittest.TestCase):
    def test_non_pdf_documents_get_one_text_page(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "lib/files").mkdir(parents=True)
            (d / "lib/files/a.csv").write_text("year,escapement\n2019,1234\n")
            (d / "lib/files/b.html").write_text("<html><script>x()</script><p>Total &amp; 618,889</p></html>")
            (d / "lib/m.json").write_text(json.dumps([{"file": "files/a.csv", "title": "A"},
                                                       {"file": "files/b.html", "title": "B"}]))
            m = packet.build([d / "lib/m.json"], d / "out")
            self.assertEqual([x["n_pages"] for x in m["documents"]], [1, 1])
            self.assertIn("2019,1234", (d / "out/text/D01/page-001.txt").read_text())
            page = (d / "out/text/D02/page-001.txt").read_text()
            self.assertIn("Total & 618,889", page)
            self.assertNotIn("x()", page)

    def test_xlsx_rows_resolve_shared_strings_and_check_against_packet_text(self):
        main = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
        parts = {
            "xl/workbook.xml": f'<workbook {main} {rel}><sheets><sheet name="WCVI Data" sheetId="1" r:id="rId1"/>'
                               '</sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                                          'relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                                          '</Relationships>',
            "xl/sharedStrings.xml": f'<sst {main}><si><t>River</t></si><si><t>Sarita</t></si></sst>',
            "xl/worksheets/sheet1.xml": f'<worksheet {main}><sheetData>'
                                        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>2019</v></c></row>'
                                        '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="C2"><v>1329</v></c></row>'
                                        '</sheetData></worksheet>',
        }
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "lib/files").mkdir(parents=True)
            with zipfile.ZipFile(d / "lib/files/n.xlsx", "w") as z:
                for name, xml in parts.items():
                    z.writestr(name, xml)
            (d / "lib/m.json").write_text(json.dumps([{"file": "files/n.xlsx", "title": "NuSEDS"}]))
            packet.build([d / "lib/m.json"], d / "out")
            self.assertEqual((d / "out/text/D01/page-001.txt").read_text(),
                             "# sheet: WCVI Data\nRiver\t2019\nSarita\t\t1329\n")
            (d / "out/pages/D01").mkdir(parents=True)
            (d / "out/pages/D01/page-002.png").write_bytes(b"")
            (d / "m").mkdir()
            (d / "m/claims.json").write_text(json.dumps({"claims": [{"claim_id": "C1", "evidence": [
                {"doc_id": "D01", "page": 1, "quote": "Sarita 1329"},
                {"doc_id": "D01", "page": 2, "quote": "Table 1 (transcribed from image)"}]}]}))
            out = cc.check(d / "m", [], d / "out")
            self.assertEqual([r["status"] for r in out["quote_rows"]], ["exact_on_page", "cited_page_rendered"])


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
            {"statement": "planted true", "truth": "true"},
            {"statement": "planted false", "truth": "false", "mutation": "wrong column", "reason": "r"},
            {"statement": "planted bare", "truth": "unsupported", "mutation": "scope transfer"}]))
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
        self.assertEqual(len(self.items), 7)
        for leak in ("astra", "fable", "claim_id", '"p"', "planted", "truth", "mutation", "reason"):
            self.assertNotIn(leak, text.replace("planted true", "").replace("planted false", "").replace(
                "planted bare", ""))

    GRADERS = {"a": "openai/sol", "b": "google/gemini", "c": "anthropic/opus"}

    def label(self, g, verdict_for):
        items = [{"item_id": i["item_id"], "verdict": verdict_for(self.key["items"][i["item_id"]], i)}
                 for i in self.items]
        (self.r / "grading" / g).mkdir(parents=True, exist_ok=True)
        (self.r / "grading" / g / "c1.labels.json").write_text(json.dumps({"items": items}))

    def label_all(self):
        honest = lambda src, it: src.get("truth", "true")
        self.label("a", honest)
        self.label("b", honest)
        self.label("c", lambda src, it: "unsupported" if src.get("model") == "openai/astra" else honest(src, it))

    def test_score_planted_leniency_and_queues(self):
        self.label_all()
        out = pool.score(self.r, self.GRADERS)
        self.assertEqual(out["planted"]["a"]["sensitivity"], {"n": 2, "of": 2, "rate": 1.0})  # false + unsupported
        self.assertEqual(out["planted"]["a"]["exact_on_negatives"]["n"], 2)
        self.assertEqual(out["planted"]["c"]["specificity"]["rate"], 1.0)
        self.assertEqual(out["planted_by_mutation"]["scope transfer"], {"n": 3, "of": 3, "rate": 1.0})
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
        authority = {"route_by_publisher": {"Pacific Fishery Management Council": "Pacific Fishery Management Council"},
                     "route_by_case": {"c1": "Deschutes estimators"}}
        out = json.loads(json.dumps(pool.score(self.r, self.GRADERS, authority), default=dict))
        self.assertEqual(list(out["custodian_questions_by_route"]), ["Deschutes estimators"])  # the case wins
        d01, d02 = out["custodian_questions_by_route"]["Deschutes estimators"]
        self.assertEqual((d01["asked_by"], sorted(q["errata"] for q in d01["questions"])), (2, [False, True]))
        self.assertEqual(d01["hold"], ["Confederated Tribes of the Warm Springs Reservation of Oregon"])
        self.assertEqual(d02["hold"], [])  # "National" is not "nation"
        paths = pool.sheets(out, self.r, self.r / "sheets", authority)
        sheet = self.r / "sheets/held/custodian-deschutes-estimators.md"  # no relationship named, so held
        self.assertIn(sheet, paths)
        text, cover = sheet.read_text(), sheet.with_suffix(".cover.md").read_text()
        self.assertIn("https://x/a.pdf#page=3", text)
        self.assertNotIn("Warm Springs Reservation of Oregon (relationship", text)  # the hold is internal
        self.assertIn("relationship **none named**", cover)
        self.assertLess(text.index("your own words"), text.index("Possible errors"))
        self.assertLess(text.index("Possible errors"), text.index("☐ 17,993"))
        self.assertLess(text.index("☐ 17,993"), text.index("## Questions"))  # errata are flagged per question
        self.assertEqual(text.count("Neither"), 1)
        self.assertIn("☐ every year in this series", text)
        sci = (self.r / "sheets" / "assessment-scientist-c1.md").read_text()
        self.assertEqual(sci.count("Evidence cited"), 4)  # 2 contested + 2 audited, shuffled together
        self.assertIn("☐ Partly (which part?)", sci)
        for leak in ("verdict", "unsupported", "openai/astra", "anthropic/fable"):
            self.assertNotIn(leak, sci)
        relationship = {**authority, "relationship": {
            "Confederated Tribes of the Warm Springs Reservation of Oregon": "(named person, programme)"}}
        paths = pool.sheets(out, self.r, self.r / "sheets2", relationship)
        self.assertIn(self.r / "sheets2/custodian-deschutes-estimators.md", paths)

    def test_edits_and_cap(self):
        q = [{"id": f"Q{i}", "question": f"Question {i}?", "answer_type": "yes_no", "choices": [], "errata": False}
             for i in range(8)]
        cells = [{"case_id": "c1", "doc_id": "D01", "page": 1, "title": "T", "url": "", "collected_by": [],
                  "hold": [], "asked_by": 1, "questions": q}]
        edits = {"Q0": {"id": "Q0", "action": "drop", "reason": "duplicate", "by": "steward"},
                 "Q7": {"id": "Q7", "action": "replace", "question": "Neutral question?", "priority": 0,
                        "reason": "leading", "by": "steward"}}
        sheet, cover, held = pool.custodian_sheet("X", cells, {}, edits)
        self.assertFalse(held)
        self.assertEqual(sheet.count("☐ Yes"), pool.CAP)
        self.assertLess(sheet.index("Neutral question?"), sheet.index("Question 1?"))
        self.assertNotIn("Question 0?", sheet)
        self.assertIn("2 held back for a follow-up, 1 dropped", cover)

    def test_holds(self):
        self.assertEqual(pool.holds(["National Marine Fisheries Service"], {}), [])
        self.assertEqual(pool.holds(["Kuskokwim Native Association"], {}), ["Kuskokwim Native Association"])
        tac = "U.S. v. Oregon Technical Advisory Committee"
        self.assertEqual(pool.holds([tac], {"includes_indigenous_members": [tac]}), [tac])

    def test_fleiss_perfect_and_chance(self):
        self.assertEqual(pool.fleiss([["true"] * 3, ["false"] * 3]), 1.0)


if __name__ == "__main__":
    unittest.main()
