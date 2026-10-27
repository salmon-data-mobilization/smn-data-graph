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
