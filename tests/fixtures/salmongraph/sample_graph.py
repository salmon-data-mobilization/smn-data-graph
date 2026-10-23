"""Build a small, fixed dataset graph two ways; used by the determinism tests.

Run as a script (``python sample_graph.py OUT_DIR [reverse]``) it writes
``sample.nq``, ``sample.trig`` and ``sample.trig.gz`` into OUT_DIR and prints
their sha256s as JSON, so a test can compare builds made in separate
processes with different hash seeds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from salmongraph import config, iri, provenance  # noqa: E402
from salmongraph.graph import GraphBuilder, L  # noqa: E402
from salmongraph.io import det  # noqa: E402

SLUG, VERSION = "test-dataset", "2026.10.23"


def statements(cfg: config.Config) -> list[tuple]:
    """(kind, args) steps in a fixed order; ``build`` may apply them in any order."""
    g = iri.dataset_graphs(SLUG, VERSION, cfg=cfg)
    xw = iri.corpus_graph("crosswalk", "2026.10.27", cfg=cfg)
    a = iri.ident("stock", "psc-frsk", 7, cfg=cfg)
    b = iri.ident("stock", "sasap", "107", cfg=cfg)
    ds = iri.dataset(SLUG, VERSION, cfg=cfg)
    steps = [
        ("add", (ds, "rdf:type", "dcat:Dataset", g["metadata"])),
        ("add", (ds, "dcterms:title", L("Test dataset", lang="en"), g["metadata"])),
        ("add", (ds, "dcterms:issued", L("2026-10-23", "xsd:date"), g["metadata"])),
        ("add", (a, "rdf:type", "smn:Population", g["identity"])),
        ("add", (a, "rdfs:label", L("Chilko"), g["identity"])),
        ("add", (b, "rdfs:label", L("Chilko River (SASAP) – é"), g["identity"])),
        ("add", (iri.obs(SLUG, VERSION, 7, 1990, "EFS", cfg=cfg), "sosa:hasSimpleResult",
                 L(412345.0), g["cube"])),
        ("add", (iri.obs(SLUG, VERSION, 7, 1991, "EFS", cfg=cfg), "sosa:hasSimpleResult",
                 L(12), g["cube"])),
        ("mark", (iri.xwalk("sasap-psc-fraser", iri.stable_key(b, "skos:closeMatch", a), cfg=cfg),
                  b, "skos:closeMatch", a, xw)),
    ]
    return steps


def build(reverse: bool = False, cfg: config.Config | None = None) -> GraphBuilder:
    cfg = cfg or config.Config()
    bld = GraphBuilder(cfg=cfg)
    steps = statements(cfg)
    if reverse:
        steps = list(reversed(steps))
    prov_graph = iri.named_graph(SLUG, VERSION, "provenance", cfg=cfg)
    model = provenance.ai_agent(bld, "test-model-1", graph=prov_graph)
    run = provenance.activity_node(bld, iri.activity("agent-run", "20261023T000000Z-test", cfg=cfg),
                                   graph=prov_graph, label="test run", date="2026-10-23",
                                   associated_with=[model])
    for kind, args in steps:
        if kind == "add":
            bld.add(*args)
        else:
            r, s, p, o, graph = args
            provenance.mark_statement(bld, r, s, p, o, graph=graph, agent=model, activity=run,
                                      evidence=["totals agree within 0.5% for 66/68 years",
                                                "https://doi.org/10.5281/zenodo.19959144"],
                                      confidence="high",
                                      criticality=provenance.criticality_of("identity-equivalence"))
    return bld


def write_all(out: Path, reverse: bool = False) -> dict[str, str]:
    b = build(reverse)
    paths = {"sample.nq": b.write_nquads(out / "sample.nq"),
             "sample.trig": b.write_trig(out / "sample.trig"),
             "sample.trig.gz": b.write_trig(out / "sample.trig.gz")}
    return {k: det.sha256_file(p) for k, p in sorted(paths.items())}


if __name__ == "__main__":
    out_dir = Path(sys.argv[1])
    print(json.dumps(write_all(out_dir, reverse=len(sys.argv) > 2 and sys.argv[2] == "reverse"),
                     sort_keys=True))
