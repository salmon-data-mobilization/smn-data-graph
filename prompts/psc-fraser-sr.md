# Task: PSC Fraser sockeye stock–recruit dataset (slug: `psc-fraser-sr`)

The shared rules (`prompts/common.md`) and the corpus contract (`prompts/corpus-contract.md`) are included above; follow both. This dataset is
the **reference** for Fraser sockeye in the corpus. SASAP, DFO R/S and Salmon
Prize Fraser rows are all checked against it.

## Source

- **Title:** "Fraser Sockeye Stock-Recruit Dataset", Pacific Salmon Commission.
  - It joins DFO spawning-ground enumeration with PSC Secretariat
    recruitment-by-age estimates.
  - The page states no use restriction. Brett ruled the dataset public and usable
    in LLM sessions (tern D-14).
  - Record the PSC terms page as the licence reference: https://www.psc.org/terms-conditions/
- **Landing page:** https://www.psc.org/publications/data/fraser-sockeye-stock-recruit-dataset/
- **Files:**
  - Summary (by brood year): https://www.psc.org/download/726/stock-recruit-data-sets/19741/stock-recruit-data_summary-format.csv
  - Detailed (by brood year × age): https://www.psc.org/download/726/stock-recruit-data-sets/19742/stock-recruit-data_detailed-format.csv
  - Documentation, 12 pp.: https://www.psc.org/download/130/frp-data/19739/stock-recruit-data-documentation.pdf
- **Version:** the 2026-05-07 release (column `dataset_version` = 2026.05.07).
  Record whatever version you download.

## Verified facts from the cloud probe (re-check them; do not copy blindly)

- **Summary columns:**
  - `production_stock_name`, `production_stock_code`, `broodyr`
  - `total_broodyr_spawners`, `total_broodyr_EFS`
  - `total_broodyr_age1_smolt`, `total_broodyr_age2_smolt`, `total_broodyr_fry_estimate`
  - `recruits_age21` … `recruits_age72` (Gilbert–Rich ages)
  - `dataset_version`
- **Detailed columns** add:
  - `stock_broodyr_age`, `returnyr`, `age`, `num_recruits`
  - `hatchery_supplementation`, `active_spawning_channel`, `major_spawn_events`
  - `run_size_type` (historical / post-RSA / post-DBE / in-season-based)
  - `age_comp_method`, `stock_ID_quality`, `big_bar_flag`
  - `exclude_SR_modelling_spawners`, `exclude_SR_modelling_recruit`
- **Stocks** are production stocks 1–19 plus aggregates. Brood years start in 1948.
- **EFS vs total spawners:** `total_broodyr_EFS` is about half of
  `total_broodyr_spawners`. The ratio varies by stock (median total/EFS 1.89–2.68)
  and by year.

## What to build

1. Fetch both CSVs and the documentation PDF with `fetch_source`. Extract the
   PDF's definitions of EFS, `run_size_type`, `stock_ID_quality`, the exclusion
   flags and the Big Bar flag, with page numbers, into the report.
2. Profile with DuckDB, including the EFS/total ratio by stock and decade, and
   `run_size_type` by brood year.
3. Build the SDP with metasalmonpy:
   - Decompose spawners vs EFS vs recruits by age with I-ADOPT, as the contract
     requires.
   - Use `smn:GilbertRichAgeNotation` for the age codes.
   - Use the PSC CV concepts where they fit (contract section 2):
     `PSC-CV-000035` for EFS, `PSC-CV-000036` and `PSC-CV-000037` for age-1 and
     age-2 smolts, and `PSC-CV-000038` for fry. Add recruits by age, and any
     variable the PSC CV does not define, as concepts in the corpus variable
     scheme. Write term requests only for missing atomic parts.
   - Validate.
4. Build the graph:
   - Stock identity nodes `ident("stock","psc-frsk",code)`.
   - Cube observations at stock × brood year for the measures total spawners,
     EFS, total recruits and recruits by age. Use the Gilbert–Rich age as a
     dimension, with its European equivalent (`smn:EuropeanAgeNotation`) attached.
   - Keep `run_size_type` and the exclusion flags as observation attributes.
5. Write at least five competency queries. For example:
   - EFS/total ratio by stock and decade;
   - stock-years excluded from SR modelling and why;
   - how the run-size estimation type changed over time;
   - the share of recruits at European 2.x ages (Gilbert–Rich 43/53/63/64) by stock;
   - smolt-to-adult or fry-to-adult survival where smolt or fry estimates exist.
6. Report, with demo notes and cross-source expectations. Expected shared stocks:
   - SASAP stocks 102–119 (Fraser, Source 4): its `TotalEscapement` should equal
     `total_broodyr_EFS`.
   - The DFO R/S Fraser series sourced from Sue Grant: recruits mostly equal;
     differences come from missing 2.x ages, internal totals and post-RSA revisions.
   - Salmon Prize Fraser stocks: equal within 0.5%.
