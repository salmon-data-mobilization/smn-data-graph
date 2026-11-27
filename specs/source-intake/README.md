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

To check a proposed cardinality, add `--expect-cardinality one-to-one`, `one-to-many`, `many-to-one` or `many-to-many`. Each “one” requires unique complete keys across that whole side. The check also requires at least one shared key and zero missing keys on either side. For multiple files on a side, repeat `--left-extra FILE` or `--right-extra FILE`. The report counts shared keys with multiple rows on both sides and gives the expanded inner-join size. Add `--require-single-match` when every left record must match once. Checks do not join or deduplicate the source data.

To inspect a proposed key across a collection, run `python3 specs/source-intake/audit_join.py --files FILE1.csv FILE2.csv --key SITE YEAR --payload ESTIMATE FRACTION --expect-unique`. The JSON lists each repeated key, file paths, 1-based data record numbers and the selected payload values. A key can repeat both within and across files. Matching payloads refer only to the fields you selected. Include all remaining columns when testing equality across complete rows. `--expect-unique` requires at least one record, complete keys and no repeated keys in the collection. Omit that option for a descriptive report. Both commands compare text exactly and interpret `--null-token` as a missing key component. Each gate exits 1 on failure and writes the report.

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

Use `--require-accounted` for a gate. It exits with status 1 for an unreviewed nonnumeric field, a failed view check, or a package with no declared measurements. An explicit unresolved decision satisfies this gate and contributes zero verified views. An input or schema error exits with status 2. For a quantitative analysis, use `--require-numeric` to check original numeric cells against the declared missing tokens and types and require at least one observed value per declared measurement or its verified view. An unresolved field fails this stronger gate. Field-specific biological interpretation and which columns should be declared measurements still require source review.

## Check export decisions and sample them for review

Run `python3 specs/source-intake/audit_mapping_decisions.py PROFILE.ttl DECISIONS.json --dataset ID --seed SEED --per-status 2` with RDFLib installed. Supply one record per distinct proposed RDF triple with the fields `id`, `status` (`accepted` or `abstained`), `table`, `claim`, `source_url`, `locator`, `reason`, `subject`, `predicate` and `object`. This profile check handles IRI objects. It verifies the exact triple, requires evidence that the subject exists even for abstentions, and reports a seeded sample from both strata. The sample includes discrepancies so they remain available to a reviewer. A positive result describes what the explicit Turtle says. The native package, the biological interpretation, implied assertions and the evidence behind each decision require separate checks. To check labels during export, pass `--owned-namespace` for each project namespace, including its final delimiter. The command reports any labels the profile assigns to terms owned by another vocabulary.

### Check coverage claims against an independent contract

Run `python3 specs/source-intake/audit_mapping_decisions.py PROFILE.ttl --dataset ID --scope-propositions EXPECTATIONS.json`. Supply the exact source-backed propositions that a consumer should find or withhold in this dataset profile. The scope contract runs independently of the mapper’s decision register, so an omitted mapping can fail the check. It can also run alongside a register and its `--seed`. Each rule needs a unique `id`, `expect` (`required` or `forbidden`), and a `subject`, `predicate` and `object`. The subject of every rule must occur in the export. Use absolute IRIs or a typed literal object with `value` and `datatype`.

```json
[
  {"id":"survey-year", "expect":"required", "subject":"urn:survey:subset", "predicate":"urn:survey:year", "object":{"value":"2010", "datatype":"http://www.w3.org/2001/XMLSchema#gYear"}, "only_object":true},
  {"id":"restricted-coverage", "expect":"required", "subject":"urn:survey:subset", "predicate":"urn:survey:coverage", "object":"urn:survey:adults", "only_subject":true},
  {"id":"other-stock", "expect":"forbidden", "subject":"urn:survey:neighbor", "predicate":"urn:survey:coverage", "object":"urn:survey:adults"}
]
```

On a required rule, `only_subject` detects the same predicate and object attached to any additional subject in this profile. `only_object` detects any additional object for that subject and predicate, such as another population, year or age class. Apply these flags where evidence supports exclusive scope. This check evaluates explicit RDF in the supplied Turtle file. Reviewers still need to establish the scientific meaning, evidence and coverage of the propositions and select any other relevant predicates to check.

## Read a verified decimal field

