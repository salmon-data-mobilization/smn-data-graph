# Salmon data corpus: architecture (initial design, 2026-10-23)

This document describes the initial architecture of the salmon data corpus: what
exists, the design it is moving to, and why. It is written for people and agents
who will review and improve it. Decisions are recorded separately in
[ADR-0001](adr/0001-corpus-architecture.md). Where this document and an accepted
ADR disagree, the ADR wins and this document has a bug. §19 says how to review it.

Status words used below:
- **exists**: on `main` and working;
- **staged**: being built for PICES (Wed 28 Oct 2026);
- **planned**: after PICES;
- **proposed**: needs a decision.

---

## 1. Purpose and scope

Pacific salmon science keeps re-integrating the same open datasets by hand. Each
synthesis rebuilds its own stock crosswalks, guesses what each column counts,
and drops the context that would let the next team reuse the result. The salmon
data integration toolkit addresses the cause: Salmon Data Packages (SDPs), the
Salmon Domain Ontology (`smn:`), the DFO profile (`gcdfo:`), the PSC controlled
vocabulary, and metasalmon / metasalmonpy. This corpus is the toolkit applied at
scale. Agents package many open datasets once, give every column explicit
semantics, and compile the results into one queryable graph.

The corpus has four jobs (ADR-0001 D9):

1. **A working knowledge network.** It is a concrete step toward the North
   Pacific knowledge network BECI (Basin-scale Events to Coastal Impacts, PICES
   and NPAFC) designed, with salmon as the first species. It builds on BECI's
   framing and partnerships, and does not replace them.
2. **Evidence.** It tests whether describing data once lowers integration cost
   at scale, measured per dataset (§15).
3. **A test suite.** Every new dataset exercises the toolkit end to end and finds
   real defects. The first dataset found 13.
4. **A data layer.** It serves the high-probability open questions in the
   2026-10-23 report: compilation concordance, observability, status
   sensitivity, forecast calibration. It also serves sealed-evaluation work in
   tern.

**Out of scope:**
- the corpus is not a system of record;
- it holds no private or embargoed data;
- it does not rule on scientific equivalence;
- it does not replace any agency database.

## 2. What exists today (measured 2026-10-23)

