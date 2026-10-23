# Task: DFO recruits-per-spawner data for BC sockeye, pink and chum (slug: `dfo-rs-productivity`)

The shared rules (`prompts/common.md`) and the corpus contract (`prompts/corpus-contract.md`) are included above; follow both.

## Source

- **Title:** "Productivity (Recruits-per-Spawner) data for Sockeye, Pink, and Chum
  Salmon from British Columbia".
  - Fisheries and Oceans Canada; Open Government Portal dataset
    3d659575-4125-44b4-8d8f-c050d6624758.
  - Licence: Open Government Licence – Canada (`ca-ogl-lgo`). Metadata were last
    modified 2026-03-24.
  - Underlying report: Ogden et al., Can. Tech. Rep. Fish. Aquat. Sci. 3130
    (https://waves-vagues.dfo-mpo.gc.ca/Library/359366.pdf).
- **Files** (DFO EDH api-proxy):
  - Data: https://api-proxy.edh-cde.dfo-mpo.gc.ca/catalogue/records/3d659575-4125-44b4-8d8f-c050d6624758/attachments/Salmon_RS_Database.csv
  - Dictionary (EN): .../attachments/Salmon_RS_Data_Dictionary_EN.csv
  - README (EN): .../attachments/Salmon_RS_README_EN.rtf
  - Time-series summary: .../attachments/Salmon_RS_Time_Series_Summary.csv
  - Decadal summary: .../attachments/Salmon_RS_Decadal_Summary.csv

## Verified facts from the cloud probe (re-check them)

- **Contents.** The time series are organised by species and unit: CU, PFMA, or
  aggregates of these. Columns include `Spawner`, `EFS`, `Catch`, `Returns`,
  `NTotRec`, `NRec<a.b>` (European ages), `Ret<a.b>` proportions, `ExplRate`,
  `R/S` and `R/EFS`, plus a `Source` column. The Fraser sockeye rows have Source
  "Sue Grant".
- **Against PSC 2026 Fraser recruits** (927 stock-years): 597 agree within 0.5%.
  The rest break down as:
  - 220 stock-years with European 2.x ages missing (4.09 M fish);
  - 57 where `NTotRec` does not equal the sum of DFO's own age columns;
  - 36 post-RSA revisions after 2014;
  - 4 that were preliminary brood years in 2014;
  - 13 unexplained.
- **Stock definitions.** One series differs by a median of 80%, which points to a
  different stock definition. Aggregates (e.g. 5+25+26, 8+15) need explicit
  membership.
- **Vocabulary gaps.** "R/S", "R/EFS", "age composition proportion" and "recruits
  by age" have no smn/gcdfo term.

## What to build

1. Fetch all files. Quote the README's definitions of `Spawner` (including jacks
   and jills) and `EFS` in the report.
2. Profile: series by species × unit type × region; year spans; `Source` values.
   Also check whether `Year` is the brood year or the return year in each column
   family, using the dictionary.
3. Build the SDP:
   - Use I-ADOPT decomposition, with explicit year basis, age notation and
     jack inclusion.
   - Add R/S and R/EFS as concepts in the corpus variable scheme
     (contract section 2), decomposed into atomic parts. Write term requests
     only for missing atomic parts.
   - Validate.
4. Build the graph:
   - Stock nodes `ident("stock","dfo-rs",<series id>)`, linked to the PSF/DFO CU
     nodes where the unit is a CU (`skos:closeMatch` in `crosswalk`).
   - Cube observations at series × year for the measures spawners, EFS, total
     recruits, returns, catch, exploitation rate, R/S and R/EFS.
5. Write the queries. For example:
   - series by species and unit;
   - which series report EFS as well as total spawners;
   - productivity (R/S) by decade for sockeye, pink and chum CUs;
   - columns without ontology terms.
6. Report, with demo notes and cross-source expectations:
   - Fraser sockeye: against `psc-fraser-sr`.
   - BC Central and North sockeye: against SASAP stocks.
   - CU-level series: against PSF NuSEDS CU nodes.
