# psf-nuseds-cleaned: build report

Dataset: "Cleaned spawner survey data", Pacific Salmon Foundation (B. Carturan, S. Peacock),
2026-02-20, CC BY 4.0, doi:10.5281/zenodo.19959144. It is DFO NuSEDS (extract 2025-11-03),
cleaned by PSF and matched to CUs and stream IDs.

Status: **every phase completed** (download, profile, SDP, graph, store, 7 queries). A clean rebuild
from `data/raw/` with one command reproduces all of it (see "Rebuild").

## What was built

| Artefact | Path | Size / count |
|---|---|---|
| Raw CSV (md5 matches Zenodo) | `data/raw/psf-nuseds-cleaned/2_nuseds_cuid_streamid_2026-02-20.csv` | 300,313,230 B; 315,501 rows x 90 cols |
| PSF column definitions | `data/raw/psf-nuseds-cleaned/METADATA_2_nuseds_cuid_streamid.csv` | 37 fields described (of 90) |
| Checksums, source record | `data/raw/psf-nuseds-cleaned/SHA256SUMS`, `source.json`, `zenodo_record.json` | |
| Column profile | `profiles/psf-nuseds-cleaned/column-profile.csv`, `profile-summary.json` | 90 rows |
| SDP | `packages/psf-nuseds-cleaned/` | 2 tables, 102 dictionary rows, 271 code rows (67 with term IRI) |
| ├ main table | `data/nuseds_cuid_streamid.csv` (git-ignored) | 315,501 rows x 91 cols (90 source + `primary_enumeration_method`) |
| ├ aggregate | `data/cu_year_spawners.csv` (git-ignored) | 26,141 rows (CU x year x estimate classification) |
| ├ observation structures | `metadata/structure/` | 20 structures (one per measurement column) |
| ├ measurement decompositions | `metadata/semantic/measurement-decompositions.csv` | 32 rows, 6 measurement columns |
| ├ SSSOM mapping sets | `metadata/semantic/*.sssom.tsv` | 3 sets: estimate classification, estimate method, enumeration method |
| ├ term gaps | `review/term-gaps.csv` | 33 gaps |
| └ build / graph summaries | `review/build-summary.json`, `review/graph-summary.json` | validation output recorded here |
| IRI-keyed row data | `packages/psf-nuseds-cleaned/data/nuseds_cuid_streamid.iri-keyed.parquet` (git-ignored) | 315,501 rows; 6.6 MB zstd; 6 IRI columns + 91 source columns |
| RDF | `graph/psf-nuseds-cleaned.trig` | 16.9 MB (under 20 MB, so not gzipped); 326,766 quads written |
| pyoxigraph store | `graph/store/psf-nuseds-cleaned/` (git-ignored) | 329,727 quads incl. gcdfo + smn vocab graphs |
| Pipeline | `pipelines/psf-nuseds-cleaned.py` + shared `pipelines/corpuslib.py` | |
| Queries | `queries/psf-nuseds-cleaned/01..07-*.rq` + `.csv` | 7 competency queries |

Named graphs (quads): metadata 1,184; mappings 1,646; identity 114,765; cube 209,158;
provenance 13. Identity nodes: 393 PSE CUs (plus DFO CU nodes from `FULL_CU_IN`), 2,377 NuSEDS stream
features (GFE_ID), 6,988 PSE stream sites (streamid), 6,184 NuSEDS populations (POP_ID),
10 regions, 5 species (NCBITaxon). Data Cube: 26,141 `qb:Observation`s.

### Rebuild

```
.venv/bin/python -I pipelines/psf-nuseds-cleaned.py                        # all stages (~7 min)
.venv/bin/python -I pipelines/psf-nuseds-cleaned.py --stages graph,queries  # ~20 s
```
Stages: `fetch` (skips files already present; re-checks md5 against Zenodo), `profile`, `package`,
`graph`, `queries`.

### Validation

*Added after the run by the reviewing session; the agent's own edit for this section was refused
at the end of the run. Source: `packages/psf-nuseds-cleaned/review/build-summary.json`.*

