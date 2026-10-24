# Ohlberger PWS 2021: lexical source discovery

Jan Ohlberger (2021), *Non-stationary and interactive effects of climate and competition on pink salmon productivity*, [Zenodo 5780246](https://doi.org/10.5281/zenodo.5780246), provides `GCB-21-1726 Data.csv` and its `README.rtf` under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The record identifies a publication/article, published 2021-12-14; it has no stated publisher version. The Spec's `lexical-cfb985d80518` is explicitly a derived CSV-content hash label, not a publisher release. The executor's explicit build date is a derived execution date, not the source's publication, observation or retrieval date.

This phase preserves the entire original table: 60 rows, 26 native fields, 1,560 cells, 197 literal `NA` tokens, no blanks and unchanged row order. `Year` is a unique, nonblank source-table key; it creates no biological identity. The builtin CSV parser consumes the UTF-8 BOM as an encoding marker. Generated CSV serialization can differ in BOM, quoting or line endings; headers and every source string must match. Both original files retain their actual publisher URLs and SHA256 pins. The README is hash-verified supporting evidence, not parsed as a second table.

The existing Spec schema rejects spaces in local filenames. The replayer therefore makes explicit byte-identical local copies: publisher `GCB-21-1726 Data.csv` → local `GCB-21-1726-Data.csv`, and publisher `GCB-21-1726 README.rtf` → local `GCB-21-1726-README.rtf`. These aliases are separate regular files in ignored staging; the original bytes, original remote keys and URLs remain unchanged. Existing different aliases, symlinks and overlapping source/build paths fail without overwrite. This changes no column, encoding or content and requires no custom parser, schema or guard change. The original failed-validation receipt is retained in local cache.

All columns are unmarked string attributes. `identity`, `observations`, `cross_source_checks` and `term_requests` are empty. This build admits **zero measured observations**, ontology mappings, cross-stock bridges or review decisions. It performs no numeric conversion, filtering, imputation, ratio calculation, brood-year shift or stock-origin interpretation. The source README calls `Year` return year and `Spawners` spawners two years prior, in millions; those descriptions remain source text. `RS`, `lnRS`, `BL` and `regime` remain lexical. The README describes `mean_pH` as pCO2 subpolar gyre; the header/description ambiguity is retained without repair. Subsequent measured intake requires reviewed time, scale, missing-token and variable meanings.

Malick v1.1 native pink stock 226, labelled PWS, is only proposed overlap context. Its 52 brood rows and two blank `use` flags do not establish equivalence to this source's return-year/wild records. No Malick file is a build input, and no join, normalization or identity assertion is emitted.

The explicit source grant makes `source.public` true as redistribution evidence. The genuine executor still sets `publication_ready: false` and records its actual metadata/contact/date gaps. No dummy contact, creator, source date or approval is inserted. All output stays in ignored local cache pending the owner's fidelity/privacy and transfer decision. No private AK/DFO/NOAA or Agent OS data is used; no person is contacted and nothing is uploaded.

Attribution is included in the Spec, generated `source_citation`, descriptions and a separate per-output inventory. That accompanying inventory contains every unchanged build file's relative path, SHA256, citation, source DOI/URLs, source licence and change notice, including `manifest.json`. It is written **outside** the genuine build directory. It does not change SDK CSVs, Parquet, RDF or the current manifest, add unmanifested files, relicense executor software, or certify science.

From the repository root, use an already installed locked environment and explicit local vocabularies. No fetch or install occurs:

```sh
<locked-python> -B specs/ohlberger-pws-2021/reproduce.py \
  --raw-dir <original-CSV-and-README-directory> \
  --staging-dir .cache/ohlberger-pws-intake/source-aliases \
  --vocab-dir <existing-offline-smn-gcdfo-psc-Turtle-directory> \
  --out-dir .cache/ohlberger-pws-intake/lexical-build-1 \
  --build-date 2026-10-24 \
  --receipt .cache/ohlberger-pws-intake/lexical-build-1-receipt.json \
  --attribution-receipt .cache/ohlberger-pws-intake/lexical-build-1-attribution.json
```

The replayer runs genuine SDK/vendored-schema build and SHACL validation, compares all original/derived CSV and SDK strings, exercises unchanged current-format `combine.load_dataset_build` and idempotent reload, verifies zero observations/identity/semantic-review assertions, and rechecks its source/Spec/evidence/script hashes. Ten outer Python DNS/socket hooks precede third-party imports and require a final zero-attempt count. This is an in-process measurement, not an OS network sandbox. Receipts use fresh paths and never overwrite earlier evidence. The executor retains its transactional source/output guards.

Focused tests use `OHLBERGER_PWS_SOURCE_DIR` and `OHLBERGER_PWS_VOCAB_DIR` for actual cached inputs; source-dependent checks skip when those explicit inputs are absent. The author and independent reviewers run them against the original files. No source table is embedded in tests or this handoff.
