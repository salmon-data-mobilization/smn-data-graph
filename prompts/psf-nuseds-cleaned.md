# Task: PSF cleaned NuSEDS spawner survey data (slug: `psf-nuseds-cleaned`)

This is the first dataset in the corpus, so the pattern you set will be
reused for the next datasets (DFO recruits-per-spawner, PSC Fraser
stock-recruit, SASAP brood and ASL tables, the Salmon Prize packs, NPAFC
PSDLD). Favour clear, reusable code and conventions.

## Source

- Title: "Cleaned spawner survey data", Pacific Salmon Foundation, curated by
  Bruno Carturan and Stephanie Peacock; published 2026-02-20; licence CC BY
  4.0; DOI 10.5281/zenodo.19959144.
- Record metadata: https://zenodo.org/api/records/19959144
- One file, about 300 MB:
  https://zenodo.org/api/records/19959144/files/2_nuseds_cuid_streamid_2026-02-20.csv/content
- It is DFO's NuSEDS (New Salmon Escapement Database System) escapement data,
  cleaned by PSF and linked to Conservation Unit IDs (CUID) and stream IDs.
  Find the exact columns, codes and meanings from the data and the Zenodo
  record description; do not assume them.

## What to build

1. Download with `curl -L`, write `SHA256SUMS` and `source.json`.
2. Profile with DuckDB. Record the profile in the report.
3. Make the SDP with metasalmonpy: dictionary, codes, semantics with real
   IRIs where they exist, observation structures and measurement
   decompositions where they fit. Use metasalmonpy's NuSEDS crosswalks
   (`nuseds_enumeration_method_crosswalk`,
   `nuseds_estimate_method_crosswalk`,
   `nuseds_estimate_classification_crosswalk`) for method and estimate-type
   columns. Validate the package and record what validation reports.
4. Build the graph (see the shared rules). Identity nodes for each CU and
   stream, with species and region where the data give them. Data Cube
   observations at the CU x species x year level (spawner abundance, with
   the estimate classification kept visible). Load everything into a
   pyoxigraph store.
5. Write and run at least five SPARQL competency queries that show the
   integration value, for example: which CUs of a species and region have
   counts in each decade; how estimate methods or classifications changed
   over time; which CUs rely mostly on low-quality estimate types; which
   columns still lack ontology terms. Save each query and its results.
6. Finish the report. Include a short "demo notes" section: two or three
   queries or facts that would look good on a slide, with the numbers.