| Item | State | Where |
|---|---|---|
| Agent harness on API credit | **exists** | `run_agent.py`, `corpus_auth.py`, `prompts/common.md` |
| Shared library | **exists** | `pipelines/corpuslib.py`: base IRI, `ident()`, `fetch_source()`, `VocabIndex` (IRI guard over gcdfo and smn), `G` graph builder, `dcat_dataset()`, `run_queries()` |
| PSF cleaned NuSEDS, end to end | **exists** | `pipelines/psf-nuseds-cleaned.py`; SDP validates with no structural or semantic issues; `graph/psf-nuseds-cleaned.trig`, 326,766 quads; store 329,727 quads with vocabularies; 7 competency queries in `queries/psf-nuseds-cleaned/`; report in `runs/20261023T015335Z-psf-nuseds-cleaned/` |
| Corpus contract and four dataset prompts | **exists** (PR #1, #2) | `prompts/corpus-contract.md`; `prompts/{psc-fraser-sr,sasap-sockeye-brood,dfo-rs-productivity,salmonprize-sockeye-2025,corpus}.md` |
| Cloud probe results (6 SDPs, 2 small graphs, EFS finding) | **exists outside this repo** | to be ported as dataset specs (§12.3) |
| Combined corpus graph, SHACL, releases, serving | **staged** | §§7–14 |

Cost and time of the first dataset: $5.27 and 34.6 minutes of agent time. A clean
rebuild from raw files takes about 6.5 minutes. The graph and query stages take
about 20 seconds.

## 3. Design principles

1. **Sources keep authority.** The corpus derives and never overrides. Every
   value traces to a pinned source release and checksum.
2. **Describe once, reuse everywhere.** Semantics are attached to the package,
   not rebuilt in each analysis.
3. **Never merge identities.** Equivalence is an assertion with evidence, held
   apart from the things it relates.
4. **Meaning comes from governed vocabularies.** No IRI is invented. Gaps are
   recorded and become term requests.
5. **Agents propose; review is proportional to risk.** Generated content is
   always marked. Critical claims need a person (§11).
6. **Derived and rebuildable.** Any release can be rebuilt byte for byte from
   pinned inputs and code.
7. **Two engines for two jobs.** SPARQL answers what something means and where
   it is. SQL over Parquet answers what the numbers are.
8. **Generic code belongs upstream.** If another project would need it, it goes
   to metasalmonpy/metasalmon (§12.1).

## 4. System context

| Component | Role in the corpus | Owner / home |
|---|---|---|
| Salmon Data Package spec (`smn-data-pkg`) | Exchange contract per dataset | salmon-data-mobilization |
| metasalmonpy / metasalmon | Build, seed, validate and publish SDPs; NuSEDS crosswalks; SSSOM; observation structures; KNB publication. Future home of the generic graph code | salmon-data-mobilization (mirror contract) |
| Salmon Domain Ontology (`smn:`) | Shared atomic semantics (abundance, year and age bases, procedures, notations) | salmon-data-mobilization (shared) |
| DFO Salmon Ontology (`gcdfo:`) | DFO profile: methods, estimate types, CU and SMU concepts | dfo-pacific-science (shared with DFO) |
| PSC Common Data Definitions | PSC profile: stock–recruit compound variables (PSC-CV-000035 to 000038), CTC stock schemes; reuses gcdfo methods | Pacific Salmon Commission (public GitLab) |
| Salmon Knowledge Commons | Source-backed concept cards: the rules behind integration hazards (age notation, jacks, estimate types, EFS); claims; ontology-gap register | salmon-data-mobilization |
| Salmon Science plugin | Agent front door: source adapters, term search, SDP review; gains a corpus-query skill (§13) | Br-Johnson/smn-sci-plgn |
| tern | Sealed, prospective evaluation of predictive questions, once its Salmon Prize slices land; consumes dated corpus tables | Symecology-Institute |
| KNB (DataONE), Zenodo, ODIS | Publication, DOIs, discovery (§14) | external |

## 5. Data flow

```
source (pinned URL, checksum, licence)
  └─ fetch    → data/raw/<slug>/ + SHA256SUMS + source.json
  └─ profile  → DuckDB profile in the run report
  └─ package  → packages/<slug>/  Salmon Data Package (metasalmonpy); validate
  └─ graph    → graph/<slug>.trig  per-dataset named graphs (§7)
  └─ shapes   → SHACL gate; build fails on violation            [staged]
  └─ combine  → graph/store/corpus/  one store; crosswalk + quality graphs  [staged]
  └─ release  → releases/<version>/  TriG.gz + Parquet + VoID + manifest  [staged]
  └─ publish  → KNB (golden path), Zenodo DOI, schema.org JSON-LD     [staged / planned]
  └─ serve    → read-only SPARQL; MCP / plugin skill (SPARQL + SQL)  [staged]
```

Each step reads only the outputs of the step before, so any one step can be
re-run. Dataset runs are independent. The combine step is the only one that
reads several datasets.

## 6. Namespaces and IRIs

### 6.1 Today

`corpuslib.BASE = https://w3id.org/salmon-demo-corpus/` is provisional and
unregistered. Under it, `id/` holds identity nodes and `def:` holds corpus
properties. From 2026-10-23, `def:` holds no definitions (ADR-0001 D4). It may
keep only structural corpus properties until those have homes.

### 6.2 Proposed: a reserved sub-tree of smn (ADR-0001 D10)

The question was: can corpus instance IRIs live in a sub-directory of the smn w3id
namespace? **Yes, technically,** with conditions. These come from the live rules
in `perma-id/w3id.org` at `ids/smn/.htaccess`, read on 2026-10-23.

- smn's rules resolve the ontology root, version paths, `research`,
  `rda-case-study`, `modules/<name>` and `profile/<name>/`, and then a catch-all
  for **single-segment** term IRIs, `^([A-Za-z0-9._-]+)/?$`.
- A multi-segment path such as `data/id/cu/dfo/SEL-21-02` matches none of these
  rules, so it currently returns 404 and cannot collide with a term. A
  `data/(.*)` rule placed before the catch-all would route it.
- `profile/<name>/` is already an smn pattern. That makes
  `https://w3id.org/smn/profile/corpus/` a natural home for the corpus profile
  SKOS scheme.

**Conditions:**

1. **A PR to perma-id/w3id.org** adding `data/` and `profile/corpus/` rules above
   the catch-all, and documenting both in `ids/smn/README.md`. Brett maintains
   the smn space.
2. **Never mint a single-segment instance IRI** (for example `smn/data` itself
   as a resource), because the term catch-all would capture it.
3. **Tools must treat the sub-trees as non-term.** `VocabIndex._check()`
   currently flags every IRI starting with `https://w3id.org/smn/` that the
   ontology does not declare. It must skip `smn/data/` and `smn/profile/corpus/`,
   or it will report hundreds of thousands of false gaps. metasalmon's IRI
   verification needs the same exclusion wherever it scans namespaces.
4. **Persistence.** An instance IRI, once published, is never reused for
   something else. A retired node keeps resolving to a tombstone.
   Version-specific things (dataset releases) carry the version in the path.
5. **Resolution targets.**
   - Identity and dataset nodes resolve to static pages and Turtle on the
     corpus's GitHub Pages site.
   - Observation IRIs resolve to their dataset release page, not one page per
     observation, because there are hundreds of thousands.
   - Machine formats follow smn's convention, `Accept`-based redirects, for
     consistency inside the smn space.
6. **Governance.** Publishing instance data under smn means the smn maintainers
   (the RDA working group) accept responsibility for those IRIs' persistence.
   That fits the move to the salmon-data-mobilization organisation (D2), but
   should be stated in the smn README.

**Proposed layout:**

```
https://w3id.org/smn/data/id/{kind}/{authority}/{local-id}     identity nodes
https://w3id.org/smn/data/dataset/{slug}/{version}             dataset releases
https://w3id.org/smn/data/obs/{slug}/{version}/{key}           observations
https://w3id.org/smn/data/xwalk/{mapping-set}/{n}              crosswalk assertions
https://w3id.org/smn/data/quality/{...}                        quality annotations
https://w3id.org/smn/data/selection/{name}/{version}           selection sets
https://w3id.org/smn/profile/corpus/{scheme}/{concept}         corpus profile SKOS
```

**Alternative:** a separate root (`https://w3id.org/salmon-data/`). It keeps
ontology terms (TBox) and instance data (ABox) in different namespaces and avoids
coupling the corpus to the ontology's governance, at the cost of a second w3id
registration. Either way, the base is a single constant in `salmongraph`, so the
choice does not block engineering.

### 6.3 Vocabulary IRIs and dereferencing

| Source | Pin used | Dereferencing |
|---|---|---|
| smn | git SHA of `salmon-domain-ontology.ttl` (flat build) | `Accept: text/turtle` on any term IRI returns the full `smn.ttl` |
| gcdfo | git SHA of `ontology/dfo-salmon.ttl` on `main` (Brett: stay on `main` for now) | `Accept: text/turtle` returns the full `gcdfo.ttl` |
| PSC CV | release tag (`v0.1.0-alpha.5`) | canonical IRIs **always** return `303` to HTML. Machine formats are at explicit IRIs: `…/concept/{id}.ttl`, `…/scheme/{id}.ttl`, `…/psc-vocabularies.ttl` |

The vocabulary loader therefore fetches the PSC CV from its explicit `.ttl` IRI
and does not rely on content negotiation. PSC's README documents this choice: it
avoids fragile `Accept` handling and keeps responses cacheable. The loader records
the pin, source URL and sha256 of every vocabulary in the provenance graph.

## 7. Graph model

### 7.1 Named graphs

Every dataset release contributes these graphs, each named under
`{base}dataset/{slug}/{version}/`:

| Graph | Contents |
|---|---|
| `metadata` | DCAT dataset and distributions, CSVW tables and columns, I-ADOPT variables, licence, attribution |
| `mappings` | Source codes as SKOS concepts and their SSSOM mappings to vocabularies |
| `identity` | Identity nodes this dataset mentions, with the source's own labels and keys |
| `cube` | RDF Data Cube (and SOSA) observations for aggregates worth querying in RDF |
| `provenance` | PROV-O build activity, inputs and checksums, tool versions, vocabulary pins |

The combine step adds the corpus-level graphs:

| Graph | Contents |
|---|---|
| `crosswalk` | Mapping assertions between identity nodes of different authorities, with evidence |
| `membership` | Roll-up and membership assertions from published identity sources (§8) |
| `quality` | DQV annotations: cross-source discrepancies, coverage, estimate-type mix |
| `review` | Agent-generation marks, confidence, criticality, review status (§11) |
| `vocab` | Pinned smn, gcdfo, PSC CV, corpus profile scheme |
| `void` | VoID + DCAT description of the corpus release and every graph |

### 7.2 Patterns

Prefixes are as in `corpuslib.NS`. `data:` stands for the instance base (§6) and
`corp:` for the corpus profile scheme.

**Dataset, distribution and provenance** (DCAT, PROV-O), as built today by
`dcat_dataset()`:

```turtle
data:dataset/psf-nuseds-cleaned/2026-02-20 a dcat:Dataset ;
  dcterms:title "Cleaned spawner survey data"@en ;
  dcterms:license <https://creativecommons.org/licenses/by/4.0/> ;
  owl:sameAs <https://doi.org/10.5281/zenodo.19959144> ;
  prov:wasDerivedFrom <https://doi.org/10.5281/zenodo.19959144> ;
  dcat:distribution data:dataset/psf-nuseds-cleaned/2026-02-20/dist/csv .
```

**Column and variable** (CSVW, I-ADOPT). The column is the source's own; the
variable is its decomposition:

```turtle
data:dataset/psc-fraser-sr/2026.05.07/table/sr_summary/column/total_broodyr_EFS
  a csvw:Column ; csvw:name "total_broodyr_EFS" ;
  sdpv:variable <https://w3id.org/psc/vocab/concept/PSC-CV-000035> .   # PSC compound variable
<https://w3id.org/psc/vocab/concept/PSC-CV-000035>
  iop:hasProperty smn:Abundance ;
  iop:hasObjectOfInterest smn:Stock ;
  iop:hasConstraint smn:BroodYearBasis, smn:SpawnerStageContext ,
                    corp:constraint/female , corp:constraint/effective .  # atomic gaps → smn term requests
```

The atomic gaps (female sex, the effective / unspawned-egg adjustment) are
exactly the ones PSC's own decomposition review recorded. They are filed as smn
term requests, and stand in the corpus profile until smn accepts them.

**Observation** (Data Cube plus SOSA), with measured uncertainty when the source
gives it:

```turtle
data:obs/psc-fraser-sr/2026.05.07/FRSK-07-1990-EFS
  a qb:Observation, sosa:Observation ;
  qb:dataSet data:dataset/psc-fraser-sr/2026.05.07 ;
  sdpv:stock data:id/stock/psc-frsk/7 ;
  smn:broodYear "1990"^^xsd:gYear ;
  sdpv:measure <https://w3id.org/psc/vocab/concept/PSC-CV-000035> ;
  sdpv:value 412345 ;
  sdpv:unit unit:NUM ;                                   # QUDT
  sdpv:estimateType gcdfo:… ;                            # when the source states it
  sdpv:standardError 23000 ; sdpv:cv 0.056 ;             # when given; never invented
  sosa:usedProcedure gcdfo:… .                           # method concept, when declared
```

`sdpv:` stands for the SDP vocabulary properties that metasalmonpy already uses.
Which of them belong in smn, in smn-data-pkg or in a corpus profile is an open
question (§18).

**Crosswalk assertion with statement-level provenance** (RDF 1.2 reifier,
supported by pyoxigraph 0.5.13):

```turtle
data:id/stock/sasap/107 skos:closeMatch data:id/stock/psc-frsk/7 .
data:xwalk/sasap-psc-fraser/7 rdf:reifies <<( data:id/stock/sasap/107 skos:closeMatch data:id/stock/psc-frsk/7 )>> ;
  sssom:mapping_justification semapv:ManualMappingCuration ;
  sssom:confidence 0.98 ;
  prov:wasAttributedTo data:agent/claude-corpus-run/20261024T… ;
  corp:criticality corp:critical ;
  corp:reviewStatus corp:awaitingReview ;
  dcterms:description "Same production stock; totals agree within 0.5% for 66/68 brood years against PSC EFS." .
```

**Quality annotation** (W3C DQV):

```turtle
data:quality/efs-vs-total/sasap-107-1990 a dqv:QualityAnnotation ;
  oa:hasTarget data:obs/sasap-sockeye-brood/2019/107-1990-esc, data:obs/psc-fraser-sr/2026.05.07/FRSK-07-1990-EFS ;
  dqv:inDimension corp:discrepancy/efs-vs-total ;
  oa:hasBody "SASAP TotalEscapement equals PSC effective female spawners (ratio 1.00); not total spawners (ratio 0.53)."@en .
```

**Membership** (from a published source) and **selection set** (for one
analysis):

```turtle
data:membership/dfo-smu-cu/2025-11-28/CK-01 rdf:reifies <<( data:id/cu/dfo/CK-01 skos:broader data:id/smu/dfo/CK-FIA-01 )>> ;
  dcterms:source <https://github.com/dfo-pacific-science/Salmon-SMU-CU-DU-Crosswalk> ;
  pav:version "2025-11-28" ; corp:validFrom "2025-11-28"^^xsd:date .

data:selection/fraser-sockeye-sr-reference/2026-10 a corp:SelectionSet ;
  corp:includes data:id/stock/psc-frsk/7 ;
  corp:excludes [ corp:unit data:id/stock/psc-frsk/19 ; corp:rationale "aggregate definition differs between sources" ] .
```

The corpus profile terms shown (`corp:criticality`, `corp:SelectionSet` and so
on) are placeholders for the profile scheme. Each one must be checked against
existing vocabularies (PROV, DQV, PAV, SSSOM, VoID, schema.org) before it is
minted. Prefer reuse.

## 8. Identity model

Fisheries identities are not a clean hierarchy. The same fish can sit in a CU, an
SMU, a PSC production stock, a fishery-management aggregate and a
compilation-local "stock". Roll-ups change over time, and a scientific question
may need to omit units for reasons that have nothing to do with the hierarchy:
hatchery influence, a changed survey method, an aggregate definition. The model
therefore has four layers.

1. **Authority nodes.** One node per unit per authority:
   `data:id/{kind}/{authority}/{local-id}`. Each carries:
   - the source's label, verbatim;
   - the source's key;
   - species (NCBITaxon);
   - region where the source states it;
   - `dcterms:source`.
   Nodes are never merged.
2. **Published membership.** Roll-up assertions ingested from authoritative
   published sources, each with source, version and validity period. Sources in
   order of adoption:
   - **DFO SMU–CU–DU crosswalk**: 483 rows, LinkML schema, dated versions;
     Open Canada official record; to be superseded by DFO Salmon Space via API.
   - **PSC Fraser production stock definitions**, from the PSC stock–recruit
     documentation.
   - **NOAA ESU/DPS population lists**: SPS and TRT populations.
   - **ADF&G stock lists** where published.
   - **PSC Chinook Technical Committee** stock and fishery registers, as the CTC
     publishes them; Brett is working on this with the CTC.

   A membership assertion is never inferred transitively without saying so.
3. **Crosswalks.** Equivalence and near-equivalence between nodes of different
   authorities, as SSSOM-style assertions:
   - `skos:exactMatch` only when the numbers prove it (identical totals within
     0.5% for at least 90% of shared years);
   - `skos:closeMatch` for the same biological unit with different numbers;
   - `broadMatch` / `narrowMatch` for aggregates.

   Each assertion has evidence, a confidence and a criticality, and is reified
   (§7.2). Crosswalks from published sources are preferred over agent-derived
   ones.
4. **Selection sets.** A named, versioned set of units for an analysis, with a
   rationale for each inclusion or exclusion. Selection sets are how a question
   can omit a stock without falsifying the identity graph.

**Identity as a product (planned).** Layers 1–3 are reusable well beyond this
corpus. They should become a governed, versioned identity registry that the
corpus, the Salmon Science plugin, the commons and the CTC tooling all consume.
That registry is either a sub-product of this repository or its own repository in
salmon-data-mobilization. This is the plugin's top-rated (P0) gap. Its review
burden is the main human cost of the whole system (§11).

## 9. Semantics and vocabulary layering

- **Layering.**
  - Atomic, reusable semantics come from smn.
  - DFO operational semantics (methods, estimate types, CU and SMU concepts)
    come from gcdfo.
  - PSC compound variables and CTC schemes come from the PSC CV.
  - Anything else goes in the corpus profile scheme until a proper home exists.
- **Compound variables are profile SKOS**, decomposed with I-ADOPT into atomic
  parts. Only missing atomic parts become smn term requests (smn ADR-0002
  decision 6).
- **NuSEDS method values** map to specific gcdfo method concepts. Where a method
  family's parent should sit (gcdfo, or an smn parent) is hub item B-76
  (ADR-0001 D13).
- **The guard** (`VocabIndex`) loads smn, gcdfo and the PSC CV at their pins. It
  refuses any IRI in those namespaces that the pinned source does not declare,
  and excludes the corpus instance and profile sub-trees (§6.2).
- **Term search.** metasalmonpy's `find_terms()` has no PSC source today. Until
  one is added upstream, dataset runs consult the PSC CV through the guard's
  loaded graph, so they do not report PSC-defined concepts as gaps.
- **Gaps become requests.** Each gap is recorded once, with:
  - the columns and datasets that need it;
  - what a term would have to say;
  - where it should be minted.

  The commons ontology-gap register and metasalmon's
  `detect_semantic_term_gaps()` → `render_ontology_term_request()` pipeline are
  the routes. The corpus produces a ranked backlog of these requests for the RDA
  working group.

## 10. Validation

SHACL shapes (`shapes/`, staged) encode the corpus contract. The build fails on a
violation. Initial shapes:

| Shape | Rule |
|---|---|
| Abundance columns | Every column whose variable has property `smn:Abundance` declares an object of interest, a year basis, a unit, and its constraints (sex, the effective adjustment, origin, life stage, jacks) where the source documents them |
| Age-class columns | Declare an age notation (`smn:GilbertRichAgeNotation` or `smn:EuropeanAgeNotation`) |
| Observations | Have a dataset, a measure, a value, a unit and every dimension of their data structure; uncertainty properties are numeric and non-negative |
| Estimates | Carry an estimate type where the source states one |
| Datasets | Carry a licence, attribution, a source checksum and a release version |
| Crosswalk and membership assertions | Are reified with evidence, a justification, a confidence and a criticality |
| Agent-generated assertions | Carry agent, activity, date, confidence and criticality, and a review status consistent with §11 |
| Vocabulary IRIs | Every smn, gcdfo or PSC IRI exists at the pin. This is enforced by the guard as well as by the shapes |

pyshacl (0.40.1, on rdflib) validates the graphs without RDF 1.2 triple terms.
Shapes over reifier nodes validate the reifier's properties, not the triple term
inside it.

## 11. Agent-derived content and review (ADR-0001 D6)

Every agent-generated assertion carries:
- `prov:wasAttributedTo` (agent and model);
- `prov:wasGeneratedBy` (run activity, date);
- its evidence;
- `corp:confidence` (`high`, `medium`, `low`);
- `corp:criticality` (`critical`, `non-critical`);
- `corp:reviewStatus`:
  - `agentAccepted`: only for high-confidence and non-critical;
  - `awaitingReview`;
  - `humanAccepted`, `humanAmended`, `rejected`, with reviewer and date.

**Critical** means it can change a number or a join:
- identity equivalence or membership;
- what a measure counts;
- unit or scale;
- year basis;
- age notation;
- estimate type;
- licence or access.

**Non-critical** examples are labels, descriptions, keywords and documentation
links.

Reviewed and unreviewed content live in the same graphs and are told apart by
status. Every query exposed through the agent endpoint and every release offers
two views:
- the **reviewed view**: only `humanAccepted` or `humanAmended`, plus
  `agentAccepted`;
- the **full view**: everything, with status shown.

Review is batched. A queue lists each pending item with its evidence and a
one-line suggested decision, sorted by criticality and by how many downstream
joins depend on it. Brett, or a named steward, records decisions as data. That is
the lever on the main human cost.

## 12. Weaknesses identified on 2026-10-23 and their remedies

| # | Weakness | Remedy | When |
|---|---|---|---|
| 1 | Generic code (`corpuslib.py`, compile, crosswalk and quality logic) lives in a demo repository, so it risks becoming a second implementation beside metasalmon | Stage it in `salmongraph/` with clean interfaces and tests. Open hub items to move it into metasalmonpy (and metasalmon by mirror) | staged; upstream planned |
| 2 | The contract is prose, not checks | SHACL shapes and a failing build (§10) | staged |
| 3 | About 1,000 lines of agent-written code per dataset; conventions will drift at 50 datasets | Declarative dataset specs plus a shared executor (§12.3); bespoke parsing only behind the executor's interface | staged for new datasets |
| 4 | Identity is unowned and rebuilt in each run | Identity layers and published sources (§8); identity registry as a product | staged (DFO SMU–CU–DU first); product planned |
| 5 | Namespace and ownership undecided | Home decided (D2); namespace proposal (D10, §6.2) | decision pending |
| 6 | Ontology coverage is narrow (DFO- and BC-centric; 56% of Salmon Prize columns resolved only to local terms) | PSC CV in the guard; ranked term-request backlog per release (§9); profile schemes as interim homes | staged |

### 12.1 Upstreaming plan

`salmongraph/` modules map onto future metasalmonpy modules:

| `salmongraph/` | metasalmonpy (future) |
|---|---|
| `compile.py` (SDP → RDF) | `graph_compile.py` |
| `vocab.py` (guard, pins, PSC loader) | `ontology_fetch.py` extension |
| `shapes/` | package data |
| `crosswalk.py`, `quality.py` | `graph_crosswalk.py` |
| `release.py` | `graph_release.py` |

Each move is a hub queue item and follows the mirror contract. The R port is
behavioural, not literal, and differences are recorded in PARITY.md and
`knowledge/parity-deviations.md`.

### 12.2 PSC controlled vocabulary findings (2026-10-23)

| Finding | Result | Action |
|---|---|---|
| All 28 mapping-set targets and 22 directly reused gcdfo concepts exist in the pinned and current gcdfo/smn | pass | none |
| IRI resolution: canonical `303` to HTML; explicit `.ttl` / `.jsonld` IRIs return 200 | pass, by design | loader uses explicit IRIs (§6.3) |
| Toolchain does not use the PSC CV (no PSC source in term search; guard loads only gcdfo/smn) | fault | guard loads the PSC CV (staged); hub item for a PSC term-search source |
| PSC pins lag `main` (gcdfo 0.0.8 vs 0.0.9; smn `f7205ee`) | drift | re-pin in the PSC repository after B-76 is ruled, because the ruling changes the 9 `psc-to-smn` rows |
| smn's alignment note says PSC refuses smn mappings | stale | correct the note in salmon-domain-ontology |

### 12.3 Dataset specification (staged)

A dataset spec (`specs/<slug>.yaml`) declares:
- source URLs, checksums, licence, attribution and version;
- tables and their keys;
- for each column: its role (identifier, dimension, measure, attribute), its
  vocabulary concept or decomposition, its unit, and any uncertainty column it
  pairs with;
- identity keys and the authority they belong to;
- measures and dimensions for the Data Cube;
- expected cross-source checks, so the combine step knows what to test.

The shared executor turns a spec into an SDP, dataset graphs, Parquet and a run
report. Agents write and justify specs and mapping reviews; the executor, not the
agent, writes the RDF. The cloud probes' datasets are ported first: PSC Fraser SR,
SASAP sockeye brood tables, DFO recruits-per-spawner and Salmon Prize 2025.

## 13. Query and agent access

| Need | Engine |
|---|---|
| Meaning and location (which columns measure spawner abundance, whatever they are called; which units a dataset covers; what an estimate type means) | SPARQL over the combined store |
| Numbers (series, sums, joins on values) | DuckDB over Parquet keyed by the same IRIs |
| Both, for agents | MCP server and plugin skill (`corpus-query`): `sparql(query)`, `sql(query)`, `describe(iri)`, `datasets()`, `review_queue()`; reviewed and full views selectable |

**Example cross-dataset questions** (the CX1–CX6 queries in
`prompts/corpus.md`):
- every spawner or escapement measure from any source, with its semantics;
- every abundance series for one stock, with agreement against the reference;
- columns whose label says total escapement but whose decomposition says
  effective female spawners;
- discrepancies by explanation;
- estimate-type mix by decade;
- the term-gap backlog.

## 14. Publication and serving (ADR-0001 D8)

| Channel | What | Status |
|---|---|---|
| KNB (DataONE), the golden path | Each SDP, through metasalmon's KNB publication functions, and each corpus release with EML | staged (credentials on Brett's Mac) |
| Zenodo | Corpus releases with DOIs: TriG.gz, Parquet, VoID, manifest; PICES WG52 protocol | staged |
| schema.org JSON-LD | One `schema:Dataset` per dataset, `variableMeasured` pointing to vocabulary IRIs, for ODIS harvesting | staged |
| SPARQL | Read-only Oxigraph server over the release store for the demo; QLever if size requires | staged (local) |
| GitHub Pages | Static pages and Turtle for identity and dataset IRIs (§6.2) | planned |

