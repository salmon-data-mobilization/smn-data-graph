#!/usr/bin/env python
"""Rebuild the psf-nuseds-cleaned corpus slice from data/raw/psf-nuseds-cleaned/.

Stages (run all by default, or pick with --stages):
  fetch    download source files with curl, write SHA256SUMS + source.json
  profile  DuckDB column profile -> profiles/<slug>/column-profile.csv
  package  Salmon Data Package (metasalmonpy): dictionary, codes, semantics,
           observation structures, measurement decompositions, SSSOM, validation
  graph    RDF (TriG, named graphs) + IRI-keyed Parquet + pyoxigraph store
  queries  run queries/<slug>/*.rq against the store, write *.csv

Usage:
  .venv/bin/python -I pipelines/psf-nuseds-cleaned.py [--stages a,b,...]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import warnings
from pathlib import Path

import duckdb
import pandas as pd
import pyoxigraph as ox

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpuslib as C  # noqa: E402
from corpuslib import L, N, NS, ident  # noqa: E402

import metasalmonpy as ms  # noqa: E402

SLUG = "psf-nuseds-cleaned"
DATASET_ID = "psf_nuseds_cleaned"
MAIN_T = "nuseds_cuid_streamid"
CUBE_T = "cu_year_spawners"
RAW = C.ROOT / "data/raw" / SLUG
OUTPUT_ROOT = C.ROOT
PKG = C.ROOT / "packages" / SLUG
GRAPH_FILE = C.ROOT / "graph" / f"{SLUG}.trig"
STORE_DIR = C.ROOT / "graph/store" / SLUG
PARQUET = PKG / "data" / f"{MAIN_T}.iri-keyed.parquet"
QDIR = C.ROOT / "queries" / SLUG
PROFILE_DIR = C.ROOT / "profiles" / SLUG
CSV_NAME = "2_nuseds_cuid_streamid_2026-02-20.csv"
META_NAME = "METADATA_2_nuseds_cuid_streamid.csv"
DOI = "10.5281/zenodo.19959144"
RECORD_URL = "https://zenodo.org/api/records/19959144"
CSV_URL = f"https://zenodo.org/api/records/19959144/files/{CSV_NAME}/content"
META_URL = ("https://raw.githubusercontent.com/salmonwatersheds/population-indicators/"
            "master/spawner-surveys/output/" + META_NAME)
LICENCE = "https://creativecommons.org/licenses/by/4.0/"
ATTRIBUTION = ("Carturan, B. and Peacock, S. (2026). Cleaned spawner survey data. Pacific Salmon "
               "Foundation. Zenodo. https://doi.org/10.5281/zenodo.19959144. Licensed CC BY 4.0. "
               "Derived from Fisheries and Oceans Canada NuSEDS (2025-11-03 extract, Open Government "
               "Licence - Canada).")
NUSEDS_OPEN_DATA = "https://open.canada.ca/data/en/dataset/c48669a3-045b-400d-b730-48aafe8c5ee6"

GRAPHS = {k: f"{C.BASE}graph/{SLUG}/{k}" for k in ("metadata", "mappings", "identity", "crosswalk", "cube", "provenance")}
DS = f"{C.BASE}dataset/{SLUG}"
SRC_DS = f"https://doi.org/{DOI}"
PROFILE = C.BASE + "profile/"
AGENT = C.BASE + "agent/software/psf-nuseds-cleaned-pipeline"
SEMAPV_AGENT = "https://w3id.org/semapv/vocab/AgentBasedMatching"
PSC_EFS = "https://w3id.org/psc/vocab/concept/PSC-CV-000035"

# --------------------------------------------------------------------------
# Column specification. Descriptions come from PSF's METADATA_2_nuseds_cuid_streamid.csv
# when the field is listed there; otherwise from the text below (written by the corpus
# agent from the field name and observed values, NOT from the DFO NuSEDS data dictionary,
# which was not retrieved; marked "[agent]").
# role, value_type, unit_iri, label, fallback description
# --------------------------------------------------------------------------
INDIV = NS["unit"] + "INDIV"
NUM = NS["unit"] + "NUM"
PCT = NS["unit"] + "PERCENT"
COLS = [
    ("SPECIES", "categorical", "string", None, "Species", None),
    ("WATERSHED_CDE", "attribute", "string", None, "DFO watershed code", "[agent] DFO legacy watershed code of the waterbody."),
    ("FWA_WATERSHED_CDE", "attribute", "string", None, "BC FWA watershed code", "[agent] BC Freshwater Atlas watershed code of the waterbody."),
    ("POP_ID", "identifier", "integer", None, "NuSEDS population ID", None),
    ("GFE_ID", "identifier", "integer", None, "NuSEDS stream ID (GFE_ID)", None),
    ("FULL_CU_IN", "attribute", "string", None, "DFO CU index", None),
    ("IndexId", "identifier", "string", None, "Species-qualified population ID", None),
    ("cuid", "identifier", "integer", None, "PSE CU ID", None),
    ("cu_name_pse", "attribute", "string", None, "CU name (PSE)", None),
    ("CU_NAME", "attribute", "string", None, "CU name (DFO census sites)", None),
    ("AREA", "attribute", "string", None, "Subdistrict", None),
    ("WATERBODY", "attribute", "string", None, "Waterbody", None),
    ("GAZETTED_NAME", "attribute", "string", None, "Gazetted name", None),
    ("LOCAL_NAME_1", "attribute", "string", None, "Local name 1", None),
    ("LOCAL_NAME_2", "attribute", "string", None, "Local name 2", None),
    ("Year", "temporal", "integer", None, "Analysis year", None),
    ("NATURAL_ADULT_SPAWNERS", "measurement", "number", INDIV, "Natural adult spawners", "[agent] NuSEDS count/estimate of adult salmon spawning naturally (excluding broodstock removals)."),
    ("NATURAL_JACK_SPAWNERS", "measurement", "integer", INDIV, "Natural jack spawners", "[agent] NuSEDS count/estimate of jacks (precocious males) spawning naturally."),
    ("NATURAL_SPAWNERS_TOTAL", "measurement", "integer", INDIV, "Natural spawners total", "[agent] NuSEDS total natural spawners (adults + jacks)."),
    ("ADULT_BROODSTOCK_REMOVALS", "measurement", "integer", INDIV, "Adult broodstock removals", "[agent] Adults removed for hatchery broodstock."),
    ("JACK_BROODSTOCK_REMOVALS", "measurement", "integer", INDIV, "Jack broodstock removals", "[agent] Jacks removed for hatchery broodstock."),
    ("TOTAL_BROODSTOCK_REMOVALS", "measurement", "integer", INDIV, "Total broodstock removals", "[agent] All fish removed for hatchery broodstock."),
    ("OTHER_REMOVALS", "measurement", "integer", INDIV, "Other removals", "[agent] Other in-river removals (e.g. fisheries, mortalities)."),
    ("TOTAL_RETURN_TO_RIVER", "measurement", "number", INDIV, "Total return to river", "[agent] Total fish returning to the river (spawners + removals)."),
    ("ENUMERATION_METHODS", "attribute", "string", None, "Enumeration methods (list)", None),
    ("ADULT_PRESENCE", "categorical", "string", None, "Adult presence", None),
    ("JACK_PRESENCE", "categorical", "string", None, "Jack presence", None),
    ("START_DTT", "temporal", "string", None, "Survey start date", "[agent] Date the first inspection was made; format DD-MON-YY (two-digit year; century ambiguous)."),
    ("END_DTT", "temporal", "string", None, "Survey end date", "[agent] Date of the last inspection; format DD-MON-YY."),
    ("NATURAL_ADULT_FEMALES", "measurement", "integer", INDIV, "Natural adult females", "[agent] Natural adult female spawners."),
    ("NATURAL_ADULT_MALES", "measurement", "integer", INDIV, "Natural adult males", "[agent] Natural adult male spawners."),
    ("EFFECTIVE_FEMALES", "measurement", "integer", INDIV, "Effective females", "[agent] Females that spawned, adjusted for pre-spawn mortality."),
    ("WEIGHTED_PCT_SPAWN", "measurement", "number", PCT, "Weighted percent spawn", "[agent] Weighted percentage of eggs spawned by females."),
    ("WATERBODY_ID", "identifier", "string", None, "Waterbody ID", "[agent] NuSEDS waterbody identifier."),
    ("POPULATION", "attribute", "string", None, "Population name", None),
    ("RUN_TYPE", "categorical", "string", None, "Run type", "[agent] Run timing type (e.g. FALL, SUMMER); numeric values 1/2 also occur."),
    ("STREAM_ARRIVAL_DT_FROM", "temporal", "string", None, "Stream arrival date from", "[agent] Earliest stream arrival date, DD-MON-YY."),
    ("STREAM_ARRIVAL_DT_TO", "temporal", "string", None, "Stream arrival date to", "[agent] Latest stream arrival date, DD-MON-YY."),
    ("START_SPAWN_DT_FROM", "temporal", "string", None, "Start spawn date from", "[agent] DD-MON-YY."),
    ("START_SPAWN_DT_TO", "temporal", "string", None, "Start spawn date to", "[agent] DD-MON-YY."),
    ("PEAK_SPAWN_DT_FROM", "temporal", "string", None, "Peak spawn date from", "[agent] DD-MON-YY."),
    ("PEAK_SPAWN_DT_TO", "temporal", "string", None, "Peak spawn date to", "[agent] DD-MON-YY."),
    ("END_SPAWN_DT_FROM", "temporal", "string", None, "End spawn date from", "[agent] DD-MON-YY."),
    ("END_SPAWN_DT_TO", "temporal", "string", None, "End spawn date to", "[agent] DD-MON-YY."),
    ("ACCURACY", "categorical", "string", None, "Accuracy", "[agent] Qualitative accuracy rating (HIGH/MED/LOW/UNK)."),
    ("PRECISION", "categorical", "string", None, "Precision", "[agent] Qualitative precision rating (HIGH/MED/LOW/UNK)."),
    ("INDEX_YN", "categorical", "string", None, "Index flag", "[agent] Y/N/U flag; meaning not documented in PSF metadata."),
    ("RELIABILITY", "categorical", "string", None, "Reliability", "[agent] Qualitative reliability rating."),
    ("ESTIMATE_STAGE", "categorical", "string", None, "Estimate stage", "[agent] FINAL, NEAR FINAL or PRELIMINARY."),
    ("ESTIMATE_CLASSIFICATION", "categorical", "string", None, "Estimate classification", None),
    ("NO_INSPECTIONS_USED", "measurement", "integer", NUM, "Number of inspections used", "[agent] Number of stream inspections used for the estimate."),
    ("ESTIMATE_METHOD", "categorical", "string", None, "Estimate method", None),
    ("CREATED_DTT", "temporal", "string", None, "Record created date", "[agent] DD-MON-YY."),
    ("UPDATED_DTT", "temporal", "string", None, "Record updated date", "[agent] DD-MON-YY."),
    ("ACT_ID", "identifier", "integer", None, "NuSEDS activity ID", "[agent] NuSEDS activity (row) identifier; unique per row."),
    ("Returns", "measurement", "number", INDIV, "Returns (PSF)", "[agent] PSF-derived returns value; Source names the NuSEDS field(s) used."),
    ("Source", "categorical", "string", None, "Returns source", "[agent] NuSEDS field(s) PSF used for Returns."),
    ("Spawners", "measurement", "integer", INDIV, "Spawners (PSF)", "[agent] PSF-derived spawners value."),
    ("SpawnersSource", "categorical", "string", None, "Spawners source", "[agent] NuSEDS field used for Spawners."),
    ("Broodstock", "measurement", "integer", INDIV, "Broodstock (PSF)", "[agent] PSF-derived broodstock removals."),
    ("BroodstockSource", "categorical", "string", None, "Broodstock source", "[agent] NuSEDS field used for Broodstock."),
    ("Removals", "measurement", "integer", INDIV, "Removals (PSF)", "[agent] PSF-derived other removals."),
    ("RemovalsSource", "categorical", "string", None, "Removals source", "[agent] NuSEDS field used for Removals."),
    ("MAX_ESTIMATE", "measurement", "number", INDIV, "Source MAX_ESTIMATE", None),
    ("CENSUS_SITE", "attribute", "string", None, "Census site", None),
    ("GFE_TYPE", "categorical", "string", None, "Stream feature type", "[agent] Geographic feature type of GFE_ID (Stream, Lake, ...)."),
    ("SPECIES_QUALIFIED", "categorical", "string", None, "Species qualifier", None),
    ("Y_LAT", "attribute", "number", None, "Latitude", None),
    ("X_LONGT", "attribute", "number", None, "Longitude", None),
    ("FAZ_ACRO", "categorical", "string", None, "Freshwater adaptive zone", None),
    ("MAZ_ACRO", "categorical", "string", None, "Marine adaptive zone", None),
    ("JAZ_ACRO", "categorical", "string", None, "Joint adaptive zone", None),
    ("CU_ACRO", "attribute", "string", None, "CU acronym", "[agent] DFO CU acronym."),
    ("CU_LAT", "attribute", "number", None, "CU centroid latitude", None),
    ("CU_LONGT", "attribute", "number", None, "CU centroid longitude", None),
    ("CU_TYPE", "categorical", "string", None, "CU type", None),
    ("CU_INDEX", "attribute", "string", None, "CU index", "[agent] CU index number within species."),
    ("SBJ_ID", "attribute", "integer", None, "Species subject ID", "[agent] Numeric species code (1 Sockeye, 2 Coho, 3 Pink, 4 Chum, 5 Chinook in these data)."),
    ("IS_INDICATOR", "categorical", "string", None, "Indicator population", None),
    ("CMNTS", "attribute", "string", None, "Comments", "[agent] Free-text comments from DFO census-site table."),
    ("EFFECTIVE_DT", "temporal", "string", None, "Effective date", "[agent] Effective date of census-site record, D-Mon-YY."),
    ("coordinates_changed", "attribute", "boolean", None, "Coordinates changed", None),
    ("StatArea", "attribute", "string", None, "Statistical area", None),
    ("FULL_CU_IN_PSE", "attribute", "string", None, "CU index (PSE)", None),
    ("stream_survey_quality", "categorical", "string", None, "Stream survey quality", None),
    ("cu_name_dfo", "attribute", "string", None, "CU name (DFO)", None),
    ("region", "categorical", "string", None, "PSE region", None),
    ("regionid", "identifier", "integer", None, "PSE region ID", None),
    ("sys_nm", "attribute", "string", None, "Site name (PSE)", None),
    ("streamid", "identifier", "integer", None, "PSE stream ID", None),
    ("primary_enumeration_method", "categorical", "string", None, "Primary enumeration method (derived)",
     "[derived by corpus pipeline] First entry of ENUMERATION_METHODS (PSF metadata: 'The first method listed is the primary method')."),
]
DERIVED = {"primary_enumeration_method"}

CUBE_COLS = [
    ("cuid", "identifier", "integer", None, "PSE CU ID", "PSE Conservation Unit ID."),
    ("FULL_CU_IN_PSE", "attribute", "string", None, "CU index (PSE)", "CU index as defined by PSF."),
    ("cu_name_pse", "attribute", "string", None, "CU name (PSE)", "CU display name in the PSE."),
    ("SPECIES", "categorical", "string", None, "Species", "Species."),
    ("SPECIES_QUALIFIED", "categorical", "string", None, "Species qualifier", "CU species qualifier (CK, CM, CO, PKE, PKO, SEL, SER)."),
    ("regionid", "identifier", "integer", None, "PSE region ID", "PSE region ID."),
    ("region", "categorical", "string", None, "PSE region", "PSE region."),
    ("Year", "temporal", "integer", None, "Analysis year", "NuSEDS analysis (return/spawning) year."),
    ("ESTIMATE_CLASSIFICATION", "categorical", "string", None, "Estimate classification",
     "NuSEDS estimate classification of the contributing stream estimates ('MISSING' where blank)."),
    ("spawner_abundance", "measurement", "number", INDIV, "Sum of source MAX_ESTIMATE",
     "Sum of the source MAX_ESTIMATE values over CU stream sites, year and estimate classification. The legacy field name is retained; this is not asserted to be spawner abundance. Values are unchanged, not infilled or expanded."),
    ("n_sites", "measurement", "integer", NUM, "Number of stream sites",
     "Number of PSE stream sites (streamid) contributing a non-missing MAX_ESTIMATE."),
]

SPAWNER_COLS = {  # columns given term gcdfo:SpawnerAbundance, with extra constraint gaps
    "NATURAL_ADULT_SPAWNERS": ["adult life stage", "natural (in-river) spawning, excludes broodstock removals"],
    "NATURAL_JACK_SPAWNERS": ["jack (precocious male) life stage", "natural (in-river) spawning, excludes broodstock removals"],
    "NATURAL_SPAWNERS_TOTAL": ["natural (in-river) spawning, excludes broodstock removals"],
    "Spawners": ["PSF-derived: NATURAL_SPAWNERS_TOTAL or sum of components"],
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def build_reference_time() -> str:
    """Stable build reference, not an assertion about when execution ended.

    A pinned timestamp is required for the package/release creation reference.
    Source publication or retrieval dates are not package-creation dates. Real
    execution time is retained outside the reproducible dataset artifacts.
    """
    value = os.environ.get("SALMONGRAPH_BUILD_TIME")
    if value is None:
        raise ValueError("An explicit --build-time or SALMONGRAPH_BUILD_TIME is required for package/graph artifacts")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("SALMONGRAPH_BUILD_TIME must include a timezone")
    return parsed.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def configure_output_root(root: Path) -> None:
    """Rebuild into an isolated output tree while reading the same pinned inputs."""
    global OUTPUT_ROOT, PKG, GRAPH_FILE, STORE_DIR, PARQUET, QDIR, PROFILE_DIR
    OUTPUT_ROOT = root.resolve()
    PKG = OUTPUT_ROOT / "packages" / SLUG
    GRAPH_FILE = OUTPUT_ROOT / "graph" / f"{SLUG}.trig"
    STORE_DIR = OUTPUT_ROOT / "graph/store" / SLUG
    PARQUET = PKG / "data" / f"{MAIN_T}.iri-keyed.parquet"
    QDIR = OUTPUT_ROOT / "queries" / SLUG
    PROFILE_DIR = OUTPUT_ROOT / "profiles" / SLUG
    if OUTPUT_ROOT != C.ROOT:
        QDIR.mkdir(parents=True, exist_ok=True)
        for query in sorted((C.ROOT / "queries" / SLUG).glob("*.rq")):
            shutil.copyfile(query, QDIR / query.name)


def review_assertion(g: C.G, subject, predicate, obj, graph: str, *, evidence=(),
                     note: str, confidence="mediumConfidence", justification=None,
                     assert_triple=False) -> str:
    """Emit a source-backed candidate and stable RDF 1.1 statement provenance.

    Critical candidates remain awaiting review and are statement-only by default:
    ordinary union queries must not silently join an unreviewed identity bridge.
    The assertion identifier includes its graph so that the same triple in two
    releases is not one review record.
    """
    s, p = N(subject), N(predicate)
    o = obj if isinstance(obj, (ox.NamedNode, ox.Literal)) else N(obj)
    key = "\n".join((str(s), str(p), str(o), graph))
    statement = f"{C.BASE}assertion/{SLUG}/{hashlib.sha256(key.encode()).hexdigest()}"
    if assert_triple:
        g.add(s, p, o, graph)
    for pred, value in [("rdf:type", "rdf:Statement"), ("rdf:subject", s),
                        ("rdf:predicate", p), ("rdf:object", o),
                        ("prov:wasAttributedTo", AGENT),
                        ("prov:wasGeneratedBy", f"{C.BASE}activity/{SLUG}/build"),
                        (PROFILE + "confidence", PROFILE + confidence),
                        (PROFILE + "criticality", PROFILE + "critical"),
                        (PROFILE + "reviewStatus", PROFILE + "awaitingReview")]:
        g.add(statement, pred, value, graph)
    for source in sorted(set(evidence)):
        g.add(statement, "dcterms:source", source, graph)
    g.add(statement, "rdfs:comment", L(note, lang="en"), graph)
    if justification:
        g.add(statement, "sssom:mapping_justification", justification, graph)
    return statement


def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    # Pin reduction/scan order for repeatable CSV, Parquet and floating-point sums.
    c.execute("SET threads = 1")
    c.execute(f"""CREATE TABLE raw AS SELECT * FROM read_csv('{RAW / CSV_NAME}', nullstr=['NA',''],
                  sample_size=-1)""")
    c.execute("""CREATE VIEW src AS SELECT *,
                  NULLIF(trim(split_part(ENUMERATION_METHODS, ',', 1)), '') AS primary_enumeration_method
                  FROM raw""")
    return c


# ==========================================================================
# fetch
# ==========================================================================

def stage_fetch() -> None:
    rec = RAW / "zenodo_record.json"
    RAW.mkdir(parents=True, exist_ok=True)
    meta = {}
    src = C.fetch_source(RAW, {"zenodo_record.json": RECORD_URL, CSV_NAME: CSV_URL, META_NAME: META_URL}, meta)
    r = json.loads(rec.read_text())
    zfile = next(f for f in r["files"] if f["key"] == CSV_NAME)
    got = next(f for f in src["files"] if f["name"] == CSV_NAME)
    assert zfile["checksum"] == "md5:" + got["md5"], "Zenodo md5 mismatch"
    meta = {
        "slug": SLUG, "title": r["metadata"]["title"], "doi": DOI,
        "doi_url": f"https://doi.org/{DOI}", "record_url": r["links"]["self_html"],
        "record_api": RECORD_URL, "publication_date": r["metadata"]["publication_date"],
        "version": r["metadata"].get("version") or "unversioned on Zenodo (file dated 2026-02-20)",
        "zenodo_record_id": r["id"], "licence": "CC-BY-4.0", "licence_url": LICENCE,
        "creators": r["metadata"]["creators"], "publisher": "Pacific Salmon Foundation",
        "attribution": ATTRIBUTION, "upstream": {"name": "DFO NuSEDS", "url": NUSEDS_OPEN_DATA,
                                                 "extract_date": "2025-11-03", "licence": "Open Government Licence - Canada"},
        "column_metadata_url": META_URL, "zenodo_md5_verified": True,
    }
    C.fetch_source(RAW, {"zenodo_record.json": RECORD_URL, CSV_NAME: CSV_URL, META_NAME: META_URL}, meta)
    log(f"fetch ok: {got['bytes']} bytes, md5 verified")


# ==========================================================================
# profile
# ==========================================================================

def stage_profile() -> dict:
    c = con()
    cols = [r[0] for r in c.execute("DESCRIBE raw").fetchall()]
    types = {r[0]: r[1] for r in c.execute("DESCRIBE raw").fetchall()}
    n = c.execute("SELECT count(*) FROM raw").fetchone()[0]
    rows = []
    for col in cols:
        q = f'"{col}"'
        nn, nd = c.execute(f"SELECT count({q}), count(DISTINCT {q}) FROM raw").fetchone()
        top = c.execute(f"SELECT {q}::VARCHAR v, count(*) k FROM raw WHERE {q} IS NOT NULL GROUP BY 1 ORDER BY k DESC, v LIMIT 5").fetchall()
        mn = mx = None
        if types[col] in ("BIGINT", "DOUBLE", "INTEGER"):
            mn, mx = c.execute(f"SELECT min({q}), max({q}) FROM raw").fetchone()
        rows.append({"column": col, "duckdb_type": types[col], "non_null": nn,
                     "null_pct": round(100 * (n - nn) / n, 2), "distinct": nd, "min": mn, "max": mx,
                     "top_values": " | ".join(f"{v} ({k})" for v, k in top)})
    out = PROFILE_DIR
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "column-profile.csv", index=False)
    summary = {"rows": n, "columns": len(cols),
               "years": c.execute("SELECT min(Year), max(Year) FROM raw").fetchone(),
               "rows_with_max_estimate": c.execute("SELECT count(*) FROM raw WHERE MAX_ESTIMATE IS NOT NULL").fetchone()[0],
               "distinct": dict(zip(["POP_ID", "GFE_ID", "cuid", "streamid", "IndexId"],
                                    c.execute("SELECT count(DISTINCT POP_ID), count(DISTINCT GFE_ID), count(DISTINCT cuid), count(DISTINCT streamid), count(DISTINCT IndexId) FROM raw").fetchone())),
               "unique_key_IndexId_GFE_ID_Year": c.execute("SELECT count(*) = count(DISTINCT (IndexId, GFE_ID, Year)) FROM raw").fetchone()[0],
               "rows_without_cuid": c.execute("SELECT count(*) FROM raw WHERE cuid IS NULL").fetchone()[0]}
    (out / "profile-summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    log(f"profile ok: {n} rows x {len(cols)} cols")
    return summary


# ==========================================================================
# package
# ==========================================================================

def crosswalks(vocab=None) -> dict[str, pd.DataFrame]:
    """metasalmonpy NuSEDS crosswalks + documented corpus corrections/additions."""
    en = ms.nuseds_enumeration_method_crosswalk().copy()
    en["source"] = "metasalmonpy 0.6.0 nuseds_enumeration_method_crosswalk"
    # B-76 retains this target. It is usable only after the pinned ontology
    # declares it; a policy ruling alone does not make an undeclared IRI valid.
    vocab = vocab or C.VocabIndex()
    if not vocab.exists(NS["gcdfo"] + "EnumerationMethod"):
        bad = en["ontology_term"] == "gcdfo:EnumerationMethod"
        en.loc[bad, "ontology_term"] = pd.NA
        en.loc[bad, "notes"] = en.loc[bad, "notes"] + " [corpus gap: the pinned gcdfo does not yet declare gcdfo:EnumerationMethod; retain as a gap pending B-76]"
    en = pd.concat([en, pd.DataFrame([{
        "nuseds_value": "Net", "method_family": "unknown", "ontology_term": pd.NA,
        "notes": "[corpus addition] Value in data, absent from crosswalk; no concept found.",
        "source": "corpus agent"}])], ignore_index=True)
    em = ms.nuseds_estimate_method_crosswalk().copy()
    em["source"] = "metasalmonpy 0.6.0 nuseds_estimate_method_crosswalk"
    em = pd.concat([em, pd.DataFrame([
        {"nuseds_value": "Fence Count", "method_family": "FS", "guidance_interpretation": "Enumeration device/mode",
         "ontology_term": "gcdfo:FixedStationTally",
         "notes": "[corpus addition, needs review] Value in data, absent from crosswalk; treated like 'Fixed Site Census'.",
         "source": "corpus agent"},
        {"nuseds_value": "Aerial Survey", "method_family": "A", "guidance_interpretation": "Field method stored as estimate method",
         "ontology_term": pd.NA,
         "notes": "[corpus addition] Value in data (6 rows), absent from crosswalk; gcdfo:AerialSurveyCount is an enumeration (field) method, not an estimate method, so left unmapped.",
         "source": "corpus agent"}])], ignore_index=True)
    ec = ms.nuseds_estimate_classification_crosswalk().copy()
    ec["source"] = "metasalmonpy 0.6.0 nuseds_estimate_classification_crosswalk"
    ec = pd.concat([ec, pd.DataFrame([
        {"nuseds_value": "NO SURVEY", "estimate_type": pd.NA, "ontology_term": pd.NA,
         "notes": "[corpus addition] Value in data (50 rows), absent from crosswalk; treated like 'NO SURVEY THIS YEAR'.",
         "source": "corpus agent"},
        {"nuseds_value": "MISSING", "estimate_type": pd.NA, "ontology_term": pd.NA,
         "notes": "[corpus addition] Shared RDF/Parquet join-key category for blank source ESTIMATE_CLASSIFICATION; raw blanks and numeric values remain unchanged (2 source rows).",
         "source": "corpus agent"}])], ignore_index=True)
    return {"ESTIMATE_CLASSIFICATION": ec, "ESTIMATE_METHOD": em, "primary_enumeration_method": en}


CODE_SCHEMES = {  # column -> (code IRI path, gcdfo scheme)
    "ESTIMATE_CLASSIFICATION": ("nuseds/estimate-classification", "gcdfo:EstimateTypeScheme"),
    "ESTIMATE_METHOD": ("nuseds/estimate-method", "gcdfo:EstimateMethodScheme"),
    "primary_enumeration_method": ("nuseds/enumeration-method", "gcdfo:EnumerationMethodScheme"),
}


def code_iri(column: str, value) -> str:
    path = CODE_SCHEMES[column][0] if column in CODE_SCHEMES else f"{SLUG}/{C.slug_iri(column)}"
    # Raw blanks remain blank in the numeric table. Their join key uses the same
    # explicit missing category as the existing aggregate, in RDF and Parquet.
    if value is None or pd.isna(value) or not str(value).strip():
        value = "MISSING" if column == "ESTIMATE_CLASSIFICATION" else "blank"
    return f"{C.BASE}code/{path}/{C.slug_iri(str(value)) or 'blank'}"


def build_codes(c, dict_df: pd.DataFrame, table: str, source_view: str, vocab: C.VocabIndex) -> pd.DataFrame:
    xw = crosswalks(vocab)
    rows = []
    for col in dict_df.loc[dict_df.column_role == "categorical", "column_name"]:
        vals = [r[0] for r in c.execute(f'SELECT DISTINCT "{col}"::VARCHAR FROM {source_view} WHERE "{col}" IS NOT NULL ORDER BY 1').fetchall()]
        if col == "ESTIMATE_CLASSIFICATION" and c.execute(
            f'SELECT count(*) FROM {source_view} WHERE "{col}" IS NULL OR trim("{col}"::VARCHAR) = \'\''
        ).fetchone()[0]:
            vals = sorted(set(vals) | {"MISSING"})
        for v in vals:
            term, vocab_iri, desc = None, None, None
            if col == "SPECIES" and v in C.NCBI_TAXON:
                term, desc = C.NCBI_TAXON[v][1], C.NCBI_TAXON[v][0]
            elif col in xw:
                hit = xw[col].loc[xw[col].nuseds_value == v]
                vocab_iri = C.expand(CODE_SCHEMES[col][1])
                if len(hit):
                    term = C.expand(hit.ontology_term.iloc[0]) if pd.notna(hit.ontology_term.iloc[0]) else None
                    desc = (hit.notes.iloc[0] or None) if pd.notna(hit.notes.iloc[0]) else None
                else:
                    desc = "Not in metasalmonpy crosswalk."
            if term and (term.startswith(NS["gcdfo"]) or term.startswith(NS["smn"])) and not vocab.exists(term):
                raise SystemExit(f"code term does not exist in vocab: {term}")
            rows.append({"dataset_id": DATASET_ID, "table_id": table, "column_name": col, "code_value": v,
                         "code_label": v, "code_description": desc, "vocabulary_iri": vocab_iri,
                         "term_iri": term, "term_type": "skos_concept" if term else None})
    return pd.DataFrame(rows)


def build_dict(spec, table: str, psf_meta: dict) -> pd.DataFrame:
    rows = []
    for name, role, vtype, unit, label, desc in spec:
        d = psf_meta.get(name) if name not in DERIVED else None
        description = d if d else (desc or f"[agent] {label}.")
        rows.append({"dataset_id": DATASET_ID, "table_id": table, "column_name": name, "column_label": label,
                     "column_description": description, "column_role": role, "value_type": vtype,
                     "unit_label": {INDIV: "Individual", NUM: "Number", PCT: "Percent"}.get(unit),
                     "unit_iri": unit, "term_iri": None, "term_type": None,
                     "required": name in ("ACT_ID", "IndexId", "GFE_ID", "Year", "POP_ID") if table == MAIN_T else role in ("identifier", "temporal"),
                     "property_iri": None, "entity_iri": None, "constraint_iri": None, "statistical_modifier_iri": None})
    df = pd.DataFrame(rows)
    sa = df.column_name.isin(SPAWNER_COLS.keys()) if table == MAIN_T else pd.Series(False, index=df.index)
    df.loc[sa, ["term_iri", "term_type", "property_iri", "entity_iri", "constraint_iri"]] = [
        NS["gcdfo"] + "SpawnerAbundance", "owl_class", NS["smn"] + "Abundance",
        NS["smn"] + "SalmonIndividual", NS["smn"] + "SpawnerStageContext"]
    if table == MAIN_T:
        df.loc[df.column_name == "SPECIES", ["term_iri", "term_type"]] = ["http://rs.tdwg.org/dwc/terms/scientificName", "property"]
        max_field = df.column_name.eq("MAX_ESTIMATE")
        df.loc[max_field, "column_description"] = ("Source MAX_ESTIMATE, retained exactly as released by PSF. "
            "The PSF field documentation is evidence, not approval of a spawner-only interpretation or a literal row-maximum equation; "
            "the measure's biological scope awaits source review.")
    return df


def decompositions(dict_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    gcdfo_v = "gcdfo main @ GitHub (owl:versionInfo 0.0.9)"
    for _, r in dict_df.loc[dict_df.term_iri == NS["gcdfo"] + "SpawnerAbundance"].iterrows():
        comps = [("property", "matched", NS["smn"] + "Abundance", "Abundance", ""),
                 ("entity", "matched", NS["smn"] + "SalmonIndividual", "Salmon individual", ""),
                 ("constraint", "matched", NS["smn"] + "SpawnerStageContext", "Spawner stage context", "")]
        extra = SPAWNER_COLS.get(r.column_name, [])
        for g in extra:
            comps.append(("constraint", "gap", "", g, f"No smn/gcdfo concept found for '{g}'."))
        comps.append(("unit", "matched", INDIV, "Individual", ""))
        for i, (role, status, iri, label, why) in enumerate(comps, 1):
            if role == "unit":
                src, sv, su = "QUDT units", "live vocabulary checked 2026-10-22", "http://qudt.org/vocab/unit/"
            elif iri.startswith(NS["smn"]):
                src, sv, su = "salmon-domain-ontology (smn)", "local flattened build checked 2026-10-22", "https://w3id.org/smn"
            else:
                src, sv, su = "salmon-demo-corpus gap review", "2026-10-22", C.BASE
            rows.append({"dataset_id": DATASET_ID, "table_id": r.table_id, "column_name": r.column_name,
                         "measurement_concept_iri": r.term_iri, "component_order": i, "component_role": role,
                         "component_status": status, "component_relation": "", "related_component_order": "",
                         "component_iri": iri, "component_label": label, "rationale": why or "Selected by corpus agent from verified ontology terms.",
                         "source": src, "source_version": sv, "source_url": su,
                         "provenance": f"corpus pipeline {SLUG}; term existence checked against local ontology files"})
    return pd.DataFrame(rows)


def observation_structures(dict_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    S, K = [], []
    for table, dims, attrs in [
        (MAIN_T, ["IndexId", "GFE_ID", "Year"], ["ESTIMATE_CLASSIFICATION", "ESTIMATE_METHOD", "primary_enumeration_method", "ESTIMATE_STAGE"]),
        (CUBE_T, ["cuid", "Year", "ESTIMATE_CLASSIFICATION"], []),
    ]:
        for m in dict_df.loc[(dict_df.table_id == table) & (dict_df.column_role == "measurement"), "column_name"]:
            sid = f"{table}__{m}"
            S.append({"dataset_id": DATASET_ID, "table_id": table, "observation_structure_id": sid,
                      "structure_label": f"{m} by {' x '.join(dims)}",
                      "structure_description": f"One {m} value per {' x '.join(dims)}."})
            comps = [(m, "measure", True)] + [(d, "dimension", True) for d in dims] + [(a, "attribute", False) for a in attrs]
            for i, (col, role, req) in enumerate(comps, 1):
                K.append({"dataset_id": DATASET_ID, "table_id": table, "observation_structure_id": sid,
                          "component_order": i, "column_name": col, "component_role": role,
                          # sosa:usedProcedure deliberately not used: every observed code would need a
                          # term_iri, but 'Unknown Estimate Method', 'Not Applicable', 'Other', ... have none.
                          "component_relation_iri": "", "required_when_observed": req})
    return pd.DataFrame(S), pd.DataFrame(K)


def write_sssom(codes: pd.DataFrame, outdir: Path, gcdfo_sha: str, vocab=None) -> list[Path]:
    xw = crosswalks(vocab)
    paths = []
    for col, (path, scheme) in CODE_SCHEMES.items():
        x = xw[col]
        observed = set(codes.loc[codes.column_name == col, "code_value"])
        x = x.loc[x.nuseds_value.isin(observed)].copy()
        pfx = "nuseds" + "".join(w[0].upper() for w in path.split("/")[1].split("-"))
        x["object_id"] = x.ontology_term.fillna("sssom:NoTermFound")
        per_obj = x.groupby("object_id").nuseds_value.transform("count")
        lines = [
            "# curie_map:",
            "#   gcdfo: https://w3id.org/gcdfo/salmon#",
            f"#   {pfx}: {C.BASE}code/{path}/",
            "#   smn: https://w3id.org/smn/",
            f"# license: {LICENCE}",
            f"# mapping_set_id: {C.BASE}mapping/{SLUG}/{path.split('/')[1]}",
            "# mapping_set_version: '2026-10-22'",
            f"# mapping_set_description: NuSEDS {col} values in {SLUG} mapped to gcdfo concepts; from metasalmonpy 0.6.0 crosswalks plus corpus corrections.",
            "# sssom_version: '1.1'",
            f"# subject_source: {C.BASE}code/{path}/",
            f"# subject_source_version: '{SLUG} 2026-02-20'",
            "# object_source: https://w3id.org/gcdfo/salmon",
            f"# object_source_version: 'main sha256:{gcdfo_sha[:16]}'",
            "subject_id\tsubject_label\tpredicate_id\tobject_id\tobject_label\tmapping_justification\tmapping_cardinality\tmapping_tool\tauthor_id\tcomment",
        ]
        for (_, r), n_obj in zip(x.iterrows(), per_obj):
            obj = r.object_id
            local = obj.split(":", 1)[1] if obj.startswith(("gcdfo:", "smn:")) else ""
            if obj == "sssom:NoTermFound":
                pred, card = "skos:exactMatch", "1:0"
            elif local in ("EstimateType", "EstimateMethod", "EnumerationMethod") or \
                    C.slug_iri(r.nuseds_value) != C.slug_iri(local.replace("Type", "true abundance type ")):
                pred, card = "skos:broadMatch", ("n:1" if n_obj > 1 else "1:1")
            else:
                pred, card = "skos:exactMatch", ("n:1" if n_obj > 1 else "1:1")
            if col == "ESTIMATE_CLASSIFICATION" and local.startswith("Type") and local[4:].isdigit():
                pred = "skos:exactMatch"
            if C.slug_iri(r.nuseds_value) == C.slug_iri(local):
                pred = "skos:exactMatch"
            note = str(r.notes if pd.notna(r.notes) else "").replace("\t", " ").replace("\n", " ")
            note = (note + f" Source: {r.source}.").strip()
            by_agent = r.source == "corpus agent"
            lines.append("\t".join([f"{pfx}:{C.slug_iri(r.nuseds_value)}", r.nuseds_value, pred, obj, "",
                                    "semapv:AgentBasedMatching" if by_agent else "semapv:ManualMappingCuration",
                                    card, "agent-authored corpus pipeline" if by_agent else "metasalmonpy 0.6.0 NuSEDS crosswalk",
                                    AGENT if by_agent else "", note]))
        p = outdir / f"{SLUG}-{path.split('/')[1]}.sssom.tsv"
        p.write_text("\n".join(lines) + "\n")
        paths.append(p)
    return paths


def stage_package() -> dict:
    build_reference_time()
    vocab = C.VocabIndex()
    # Validate the truthful agent justification before overwriting any package
    # artifact. Older metasalmonpy pins omit this canonical SEMAPV term from
    # their enum; that requires a dependency fix, not fabricated human curation.
    with tempfile.TemporaryDirectory() as td:
        probe_codes = pd.DataFrame({"column_name": ["ESTIMATE_CLASSIFICATION"], "code_value": ["NO SURVEY"]})
        probe = write_sssom(probe_codes, Path(td), vocab.sources["gcdfo"]["sha256"], vocab)[0]
        try:
            ms.read_sssom_mapping_set(str(probe))
        except ValueError as error:
            if "mapping_justification" not in str(error):
                raise
            raise RuntimeError("The pinned metasalmonpy must support canonical semapv:AgentBasedMatching before this package can be built; no human-curation fallback is permitted.") from error
    c = con()
    psf_meta = dict(pd.read_csv(RAW / META_NAME)[["field", "description"]].itertuples(index=False))
    log("reading source into pandas")
    main = c.execute("SELECT * FROM src").df()
    c.execute("""CREATE TABLE cube AS SELECT cuid, FULL_CU_IN_PSE, cu_name_pse, SPECIES, SPECIES_QUALIFIED,
                 regionid, region, Year, coalesce(ESTIMATE_CLASSIFICATION, 'MISSING') AS ESTIMATE_CLASSIFICATION,
                 sum(MAX_ESTIMATE) AS spawner_abundance, count(DISTINCT streamid) AS n_sites
                 FROM src WHERE cuid IS NOT NULL AND MAX_ESTIMATE IS NOT NULL
                 GROUP BY ALL ORDER BY cuid, Year, ESTIMATE_CLASSIFICATION""")
    assert c.execute("SELECT count(*) = count(DISTINCT (cuid, Year, ESTIMATE_CLASSIFICATION)) FROM cube").fetchone()[0]
    cube = c.execute("SELECT * FROM cube").df()
    dict_df = pd.concat([build_dict(COLS, MAIN_T, psf_meta), build_dict(CUBE_COLS, CUBE_T, psf_meta)], ignore_index=True)
    codes = pd.concat([build_codes(c, dict_df[dict_df.table_id == MAIN_T], MAIN_T, "src", vocab),
                       build_codes(c, dict_df[dict_df.table_id == CUBE_T], CUBE_T, "cube", vocab)], ignore_index=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        art = ms.infer_salmon_datapackage_artifacts({MAIN_T: main.head(2000), CUBE_T: cube.head(2000)},
                                                    dataset_id=DATASET_ID, seed_semantics=False)
    ds = art["dataset_meta"].copy()
    ymin, ymax = int(main.Year.min()), int(main.Year.max())
    ds.loc[0, ["title", "description", "creator", "contact_name", "contact_email", "license", "contact_org",
               "temporal_start", "temporal_end", "spatial_extent", "dataset_type", "source_citation",
               "update_frequency", "topic_categories", "keywords", "security_classification", "provenance_note", "created"]] = [
        "Cleaned NuSEDS spawner survey data linked to Conservation Units (PSF, 2026-02-20)",
        ("DFO NuSEDS escapement (spawner survey) records cleaned by the Pacific Salmon Foundation and matched to "
         "Conservation Units (cuid) and PSE stream IDs (streamid). One row per population x stream x year. "
         "Repackaged as a Salmon Data Package by the salmon-demo-corpus pipeline; values are unchanged from the source "
         "CSV apart from the derived column primary_enumeration_method. Table cu_year_spawners is a corpus-derived "
         "aggregate (sum of MAX_ESTIMATE by CU, year and estimate classification)."),
        "Bruno Carturan (ORCID 0000-0001-6811-1063); Stephanie Peacock (ORCID 0000-0001-5016-2153); Pacific Salmon Foundation",
        "Pacific Salmon Foundation (Salmon Watersheds Program)", "MISSING METADATA: no contact email in Zenodo record",
        "CC-BY-4.0", "Pacific Salmon Foundation",
        f"{ymin}-01-01", f"{ymax}-12-31",
        f"lon={main.X_LONGT.min():.4f}..{main.X_LONGT.max():.4f}, lat={main.Y_LAT.min():.4f}..{main.Y_LAT.max():.4f} (British Columbia and Yukon)",
        "escapement_estimates", ATTRIBUTION, "irregular", "biota;inlandWaters",
        "salmon; NuSEDS; escapement; spawner survey; Conservation Unit; Pacific Salmon Explorer",
        "unclassified",
        (f"Source {SRC_DS} retrieved via Zenodo API; md5 verified; column definitions from {META_URL}. "
         "PSF cleaning: https://salmonwatersheds.github.io/population-indicators/spawner-surveys/code/1_nuseds_collation.html ; "
         "CU matching: https://github.com/salmonwatersheds/salmon_data_demise/blob/main/code/b_nuseds_cuid_pse.Rmd"),
        build_reference_time()[:10]]
    tm = art["table_meta"].set_index("table_id")
    tm.loc[MAIN_T, ["table_label", "description", "observation_unit", "observation_unit_iri", "primary_key"]] = [
        "NuSEDS spawner survey records with CU and stream IDs",
        "One row per NuSEDS population (IndexId) x stream (GFE_ID) x analysis year; all 90 source columns plus primary_enumeration_method.",
        "Escapement estimate", NS["smn"] + "EscapementEstimate", "ACT_ID"]
    tm.loc[CUBE_T, ["table_label", "description", "observation_unit", "observation_unit_iri", "primary_key"]] = [
        "Sum of source MAX_ESTIMATE by CU, year and estimate classification",
        "Sum of MAX_ESTIMATE over stream sites, by PSE CU x year x NuSEDS estimate classification. Source of the RDF Data Cube.",
        "Source MAX_ESTIMATE aggregate; biological scope awaits review", "", "cuid,Year,ESTIMATE_CLASSIFICATION"]
    tm = tm.reset_index()
    if PKG.exists() and not (PKG / "metadata").exists():
        pass
    log("writing SDP (CSV, ~300 MB)")
    ms.write_salmon_datapackage(resources={MAIN_T: main, CUBE_T: cube}, dataset_meta=ds, table_meta=tm,
                                dict_df=dict_df, codes=codes, path=str(PKG), overwrite=True)
    dec = decompositions(dict_df)
    ms.write_sdp_measurement_decompositions(PKG, dec, overwrite=True)
    S, K = observation_structures(dict_df)
    ms.write_sdp_observation_structures(PKG, S, K, overwrite=True)
    with tempfile.TemporaryDirectory() as td:
        ms.write_sdp_sssom(PKG, write_sssom(codes, Path(td), vocab.sources["gcdfo"]["sha256"], vocab), overwrite=True)
    # term gaps (structured): measurement/categorical columns with no term, plus decomposition gaps
    gaps = []
    for _, r in dict_df.iterrows():
        if r.column_role == "measurement" and not r.term_iri:
            gaps.append({"table_id": r.table_id, "column_name": r.column_name, "gap_kind": "measurement variable",
                         "label": r.column_label, "rationale": "No smn/gcdfo variable concept found."})
    for _, r in dec.loc[dec.component_status == "gap"].iterrows():
        gaps.append({"table_id": r.table_id, "column_name": r.column_name, "gap_kind": f"I-ADOPT {r.component_role}",
                     "label": r.component_label, "rationale": r.rationale})
    for _, r in codes.loc[codes.vocabulary_iri.notna() & codes.term_iri.isna()].iterrows():
        gaps.append({"table_id": r.table_id, "column_name": r.column_name, "gap_kind": "code value",
                     "label": r.code_value, "rationale": r.code_description or "No concept in crosswalk."})
    gdf = pd.DataFrame(gaps).drop_duplicates()
    (PKG / "review").mkdir(exist_ok=True)
    gdf.to_csv(PKG / "review" / "term-gaps.csv", index=False)
    try:
        mgap = ms.detect_semantic_term_gaps(dict_df=dict_df)
        mgap.to_csv(PKG / "review" / "metasalmonpy-detect-semantic-term-gaps.csv", index=False)
        n_mgap = len(mgap)
    except Exception as e:  # record, don't hide
        n_mgap = f"error: {type(e).__name__}: {e}"
    val = ms.validate_salmon_datapackage(str(PKG))
    try:
        val_iris = ms.validate_salmon_datapackage(str(PKG), require_iris=True)
    except Exception as e:
        val_iris = {"error": f"{type(e).__name__}: {e}"}
    def summarise(v):
        if not isinstance(v, dict) or "package" not in v:
            return v
        sv = v.get("semantic_validation", {})
        return {"structural_issues": v["issues"].to_dict("records"),
                "semantic_issues": sv.get("issues").to_dict("records") if hasattr(sv.get("issues"), "to_dict") else [],
                "missing_terms": sv["missing_terms"]["term_label"].tolist() if hasattr(sv.get("missing_terms"), "to_dict") else [],
                "missing_semantics_by_field": sv["missing_semantics"].groupby("field").size().to_dict() if hasattr(sv.get("missing_semantics"), "groupby") else {}}
    val, val_iris = summarise(val), summarise(val_iris)
    res = {"main_rows": len(main), "cube_rows": len(cube), "dict_rows": len(dict_df), "codes_rows": len(codes),
           "codes_with_term": int(codes.term_iri.notna().sum()), "decomposition_rows": len(dec),
           "observation_structures": len(S), "term_gaps": len(gdf), "metasalmonpy_term_gaps": n_mgap,
           "validation": val, "validation_require_iris": val_iris}
    (PKG / "review" / "build-summary.json").write_text(json.dumps(res, indent=2, default=str) + "\n")
    log(f"package ok: {json.dumps({k: v for k, v in res.items() if not k.startswith('validation')}, default=str)}")
    return res


# ==========================================================================
# graph
# ==========================================================================

def add_def(g: C.G, iri: str, kind: str, label: str, comment: str, gr: str, **extra) -> None:
    g.add(iri, "rdf:type", kind, gr)
    g.add(iri, "rdfs:label", L(label, lang="en"), gr)
    g.add(iri, "rdfs:comment", L(comment, lang="en"), gr)
    g.add(iri, "rdfs:isDefinedBy", C.BASE + "def/", gr)
    for p, o in extra.items():
        g.add(iri, p.replace("__", ":"), o, gr)


def add_identities(g: C.G, c) -> dict[str, int]:
    """Retain observed source pairings; stable labels do not choose membership.

    Source identifier attributes can vary. All distinct attribute tuples are
    retained, with the first non-null label in lexical order used for display.
    Crosswalks are candidates in a separate graph, never asserted as approved
    equivalences from an arbitrary representative row. POP_ID is deliberately
    not reminted here: Pink odd/even IndexId contexts remain in the evidence.
    """
    ID, XW, D = GRAPHS["identity"], GRAPHS["crosswalk"], NS["def"]
    cus = c.execute("""SELECT DISTINCT cuid, cu_name_pse, cu_name_dfo, FULL_CU_IN_PSE,
                       SPECIES, SPECIES_QUALIFIED, regionid, region, CU_TYPE, CU_LAT, CU_LONGT
                       FROM src WHERE cuid IS NOT NULL ORDER BY ALL""").fetchall()
    labelled = {}
    for cuid, name, dname, pidx, sp, sq, rid, rname, ctype, lat, lon in cus:
        cu = ident("cu", "psf", cuid)
        g.add(cu, "rdf:type", "gcdfo:ConservationUnit", ID)
        if name:
            if cu not in labelled or name != labelled[cu]:
                g.add(cu, "skos:altLabel" if cu in labelled else "skos:prefLabel", L(name, lang="en"), ID)
            labelled.setdefault(cu, name)
        if dname and dname != name:
            g.add(cu, "skos:altLabel", L(dname, lang="en"), ID)
        g.add(cu, "dcterms:identifier", L(f"psf-cuid:{cuid}"), ID)
        g.add(cu, "skos:notation", L(str(cuid), D + "psfCuid"), ID)
        if pidx:
            g.add(cu, D + "pseCuIndex", L(pidx), ID)
        if sp in C.NCBI_TAXON:
            g.add(cu, D + "taxon", C.NCBI_TAXON[sp][1], ID)
        if sq:
            g.add(cu, D + "speciesQualifier", L(sq), ID)
        if rid is not None:
            reg = ident("region", "psf", rid)
            g.add(cu, D + "region", reg, ID)
            g.add(reg, "rdf:type", "skos:Concept", ID)
            if rname:
                g.add(reg, "skos:prefLabel", L(rname, lang="en"), ID)
            g.add(reg, "skos:notation", L(str(rid)), ID)
        if ctype:
            g.add(cu, D + "cuType", L(ctype), ID)
        if lat is not None and lon is not None:
            g.add(cu, "wgs:lat", L(float(lat)), ID)
            g.add(cu, "wgs:long", L(float(lon)), ID)
    pairings = c.execute("""SELECT cuid, FULL_CU_IN,
                         list(DISTINCT FULL_CU_IN_PSE ORDER BY FULL_CU_IN_PSE),
                         list(DISTINCT IndexId ORDER BY IndexId), min(Year), max(Year)
                         FROM src WHERE cuid IS NOT NULL AND FULL_CU_IN IS NOT NULL
                         GROUP BY cuid, FULL_CU_IN ORDER BY cuid, FULL_CU_IN""").fetchall()
    for cuid, didx, pidxs, index_ids, first_year, last_year in pairings:
        cu, dcu = ident("cu", "psf", cuid), ident("cu", "dfo", didx)
        g.add(dcu, "rdf:type", "gcdfo:ConservationUnit", ID)
        g.add(dcu, "dcterms:identifier", L(f"dfo-full-cu-in:{didx}"), ID)
        g.add(dcu, "skos:notation", L(didx, D + "dfoFullCuIn"), ID)
        g.add(cu, D + "dfoCuIndex", L(didx), ID)
        context = {"cuid": cuid, "FULL_CU_IN": didx, "FULL_CU_IN_PSE": pidxs,
                   "IndexId": index_ids, "observed_year_bounds": [first_year, last_year]}
        review_assertion(g, cu, "skos:closeMatch", dcu, XW, evidence=[SRC_DS, META_URL],
            confidence="lowConfidence", justification=SEMAPV_AGENT,
            note="Candidate PSF-to-DFO CU correspondence from source row pairings; equal code strings do not establish exact equivalence or human approval. "
                 + json.dumps(context, sort_keys=True))
    for sp, (sci, tax) in C.NCBI_TAXON.items():
        if sp not in ("Steelhead", "Cutthroat"):
            g.add(tax, "rdfs:label", L(sci), ID)
            g.add(tax, "skos:altLabel", L(f"{sp} salmon", lang="en"), ID)
    streams = c.execute("""SELECT DISTINCT GFE_ID, sys_nm, GAZETTED_NAME, WATERBODY,
                           GFE_TYPE, Y_LAT, X_LONGT, WATERSHED_CDE, FWA_WATERSHED_CDE, StatArea
                           FROM src WHERE GFE_ID IS NOT NULL ORDER BY ALL""").fetchall()
    labelled = {}
    for gfe, nm, gaz, wb, gtype, lat, lon, wsc, fwa, sa in streams:
        stream = ident("stream", "dfo-nuseds-gfe", gfe)
        g.add(stream, "rdf:type", D + "StreamFeature", ID)
        if gtype == "Stream":
            g.add(stream, "rdf:type", "obo:ENVO_00000023", ID)
        if nm:
            if stream not in labelled or nm != labelled[stream]:
                g.add(stream, "skos:altLabel" if stream in labelled else "skos:prefLabel", L(nm), ID)
            labelled.setdefault(stream, nm)
        for alternate in (gaz, wb):
            if alternate and alternate != nm:
                g.add(stream, "skos:altLabel", L(alternate), ID)
        g.add(stream, "dcterms:identifier", L(f"dfo-nuseds-gfe-id:{gfe}"), ID)
        if gtype:
            g.add(stream, D + "featureType", L(gtype), ID)
        if lat is not None and lon is not None:
            g.add(stream, "wgs:lat", L(float(lat)), ID)
            g.add(stream, "wgs:long", L(float(lon)), ID)
            g.add(stream, "geo:hasGeometry", L(f"POINT({lon} {lat})", "geo:wktLiteral"), ID)
        for prefix, value in (("dfo-watershed-code", wsc), ("bc-fwa-watershed-code", fwa)):
            if value:
                g.add(stream, "dcterms:identifier", L(f"{prefix}:{value}"), ID)
        if sa:
            g.add(stream, D + "statArea", L(str(sa)), ID)
    sites = c.execute("""SELECT streamid, min(sys_nm), bool_or(IS_INDICATOR = 'Y')
                         FROM src WHERE streamid IS NOT NULL GROUP BY streamid ORDER BY streamid""").fetchall()
    for sid, name, indicator in sites:
        site = ident("site", "psf-streamid", sid)
        g.add(site, "rdf:type", D + "SurveySite", ID)
        if name:
            g.add(site, "skos:prefLabel", L(name), ID)
        g.add(site, "dcterms:identifier", L(f"psf-streamid:{sid}"), ID)
        if indicator is not None:
            g.add(site, D + "isIndicator", L(bool(indicator)), ID)
    for sid, gfe in c.execute("""SELECT DISTINCT streamid, GFE_ID FROM src
                                WHERE streamid IS NOT NULL AND GFE_ID IS NOT NULL ORDER BY ALL""").fetchall():
        g.add(ident("site", "psf-streamid", sid), D + "atStream", ident("stream", "dfo-nuseds-gfe", gfe), ID)
    pops = c.execute("""SELECT POP_ID, min(POPULATION), min(SPECIES) FROM src
                        WHERE POP_ID IS NOT NULL GROUP BY POP_ID ORDER BY POP_ID""").fetchall()
    for pid, name, species in pops:
        pop = ident("population", "dfo-nuseds", pid)
        g.add(pop, "rdf:type", "smn:Population", ID)
        if name:
            g.add(pop, "skos:prefLabel", L(name), ID)
        g.add(pop, "dcterms:identifier", L(f"dfo-nuseds-pop-id:{pid}"), ID)
        if species in C.NCBI_TAXON:
            g.add(pop, D + "taxon", C.NCBI_TAXON[species][1], ID)
    for pid, gfe in c.execute("""SELECT DISTINCT POP_ID, GFE_ID FROM src
                                WHERE POP_ID IS NOT NULL AND GFE_ID IS NOT NULL ORDER BY ALL""").fetchall():
        g.add(ident("population", "dfo-nuseds", pid), D + "atStream", ident("stream", "dfo-nuseds-gfe", gfe), ID)
    memberships = c.execute("""SELECT POP_ID, cuid, list(DISTINCT IndexId ORDER BY IndexId),
                              list(DISTINCT SPECIES_QUALIFIED ORDER BY SPECIES_QUALIFIED), min(Year), max(Year)
                              FROM src WHERE POP_ID IS NOT NULL AND cuid IS NOT NULL
                              GROUP BY POP_ID, cuid ORDER BY POP_ID, cuid""").fetchall()
    for pid, cuid, index_ids, qualifiers, first_year, last_year in memberships:
        context = {"POP_ID": pid, "cuid": cuid, "IndexId": index_ids,
                   "SPECIES_QUALIFIED": qualifiers, "observed_year_bounds": [first_year, last_year]}
        review_assertion(g, ident("population", "dfo-nuseds", pid), "smn:populationOf", ident("cu", "psf", cuid), ID,
            evidence=[SRC_DS, META_URL], note="Source population-to-CU pairing; not functional membership. "
            "Pink POP_IDs can include odd/even IndexId contexts; these have not been merged or independently approved. "
            + json.dumps(context, sort_keys=True))
    return {"cu": len({row[0] for row in cus}), "streams": len({row[0] for row in streams}),
            "sites": len(sites), "populations": len(pops)}


def write_iri_parquet(c, path: Path) -> None:
    """Use the graph's code_iri implementation for every classification join key."""
    values = c.execute("SELECT DISTINCT ESTIMATE_CLASSIFICATION FROM src ORDER BY 1").fetchall()
    mapping = pd.DataFrame([(v, code_iri("ESTIMATE_CLASSIFICATION", v)) for (v,) in values],
                           columns=["code_value", "code_iri"])
    c.register("classification_iris", mapping)
    path.parent.mkdir(parents=True, exist_ok=True)
    B = NS["id"]
    c.execute(f"""COPY (SELECT
        CASE WHEN cuid IS NOT NULL THEN '{B}cu/psf/' || cuid END AS cu_iri,
        '{B}stream/dfo-nuseds-gfe/' || GFE_ID AS stream_iri,
        '{B}population/dfo-nuseds/' || POP_ID AS population_iri,
        CASE WHEN streamid IS NOT NULL THEN '{B}site/psf-streamid/' || streamid END AS site_iri,
        CASE SPECIES {' '.join(f"WHEN '{k}' THEN '{v[1]}'" for k, v in C.NCBI_TAXON.items())} END AS species_iri,
        classification_iris.code_iri AS estimate_classification_iri,
        src.* FROM src LEFT JOIN classification_iris
          ON src.ESTIMATE_CLASSIFICATION IS NOT DISTINCT FROM classification_iris.code_value
        ORDER BY src.ACT_ID) TO '{path}' (FORMAT parquet, COMPRESSION zstd)""")


