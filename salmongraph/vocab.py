"""The vocabulary IRI guard: smn, gcdfo and the PSC CV at recorded pins.

ADR-0001 D4: every IRI the corpus uses in the smn, gcdfo or PSC namespaces
must exist in the pinned source. :class:`VocabIndex` loads the three sources,
records a pin for each (URL, portable path, sha256, version) and answers
:meth:`~VocabIndex.exists`, :meth:`~VocabIndex.label` and
:meth:`~VocabIndex.check`.

**Declared** means: the IRI is the subject of an ``rdf:type`` triple in the
source that owns its namespace (measured 2026-10-23: every own-namespace
subject in all three sources is typed), or a version IRI that source names.
Ownership matters: gcdfo's file re-declares 38 smn concepts and smn's file
annotates a gcdfo IRI; neither may vouch for the other's namespace.

**Not checked** (section 6.2, condition 3): IRIs under
``https://w3id.org/smn/data/`` and ``https://w3id.org/smn/profile/corpus/``,
the configured base and profile base when they lie under a vocabulary
namespace, each namespace root, and the PSC CV's document IRIs (the
``.ttl``/``.jsonld`` representations and ``release/`` paths).

Sources and their defaults (each overridable by environment variable):

=====  ==================================================================  =========================
key    default                                                             override
=====  ==================================================================  =========================
smn    local flat build ``~/code/salmon-domain-ontology/salmon-domain-      ``SALMONGRAPH_SMN_TTL``
       ontology.ttl``; version = last git commit touching the file
gcdfo  ``raw.githubusercontent.com/.../main/ontology/dfo-salmon.ttl``,     ``SALMONGRAPH_GCDFO_URL``,
       cached as ``data/raw/_vocab/gcdfo.ttl``; version = last commit on    ``SALMONGRAPH_GCDFO_TTL``
       ``main`` touching the file whose bytes match (GitHub API)
psc    explicit ``https://w3id.org/psc/vocab/psc-vocabularies.ttl``         ``SALMONGRAPH_PSC_URL``,
       (canonical PSC IRIs always 303 to HTML), cached as                    ``SALMONGRAPH_PSC_TTL``
       ``data/raw/_vocab/psc-vocabularies.ttl``; version = the release
       tag whose manifest lists the same sha256
=====  ==================================================================  =========================

``SALMONGRAPH_VOCAB_CACHE`` moves the cache directory; ``SALMONGRAPH_OFFLINE=1``
forbids network access (a missing cache is then an error, and versions that
need the network are recorded as unknown, with the reason). A resolved
version is remembered beside a cached download in ``<file>.pin.json``, keyed
by its sha256, so later runs need no network.

Upstream: metasalmonpy's ``ontology_release`` reads immutable *release*
snapshots of smn and gcdfo; this module reads the flat build and ``main``
(Brett, 2026-10-23) and adds the PSC CV. They should converge when this moves
upstream (architecture.md 12.1).
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pyoxigraph as ox

from . import config as _config
from . import iri as _iri
from .config import GCDFO_NS, PSC_VOCAB_NS, SMN_NS, STATIC_NS, Config
from .graph import L
from .io import det

__all__ = [
    "ENV_SMN_TTL", "ENV_GCDFO_URL", "ENV_GCDFO_TTL", "ENV_PSC_URL", "ENV_PSC_TTL",
    "ENV_VOCAB_CACHE", "ENV_OFFLINE", "DEFAULT_SMN_TTL", "DEFAULT_GCDFO_URL", "DEFAULT_PSC_URL",
    "PSC_RELEASE_INDEX_URL", "PSC_DOCUMENT_PATTERNS", "VocabSource", "VocabPin", "VocabularyError",
    "UndeclaredIRIError",
    "default_sources", "VocabIndex",
]

ENV_SMN_TTL = "SALMONGRAPH_SMN_TTL"
ENV_GCDFO_URL = "SALMONGRAPH_GCDFO_URL"
ENV_GCDFO_TTL = "SALMONGRAPH_GCDFO_TTL"
ENV_PSC_URL = "SALMONGRAPH_PSC_URL"
ENV_PSC_TTL = "SALMONGRAPH_PSC_TTL"
ENV_VOCAB_CACHE = "SALMONGRAPH_VOCAB_CACHE"
ENV_OFFLINE = "SALMONGRAPH_OFFLINE"

DEFAULT_SMN_TTL = "~/code/salmon-domain-ontology/salmon-domain-ontology.ttl"
# gcdfo on main via GitHub raw: w3id.org/gcdfo/salmon redirects to GitHub Pages
# (Brett, 2026-10-23: stay on main for now).
DEFAULT_GCDFO_URL = ("https://raw.githubusercontent.com/dfo-pacific-science/dfo-salmon-ontology/"
                     "main/ontology/dfo-salmon.ttl")
DEFAULT_PSC_URL = PSC_VOCAB_NS + "psc-vocabularies.ttl"
PSC_RELEASE_INDEX_URL = PSC_VOCAB_NS + "release/index.json"

_RDF_TYPE = STATIC_NS["rdf"] + "type"
_OWL = STATIC_NS["owl"]
_LABELS = (STATIC_NS["skos"] + "prefLabel", STATIC_NS["rdfs"] + "label")
#: Full-match regexes of PSC CV document IRIs (representations and releases), not terms.
PSC_DOCUMENT_PATTERNS = (
    re.escape(PSC_VOCAB_NS) + r"psc-vocabularies\.(ttl|jsonld)",
    re.escape(PSC_VOCAB_NS) + r"release/.*",
    re.escape(PSC_VOCAB_NS) + r"(concept|scheme)/[^/]+\.(ttl|jsonld)",
)


class VocabularyError(RuntimeError):
    """A vocabulary source could not be loaded as configured."""


class UndeclaredIRIError(VocabularyError):
    """IRIs in the smn, gcdfo or PSC namespaces that the pinned sources do not declare."""

    def __init__(self, iris: Iterable[str]) -> None:
        self.iris = sorted(set(iris))
        shown = "\n  ".join(self.iris[:50])
        more = f"\n  ... and {len(self.iris) - 50} more" if len(self.iris) > 50 else ""
        super().__init__(f"{len(self.iris)} undeclared vocabulary IRI(s):\n  {shown}{more}")


@dataclass(frozen=True)
class VocabSource:
    """Where one vocabulary comes from.

    ``path`` is the file read. When ``cached`` is true it is a download cache
    for ``url``, fetched when missing (or on ``refresh``). ``version`` is an
    explicit pin that skips detection. ``non_term`` holds full-match regexes
    for document IRIs inside ``namespace`` that are not terms.
    """

    key: str
    namespace: str
    title: str
    path: Path
    url: str | None = None
    cached: bool = False
    ontology_iri: str | None = None
    version: str | None = None
    non_term: tuple[str, ...] = ()


@dataclass(frozen=True)
class VocabPin:
    """What was loaded, recorded for provenance and release manifests.

    ``version_kind`` is ``git-commit`` (last commit touching the file),
    ``git-commit-dirty`` (the file differs from that commit), ``release-tag``,
    ``declared`` (given explicitly) or ``unknown`` (``version_note`` says why).
    ``path`` is portable (``io.det.portable_path``); ``url`` is where the
    bytes are published, when known.
    """

    key: str
    namespace: str
    title: str
    ontology_iri: str | None
    url: str | None
    path: str
    sha256: str
    triples: int
    version: str | None
    version_kind: str
    version_info: str | None
    repository: str | None = None
    version_note: str | None = None

    def as_dict(self) -> dict:
        """Plain dict with sorted keys (for JSON manifests)."""
        d = asdict(self)
        return {k: d[k] for k in sorted(d)}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def default_sources(env: Mapping[str, str] | None = None) -> list[VocabSource]:
    """The three sources of ADR-0001 D4, with environment overrides applied."""
    env = os.environ if env is None else env
    cache = Path(os.path.expanduser(env.get(ENV_VOCAB_CACHE) or str(_config.ROOT / "data/raw/_vocab")))
    smn_path = Path(os.path.expanduser(env.get(ENV_SMN_TTL) or DEFAULT_SMN_TTL))
    gcdfo_url = env.get(ENV_GCDFO_URL) or DEFAULT_GCDFO_URL
    gcdfo_local = env.get(ENV_GCDFO_TTL)
    psc_url = env.get(ENV_PSC_URL) or DEFAULT_PSC_URL
    psc_local = env.get(ENV_PSC_TTL)
    return [
        VocabSource("smn", SMN_NS, "Salmon Domain Ontology (smn), flat build", smn_path,
                    url=None, cached=False, ontology_iri="https://w3id.org/smn"),
        VocabSource("gcdfo", GCDFO_NS, "DFO Salmon Ontology (gcdfo)",
                    Path(os.path.expanduser(gcdfo_local)) if gcdfo_local else cache / "gcdfo.ttl",
                    url=None if gcdfo_local else gcdfo_url, cached=not gcdfo_local,
                    ontology_iri="https://w3id.org/gcdfo/salmon"),
        VocabSource("psc", PSC_VOCAB_NS, "PSC salmon controlled vocabulary (PSC CV)",
                    Path(os.path.expanduser(psc_local)) if psc_local else cache / "psc-vocabularies.ttl",
                    url=None if psc_local else psc_url, cached=not psc_local,
                    ontology_iri=PSC_VOCAB_NS, non_term=PSC_DOCUMENT_PATTERNS),
    ]


# --------------------------------------------------------------------------
# Network and git helpers (best effort; failures become "unknown" with a note)
# --------------------------------------------------------------------------

def _http_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "salmongraph/0.1 (+salmon-demo-corpus)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https URLs only)
        return resp.read()


def _download(url: str, dest: Path, timeout: float) -> None:
    if not url.startswith("https://"):
        raise VocabularyError(f"refusing to download a vocabulary over non-https: {url}")
    try:
        data = _http_get(url, timeout)
    except (urllib.error.URLError, OSError) as exc:
        raise VocabularyError(f"could not download {url}: {exc}") from exc
    try:  # parse it all before caching: an HTML page or a truncated file must not be cached
        n = sum(1 for _ in ox.parse(data, format=ox.RdfFormat.TURTLE))
    except (SyntaxError, ValueError) as exc:
        raise VocabularyError(f"{url} did not return Turtle: {exc}") from exc
    if n == 0:
        raise VocabularyError(f"{url} returned no triples")
    det.write_bytes(dest, data, gzip=False)


def _git(args: Sequence[str], cwd: Path) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                             timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _public_repo_url(remote: str | None) -> str | None:
    """A shareable repository URL, or None. Drops credentials; refuses local paths and hosts."""
    if not remote:
        return None
    m = re.match(r"^[\w.-]+@([\w.-]+):(.+)$", remote)  # git@github.com:org/repo.git
    url = f"https://{m.group(1)}/{m.group(2)}" if m else remote
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return None
    except ValueError:
        if host == "localhost" or "." not in host:
            return None
    path = re.sub(r"\.git$", "", parts.path.rstrip("/"))
    return urllib.parse.urlunsplit(("https", host, path, "", ""))


def _git_file_version(path: Path) -> tuple[str, str, str | None] | None:
    top = _git(["rev-parse", "--show-toplevel"], path.parent)
    if not top:
        return None
    try:
        rel = os.path.relpath(path.resolve(), Path(top).resolve())
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    commit = _git(["log", "-1", "--format=%H", "--", rel], Path(top))
    if not commit or not re.fullmatch(r"[0-9a-f]{40}", commit):
        return None
    dirty = _git(["status", "--porcelain", "--", rel], Path(top))
    repo = _public_repo_url(_git(["config", "--get", "remote.origin.url"], Path(top)))
    return commit, ("git-commit-dirty" if dirty else "git-commit"), repo


def _local_release_tag(path: Path, sha: str) -> tuple[str, str] | None:
    """Match ``sha`` against release manifests in a PSC clone near ``path``."""
    name = path.name
    for anc in list(path.absolute().parents)[:3]:
        for rel in ("releases", "public/release"):
            d = anc / rel
            if not d.is_dir():
                continue
            for manifest in sorted(d.glob("*/manifest.json")):
                try:
                    m = json.loads(manifest.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for a in m.get("artifacts", []):
                    if a.get("path") == name and a.get("sha256") == sha:
                        return str(m.get("version") or manifest.parent.name), name
    return None


def _remote_github_version(url: str, sha: str, timeout: float) -> tuple[str | None, str, str | None, str | None]:
    m = re.match(r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$", url)
    if not m:
        return None, "unknown", None, "not a raw.githubusercontent.com URL"
    owner, repo, ref, fpath = m.groups()
    repo_url = f"https://github.com/{owner}/{repo}"
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref, "git-commit", repo_url, None
    api = (f"https://api.github.com/repos/{owner}/{repo}/commits?"
           + urllib.parse.urlencode({"path": fpath, "sha": ref, "per_page": 1}))
    try:
        commits = json.loads(_http_get(api, timeout))
        commit = commits[0]["sha"]
        raw = _http_get(f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{fpath}", timeout)
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as exc:
        return None, "unknown", repo_url, f"GitHub lookup failed: {type(exc).__name__}"
    if det.sha256_bytes(raw) != sha:
        return None, "unknown", repo_url, (f"cached file is not the latest commit on {ref} touching "
                                           f"{fpath}; refresh the cache or declare the version")
    return commit, "git-commit", repo_url, None


def _remote_psc_release(url: str, sha: str, timeout: float) -> tuple[str | None, str | None]:
    name = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
    try:
        index = json.loads(_http_get(PSC_RELEASE_INDEX_URL, timeout))
        for rel in index.get("releases", []):
            v = rel.get("version")
            if not v:
                continue
            m = json.loads(_http_get(f"{PSC_VOCAB_NS}release/{v}/manifest.json", timeout))
            for a in m.get("artifacts", []):
                if a.get("path") == name and a.get("sha256") == sha:
                    return v, None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"PSC release lookup failed: {type(exc).__name__}"
    return None, "no PSC release manifest lists this sha256"


# --------------------------------------------------------------------------
# The index
# --------------------------------------------------------------------------

class VocabIndex:
    """smn + gcdfo + PSC CV, loaded at recorded pins; the IRI guard.

    Parameters
    ----------
    sources:
        Default :func:`default_sources` (environment applied).
    cfg:
        IRI layout; decides which corpus sub-trees are excluded and the
        vocabulary graph IRIs. Default ``config.current()``.
    offline:
        Forbid network access. Default: ``SALMONGRAPH_OFFLINE``.
    refresh:
        Re-download cached sources even when present.
    timeout:
        Seconds per HTTP request.
    """

    def __init__(self, sources: Sequence[VocabSource] | None = None, *, cfg: Config | None = None,
                 offline: bool | None = None, refresh: bool = False, timeout: float = 60.0) -> None:
        self.cfg = cfg if cfg is not None else _config.current()
        self.sources = list(sources) if sources is not None else default_sources()
        self.offline = _truthy(os.environ.get(ENV_OFFLINE)) if offline is None else offline
        self.timeout = timeout
        self.pins: dict[str, VocabPin] = {}
        self._triples: dict[str, list[ox.Triple]] = {}
        self._declared: dict[str, frozenset[str]] = {}
        self._labels: dict[str, str] = {}
        self._non_term: dict[str, tuple[re.Pattern[str], ...]] = {}
        self._store: ox.Store | None = None
        keys = [s.key for s in self.sources]
        if len(set(keys)) != len(keys):
            raise VocabularyError(f"duplicate vocabulary keys: {keys}")
        for src in self.sources:
            self._load(src, refresh)
        self._owners = sorted(((s.namespace, s.key) for s in self.sources), key=lambda x: (-len(x[0]), x[1]))
        self._excluded = self.cfg.excluded_subtrees

    # -- loading -------------------------------------------------------------
    def _load(self, src: VocabSource, refresh: bool) -> None:
        path = src.path
        if src.cached and src.url and (refresh or not path.exists()):
            if self.offline:
                raise VocabularyError(f"{src.key}: {det.portable_path(path)} is missing and "
                                      f"{ENV_OFFLINE} forbids downloading {src.url}")
            _download(src.url, path, self.timeout)
        if not path.exists():
            raise VocabularyError(f"{src.key}: vocabulary file not found at {det.portable_path(path)}")
        data = path.read_bytes()
        sha = det.sha256_bytes(data)
        try:
            triples = list(ox.parse(data, format=ox.RdfFormat.TURTLE))
        except (SyntaxError, ValueError) as exc:
            raise VocabularyError(f"{src.key}: cannot parse {det.portable_path(path)}: {exc}") from exc
        ns = src.namespace
        declared: set[str] = set()
        versions: set[str] = set()
        ontologies: set[str] = set()
        labels: dict[str, tuple] = {}
        for t in triples:
            s, p, o = t.subject, t.predicate.value, t.object
            if not isinstance(s, ox.NamedNode):
                continue
            if p == _RDF_TYPE:
                if s.value.startswith(ns):
                    declared.add(s.value)
                if isinstance(o, ox.NamedNode) and o.value == _OWL + "Ontology":
                    ontologies.add(s.value)
            elif p in (_OWL + "versionIRI", _OWL + "priorVersion") and isinstance(o, ox.NamedNode):
                if o.value.startswith(ns):
                    declared.add(o.value)
            elif p in _LABELS and isinstance(o, ox.Literal) and s.value.startswith(ns):
                lang = o.language or ""
                rank = (_LABELS.index(p), 0 if lang == "en" else 1 if lang == "" else 2, lang, o.value)
                if s.value not in labels or rank < labels[s.value]:
                    labels[s.value] = rank
        info = sorted(t.object.value for t in triples
                      if t.predicate.value == _OWL + "versionInfo" and isinstance(t.object, ox.Literal)
                      and isinstance(t.subject, ox.NamedNode) and t.subject.value in ontologies)
        version, kind, repo, note, url = self._resolve_version(src, path, sha)
        self._triples[src.key] = triples
        self._declared[src.key] = frozenset(declared)
        for k, rank in labels.items():
            self._labels[k] = rank[3]
        self._non_term[src.key] = tuple(re.compile(p) for p in src.non_term)
        self.pins[src.key] = VocabPin(
            key=src.key, namespace=ns, title=src.title, ontology_iri=src.ontology_iri, url=url,
            path=det.portable_path(path), sha256=sha, triples=len(triples), version=version,
            version_kind=kind, version_info=info[0] if info else None, repository=repo,
            version_note=note)

    def _resolve_version(self, src: VocabSource, path: Path, sha: str):
        """(version, kind, repository, note, url) for one loaded file."""
        url = src.url
        if src.version:
            return src.version, "declared", None, None, url
        sidecar = path.with_name(path.name + ".pin.json")
        if src.cached and sidecar.exists():
            try:
                rec = json.loads(sidecar.read_text(encoding="utf-8"))
                if rec.get("sha256") == sha and rec.get("version"):
                    return rec["version"], rec["version_kind"], rec.get("repository"), None, url
            except (OSError, ValueError, KeyError):
                pass
        if not src.cached:
            # A local file: a release manifest beside it (a PSC clone) names a
            # release whose published copy has these exact bytes; else git.
            tag = _local_release_tag(path, sha)
            if tag:
                release_url = url
                if release_url is None and src.namespace == PSC_VOCAB_NS:
                    release_url = f"{PSC_VOCAB_NS}release/{tag[0]}/{tag[1]}"
                return tag[0], "release-tag", None, None, release_url
            g = _git_file_version(path)
            if g:
                note = ("the file differs from this commit (uncommitted changes)"
                        if g[1] == "git-commit-dirty" else None)
                return g[0], g[1], g[2], note, url
        if not url:
            return (None, "unknown", None,
                    "local file: no release manifest lists its sha256 and git has no commit for it", url)
        if self.offline:
            return None, "unknown", None, f"{ENV_OFFLINE} set; version lookup needs the network", url
        if src.namespace == PSC_VOCAB_NS:
            v, note = _remote_psc_release(url, sha, self.timeout)
            result = (v, "release-tag" if v else "unknown", None, note)
        else:
            result = _remote_github_version(url, sha, self.timeout)
        if src.cached and result[0]:
            det.write_json(sidecar, {"sha256": sha, "url": url, "version": result[0],
                                     "version_kind": result[1], "repository": result[2]})
        return (*result, url)

    # -- the guard ------------------------------------------------------------
    def owner(self, iri: str) -> str | None:
        """Key of the vocabulary whose namespace contains ``iri`` (most specific), else None."""
        for ns, key in self._owners:
            if iri.startswith(ns):
                return key
        return None

    def is_guarded(self, iri: str) -> bool:
        """True when ``iri`` is in a vocabulary namespace and is not an excluded non-term IRI."""
        key = self.owner(iri)
        if key is None:
            return False
        if any(iri.startswith(x) for x in self._excluded):
            return False
        if iri == self.pins[key].namespace:
            return False
        return not any(p.fullmatch(iri) for p in self._non_term[key])

    def exists(self, iri: str) -> bool:
        """True when the owning vocabulary declares ``iri`` at its pin."""
        key = self.owner(iri)
        return key is not None and iri in self._declared[key]

    def check(self, iris: Iterable[str]) -> list[str]:
        """Sorted unique guarded IRIs among ``iris`` that are not declared (empty = all good)."""
        return sorted({i for i in iris if self.is_guarded(i) and not self.exists(i)})

    def label(self, iri: str) -> str | None:
        """Preferred label from the owning source: skos:prefLabel before rdfs:label, @en first."""
        return self._labels.get(iri)

    def declared(self, key: str) -> frozenset[str]:
        """Every IRI vocabulary ``key`` declares (for term search and reports)."""
        return self._declared[key]

    # -- graphs and provenance ----------------------------------------------
    def graph_iri(self, key: str) -> str:
        """Named graph that holds vocabulary ``key``: ``graph/vocab/{key}/sha256-...``."""
        return _iri.vocab_graph(key, self.pins[key].sha256, cfg=self.cfg)

    def quads(self, key: str) -> list[ox.Quad]:
        """Vocabulary ``key`` as quads in :meth:`graph_iri`."""
        g = ox.NamedNode(self.graph_iri(key))
        return [ox.Quad(t.subject, t.predicate, t.object, g) for t in self._triples[key]]

    def load_into(self, store: ox.Store) -> dict[str, str]:
        """Load every vocabulary into ``store``, one named graph each; returns {key: graph IRI}."""
        out = {}
        for key in sorted(self._triples):
            store.extend(self.quads(key))
            out[key] = self.graph_iri(key)
        return out

    @property
    def store(self) -> ox.Store:
        """In-memory store of all three vocabularies (built on first use)."""
        if self._store is None:
            self._store = ox.Store()
            self.load_into(self._store)
        return self._store

    def pins_dict(self) -> dict[str, dict]:
        """``{key: pin.as_dict()}`` sorted by key, for JSON manifests."""
        return {k: self.pins[k].as_dict() for k in sorted(self.pins)}

    def provenance(self, graph: str, *, include_paths: bool = False) -> list[ox.Quad]:
        """The pins as RDF quads in ``graph`` (a provenance or ``vocab-pins`` graph).

        One node per vocabulary, the IRI of the graph that holds it::

            <graph/vocab/gcdfo/sha256-31e7...> a prov:Entity, void:Dataset ;
                dcterms:title "..."@en ; void:uriSpace "https://w3id.org/gcdfo/salmon#" ;
                dcterms:identifier "sha256:31e7..." ; void:triples 3610 ;
                pav:version "4b547fad..." ; owl:versionInfo "0.0.9" ;
                pav:retrievedFrom <https://raw.githubusercontent.com/...> ;
                dcterms:source <https://w3id.org/gcdfo/salmon> ;
                rdfs:comment "version kind: git-commit" ;
                rdfs:seeAlso <https://github.com/dfo-pacific-science/dfo-salmon-ontology> .

        Local paths are left out by default, so the same vocabulary bytes give
        the same provenance on every machine; ``include_paths`` adds the
        portable path as an ``rdfs:comment``.
        """
        g = ox.NamedNode(graph)
        ns = STATIC_NS
        out: list[ox.Quad] = []

        def add(s: str, p: str, o: ox.NamedNode | ox.Literal) -> None:
            out.append(ox.Quad(ox.NamedNode(s), ox.NamedNode(p), o, g))

        for key in sorted(self.pins):
            pin = self.pins[key]
            node = self.graph_iri(key)
            add(node, ns["rdf"] + "type", ox.NamedNode(ns["prov"] + "Entity"))
            add(node, ns["rdf"] + "type", ox.NamedNode(ns["void"] + "Dataset"))
            add(node, ns["dcterms"] + "title", ox.Literal(pin.title, language="en"))
            add(node, ns["void"] + "uriSpace", ox.Literal(pin.namespace))
            add(node, ns["dcterms"] + "identifier", ox.Literal("sha256:" + pin.sha256))
            add(node, ns["void"] + "triples", L(pin.triples))
            if pin.version:
                add(node, ns["pav"] + "version", ox.Literal(pin.version))
            add(node, ns["rdfs"] + "comment", ox.Literal(f"version kind: {pin.version_kind}"
                                                         + (f" ({pin.version_note})" if pin.version_note else "")))
            if pin.version_info:
                add(node, ns["owl"] + "versionInfo", ox.Literal(pin.version_info))
            if pin.url:
                add(node, ns["pav"] + "retrievedFrom", ox.NamedNode(pin.url))
            if pin.ontology_iri:
                add(node, ns["dcterms"] + "source", ox.NamedNode(pin.ontology_iri))
            if pin.repository:
                add(node, ns["rdfs"] + "seeAlso", ox.NamedNode(pin.repository))
            if include_paths:
                add(node, ns["rdfs"] + "comment", ox.Literal(f"loaded from {pin.path}"))
        return det.sorted_quads(out)
