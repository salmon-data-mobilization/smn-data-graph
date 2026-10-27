# Local connected-discovery library

This standalone Python project packages one read-only entrypoint:
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
`discovery.discover`. No listener or command-line service is supplied. Vocabulary
fetching, package building/admission, SDK bridges, corpus recipes, publishers,
private data and local dependency paths are absent. This is not an SDK or a full
graph-build package; retained helper modules do not widen that supported surface.

The root corpus `pyproject.toml`, lock file, pipelines and catalogue validation
remain separate and unchanged. No MetaSalmonPy dependency or held SDK candidate
is needed by this subproject.

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

The 21 original discovery checks are copied byte-for-byte. A small fixture
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