def validate_parquet_iris(store, c, path: Path) -> dict[str, int]:
    """Fail if a non-null row-level join key has no dataset-graph subject."""
    counts = {}
    for column in ("cu_iri", "stream_iri", "population_iri", "site_iri", "species_iri", "estimate_classification_iri"):
        keys = [row[0] for row in c.execute(
            f'SELECT DISTINCT "{column}" FROM read_parquet(\'{path}\') WHERE "{column}" IS NOT NULL ORDER BY 1'
        ).fetchall()]
        absent = [iri for iri in keys if next(store.quads_for_pattern(N(iri), None, None, None), None) is None]
        if absent:
            raise ValueError(f"Orphan Parquet {column} join keys: {absent[:10]} ({len(absent)} total)")
        counts[column] = len(keys)
    return counts


def stage_graph() -> dict:
    build_reference_time()
    vocab = C.VocabIndex()
    g = C.G(vocab)
    src = json.loads((RAW / "source.json").read_text())
    pkg = ms.read_salmon_datapackage(str(PKG))
    dict_df = pkg["dictionary"] if "dictionary" in pkg else pkg.get("dict")
    codes = pkg["codes"]
    c = con()
    M, MP, ID, CB, PV = (GRAPHS[k] for k in ("metadata", "mappings", "identity", "cube", "provenance"))
    D = NS["def"]

    # ---- corpus vocabulary (provisional) -------------------------------------------------
    for p, kind, label, comment in [
        ("taxon", "owl:ObjectProperty", "taxon", "Links an identity node (CU, population) to its NCBITaxon species."),
        ("region", "owl:ObjectProperty", "region", "PSE region of a CU."),
        ("dfoCuIndex", "owl:DatatypeProperty", "DFO CU index", "DFO FULL_CU_IN of a CU."),
        ("pseCuIndex", "owl:DatatypeProperty", "PSE CU index", "PSF FULL_CU_IN_PSE of a CU."),
        ("speciesQualifier", "owl:DatatypeProperty", "species qualifier", "CU species qualifier (CK, CM, CO, PKE, PKO, SEL, SER)."),
        ("cuType", "owl:DatatypeProperty", "CU type", "DFO CU_TYPE (Current, Bin, Extirpated, VREQ[...])."),
        ("featureType", "owl:DatatypeProperty", "feature type", "NuSEDS GFE_TYPE of a stream/waterbody feature."),
        ("statArea", "owl:DatatypeProperty", "statistical area", "Pacific Fishery Management Area."),
        ("atStream", "owl:ObjectProperty", "at stream", "Links a population or site to its NuSEDS stream feature (GFE_ID)."),
        ("isIndicator", "owl:DatatypeProperty", "indicator", "DFO indicator-population flag."),
        ("variable", "owl:ObjectProperty", "variable", "Links a table column to the I-ADOPT variable it holds."),
        ("columnRole", "owl:DatatypeProperty", "column role", "SDP column_role."),
        ("semanticStatus", "owl:DatatypeProperty", "semantic status", "'matched', 'partial' (variable with gaps) or 'gap' (no ontology term)."),
        ("hasGap", "owl:ObjectProperty", "has gap", "Links a variable or column to a recorded ontology term gap."),
        ("codeList", "owl:ObjectProperty", "code list", "Links a categorical column to its SKOS code list."),
        ("rowCount", "owl:DatatypeProperty", "row count", "Number of data rows in a table."),
        ("conservationUnit", "qb:DimensionProperty", "conservation unit", "Cube dimension: PSE Conservation Unit."),
        ("species", "qb:DimensionProperty", "species", "Cube dimension: species (NCBITaxon IRI)."),
        ("estimateClassification", "qb:DimensionProperty", "estimate classification", "Cube dimension: NuSEDS ESTIMATE_CLASSIFICATION code (mapped to gcdfo estimate types in the mappings graph)."),
        ("spawnerAbundance", "qb:MeasureProperty", "sum of source MAX_ESTIMATE", "Sum of unchanged source MAX_ESTIMATE values. Legacy predicate name retained; no spawner-only interpretation is asserted."),
        ("siteCount", "qb:MeasureProperty", "number of stream sites", "Number of stream sites contributing an estimate."),
        ("unitMeasure", "qb:AttributeProperty", "unit of measure", "QUDT unit of the measure."),
    ]:
        add_def(g, D + p, kind, label, comment, M)
    g.add(D + "conservationUnit", "rdfs:range", "gcdfo:ConservationUnit", M)
    g.add(D + "estimateClassification", "qb:codeList", C.BASE + "code/nuseds/estimate-classification", M)
    for cls, label, comment in [("SemanticGap", "Semantic gap", "A needed ontology term that was not found; candidate term request."),
                                ("StreamFeature", "NuSEDS stream feature", "A NuSEDS geographic feature (GFE_ID): stream, lake, channel, ..."),
                                ("SurveySite", "PSE stream site", "A source PSE streamid; all observed stream associations are retained.")]:
        add_def(g, D + cls, "owl:Class", label, comment, M)
    for name in ("confidence", "criticality", "reviewStatus"):
        g.add(PROFILE + name, "rdf:type", "owl:ObjectProperty", M)
    for name in ("highConfidence", "mediumConfidence", "lowConfidence", "critical", "awaitingReview"):
        g.add(PROFILE + name, "rdf:type", "skos:Concept", M)
    g.add(AGENT, "rdf:type", "prov:SoftwareAgent", M)
    g.add(AGENT, "rdfs:label", L("Agent-authored legacy PSF NuSEDS corpus pipeline"), M)

    # ---- DCAT + provenance ---------------------------------------------------------------
    csvf = next(f for f in src["files"] if f["name"] == CSV_NAME)
    C.dcat_dataset(g, ds=SRC_DS, graph=M, title=src["title"],
                   description="Cleaned version of DFO NuSEDS (2025-11-03 extract) matched to Conservation Units by the Pacific Salmon Foundation.",
                   doi=DOI, landing=src["record_url"], licence_iri=LICENCE, creators=src["creators"],
                   publisher="Pacific Salmon Foundation", issued=src["publication_date"], keywords=["salmon", "NuSEDS", "escapement"],
                   distributions=[{"iri": f"{C.BASE}distribution/{SLUG}/source-csv", "title": CSV_NAME,
                                   "download_url": CSV_URL, "media_type": "text/csv", "bytes": csvf["bytes"], "sha256": csvf["sha256"]}],
                   attribution=ATTRIBUTION, derived_from=[NUSEDS_OPEN_DATA])
    C.dcat_dataset(g, ds=DS, graph=M, title="Cleaned NuSEDS spawner survey data as a Salmon Data Package (salmon-demo-corpus)",
                   description="Salmon Data Package and RDF of the PSF cleaned NuSEDS data, built by the salmon-demo-corpus pipeline.",
                   doi=None, landing=f"{C.BASE}dataset/{SLUG}", licence_iri=LICENCE, creators=[],
                   publisher="Pacific Salmon Commission (salmon-demo-corpus)", issued=None,
                   keywords=["salmon", "NuSEDS", "Salmon Data Package", "knowledge graph"],
                   distributions=[
                       {"iri": f"{C.BASE}distribution/{SLUG}/sdp", "title": "Salmon Data Package (datapackage.json)",
                        "access_url": f"{C.BASE}package/{SLUG}/datapackage.json", "media_type": "application/json"},
                       {"iri": f"{C.BASE}distribution/{SLUG}/parquet", "title": "Row-level data keyed by corpus IRIs (Parquet)",
                        "access_url": f"{C.BASE}package/{SLUG}/data/{PARQUET.name}", "media_type": "application/vnd.apache.parquet"},
                       {"iri": f"{C.BASE}distribution/{SLUG}/rdf", "title": "RDF (TriG)",
                        "access_url": f"{C.BASE}graph/{SLUG}.trig", "media_type": "application/trig"}],
                   attribution=ATTRIBUTION, derived_from=[SRC_DS])
    act = f"{C.BASE}activity/{SLUG}/build"
    g.add(act, "rdf:type", "prov:Activity", PV)
    g.add(act, "rdfs:label", L(f"salmon-demo-corpus pipeline build of {SLUG}"), PV)
    g.add(act, "prov:used", SRC_DS, PV)
    g.add(act, "prov:used", f"{C.BASE}distribution/{SLUG}/source-csv", PV)
    g.add(act, "dcterms:date", L(build_reference_time(), "xsd:dateTime"), PV)
    g.add(act, "rdfs:comment", L("Pinned build reference timestamp, not actual execution start or end; real run events are retained outside reproducible artifacts."), PV)
    g.add(act, "prov:wasAssociatedWith", f"{C.BASE}agent/software/metasalmonpy-{ms.__version__}", PV)
    g.add(f"{C.BASE}agent/software/metasalmonpy-{ms.__version__}", "rdf:type", "prov:SoftwareAgent", PV)
    g.add(f"{C.BASE}agent/software/metasalmonpy-{ms.__version__}", "rdfs:label", L(f"metasalmonpy {ms.__version__}"), PV)
    g.add(DS, "prov:wasGeneratedBy", act, PV)
    g.add(DS, "prov:wasDerivedFrom", SRC_DS, PV)
    for key, info in vocab.sources.items():
        g.add(act, "prov:used", {"gcdfo": "https://w3id.org/gcdfo/salmon", "smn": "https://w3id.org/smn"}[key], PV)
    g.add(act, "rdfs:comment", L(f"Ontology files used: {json.dumps(vocab.sources)}"), PV)
    metadata_file = next(f for f in src["files"] if f["name"] == META_NAME)
    metadata_dist = f"{C.BASE}distribution/{SLUG}/source-metadata"
    g.add(metadata_dist, "rdf:type", "dcat:Distribution", PV)
    g.add(metadata_dist, "dcat:downloadURL", META_URL, PV)
    g.add(metadata_dist, "dcterms:identifier", L("sha256:" + metadata_file["sha256"]), PV)
    g.add(act, "prov:used", metadata_dist, PV)

    # ---- tables, columns, variables ---------------------------------------------------------
    tables = pkg["tables"] if "tables" in pkg else pkg.get("table_meta")
    rowcounts = {MAIN_T: c.execute("SELECT count(*) FROM src").fetchone()[0]}
    for _, t in tables.iterrows():
        tiri = f"{DS}/table/{t.table_id}"
        g.add(DS, "dcterms:hasPart", tiri, M)
        g.add(tiri, "rdf:type", "csvw:Table", M)
        g.add(tiri, "dcterms:title", L(t.table_label), M)
        g.add(tiri, "dcterms:description", L(t.description), M)
        g.add(tiri, "csvw:url", L(str(t.file_name)), M)
        if isinstance(t.observation_unit_iri, str) and t.observation_unit_iri:
            g.add(tiri, "sosa:hasFeatureOfInterest" if False else "dcterms:type", t.observation_unit_iri, M)
    dec = pd.read_csv(PKG / "metadata/semantic/measurement-decompositions.csv", dtype=str, keep_default_na=False)
    for _, r in dict_df.iterrows():
        tiri = f"{DS}/table/{r.table_id}"
        col = f"{tiri}/column/{r.column_name}"
        g.add(tiri, "csvw:column", col, M)
        g.add(col, "rdf:type", "csvw:Column", M)
        g.add(col, "csvw:name", L(r.column_name), M)
        g.add(col, "csvw:title", L(r.column_label), M)
        g.add(col, "dcterms:description", L(r.column_description), M)
        g.add(col, D + "columnRole", L(r.column_role), M)
        g.add(col, "csvw:datatype", L(r.value_type), M)
        if isinstance(r.unit_iri, str) and r.unit_iri:
            g.add(col, "http://qudt.org/schema/qudt/unit", r.unit_iri, M)
        term = r.term_iri if isinstance(r.term_iri, str) and r.term_iri else None
        status = "gap"
        provisional = r.column_name in ("MAX_ESTIMATE", "spawner_abundance", "EFFECTIVE_FEMALES")
        if r.column_role == "measurement" and (term or provisional):
            var = f"{C.BASE}id/variable/{SLUG}/{r.table_id}/{r.column_name}"
            g.add(col, D + "variable", var, M)
            g.add(var, "rdf:type", "iop:Variable", M)
            g.add(var, "rdfs:label", L(f"{r.column_label} ({r.column_name})", lang="en"), M)
            if term:
                g.add(var, "skos:broadMatch", term, M)
            if provisional:
                review_assertion(g, var, "rdfs:label", L(r.column_label, lang="en"), M,
                    evidence=[SRC_DS, META_URL],
                    note="Critical source-field interpretation awaiting source/dictionary review; source numbers are unchanged and no spawner-only or literal row-maximum equation is asserted.")
                if r.column_name == "EFFECTIVE_FEMALES":
                    review_assertion(g, var, "skos:closeMatch", PSC_EFS, MP, evidence=[SRC_DS, META_URL],
                        confidence="lowConfidence", justification=SEMAPV_AGENT,
                        note="Candidate only: PSC-CV-000035 is a brood-year stock-recruit variable. NuSEDS EFFECTIVE_FEMALES requires DFO dictionary and scope review before accepting this alignment.")
            rows = dec[(dec.table_id == r.table_id) & (dec.column_name == r.column_name)]
            pmap = {"property": "iop:hasProperty", "entity": "iop:hasObjectOfInterest",
                    "constraint": "iop:hasConstraint", "statistical_modifier": "iop:hasStatisticalModifier"}
            has_gap = False
            for _, d in rows.iterrows():
                if d.component_status == "matched" and d.component_role in pmap:
                    g.add(var, pmap[d.component_role], d.component_iri, M)
                elif d.component_status == "gap":
                    has_gap = True
                    gap = f"{C.BASE}id/gap/{SLUG}/{C.slug_iri(d.component_role + '-' + d.component_label)}"
                    g.add(var, D + "hasGap", gap, M)
                    g.add(gap, "rdf:type", D + "SemanticGap", M)
                    g.add(gap, "rdfs:label", L(d.component_label, lang="en"), M)
                    g.add(gap, "dcterms:type", L(f"I-ADOPT {d.component_role}"), M)
                    g.add(gap, "skos:scopeNote", L(d.rationale, lang="en"), M)
            status = "partial" if has_gap or provisional else "matched"
        elif term:
            g.add(col, "dcterms:subject", term, M)
            status = "matched"
        elif r.column_role in ("categorical",):
            cc = codes[(codes.table_id == r.table_id) & (codes.column_name == r.column_name)]
            has = cc.term_iri.fillna("").astype(str).str.strip().ne("")  # read_salmon_datapackage gives "" not NaN
            status = "matched" if len(cc) and has.all() else ("partial" if has.any() else "gap")
        elif r.column_role in ("identifier", "temporal", "attribute"):
            status = "not-required"
        if r.column_role == "measurement" and not term:
            gap = f"{C.BASE}id/gap/{SLUG}/variable-{C.slug_iri(r.column_name)}"
            g.add(col, D + "hasGap", gap, M)
            g.add(gap, "rdf:type", D + "SemanticGap", M)
            g.add(gap, "rdfs:label", L(f"variable: {r.column_label}", lang="en"), M)
            g.add(gap, "dcterms:type", L("measurement variable"), M)
        g.add(col, D + "semanticStatus", L(status), M)
        if r.column_role == "categorical":
            sch = f"{C.BASE}code/{CODE_SCHEMES[r.column_name][0]}" if r.column_name in CODE_SCHEMES else f"{C.BASE}code/{SLUG}/{C.slug_iri(r.column_name)}"
            g.add(col, D + "codeList", sch, M)
    for t, n in rowcounts.items():
        g.add(f"{DS}/table/{t}", D + "rowCount", L(int(n)), M)

    # ---- code lists + SSSOM mappings ------------------------------------------------------------
    sssom = {}
    for p in sorted((PKG / "metadata/semantic").glob("*.sssom.tsv")):
        ms_set = ms.read_sssom_mapping_set(str(p))
        cm = ms_set.metadata["curie_map"]
        for _, m in ms_set.mappings.iterrows():
            def ex(x):
                pf, _, loc = x.partition(":")
                return cm.get(pf, NS.get(pf, pf + ":")) + loc
            sssom[ex(m.subject_id)] = (m.predicate_id, m.object_id, ms_set.metadata["mapping_set_id"],
                                      m.get("comment", ""), m.mapping_justification)
    for _, r in codes.drop_duplicates(["column_name", "code_value"]).iterrows():
        sch = f"{C.BASE}code/{CODE_SCHEMES[r.column_name][0]}" if r.column_name in CODE_SCHEMES else f"{C.BASE}code/{SLUG}/{C.slug_iri(r.column_name)}"
        ci = code_iri(r.column_name, r.code_value)
        g.add(sch, "rdf:type", "skos:ConceptScheme", MP)
        g.add(sch, "rdfs:label", L(f"{r.column_name} codes"), MP)
        g.add(ci, "rdf:type", "skos:Concept", MP)
        g.add(ci, "skos:inScheme", sch, MP)
        g.add(ci, "skos:prefLabel", L(r.code_value), MP)
        g.add(ci, "skos:notation", L(r.code_value), MP)
        if ci in sssom:
            pred, obj, set_id, note, justification = sssom[ci]
            by_agent = justification in ("semapv:AgentBasedMatching", SEMAPV_AGENT)
            if obj != "sssom:NoTermFound":
                if by_agent:
                    review_assertion(g, ci, C.expand(pred), C.expand(obj), MP,
                        evidence=[SRC_DS, META_URL, set_id], note=str(note), justification=SEMAPV_AGENT)
                else:
                    g.add(ci, C.expand(pred), C.expand(obj), MP)
            else:
                gap = f"{C.BASE}id/gap/{SLUG}/code-{C.slug_iri(r.column_name)}-{C.slug_iri(r.code_value)}"
                g.add(ci, D + "hasGap", gap, MP)
                g.add(gap, "rdf:type", D + "SemanticGap", MP)
                g.add(gap, "rdfs:label", L(f"{r.column_name} = {r.code_value}"), MP)
                g.add(gap, "dcterms:type", L("code value"), MP)
                if by_agent:
                    review_assertion(g, ci, C.expand(pred), C.expand(obj), MP,
                        evidence=[SRC_DS, META_URL, set_id], note=str(note), justification=SEMAPV_AGENT)
            g.add(ci, "dcterms:source", set_id, MP)
            if isinstance(note, str) and note:
                g.add(ci, "skos:editorialNote", L(note), MP)
        elif isinstance(r.term_iri, str) and r.term_iri:
            g.add(ci, "skos:exactMatch", r.term_iri, MP)

    # ---- source identity nodes and reviewable pairing candidates ----------------------------
    identity_counts = add_identities(g, c)

    # ---- RDF Data Cube --------------------------------------------------------------------------
    qbds = f"{C.BASE}cube/{SLUG}/cu-year-spawners"
    dsd = f"{qbds}/structure"
    g.add(qbds, "rdf:type", "qb:DataSet", CB)
    g.add(qbds, "rdfs:label", L("Sum of source MAX_ESTIMATE by CU, species, year and estimate classification", lang="en"), CB)
    g.add(qbds, "rdfs:comment", L("Sum of unchanged source MAX_ESTIMATE values; biological scope awaits review. Not infilled or expanded; the legacy name does not establish spawner abundance.", lang="en"), CB)
    g.add(qbds, "qb:structure", dsd, CB)
    g.add(qbds, "prov:wasDerivedFrom", f"{DS}/table/{CUBE_T}", CB)
    g.add(qbds, "dcterms:license", LICENCE, CB)
    g.add(qbds, "dcterms:source", SRC_DS, CB)
    g.add(DS, "dcterms:hasPart", qbds, M)
    g.add(dsd, "rdf:type", "qb:DataStructureDefinition", CB)
    for i, (prop, kind) in enumerate([(D + "conservationUnit", "qb:dimension"), (D + "species", "qb:dimension"),
                                      ("smn:returnYear", "qb:dimension"), (D + "estimateClassification", "qb:dimension"),
                                      (D + "spawnerAbundance", "qb:measure"), (D + "siteCount", "qb:measure"),
                                      (D + "unitMeasure", "qb:attribute")], 1):
        comp = f"{dsd}/component/{i}"
        g.add(dsd, "qb:component", comp, CB)
        g.add(comp, kind, prop, CB)
        g.add(comp, "qb:order", L(i), CB)
    g.add(qbds, D + "unitMeasure", INDIV, CB)
    cube = c.execute(f"SELECT * FROM read_csv('{PKG / 'data' / (CUBE_T + '.csv')}', sample_size=-1)").df()
    for r in cube.itertuples(index=False):
        o = f"{qbds}/obs/{r.cuid}/{r.Year}/{C.slug_iri(r.ESTIMATE_CLASSIFICATION)}"
        g.add(o, "rdf:type", "qb:Observation", CB)
        g.add(o, "qb:dataSet", qbds, CB)
        g.add(o, D + "conservationUnit", ident("cu", "psf", r.cuid), CB)
        g.add(o, D + "species", C.NCBI_TAXON[r.SPECIES][1], CB)
        g.add(o, "smn:returnYear", L(str(int(r.Year)), "xsd:gYear"), CB)
        g.add(o, D + "estimateClassification", code_iri("ESTIMATE_CLASSIFICATION", r.ESTIMATE_CLASSIFICATION), CB)
        g.add(o, D + "spawnerAbundance", L(float(r.spawner_abundance)), CB)
        g.add(o, D + "siteCount", L(int(r.n_sites)), CB)

    # ---- write -------------------------------------------------------------------------------------
    if g.unverified:
        raise SystemExit(f"Unverified smn/gcdfo IRIs emitted: {sorted(g.unverified)}")
    out = g.write(GRAPH_FILE)

    # IRI-keyed Parquet (row-level data); raw numeric values are unchanged.
    write_iri_parquet(c, PARQUET)
    # pyoxigraph store
    if STORE_DIR.exists():
        shutil.rmtree(STORE_DIR)
    STORE_DIR.parent.mkdir(parents=True, exist_ok=True)
    st = ox.Store(str(STORE_DIR))
    st.bulk_extend(g.quads)
    # Count the unique dataset quads before adding the vocabulary graphs.
    dataset_quads = len(st)
    per_graph = {k: sum(1 for _ in st.quads_for_pattern(None, None, None, N(v)))
                 for k, v in GRAPHS.items()}
    log(f"graph written: {out} ({dataset_quads} quads)")
    iri_counts = validate_parquet_iris(st, c, PARQUET)
    for key, path in vocab.paths.items():
        st.bulk_load(path=str(path), format=ox.RdfFormat.TURTLE, to_graph=N(f"{C.BASE}graph/vocab/{key}"))
    st.flush()
    stats = {"quads_dataset": dataset_quads, "quads_store_total": len(st),
             "per_graph": per_graph,
             **identity_counts,
             "parquet_join_keys": iri_counts,
             "cube_observations": len(cube), "graph_file": str(out.relative_to(OUTPUT_ROOT)),
             "graph_file_bytes": out.stat().st_size, "parquet_bytes": PARQUET.stat().st_size}
    (PKG / "review" / "graph-summary.json").write_text(json.dumps(stats, indent=2) + "\n")
    log(f"graph ok: {stats}")
    return stats


def stage_queries() -> dict:
    st = ox.Store(str(STORE_DIR))
    counts = C.run_queries(st, QDIR)
    log(f"queries ok: {counts}")
    return counts


STAGES = {"fetch": stage_fetch, "profile": stage_profile, "package": stage_package,
          "graph": stage_graph, "queries": stage_queries}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default=",".join(STAGES))
    ap.add_argument("--build-time", help="Pinned UTC reference timestamp; not actual execution time")
    ap.add_argument("--output-root", type=Path, help="Isolated output tree; source inputs are read from this checkout")
    a = ap.parse_args()
    if a.build_time:
        os.environ["SALMONGRAPH_BUILD_TIME"] = a.build_time
    if a.output_root:
        configure_output_root(a.output_root)
    timings = {}
    log(f"actual execution started: {C.now_utc()}")
    for s in a.stages.split(","):
        t0 = time.time()
        STAGES[s]()
        timings[s] = round(time.time() - t0, 1)
    log(f"timings (s): {timings}")
    log(f"actual execution ended: {C.now_utc()}")