Every release is versioned and immutable. A release's manifest lists every file
with its sha256, the input pins, the tool versions and the review-status counts.

## 15. Build, reproducibility and the run ledger

- Every dataset build is deterministic from `data/raw/<slug>/` (checksummed),
  the dataset spec, and pinned tool and vocabulary versions.
- Each run appends one row per dataset to `runs/ledger.csv` (staged), with these
  columns:
  - run id, dataset, tool versions;
  - agent cost, agent wall time, human review minutes;
  - number of breakages by kind (toolkit defect, vocabulary gap, retrieval miss,
    source problem);
  - term requests, discrepancies found, SHACL violations at first build.
- The ledger is the evidence for job 2 in §1. It should be published with each
  release.

## 16. Licensing and redistribution

- Each dataset's licence and attribution are carried in its package, graph and
  release.
- Derived graphs inherit the most restrictive applicable terms.
- Datasets with unconfirmed redistribution terms (the Salmon Prize packs, where
  the repository is GPL-3.0 and no data licence is stated) are built locally and
  left out of public releases until confirmed.
- Discrepancy findings about a colleague's compilation are shared with its
  custodians before they are presented. They are framed as what the toolkit
  surfaced, never as an error in their work.

## 17. Plan

**Before PICES (by Tue 27 Oct):**
- the `salmongraph/` package with the combined store, VoID/DCAT, release builder
  and reifier provenance;
