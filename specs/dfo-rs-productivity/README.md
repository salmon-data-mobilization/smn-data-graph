# DFO salmon productivity in British Columbia

The package preserves all three DFO data files for British Columbia sockeye, pink and chum salmon. The annual table contains 8,093 records with escapement, catch, returns, age composition, recruits, productivity ratios and data-quality fields. One file provides 160 time-series summaries. Another provides 87 decadal data-quality summaries across four species or brood-line blocks. The graph describes the tables, fields and source files. The local Salmon Data Package holds the lexical values and the information needed to reconstruct each source cell. [DFO dataset](https://open.canada.ca/data/en/dataset/3d659575-4125-44b4-8d8f-c050d6624758) · [Ogden et al., 2015, methods report](https://waves-vagues.dfo-mpo.gc.ca/Library/359366.pdf)

DFO assigns the Open Government Licence – Canada to record `3d659575-4125-44b4-8d8f-c050d6624758`. Contains information licensed under the Open Government Licence – Canada. The catalogue record retrieved on 2026-11-26 lists 2025-01-31 as the data modification date and 2026-03-24 as the metadata modification date. DFO gives no release number. This package version uses a digest of the five pinned file hashes in Spec order, joined with a newline. [Primary catalogue record](https://open.canada.ca/data/api/3/action/package_show?id=3d659575-4125-44b4-8d8f-c050d6624758) · [Licence and attribution](https://open.canada.ca/en/open-government-licence-canada/)

## Reading the tables

The annual table preserves 61 source fields in their original order. The last two have empty headers and contain only empty cells. The package names them by their original positions, `unnamed_source_column_60` and `unnamed_source_column_61`. The combination of `Species`, `CU or PFMA or aggregate` and `Year` identifies each record within these exact bytes. DFO mixes Conservation Units, management areas and aggregates in the area column. A common spelling across datasets requires independent evidence before it can identify a common stock.

The source `Year` spans 1950–2013. DFO defines it as the return year for catch and escapement and the brood year for recruits. There are 3,380 nonblank `R/S` values dated 1954–2011. DFO lists 1950–2012 as the dataset’s catalogue coverage. The five annual records dated 2013 have empty `R/S` fields. Annual spawner estimates can include jacks and jills. DFO directs readers to `Esc comm` for adult-only exceptions. [English data dictionary](https://api-proxy.edh-cde.dfo-mpo.gc.ca/catalogue/records/3d659575-4125-44b4-8d8f-c050d6624758/attachments/Salmon_RS_Data_Dictionary_EN.csv)

The series summary preserves all 25 source fields, including three blank `CU or PFMA` cells and seven literal `NA` values. A derived `source_record_number` gives the one-based record position after the header in the pinned CSV. It serves as the local package key. All original fields are lexical attributes. Observations and cross-source identity assignments require separate source interpretation.

The SDK trims whitespace at the edges of string fields. The pinned source CSVs contain exactly one trailing ASCII space in each of 69 annual comments and eight series-summary comments. In these two tables, the package stores the comment text up to the final space and records its position in a derived field, `source_columns_with_trailing_space`. For each row, split this field on `|` and append one U+0020 space to the value at each listed one-based **source** column position. An empty field means the row needs no padding restored. This convention affects six comment fields. Numerical values, identifiers and all decadal records retain their original text.

The decadal file stacks four tables with different column labels for stocks or areas. Each block becomes a separate package table under its own header. Sockeye has 24 rows, even-year pink has 18, odd-year pink has 21 and chum has 24. Each row describes the quality of one type of data for a stated period. The source fields `Species`, `Decade` and `DataQualityType` form the local key within a block. All period labels remain as supplied, including those for odd-year pink. Rectangular CSV padding to the right of each block was empty in both header and data rows. The independent check restores it and reproduces all four source headers and the complete 91-row by 91-column grid.

## Replay and check

Stage the five files from `source.files` in [the Spec](dfo-rs-productivity.yaml) under their declared filenames. The Spec records the direct publisher URLs and SHA-256 of the three data files, the English dictionary and the English readme. Run the batch intake with the project-local [parser](../dfo_rs_productivity_parser.py) in the executor source tree. Source attribution and the licence URI are part of the Spec.

After the executor writes a dataset build, run the independent source comparison from the repository root. It reverses the two positional header aliases and removes the derived summary ordinal, checking each ordinal against its actual source position. It checks the reconstruction positions against the pinned inputs, restores all 77 trailing spaces, compares all 501,570 original data cells across six tables, and reconstructs the complete decadal CSV grid.

```sh
python specs/dfo-rs-productivity/verify_source.py --raw-dir "$DFO_RAW_DIR" --build-dir "$DFO_BUILD_DIR"
```