Use the following command when a published measurement has more decimal digits than a binary floating-point reader can preserve. Supply the reviewed package and field decisions, then the expected SHA-256 of the original source CSV from the publisher or a verified intake manifest.

```sh
python3 specs/source-intake/read_numeric_view.py PACKAGE decisions.json \
  --source example samples reading --source-sha256 "$expected_source_sha256"
```

The reader checks the source bytes and reuses the audit's direct-view checks for variable identity, units, primary keys, values and missingness. It emits JSON in source order with the primary key column names and one pair per row, consisting of the key tuple and a decimal string or null. The Python function `read_verified_decimals(package, decisions_path, source, source_sha256)` returns the key names and a dictionary of key tuples to `decimal.Decimal` or `None`. Numeric spellings can normalize during decimal parsing. Original CSV bytes remain the authority for exact source spelling. Preserve decimal types during arithmetic and choose an appropriate decimal context for calculated results.

This reader verifies one reviewed source-to-view mapping. Native SDK package validation remains a separate check. metasalmonpy v0.6.0 preserves a column as strings and reports a precision mismatch when its binary64 reader would change a declared numeric value.

A source field with documented thousands grouping can add `"source_number_format": {"grouping":"comma_thousands","locator":"…","rationale":"…"}` to its direct-view decision. Supply a publisher locator and explain the interpretation. The auditor and reader accept comma groups of three digits in that source field. They preserve the original CSV and require the target numeric field to use an ordinary decimal spelling. A malformed group, a comma used as the decimal mark or different source and view values fails the check.

## Test an inference from integrated packages

For a blind run, the source reader sends the fingerprint of a private SHA-256 design manifest after specifying which fish or strata would have to match. Use the following commands to witness the plan before releasing any observation files for analysis. Include a byte-for-byte copy of the public receipt with each submitted export. The grader checks that copy against the original receipt and the digest received from the reader. This sequence records what was witnessed and when. The independence of the participants and observation access must also be documented.

```sh
python3 specs/source-intake/audit_study_gate.py witness reader/DESIGN.sha256 MAPPING_OPEN.json --expected-sha256 "$reader_digest"
python3 specs/source-intake/audit_study_gate.py verify reader/DESIGN.sha256 MAPPING_OPEN.json --expected-sha256 "$reader_digest" --submission case/round1/study-gate.json
```

Repeat `--context LABEL SHA256` to bind a common rubric or vocabulary snapshot at both stages. Registration contents stay with the reader and grader. Give the export analyst the scientific design with the hidden mapping criteria removed.

For a full independent review of a decision register, add `--judgment-reference reference.json` to `audit_mapping_decisions.py`. Supply an array with the original proposition (`id`, `claim`, `subject`, `predicate`, `object`) and the referee’s own `evidence_verdict`, `action`, `source_url`, `locator` and `reason`. The rubric defines the four verdicts and three actions. The check distinguishes a missing or asserted triple from a wrongly explained abstention. For example, a source that defines a field as the region of harvest contradicts a claim that it identifies natal origin. The individual fish’s actual origin remains unknown. Missing reference items and changed propositions fail the full review. Save disagreements before any repair.

Use the [scientific review rubric](scientific-review-rubric.json) when testing an integrated dataset. Record the six common mapping scores and the four source-reader questions per dataset. Score the scientific analysis separately. Preserve the first export, references, judgments and later corrections under distinct hashes.

1. Before anyone computes the joined outcome, an independent source reader chooses one realistic scientific question and the nearest plausible overclaim. Use the publisher's least aggregated available records, dictionaries, lookup versions and methods. Record where the derivation stops. Specify the target fish or fishery, observational unit, years, area, sample selection, statistic, numerical tolerance, sensitivity and conditions for withholding the inference. Seal the design. Mappers may see the common rubric. Keep case answers, reference records and held-out questions blind.
2. Compute the answer from the publisher files. Save the eligible record keys, multiplicity on each side, unpaired and excluded keys with reasons, denominator components and result. Preserve the distinction between suppression, unknown and observed zero. Mark a related publication that draws on the same source records as shared lineage.
3. Use the sealed packages to run the same analysis independently. Read measurement values through the native package, verify the RDF statements that license the variable, geographical and population matches, and list each scientific assumption or crosswalk the analyst supplied. Try the prespecified plausible error, such as dropping the sector restriction. Show the first check that catches it.
4. Have a separate grader compare record identities and values, then exclusions and denominators, then the estimate. Check both the interpretation and its nearest overclaim. Report what the evidence supports as stated, what needs narrower scope, what the source leaves unresolved and what the mapping lost. A correctly withheld scientific claim and a technical failure have different outcomes.
5. Use the retrospective to select the defect with the greatest effect on the conclusion. Repair the responsible profile or tool. Replay the identical question and adverse control. Keep the first score beside the retest. Where the source limits the analysis, specify the missing observation or design feature that would change the verdict.

