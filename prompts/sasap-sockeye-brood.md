# Task: SASAP sockeye brood tables, NE Pacific (slug: `sasap-sockeye-brood`)

The shared rules (`prompts/common.md`) and the corpus contract (`prompts/corpus-contract.md`) are included above; follow both.

## Source

- **Title:** "Sockeye salmon brood tables, northeastern Pacific, 1922-2016".
  - Published by the State of Alaska's Salmon and People (SASAP) project, NCEAS,
    on the KNB.
  - EML packageId `doi:10.5063/F1891459`.
  - The cloud probe fetched it through `doi:10.5063/CR5RR9`. Record which version
    you get.
  - EML `intellectualRights`: "no restrictions". Cite as the EML says.
- **Files** (DataONE resolve URLs, taken from the EML):
  - BroodTables.csv: https://cn.dataone.org/cn/v2/resolve/urn:uuid:8371e85b-b693-4f22-9454-714ee17056f7
  - StockInfo.csv: https://cn.dataone.org/cn/v2/resolve/urn:uuid:178c61cc-6119-42c2-9387-5b0b602324d4
  - SourceInfo.csv: https://cn.dataone.org/cn/v2/resolve/urn:uuid:47fa131f-f5be-409d-b13b-8d9756a6239e
  - broodTableProcessing.Rmd: https://cn.dataone.org/cn/v2/resolve/urn:uuid:2e1f4408-6cbc-4acd-97b2-a0635a316952
  - The EML itself, from the KNB landing page for the DOI.

## Verified facts from the cloud probe (re-check them)

- **About 2,985 stock-years**, sockeye only. By region:
  - Fraser River 1,320
  - Bristol Bay 572
  - Kodiak 282
  - Chignik 190
  - PWS 160
  - SEAK 112
  - Cook Inlet 98
  - AK Peninsula 76
  - BC Central 49
  - BC North 46
  - WA 45
  - AYK 35
- **Columns:**
  - `Stock.ID`, `Species`, `Stock`, `Ocean.Region`, `Region`, `Sub.Region`
  - `Jurisdiction`, `Lat`, `Lon`, `UseFlag`, `BroodYear`, `TotalEscapement`
  - `R0.1` … `R4.3` (European age notation)
  - `TotalRecruits`
- **The EML** defines `TotalEscapement` as "Total escapement value" and
  annotates it with `http://purl.dataone.org/odo/salmon_000480` ("Annual
  escapement count").
- **The Fraser rows are effective female spawners, not total escapement.**
  - Fraser stocks are Stock.ID 102–119, Source.ID 4: "Sue Grant (DFO), Bronwyn
    McDonald (DFO) and Mike Lapointe (PSC) via Brendan Connors (ESSA
    Technologies)".
  - Joined to the PSC Fraser SR data, `TotalEscapement` / PSC
    `total_broodyr_EFS` has a median of exactly 1.00 for all 18 matched stocks
    (1,155 stock-years). The share of years within 1% is 0.87–1.00, except Gates
    0.62 and Cultus 0.11.
  - `TotalEscapement` / PSC `total_broodyr_spawners` has a median of 1.89–2.68,
    and no year is within 1%.
  - None of the EML, StockInfo, SourceInfo or the processing Rmd mentions EFS.
  - Treat this as a documentation and annotation gap in the merged compilation.
    It is not an error in PSC practice: EFS is the deliberate Fraser SR spawner
    measure.

## What to build

1. Fetch the files.
2. Profile:
   - stock-years by region and decade;
   - zero vs NA escapement (the Rmd recodes zeros to NA);
   - the use of `UseFlag`;
   - the source for each region.
3. Build the SDP:
   - Keep the source's column names.
   - Give `TotalEscapement` a **region-conditional** semantic description. For
     Source.ID 4 rows, decompose it as spawners + female + effective, and record
     the evidence. For other sources, decompose it as escapement unless their
     documentation says otherwise. Check SourceInfo for each region, and record
     unknowns as unknown.
   - Use `smn:EuropeanAgeNotation` for the `R*` columns.
   - Validate.
4. Build the graph:
   - Stock nodes `ident("stock","sasap",Stock.ID)`, with region, jurisdiction,
     coordinates and source.
   - Cube observations at stock × brood year (escapement, total recruits,
     recruits by European age).
   - A source-agent node for each Source.ID.
5. Write the queries. For example:
   - stock-years by region and source;
   - which regions' "escapement" is EFS vs total vs unknown;
   - the coverage timeline;
   - Fraser rows whose spawner semantics differ from the column label.
6. Report, with demo notes and cross-source expectations:
   - Fraser: against `psc-fraser-sr`, as above.
   - Bristol Bay: against the Salmon Prize Bristol Bay stocks.
   - BC Central and North: against `dfo-rs-productivity`.
