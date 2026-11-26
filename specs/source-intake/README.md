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

## Batch three

The [batch three dataset index](batch-3.md) lists 30 additions, with ten datasets from each of the three source groups. This batch adds 49 tables and 134,383 records. Across all three batches, the local graph identifies 36 datasets and 62 tables containing 152,637 packaged records.

## Rebuild the packages and load the local graph

Use an isolated checkout or export of the source-intake executor. The public commit below supplies the Spec v1 builder and byte-verifying admission code. It pins MetaSalmonPy at `943fe1f50d7ac5b88b8be81250dca2e7aeb0f632`. The read-only library under `python/` is used separately for connected discovery.

Run from the root of the checkout containing these specs. The example creates a new runtime under the ignored cache. Each batch has a separate input and build directory. All three batches use the same database.

```sh
first="$PWD/data/intake/2026-11-26"
second="$PWD/data/intake/2026-11-26-batch2"
third="$PWD/data/intake/2026-11-26-batch3"
runtime="$PWD/.cache/source-intake-executor"
git fetch origin codex/ohlberger-pws-intake
mkdir -p "$runtime/specs"
git archive b11d3bcd8b46c87934d268668ead2a023c9e40b3 salmongraph pipelines pyproject.toml uv.lock .python-version README.md | tar -x -C "$runtime"
cp specs/dfo_rs_productivity_parser.py specs/dfo_smu_cu_du_lookup_parser.py \
   specs/dfo_pacific_tables_parser.py specs/knb_lexical_csv.py specs/west_coast_csv.py "$runtime/specs/"
uv sync --frozen --project "$runtime"
```

Stage the files from each Spec's `source.files` using its exact `url` and `name` under `<batch-directory>/<slug>/raw/`. Use the corresponding directory above for each batch. The build checks the source-file SHA-256 pins. The SASAP processing documents are cited inputs. The executor reads the published tables directly. Save the three Turtle files listed in [vocabularies.tsv](vocabularies.tsv) under `$first/vocab/` as `smn.ttl`, `gcdfo.ttl` and `psc.ttl`. Replay checks the vocabulary hashes before it builds any package.

```sh
export SALMONGRAPH_SMN_TTL="$first/vocab/smn.ttl"
export SALMONGRAPH_GCDFO_TTL="$first/vocab/gcdfo.ttl"
export SALMONGRAPH_PSC_TTL="$first/vocab/psc.ttl"
PYTHONPATH="$runtime" "$runtime/.venv/bin/python" -B specs/source-intake/replay.py \
  --batch 1 --intake-dir "$first" --build-date 2026-11-26 --store "$PWD/graph/store/corpus"
PYTHONPATH="$runtime" "$runtime/.venv/bin/python" -B specs/source-intake/replay.py \
  --batch 2 --intake-dir "$second" --build-date 2026-11-26 --store "$PWD/graph/store/corpus"
PYTHONPATH="$runtime" "$runtime/.venv/bin/python" -B specs/source-intake/replay.py \
  --batch 3 --intake-dir "$third" --build-date 2026-11-26 --store "$PWD/graph/store/corpus"
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

## Check a proposed join

Run `python3 specs/source-intake/audit_join.py LEFT.csv RIGHT.csv --left-key COLUMN [COLUMN ...]` on the exact UTF-8 CSV views you intend to join. Supply `--right-key` for different column names and repeat `--null-token` for publisher-defined missing values. The command matches exact lexical tuples and reports both whole-file key repetition and matches on the overlapping keys. Use `--require-single-match` when attaching exactly one lookup row to every row on the left. The JSON gives the number of expanded inner-join rows even on a cardinality failure. Link the source definitions for both keys to explain why the records represent comparable entities or events.

## Audit native measurement types for numeric analysis

Run `python3 specs/source-intake/audit_measurement_types.py PACKAGE` to list each native measurement field and its declared type. The audit compares `metadata/column_dictionary.csv` with the Frictionless data resource schema in `datapackage.json`. The JSON report counts text measurement slots, declared numeric slots, verified direct numeric views, explicit unresolved decisions and fields awaiting a decision. A numeric field can itself be the target of a verified view, so several listed fields can represent one scientific variable.

To review a text measurement, pass `--decisions decisions.json`. Each field identifier contains the dataset ID, table ID and column name. Use a direct view when the source has a numeric interpretation and a reason when a decision is unresolved.

```json
[
  {"source": ["example", "samples", "reading"], "view": ["example", "numeric_samples", "reading_numeric"]},
  {"source": ["example", "samples", "condition"], "unresolved": "The survey records qualitative categories."}
]
```

A direct view must have a matching resolved variable IRI, matching unit and I-ADOPT fields, a native integer or number type, identical named primary keys, and the same rows, numerical values and missingness. The audit matches keys across CSVs, compares finite decimal values, and uses each resource schema's declared missing tokens (the default is an empty field). At least one nonmissing pair must exist. A conversion, subset, estimate or aggregation needs its own scientific review. The audit checks the reviewer's stated link and preserves unresolved fields in its report. The reviewer determines whether the sampling design and variable support the intended analysis.

When a publisher assigns a missing marker to one measurement field, add `source_missing_tokens` and `source_missing_evidence` to that direct-view decision. Cite the field or table and explain why the marker means missing there. For example, an instrument reading could use the following decision.

```json
{
  "source": ["example", "samples", "reading"],
  "view": ["example", "numeric_samples", "reading_numeric"],
  "source_missing_tokens": ["ND"],
  "source_missing_evidence": {
    "locator": "Instrument export manual, reading field dictionary",
    "rationale": "The instrument uses ND when it did not record a reading."
  }
}
```

Resource `missingValues` still apply to their full declared scope. Additional tokens apply only when reading this exact source value column. Keys, sibling columns and target values keep their respective resource rules. Both token sets use exact case-sensitive text, including whitespace. Additions must be distinct, nonblank strings absent from the resource list. Negative numeric sentinels such as `-999` require the same evidence and match only the stated spelling (`-999.0` is a different token). Zero, positive numeric values and infinities cannot be introduced through a field override. The JSON report retains the supplied locator and rationale and counts source cells matching each additional token for a verified view.

Use `--require-accounted` for a gate. It exits with status 1 for an unreviewed nonnumeric field, a failed view check, or a package with no declared measurements. An explicit unresolved decision satisfies this gate and contributes zero verified views. An input or schema error exits with status 2.

## Check export decisions and sample them for review

Run `python3 specs/source-intake/audit_mapping_decisions.py PROFILE.ttl DECISIONS.json --dataset ID --seed SEED --per-status 2` with RDFLib installed. Supply one record per distinct proposed RDF triple with the fields `id`, `status` (`accepted` or `abstained`), `table`, `claim`, `source_url`, `locator`, `reason`, `subject`, `predicate` and `object`. This profile check handles IRI objects. It verifies the exact triple, requires evidence that the subject exists even for abstentions, and reports a seeded sample from both strata. The sample includes discrepancies so they remain available to a reviewer. A positive result describes what the explicit Turtle says. The native package, the biological interpretation, implied assertions and the evidence behind each decision require separate checks.
