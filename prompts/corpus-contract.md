# Corpus contract: rules every dataset pipeline follows so the graphs join

This extends `prompts/common.md`. It exists because the next datasets describe
the **same fish** in different ways, and the demo depends on the corpus graph
showing where they agree, where they differ, and why. Read it before you start a
dataset that shares stocks with one already in the corpus.

## 1. Identity nodes, by authority (never merge two authorities' nodes)

Use `corpuslib.ident(kind, authority, local_id)`. Each source keeps its own node.
Equivalence lives only in the `crosswalk` graph (section 3).

| Thing | Pattern | Example |
|---|---|---|
| Fraser sockeye production stock (canonical for Fraser SR data) | `ident("stock", "psc-frsk", <production_stock_code>)` | `.../id/stock/psc-frsk/7` (Chilko) |
| SASAP brood-table stock | `ident("stock", "sasap", <Stock.ID>)` | `.../id/stock/sasap/102` |
| DFO R/S time series | `ident("stock", "dfo-rs", <series id or CU + unit>)` | |
| Salmon Prize stock | `ident("stock", "salmonprize", <System>-<River>)` | `.../id/stock/salmonprize/fraser-chilko` |
| PSF / DFO CU, NuSEDS population, stream | as in the `psf-nuseds-cleaned` pipeline | `.../id/cu/psf/<CUID>` |

Every stock node gets `rdfs:label` (the source's own name, verbatim),
`dcterms:source` (the dataset IRI), the species (NCBITaxon), and region or
jurisdiction where the source states it.

## 2. Measures must say what was measured, not only what the column is called

The key lesson from the cloud probes: a column called `TotalEscapement` in a
multi-region compilation held **effective female spawners** for every Fraser
sockeye stock. So:

- **Decompose every abundance column with I-ADOPT.** The object of interest is
  spawners, recruits, catch or run. Then add the constraints: sex (female),
  "effective" (pre-spawn mortality removed), origin (natural / hatchery), and age
  class or jack inclusion.
- **Use smn/gcdfo IRIs only where they exist.** `VocabIndex` enforces this. For
  the known gaps, mint the term under `def:` and also write a `def:TermGap` node:
  effective female spawners, recruits per spawner, recruits per effective female
  spawner, recruits by age class, smolt abundance, fry abundance, jack,
  production stock group. The term gaps feed the ontology term-request list.
  (`smn:EuropeanAgeNotation` does exist; the cloud probe's term search missed it,
  so check the ontology file as well as term search before declaring a gap.)
- **Make the age notation explicit on every age-class column.** Use
  `smn:GilbertRichAgeNotation` for PSC Fraser `age` codes (21, 31, 32, 41, 42,
  43, 51, 52, 53, 62, 63, 64, 72) and `smn:EuropeanAgeNotation` for `a.b`. Store
  the mapping as data: Gilbert–Rich `Nb` → European `(b-1).(N-b)`. Reading
  Gilbert–Rich codes as European misassigns 100% of age cells.
- **Make the year basis explicit:** brood year or return year (`smn:broodYear`
  and `smn:returnYear` both exist).
- **Keep vintage and estimation type visible.** PSC `run_size_type`
  (historical / post-RSA / post-DBE / in-season-based), DFO estimate
  classification, the dataset version, and the extract date.

## 3. The `crosswalk` named graph (shared, rebuilt by `pipelines/corpus.py`)

- Use `skos:exactMatch` only when the numbers prove it: identical totals by
  brood year within 0.5% for at least 90% of years. Use `skos:closeMatch` for the
  same biological unit with different numbers, and `skos:narrowMatch` /
  `skos:broadMatch` for aggregates (for example PSC 5+25+26 or 8+15).
- Every crosswalk assertion is a reified node. It records who or what asserted
  it, the evidence (the match statistics), and the date. Write it in SSSOM terms
  where possible.

## 4. The `discrepancy` named graph (built by `pipelines/corpus.py`)

A `def:Discrepancy` node exists for each source pair × stock × year where the
values differ beyond tolerance. It carries `def:valueA`, `def:valueB`,
`def:sourceA`, `def:sourceB` and `def:explanation`, chosen from a controlled list:

- spawner measure differs: EFS vs total
- age classes missing
- total ≠ sum of own age classes
- vintage / run-size revision
- aggregate membership
- unexplained

These nodes are the demo's evidence that the toolkit makes hidden semantic
differences visible.

## 5. What every dataset report must add

Add a "cross-source expectations" section. List the stocks this dataset shares
with datasets already in the corpus, and the checks `corpus.py` should run on
them.

## 6. Parallel runs

Several dataset runs may go at once. Your run folder is the newest
`runs/<timestamp>-<your slug>` folder (its name ends with your slug) that has no
`report.md`. Do not use another dataset's folder. Write only under your own
slug's paths, plus `runs/<your run>/`.
