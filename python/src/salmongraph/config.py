"""The single source of IRI layout and namespaces for the corpus graph.

Everything that builds an IRI under the corpus base, or needs a namespace, gets
it from here (through ``salmongraph.iri`` for minting). Nothing else in the
package, and nothing downstream, may hard-code the base: it is provisional
(ADR-0001 D10) and will change when the namespace is decided.

Configuration comes from the environment, read once per process and cached:

``SALMONGRAPH_BASE``
    Instance base, default ``https://w3id.org/salmon-demo-corpus/``
    (provisional, unregistered). The D10 proposal is
    ``https://w3id.org/smn/data/``.
``SALMONGRAPH_PROFILE_BASE``
    Base of the corpus profile terms (prefix ``corp:``), default
    ``<BASE>profile/``. The D10 proposal is
    ``https://w3id.org/smn/profile/corpus/``.
``SALMONGRAPH_SDPV_NS``
    Namespace of the SDP vocabulary properties (prefix ``sdpv:``), default
    ``<PROFILE>sdp/``. metasalmonpy defines no RDF namespace for the SDP's
    ``sdp:`` keys (they are JSON keys in ``datapackage.json`` only), so this
    is provisional and lives in the corpus profile until smn-data-pkg (or
    smn) publishes one (architecture.md section 18, question 3).

Use :func:`current` to read the active configuration, :func:`override` to
change it for a block (tests, scripts), and :func:`reset` to re-read the
environment. Module attributes ``BASE``, ``PROFILE``, ``SDPV``, ``NS`` and
``PREFIXES`` always reflect :func:`current`; a name imported with ``from
salmongraph.config import BASE`` is frozen at import time, so prefer
``config.current().base`` or pass ``cfg=`` to the minting helpers.

Safety rules enforced when a configuration is built (section 6.2):

* a base must be an absolute ``http(s)`` IRI ending in ``/``;
* a base may never contain a vocabulary namespace (``https://w3id.org/`` or
  ``https://w3id.org/smn/`` itself would make the IRI guard skip real terms);
* a base may not sit under the gcdfo or PSC namespaces (the corpus does not
  mint in another authority's namespace);
* a base under smn must be a proper sub-tree of it (``smn/data/``,
  ``smn/profile/corpus/``), which the guard then treats as non-term IRIs.
"""

from __future__ import annotations

import contextlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping

__all__ = [
    "ROOT", "DEFAULT_BASE", "ENV_BASE", "ENV_PROFILE_BASE", "ENV_SDPV_NS",
    "SMN_NS", "GCDFO_NS", "PSC_VOCAB_NS", "PSC_CONCEPT_NS", "PSC_SCHEME_NS",
    "SMN_DATA_SUBTREE", "SMN_PROFILE_CORPUS_SUBTREE", "VOCAB_NAMESPACES",
    "STATIC_NS", "LAYOUT", "TOP_LEVEL", "DATASET_GRAPH_PARTS", "SHARED_GRAPHS",
    "RESERVED_SLUGS", "Config", "ConfigError", "from_env", "current", "reset",
    "override",
]

#: Repository root (the directory that holds ``salmongraph/``). Relative file
#: locations in INTERFACES.md (``specs/``, ``build/``, ``dist/``,
#: ``releases/``, ``data/raw/``) are relative to it.
ROOT = Path(__file__).resolve().parents[1]

ENV_BASE = "SALMONGRAPH_BASE"
ENV_PROFILE_BASE = "SALMONGRAPH_PROFILE_BASE"
ENV_SDPV_NS = "SALMONGRAPH_SDPV_NS"

#: Provisional, unregistered (ADR-0001 D10). Same value as ``corpuslib.BASE``.
DEFAULT_BASE = "https://w3id.org/salmon-demo-corpus/"

# Vocabulary namespaces the IRI guard covers (ADR-0001 D4).
SMN_NS = "https://w3id.org/smn/"
GCDFO_NS = "https://w3id.org/gcdfo/salmon#"
PSC_VOCAB_NS = "https://w3id.org/psc/vocab/"
PSC_CONCEPT_NS = PSC_VOCAB_NS + "concept/"
PSC_SCHEME_NS = PSC_VOCAB_NS + "scheme/"

#: The two smn sub-trees D10 reserves for the corpus. The guard never treats
#: an IRI under them as a term (section 6.2, condition 3).
SMN_DATA_SUBTREE = SMN_NS + "data/"
SMN_PROFILE_CORPUS_SUBTREE = SMN_NS + "profile/corpus/"

VOCAB_NAMESPACES: Mapping[str, str] = {"smn": SMN_NS, "gcdfo": GCDFO_NS, "psc": PSC_VOCAB_NS}

