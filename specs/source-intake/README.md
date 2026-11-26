# Pacific salmon source intakes, 26 November 2026

These batches add source datasets to one local Oxigraph store. The graph identifies each dataset, its publisher, original files, hashes, tables and fields. Each table has a resource path within its local Salmon Data Package, where the values and source flags can be read. The intake preserves source identifiers and leaves biological equivalence and measurement mappings open.

## Batch one

| Source | Tables | Records | Scope |
| --- | ---: | ---: | --- |
| [DFO salmon productivity](../dfo-rs-productivity/README.md) | 6 | 8,340 | British Columbia sockeye, pink and chum. Annual records and two levels of summary. |
| [NWFSC Columbia River chum](../nwfsc-columbia-chum-2020/README.md) | 1 | 132 | Four WDFW spawner series represented in VRData 2.3. |
| [SASAP sockeye brood tables](../sasap-sockeye-brood/README.md) | 3 | 3,117 | Brood records, stock information and source information for Alaska, British Columbia and Washington. |

The 11,589 records in batch one include measurements, summaries and lookup records. The graph holds structural metadata and provenance. The numerical observation projection is empty for this intake. The SASAP sockeye brood EML declares “no restrictions” and gives no licence URI. Its Spec records redistribution as unconfirmed. The package checks validate technical fidelity. Interpretation of mixed year bases, escapement and spawner definitions, or cross-source stock matches requires separate evidence.

## Batch two

| Source | Tables | Records | Scope |
| --- | ---: | ---: | --- |
| [DFO Pacific salmon unit lookup](../dfo-smu-cu-du-lookup/README.md) | 1 | 484 | Bilingual stock management unit, conservation unit and designatable unit lookup for five species. |
| [Snake River Chinook spawner estimates](../nwfsc-snake-chinook-pit-model/README.md) | 1 | 159 | Model-based estimates for 20 spring/summer Chinook populations, 2010–2019. VRData credits the Nez Perce Tribe as contributor. |
| [Alaska salmon harvest by sector](../sasap-alaska-harvest-sectors/README.md) | 1 | 6,022 | Commercial, subsistence, personal-use and sport harvest in 13 regions. The CSV includes years from 1969 through 2016, with different coverage by sector. |

The second batch adds 6,665 records. Replaying both batches produces a catalogue of six datasets and 13 tables containing 18,254 source records. DFO's blank and multi-valued unit indexes, NOAA's population codes, and Alaska’s confidentiality flags remain available in the source tables. The graph indexes these fields and their provenance. A cross-source comparison still requires a decision about the meaning of each measure and population.

## Rebuild the packages and load the local graph

Use an isolated checkout or export of the source-intake executor. The public commit below supplies the Spec v1 builder and byte-verifying admission code. It pins MetaSalmonPy at `943fe1f50d7ac5b88b8be81250dca2e7aeb0f632`. The read-only library under `python/` is used separately for connected discovery.

Run from the root of the checkout containing these specs. The example creates a new runtime under the ignored cache. Each batch has a separate input and build directory. Both commands below target the same database.

```sh
first="$PWD/data/intake/2026-11-26"
second="$PWD/data/intake/2026-11-26-batch2"
runtime="$PWD/.cache/source-intake-executor"
git fetch origin codex/ohlberger-pws-intake
mkdir -p "$runtime/specs"
git archive b11d3bcd8b46c87934d268668ead2a023c9e40b3 salmongraph pipelines pyproject.toml uv.lock .python-version README.md | tar -x -C "$runtime"
cp specs/dfo_rs_productivity_parser.py specs/dfo_smu_cu_du_lookup_parser.py "$runtime/specs/"
uv sync --frozen --project "$runtime"
```

Stage the files from each Spec's `source.files` using its exact `url` and `name` under `$first/<slug>/raw/` for batch one or `$second/<slug>/raw/` for batch two. The build checks the source-file SHA-256 pins. The SASAP processing documents are cited inputs. The executor reads the published tables directly. Save the three Turtle files listed in [vocabularies.tsv](vocabularies.tsv) under `$first/vocab/` as `smn.ttl`, `gcdfo.ttl` and `psc.ttl`. Replay checks the vocabulary hashes before it builds any package.

```sh
export SALMONGRAPH_SMN_TTL="$first/vocab/smn.ttl"
export SALMONGRAPH_GCDFO_TTL="$first/vocab/gcdfo.ttl"
export SALMONGRAPH_PSC_TTL="$first/vocab/psc.ttl"
PYTHONPATH="$runtime" "$runtime/.venv/bin/python" -B specs/source-intake/replay.py \
  --batch 1 --intake-dir "$first" --build-date 2026-11-26 --store "$PWD/graph/store/corpus"
PYTHONPATH="$runtime" "$runtime/.venv/bin/python" -B specs/source-intake/replay.py \
  --batch 2 --intake-dir "$second" --build-date 2026-11-26 --store "$PWD/graph/store/corpus"
```

The replay compares each built table with the source. For DFO productivity it reconstructs the original tables, including the positional headers, blank padding and 77 trailing spaces in comment fields. The executor validates the Salmon Data Packages and checks their graphs with SHACL. Each source directory contains a `build/` with the package, manifest and validation report. The loader verifies the manifest and sidecars and admits each dataset in a separate transaction. Repeating a successful admission with identical inputs reuses the same graph. Changes to an existing package require a fresh intake directory.

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
