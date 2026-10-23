"""Shared helpers for salmon-demo-corpus pipelines.

Every dataset pipeline (pipelines/<slug>.py) imports this module. It holds the
conventions that must stay identical across datasets so the per-dataset graphs
join into one corpus graph:

* one base IRI for minted resources (BASE, provisional);
* identity-node IRI patterns (``ident(kind, authority, local_id)``);
* download + SHA256SUMS + source.json (``fetch_source``);
* a vocabulary store of the released/main ontologies, used to check that every
  ontology IRI we emit really exists (``VocabIndex``);
* small RDF builders on top of pyoxigraph (``G`` graph builder);
* DCAT / PROV-O / licence boilerplate (``dcat_dataset``);
* SPARQL competency-query runner (``run_queries``).
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable

import pyoxigraph as ox

ROOT = Path(__file__).resolve().parents[1]

# Provisional: not yet registered with w3id.org.
BASE = "https://w3id.org/salmon-demo-corpus/"

NS = {
    "corpus": BASE,
    "id": BASE + "id/",
    "def": BASE + "def/",          # corpus-minted properties/classes (provisional)
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "prov": "http://www.w3.org/ns/prov#",
    "qb": "http://purl.org/linked-data/cube#",
    "csvw": "http://www.w3.org/ns/csvw#",
    "sosa": "http://www.w3.org/ns/sosa/",
    "schema": "https://schema.org/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "geo": "http://www.opengis.net/ont/geosparql#",
    "wgs": "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "iop": "https://w3id.org/iadopt/ont/",
    "smn": "https://w3id.org/smn/",
    "gcdfo": "https://w3id.org/gcdfo/salmon#",
    "obo": "http://purl.obolibrary.org/obo/",
    "unit": "http://qudt.org/vocab/unit/",
    "qk": "http://qudt.org/vocab/quantitykind/",
    "sssom": "https://w3id.org/sssom/",
    "dwc": "http://rs.tdwg.org/dwc/terms/",
}

# Standard vocabularies we use structurally (W3C/DC); not checked term by term.
STRUCTURAL_NS = tuple(NS[k] for k in (
    "rdf", "rdfs", "xsd", "owl", "skos", "dcterms", "dcat", "prov", "qb", "csvw",
    "sosa", "schema", "foaf", "geo", "wgs", "sssom", "corpus"))

# Verified NCBITaxon IRIs (EBI OLS4 exact search, 2026-10-22).
NCBI_TAXON = {
    "Chinook": ("Oncorhynchus tshawytscha", NS["obo"] + "NCBITaxon_74940"),
    "Coho": ("Oncorhynchus kisutch", NS["obo"] + "NCBITaxon_8019"),
    "Sockeye": ("Oncorhynchus nerka", NS["obo"] + "NCBITaxon_8023"),
    "Pink": ("Oncorhynchus gorbuscha", NS["obo"] + "NCBITaxon_8017"),
    "Chum": ("Oncorhynchus keta", NS["obo"] + "NCBITaxon_8018"),
    "Steelhead": ("Oncorhynchus mykiss", NS["obo"] + "NCBITaxon_8022"),
    "Cutthroat": ("Oncorhynchus clarkii", NS["obo"] + "NCBITaxon_30962"),
}

VOCAB_FILES = {
    # gcdfo main branch via GitHub raw: w3id.org/gcdfo/salmon redirects to
    # dfo-pacific-science.github.io, which the corpus sandbox blocks.
    "gcdfo": ("https://raw.githubusercontent.com/dfo-pacific-science/dfo-salmon-ontology/main/ontology/dfo-salmon.ttl",
              ROOT / "data/raw/_vocab/gcdfo.ttl"),
    # smn: local flattened build of ~/code/salmon-domain-ontology (w3id.org/smn/
    # serves HTML by default).
    "smn": (None, Path.home() / "code/salmon-domain-ontology/salmon-domain-ontology.ttl"),
}


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug_iri(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").lower()


def ident(kind: str, authority: str, local_id) -> str:
    """Identity-node IRI: BASE/id/<kind>/<authority>/<local id>.

    kind: cu, stream, population, site, region, species-group, ...
    authority: who issued the local id (dfo-nuseds, psf, dfo, ...).
    """
    local = re.sub(r"[^A-Za-z0-9._~-]", "_", str(local_id))
    return f"{NS['id']}{kind}/{authority}/{local}"


# --------------------------------------------------------------------------
# Download + provenance of raw files
# --------------------------------------------------------------------------

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_source(raw_dir: Path, files: dict[str, str], meta: dict, force: bool = False) -> dict:
    """Download files with curl -L (skip if present), write SHA256SUMS + source.json.

    files: {local file name: URL}. meta: extra fields for source.json.
    Existing source.json retrieval times are kept unless a file is re-downloaded.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    src_path = raw_dir / "source.json"
    old = json.loads(src_path.read_text()) if src_path.exists() else {}
    old_files = {f["name"]: f for f in old.get("files", [])}
    out_files = []
    for name, url in files.items():
        dest = raw_dir / name
        retrieved = old_files.get(name, {}).get("retrieved_at")
        if force or not dest.exists():
            subprocess.run(["curl", "-L", "--fail", "-sS", "-o", str(dest), url], check=True)
            retrieved = now_utc()
        out_files.append({"name": name, "url": url, "bytes": dest.stat().st_size,
                          "sha256": sha256(dest), "md5": md5(dest),
                          "retrieved_at": retrieved or now_utc()})
    (raw_dir / "SHA256SUMS").write_text("".join(f"{f['sha256']}  {f['name']}\n" for f in out_files))
    src = {**meta, "files": out_files}
    src_path.write_text(json.dumps(src, indent=2) + "\n")
    return src


