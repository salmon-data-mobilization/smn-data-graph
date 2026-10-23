# salmongraph interfaces (v0.1.0, 2026-10-23)

This is the contract between the salmongraph modules, so engineers can build
them in parallel. ADR-0001 wins over this file, and this file wins over a
module's guess. Each stub's docstring has the full detail; this file has the
names, signatures, files and graphs that more than one module depends on.

To change something here, change the code and this file in the same commit,
and say so in your result. `tests/test_foundation.py` fails if a stub's public
name is missing from this file.

## 1. Status

| Module | State | What it does |
|---|---|---|
| `config` | **working** | IRI layout, namespaces, `SALMONGRAPH_*` settings |
| `iri` | **working** | minting helpers for every layout entry; slugs; guards |
| `vocab` | **working** | `VocabIndex`: smn + gcdfo + PSC CV at recorded pins; the IRI guard |
| `graph` | **working** | `GraphBuilder`: quads in named graphs, literals, RDF 1.2 reifiers |
| `io.det` | **working** | sorted N-Quads / TriG, gzip mtime 0, canonical JSON/CSV, sha256, portable paths |
| `provenance` | **working (minimal)** | D6 marks, review status, agent and activity nodes, corp: profile terms |
| `spec` | stub | `specs/<slug>.yaml` parsing and validation |
| `executor` | stub | spec -> SDP, dataset graphs, Parquet, report (includes the SDP -> RDF compiler) |
| `identity` | stub | authority nodes, published membership, crosswalks, selection sets |
| `combine` | stub | one corpus store, shared graphs, cross-source checks |
| `shapes/`, `validate` | stub | SHACL shapes and the gate |
| `review` | stub | review queue, decisions as data, reviewed/full views |
| `ledger` | stub | `runs/ledger.csv` |
| `catalog` | stub | VoID + DCAT for releases and graphs |
| `release` | stub | `dist/corpus-<version>/` and `releases/<version>/manifest.json` |
| `serve.sparql_server`, `serve.mcp_server` | stub | read-only SPARQL; MCP tools |
| `publish.schemaorg`, `publish.knb`, `publish.zenodo` | stub | JSON-LD; KNB dry-run plans; Zenodo metadata (no uploads) |

Every stub raises `NotImplementedError` when called, not when imported.

## 2. Rules every module follows

- **Never hard-code the base.** Build every corpus IRI with `salmongraph.iri`.
  Read namespaces from `config.current().ns` or pass `cfg=`.
- **Never invent a vocabulary IRI.** Every smn, gcdfo and PSC IRI must be
  declared at its pin: build with `GraphBuilder(vocab)` and call
  `assert_vocab()` before writing. Nothing goes under `def:` (read-only
  legacy prefix of the NuSEDS graph).
