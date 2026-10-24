"""Tests for the salmongraph foundation: config, iri, vocab, graph, io.det, provenance.

Run from the repository root::

    python -m pytest -q tests/test_foundation.py
"""

from __future__ import annotations

import datetime as dt
import gzip
import importlib
import importlib.util
import inspect
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyoxigraph as ox
import pytest

from conftest import FIXTURES, ROOT, tiny_sources
from salmongraph import config, iri, provenance
from salmongraph.config import Config, ConfigError
from salmongraph.graph import RDF_REIFIES, GraphBuilder, L, N
from salmongraph.io import det
from salmongraph.vocab import UndeclaredIRIError, VocabIndex

SMN = config.SMN_NS
GCDFO = config.GCDFO_NS
PSC = config.PSC_CONCEPT_NS
DEFAULT = config.DEFAULT_BASE


def _load_corpuslib():
    spec = importlib.util.spec_from_file_location("corpuslib_under_test", ROOT / "pipelines" / "corpuslib.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sample():
    spec = importlib.util.spec_from_file_location("sample_graph", FIXTURES / "sample_graph.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# config
# ==========================================================================

def test_default_layout():
    c = config.current()
    assert c.base == DEFAULT
    assert c.profile_base == DEFAULT + "profile/"
    assert c.sdpv == DEFAULT + "profile/sdp/"
    assert c.ns["corpus"] == DEFAULT and c.ns["id"] == DEFAULT + "id/"
    assert c.ns["corp"] == c.profile_base and c.ns["sdpv"] == c.sdpv
    assert list(c.prefixes) == sorted(c.prefixes)
    assert c.excluded_subtrees == (config.SMN_DATA_SUBTREE, config.SMN_PROFILE_CORPUS_SUBTREE)


def test_env_overrides(monkeypatch):
    monkeypatch.setenv(config.ENV_BASE, "https://example.org/corpus/")
    config.reset()
    assert config.current().base == "https://example.org/corpus/"
    assert config.BASE == "https://example.org/corpus/"          # dynamic module attribute
    assert config.PROFILE == "https://example.org/corpus/profile/"
    assert iri.ident("cu", "dfo", "SEL-21-02") == "https://example.org/corpus/id/cu/dfo/SEL-21-02"
    monkeypatch.setenv(config.ENV_PROFILE_BASE, "https://example.org/profile/")
    monkeypatch.setenv(config.ENV_SDPV_NS, "https://example.org/sdp#")
    config.reset()
    assert config.current().profile_base == "https://example.org/profile/"
    assert iri.profile_term("reviewStatus") == "https://example.org/profile/reviewStatus"
    assert iri.sdpv_term("columnRole") == "https://example.org/sdp#columnRole"


def test_override_context_is_scoped():
    with config.override(base="https://w3id.org/smn/data/") as c:
        assert c.profile_base == "https://w3id.org/smn/data/profile/"
        assert iri.ident("cu", "dfo", "CK-01") == "https://w3id.org/smn/data/id/cu/dfo/CK-01"
        with config.override(base="https://w3id.org/smn/data/",
                             profile_base="https://w3id.org/smn/profile/corpus/"):
            assert iri.profile_term("criticality") == "https://w3id.org/smn/profile/corpus/criticality"
    assert config.current().base == DEFAULT


@pytest.mark.parametrize("bad", [
    {"base": "https://w3id.org/smn/"},          # would switch the smn guard off
    {"base": "https://w3id.org/"},              # contains every vocabulary namespace
    {"base": "https://w3id.org/gcdfo/salmon/x/"},  # not under gcdfo#, but check the next
    {"base": "https://w3id.org/psc/vocab/data/"},  # another authority's namespace
    {"base": "https://example.org/no-slash"},
    {"base": "https://example.org/a#b/"},
    {"base": "ftp://example.org/x/"},
    {"base": "https://example.org/x/", "profile_base": "https://example.org/x/"},
])
def test_config_refuses_unsafe_layouts(bad):
    if bad == {"base": "https://w3id.org/gcdfo/salmon/x/"}:
        # Not under the gcdfo namespace (which ends in '#'), so this one is allowed.
        assert Config(**bad).base == bad["base"]
        return
    with pytest.raises(ConfigError):
        Config(**bad)


def test_static_namespaces_match_corpuslib_and_metasalmonpy():
    cl = _load_corpuslib()
    for key, value in cl.NS.items():
        if key in ("corpus", "id", "def"):
            continue
        assert config.STATIC_NS[key] == value, key
    c = Config()
    assert c.ns["corpus"] == cl.NS["corpus"] and c.ns["id"] == cl.NS["id"]
    assert c.legacy_ns["def"] == cl.NS["def"]
    sssom = importlib.import_module("metasalmonpy.sssom")
    for key in ("semapv", "sssom", "skos", "owl", "rdf", "rdfs", "xsd"):
        assert config.STATIC_NS[key] == sssom._BUILTIN_PREFIXES[key], key
    assert config.STATIC_NS["psc"] == "https://w3id.org/psc/vocab/concept/"


# ==========================================================================
# iri
# ==========================================================================

def test_ident_matches_corpuslib_for_unreserved_ids():
    cl = _load_corpuslib()
    for kind, auth, local in [("cu", "dfo", "SEL-21-02"), ("cu", "psf", 7), ("stock", "psc-frsk", "7"),
                              ("stock", "salmonprize", "fraser-chilko"),
                              ("stream", "dfo-nuseds-gfe", 12345), ("population", "dfo-nuseds", "a.b_c~d")]:
        assert iri.ident(kind, auth, local) == cl.ident(kind, auth, local)
    assert iri.ident("cu", "psf", np.int64(7)) == iri.ident("cu", "psf", 7)


@pytest.mark.parametrize("value", ["Total Escapement", "a/b", "ünïcödé", "100%", "x?y#z", ".", "..",
                                   "  padded ", "CK-01", 1990, "SEL_21.02~x"])
def test_segment_is_reversible(value):
    seg = iri.segment(value)
    assert "/" not in seg and " " not in seg and seg not in (".", "..")
    assert iri.unsegment(seg) == str(value)


@pytest.mark.parametrize("missing", [None, float("nan"), "", True])
def test_missing_values_are_refused(missing):
    with pytest.raises(iri.MintError):
        iri.segment(missing)


def test_names_are_checked_not_rewritten():
    with pytest.raises(iri.MintError):
        iri.ident("CU", "dfo", "x")
    with pytest.raises(iri.MintError):
        iri.ident("cu", "dfo nuseds", "x")
    assert iri.slug("Fraser / Chilko") == "fraser-chilko"
    assert iri.slug("Pacific Salmon Foundation") == _load_corpuslib().slug_iri("Pacific Salmon Foundation")
    with pytest.raises(iri.MintError):
        iri.slug("---")


def test_layout_helpers():
    B = DEFAULT
    assert iri.dataset("psc-fraser-sr", "2026.05.07") == B + "dataset/psc-fraser-sr/2026.05.07"
    assert iri.distribution("psf-nuseds-cleaned", "2026-02-20", "csv") == B + "dataset/psf-nuseds-cleaned/2026-02-20/dist/csv"
    assert iri.column("psc-fraser-sr", "2026.05.07", "sr_summary", "total_broodyr_EFS") == \
        B + "dataset/psc-fraser-sr/2026.05.07/table/sr_summary/column/total_broodyr_EFS"
    assert iri.obs("psc-fraser-sr", "2026.05.07", "FRSK-07", 1990, "EFS") == \
        B + "obs/psc-fraser-sr/2026.05.07/FRSK-07/1990/EFS"
    assert iri.xwalk("sasap-psc-fraser", 7) == B + "xwalk/sasap-psc-fraser/7"
    assert iri.quality("efs-vs-total", "sasap-107-1990") == B + "quality/efs-vs-total/sasap-107-1990"
    assert iri.membership("dfo-smu-cu", "2025-11-28", "CK-01") == B + "membership/dfo-smu-cu/2025-11-28/CK-01"
    assert iri.selection("fraser-sockeye-sr-reference", "2026-10") == B + "selection/fraser-sockeye-sr-reference/2026-10"
    assert iri.named_graph("psc-fraser-sr", "2026.05.07", "cube") == B + "graph/psc-fraser-sr/2026.05.07/cube"
    assert set(iri.dataset_graphs("x", "1")) == set(config.DATASET_GRAPH_PARTS)
    assert iri.corpus_graph("crosswalk", "2026.10.27") == B + "graph/corpus/2026.10.27/crosswalk"
    assert iri.vocab_graph("gcdfo", "ab" * 32) == B + "graph/vocab/gcdfo/sha256-" + "ab" * 8
    assert iri.software_agent("metasalmonpy", "0.6.0") == B + "agent/software/metasalmonpy/0.6.0"
    assert iri.model_agent("claude-opus-5-5") == B + "agent/model/claude-opus-5-5"
    assert iri.activity("build", "psc-fraser-sr", "2026.05.07") == B + "activity/build/psc-fraser-sr/2026.05.07"
    assert iri.release("2026.10.27") == B + "release/2026.10.27"
    assert iri.code("nuseds/estimate-classification", "TRUE ABUNDANCE (TYPE-1)") == \
        B + "code/nuseds/estimate-classification/TRUE%20ABUNDANCE%20%28TYPE-1%29"
    assert iri.profile_concept("variables", "effective-female-spawners") == \
        B + "profile/variables/effective-female-spawners"
    for bad in (lambda: iri.dataset("corpus", "1"), lambda: iri.named_graph("x", "1", "other"),
                lambda: iri.corpus_graph("nope", "1"), lambda: iri.agent("robot", "x"),
                lambda: iri.activity("dance", "x"), lambda: iri.profile_term("has space"),
                lambda: iri.vocab_graph("smn", "not-a-digest")):
        with pytest.raises(iri.MintError):
            bad()


def test_parse_inverts_the_layout():
    p = iri.parse(iri.ident("stock", "sasap", "Total Esc/1"))
    assert p.kind == "id" and p.parts == {"kind": "stock", "authority": "sasap", "local": "Total Esc/1"}
    p = iri.parse(iri.column("psc-fraser-sr", "2026.05.07", "sr_summary", "total_broodyr_EFS"))
    assert p.kind == "column" and p.parts["column"] == "total_broodyr_EFS"
    p = iri.parse(iri.obs("psc-fraser-sr", "2026.05.07", "FRSK-07", 1990, "EFS"))
    assert p.kind == "obs" and p.parts["key"] == "FRSK-07/1990/EFS"
    p = iri.parse(iri.code("nuseds/estimate-classification", "FINAL"))
    assert p.kind == "code" and p.parts == {"scheme": "nuseds/estimate-classification", "value": "FINAL"}
    p = iri.parse(iri.corpus_graph("quality", "2026.10.27"))
    assert p.kind == "corpus_graph" and p.parts == {"version": "2026.10.27", "name": "quality"}
    assert iri.parse(iri.profile_term("reviewStatus")).kind == "profile"
    assert iri.parse("https://w3id.org/smn/Abundance") is None


def test_single_segment_smn_iri_is_refused():
    """Section 6.2 condition 2, with the base moved under smn as D10 proposes."""
    with config.override(base="https://w3id.org/smn/data/",
                         profile_base="https://w3id.org/smn/profile/corpus/") as c:
        for bad in ("https://w3id.org/smn/data", "https://w3id.org/smn/data/"):
            with pytest.raises(iri.MintError):
                iri.check_mintable(bad, cfg=c)
        ok = iri.ident("cu", "dfo", "SEL-21-02")
        assert ok == "https://w3id.org/smn/data/id/cu/dfo/SEL-21-02"
        assert iri.profile_concept("variables", "efs").startswith(config.SMN_PROFILE_CORPUS_SUBTREE)
    with pytest.raises(iri.MintError):
        iri.check_mintable("https://w3id.org/smn/Abundance")       # not under the base at all
    for bad in (DEFAULT + "id/a/b/c?x=1", DEFAULT + "id/a/b/c#x", DEFAULT + "id/a/../c",
                DEFAULT + "id/a b/c"):
        with pytest.raises(iri.MintError):
            iri.check_mintable(bad)


def test_stable_key():
    a = iri.stable_key("s", "skos:closeMatch", "o")
    assert a == iri.stable_key("s", "skos:closeMatch", "o") and len(a) == 16
    assert a != iri.stable_key("o", "skos:closeMatch", "s")
    assert iri.stable_key("ab", "c") != iri.stable_key("a", "bc")


# ==========================================================================
# vocab: hermetic tests on the fixture vocabularies
# ==========================================================================

def test_ownership_decides_declaration(tiny_vocab):
    v = tiny_vocab
    assert v.exists(SMN + "TermA") and v.exists(GCDFO + "MethodX") and v.exists(PSC + "PSC-CV-999999")
    # Declared in the wrong file: not a term of the owning vocabulary.
    assert not v.exists(GCDFO + "OnlyAnnotatedBySmn")
    assert not v.exists(SMN + "MirroredOnlyInGcdfo")
    # Mentioned but never declared in the owner's file.
    assert v.check([GCDFO + "UndeclaredParent", GCDFO + "MethodX"]) == [GCDFO + "UndeclaredParent"]
    assert v.exists(SMN + "9.9.9")                       # the ontology's version IRI
    assert v.pins["smn"].version_info == "9.9.9" and v.pins["smn"].version == "test-smn"


def test_exclusions(tiny_vocab):
    v = tiny_vocab
    not_terms = [SMN + "data/id/cu/dfo/SEL-21-02", SMN + "profile/corpus/variables/efs",
                 SMN, GCDFO, config.PSC_VOCAB_NS,
                 config.PSC_VOCAB_NS + "psc-vocabularies.ttl", config.PSC_VOCAB_NS + "psc-vocabularies.jsonld",
                 config.PSC_VOCAB_NS + "release/v0.1.0-alpha.5/psc-vocabularies.ttl",
                 PSC + "PSC-CV-000035.ttl", config.PSC_SCHEME_NS + "x.jsonld",
                 "http://www.w3.org/2004/02/skos/core#Concept", DEFAULT + "id/cu/dfo/X"]
    for i in not_terms:
        assert not v.is_guarded(i), i
    assert v.check(not_terms) == []
    for i in (SMN + "data", SMN + "profile/other/x", SMN + "NotATerm", PSC + "PSC-CV-000000",
              config.PSC_VOCAB_NS + "made-up"):
        assert v.is_guarded(i), i
    assert v.check([SMN + "NotATerm", PSC + "PSC-CV-000000", SMN + "NotATerm"]) == \
        sorted([SMN + "NotATerm", PSC + "PSC-CV-000000"])


def test_base_under_a_vocabulary_namespace_is_excluded():
    cfg = Config(base="https://w3id.org/smn/corpus-data/")
    v = VocabIndex(tiny_sources(), cfg=cfg, offline=True)
    assert "https://w3id.org/smn/corpus-data/" in cfg.excluded_subtrees
    assert not v.is_guarded("https://w3id.org/smn/corpus-data/id/cu/dfo/X")
    assert v.is_guarded("https://w3id.org/smn/corpus-dataX")


def test_labels_prefer_preflabel_and_english(tiny_vocab):
    assert tiny_vocab.label(SMN + "TermA") == "Term A"
    assert tiny_vocab.label(SMN + "TermB") == "Term B"
    assert tiny_vocab.label(SMN + "Nothing") is None


def test_vocab_graphs_and_provenance_are_deterministic(tiny_vocab):
    g = DEFAULT + "graph/corpus/test/vocab-pins"
    a = det.nquads_bytes(tiny_vocab.provenance(g))
    b = det.nquads_bytes(VocabIndex(tiny_sources(), cfg=Config(), offline=True).provenance(g))
    assert a == b
    assert b"sha256:" in a and b"/Users/" not in a and b"/home/" not in a
    st = ox.Store()
    loaded = tiny_vocab.load_into(st)
    assert sorted(loaded) == ["gcdfo", "psc", "smn"]
    assert all(v.startswith(DEFAULT + "graph/vocab/") for v in loaded.values())


# ==========================================================================
# vocab: the real sources (positive and negative controls)
# ==========================================================================

POSITIVE_CONTROLS = [SMN + "EuropeanAgeNotation", GCDFO + "FixedStationTally", PSC + "PSC-CV-000035"]


def test_positive_controls_are_found(real_vocab):
    for i in POSITIVE_CONTROLS:
        assert real_vocab.is_guarded(i), i
        assert real_vocab.exists(i), i
        assert real_vocab.label(i), i
    assert real_vocab.check(POSITIVE_CONTROLS) == []
    assert real_vocab.label(PSC + "PSC-CV-000035") == "Effective female spawner abundance"


def test_negative_control_is_reported(real_vocab):
    bad = GCDFO + "UndeclaredGuardProbe"
    assert real_vocab.is_guarded(bad) and not real_vocab.exists(bad)
    assert real_vocab.check(POSITIVE_CONTROLS + [bad]) == [bad]


def test_real_subtree_exclusions(real_vocab):
    iris = [SMN + "data/id/cu/dfo/SEL-21-02", SMN + "profile/corpus/variables/efs",
            config.PSC_VOCAB_NS + "psc-vocabularies.ttl", PSC + "PSC-CV-000035.ttl"]
    assert real_vocab.check(iris) == []
    assert real_vocab.check([SMN + "data"]) == [SMN + "data"]


def test_real_pins_are_recorded(real_vocab):
    assert sorted(real_vocab.pins) == ["gcdfo", "psc", "smn"]
    for key, pin in real_vocab.pins.items():
        assert re.fullmatch(r"[0-9a-f]{64}", pin.sha256), key
        assert not pin.path.startswith("/"), pin.path          # portable, never absolute
        assert pin.triples > 0
        assert pin.version_kind in ("git-commit", "git-commit-dirty", "release-tag", "declared", "unknown")
        assert pin.version or pin.version_note, key           # unknown versions say why
        if pin.version_kind.startswith("git-commit"):
            assert re.fullmatch(r"[0-9a-f]{40}", pin.version)
        if pin.version_kind == "release-tag":
            assert re.fullmatch(r"v\d+\.\d+\.\d+.*", pin.version)
    assert real_vocab.pins["psc"].url is None or real_vocab.pins["psc"].url.endswith(".ttl")
    quads = real_vocab.provenance(DEFAULT + "graph/corpus/test/vocab-pins")
    iris = {t.value for q in quads for t in (q.subject, q.object) if isinstance(t, ox.NamedNode)}
    assert real_vocab.check(iris) == []
    json.dumps(real_vocab.pins_dict())


def test_builder_reports_undeclared_iris(real_vocab):
    g = DEFAULT + "graph/test/1/metadata"
    b = GraphBuilder(real_vocab)
    b.add(DEFAULT + "id/x/y/z", "rdf:type", "smn:EuropeanAgeNotation", g)
    b.add(DEFAULT + "id/x/y/z", "sosa:usedProcedure", "gcdfo:FixedStationTally", g)
    assert b.undeclared() == []
    b.assert_vocab()
    b.reify(DEFAULT + "xwalk/t/1", DEFAULT + "id/x/y/z", "sosa:usedProcedure", "gcdfo:UndeclaredGuardProbe", g)
    b.add(DEFAULT + "id/x/y/z", "dcterms:type", L("v", "https://w3id.org/psc/vocab/concept/PSC-CV-000000"), g)
    assert b.undeclared() == [GCDFO + "UndeclaredGuardProbe", PSC + "PSC-CV-000000"]
    with pytest.raises(UndeclaredIRIError) as err:
        b.assert_vocab()
    assert err.value.iris == [GCDFO + "UndeclaredGuardProbe", PSC + "PSC-CV-000000"]


# ==========================================================================
# graph: builder, literals, RDF 1.2 reifiers
# ==========================================================================

def test_reifier_round_trip():
    g = DEFAULT + "graph/corpus/2026.10.27/crosswalk"
    s, o = iri.ident("stock", "sasap", 107), iri.ident("stock", "psc-frsk", 7)
    r = iri.xwalk("sasap-psc-fraser", iri.stable_key(s, "skos:closeMatch", o))
    b = GraphBuilder()
    b.reify(r, s, "skos:closeMatch", o, g, assert_triple=True)
    b.add(r, "sssom:confidence", L(0.98), g)
    q = ("PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> "
         "SELECT ?r ?s ?p ?o WHERE { ?r rdf:reifies <<( ?s ?p ?o )>> }")
    for store in (b.to_store(),
                  _store_from(b.nquads(), ox.RdfFormat.N_QUADS),
                  _store_from(b.trig(), ox.RdfFormat.TRIG)):
        rows = list(store.query(q, use_default_graph_as_union=True))
        assert len(rows) == 1
        row = rows[0]
        assert (row["r"].value, row["s"].value, row["p"].value, row["o"].value) == \
            (r, s, config.STATIC_NS["skos"] + "closeMatch", o)
        named = list(store.query("PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> "
                                 f"SELECT ?r WHERE {{ GRAPH <{g}> {{ ?r rdf:reifies <<( ?s ?p ?o )>> }} }}"))
        assert [x["r"].value for x in named] == [r]
        assert len(store) == 3                                    # triple asserted, reified, annotated
    reifies = [x for x in b.quads if x.predicate.value == RDF_REIFIES]
    assert isinstance(reifies[0].object, ox.Triple)
    assert b"<<( " in b.nquads() and b"<<( " in b.trig()


def _store_from(data: bytes, fmt) -> ox.Store:
    st = ox.Store()
    st.load(data, format=fmt)
    return st


def test_reify_without_asserting():
    g = DEFAULT + "graph/corpus/1/membership"
    b = GraphBuilder()
    b.reify(iri.membership("dfo-smu-cu", "2025-11-28", "CK-01"), iri.ident("cu", "dfo", "CK-01"),
            "skos:broader", iri.ident("smu", "dfo", "CK-FIA-01"), g)
    assert len(b) == 1 and b.quads[0].predicate.value == RDF_REIFIES


def test_builder_refuses_default_graph_and_dedupes():
    b = GraphBuilder()
    with pytest.raises(ValueError):
        b.extend([ox.Quad(N("https://example.org/s"), N("rdf:type"), N("skos:Concept"), ox.DefaultGraph())])
    for _ in range(3):
        b.add("https://example.org/s", "rdf:type", "skos:Concept", DEFAULT + "graph/x/1/metadata")
    assert len(b) == 1 and b.graphs() == {DEFAULT + "graph/x/1/metadata": 1}


def test_literals():
    xsd = config.STATIC_NS["xsd"]
    assert L(np.int64(7)).datatype.value == xsd + "integer" and L(np.int64(7)).value == "7"
    assert L(True).value == "true" and L(True).datatype.value == xsd + "boolean"
    assert L(0.1).value == "0.1" and L(0.1).datatype.value == xsd + "double"
    assert L(np.float64(2.5)).value == "2.5"
    assert L(math.inf).value == "INF"
    assert L(dt.date(1990, 1, 2)).value == "1990-01-02" and L(dt.date(1990, 1, 2)).datatype.value == xsd + "date"
    assert L("1990", "xsd:gYear").datatype.value == xsd + "gYear"
    assert L("Chilko", lang="en").language == "en"
    for missing in (None, float("nan")):
        with pytest.raises(ValueError):
            L(missing)


def test_bnodes_are_deterministic():
    assert GraphBuilder.bnode("a", 1) == GraphBuilder.bnode("a", 1)
    assert GraphBuilder.bnode("a", 1) != GraphBuilder.bnode("a", 2)
    with pytest.raises(ValueError):
        GraphBuilder.bnode()


# ==========================================================================
# io.det: byte-identical serialisation
# ==========================================================================

def test_byte_identical_across_builds_and_insertion_order(tmp_path):
    sample = _sample()
    one, two = sample.build(reverse=False), sample.build(reverse=True)
    assert one.quads != two.quads                              # different insertion order...
    assert one.nquads() == two.nquads()                        # ...same bytes
    assert one.trig() == two.trig()
    h1 = sample.write_all(tmp_path / "a")
    h2 = sample.write_all(tmp_path / "b", reverse=True)
    assert h1 == h2
    raw = (tmp_path / "a" / "sample.trig.gz").read_bytes()
    assert raw[4:8] == b"\x00\x00\x00\x00"                    # gzip mtime 0
    assert gzip.decompress(raw) == (tmp_path / "a" / "sample.trig").read_bytes()
    assert oct((tmp_path / "a" / "sample.nq").stat().st_mode & 0o777) == "0o644"


def test_byte_identical_across_processes(tmp_path):
    """Separate interpreters with different hash seeds give the same bytes."""
    script = FIXTURES / "sample_graph.py"
    outs = []
    for seed, order in (("1", "forward"), ("4242", "reverse")):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SALMONGRAPH_")}
        env["PYTHONHASHSEED"] = seed
        res = subprocess.run([sys.executable, str(script), str(tmp_path / seed), order],
                             capture_output=True, text=True, env=env, cwd=str(ROOT), check=True)
        outs.append(json.loads(res.stdout))
    assert outs[0] == outs[1]
    assert set(outs[0]) == {"sample.nq", "sample.trig", "sample.trig.gz"}


def test_trig_header_is_sorted_and_minimal():
    text = _sample().build().trig().decode()
    header = [ln for ln in text.splitlines() if ln.startswith("@prefix ")]
    names = [ln.split()[1].rstrip(":") for ln in header]
    assert names == sorted(names)
    assert "dwc" not in names and "def" not in names            # unused prefixes are left out
    assert {"corp", "prov", "skos", "rdf"} <= set(names)
    assert text.count("@prefix ") == len(header)                 # no second header from the serialiser


def test_sorted_nquads_order():
    lines = _sample().build().nquads().decode().splitlines()
    keys = [det.quad_key(q) for q in ox.parse("\n".join(lines).encode(), format=ox.RdfFormat.N_QUADS)]
    assert keys == sorted(keys) and len(keys) == len(set(keys))


def test_portable_path(tmp_path):
    assert det.portable_path(ROOT / "data/raw/_vocab/gcdfo.ttl") == "data/raw/_vocab/gcdfo.ttl"
    assert det.portable_path(Path.home() / "code/x.ttl", root=tmp_path) == "~/code/x.ttl"
    assert det.portable_path("/opt/elsewhere/x.ttl", root=tmp_path).startswith(("<external>/", "~/"))
    assert not det.portable_path("/opt/elsewhere/x.ttl", root=tmp_path).startswith("/")


def test_canonical_json_and_csv(tmp_path):
    p = det.write_json(tmp_path / "a.json", {"b": 1, "a": [3, "é"]})
    assert p.read_bytes() == '{\n  "a": [\n    3,\n    "é"\n  ],\n  "b": 1\n}\n'.encode()
    q = det.write_csv(tmp_path / "a.csv", ["x", "y"], [[1, None], ["a,b", 2]])
    assert q.read_bytes() == b'x,y\n1,\n"a,b",2\n'


# ==========================================================================
# provenance: D6 marks
# ==========================================================================

@pytest.mark.parametrize("confidence,criticality,expected", [
    ("high", "non-critical", "agentAccepted"),
    ("high", "critical", "awaitingReview"),
    ("medium", "non-critical", "awaitingReview"),
    ("medium", "critical", "awaitingReview"),
    ("low", "non-critical", "awaitingReview"),
    ("low", "critical", "awaitingReview"),
])
def test_review_status_rule(confidence, criticality, expected):
    assert provenance.review_status(confidence, criticality) == expected


def test_criticality_of():
    for aspect in ("identity-equivalence", "membership", "measure-counts", "unit-scale", "year-basis",
                   "age-notation", "estimate-type", "licence"):
        assert provenance.criticality_of(aspect) == "critical"
    for aspect in ("label", "description", "keyword", "documentation-link"):
        assert provenance.criticality_of(aspect) == "non-critical"
    with pytest.raises(ValueError):
        provenance.criticality_of("vibes")


def _marked_builder():
    g = DEFAULT + "graph/test-dataset/1/mappings"
    pg = DEFAULT + "graph/test-dataset/1/provenance"
    b = GraphBuilder()
    model = provenance.ai_agent(b, "test-model-1", graph=pg)
    run = provenance.activity_node(b, iri.activity("agent-run", "run-1"), graph=pg, label="run 1",
                                   date="2026-10-23", associated_with=[model])
    return b, g, model, run


def test_mark_derived_writes_every_mark():
    b, g, model, run = _marked_builder()
    T = provenance.terms()
    label_node = iri.profile_concept("variables", "test-variable")
    status = provenance.mark_derived(b, label_node, agent=model, activity=run,
                                     evidence=["PSC SR documentation p. 4", "https://doi.org/10.1/x"],
                                     confidence="high", criticality="non-critical", graph=g,
                                     date="2026-10-23")
    assert status == "agentAccepted"
    st = b.to_store()
    q = f"""PREFIX prov: <http://www.w3.org/ns/prov#> PREFIX dcterms: <http://purl.org/dc/terms/>
    SELECT ?agent ?act ?conf ?crit ?status ?created WHERE {{ GRAPH <{g}> {{
      <{label_node}> prov:wasAttributedTo ?agent ; prov:wasGeneratedBy ?act ;
        <{T.confidence}> ?conf ; <{T.criticality}> ?crit ; <{T.review_status}> ?status ;
        dcterms:created ?created }} }}"""
    rows = list(st.query(q))
    assert len(rows) == 1
    r = rows[0]
    assert (r["agent"].value, r["act"].value) == (model, run)
    assert r["conf"].value == T.values["high"] and r["crit"].value == T.values["non-critical"]
    assert r["status"].value == T.values["agentAccepted"] and r["created"].value == "2026-10-23"
    ev = list(st.query(f"""PREFIX prov: <http://www.w3.org/ns/prov#> SELECT ?e ?v WHERE {{
        <{label_node}> prov:wasDerivedFrom ?e . OPTIONAL {{ ?e prov:value ?v }} }}""",
                        use_default_graph_as_union=True))
    assert sorted((x["v"].value if x["v"] else x["e"].value) for x in ev) == \
        ["PSC SR documentation p. 4", "https://doi.org/10.1/x"]
    assert provenance.token_of(T.values["agentAccepted"]) == "agentAccepted"


def test_mark_statement_on_a_reifier():
    b, g, model, run = _marked_builder()
    s, o = iri.ident("stock", "sasap", 107), iri.ident("stock", "psc-frsk", 7)
    r = iri.xwalk("sasap-psc-fraser", iri.stable_key(s, "skos:closeMatch", o))
    status = provenance.mark_statement(
        b, r, s, "skos:closeMatch", o, graph=g, agent=model, activity=run,
        evidence="totals agree within 0.5% for 66/68 brood years", confidence="high",
        criticality=provenance.criticality_of("identity-equivalence"))
    assert status == "awaitingReview"                     # critical: always awaits review
    T = provenance.terms()
    q = f"""PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    SELECT ?r ?s ?o ?status WHERE {{ ?r rdf:reifies <<( ?s <http://www.w3.org/2004/02/skos/core#closeMatch> ?o )>> ;
        <{T.review_status}> ?status }}"""
    rows = list(b.to_store().query(q, use_default_graph_as_union=True))
    assert [(x["r"].value, x["s"].value, x["o"].value, x["status"].value) for x in rows] == \
        [(r, s, o, T.values["awaitingReview"])]


def test_mark_derived_refuses_bad_input():
    b, g, model, run = _marked_builder()
    t = iri.profile_concept("variables", "x")
    ok = dict(agent=model, activity=run, evidence="e", confidence="high", criticality="critical", graph=g)
    for bad in ({"confidence": "certain"}, {"criticality": "major"}, {"evidence": []},
                {"evidence": "  "}, {"agent": "not an iri"}, {"date": "23 Oct 2026"}):
        with pytest.raises(ValueError):
            provenance.mark_derived(b, t, **{**ok, **bad})
    with pytest.raises(ValueError):
        provenance.mark_derived(b, ox.BlankNode("x"), **ok)
    provenance.mark_derived(b, t, **ok)
    with pytest.raises(ValueError):
        provenance.mark_derived(b, t, **ok)              # a target is marked once


def test_profile_vocabulary_declares_every_corp_term():
    g = DEFAULT + "graph/corpus/test/vocab-pins"
    quads = provenance.profile_vocabulary(g)
    declared = {q.subject.value for q in quads if q.predicate.value == config.STATIC_NS["rdf"] + "type"}
    T = provenance.terms()
    expected = {T.confidence, T.criticality, T.review_status, *T.schemes.values(), *T.values.values()}
    assert expected <= declared
    assert len(T.values) == 10
    assert det.nquads_bytes(quads) == det.nquads_bytes(provenance.profile_vocabulary(g))
    notations = {q.object.value for q in quads if q.predicate.value.endswith("#notation")}
    assert notations == set(provenance.CONFIDENCE_LEVELS) | set(provenance.CRITICALITY_LEVELS) | \
        set(provenance.REVIEW_STATUSES)


def test_agents_and_activity_nodes():
    b = GraphBuilder()
    pg = DEFAULT + "graph/x/1/provenance"
    sw = provenance.software_agent(b, "metasalmonpy", "0.6.0", graph=pg)
    person = provenance.person_agent(b, "Brett Johnson", graph=pg)
    orcid = provenance.person_agent(b, "Someone", graph=pg, orcid="0000-0002-1825-0097")
    act = provenance.activity_node(b, iri.activity("build", "x", "1"), graph=pg, label="build",
                                   date="2026-10-23", used=[iri.dataset("x", "1")], associated_with=[sw],
                                   started_at="2026-10-23T01:02:03Z")
    assert sw == DEFAULT + "agent/software/metasalmonpy/0.6.0"
    assert person == DEFAULT + "agent/person/brett-johnson"
    assert orcid == "https://orcid.org/0000-0002-1825-0097"
    assert act == DEFAULT + "activity/build/x/1"
    with pytest.raises(ValueError):
        provenance.activity_node(b, iri.activity("build", "y"), graph=pg, label="b", date="2026-10-23",
                                 ended_at="2026-10-23")
    with pytest.raises(ValueError):
        provenance.person_agent(b, "x", graph=pg, orcid="1234")


# ==========================================================================
# Stubs: importable, documented, raise NotImplementedError, listed in INTERFACES.md
# ==========================================================================

STUB_MODULES = ["salmongraph.identity", "salmongraph.combine",
                "salmongraph.review", "salmongraph.ledger",
                "salmongraph.catalog", "salmongraph.release", "salmongraph.serve.sparql_server",
                "salmongraph.serve.mcp_server", "salmongraph.publish.schemaorg", "salmongraph.publish.knb",
                "salmongraph.publish.zenodo"]

# Implemented portions have substantive fixture tests. Keep checking the
# remaining placeholders instead of dropping an entire partially built module.
IMPLEMENTED_PARTIAL_FUNCTIONS = {
    "salmongraph.review": {"review_queue", "write_review_queue", "status_counts"},
}


@pytest.mark.parametrize("name", STUB_MODULES)
def test_stub_functions_raise_not_implemented(name):
    mod = importlib.import_module(name)
    assert mod.__doc__ and "STUB" in mod.__doc__
    funcs = [getattr(mod, n) for n in mod.__all__ if inspect.isfunction(getattr(mod, n))]
    assert funcs, name
    for fn in funcs:
        if fn.__name__ in IMPLEMENTED_PARTIAL_FUNCTIONS.get(name, set()):
            continue
        assert fn.__doc__, f"{name}.{fn.__name__} has no docstring"
        params = inspect.signature(fn).parameters.values()
        args = [None for p in params if p.kind == p.POSITIONAL_OR_KEYWORD and p.default is p.empty]
        kwargs = {p.name: None for p in params if p.kind == p.KEYWORD_ONLY and p.default is p.empty}
        with pytest.raises(NotImplementedError):
            fn(*args, **kwargs)


def test_interfaces_md_lists_every_public_name():
    text = (ROOT / "salmongraph" / "INTERFACES.md").read_text(encoding="utf-8")
    missing = []
    for name in STUB_MODULES + ["salmongraph.provenance", "salmongraph.spec", "salmongraph.executor",
                              "salmongraph.validate", "salmongraph.shapes"]:
        mod = importlib.import_module(name)
        missing += [f"{name}.{n}" for n in mod.__all__ if n not in text]
    assert missing == []