- SHACL shapes and a failing build;
- the PSC CV in the guard;
- identity layer 2 from the DFO SMU–CU–DU crosswalk;
- dataset specs and the executor, with the four probe datasets ported;
- the combine step with crosswalk and quality graphs;
- the MCP server and plugin skill;
- a local read-only SPARQL endpoint;
- schema.org JSON-LD;
- release packaging for KNB and Zenodo, with the uploads run by Brett;
- this ADR and design;
- the run ledger.

**After PICES:**
- upstream moves into metasalmonpy/metasalmon;
- the identity registry as a product;
- the w3id PR (once D10 is accepted) and GitHub Pages resolution;
- a PSC term-search source in metasalmonpy;
- the B-76 ruling and the PSC re-pin;
- more datasets (NOAA SPS, NPAFC PSDLD and statistics, IYS, SASAP ASL, ocean
  indices);
- tern cases built on corpus tables.

## 18. Open questions

1. **Namespace.** smn sub-tree or a separate root (§6.2)?
2. **Repository name and visibility** after the move to salmon-data-mobilization.
3. **SDP vocabulary properties** (`sdpv:`). Which belong in smn, in smn-data-pkg,
   or in a corpus profile?
4. **Method placement** (B-76): where the gcdfo method branches hang, and the
   fate of `smn:EnumerationMethod`.