For an outcome count, build a candidate roster from an enumeration that does not require a detected event. Give `audit_candidate_denominator.py` that CSV and a second CSV of the fish admitted by the proposed filter. Repeat `--key` for the full fish identity and `--stratum` for every design stratum. Set `--outcome` to the roster’s nonnegative integer count and declare any additional missing codes with `--missing-code`. The JSON reports retained and excluded counts by stratum for zero, positive and missing outcomes. Exit 2 identifies loss of an entire observed outcome class or an empty observed selection. Exit 1 identifies invalid inputs or unmatched identities. Partial selection and single-class rosters still require scientific review. Compare individual counts to an independent reference, since a within-stratum reassignment can preserve every rate.

The independent reader can check a proposed table with `python3 specs/source-intake/audit_schema_projection.py publisher-header.csv metadata/column_dictionary.csv --source SOURCE_DATASET SOURCE_TABLE --native SDP_DATASET SDP_TABLE --require FIELD --output private-receipt.json`. Supply an exact header-only CSV from one publisher table. Repeat `--require` for each analysis field and `--alias SOURCE_NAME NATIVE_NAME` for documented renames in that table. Exact name matching applies otherwise. The private receipt distinguishes a field absent from the supplied source header from a publisher field lost in the projection. Exit 0 means all requested names are declared, 2 means some are missing, and 1 means the inputs or output path are invalid. Keep requirements, aliases and the receipt from mappers during a scored round. Field presence establishes neither semantic equivalence nor usable values.

## Look up stream roles for a return year

Run `python3 specs/source-intake/audit_scoped_roles.py claims.json queries.json` to check which documented roles apply to a stream in a specific estimate. Both files use version 1 of the JSON interface. The claim register is curated by the analyst. Use stable identifiers from the relevant evidence for the stream, signal, target series, edition and estimation method. Qualify ambiguous names in those identifiers. Use the same five identifiers in each query. Matching is literal and case-sensitive.

In this fictional example, a survey recorded fish in Alder during 2001–2003. An estimator used those counts in 2002. For a standalone subset, enter a separate assertion specifying whether the stream qualifies for that subset in the scoped product. Each assertion needs a traceable evidence locator. The lookup evaluates the supplied assertions and does not authenticate their sources.

```json
{"version": 1, "claims": [
  {"stream": "Alder", "signal": "adult count", "series": "Coast index", "edition": "first", "method": "reach expansion", "first_year": 2001, "last_year": 2003, "role": "monitoring", "assertion": "include", "evidence": "Example survey log, table 4"},
  {"stream": "Alder", "signal": "adult count", "series": "Coast index", "edition": "first", "method": "reach expansion", "first_year": 2002, "last_year": 2002, "role": "estimator_input", "assertion": "include", "evidence": "Example methods, table 9, 2002 inputs"}
]}
```

```json
{"version": 1, "queries": [
  {"stream": "Alder", "signal": "adult count", "series": "Coast index", "edition": "first", "method": "reach expansion", "return_year": 2002}
]}
```

Supply integer years. Both endpoints of a claim interval are included. Enter a separate record for each uninterrupted interval and each role. Each query asks about a single return year. The JSON output echoes queries in order and gives independent decisions for `monitoring`, `estimator_input`, and `standalone_subset`. Each decision contains `status`, `include_evidence`, and `exclude_evidence`. Only `supported` licenses membership. A matching `exclude` assertion alone yields `excluded`. A gap or absence of matching assertions yields `abstain`. Conflicting assertions within the same scope and role yield `contradiction` with the locators from both sides. The example returns supported monitoring and estimator use, and abstains on standalone membership.

The CLI prints its report to standard output and exits 0 for any valid lookup, including an abstention or contradiction. Consumers must read the required role's status. Invalid input exits 1 with no report.
