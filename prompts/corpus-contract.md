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

**Roll-ups are not a hierarchy** (ADR-0001 D5). Never infer that a population
belongs to a CU, or a CU to an SMU, from names or geography alone. Membership
comes from a published source wherever one exists. The first is the DFO
SMU–CU–DU crosswalk (`dfo-pacific-science/Salmon-SMU-CU-DU-Crosswalk` on GitHub;
the official record is on Open Canada). Record each membership with its source,
the source's version, and the period it is valid for. If you propose a link that
no source publishes, mark it as agent-derived and critical (section 2a).

**Never hardcode the base IRI.** Build every instance IRI with `ident()` or from
`corpuslib.NS`. The base is provisional and will change (ADR-0001 D10).

## 2. Measures must say what was measured, not only what the column is called

The key lesson from the cloud probes: a column called `TotalEscapement` in a
multi-region compilation held **effective female spawners** for every Fraser
sockeye stock. So:

- **Decompose every abundance column with I-ADOPT.** The object of interest is
  spawners, recruits, catch or run. Then add the constraints: sex (female),
  "effective" (pre-spawn mortality removed), origin (natural / hatchery), and age
  class or jack inclusion.
- **Use smn/gcdfo IRIs only where they exist.** `VocabIndex` enforces this.
- **Never mint compound variables as shared terms** (Brett, 2026-10-23; smn
  ADR-0002 decision 6; smn `CONVENTIONS.md` "Keep compound dataset variables in
  profile/project SKOS"; gcdfo CONVENTIONS 2.3.4.1). Effective female spawners,
  recruits per spawner, recruits per EFS, recruits by age class, smolt and fry
  abundance, total return and similar column variables are **profile SKOS
  concepts**, optionally typed `iadopt:Variable`. Use gcdfo where the concept
  already exists there (NuSEDS-derived concepts belong in the gcdfo profile).
  Otherwise put it in the shared corpus scheme
  `<https://w3id.org/salmon-demo-corpus/scheme/variables>` (a `skos:ConceptScheme`).
  Decompose each concept into **atomic** parts: `iadopt:hasProperty
  smn:Abundance`, an object of interest, and constraints such as basis, sex,
  "effective" (pre-spawn mortality removed), origin, life stage and jack
  inclusion.
- **Only atomic constraints go to smn, as term requests.** When an atomic part
  has no smn/gcdfo term, write a term-request node for that atomic part only.
  Examples: female sex as a constraint, the effective (pre-spawn-mortality-adjusted)
  qualifier, jack. Never request the compound. The term requests feed the RDA WG
  list.
- **The PSC controlled vocabulary already defines four stock–recruit
  variables.** Use them where they fit, and say so in the report:
  `PSC-CV-000035` (effective female spawner abundance), `PSC-CV-000036` and
  `PSC-CV-000037` (freshwater age-1 and age-2 smolt abundance) and
  `PSC-CV-000038` (fry abundance estimate). Their IRIs are
  `https://w3id.org/psc/vocab/concept/<concept-id>`. Read the definitions in the PSC
  Salmon Vocabularies repo on this Mac (`~/code/psc-salmon-vocabularies`,
  read-only, `data/concepts.csv`) before you use one. Two warnings. EFS in
  PSC-CV-000035 is adjusted for eggs not spawned, so do not use it for an
  unadjusted female count. And a PSC canonical IRI always redirects to an HTML
  page; the machine-readable copy is the `.ttl` beside it. `smn:EuropeanAgeNotation`
  exists (the cloud probe's term search missed it), so check the ontology files
  as well as term search before declaring any gap.
- **Namespaces.** `def:` is not a home for definitions: any definition must come
  from smn/gcdfo or become an smn term request. Instance IRIs (stocks,
  observations, crosswalk and quality nodes) stay under the provisional base
  until ADR-0001 D10 is decided. w3id registration is optional for the demo. Say
  "provisional namespace" in every report.
- **Enumeration and estimate methods stay in gcdfo** (Brett, 2026-10-23;
  ADR-0001 D13). Use metasalmonpy's crosswalks, which map each NuSEDS method
  value to a specific gcdfo concept. Two estimate values (`Cumulative CPUE`,
  `Combined Methods`) are linked only to `gcdfo:EstimateMethod`, at scheme
  level; keep those as broad matches, as the crosswalk notes say. Do not add new
  scheme-level fallbacks, and never fall back to `smn:EnumerationMethod`.
  `gcdfo:EnumerationMethod` does not exist, so `Based on Angling Catch`, which
  the crosswalk maps to it, stays unmapped and is recorded as a gap. Hub item
  B-76 holds the open question of where the method branches hang. Map
  `Fence Count` (an `ESTIMATE_METHOD` value) to `gcdfo:FixedStationTally`. The
  values `NO SURVEY`, `Fence Count`, `Aerial Survey` and `Net` are in the data
  but missing from the crosswalks. Map them in the pipeline and record each
  workaround; the upstream change is paused. Keep gcdfo on `main`.
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

## 2a. Mark everything you derive (ADR-0001 D6)

Every assertion you make that a source does not state is agent-derived: a column
mapping, a decomposition, an identity link, a membership, a value mapping, a
discrepancy explanation. Mark each one, in the package's mapping or review
tables and in the graph, with:

- who asserted it (agent and model) and the run;
- the evidence (the source passage, the match statistics or the rule used);
- a **confidence**: `high`, `medium` or `low`;
- a **criticality**: `critical` or `non-critical`.

An assertion is **critical** if it can change a number or a join:

- identity equivalence or membership;
- what a measure counts (sex, the "effective" adjustment, origin, life stage,
  jack inclusion);
- unit or scale;
- year basis;
- age notation;
- estimate type;
- licence or access terms.

Labels, descriptions, keywords and documentation links are non-critical.

Only an assertion that is both `high` and `non-critical` is **agent-accepted**.
Everything else is **awaiting review**: list it in the report's review queue,
critical items first, each with its evidence and a one-line suggested decision.
Never describe an agent-derived assertion as verified or reviewed.

## 3. The `crosswalk` named graph (shared, rebuilt by `pipelines/corpus.py`)

- Use `skos:exactMatch` only when the numbers prove it: identical totals by
  brood year within 0.5% for at least 90% of years. Use `skos:closeMatch` for the
  same biological unit with different numbers, and `skos:narrowMatch` /
  `skos:broadMatch` for aggregates (for example PSC 5+25+26 or 8+15).
- Every crosswalk assertion is a reified node. It records who or what asserted
  it, the evidence (the match statistics), and the date. Write it in SSSOM terms
  where possible.
- Every crosswalk assertion is critical (section 2a), so an agent-derived one
  always awaits review, however strong the numbers are. A link published by a
  source (for example DFO's SMU–CU–DU crosswalk) is not agent-derived; cite the
  source and its version instead.

## 4. The `discrepancy` named graph (built by `pipelines/corpus.py`)

Record each cross-source difference with the W3C Data Quality Vocabulary
(`dqv:`, http://www.w3.org/ns/dqv#), not with corpus-minted classes. For each
source pair × stock × year where the values differ beyond tolerance, write a
`dqv:QualityAnnotation`. Its `oa:hasTarget` is the two observations, and its
`dqv:inDimension` is a concept from a small corpus SKOS scheme of explanation
classes (`<https://w3id.org/salmon-demo-corpus/scheme/discrepancy-explanations>`).
Also write a `dqv:QualityMeasurement` that holds the relative difference.
The explanation classes are:

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
