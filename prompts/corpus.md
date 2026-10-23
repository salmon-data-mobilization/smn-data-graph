# Task: build the combined corpus graph (slug: `corpus`, script: `pipelines/corpus.py`)

The shared rules (`prompts/common.md`) and the corpus contract (`prompts/corpus-contract.md`) are included above; follow both. Run this after
two or more dataset pipelines have written `graph/<slug>.trig`. Rerun it
whenever a dataset is added. Do not re-run the dataset pipelines: read their
TriG files and their IRI-keyed Parquet files.

## What to build

1. **Load.** Load every `graph/<slug>.trig[.gz]` and the gcdfo and smn vocabulary
   graphs into one pyoxigraph store at `graph/store/corpus/`. Keep each dataset's
   named graphs. Record the input sha256s in a `corpus-provenance` graph.
2. **Crosswalk graph.** For each pair of datasets that share stocks, match stock
   nodes on species + region + normalised name and on overlapping years. Then
   test the numbers:
   - Use `skos:exactMatch` only when identical totals fall within 0.5% for at
     least 90% of shared years.
   - Otherwise use `skos:closeMatch`.
   - Use `skos:narrowMatch` / `skos:broadMatch` for aggregates.

   Reify each assertion as a node carrying the match statistics. Also write an
   SSSOM TSV (`graph/corpus-crosswalk.sssom.tsv`). The expected first links are:
   - `psc-frsk/*` ↔ `sasap/102..119` ↔ `salmonprize/fraser-*` ↔ `dfo-rs` Fraser
     series;
   - the PSF CU nodes ↔ the `dfo-rs` CU series;
   - `sasap` Bristol Bay ↔ `salmonprize` Bristol Bay.
3. **Discrepancy graph.** For every matched pair × brood year, create a
   `dqv:QualityAnnotation` (see contract section 4) where the values differ beyond tolerance. Classify the
   explanation in this order:
   - (a) EFS vs total: the ratio to the PSC EFS is ≈1 while the ratio to PSC
     total spawners is ≈2;
   - (b) 2.x ages missing: the difference equals PSC Gilbert–Rich 43/53/63/64
     recruits;
   - (c) the total does not equal the sum of the source's own age columns;
   - (d) vintage: the PSC `run_size_type` is post-RSA or post-DBE for that year;
   - (e) aggregate membership;
   - (f) unexplained.

   The coordinator's checks give these expected results:
   - SASAP Fraser `TotalEscapement` = PSC EFS for 18 stocks and 1,155
     stock-years;
   - DFO 2014 vs PSC 2026 recruits: 597 agree, then 220 (b), 57 (c), 40 (d) and
     13 (f).
4. **Cross-dataset competency queries**, in `queries/corpus/NN-*.rq`, with CSV
   results. At least:
   - **CX1.** Every spawner or escapement measure in the corpus, from any source,
     whatever the column is called. Give the dataset, the column, the I-ADOPT
     object of interest and constraints, and the estimate type.
   - **CX2.** For one stock (Chilko), every abundance series from every source.
     Give the year span, the measure semantics and the agreement with the PSC
     reference.
   - **CX3.** Columns whose label says "total escapement" but whose decomposition
     says effective female spawners. Count the stock-years affected and the share
     of the compilation (expected about 44% of SASAP sockeye stock-years).
   - **CX4.** Discrepancies by explanation × source pair, with the count and the
     absolute gap.
   - **CX5.** Estimate-type composition of spawner records by decade, across
     sources, resolved through SSSOM.
   - **CX6.** The term-gap list across the whole corpus, ranked by the number of
     datasets and columns that need the term. This is the ontology term-request
     backlog.
5. **Demo export.** Write `graph/corpus-summary.json`:
   - triple counts per graph;
   - datasets;
   - stocks per authority;
   - crosswalk links by type;
   - discrepancies by explanation;
   - the top term gaps.

   Also write a static `graph/corpus.trig.gz`, so the corpus can be loaded
   anywhere (for example into an ODIS-style or Fuseki store).
6. Report, with demo notes: the 3–4 strongest cross-source facts with numbers,
   and the exact SPARQL to run them live. Demo rulings (Brett, 2026-10-23):
   - Do not show cube abundance values. The NuSEDS cube is a sum of stream
     `MAX_ESTIMATE` values, not CU abundance, so show coverage, estimate types,
     counts and discrepancies instead.
   - End monitoring trends at 2023, because 2024 may be incomplete. The NuSEDS
     result is a 47% fall in stream-level estimates from 1985 to 2023.