- **Determinism.** Same inputs, same bytes. Write RDF only through `io.det`
  (or the builder's writers), JSON with `io.det.write_json`, CSV with
  `io.det.write_csv` after sorting rows. Dates come from inputs or an explicit
  `build_date` argument (YYYY-MM-DD), never the wall clock. No absolute paths
  in outputs: use `io.det.portable_path`. Blank nodes only via
  `GraphBuilder.bnode(key)`. Parquet is written with pyarrow, zstd, rows
  sorted by their IRI key; its bytes are stable for a fixed pyarrow version,
  which the manifest records.
- **D6.** Anything a source does not state is marked with
  `provenance.mark_derived` or `provenance.mark_statement` (section 6).
- **Licensing (D2).** Unconfirmed redistribution never reaches a public
  release (`spec.DatasetSpec.public`).
- **Secrets.** Never read, print or store credentials; publication modules
  only prepare plans (section 9).

## 3. Configuration (`salmongraph.config`)

| Variable | Default | Meaning |
|---|---|---|
| `SALMONGRAPH_BASE` | `https://w3id.org/salmon-demo-corpus/` | instance base (provisional, ADR-0001 D10; proposal `https://w3id.org/smn/data/`) |
| `SALMONGRAPH_PROFILE_BASE` | `<BASE>profile/` | corpus profile terms, prefix `corp:` (proposal `https://w3id.org/smn/profile/corpus/`) |
| `SALMONGRAPH_SDPV_NS` | `<PROFILE>sdp/` | SDP vocabulary properties, prefix `sdpv:` (provisional: see 3.2) |
| `SALMONGRAPH_SMN_TTL` | `~/code/salmon-domain-ontology/salmon-domain-ontology.ttl` | smn flat build |
| `SALMONGRAPH_GCDFO_URL` / `SALMONGRAPH_GCDFO_TTL` | raw `main` URL / unset | gcdfo source / local file instead |
| `SALMONGRAPH_PSC_URL` / `SALMONGRAPH_PSC_TTL` | `https://w3id.org/psc/vocab/psc-vocabularies.ttl` / unset | PSC CV source / local file instead (e.g. a clone's `public/psc-vocabularies.ttl`) |
| `SALMONGRAPH_VOCAB_CACHE` | `data/raw/_vocab/` | download cache (git-ignored) |
| `SALMONGRAPH_OFFLINE` | unset | `1`: no network |

```python
config.ROOT: Path                         # repository root
config.Config(base=..., profile_base=None, sdpv=None)   # frozen, validated
    .ns -> dict[str, str]                 # STATIC_NS + corpus, id, corp, sdpv
    .legacy_ns -> {"def": ...}            # read-only
    .prefixes -> dict[str, str]           # ns + legacy, sorted: the serialisation map
    .excluded_subtrees -> tuple[str, ...] # what the guard never treats as terms
config.current() -> Config                # innermost override, else the environment (cached)
config.override(cfg=None, **fields)       # context manager; fields are NOT merged with env
config.reset() -> None                    # re-read the environment next time
config.BASE, .PROFILE, .SDPV, .NS, .PREFIXES   # dynamic module attributes
config.SMN_NS, GCDFO_NS, PSC_VOCAB_NS, PSC_CONCEPT_NS, PSC_SCHEME_NS
config.SMN_DATA_SUBTREE, SMN_PROFILE_CORPUS_SUBTREE
config.DATASET_GRAPH_PARTS, SHARED_GRAPHS, RESERVED_SLUGS, LAYOUT
```

A `Config` refuses a base that contains a vocabulary namespace (it would
switch the guard off), a base under gcdfo or the PSC CV, and a profile base
equal to the base.

### 3.1 Prefixes

The fixed prefixes (`config.STATIC_NS`) keep exactly the IRIs of
`pipelines/corpuslib.NS` (rdf, rdfs, xsd, owl, skos, dcterms, dcat, prov, qb,
csvw, sosa, schema = `https://schema.org/`, foaf, geo, wgs, iop, smn, gcdfo,
obo, unit, qk, sssom, dwc, dqv, oa) and add pav `http://purl.org/pav/`, void
`http://rdfs.org/ns/void#`, semapv `https://w3id.org/semapv/vocab/` (as
metasalmonpy's SSSOM code), qudt `http://qudt.org/schema/qudt/` and psc
`https://w3id.org/psc/vocab/concept/`. Configurable: `corpus` = BASE (the
architecture's `data:`), `id` = BASE + `id/`, `corp` = PROFILE, `sdpv`.

### 3.2 The `sdpv:` namespace

metasalmonpy defines **no RDF namespace** for the SDP: its `sdp:` keys
(`sdp:columnRole`, `sdp:termIri`, `sdp:termType`, `sdp:unitIri`,
`sdp:unitLabel` in field `custom` blocks; `sdp:table`, `sdp:requirement` and
others in the schema files) are JSON keys, never bound to an IRI, in
metasalmonpy 0.6.0 or metasalmon. So `sdpv:` is provisional and sits in the
corpus profile until smn-data-pkg or smn publishes one (architecture.md 18,
question 3). Before minting an `sdpv:` term, check these, which already fit
most needs:

| Need | Reuse |
|---|---|
| column of a table | `csvw:column`, `csvw:name`, `csvw:title`, `csvw:datatype` |
| unit of a column or observation | `qudt:unit` (as the NuSEDS pipeline does) |
| observed property of an observation | `sosa:observedProperty`; `qb:measureType` in a Data Cube |
| numeric result | `sosa:hasSimpleResult`, or the measure property in a Data Cube |
| standard uncertainty | `qudt:standardUncertainty` |
| method | `sosa:usedProcedure` (gcdfo method concepts, ADR-0001 D13) |
| variable decomposition | `iop:hasProperty`, `iop:hasObjectOfInterest`, `iop:hasConstraint`, `iop:hasStatisticalModifier` |
| concept measured by a component | `qb:concept` |

What has no fit yet (a column's variable concept; estimate type; CV; year as
a dimension with its basis) needs an `sdpv:` term, minted with
`iri.sdpv_term(localName)` and listed in section 6.4 with its reason.

## 4. IRI layout (`salmongraph.iri`)

All helpers take `cfg=None` (current configuration). Names (kind, authority,
slug, mapping set, scheme) are lower-case kebab tokens, checked and never
altered; make one from free text with `iri.slug()`. Values (local IDs,
versions, keys, column names, code values) are percent-encoded per segment
with `iri.segment()`, reversibly (`iri.unsegment()`); unreserved characters
pass unchanged, so `ident()` equals `corpuslib.ident()` for IDs like `7`,
`SEL-21-02` or `fraser-chilko`.

| Thing | Helper | Path under BASE |
|---|---|---|
| identity node | `ident(kind, authority, local_id)` | `id/{kind}/{authority}/{local}` |
| dataset release | `dataset(slug, version)` | `dataset/{slug}/{version}` |
| distribution | `distribution(slug, version, name)` | `dataset/{slug}/{version}/dist/{name}` |
| table / column | `table(slug, version, table)`, `column(slug, version, table, column)` | `.../table/{table}[/column/{column}]` |
| observation | `obs(slug, version, *key)` | `obs/{slug}/{version}/{key...}` |
| crosswalk assertion | `xwalk(mapping_set, n)` | `xwalk/{set}/{n}` |
| quality annotation | `quality(*path)` | `quality/{path...}` |
| membership assertion | `membership(source, version, key)` | `membership/{source}/{version}/{key}` |
| selection set | `selection(name, version)` | `selection/{name}/{version}` |
| dataset named graph | `named_graph(slug, version, part)`, `dataset_graphs(slug, version)` | `graph/{slug}/{version}/{part}` |
| shared corpus graph | `corpus_graph(name, corpus_version)` | `graph/corpus/{corpus-version}/{name}` |
| vocabulary graph | `vocab_graph(key, sha256)` (or `VocabIndex.graph_iri(key)`) | `graph/vocab/{key}/sha256-{16 hex}` |
| agent | `agent(kind, *path)`; `software_agent(name, version)`, `model_agent(model)`, `person_agent(name)`, `org_agent(name)` | `agent/{software\|model\|person\|org}/...` |
| activity | `activity(kind, *path)` | `activity/{build\|agent-run\|combine\|release\|review\|ingest\|publish}/...` |
| corpus release | `release(version)` | `release/{version}` |
| source code value | `code(scheme, value)` | `code/{scheme...}/{value}` |
| profile term | `profile_term(localName)` | `{PROFILE}{localName}` |
| profile SKOS | `profile_scheme(scheme)`, `profile_concept(scheme, concept)` | `{PROFILE}{scheme}[/{concept}]` |
| SDP vocabulary term | `sdpv_term(localName)` | `{SDPV}{localName}` |

Also: `iri.stable_key(*parts, length=16)` (deterministic key: use it for
crosswalk and quality IRIs), `iri.check_mintable(iri)` (the guards below),
`iri.parse(iri) -> ParsedIRI | None` (invert the layout, for debugging and
`describe()`), `iri.MintError`.

Guards on every minted IRI: under BASE or PROFILE; no query, fragment,
whitespace or dot segment; dataset slugs `corpus` and `vocab` are reserved;
and **never a single-segment IRI directly under `https://w3id.org/smn/`**
(section 6.2 condition 2), which matters once BASE moves under smn.

Persistence (6.2 condition 4): a published IRI is never reused for something
else. Key observations, crosswalks and memberships on source identifiers or
`stable_key`, never on row numbers. Version-specific things carry the version.

## 5. Named graphs

| Graph | IRI | Written by | Contents |
|---|---|---|---|
| dataset `metadata` | `named_graph(slug, v, "metadata")` | executor | DCAT dataset + distributions, CSVW tables/columns, variables, licence, attribution |
| dataset `mappings` | `named_graph(slug, v, "mappings")` | executor | source codes as SKOS concepts, their mappings |
| dataset `identity` | `named_graph(slug, v, "identity")` | executor | authority nodes this dataset mentions |
| dataset `cube` | `named_graph(slug, v, "cube")` | executor | RDF Data Cube / SOSA aggregates |
| dataset `provenance` | `named_graph(slug, v, "provenance")` | executor | build activity, inputs, checksums, tool versions, `VocabIndex.provenance()` |
| shared `identity` | `corpus_graph("identity", cv)` | combine / identity | nodes from published identity sources |
| shared `membership` | `corpus_graph("membership", cv)` | combine / identity | published roll-ups (reified) |
| shared `crosswalk` | `corpus_graph("crosswalk", cv)` | combine / identity | equivalence assertions (reified, SSSOM terms) |
| shared `quality` | `corpus_graph("quality", cv)` | combine | DQV annotations of cross-source discrepancies |
| shared `review` | `corpus_graph("review", cv)` | review | human decision records |
| shared `vocab-pins` | `corpus_graph("vocab-pins", cv)` | combine | `VocabIndex.provenance()` + `provenance.profile_vocabulary()` |
| shared `catalog` | `corpus_graph("catalog", cv)` | catalog | VoID + DCAT of the release and every graph |
| vocabulary content | `VocabIndex.graph_iri(key)` | combine (`VocabIndex.load_into`) | smn, gcdfo, PSC CV as loaded |

`cv` is the corpus version (for example `2026.10.27`). D6 marks live in the
graph of the statement they mark. Queries use the union of named graphs as
the default graph.

## 6. D6 marks (`salmongraph.provenance`)

### 6.1 The pattern

```turtle
<target>  prov:wasAttributedTo <agent/model/claude-...> ;
          prov:wasGeneratedBy  <activity/agent-run/20261024T...-psc-fraser-sr> ;
          prov:wasDerivedFrom  <https://doi.org/...> , _:e ;    # cited source / text evidence
          corp:confidence  corp:highConfidence ;                 # | mediumConfidence | lowConfidence
          corp:criticality corp:critical ;                       # | nonCritical
          corp:reviewStatus corp:awaitingReview ;                # agentAccepted only for high + nonCritical
          dcterms:created "2026-10-24"^^xsd:date .               # optional
_:e a prov:Entity ; prov:value "totals agree within 0.5% for 66/68 brood years" .
<activity/...> a prov:Activity ; dcterms:date "2026-10-24"^^xsd:date ; prov:wasAssociatedWith <agent/...> .
```

`<target>` is a reifier (`xw rdf:reifies <<( s p o )>>`) when one statement
is agent-derived, or a node when the node is agent-generated as a whole.
Exactly one `corp:reviewStatus` per target in any built store.

### 6.2 Functions (stable signatures)

```python
provenance.CONFIDENCE_LEVELS = ("high", "medium", "low")
provenance.CRITICALITY_LEVELS = ("critical", "non-critical")
provenance.REVIEW_STATUSES = ("agentAccepted", "awaitingReview", "humanAccepted", "humanAmended", "rejected")
provenance.REVIEWED_STATUSES = {"agentAccepted", "humanAccepted", "humanAmended"}
provenance.CRITICAL_ASPECTS      # identity-equivalence, membership, measure-counts, unit-scale,
                                 # year-basis, age-notation, estimate-type, licence
provenance.NON_CRITICAL_ASPECTS  # label, description, keyword, documentation-link
provenance.criticality_of(aspect) -> "critical" | "non-critical"
provenance.review_status(confidence, criticality) -> "agentAccepted" | "awaitingReview"
provenance.terms(cfg=None) -> ProfileTerms(confidence, criticality, review_status, schemes, values)
provenance.token_of(concept_iri, cfg=None) -> str | None
provenance.profile_vocabulary(graph, *, cfg=None) -> list[Quad]
provenance.mark_derived(builder, target, *, agent, activity, evidence, confidence,
                        criticality, graph, date=None) -> status
provenance.mark_statement(builder, reifier, s, p, o, *, graph, agent, activity, evidence,
                          confidence, criticality, assert_triple=True, date=None) -> status
provenance.software_agent(builder, name, version, *, graph, label=None) -> iri
provenance.ai_agent(builder, model, *, graph, label=None, on_behalf_of=None) -> iri
provenance.person_agent(builder, name, *, graph, orcid=None) -> iri
provenance.activity_node(builder, activity, *, graph, label, date, used=(), associated_with=(),
                         informed_by=(), started_at=None, ended_at=None) -> iri
```

Extend only by adding keyword arguments with defaults.

### 6.3 Criticality

Critical means it can change a number or a join: identity equivalence or
membership; what a measure counts (sex, the effective adjustment, origin,
life stage, jacks); unit or scale; year basis; age notation; estimate type;
licence or access. Use `criticality_of(aspect)` instead of choosing by hand.

### 6.4 Corpus profile terms minted, and why

Checked on 2026-10-23 against PROV, PAV, DQV, SSSOM, VoID, DCAT and
schema.org. Every term below is declared by `profile_vocabulary()`.

| Term | Why no existing term fits |
|---|---|
| `corp:confidence` | `sssom:confidence` is a number in [0, 1] for mappings; D6 needs an ordinal (high/medium/low) for any assertion, and inventing numbers would misstate it. PROV, PAV, DQV, VoID, DCAT and schema.org have no confidence property. `sssom:confidence` is still written beside it when a crosswalk has a score. |
| `corp:criticality` | No vocabulary in the list has a property for "can change a number or a join". |
| `corp:reviewStatus` | `schema:creativeWorkStatus` is closest, but its domain is a creative work and its values are free text, and the PSC CV already uses it on its concepts ("active"), so reusing it would mix review states with PSC term statuses in one store. PAV has who and when (`pav:curatedBy`, `pav:curatedOn`, used by `review.py`) but no state; SSSOM, DQV, PROV, VoID and DCAT have none. |
| `corp:confidenceLevels`, `corp:criticalityLevels`, `corp:reviewStatuses` | SKOS concept schemes holding the values of the three properties above. |
| `corp:highConfidence`, `corp:mediumConfidence`, `corp:lowConfidence`, `corp:critical`, `corp:nonCritical`, `corp:agentAccepted`, `corp:awaitingReview`, `corp:humanAccepted`, `corp:humanAmended`, `corp:rejected` | Values of the properties above, as SKOS concepts with the ADR token as `skos:notation`. |

Reused instead of minted: evidence (`prov:wasDerivedFrom`, `prov:value`),
agent (`prov:wasAttributedTo`), activity (`prov:wasGeneratedBy`), dates
(`dcterms:date`, `dcterms:created`), reviewer and decision time
(`pav:curatedBy`, `pav:curatedOn`), validity periods of memberships
(`schema:validFrom`, `schema:validThrough`), selection-set inclusion
(`prov:Collection`, `prov:hadMember`). The architecture's placeholders
`corp:validFrom`, `corp:SelectionSet` and `corp:includes` are therefore not
needed; `corp:excludes` may be (identity.py docstring).

## 7. Files and locations

| Path (repository root) | Committed | Written by | Contents |
|---|---|---|---|
| `specs/<slug>.yaml` | yes | agents | dataset spec (`spec.py` docstring has the YAML shape) |
| `data/raw/<slug>/` | no | fetch | source files, `SHA256SUMS`, `source.json` |
| `data/raw/_vocab/` | no | `VocabIndex` | gcdfo and PSC CV caches, `<file>.pin.json` |
| `build/<slug>/<version>/` | no | executor | `dataset.trig`, `observations.parquet`, `sdp/`, `report.md`, `report.json`, `review-queue.csv`, `manifest.json` |
| `build/corpus/<corpus-version>/` | no | combine | `store/`, `shared.trig`, `crosswalk.sssom.tsv`, `checks.json`, `summary.json` |
| `dist/corpus-<version>/` | no | release | `corpus.trig.gz`, `void.ttl`, `observations/`, `schemaorg/`, `sdp/`, `review-queue.csv`, `ledger.csv`, `ATTRIBUTION.md`, `manifest.json`, `SHA256SUMS` (and `zenodo.json`) |
| `releases/<version>/manifest.json` | yes | release | the release manifest, byte for byte |
| `reviews/decisions.csv` | yes | people | human review decisions (`review.DECISION_COLUMNS`) |
| `runs/ledger.csv` | yes | ledger | one row per dataset per run (`ledger.LEDGER_COLUMNS`) |
| `salmongraph/shapes/*.ttl` | yes | shapes | SHACL shapes |

`<version>` in a path is `iri.segment(version)`.

## 8. Implemented modules: public API

### `salmongraph.vocab`

```python
VocabIndex(sources=None, *, cfg=None, offline=None, refresh=False, timeout=60.0)
    .pins: dict[str, VocabPin]        # key, namespace, title, ontology_iri, url, path (portable),
                                      # sha256, triples, version, version_kind, version_info,
                                      # repository, version_note
    .owner(iri) -> "smn" | "gcdfo" | "psc" | None
    .is_guarded(iri) -> bool          # in a vocabulary namespace and not excluded
    .exists(iri) -> bool              # declared by the OWNING source at its pin
    .check(iris) -> list[str]         # sorted undeclared guarded IRIs; [] = good
    .label(iri) -> str | None         # skos:prefLabel, then rdfs:label; @en first
    .declared(key) -> frozenset[str]
    .graph_iri(key) -> str
    .quads(key) -> list[Quad]
    .load_into(store) -> {key: graph IRI}
    .store -> pyoxigraph.Store        # all three, lazily
    .pins_dict() -> {key: dict}       # for manifests
    .provenance(graph, *, include_paths=False) -> list[Quad]
default_sources(env=None) -> list[VocabSource]
VocabularyError, UndeclaredIRIError(.iris)
```

Declared means: subject of an `rdf:type` triple in the source that owns the
namespace, or a version IRI that source names. Not guarded: the smn sub-trees
`data/` and `profile/corpus/`, the base and profile base when under a
vocabulary namespace, each namespace root, and the PSC CV's document IRIs
(`psc-vocabularies.ttl/.jsonld`, `release/...`, `concept|scheme/{id}.ttl|.jsonld`).
Version kinds: `git-commit` (last commit touching the file), `git-commit-dirty`,
`release-tag`, `declared`, `unknown` (with `version_note`).

### `salmongraph.graph`

```python
GraphBuilder(vocab=None, *, cfg=None)      # alias G
    .add(s, p, o, graph) -> Quad           # strings are IRIs or CURIEs; literals via L()
    .extend(quads); .type(s, cls, graph); .label(s, text, graph, *, lang="en", predicate="rdfs:label")
    .reify(reifier, s, p, o, graph, *, assert_triple=False) -> NamedNode
    .bnode(*key) -> BlankNode              # deterministic label
    .undeclared() -> list[str]; .assert_vocab()
    .quads; len(); .graphs() -> {graph: count}; .to_store(store=None)
    .nquads() -> bytes; .trig(prefixes=None) -> bytes
    .write_nquads(path, *, gzip=None); .write_trig(path, *, gzip=None, prefixes=None)
    .marked: dict[str, str]                # maintained by provenance
expand(curie_or_iri, *, cfg=None); N(iri_or_curie); L(value, dtype=None, lang=None)
RDF_REIFIES
```

The default graph is refused. `L()` unwraps numpy/pandas scalars and
refuses missing values. SPARQL finds reifiers with
`?r rdf:reifies <<( ?s ?p ?o )>>`.

### `salmongraph.io.det`

```python
sorted_quads(quads); nquads_bytes(quads); trig_bytes(quads, prefixes=None, *, only_used=True)
used_prefixes(quads, prefixes); term_key(term); quad_key(quad)
gzip_bytes(data, *, level=9)               # mtime 0, no file name
write_bytes(path, data, *, gzip=None)      # atomic; gzip when path ends .gz
write_text(path, text, *, gzip=None); json_bytes(obj); write_json(path, obj)
csv_bytes(header, rows); write_csv(path, header, rows)
sha256_bytes(data); sha256_file(path); file_record(path, *, root=None)
portable_path(path, *, root=None)          # repo-relative, else ~/..., else <external>/name
```

## 9. Downstream modules: signatures

Details, inputs and outputs are in each docstring.

### `salmongraph.spec`

`SPEC_VERSION`, `SPECS_DIR`, `SpecError`, `DatasetSpec` (`.public`),
`spec_path(slug)`, `load_spec(path_or_slug)`, `validate_spec(spec, vocab) -> list[str]`,
`spec_sha256(spec)`.

### `salmongraph.executor`

`BUILD_DIR`, `BUILD_FILES`, `AgentRun(run_id, model, date)`, `BuildResult`,
`build_dir(slug, version)`,
`build_dataset(spec, *, build_date, vocab=None, raw_dir=None, out_dir=None, run=None, validate=True) -> BuildResult`,
`compile_dataset_graph(spec, sdp_dir, *, builder, build_date, run=None) -> {part: graph}`,
`write_observations(spec, frames, path) -> int`.
`observations.parquet` columns: `obs_iri` (unique, sorted), `dataset_iri`,
`measure_iri`, `value`, `unit_iri`, `year`, `year_basis_iri`,
`<dimension>_iri`..., optional `standard_error`, `cv`, `lower`, `upper`,
`estimate_type_iri`, `method_iri`, and `review_status`.

### `salmongraph.identity`

`MembershipRow`, `authority_node(builder, kind, authority, local_id, *, graph, label, source, types=(), species=None, region=None, identifier=None)`,
`load_dfo_smu_cu_du(path, *, source_version) -> list[MembershipRow]`,
`add_membership(builder, row, *, graph, predicate="skos:broader", assert_triple=True)`,
`add_crosswalk(builder, subject, predicate, obj, *, mapping_set, graph, justification, evidence, confidence_score=None, published_source=None, agent=None, activity=None, confidence=None, date=None)`,
`selection_set(builder, name, version, *, graph, label, includes, excludes, agent=None, activity=None)`.

### `salmongraph.combine`

`CORPUS_BUILD_DIR`, `CombineResult`, `corpus_build_dir(corpus_version)`,
`load_dataset_build(store, build_dir) -> manifest`,
`combine(build_dirs, *, corpus_version, build_date, vocab=None, out_dir=None) -> CombineResult`,
`run_cross_source_checks(store, *, corpus_version, build_date, parquet_dirs) -> dict`.

### `salmongraph.shapes` and `salmongraph.validate`

`shapes.SHAPES_DIR`, `shapes.shape_files()`;
`validate.Violation`, `validate.ValidationReport`, `validate.ShaclViolationError`,
`validate.for_shacl(quads)` (rewrites `?r rdf:reifies <<( s p o )>>` as a
literal so pyshacl/rdflib can read it), `validate.validate(data, *, shapes=None, graphs=None)`,
`validate.assert_valid(data, *, shapes=None, graphs=None)`.

### `salmongraph.review`

`REVIEW_QUEUE_COLUMNS`, `DECISION_COLUMNS`, `DECISIONS_PATH`, `VIEWS`,
`ReviewItem`, `Decision`, `review_queue(data, *, graphs=None)`,
`write_review_queue(items, path)`, `load_decisions(path=DECISIONS_PATH)`,
`apply_decisions(builder, decisions, *, graph) -> missing targets`,
`view_store(store, view="reviewed")`, `status_counts(data)`.

### `salmongraph.ledger`

`LEDGER_PATH`, `LEDGER_COLUMNS`, `LedgerRow`, `append_run(row, path=LEDGER_PATH)`,
`read_ledger(path=LEDGER_PATH)`.

### `salmongraph.catalog`

`graph_triple_counts(store)`,
`describe_dataset_release(builder, *, slug, version, graphs, counts, graph)`,
`describe_corpus_release(builder, *, corpus_version, build_date, datasets, shared_graphs, vocab, counts, graph)`.

### `salmongraph.release`

`DIST_DIR`, `RELEASES_DIR`, `ReleaseResult`, `dist_dir(corpus_version)`,
`build_release(combined, *, build_dirs, build_date, public=True)`,
`verify_release(path) -> problems`. The manifest fields are in the docstring;
every `.gz` file also records `content_sha256` of its uncompressed bytes,
because compressed bytes can differ between zlib builds.

### `salmongraph.serve`

`sparql_server.query(store_dir, sparql, *, view="reviewed")`,
`sparql_server.serve(store_dir, *, host="127.0.0.1", port=7878)`,
`sparql_server.main(argv=None)`;
`mcp_server.TOOLS` = sparql, sql, describe, datasets, review_queue;
`mcp_server.build_server(store_dir, parquet_dir, *, name="salmon-corpus")`,
`mcp_server.main(argv=None)`. Default view: reviewed.

### `salmongraph.publish`

`schemaorg.dataset_jsonld(store, dataset_iri)`,
`schemaorg.write_dataset_jsonld(store, dataset_iri, path)`;
`knb.plan_dataset_publication(sdp_dir, *, manifest_path, eml_path=None, public=None)`,
`knb.plan_release_publication(release_dir)` (dry runs only);
`zenodo.deposition_metadata(manifest)`, `zenodo.write_deposition_metadata(release_dir)`.
Nothing here uploads; Brett runs uploads.

## 10. Known gaps in this version

- `sdpv:` has no published home (3.2).
- The PSC CV default URL is the latest complete Turtle; its version is the
  release tag whose manifest lists the same sha256, found from a local clone
  or the release index. Pin a release explicitly with
  `SALMONGRAPH_PSC_URL=https://w3id.org/psc/vocab/release/<tag>/psc-vocabularies.ttl`.
- gcdfo's version is the last commit on `main` touching `ontology/dfo-salmon.ttl`
  whose bytes match the cache (GitHub API); offline and with no `.pin.json`
  it is `unknown`.
- `iri.parse()` is for debugging; it does not round-trip multi-segment keys exactly.