# --------------------------------------------------------------------------
# Vocabulary index: does an ontology IRI really exist?
# --------------------------------------------------------------------------

class VocabIndex:
    """In-memory store of gcdfo + smn used to check IRIs and fetch labels."""

    def __init__(self) -> None:
        self.store = ox.Store()
        self.sources = {}
        for key, (url, path) in VOCAB_FILES.items():
            if not path.exists() and url:
                path.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["curl", "-L", "--fail", "-sS", "-o", str(path), url], check=True)
            self.store.load(path=str(path), format=ox.RdfFormat.TURTLE)
            self.sources[key] = {"url": url, "path": str(path), "sha256": sha256(path)}
        self._subjects = {q.subject.value for q in self.store if isinstance(q.subject, ox.NamedNode)}

    def exists(self, iri: str) -> bool:
        return iri in self._subjects

    def label(self, iri: str) -> str | None:
        for r in self.store.query(
            f"SELECT ?l WHERE {{ <{iri}> <{NS['skos']}prefLabel>|<{NS['rdfs']}label> ?l }} LIMIT 1"
        ):
            return r["l"].value
        return None


def expand(curie_or_iri: str | None) -> str | None:
    if curie_or_iri is None or str(curie_or_iri) in ("", "nan", "<NA>"):
        return None
    s = str(curie_or_iri)
    if s.startswith("http://") or s.startswith("https://"):
        return s
    pfx, _, local = s.partition(":")
    return NS[pfx] + local if pfx in NS else s


# --------------------------------------------------------------------------
# RDF building
# --------------------------------------------------------------------------

def N(iri_or_curie: str) -> ox.NamedNode:
    return ox.NamedNode(expand(iri_or_curie))


def L(value, dtype: str | None = None, lang: str | None = None) -> ox.Literal:
    if lang:
        return ox.Literal(str(value), language=lang)
    if dtype:
        return ox.Literal(str(value), datatype=N(dtype))
    if isinstance(value, bool):
        return ox.Literal("true" if value else "false", datatype=N("xsd:boolean"))
    if isinstance(value, int):
        return ox.Literal(str(value), datatype=N("xsd:integer"))
    if isinstance(value, float):
        return ox.Literal(repr(value), datatype=N("xsd:double"))
    return ox.Literal(str(value))


class G:
    """Collects quads into named graphs; checks ontology IRIs as it goes."""

    def __init__(self, vocab: VocabIndex | None = None) -> None:
        self.quads: list[ox.Quad] = []
        self.vocab = vocab
        self.unverified: set[str] = set()

    def add(self, s, p, o, graph: str) -> None:
        s = s if isinstance(s, (ox.NamedNode, ox.BlankNode)) else N(s)
        p = p if isinstance(p, ox.NamedNode) else N(p)
        if not isinstance(o, (ox.NamedNode, ox.BlankNode, ox.Literal)):
            o = N(o)
        for node in (s, p, o):
            if isinstance(node, ox.NamedNode):
                self._check(node.value)
        self.quads.append(ox.Quad(s, p, o, N(graph)))

    def _check(self, iri: str) -> None:
        if self.vocab is None:
            return
        if iri.startswith(NS["smn"]) or iri.startswith(NS["gcdfo"]):
            if not self.vocab.exists(iri):
                self.unverified.add(iri)

    def write(self, path: Path, gzip_over_mb: float = 20.0) -> Path:
        """Write TriG; gzip if the plain file is over gzip_over_mb."""
        store = ox.Store()
        store.bulk_extend(self.quads)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = store.dump(format=ox.RdfFormat.TRIG, prefixes={k: v for k, v in NS.items()})
        if len(data) > gzip_over_mb * 1e6:
            path = path.with_suffix(path.suffix + ".gz")
            with gzip.open(path, "wb", compresslevel=6) as fh:
                fh.write(data)
            stale = path.with_suffix("")
        else:
            path.write_bytes(data)
            stale = path.with_suffix(path.suffix + ".gz")
        if stale.exists():
            stale.unlink()
        return path


