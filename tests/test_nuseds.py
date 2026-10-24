"""Semantic and reproducibility contracts for the legacy NuSEDS adapter.

Fixtures exercise the source-to-graph join boundary without a network, source
download, model call, or full 300 MB dataset rebuild.
"""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
import pandas as pd
import pyoxigraph as ox


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nuseds_pipeline", ROOT / "pipelines/psf-nuseds-cleaned.py")
nuseds = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nuseds)
C = nuseds.C


class Vocabulary:
    def __init__(self, enumeration=False):
        self.enumeration = enumeration

    def exists(self, iri):
        return iri != C.NS["gcdfo"] + "EnumerationMethod" or self.enumeration


def source_rows():
    base = dict(ACT_ID=1, cuid=1, cu_name_pse="Alpha", cu_name_dfo="DFO Alpha",
                FULL_CU_IN_PSE="PSE-1", FULL_CU_IN="DFO-1", SPECIES="Pink",
                SPECIES_QUALIFIED="PKE", regionid=1, region="Fraser", CU_TYPE="Current",
                CU_LAT=50.0, CU_LONGT=-120.0, GFE_ID=11, sys_nm="Stream A",
                GAZETTED_NAME="A", WATERBODY="A", GFE_TYPE="Stream", Y_LAT=50.0,
                X_LONGT=-120.0, WATERSHED_CDE="W1", FWA_WATERSHED_CDE="F1", StatArea="1",
                streamid=10, IS_INDICATOR="Y", POP_ID=100, POPULATION="Pink population",
                IndexId="100-PKE", Year=2000, ESTIMATE_CLASSIFICATION=None, MAX_ESTIMATE=15.5,
                Spawners=7.5)
    return [base, {**base, "ACT_ID": 2, "cuid": 2, "cu_name_pse": "Beta", "FULL_CU_IN_PSE": "PSE-2",
                   "SPECIES_QUALIFIED": "PKO", "IndexId": "100-PKO", "GFE_ID": 22,
                   "sys_nm": "Stream B", "Year": 2001, "ESTIMATE_CLASSIFICATION": "",
                   "MAX_ESTIMATE": 22.25, "Spawners": 8.0},
            {**base, "ACT_ID": 3, "FULL_CU_IN": "DFO-OTHER", "ESTIMATE_CLASSIFICATION": "TRUE ABUNDANCE (TYPE-1)",
             "MAX_ESTIMATE": 30.0, "Spawners": 20.0}]


def connection(rows=None):
    c = duckdb.connect()
    c.execute("SET threads = 1")
    c.register("source_frame", pd.DataFrame(source_rows() if rows is None else rows))
    c.execute("CREATE TABLE src AS SELECT * FROM source_frame")
    return c


def stored(builder):
    store = ox.Store()
    store.bulk_extend(builder.quads)
    return store


class NuSEDSContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_max_and_cube_do_not_claim_spawner_semantics(self):
        main = nuseds.build_dict(nuseds.COLS, nuseds.MAIN_T, {})
        cube = nuseds.build_dict(nuseds.CUBE_COLS, nuseds.CUBE_T, {})
        maximum = main.loc[main.column_name == "MAX_ESTIMATE"].iloc[0]
        aggregate = cube.loc[cube.column_name == "spawner_abundance"].iloc[0]
        for row in (maximum, aggregate):
            self.assertIsNone(row.term_iri)
            self.assertIsNone(row.constraint_iri)
        self.assertEqual(maximum.column_label, "Source MAX_ESTIMATE")
        self.assertEqual(aggregate.column_label, "Sum of source MAX_ESTIMATE")
        self.assertEqual(main.loc[main.column_name == "NATURAL_ADULT_SPAWNERS", "term_iri"].iloc[0],
                         C.NS["gcdfo"] + "SpawnerAbundance")
        self.assertFalse(nuseds.decompositions(pd.concat([main, cube])).column_name.isin(
            ["MAX_ESTIMATE", "spawner_abundance"]).any())

    def test_angling_is_a_gap_until_the_pinned_vocabulary_declares_its_target(self):
        for declared in (False, True):
            x = nuseds.crosswalks(Vocabulary(declared))["primary_enumeration_method"]
            row = x.loc[x.nuseds_value == "Based on Angling Catch"].iloc[0]
            if declared:
                self.assertEqual(row.ontology_term, "gcdfo:EnumerationMethod")
            else:
                self.assertTrue(pd.isna(row.ontology_term))
                self.assertIn("pinned gcdfo", row.notes)

    def test_sssom_attributes_only_corpus_additions_to_the_agent(self):
        codes = pd.DataFrame({"column_name": ["ESTIMATE_CLASSIFICATION", "ESTIMATE_CLASSIFICATION", "ESTIMATE_METHOD"],
                              "code_value": ["NO SURVEY", "TRUE ABUNDANCE (TYPE-1)", "Fence Count"]})
        paths = nuseds.write_sssom(codes, self.folder, "a" * 64, Vocabulary())
        rows = pd.concat([pd.read_csv(p, sep="\t", comment="#", keep_default_na=False) for p in paths])
        agent = rows.loc[rows.subject_label.isin(["NO SURVEY", "Fence Count"])]
        upstream = rows.loc[rows.subject_label == "TRUE ABUNDANCE (TYPE-1)"]
        self.assertEqual(set(agent.mapping_justification), {"semapv:AgentBasedMatching"})
        self.assertEqual(set(agent.author_id), {nuseds.AGENT})
        self.assertEqual(set(upstream.mapping_justification), {"semapv:ManualMappingCuration"})
        self.assertEqual(set(upstream.author_id), {""})

    def test_null_classification_has_a_graph_code_even_without_an_aggregate(self):
        c = connection([source_rows()[0]])
        self.addCleanup(c.close)
        dictionary = pd.DataFrame({"column_role": ["categorical"], "column_name": ["ESTIMATE_CLASSIFICATION"]})
        codes = nuseds.build_codes(c, dictionary, nuseds.MAIN_T, "src", Vocabulary())
        self.assertEqual(codes.code_value.tolist(), ["MISSING"])
        self.assertEqual(nuseds.code_iri("ESTIMATE_CLASSIFICATION", codes.code_value.iloc[0]),
                         nuseds.code_iri("ESTIMATE_CLASSIFICATION", None))

    def test_candidates_have_statement_provenance_without_live_join_edges(self):
        g = C.G()
        iri = nuseds.review_assertion(g, "https://example.org/a", "skos:closeMatch", "https://example.org/b",
            nuseds.GRAPHS["crosswalk"], evidence=[nuseds.SRC_DS, nuseds.META_URL],
            note="Candidate source pairing", justification=nuseds.SEMAPV_AGENT)
        store = stored(g)
        self.assertFalse(bool(store.query("ASK { <https://example.org/a> <http://www.w3.org/2004/02/skos/core#closeMatch> <https://example.org/b> }", use_default_graph_as_union=True)))
        properties = {q.predicate.value: q.object for q in store.quads_for_pattern(C.N(iri), None, None, None)}
        for name, value in [("reviewStatus", "awaitingReview"), ("criticality", "critical"), ("confidence", "mediumConfidence")]:
            self.assertEqual(properties[nuseds.PROFILE + name], C.N(nuseds.PROFILE + value))
        self.assertEqual(properties[C.NS["rdf"] + "predicate"], C.N("skos:closeMatch"))
        self.assertEqual(properties[C.NS["prov"] + "wasAttributedTo"], C.N(nuseds.AGENT))
        self.assertEqual(properties[C.NS["sssom"] + "mapping_justification"], C.N(nuseds.SEMAPV_AGENT))

    def test_all_source_cu_and_pink_population_pairings_survive(self):
        g, c = C.G(), connection()
        self.addCleanup(c.close)
        stats = nuseds.add_identities(g, c)
        store = stored(g)
        statements = list(store.query("""SELECT ?s ?p ?o ?g WHERE { GRAPH ?g {
            ?statement a <http://www.w3.org/1999/02/22-rdf-syntax-ns#Statement> ;
              <http://www.w3.org/1999/02/22-rdf-syntax-ns#subject> ?s ;
              <http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate> ?p ;
              <http://www.w3.org/1999/02/22-rdf-syntax-ns#object> ?o . } }"""))
        crosswalk = [r for r in statements if r["g"].value == nuseds.GRAPHS["crosswalk"]]
        population = [r for r in statements if r["p"].value == C.NS["smn"] + "populationOf"]
        self.assertEqual(len(crosswalk), 3)
        self.assertEqual(len(population), 2)
        self.assertEqual(stats, {"cu": 2, "streams": 2, "sites": 1, "populations": 1})
        self.assertFalse(any(q.predicate == C.N("gcdfo:hasConservationUnit") for q in store))
        self.assertFalse(any(q.predicate in (C.N("skos:exactMatch"), C.N("skos:closeMatch"), C.N("smn:populationOf")) for q in store))
        comments = [q.object.value for q in store if q.predicate == C.N("rdfs:comment")]
        self.assertTrue(any('"IndexId": ["100-PKE"]' in text for text in comments))
        self.assertTrue(any('"IndexId": ["100-PKO"]' in text for text in comments))
        site_edges = list(store.quads_for_pattern(C.N(C.ident("site", "psf-streamid", 10)), C.N(C.NS["def"] + "atStream"), None, None))
        self.assertEqual(len(site_edges), 2)

    def test_source_order_does_not_change_identity_bytes(self):
        data = []
        for i, rows in enumerate((source_rows(), list(reversed(source_rows())))):
            c, g = connection(rows), C.G()
            self.addCleanup(c.close)
            nuseds.add_identities(g, c)
            data.append(g.write(self.folder / f"identity-{i}.trig").read_bytes())
        self.assertEqual(data[0], data[1])

    def test_parquet_and_rdf_share_missing_classification_iris_and_preserve_numbers(self):
        c = connection()
        self.addCleanup(c.close)
        path = self.folder / "source.parquet"
        nuseds.write_iri_parquet(c, path)
        rows = c.execute(f"SELECT ACT_ID, MAX_ESTIMATE, Spawners, estimate_classification_iri FROM read_parquet('{path}') ORDER BY ACT_ID").fetchall()
        self.assertEqual([row[:3] for row in rows], [(1, 15.5, 7.5), (2, 22.25, 8.0), (3, 30.0, 20.0)])
        missing = nuseds.code_iri("ESTIMATE_CLASSIFICATION", "MISSING")
        self.assertEqual(rows[0][3], missing)
        self.assertEqual(rows[1][3], missing)
        self.assertEqual(nuseds.code_iri("ESTIMATE_CLASSIFICATION", pd.NA), missing)
        self.assertEqual(nuseds.code_iri("ESTIMATE_CLASSIFICATION", "  "), missing)
        first = path.read_bytes()
        nuseds.write_iri_parquet(c, path)
        self.assertEqual(first, path.read_bytes())

    def test_join_key_gate_rejects_a_missing_dataset_subject(self):
        c = connection()
        self.addCleanup(c.close)
        path = self.folder / "keys.parquet"
        nuseds.write_iri_parquet(c, path)
        st = ox.Store()
        for column in ("cu_iri", "stream_iri", "population_iri", "site_iri", "species_iri", "estimate_classification_iri"):
            for (iri,) in c.execute(f'SELECT DISTINCT "{column}" FROM read_parquet(\'{path}\') WHERE "{column}" IS NOT NULL').fetchall():
                st.add(ox.Quad(C.N(iri), C.N("rdf:type"), C.N("skos:Concept"), C.N(nuseds.GRAPHS["identity"])))
        counts = nuseds.validate_parquet_iris(st, c, path)
        self.assertEqual(counts["estimate_classification_iri"], 2)
        node = C.N(nuseds.code_iri("ESTIMATE_CLASSIFICATION", "MISSING"))
        for quad in list(st.quads_for_pattern(node, None, None, None)):
            st.remove(quad)
        with self.assertRaisesRegex(ValueError, "Orphan Parquet estimate_classification_iri"):
            nuseds.validate_parquet_iris(st, c, path)

    def test_reference_time_requires_an_explicit_pin_not_source_publication(self):
        with patch.object(nuseds, "RAW", self.folder), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "explicit"):
                nuseds.build_reference_time()
            os.environ["SALMONGRAPH_BUILD_TIME"] = "2026-10-23T19:00:00-07:00"
            self.assertEqual(nuseds.build_reference_time(), "2026-10-24T02:00:00Z")
            os.environ["SALMONGRAPH_BUILD_TIME"] = "2026-10-23T19:00:00"
            with self.assertRaisesRegex(ValueError, "timezone"):
                nuseds.build_reference_time()

    def test_competency_queries_keep_pending_classifications_out_of_live_types(self):
        g = C.G()
        graph = nuseds.GRAPHS["mappings"]
        codes = [nuseds.code_iri("ESTIMATE_CLASSIFICATION", name) for name in ("LIVE", "PENDING", "MISSING")]
        scheme = C.BASE + "code/nuseds/estimate-classification"
        cu, region, taxon = [C.BASE + "fixture/" + value for value in ("cu", "region", "species")]
        for i, code in enumerate(codes):
            g.add(code, "skos:inScheme", scheme, graph)
            g.add(code, "skos:prefLabel", C.L(("LIVE", "PENDING", "MISSING")[i]), graph)
            g.add(code, "dcterms:source", C.BASE + "mapping/fixture", graph)
            observation = C.BASE + f"fixture/observation/{i}"
            for predicate, obj in [(C.NS["def"] + "conservationUnit", cu),
                                   (C.NS["def"] + "estimateClassification", code),
                                   ("smn:returnYear", C.L("2020", "xsd:gYear")),
                                   (C.NS["def"] + "siteCount", C.L(10))]:
                g.add(observation, predicate, obj, nuseds.GRAPHS["cube"])
        g.add(scheme, "rdfs:label", C.L("Classification codes"), graph)
        g.add(codes[0], "skos:exactMatch", "gcdfo:Type1", graph)
        g.add("gcdfo:Type1", "skos:prefLabel", C.L("Type 1"), graph)
        g.add("gcdfo:Type5", "skos:prefLabel", C.L("Type 5"), graph)
        for code, target in [(codes[1], "gcdfo:Type5"), (codes[1], "gcdfo:Type6"),
                             (codes[2], "sssom:NoTermFound")]:
            nuseds.review_assertion(g, code, "skos:exactMatch", target, graph,
                evidence=[nuseds.SRC_DS], note="Pending classification", justification=nuseds.SEMAPV_AGENT)
        for subject, predicate, obj in [(cu, "skos:prefLabel", C.L("CU")),
                                        (cu, C.NS["def"] + "pseCuIndex", C.L("CU-1")),
                                        (cu, C.NS["def"] + "region", region),
                                        (cu, C.NS["def"] + "taxon", taxon),
                                        (region, "skos:prefLabel", C.L("Fraser")),
                                        (taxon, "rdfs:label", C.L("Pink salmon"))]:
            g.add(subject, predicate, obj, nuseds.GRAPHS["identity"])
        st = stored(g)
        def query(name):
            text = (ROOT / "queries" / nuseds.SLUG / name).read_text().replace(
                "https://w3id.org/salmon-demo-corpus/", C.BASE)
            return list(st.query(text, use_default_graph_as_union=True))
        coverage = query("02-classification-by-decade.rq")
        self.assertEqual(sum(int(row["site_estimates"].value) for row in coverage), 30)
        self.assertEqual(sum(row["mapping_state"].value == "pending agent interpretation" for row in coverage), 2)
        self.assertFalse(any(row["estimate_type"].value == "Type 5" for row in coverage))
        screen = query("03-low-quality-cus.rq")
        self.assertEqual(len(screen), 1)
        self.assertEqual(int(screen[0]["type5_6_estimates"].value), 0)
        self.assertEqual(int(screen[0]["unresolved_classification_estimates"].value), 20)
        evidence = query("07-mapping-evidence.rq")
        self.assertEqual(len(evidence), 4)
        self.assertEqual(sum(row["mapping_state"].value == "pending agent candidate" for row in evidence), 3)


if __name__ == "__main__":
    unittest.main()