`validate_salmon_datapackage` reports **no structural issues and no semantic issues**. 14 measurement
columns have no term (`term_iri`, `entity_iri`, `property_iri`, `constraint_iri` missing for each;
`statistical_modifier_iri` missing for 20 fields): Adult/Jack/Total Broodstock Removals, Other
Removals, Total Return To River, Natural Adult Females, Natural Adult Males, Effective Females,
Weighted Pct Spawn, No Inspections Used, Returns, Broodstock, Removals, N Sites. These are the
term gaps listed below. A clean rebuild from `data/raw/` took 6 min 23 s and reproduced every count
and query result.

## Profile (DuckDB)

- 315,501 rows, 90 columns, years 1920-2024. Missing values are the string `NA`. Read with
  `nullstr=['NA','']`, otherwise all numeric columns come in as VARCHAR.
- Row key: (`IndexId`, `GFE_ID`, `Year`) is unique; `ACT_ID` is unique per row. (`IndexId`, `Year`)
  alone has 350 duplicates.
- Distinct values: POP_ID 6,184; GFE_ID 2,377; IndexId 7,026; cuid 393 (+null); streamid 6,988;
  CU_NAME 363; region 10.
- `cuid`/`streamid` null in 2,085 rows (0.7%): records not matched to a CU.
- `MAX_ESTIMATE` (PSF: max of 8 NuSEDS count fields) is non-null in 157,573 rows (49.9%): range
  0-19,842,566, median 400. The other half are survey-year rows with no estimate.
  17,248 of those rows still have `ADULT_PRESENCE = PRESENT`.
- `ESTIMATE_CLASSIFICATION` (all rows): UNKNOWN 248,014 (78.6%), Type-6 26,311, Type-4 15,532,
  Type-3 10,846, Type-5 9,149, Type-1 2,490, Type-2 1,857, RELATIVE: CONSTANT MULTI-YEAR 613,
  NO SURVEY THIS YEAR 360, RELATIVE: VARYING MULTI-YEAR 277, **NO SURVEY 50** (not in PSF metadata
  or the metasalmonpy crosswalk), null 2.
- `ESTIMATE_METHOD`: 25 values. Unknown Estimate Method 137,145, Not Applicable 116,467, Expert Opinion
  27,123, AUC 10,054, ... **Fence Count 2,553 and Aerial Survey 6 are not in the crosswalk.**
- `ENUMERATION_METHODS`: 88.8% null; a comma-separated list (347 combinations; the first entry is
  primary). Most common tokens: Walk 24,758, Helicopter 5,821, Bank Walk 2,928. **`Net` (1) is not in the
  crosswalk.**
- `stream_survey_quality` (PSF) is a deterministic recode of `ESTIMATE_CLASSIFICATION`
  (Type-1 High ... Type-5/6 and multi-year Low, UNKNOWN Unknown).
- Dates (`START_DTT`, `*_DT_FROM/TO`, `CREATED_DTT`) are `DD-MON-YY` strings with two-digit years, so
  the century is ambiguous. I left them as strings.
- 53 of the 90 columns are not described in PSF's metadata file. Their SDP descriptions are marked
  `[agent]` (inferred from names and values); the DFO NuSEDS data dictionary was not retrieved.

## Time per phase (wall clock, approximate)

| Phase | Time |
|---|---|
| Download (300 MB from Zenodo, in background) | 4 min |
| Reading metasalmonpy source, ontology checks, design | 11 min (overlapped with download) |
| Profiling | 4 min |
| Writing pipeline + shared library | 6 min |
| Package build/debug (3 failed runs, then OK) | 14 min. One package run takes ~6 min, mostly metasalmonpy validators re-reading the 250 MB CSV |
| Graph + store + queries | 3 min (graph stage 18 s, queries 1 s) |
| Report, clean rebuild | ~10 min |
| **Total** | **~50 min; about $5 of the $9 budget** |

*Reviewer note: the agent's phase times overlap and overstate the total. Measured by the runner:
34.6 min wall clock (main task 29.4 min, then two short follow-up turns), estimated cost $5.27
(`run.json`); the Console credit fell by $5.26.*

## What broke or was confusing, and the workaround

