# ADR-0001: Architecture and governance of the salmon data corpus

- **Status:** decisions D1–D9 and D11–D12 **accepted** (Brett Johnson, 2026-10-23).
  D10 (namespace) is **proposed**. D13 (method placement) **defers** to hub item
  B-76.
- **Date:** 2026-10-23
- **Deciders:** Brett Johnson. This record was drafted by a Claude Code session
  from Brett's written rulings in that session.
- **Long-form design:** [`docs/architecture.md`](../architecture.md). This ADR
  records decisions; the design document explains them and is the thing to
  review and improve.

## Context

This repository started on 2026-10-22 as a demo for Brett's PICES-2026 S12 talk,
"The salmon data integration toolkit" (Nanaimo, Wed 28 Oct 2026). Its first run
turned PSF's cleaned NuSEDS into a validated Salmon Data Package (SDP) and a
330k-quad graph for about $5 of API credit. Cloud probes packaged five more open
datasets and found cross-source problems no single dataset shows: SASAP's merged
brood tables label PSC effective female spawners as "total escapement" for 18
Fraser stocks. That probe work is not yet in this repository.

The work now has three uses beyond the demo. It is the first working instance of
an agent-built, standards-based salmon knowledge graph, the "Salmon Knowledge
Portal" Brett proposed in Anchorage (Nov 2025, Zenodo 10.5281/zenodo.17783407).
It is the first evidence on whether describing data once lowers integration cost
at scale. And it is a standing integration test of the toolkit: the first run
alone found 13 metasalmonpy problems. A review on 2026-10-23 found six weaknesses
that would hurt as the corpus grows (architecture.md §12). Brett asked that all of
them be addressed, with the decisions below, before PICES where possible.

## Decisions

### D1. Purpose

The corpus is a **reproducible, governed integration layer** over openly published
salmon datasets. It is not a new central database. Sources keep authority. The
Salmon Data Package is the exchange contract, and the graph is a derived index
that can be rebuilt from pinned sources at any time.

### D2. Home

The work moves to the RDA **salmon-data-mobilization** GitHub organisation, next
to metasalmon, metasalmonpy, smn-data-pkg, the Salmon Domain Ontology and the
Knowledge Commons. It contains no PSC-private data, code or credentials. Each
source's licence travels with its package and graph. A source whose redistribution
terms are unconfirmed (for example the Salmon Prize packs) stays out of public
releases until confirmed.

### D3. Generic code moves upstream

These are toolkit features, not corpus features:

- the SDP→RDF compiler;
- the vocabulary IRI guard;
- SHACL validation;
- crosswalk and quality-annotation builders;
- release packaging;
- serving.

They are staged here in the `salmongraph/` package, written so they can move into
metasalmonpy (and metasalmon under the mirror contract) after PICES through the
hub's queue. This repository keeps:

- dataset specifications;
- dataset-specific parsers, only where unavoidable;
- releases;
- competency queries;
- run reports.

### D4. Semantics

- The Salmon Domain Ontology (`smn:`), the DFO profile (`gcdfo:`) and the PSC
  controlled vocabulary (`https://w3id.org/psc/vocab/`) are semantic contracts.
  Every IRI they contribute must exist in the pinned source; the guard enforces
  this for all three.
- Compound dataset variables (effective female spawners, recruits per spawner,
  recruits by age, smolt and fry abundance and the like) are **profile SKOS
  concepts**. That means gcdfo for DFO/NuSEDS concepts, the PSC CV where PSC
  already defines one (PSC-CV-000035 to 000038), and otherwise the corpus
  profile scheme. Each concept is decomposed with I-ADOPT into atomic parts.
- Only atomic constraints become smn term requests (smn ADR-0002 decision 6; smn
  `CONVENTIONS.md`; gcdfo CONVENTIONS 2.3.4.1).
- No definition is minted under a corpus-local `def:` namespace.

### D5. Identity is the spine, and it is not a hierarchy

- Every authority keeps its own identity nodes (PSC production stock, DFO CU,
  SMU, DU, NuSEDS population and stream, SASAP stock, NOAA population, ADF&G
  stock, compilation-local IDs).
- Equivalence lives only in a separate **crosswalk** graph, as SSSOM-style
  mapping assertions with evidence.
- Membership and roll-ups (CU→SMU, population→CU, stock→aggregate) are
  **membership assertions** from published sources, each with its source,
  version and valid-from/valid-to period. They are never inferred as a single
  hierarchy.
- Analyses that include or exclude units for scientific reasons use **selection
  sets**: named, versioned, with a rationale per inclusion or exclusion.
- Published sources come first: the DFO SMU–CU–DU crosswalk (Open Canada; GitHub
  `dfo-pacific-science/Salmon-SMU-CU-DU-Crosswalk`, to be superseded by DFO
  Salmon Space), PSC Fraser production stock definitions, NOAA ESU/DPS
  population lists, ADF&G stock lists, and the PSC Chinook Technical Committee's
  stock and fishery registers as they are published.
- Agents may propose links where no source publishes one, under D6.

### D6. Agent-derived content and review

Every assertion an agent generates is marked as such. The mark records:

- the agent and model;
- the activity and date;
- the evidence;
- a **confidence** (`high`, `medium`, `low`);
- a **criticality** (`critical`, `non-critical`).

An assertion is **critical** when it can change a number or a join:

- identity equivalence or membership;
- what a measure counts (sex, the "effective" adjustment, origin, life stage,
  jack inclusion);