#: Fixed namespaces. Every key that ``pipelines/corpuslib.py`` defines has the
#: identical IRI here (tests pin this); ``semapv`` and ``sssom`` are the SSSOM
#: built-ins metasalmonpy's ``sssom.py`` uses. The configurable ones
#: (``corpus``, ``id``, ``corp``, ``sdpv``) are added by :attr:`Config.ns`.
STATIC_NS: Mapping[str, str] = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "prov": "http://www.w3.org/ns/prov#",
    "pav": "http://purl.org/pav/",
    "void": "http://rdfs.org/ns/void#",
    "dqv": "http://www.w3.org/ns/dqv#",
    "oa": "http://www.w3.org/ns/oa#",
    "qb": "http://purl.org/linked-data/cube#",
    "csvw": "http://www.w3.org/ns/csvw#",
    "sosa": "http://www.w3.org/ns/sosa/",
    "schema": "https://schema.org/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "geo": "http://www.opengis.net/ont/geosparql#",
    "wgs": "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "iop": "https://w3id.org/iadopt/ont/",
    "sssom": "https://w3id.org/sssom/",
    "semapv": "https://w3id.org/semapv/vocab/",
    "qudt": "http://qudt.org/schema/qudt/",
    "unit": "http://qudt.org/vocab/unit/",
    "qk": "http://qudt.org/vocab/quantitykind/",
    "obo": "http://purl.obolibrary.org/obo/",
    "dwc": "http://rs.tdwg.org/dwc/terms/",
    "smn": SMN_NS,
    "gcdfo": GCDFO_NS,
    "psc": PSC_CONCEPT_NS,
}

#: Path templates under the base (section 6.2, extended). Placeholders are
#: filled with already-encoded segments by ``salmongraph.iri``; never format
#: these yourself.
LAYOUT: Mapping[str, str] = {
    "id": "id/{kind}/{authority}/{local}",
    "dataset": "dataset/{slug}/{version}",
    "distribution": "dataset/{slug}/{version}/dist/{name}",
    "table": "dataset/{slug}/{version}/table/{table}",
    "column": "dataset/{slug}/{version}/table/{table}/column/{column}",
    "obs": "obs/{slug}/{version}/{key}",
    "xwalk": "xwalk/{set}/{n}",
    "quality": "quality/{path}",
    "membership": "membership/{source}/{version}/{key}",
    "selection": "selection/{name}/{version}",
    "graph": "graph/{slug}/{version}/{part}",
    "corpus_graph": "graph/corpus/{version}/{name}",
    "vocab_graph": "graph/vocab/{key}/{pin}",
    "agent": "agent/{kind}/{path}",
    "activity": "activity/{kind}/{path}",
    "release": "release/{version}",
    "code": "code/{scheme}/{value}",
}

#: First path segment of every layout entry, plus ``profile`` (the default
#: profile home) and ``def`` (legacy, read-only). Used by ``iri.parse``.
TOP_LEVEL = ("id", "dataset", "obs", "xwalk", "quality", "membership", "selection",
             "graph", "agent", "activity", "release", "code", "profile", "def")

#: Named graphs every dataset release contributes (architecture.md 7.1).
DATASET_GRAPH_PARTS = ("metadata", "mappings", "identity", "cube", "provenance")

#: Corpus-level graphs written by combine/release (INTERFACES.md).
SHARED_GRAPHS = ("identity", "membership", "crosswalk", "quality", "review",
                 "vocab-pins", "catalog")

#: Slugs a dataset may not take, because ``graph/<slug>/`` is taken.
RESERVED_SLUGS = frozenset({"corpus", "vocab"})


class ConfigError(ValueError):
    """A configuration would break the namespace rules of section 6.2."""


_NS_IRI = re.compile(r"^https?://[^\s<>\"{}|\\^`?#]+/$")


def _check_base(name: str, value: str, *, terminators: str = "/") -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{name} must be a non-empty IRI string, got {value!r}")
    body, end = value[:-1], value[-1]
    if end not in terminators or not _NS_IRI.match(body + "/") or "#" in body:
        raise ConfigError(
            f"{name} must be an absolute http(s) IRI ending in {' or '.join(terminators)!s} "
            f"with no query, fragment or whitespace; got {value!r}")
    for key, ns in VOCAB_NAMESPACES.items():
        if ns.startswith(value):
            raise ConfigError(
                f"{name}={value!r} contains the {key} namespace {ns!r}; the IRI guard "
                "would then skip real vocabulary terms (section 6.2, condition 3)")
    for key, ns in (("gcdfo", GCDFO_NS), ("psc", PSC_VOCAB_NS)):
        if value.startswith(ns):
            raise ConfigError(f"{name}={value!r} lies under the {key} namespace; the corpus "
                              "does not mint in another authority's namespace")
    return value


