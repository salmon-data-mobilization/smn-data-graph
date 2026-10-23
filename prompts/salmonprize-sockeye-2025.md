# Task: Salmon Prize 2025 Sockeye International data pack (slug: `salmonprize-sockeye-2025`)

The shared rules (`prompts/common.md`) and the corpus contract (`prompts/corpus-contract.md`) are included above; follow both.

## Source and licence (check before publishing anything)

- **Archive:** https://github.com/SOLV-Code/SalmonPrize_Diagnostics (SOLV
  Consulting; Gottfried Pestal, who is a co-author on Brett's PICES talk).
  - Folder: `Sockeye_International_2025/`.
  - The repository licence is GPL-3.0. **There is no separate data licence.**
  - Record this as "data terms not stated; ask the organisers" and keep the
    package local-only until Brett has asked Pestal.
- **Files:**
  - `CompetitionDataSet/Original_Data_Pack/`: Bristol Bay, Columbia and Fraser
    brood and return tables, the combined tables, and
    `Combined_First_Year_At_Sea.csv`.
  - `Observed_Runs/`
  - `AgencyFC/Sockeye_International_2025_AgencyForecasts.csv`
  - `Team_Submissions/*/predictions.csv`
  - `Team_Submissions/Sockeye_International_2025_ModelMetadata.csv`
  - `Diagnostics/*.csv`
- **Raw URLs:** `https://raw.githubusercontent.com/SOLV-Code/SalmonPrize_Diagnostics/main/<path>`.
  Record the commit SHA you fetched.

## Verified facts from the cloud probe (re-check them)

- **Coverage:** 14 sockeye stocks — Bristol Bay 8, Fraser 5, and the Columbia
  aggregate. The brood table has 978 rows × 22 columns.
- **Age notation:** age classes are in European notation (`AgeClass_0.1` …
  `AgeClass_3.4`).
- **Fraser recruits:** these match PSC 2026 within 0.5% for 69 brood years per
  stock (1948–2016), apart from Chilko 2015. Age-level cells: 1,168 of 1,211 are
  equal within 0.5%.
- **Model metadata:** `ModelMetadata.csv` describes the competing model types.
  Comment lines start with `#`, and the file warns that commas in text break
  parsing.

## What to build

1. Fetch the listed files at a pinned commit.
2. Profile:
   - stocks by system;
   - brood-year spans;
   - forecasts per team × stock × year;
   - agency vs team forecasts;
   - observed runs.
3. Build the SDP. Use three tables at least:
   - brood/return (stock-recruit);
   - forecasts (team or agency × stock × forecast year × value, with quantiles
     where given);
   - model metadata.

   Decompose the measures with I-ADOPT and validate.
4. Build the graph:
   - Stock nodes `ident("stock","salmonprize",<system>-<river>)`.
   - Cube observations for recruits by brood year and age.
   - A **forecast ledger**: forecast node → stock, target year, value, team
     (`prov:Agent`), model type, and the observed run. Absolute percent error is
     derived by query, not stored.
5. Write the queries. For example:
   - forecast error by model type and system;
   - agency vs best team by stock;
   - stocks where every forecast missed in the same direction in the same year
     (a shared signal);
   - which forecasts used environmental covariates.
6. Report, with demo notes and cross-source expectations:
   - Fraser: against `psc-fraser-sr`.
   - Bristol Bay: against the SASAP Bristol Bay stocks.