def dcat_dataset(g: G, *, ds: str, graph: str, title: str, description: str, doi: str | None,
                 landing: str, licence_iri: str, creators: list[dict], publisher: str,
                 issued: str | None, keywords: Iterable[str], distributions: list[dict],
                 attribution: str, derived_from: list[str] = ()) -> None:
    """DCAT dataset + distributions + licence + attribution (PROV-O)."""
    g.add(ds, "rdf:type", "dcat:Dataset", graph)
    g.add(ds, "dcterms:title", L(title, lang="en"), graph)
    g.add(ds, "dcterms:description", L(description, lang="en"), graph)
    if doi:
        g.add(ds, "dcterms:identifier", L(doi), graph)
        g.add(ds, "owl:sameAs", f"https://doi.org/{doi}", graph)
    g.add(ds, "dcat:landingPage", landing, graph)
    g.add(ds, "dcterms:license", licence_iri, graph)
    g.add(ds, "dcterms:rights", L(attribution, lang="en"), graph)
    g.add(ds, "dcterms:bibliographicCitation", L(attribution, lang="en"), graph)
    if issued:
        g.add(ds, "dcterms:issued", L(issued, "xsd:date"), graph)
    pub = ident("agent", "org", slug_iri(publisher))
    g.add(ds, "dcterms:publisher", pub, graph)
    g.add(pub, "rdf:type", "foaf:Organization", graph)
    g.add(pub, "foaf:name", L(publisher), graph)
    for c in creators:
        person = f"https://orcid.org/{c['orcid']}" if c.get("orcid") else ident("agent", "person", slug_iri(c["name"]))
        g.add(ds, "dcterms:creator", person, graph)
        g.add(person, "rdf:type", "foaf:Person", graph)
        g.add(person, "foaf:name", L(c["name"]), graph)
        g.add(ds, "prov:wasAttributedTo", person, graph)
    for kw in keywords:
        g.add(ds, "dcat:keyword", L(kw, lang="en"), graph)
    for src in derived_from:
        g.add(ds, "prov:wasDerivedFrom", src, graph)
    for d in distributions:
        dist = d["iri"]
        g.add(ds, "dcat:distribution", dist, graph)
        g.add(dist, "rdf:type", "dcat:Distribution", graph)
        g.add(dist, "dcterms:title", L(d["title"]), graph)
        if d.get("download_url"):
            g.add(dist, "dcat:downloadURL", d["download_url"], graph)
        if d.get("access_url"):
            g.add(dist, "dcat:accessURL", d["access_url"], graph)
        g.add(dist, "dcat:mediaType", f"https://www.iana.org/assignments/media-types/{d['media_type']}", graph)
        if d.get("bytes") is not None:
            g.add(dist, "dcat:byteSize", L(int(d["bytes"]), "xsd:nonNegativeInteger"), graph)
        if d.get("sha256"):
            g.add(dist, "dcterms:identifier", L("sha256:" + d["sha256"]), graph)
        g.add(dist, "dcterms:license", licence_iri, graph)


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------

def run_queries(store: ox.Store, qdir: Path, prefixes: str = "") -> dict[str, int]:
    """Run every NN-*.rq in qdir, write NN-*.csv next to it. Returns row counts."""
    counts = {}
    for rq in sorted(qdir.glob("*.rq")):
        text = rq.read_text()
        res = store.query(text, use_default_graph_as_union=True)
        vars_ = [v.value for v in res.variables]
        rows = []
        for sol in res:
            rows.append([("" if sol[v] is None else sol[v].value) for v in vars_])
        with open(rq.with_suffix(".csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(vars_)
            w.writerows(rows)
        counts[rq.name] = len(rows)
    return counts
