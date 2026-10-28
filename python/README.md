# Local connected-discovery library

The primary read-only entrypoint is:
`salmongraph.discovery.discover`. It reads an **already admitted**, access-appropriate
local Oxigraph store and finds other datasets through exact measurement,
procedure and population IRIs. The caller must enforce fresh permissions and bind
the current project's dataset IRIs.

```python
from pathlib import Path
from salmongraph.discovery import discover

result = discover(
    Path("admitted-store"),
    project_datasets=["https://example.test/fictional/project/dataset"],
    families=("measurement", "procedure", "population"),
    include_pending=False,
    limit=50,
)
```

The example IRI is fictional. An exact shared IRI is a discovery connection,
not a scientific compatibility or pooling claim. Actual source, reifier, review,
scope and provenance evidence remains inspectable; pending relationships remain
unasserted. Layout, labels and proximity infer no identity.

## Supported scope and dependencies

The wheel contains only the allowlisted query/review kernel copied from reviewed
source commit `0015476bebb73beb5fbbe349c5ab920fe0f05f5e`. Runtime discovery needs
PyOxigraph only. Existing namespace configuration and review/criticality rules
are preserved; no frozen source graph is reminted. Set the matching namespace
configuration explicitly when required by an admitted store.

The `serve/sparql_server.py` helper and `_stub.py` are included solely to preserve
the original query checks and their real local SELECT/ASK assertions. Its parser
dependencies, RDFLib and pyparsing, are in the **test extra**, not required by
`discovery.discover`. No listener or command-line service is supplied. Vocabulary fetching, native-package building/admission, SDK bridges, corpus
recipes, publishers, private data and local dependency paths are absent. The
separate pure source-contribution boundary below does not add those operations. This is not an SDK or a full
graph-build package; retained helper modules do not widen that supported surface.

The root corpus `pyproject.toml`, lock file, pipelines and catalogue validation
remain separate and unchanged. No MetaSalmonPy dependency or held SDK candidate
is needed by this subproject.

## Pure confirmed-source contribution boundary

`salmongraph.contribution.preview(candidate, current=trusted_current)`
validates one closed `confirmed-column-contribution/1` candidate, then shows
**all graph bytes, generated record IRIs and selected content**. Its separate
`admit(candidate, current=..., consent=...)` function recomputes the exact preview
and compiles only after consent names its SHA-256:

```python
from salmongraph.contribution import preview, admit

shown = preview(candidate, current=trusted_current)
# A separate user interaction reviews shown's exact content and private audience.
compiled = admit(candidate, current=trusted_current, consent={
    "version": "confirmed-column-contribution-consent/1",
    "accepted": True,
    "previewSha256": shown["sha256"],
})
# compiled["graphBytes"] is canonical N-Quads, not a stored contribution.
```

The caller independently supplies current source authority IRI and D01 source/semantic/documentation/
selection/project bindings, the exact confirmed native projection, its selected
source-understanding evidence/scope and verified native-artifact hashes (the old version requires exactly six).
This module checks equality and structure; **it does not verify native artifact
bytes or an SDK runtime, or authenticate the attribution IRI**. Its receipt says
`trusted_caller_binding_not_runtime_attestation` and `compiled_not_persisted`.
Never accept `current` from a browser as proof. D01 projection and artifact
hashes use the existing compact UTF-8 `JSON.stringify` field ordering; the
contribution preview uses sorted-key compact UTF-8 JSON. Neither path silently
changes an upstream hash or vocabulary snapshot.

The exact `confirmed-column-semantics/1` projection and old column candidate,
current, consent, preview and receipt versions remain unchanged. A known
`confirmed-source-semantics/2` projection with `procedure: null` and
`identifiers: []` still uses that exact old contract and hashes its actual v2
projection. No field is downgraded, stripped or normalized.

Nonempty native families use the separate, closed `confirmed-source-contribution/2`
and `current-source-contribution/2` contracts. Their matching consent, preview
and compiled-receipt versions end in `/2`. `current` carries the actual native
procedure, authority-qualified identifiers, independently saved evidence/scope,
and verified artifacts (six base files, codes, and optional genuine SSSOM files).
A candidate explicitly selects columns, a procedure, and/or indexed identities;
a reference-only contribution needs no unrelated column-concept selection.
Unknown shapes, unresolved selected codes/procedures and unsupported native
fields refuse the whole operation. There are no free-form RDF fields.

Native `tables.method_iri` and `tables.protocol_iri` describe table metadata; they
do not prove observation grain or observed procedure use. Native `codes.term_iri`
references an explicitly supplied identity; it does not prove biological type
or membership. The compiler creates a metadata record with `dcterms:isPartOf`
and a **critical pending reified** `dcterms:references`, never its live SPO.
A closed JSON literal tagged `sdp-native-reference/1` records the native field
and scope. These are record descriptions using existing DCTERMS/PROV predicates,
not new ontology terms or a replacement graph representation.

Discovery labels these paths `match_basis="native_metadata_reference"` and
returns the exact `native_reference` context on both edges. Procedure matches
require the same field (method versus protocol) and table scope. Code matches
require the exact target IRI **and** native key, authority name/version,
vocabulary IRI and term type; column ordinal is source-local. Labels never join,
different authority releases never collapse, and metadata references never join
observed `sosa:usedProcedure` or typed observation-membership paths. Existing
actual observation paths remain unchanged. Row-varying procedure tokens,
including `NA`, blanks and `NO SURVEY`, acquire no inferred semantics.