@dataclass(frozen=True)
class Config:
    """One IRI layout: instance base, profile base and SDP vocabulary namespace.

    ``profile_base`` defaults to ``base + "profile/"`` and ``sdpv`` to
    ``profile_base + "sdp/"``. Instances are immutable and validated on
    construction (see the module docstring for the rules).
    """

    base: str = DEFAULT_BASE
    profile_base: str | None = None
    sdpv: str | None = None

    def __post_init__(self) -> None:
        _check_base("base", self.base)
        profile = self.profile_base or self.base + "profile/"
        _check_base("profile_base", profile)
        if profile == self.base:
            raise ConfigError("profile_base must differ from base")
        sdpv = self.sdpv or profile + "sdp/"
        _check_base("sdpv", sdpv, terminators="/#")
        object.__setattr__(self, "profile_base", profile)
        object.__setattr__(self, "sdpv", sdpv)

    # -- namespaces ---------------------------------------------------------
    @property
    def ns(self) -> dict[str, str]:
        """Prefix map: :data:`STATIC_NS` plus ``corpus``, ``id``, ``corp``, ``sdpv``."""
        out = dict(STATIC_NS)
        out.update({"corpus": self.base, "id": self.base + "id/",
                    "corp": self.profile_base, "sdpv": self.sdpv})
        return out

    @property
    def legacy_ns(self) -> dict[str, str]:
        """Read-only prefixes of the first pipeline's graph (``def:``).

        ``def:`` holds no definitions from 2026-10-23 (ADR-0001 D4); it is here
        only so the NuSEDS graph serialises with its prefix. Never mint under it.
        """
        return {"def": self.base + "def/"}

    @property
    def prefixes(self) -> dict[str, str]:
        """``ns`` plus ``legacy_ns``, sorted by prefix: the serialisation map."""
        merged = {**self.ns, **self.legacy_ns}
        return {k: merged[k] for k in sorted(merged)}

    @property
    def excluded_subtrees(self) -> tuple[str, ...]:
        """IRI prefixes the vocabulary guard must never treat as terms.

        Always the two smn sub-trees of D10, plus the base, profile base and
        sdpv namespace whenever one of them lies under a vocabulary namespace.
        """
        out = [SMN_DATA_SUBTREE, SMN_PROFILE_CORPUS_SUBTREE]
        for value in (self.base, self.profile_base, self.sdpv):
            if any(value.startswith(ns) for ns in VOCAB_NAMESPACES.values()):
                out.append(value)
        return tuple(sorted(set(out)))

    def join(self, template: str, **segments: str) -> str:
        """``base`` + ``LAYOUT[template]`` filled with pre-encoded segments.

        Low level: ``salmongraph.iri`` encodes and guards; call that instead.
        """
        return self.base + LAYOUT[template].format(**segments)


def from_env(env: Mapping[str, str] | None = None) -> Config:
    """Build a :class:`Config` from ``SALMONGRAPH_*`` variables (unset or empty = default)."""
    env = os.environ if env is None else env
    return Config(base=env.get(ENV_BASE) or DEFAULT_BASE,
                  profile_base=env.get(ENV_PROFILE_BASE) or None,
                  sdpv=env.get(ENV_SDPV_NS) or None)


_cached: Config | None = None
_stack: list[Config] = []


def current() -> Config:
    """The active configuration: the innermost :func:`override`, else the environment."""
    global _cached
    if _stack:
        return _stack[-1]
    if _cached is None:
        _cached = from_env()
    return _cached


def reset() -> None:
    """Forget the cached environment configuration; the next :func:`current` re-reads it."""
    global _cached
    _cached = None


@contextlib.contextmanager
def override(cfg: Config | None = None, **fields: str) -> Iterator[Config]:
    """Make ``cfg`` (or ``Config(**fields)``) current inside a ``with`` block.

    The fields are not merged with the environment, so the block is
    reproducible: ``override(base="https://w3id.org/smn/data/")`` gives that
    base with the default profile and sdpv derived from it.
    """
    if cfg is None:
        cfg = Config(**fields)
    elif fields:
        raise TypeError("pass either a Config or fields, not both")
    _stack.append(cfg)
    try:
        yield cfg
    finally:
        _stack.pop()


def __getattr__(name: str):  # PEP 562: dynamic module attributes
    if name == "BASE":
        return current().base
    if name == "PROFILE":
        return current().profile_base
    if name == "SDPV":
        return current().sdpv
    if name == "NS":
        return current().ns
    if name == "PREFIXES":
        return current().prefixes
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
