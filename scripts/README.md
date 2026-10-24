# Independent baseline audit

`audit_pices_baseline.py` reads the checked-in legacy PSF NuSEDS TriG and package.
It does not fetch sources, rebuild the corpus, call an agent, or change inputs.
It checks saved graph counts, the reviewed `hasConservationUnit` domain risk,
known `MAX_ESTIMATE` spawner annotations, per-assertion identity review marks,
and explicit agent/manual-curation provenance claims. It is a regression aid, not release certification or a
replacement for SHACL and scientific review.

From the repository root, using an environment with the existing `pyoxigraph`
dependency installed:

```sh
python scripts/audit_pices_baseline.py
python scripts/audit_pices_baseline.py --output runs/local-baseline-audit/receipt.json
python -m unittest discover -s tests -p 'test_audit_pices_baseline.py' -v
```

The JSON receipt contains relative input paths, SHA-256 hashes, parsed unique
quad counts and bounded findings. Output is deterministic for the same artifact
bytes and parser version. `--output` is the only write; it cannot overwrite an
audited input. Exit codes are `0` for the scoped checks passing (warnings may
remain), `1` for blockers, and `2` for missing or malformed input.
For `.trig.gz`, parsing uses decompressed content while input hashes describe
the original compressed artifact. Invalid or truncated gzip is an input error.

The default namespace and graph paths describe the legacy baseline. A namespace
migration that retains that layout can use `--base-iri`; a different graph model
needs a deliberate audit update. Unknown/missing graphs are reported. The audit
does not fetch the ontology or infer that classes are disjoint. It reports the
unintended Stock Management Unit entailment identified in the design review.

The identity gate covers CU-to-CU `skos:exactMatch`, `closeMatch`, `broadMatch`
and `narrowMatch`, plus Population-to-CU `smn:populationOf`. It checks live edges
and RDF 1.1 statement-only candidates, so omitting a live triple does not hide
the pending relationship. Types, reification and marks may occur in different
named graphs; repeated identical triples count once. Each candidate needs one
named `rdf:Statement` with unambiguous subject/predicate/object, URI-valued agent,
activity and source evidence, a nonempty context comment, one allowed confidence,
criticality `critical`, and exactly one `awaitingReview` status.

Valid pending candidates pass this structural gate. They remain unapproved and
cannot appear as live critical join edges in this legacy format, which has no
reviewed query view. Missing marks, critical `agentAccepted`, conflicting status
values, human decision formats and RDF 1.2 `rdf:reifies` records block the scoped
audit. Supporting human approvals or the future graph model requires a deliberate
audit update with its own review evidence checks.

The MAX check also follows the column's I-ADOPT decomposition to detect residual
`smn:SpawnerStageContext`, including a constraint on its object-of-interest node,
even after `term_iri` is removed. When the package's decomposition CSV exists,
its MAX rows are checked and the file is included in the input hashes. These
checks detect known unsafe claims; they do not select replacement semantics.