- unit or scale;
- year basis;
- age notation;
- estimate type;
- licence or access terms.

Only high-confidence, non-critical assertions are **agent-accepted**. They are
used, and stay marked as agent-generated. Everything else goes to a human review
queue and is excluded from released "reviewed" views until a person accepts it.
The status is visible in every release and query result.

### D7. Storage and query

- The store is a hybrid:
  - RDF in pyoxigraph for metadata, semantics, identity, crosswalks, provenance,
    quality annotations and Data Cube summaries;
  - row-level data in Parquet keyed by the same IRIs, queried with DuckDB.
- There is one combined store with one named graph per dataset release, described
  with VoID and DCAT.
- Statement-level provenance on crosswalk, membership and quality edges uses RDF
  1.2 reifiers (`rdf:reifies` with a triple term). pyoxigraph 0.5.13 supports
  this; tested 2026-10-23.
- A SHACL gate (pyshacl) fails the build on contract violations.
- Units use QUDT. Uncertainty (standard error, CV, confidence bounds) is modelled
  explicitly. Observations align with SOSA alongside RDF Data Cube, as smn's own
  Fraser example does.

### D8. Publication and serving

- **Golden path:** the KNB (DataONE) repository, for Salmon Data Packages and
  corpus releases, through metasalmon's KNB publication functions.
- **Zenodo:** versioned releases with DOIs, consistent with the PICES WG52
  repository protocol.
- **schema.org JSON-LD** per dataset, for ODIS harvesting.
- **SPARQL:** a read-only Oxigraph endpoint for the demo and early use, with
  QLever if scale requires.
- **Agent access:** an agent-facing endpoint, as an MCP server and a Salmon
  Science plugin skill, that exposes SPARQL ("what does this mean and where is
  it") and SQL over Parquet ("give me the numbers").

### D9. Framing

The corpus is presented as four things at once:

1. a working step toward the North Pacific knowledge network that BECI set out
   to build, credited as building on BECI's design and partnerships;
2. evidence for or against the claim that describing data once lowers
   integration cost;
3. a standing integration test suite for the toolkit;
4. the data layer that sealed-evaluation work (tern) and the open questions in
   the 2026-10-23 report need.

### D10. Namespace (proposed)

Instance IRIs go under a reserved sub-tree of the smn namespace:

- `https://w3id.org/smn/data/` for identity nodes, datasets, observations,
  crosswalk and quality nodes;
- `https://w3id.org/smn/profile/corpus/` for the corpus profile SKOS scheme. This
  follows smn's existing `profile/<name>/` pattern.

This needs a perma-id/w3id.org pull request adding rules for those sub-trees ahead
of smn's term catch-all, and the IRI guard must treat both sub-trees as non-term
IRIs. architecture.md §6 gives the conditions, the persistence rules and the
alternative (a separate `w3id.org/salmon-data/` root). Until D10 is accepted, the
base IRI is configurable and the provisional base stays in use.

### D11. Dataset onboarding

A new dataset is described by a **declarative dataset specification** (YAML):

- source and licence;
- files;
- column semantics and I-ADOPT decompositions;
- identity keys;
- measures and dimensions;
- expected cross-source checks.

Shared code executes the specification. Agents write and justify specifications
and their mapping reviews. Per-dataset Python is allowed only for genuinely
bespoke parsing, and lives behind the same interface. The NuSEDS pipeline keeps
working as written and is migrated later.

### D12. Measure the hypothesis

Every dataset run records the following in a machine-readable run ledger:

- cost;
- wall time;
- human review time;
- breakages (toolkit defects, vocabulary gaps, retrieval misses);
- term requests;
- cross-source discrepancies found.

This is the evidence for D9's second claim.

### D13. Enumeration and estimate methods

On 2026-10-23 Brett stated that enumeration and estimate methods were developed in
gcdfo and should stay there. The open choice is recorded in hub item B-76: where
gcdfo's method branches hang, and whether `smn:EnumerationMethod` stays the
shared parent. B-148, which is blocked on B-76, records the related failure. Until
B-76 is ruled, the corpus maps NuSEDS method values to the **specific gcdfo
concepts**. The one value with no specific concept ("Based on Angling Catch")
maps to nothing and is recorded as a gap.

## Consequences

- **Positive.**
  - The work has a public, community home.
  - The graph joins across datasets without merging identities.
  - Every number in a query result can be traced to its source release, the
    semantics it was given, and who or what asserted them.
  - Review effort goes where errors would matter.
- **Costs.**
  - Each dataset release is heavier: shapes, ledgers, reifiers.
  - Upstreaming needs hub items and mirror work in two languages.
  - The namespace PR depends on perma-id review time.
  - Selection sets add a concept people must learn.
- **Risks.**
  - Crosswalk and measure-semantics review still lands mostly on Brett until
    stewards are named.
  - DFO's move from the GitHub crosswalk to Salmon Space changes the identity
    source.
  - Source licences vary, and a mistake in redistribution is public and
    permanent.

## References

- 2026-10-23 decisions and review: the Claude Code session, recorded in this ADR.
- smn ADR-0002; smn `CONVENTIONS.md`; gcdfo CONVENTIONS 2.3.4.1.
- Hub queue items B-76 and B-148 (metasalmon `queue/items/`).
- PSC Common Data Definitions v0.1.0-alpha.5, `https://w3id.org/psc/vocab/`.
- DFO SMU–CU–DU crosswalk:
  `https://github.com/dfo-pacific-science/Salmon-SMU-CU-DU-Crosswalk`.
