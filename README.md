# salmon-demo-corpus

Agent-built corpus of interoperable Pacific salmon datasets for the PICES-2026
S12 demo of the salmon data integration toolkit (talk: Wed 28 Oct 2026).

Agents run through the Claude Agent SDK and are paid by the monthly
promotional API credit of the Console organization "Brett's Individual Org"
(not by a Claude subscription).

## Read-only connected discovery

For the standalone local query library, use [python/README.md](python/README.md).
It discovers connections in an already admitted graph and needs PyOxigraph only;
no Claude account, API key or private SDK is required. The corpus-building setup
below is a separate workflow.

## Setup

1. Store the Console API key in the macOS Keychain (one time):

   ```bash
   security add-generic-password -a "$USER" -s anthropic-salmon-corpus -w
   ```

2. Install dependencies: `uv sync`

3. Check the connection: `uv run smoke_test.py` (spends at most about $0.50).
   Then confirm the run on the Console Usage page.

`corpus_auth.py` reads the key from the Keychain and clears any Claude session
variables inherited from the shell, so a run never uses a session's account.

## Local source intake

The three [Pacific salmon source intakes](specs/source-intake/README.md) cover 36 datasets and 62 tables. The [third batch](specs/source-intake/batch-3.md) adds Canadian monitoring and fisheries records, U.S. West Coast and Columbia Basin field studies, and Alaska and North Pacific archives. The table catalogue query returns each dataset’s publisher record and the path to each table in its local package.

## Starter catalogue evidence

[The prepared catalogue](specs/starter-corpus/catalogue-evidence.json) records
four source datasets and one collection: the NPAFC International Pacific Salmon
Data Legacy Database, SASAP, and three Alaska salmon records. It retains primary
metadata URLs and hashes, record-level rights, revision lineage, unknown release
versions and publisher coverage-quality flags. Project association does not
assert portal membership or biological equivalence.

This file is metadata preparation, not observation data, graph ingestion,
accepted semantic mappings or publication approval. Its snapshot filenames refer
to the preparation evidence; this repository does not contain those snapshots.

The standalone checks require Python 3.13 and pytest 9.1.1 and need no corpus API
key, graph runtime, source download or model call:

```sh
python -m pytest -q tests/test_starter_catalogue_evidence.py
```

The Catalogue evidence workflow runs these checks for relevant pull requests
and changes to main. It validates the prepared artifact; it does not fetch or
reconfirm the live publishers' records or certify their scientific content.

## Two-source aggregate coverage audit

Run `python python/aggregate_coverage.py facts.json --trig facts.trig` with RDFLib 7.6.0 to check two published totals against a defined return-year population. Keep local source facts and outputs outside version control. The JSON result gives the shared accounting units, each source's reconciliation, and the decision. The optional TriG export contains each source's roster in its version-specific named graph. [The SPARQL query](python/aggregate_coverage.rq) can be run directly on that export to inspect the support records; the CLI applies the reconciliation and addition rules.

- The root object has a `target` object and exactly two entries in `sources`. Both sources and the target declare `frame` (the same absolute IRI for a versioned partition), `species`, integer return `year`, `measure`, `unit` and `statistic`. Only a quantity which is additive across the chosen partition may use `"statistic":"sum"`.
- The target lists `atoms`, the exhaustive list of disjoint canonical unit IRIs for the requested population. Establish that partition from evidence before running the checker. Include age, origin, seasonal, biological or reporting distinctions that alter membership. A list of names alone cannot establish disjointness. Optional `aliases` maps distinct spellings or source identifiers to canonical atom IRIs in this frame. Optional `contains` maps a parent IRI to an array of child IRIs. A known parent must be expanded with source evidence before use.
- Each source supplies an absolute version-specific `graph` IRI, publisher `version`, `reported` total, boolean `complete`, and `components` array. A component supplies source-local `id`, boolean `resolved`, and an `atoms` array of objects with `id`, `role` (`direct` or `represented`), `value` and `version`. A represented unit needs evidence that it contributes to the estimate. When a group total lacks documented allocations, preserve supported atom identities and leave their values null. When even membership cannot be resolved, set `resolved` to false.
- Provide `evidence` for the target, each reported total and each component mapping. Include a specific locator such as a table and row, or supply a separate `locator` string. Record the basis for temporal scope, aliases, containment and component allocations. The checker takes these assertions as input. Verify them against the source independently. Use exact nonnegative integers or decimal strings for amounts. For shared atoms, use the same estimate-version identifier only when evidence establishes the same observation or estimation vintage across sources. Unknown lineage can be recorded as null.
- `add_totals` requires compatible disjoint coverage of the entire target with both totals reconciled. For compatible overlap, `rebuild_union` counts each canonical atom once after checking its value and estimate version. A conflict, difference in scope, or unresolved requirement yields `withhold` and a null union. A demonstrated overlap remains visible when values differ. A well-formed audit exits with status 0 for all three decisions. Invalid input exits with status 2.

The [fictional tests](tests/test_aggregate_coverage.py) include complete input examples. Run `python -m unittest discover -s tests -p test_aggregate_coverage.py` to check the decisions and repeat the query on the exported RDF.