metasalmonpy 0.6.0:
1. **Crosswalk IRI that does not exist.** `nuseds_enumeration_method_crosswalk()` maps
   "Based on Angling Catch" to `gcdfo:EnumerationMethod`, which is not in gcdfo. gcdfo's
   `EnumerationMethodScheme` uses `smn:EnumerationMethod` as its top concept. Fixed in the pipeline
   (`crosswalks()`), with a note in the SSSOM comment. **This should be fixed upstream.**
2. **Crosswalks miss values found in the data:** `NO SURVEY` (classification), `Fence Count` and
   `Aerial Survey` (estimate method), `Net` (enumeration). I added them as documented "corpus additions".
   `Fence Count` -> `gcdfo:FixedStationTally` (broadMatch) needs review. `Aerial Survey` is left
   unmapped on purpose: `gcdfo:AerialSurveyCount` is a field method, not an estimate method.
3. **Inference parses two-digit-year dates into the future:** `infer_salmon_datapackage_artifacts`
   set `temporal_end = 2075-11-15` (it read `15-NOV-75` as 2075). It also emits pandas `UserWarning`
   floods. I overrode temporal coverage from `Year`.
4. **Role inference is inconsistent** for parallel fields (`ADULT_BROODSTOCK_REMOVALS` comes out as an
   attribute, `TOTAL_BROODSTOCK_REMOVALS` as a measurement). I set all 102 roles explicitly.
5. **`sosa:usedProcedure` cannot be used with NuSEDS method columns.** The observation-structure
   validator requires every observed code to have a `term_iri`. "Unknown Estimate Method", "Not
   Applicable", "Expert Opinion" and "Other" have none, and should not get one. So method columns are
   plain attributes in the structures, and the method link lives in SSSOM and the graph instead.
6. **The observation-structure extension is all or nothing.** Once used, every measurement column needs
   a structure, so there are 20 near-identical structures. It is generated in code, but it is noise.
7. **Composite primary key syntax is undocumented in the guides:** it is comma-separated
   (`cuid,Year,ESTIMATE_CLASSIFICATION`). I found this in the source after a validation error.
8. **`write_salmon_datapackage` refuses a folder it did not create.** This bit me when I wrote the profile
   into the package folder first. The profile now lives in `profiles/`.
9. **Measurement decompositions need `source_version` and `source_url` on every row,** including gap
   rows. That makes sense, but I only learned it from the error.
10. **`detect_semantic_term_gaps(dict_df=...)` returns 0 rows** without LLM or suggestion evidence, so it
    did not find the 14 measurement columns with no term. I wrote my own gap table
    (`review/term-gaps.csv`) and recorded the metasalmonpy output next to it.
11. **`validate_salmon_datapackage` returns DataFrames**, which is awkward to log. I summarise them in
    `build-summary.json`.
12. **Slow on large tables:** each extension writer and the validator re-read the 250 MB CSV, so a
    package build takes about 6 min. Not a blocker, but it will hurt with bigger datasets.
13. `read_salmon_datapackage` returns blank codes as `""`, not NaN. This caused a bug in my status logic,
    now fixed.