5. **Stewards.** Who reviews critical identity and measure-semantics assertions
   besides Brett?
6. **Salmon Space.** When DFO's Salmon Space API supersedes the GitHub crosswalk,
   does the corpus pin API snapshots, and how are they archived?
7. **Selection sets.** Should they live in the identity registry or in each
   analysis?

## 19. How to review this design

Reviewers, whether people or agents, should check these, citing files and lines:

1. **Join correctness.** Can the identity model (§8) produce a wrong join without
   any shape or status catching it? Name the path.
2. **Silent semantic loss.** Can a measure's meaning (sex, the effective
   adjustment, origin, life stage, jacks, year basis, age notation, estimate type,
   unit) be lost between source, SDP, graph and query result? Where?
3. **Vocabulary discipline.** Does any proposed corpus term duplicate PROV, DQV,
   PAV, SSSOM, VoID, schema.org, SOSA, I-ADOPT, smn, gcdfo or the PSC CV?
4. **Namespace safety.** Can any proposed IRI pattern collide with smn's rules,
   break persistence, or be mistaken for a term by existing tools?
5. **Reproducibility.** Can a release be rebuilt byte for byte? What is not
   pinned?
6. **Review load.** Will the D6 policy put too much or too little in front of a
   person? What would you change?
7. **Upstream fit.** Does `salmongraph/` duplicate or contradict anything
   metasalmonpy already does (`write_sdp_sssom`, `observation_structures`,
   `measurement_decompositions`, `write_sdp_semantic_closure`, `dwc_dp_export`,
   `publish_sdp_to_knb`)?
8. **Scale.** What breaks first at 50 datasets and 10 million observations?

Record findings as issues or PR comments in this repository, each with its
section number.
