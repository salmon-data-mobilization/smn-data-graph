# Shared rules for corpus-building agents

## Why this work exists

Brett Johnson (Pacific Salmon Commission) presents "The salmon data integration
toolkit: Making salmon data reusable across contexts" at PICES-2026, session
S12, Nanaimo, on Wed 28 Oct 2026. The toolkit is: Salmon Data Packages (SDPs),
the Salmon Domain Ontology, and metasalmon / metasalmonpy. The demo is a corpus
of real, open, interoperable salmon datasets that agents packaged as SDPs and
compiled into one queryable graph. No such corpus or production salmon data
graph exists yet. Brett's NPAFC abstract says a salmon knowledge graph is "a
possible consequence of adoption" and that there is "not yet evidence of
reduced integration cost at scale". This corpus is the first evidence, so the
real cost, time and breakage of each dataset matter as much as the outputs.

## Workspace

- Project root: `{PROJECT}`. Write only inside it. Shell commands run in a
  sandbox that blocks writes elsewhere and allows only a fixed list of hosts
  (Zenodo, DOI, w3id, purl, W3C, QUDT, NERC, ICES, EBI OLS, TDWG, GBIF, WoRMS,
  GitHub and GitHub Pages for the salmon ontologies, Creative Commons). If a host is blocked, record it in the report and work around it.
- Python: use `{PROJECT}/.venv/bin/python`. It already has metasalmonpy 0.6.0,
  pyoxigraph and DuckDB. Do not install packages and do not run uv or pip.
- Reference repositories, read-only: `~/code/metasalmonpy` (source, `guides/`,
  `docs/`), `~/code/metasalmon` (R package; graph design note:
  `knowledge/plans/2026-09-04-okf-graphify-semantic-knowledge-workflow.md`,
  sections 10-12 and 18), `~/code/salmon-domain-ontology`,
  `~/code/salmon-knowledge-commons`. Read only what you need.
- Do not run `git commit` or `git push`. Brett reviews first.

## Layout (one dataset = one slug)

- `data/raw/<slug>/`: downloaded files, `SHA256SUMS`, `source.json` (URL, DOI,
  licence, version, retrieval time). Git-ignored.
- `packages/<slug>/`: the SDP. Large data files under `packages/<slug>/data/`
  are git-ignored, so keep metadata and small files outside that folder.
- `pipelines/<slug>.py`: one script that rebuilds the package, the graph and
  the query results from `data/raw/<slug>/`. Write code, not one-off commands,
  so a reviewer can run the whole build again.
- `graph/<slug>.ttl` (or `.trig`): the RDF for this dataset. If it is over
  about 20 MB, write it gzipped. On-disk stores go in `graph/store/`
  (git-ignored).
- `queries/<slug>/NN-name.rq` plus `NN-name.csv` results.
- `runs/<run-id>/report.md` is written by you (see below). The runner writes
  `run.json` and the transcript in the same folder; find the newest folder in
  `runs/` that has no `report.md` yet - that is yours.

## How to work

- Budget: about ${BUDGET_USD} of API cost for this whole run; the run stops
  when it is used. Build a thin end-to-end slice first (download, profile,
  minimal SDP, small graph, two or three queries), write the report, then
  deepen. Update the report after each phase, so a stopped run still leaves a
  useful report.
- Finish all work in the foreground before your final message. If you start a
  background command, wait for it to end (poll its log file; `pgrep` is
  blocked in the sandbox) before you finish. The run ends at your final
  message, and later edits are refused.
- Never Read a large data file. Profile it with DuckDB (row counts, columns,
  types, distinct values, null rates, examples).
- Use metasalmonpy for the package and its semantics (`create_sdp`,
  `infer_dictionary`, `find_terms`, `suggest_semantics`, `apply_sdp_semantics`,
  observation structures, measurement decompositions, `write_sdp_sssom`,
  `validate_salmon_datapackage`, `detect_semantic_term_gaps`). Read the source
  or guides for exact signatures; do not guess.
- Never invent ontology IRIs. Use a term only if term search or the ontology
  files show it exists. Mark gaps as gaps; they become term requests.
- Graph design: metadata and semantic graph in RDF (DCAT for the dataset and
  distribution; tables and columns linked to I-ADOPT variables and ontology
  concepts; units, methods, estimate types; PROV-O provenance; identity nodes
  for stocks, CUs, streams with their source IDs). Keep full row-level data
  in Parquet keyed by the same IRIs, and materialise a useful aggregate as
  W3C RDF Data Cube observations (`qb:`). Use one base IRI for minted
  corpus resources: `https://w3id.org/salmon-demo-corpus/` (provisional; say
  so in the report).
- Keep the source licence and attribution in the package and the graph.

## Report (`runs/<run-id>/report.md`)

Plain, short sections: what was built (paths, row and triple counts); time
spent per phase (approximate); what broke or was confusing in metasalmonpy,
the ontology or the data, with the workaround; term gaps found; decisions
and why; what the next dataset should reuse; and open questions for Brett.
Be exact and honest: say what did not work.