Ontology and hosts:
- `https://w3id.org/gcdfo/salmon` redirects to `dfo-pacific-science.github.io`, which **is blocked by the
  sandbox**. Workaround: gcdfo `main` from `raw.githubusercontent.com` (`owl:versionInfo 0.0.9`;
  sha256 recorded in the graph's PROV). Not a pinned release; flag before the talk.
- `https://w3id.org/smn/` returns HTML by default. I used the local flattened build
  `~/code/salmon-domain-ontology/salmon-domain-ontology.ttl`.
- `creativecommons.org` is blocked; the licence IRI is used, not dereferenced.
- smn has **no I-ADOPT `iop:Variable` individuals yet**, only statistical modifiers. So there is no
  existing variable to reuse; I minted corpus variable nodes per column with `skos:broadMatch` to
  `gcdfo:SpawnerAbundance`.

Data:
- Most of the record is unclassified (see demo notes). Before 1990, >98% of stream estimates are
  `UNKNOWN` classification. This is almost certainly legacy migration, not survey quality; queries
  label it "unmapped NuSEDS: UNKNOWN", not "low quality", except in CQ3 (which is restricted to 2015+).
- One DFO CU (SEL-21-02, Babine) is split by PSF into 3 CUs. These are linked with `skos:broadMatch`
  to the DFO CU node, so datasets keyed on DFO `FULL_CU_IN` still join.

## Term gaps (candidate term requests)

From `review/term-gaps.csv` (33 rows) and CQ4:
- **Variables with no concept (14 columns):** broodstock removals (adult, jack, total), other removals,
  total return to river, natural adult females / males, effective females, weighted percent spawn,
  number of inspections used, PSF `Returns`/`Broodstock`/`Removals`, and the aggregate `n_sites`.
  The most valuable requests are "return to river" (in-river run size), "broodstock removal" and
  "effective female spawners".
- **I-ADOPT constraint gaps:** adult life stage; jack (precocious male) life stage; natural (in-river)
  spawning, excluding broodstock. smn has `SpawnerStageContext` but no adult/jack or natural-spawning
  constraint.
- **Statistical modifier gap:** "maximum across alternative escapement fields" (`MAX_ESTIMATE`).
  `smn:MaximumStatisticalModifier` exists, but using it would misstate the meaning.
- **Codes with no concept (by design or missing):** classification UNKNOWN, NO SURVEY (THIS YEAR);
  estimate methods Unknown, Not Applicable, Expert Opinion, Other, Aerial Survey; enumeration
  Biologist/Working Group, Other, Net. "Expert Opinion" may deserve a concept: it covers 27,123 rows.
- **27 categorical columns have no code vocabulary at all** (CQ4): presence (ADULT/JACK_PRESENCE),
  ACCURACY/PRECISION/RELIABILITY, ESTIMATE_STAGE, RUN_TYPE, GFE_TYPE, CU_TYPE, adaptive zones,
  region, species qualifier. Run timing, life-stage presence and estimate stage are the obvious
  candidates for smn/gcdfo schemes.

## Decisions and why

- **SDP = source table unchanged + 1 derived column + 1 aggregate table.** Values are untouched so
  the package can be audited against Zenodo. `primary_enumeration_method` (the first token of
  `ENUMERATION_METHODS`) is derived because the full list is multi-valued and cannot carry codes.
- **Cube grain = CU x species x year x estimate classification**, with measures spawner abundance
  (sum of stream `MAX_ESTIMATE`) and number of sites. Making classification a *dimension*, not an
  attribute, keeps the cube additive and makes "how much of a CU's abundance rests on Type-5/6" one
  `SUM`. **This is not the PSE CU-level spawner series** (no infilling, no expansion). The cube's
  comment says so.
- **Codes are corpus SKOS concepts mapped to gcdfo through SSSOM,** not replaced by gcdfo IRIs. The
  NuSEDS label and the mapping evidence (predicate, set, note) stay queryable (CQ7), and the queries
  resolve types through the mappings graph (CQ2, CQ3). Predicates: exactMatch for same-meaning labels
  and Type-1..6, broadMatch where the gcdfo concept is broader or scheme-level, and `sssom:NoTermFound`
  for none.
- **IRI patterns** (base `https://w3id.org/salmon-demo-corpus/`, **provisional, not registered with
  w3id**): `id/<kind>/<authority>/<local-id>` for identities (`id/cu/psf/328`, `id/cu/dfo/CK-31`,
  `id/stream/dfo-nuseds-gfe/11486`, `id/population/dfo-nuseds/3306`, `id/site/psf-streamid/…`,
  `id/region/psf/…`); `code/nuseds/<column>/<slug>` for NuSEDS codes, shared across datasets;
  `def/` for corpus properties; `graph/<slug>/<part>` for named graphs; `cube/<slug>/…`.
- **Two CU identities:** the PSF `cuid` node is primary (the data are keyed on it). A DFO `FULL_CU_IN`
  node is linked with exactMatch (same index) or broadMatch (PSF split).
- **IRI guard:** the graph builder refuses to write any smn/gcdfo IRI that is not in the ontology files
  (this caught one bad IRI). Species IRIs (NCBITaxon) were checked on EBI OLS; QUDT units
  (`INDIV`, `NUM`, `PERCENT`) were checked by dereferencing.
- **Parquet lives in `packages/<slug>/data/`** (git-ignored, next to the CSV). Validation tolerates it.

## What the next dataset should reuse

- `pipelines/corpuslib.py`: `BASE`/`NS`, `ident()`, `fetch_source()` (curl + SHA256SUMS + source.json),
  `VocabIndex` (gcdfo + smn existence checks), `G` (named-graph builder with IRI guard, TriG, gzip
  over 20 MB), `dcat_dataset()`, `run_queries()`, and the verified `NCBI_TAXON` map.
- The stage layout and structure of `pipelines/psf-nuseds-cleaned.py` (copy and edit the column spec,
  cube SQL and identity section).
- Identity IRIs: DFO RPS and PSC Fraser should link CUs to `id/cu/dfo/<FULL_CU_IN>` (already minted
  here), and streams to `id/stream/dfo-nuseds-gfe/<GFE_ID>` when they carry NuSEDS IDs.
- The `def:` cube properties (`conservationUnit`, `species`, `estimateClassification`,
  `spawnerAbundance`) plus `smn:returnYear`, so cubes from different datasets can be queried together.
- `code/nuseds/*` code schemes and the 3 SSSOM sets (any NuSEDS-derived dataset).
- Lessons: read CSVs with explicit `nullstr`; set column roles explicitly; skip `sosa:usedProcedure`
  when codes include "unknown"; never write anything into the package folder before `write_salmon_datapackage`.

## Open questions for Brett

1. Fix `gcdfo:EnumerationMethod` -> `smn:EnumerationMethod` in metasalmonpy (and the R crosswalk), and
   add `NO SURVEY`, `Fence Count`, `Aerial Survey`, `Net`?
2. Should `Fence Count` map to `gcdfo:FixedStationTally` (as I did, broadMatch) or `FixedSiteCensusManual`?
3. Is the provisional base `https://w3id.org/salmon-demo-corpus/` acceptable, and should
   `def:` properties move into smn (for example `conservationUnit` as a cube dimension)?
4. Should gcdfo be pinned to a release (0.0.9 tag) rather than `main`? The w3id redirect host is blocked
   in the corpus sandbox.
5. Should the corpus mint I-ADOPT variable *individuals* in smn (for example "natural adult spawner
   abundance"), not per-dataset variable nodes? Every NuSEDS-derived dataset will need the same ones.
6. Is "sum of stream MAX_ESTIMATE" a fair demo measure, or should the cube come from the PSE CU-level
   series (PSE data library, outside this record)?
7. 2024 may be incomplete in NuSEDS (reporting lag). Should 2024 be dropped from the trend slide?

## Demo notes (slide-ready)

1. **"The quality label arrived in the 1990s."** Share of stream-level spawner estimates with
   classification UNKNOWN, by decade (CQ2): 1950s 99.7% (18,527 of 18,579), 1980s 98.7%,
   **1990s 81.9%**, **2000s 8.4%**, 2010s 0.5% (76 of 14,181). One SPARQL query, with gcdfo
   Type-1..6 resolved through the SSSOM mappings.
2. **Monitoring decline (CQ5):** CUs with any spawner estimate peaked at **293 in 1985** and fell to
   **211 in 2015** and **179 in 2024**. Stream-level estimates fell from 2,688 (1985) to 1,371 (2024),
   **-49%**. (2024 may be incomplete.)
3. **Where to be careful (CQ3):** since 2015, **39 CUs** across all 5 species have at least half of their
   stream estimates as Type-5/6 or unclassified. For example, Southern Fjords river-type sockeye (SER-09):
   94% of 31.
4. Integration hook: one graph holds **393 CUs, 2,377 streams, 6,184 NuSEDS populations, 26,141
   cube observations**. Every value traces to the DOI, the licence and the column definitions, and the
   graph flags where the ontology still has gaps (CQ4: 19 measurement and 27 categorical columns).
