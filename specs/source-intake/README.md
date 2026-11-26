# Pacific salmon source intake, 26 November 2026

This batch adds three source datasets to a local Oxigraph store. The graph identifies each dataset, its publisher, original files, hashes, tables and fields. Each table has a resource path within its local Salmon Data Package, where the values and source flags can be read. The intake preserves source identifiers and leaves biological equivalence and measurement mappings open.

| Source | Tables | Records | Scope |
| --- | ---: | ---: | --- |
| [DFO salmon productivity](../dfo-rs-productivity/README.md) | 6 | 8,340 | British Columbia sockeye, pink and chum. Annual records and two levels of summary. |
| [NWFSC Columbia River chum](../nwfsc-columbia-chum-2020/README.md) | 1 | 132 | Four WDFW spawner series represented in VRData 2.3. |
| [SASAP sockeye brood tables](../sasap-sockeye-brood/README.md) | 3 | 3,117 | Brood records, stock information and source information for Alaska, British Columbia and Washington. |

The 11,589 records include measurements, summaries and lookup records. The graph holds structural metadata and provenance. The numerical observation projection is empty for this intake. The SASAP EML declares “no restrictions” and gives no licence URI. Its Spec records redistribution as unconfirmed. The package checks validate technical fidelity. Interpretation of mixed year bases, escapement and spawner definitions, or cross-source stock matches requires separate evidence.

## Rebuild the packages and load the local graph

Use an isolated checkout or export of the source-intake executor. The public commit below supplies the Spec v1 builder and byte-verifying admission code. It pins MetaSalmonPy at `943fe1f50d7ac5b88b8be81250dca2e7aeb0f632`. The read-only library under `python/` is used separately for connected discovery.

Run from the root of the checkout containing these specs. The example creates a new runtime under the ignored cache. Set `intake_dir` to the location where you will stage the source files.

```sh
intake_dir="$PWD/data/intake/2026-11-26"
runtime="$PWD/.cache/source-intake-executor"
git fetch origin codex/ohlberger-pws-intake
mkdir -p "$runtime/specs"
git archive b11d3bcd8b46c87934d268668ead2a023c9e40b3 salmongraph pipelines pyproject.toml uv.lock .python-version README.md | tar -x -C "$runtime"
cp specs/dfo_rs_productivity_parser.py "$runtime/specs/"
uv sync --frozen --project "$runtime"
```

Stage the files from each Spec's `source.files` using its exact `url` and `name` under `$intake_dir/<slug>/raw/`. The build checks all 14 SHA-256 pins. The SASAP processing document is a cited input. The executor reads the published tables directly. Save the three Turtle files listed in [vocabularies.tsv](vocabularies.tsv) under `$intake_dir/vocab/` as `smn.ttl`, `gcdfo.ttl` and `psc.ttl`. Replay checks the vocabulary hashes before it builds any package.

```sh
export SALMONGRAPH_SMN_TTL="$intake_dir/vocab/smn.ttl"
export SALMONGRAPH_GCDFO_TTL="$intake_dir/vocab/gcdfo.ttl"
export SALMONGRAPH_PSC_TTL="$intake_dir/vocab/psc.ttl"
PYTHONPATH="$runtime" "$runtime/.venv/bin/python" -B specs/source-intake/replay.py \
  --intake-dir "$intake_dir" --build-date 2026-11-26 --store "$PWD/graph/store/corpus"
```

The replay compares each built table with the source. For DFO it reconstructs the original tables, including the positional headers, blank padding and 77 trailing spaces in comment fields. The executor validates the Salmon Data Packages and checks their graphs with SHACL. Each source directory contains a `build/` with the package, manifest and validation report. The loader verifies the manifest and sidecars and admits each dataset in a separate transaction. Repeating a successful admission with identical inputs reuses the same graph. Changes to an existing package require a fresh intake directory.

## Find the data

Run the [table catalogue query](tables.rq) against the local store. It returns the publisher link, table name, number of fields and path to its CSV within the package. From the same checkout and runtime:

```sh
"$runtime/.venv/bin/python" - <<'PY'
from pathlib import Path

from pyoxigraph import Store

store = Store.read_only("graph/store/corpus")
query = Path("specs/source-intake/tables.rq").read_text()
for row in store.query(query):
    print(row["title"].value, row["table"].value, row["resource"].value, sep="\t")
PY
```