Explicitly packaged, complete SSSOM mappings retain their declared predicate,
source/target versions, evidence, uncertainty, mapping-set provenance and scope
as separately **critical pending** statements. They are not traversed to infer
identity equivalence. No `qb:Observation`, `smn:Population`, CU/SMU membership,
new vocabulary IRI or shared acceptance is invented. Project-local vocabulary
needs no mandatory SDO promotion. The existing namespace configuration and
exact dataset IRI must agree; configuration and existing graphs are not changed.
Only the previewed metadata/statement record IRIs are minted.

Each selected field must match the trusted current citation/scope exactly. An
explicit contribution-time confidence, attribution IRI, activity IRI, date and
evidence are mandatory. They are recorded as supplied, never inferred from a
checkbox, model or filename. Existing `GraphBuilder`, provenance marking and
review validation compile the selected semantic claims as **critical `awaitingReview`
reifiers with no live semantic SPO**. Depositor confirmation is not graph
`humanAccepted` or `agentAccepted`, publication or scientific approval. The
actual read-only query can expose these paths only with `include_pending=True`;
they remain visibly pending alongside the other dataset's actual authority.

Unknown fields, raw-table payloads, private actor/project/version/model IDs,
changed source/native/semantic bindings, shared/public audiences and unsupported
semantics are structurally refused. Explicitly selected citation/note text and
IRIs may themselves contain sensitive content: the caller's exact-content
review remains necessary. This is not a universal privacy classifier. Errors
contain fixed messages and codes, not source-derived text. Inputs are bounded
at 512 KiB each, 128 selected columns, eight review evidence items and a 4 MiB
compiled graph; exceeding a limit refuses the complete candidate.

The pure functions perform no network or file I/O and return no durability,
authorization, cross-request idempotency or publication guarantee. The app must
hold fresh project ACL/basis checks, preserve immutable dataset/version hashes,
record an idempotency key/outcome/receipt atomically and reconcile interrupted
outcomes. Vercel's temporary filesystem is not durable graph storage. A later
permission-bound caller may load authorized durable bytes into a disposable
store, then use actual `discovery.discover`; graph display filters are not ACLs.

`tests/fixtures/fictional-d01-native.json` contains wholly fictional cells and a
genuine frozen SDK943 D01 native result; tests check its complete CSV grid and
native dictionary/file hashes. The trusted current/confirmation context is an
explicit fictional fixture, not an app sign-in or scientific decision. Tests
then compile a selected annotation, reopen an actual disposable store and find
one openly fictional OTHER dataset through the real query. The numeric/NA
fixture refusal and generation receipts are retained outside the public source.
`fictional-rich-native.json` and `fictional-rich-mapping-native.json` add genuine
SDK943 seven/nine-file outputs. Their complete literal grid, native method/code
fields and registered SSSOM artifact hashes are checked independently. The
qualified-identity query mutations are explicit synthetic RDF test boundaries,
not claims of new SDK generation. No SDK is installed or required by these tests
or the resulting wheel.

## Results and limits

Each path links a supplied project dataset to an **other** dataset through an
exact IRI and includes its structural membership witness, actual source/version,
assertion graphs, reifiers, evidence and effective authority. Identical labels
do not create identity. `include_pending=True` adds separately labelled
suggestions without asserting their SPOs. Graph display filters never remove
global review context or lower a criticality floor.

The result limit is 1..100 paths, with one further distinct path checking
`has_more`. Targeted evidence loading is bounded by 50,000 distinct quad reads
and 10,000 indexed patterns. Exhaustion returns
`query_status="partial_evidence_refused"`, no paths, and an explicit reason.
Store/review errors propagate without a catalogue or full-view fallback.

**Global review still materializes the complete store.** Targeted limits do not
bound its memory/time or PyOxigraph's native allocations. Synthetic tests show
unchanged targeted reads when unrelated quads take a store above 50,000 quads;
they do not establish a production capacity or concurrent-service guarantee.

## Build and test the installed artifact

Use Python 3.13 and ordinary non-editable wheel installation:

```sh
python -m pip wheel --no-deps --wheel-dir wheelhouse ./python
python -m venv /tmp/smn-graph-check
/tmp/smn-graph-check/bin/python -m pip install wheelhouse/smn_data_graph-0.1.0-py3-none-any.whl 'pytest==9.1.1' 'rdflib==7.6.0' 'pyparsing==3.3.3'
python -I python/scripts/check_wheel.py wheelhouse/smn_data_graph-0.1.0-py3-none-any.whl
/tmp/smn-graph-check/bin/python -I -m pytest python/tests --import-mode=importlib -q -s -W error
```

The original discovery checks remain intact. A small fixture
replaces the private corpus fixture: it resets namespace variables, requires
the actual module to originate in the installed non-editable wheel, and checks
that MetaSalmonPy is absent. It does not insert a checkout into `sys.path`.
Tests use fictional disposable stores, block socket/DNS/connect calls and verify
source-store file hashes and modification times. This is not kernel-level
network isolation or app/Auth/deployment/scientific/publication proof.

The wheel checker accepts only the reviewed Python-file allowlist and normal
distribution metadata. It refuses bundled data/builds, local dependency URLs,
personal paths and the held SDK candidate. It checks wheel inventory, RECORD
hashes and declared requirements. No tests or private artifacts are shipped.
