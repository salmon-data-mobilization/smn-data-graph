"""Minting helpers for corpus instance and profile IRIs (architecture.md 6.2).

Every corpus IRI is built here, from the layout in ``salmongraph.config``.
Two kinds of path segment exist:

* **names** (``kind``, ``authority``, dataset ``slug``, mapping-set and
  scheme names): lower-case kebab tokens, checked and never altered. Make one
  from free text with :func:`slug`.
* **values** (local identifiers, versions, observation keys, column names,
  code values): any text, percent-encoded with :func:`segment`, which keeps
  RFC 3986 unreserved characters (``A-Z a-z 0-9 - . _ ~``) as they are and is
  exactly reversible with :func:`unsegment`. For a local identifier made only
  of unreserved characters, :func:`ident` returns the same IRI as
  ``pipelines/corpuslib.ident`` (tests pin this), so the NuSEDS graph keeps
  joining.

Persistence (section 6.2, condition 4): an IRI, once published, is never
reused for something else. Build keys from source identifiers, never from row
numbers; :func:`stable_key` gives a short deterministic key for things with no
natural identifier (crosswalk assertions, quality annotations).

Guards applied to every minted IRI (:func:`check_mintable`):

* it must lie under the configured base or profile base;
* no query, fragment, whitespace or dot segment;
* never a single-segment IRI directly under ``https://w3id.org/smn/``
  (section 6.2, condition 2): smn's w3id catch-all would capture it as a term.
  This matters if the base is ever moved under smn (ADR-0001 D10).
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from dataclasses import dataclass
from typing import Iterable

from . import config as _config
from .config import (DATASET_GRAPH_PARTS, LAYOUT, RESERVED_SLUGS, SHARED_GRAPHS, SMN_NS,
                     TOP_LEVEL, Config)

__all__ = [
    "MintError", "AGENT_KINDS", "ACTIVITY_KINDS", "slug", "segment", "unsegment", "stable_key",
    "check_mintable", "ident", "dataset", "distribution", "table", "column", "obs", "xwalk",
    "quality", "membership", "selection", "named_graph", "dataset_graphs", "corpus_graph",
    "vocab_graph", "agent", "software_agent", "model_agent", "person_agent", "org_agent",
    "activity", "release", "code", "profile_term", "profile_scheme", "profile_concept",
    "sdpv_term", "ParsedIRI", "parse",
]

#: ``agent/{kind}/...``: who or what acted (PROV agents).
AGENT_KINDS = ("software", "model", "person", "org")
#: ``activity/{kind}/...``: what was done (PROV activities).
ACTIVITY_KINDS = ("build", "agent-run", "combine", "release", "review", "ingest", "publish")


class MintError(ValueError):
    """An IRI would break the layout or the namespace rules of section 6.2."""


_NAME_RE = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")
_TERM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
_SMN_CATCH_ALL = re.compile(r"^[A-Za-z0-9._-]+/?$")  # perma-id ids/smn/.htaccess, 2026-10-23
_BAD_CHARS = re.compile(r"[\s<>\"{}|\\^`?#]")


def _cfg(cfg: Config | None) -> Config:
    return cfg if cfg is not None else _config.current()


def _name(value: object, what: str) -> str:
    text = str(value) if value is not None else ""
    if not _NAME_RE.match(text):
        raise MintError(f"{what} must be a lower-case kebab token like 'dfo-nuseds' "
                        f"(use iri.slug() on free text); got {value!r}")
    return text


def _scalar(value: object) -> object:
    # numpy / pandas scalars (np.int64 from a DataFrame) become Python scalars,
    # so 7 and np.int64(7) mint the same IRI.
    item = getattr(value, "item", None)
    if callable(item) and type(value).__module__.split(".")[0] in ("numpy", "pandas"):
        try:
            return item()
        except (TypeError, ValueError):
            return value
    return value


def slug(text: object) -> str:
    """Lossy, stable kebab slug for free text: ``"Fraser / Chilko"`` -> ``"fraser-chilko"``.

    Same rule as ``corpuslib.slug_iri`` (runs of anything but ASCII letters and
    digits become one ``-``; lower case). Not reversible: use it for names,
    never for source identifiers (use :func:`segment` for those).
    """
    out = re.sub(r"[^A-Za-z0-9]+", "-", str(_scalar(text))).strip("-").lower()
    if not out:
        raise MintError(f"slug({text!r}) is empty")
    return out


def segment(value: object) -> str:
    """Percent-encode one path segment, reversibly (see :func:`unsegment`).

    Unreserved characters stay as they are; everything else, including ``/``,
    becomes ``%XX`` (upper-case hex, UTF-8). ``.`` and ``..`` are encoded too,
    because IRI normalisation would otherwise remove them. Empty and missing
    values are refused.
    """
    value = _scalar(value)
    if (value is None or isinstance(value, float) and value != value
            or type(value).__name__ in ("NAType", "NaTType")):
        raise MintError("cannot mint from a missing value")
    if isinstance(value, bool):
        raise MintError("cannot mint from a bool; pass a string")
    text = str(value)
    if text == "":
        raise MintError("cannot mint from an empty string")
    if text in (".", ".."):
        return text.replace(".", "%2E")
    return urllib.parse.quote(text, safe="-._~")


def unsegment(seg: str) -> str:
    """Inverse of :func:`segment`."""
    return urllib.parse.unquote(seg)


def stable_key(*parts: object, length: int = 16) -> str:
    """Deterministic short key: first ``length`` hex digits of sha256 over the parts.

    Use for things with no natural identifier, e.g.
    ``xwalk("sasap-psc-fraser", stable_key(subject, predicate, object))``,
    so the same assertion keeps the same IRI on every rebuild.
    """
    if not parts:
        raise MintError("stable_key needs at least one part")
    joined = "\x1f".join(str(_scalar(p)) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


def check_mintable(iri: str, *, cfg: Config | None = None) -> str:
    """Return ``iri`` if the corpus may mint it, else raise :class:`MintError`."""
    c = _cfg(cfg)
    # The namespaces themselves were validated by Config (an sdpv namespace may
    # end in '#'); only the part after the longest matching one is checked here.
    spaces = sorted((ns for ns in (c.base, c.profile_base, c.sdpv) if iri.startswith(ns)), key=len)
    if not spaces:
        raise MintError(f"{iri!r} is not under the corpus base {c.base!r} or profile "
                        f"{c.profile_base!r}")
    if _BAD_CHARS.search(iri[len(spaces[-1]):]):
        raise MintError(f"minted IRI has a query, fragment or unsafe character: {iri!r}")
    if iri.startswith(SMN_NS) and _SMN_CATCH_ALL.match(iri[len(SMN_NS):]):
        raise MintError(f"{iri!r} is a single-segment IRI directly under smn; smn's w3id "
                        "catch-all would capture it as a term (section 6.2, condition 2)")
    path = urllib.parse.urlsplit(iri).path
    if any(s in (".", "..") for s in path.split("/")):
        raise MintError(f"{iri!r} has a dot segment")
    return iri


def _mint(template: str, cfg: Config | None, **segments: str) -> str:
    c = _cfg(cfg)
    return check_mintable(c.join(template, **segments), cfg=c)


def _join(values: Iterable[object]) -> str:
    parts = [segment(v) for v in values]
    if not parts:
        raise MintError("at least one path segment is required")
    return "/".join(parts)


def _dataset_slug(value: object) -> str:
    s = _name(value, "dataset slug")
    if s in RESERVED_SLUGS:
        raise MintError(f"dataset slug {s!r} is reserved (graph/{s}/ is taken)")
    return s


# --------------------------------------------------------------------------
# Instance IRIs (under BASE)
# --------------------------------------------------------------------------

def ident(kind: str, authority: str, local_id: object, *, cfg: Config | None = None) -> str:
    """Identity node: ``{BASE}id/{kind}/{authority}/{local-id}``.

    ``kind``: cu, smu, du, stock, population, stream, site, region, ...
    ``authority``: who issued ``local_id`` (dfo, psf, dfo-nuseds, psc-frsk, sasap,
    ...). ``local_id`` is the source's own key, verbatim (percent-encoded).
    Nodes of different authorities are never merged (ADR-0001 D5).
    """
    return _mint("id", cfg, kind=_name(kind, "kind"), authority=_name(authority, "authority"),
                 local=segment(local_id))


def dataset(slug_: str, version: object, *, cfg: Config | None = None) -> str:
    """Dataset release: ``{BASE}dataset/{slug}/{version}``."""
    return _mint("dataset", cfg, slug=_dataset_slug(slug_), version=segment(version))


def distribution(slug_: str, version: object, name: str, *, cfg: Config | None = None) -> str:
    """Distribution of a dataset release: ``{BASE}dataset/{slug}/{version}/dist/{name}``."""
    return _mint("distribution", cfg, slug=_dataset_slug(slug_), version=segment(version),
                 name=_name(name, "distribution name"))


def table(slug_: str, version: object, table_id: object, *, cfg: Config | None = None) -> str:
    """CSVW table: ``{BASE}dataset/{slug}/{version}/table/{table}``."""
    return _mint("table", cfg, slug=_dataset_slug(slug_), version=segment(version),
                 table=segment(table_id))


def column(slug_: str, version: object, table_id: object, column_name: object, *,
           cfg: Config | None = None) -> str:
    """CSVW column, named exactly as in the source: ``.../table/{table}/column/{column}``."""
    return _mint("column", cfg, slug=_dataset_slug(slug_), version=segment(version),
                 table=segment(table_id), column=segment(column_name))


def obs(slug_: str, version: object, *key: object, cfg: Config | None = None) -> str:
    """Observation: ``{BASE}obs/{slug}/{version}/{key...}``.

    ``key`` is one or more source values (stock id, year, measure, ...), each
    encoded as its own segment, so the key is reversible. Observation IRIs
    resolve to their dataset release page, not one page each (6.2 condition 5).
    """
    return _mint("obs", cfg, slug=_dataset_slug(slug_), version=segment(version), key=_join(key))


def xwalk(mapping_set: str, n: object, *, cfg: Config | None = None) -> str:
    """Crosswalk assertion (a reifier): ``{BASE}xwalk/{mapping-set}/{n}``.

    Prefer ``n = stable_key(subject, predicate, object)`` over a counter.
    """
    return _mint("xwalk", cfg, set=_name(mapping_set, "mapping set"), n=segment(n))


def quality(*path: object, cfg: Config | None = None) -> str:
    """Quality annotation: ``{BASE}quality/{path...}``, e.g. ``quality("efs-vs-total", key)``."""
    return _mint("quality", cfg, path=_join(path))


def membership(source: str, version: object, key: object, *, cfg: Config | None = None) -> str:
    """Membership assertion (a reifier): ``{BASE}membership/{source}/{version}/{key}``.

    ``source`` names the publishing source (``dfo-smu-cu``), ``version`` its
    version (``2025-11-28``), ``key`` the member's source key (``CK-01``).
    """
    return _mint("membership", cfg, source=_name(source, "membership source"),
                 version=segment(version), key=segment(key))


def selection(name: str, version: object, *, cfg: Config | None = None) -> str:
    """Selection set: ``{BASE}selection/{name}/{version}``."""
    return _mint("selection", cfg, name=_name(name, "selection name"), version=segment(version))


def named_graph(slug_: str, version: object, part: str, *, cfg: Config | None = None) -> str:
    """Named graph of a dataset release: ``{BASE}graph/{slug}/{version}/{part}``.

    ``part`` is one of ``config.DATASET_GRAPH_PARTS``.
    """
    if part not in DATASET_GRAPH_PARTS:
        raise MintError(f"dataset graph part must be one of {DATASET_GRAPH_PARTS}, got {part!r}")
    return _mint("graph", cfg, slug=_dataset_slug(slug_), version=segment(version), part=part)


def dataset_graphs(slug_: str, version: object, *, cfg: Config | None = None) -> dict[str, str]:
    """All named graphs of a dataset release, keyed by part."""
    return {p: named_graph(slug_, version, p, cfg=cfg) for p in DATASET_GRAPH_PARTS}


def corpus_graph(name: str, corpus_version: object, *, cfg: Config | None = None) -> str:
    """Shared corpus graph: ``{BASE}graph/corpus/{corpus-version}/{name}``.

    ``name`` is one of ``config.SHARED_GRAPHS``.
    """
    if name not in SHARED_GRAPHS:
        raise MintError(f"shared graph must be one of {SHARED_GRAPHS}, got {name!r}")
    return _mint("corpus_graph", cfg, version=segment(corpus_version), name=name)


def vocab_graph(key: str, sha256: str, *, cfg: Config | None = None) -> str:
    """Graph holding one pinned vocabulary: ``{BASE}graph/vocab/{key}/sha256-{16 hex}``."""
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise MintError(f"vocab_graph needs a sha256 hex digest, got {sha256!r}")
    return _mint("vocab_graph", cfg, key=_name(key, "vocabulary key"), pin=f"sha256-{sha256[:16]}")


def agent(kind: str, *path: object, cfg: Config | None = None) -> str:
    """PROV agent: ``{BASE}agent/{kind}/{path...}``; ``kind`` in :data:`AGENT_KINDS`."""
    if kind not in AGENT_KINDS:
        raise MintError(f"agent kind must be one of {AGENT_KINDS}, got {kind!r}")
    return _mint("agent", cfg, kind=kind, path=_join(path))


def software_agent(name: str, version: object, *, cfg: Config | None = None) -> str:
    """``{BASE}agent/software/{name}/{version}``, e.g. metasalmonpy 0.6.0."""
    return agent("software", _name(name, "software name"), version, cfg=cfg)


def model_agent(model_id: object, *, cfg: Config | None = None) -> str:
    """``{BASE}agent/model/{model-id}``: an AI model acting as an agent."""
    return agent("model", model_id, cfg=cfg)


def person_agent(name: object, *, cfg: Config | None = None) -> str:
    """``{BASE}agent/person/{slug(name)}``. Use the ORCID IRI instead whenever one is known."""
    return agent("person", slug(name), cfg=cfg)


def org_agent(name: object, *, cfg: Config | None = None) -> str:
    """``{BASE}agent/org/{slug(name)}``. Use a ROR IRI instead whenever one is known."""
    return agent("org", slug(name), cfg=cfg)


def activity(kind: str, *path: object, cfg: Config | None = None) -> str:
    """PROV activity: ``{BASE}activity/{kind}/{path...}``; ``kind`` in :data:`ACTIVITY_KINDS`.

    Examples: ``activity("build", slug, version)``, ``activity("agent-run", run_id)``,
    ``activity("combine", corpus_version)``.
    """
    if kind not in ACTIVITY_KINDS:
        raise MintError(f"activity kind must be one of {ACTIVITY_KINDS}, got {kind!r}")
    return _mint("activity", cfg, kind=kind, path=_join(path))


def release(version: object, *, cfg: Config | None = None) -> str:
    """Corpus release (a dcat:Dataset / void:Dataset): ``{BASE}release/{version}``."""
    return _mint("release", cfg, version=segment(version))


def code(scheme: str, value: object, *, cfg: Config | None = None) -> str:
    """Source code value as a SKOS concept: ``{BASE}code/{scheme}/{value}``.

    ``scheme`` is one or more ``/``-separated names (``nuseds/estimate-classification``,
    as the NuSEDS pipeline uses); ``value`` is the source code, verbatim.
    """
    parts = str(scheme).split("/")
    return _mint("code", cfg, scheme="/".join(_name(p, "code scheme") for p in parts),
                 value=segment(value))


# --------------------------------------------------------------------------
# Profile IRIs (under PROFILE, prefix corp:) and the SDP vocabulary (sdpv:)
# --------------------------------------------------------------------------

def profile_term(local_name: str, *, cfg: Config | None = None) -> str:
    """Structural corpus profile term ``corp:{localName}`` (property or value).

    Mint one only after checking PROV, PAV, DQV, SSSOM, VoID, DCAT and
    schema.org, and list it with the reason in INTERFACES.md.
    """
    if not _TERM_RE.match(local_name or ""):
        raise MintError(f"profile term must be camelCase ASCII, got {local_name!r}")
    c = _cfg(cfg)
    return check_mintable(c.profile_base + local_name, cfg=c)


def profile_scheme(scheme: str, *, cfg: Config | None = None) -> str:
    """Corpus profile SKOS concept scheme: ``{PROFILE}{scheme}`` (e.g. ``variables``)."""
    c = _cfg(cfg)
    return check_mintable(c.profile_base + _name(scheme, "profile scheme"), cfg=c)


def profile_concept(scheme: str, concept: str, *, cfg: Config | None = None) -> str:
    """Corpus profile SKOS concept: ``{PROFILE}{scheme}/{concept}``.

    For compound variables with no gcdfo or PSC home, interim atomic
    constraints awaiting an smn term request, and explanation classes. Never
    for an atomic concept smn or gcdfo already has.
    """
    c = _cfg(cfg)
    return check_mintable(profile_scheme(scheme, cfg=c) + "/" + _name(concept, "profile concept"), cfg=c)


def sdpv_term(local_name: str, *, cfg: Config | None = None) -> str:
    """SDP vocabulary property ``sdpv:{localName}`` (provisional namespace; see config)."""
    if not _TERM_RE.match(local_name or ""):
        raise MintError(f"sdpv term must be camelCase ASCII, got {local_name!r}")
    c = _cfg(cfg)
    return check_mintable(c.sdpv + local_name, cfg=c)


# --------------------------------------------------------------------------
# Debugging: invert the layout
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedIRI:
    """What :func:`parse` found: the layout entry and its decoded segments."""

    kind: str                 # a LAYOUT key, or "profile", "sdpv", "legacy-def"
    parts: dict[str, str]     # decoded placeholder values; multi-segment values joined by "/"
    iri: str


def parse(iri: str, *, cfg: Config | None = None) -> ParsedIRI | None:
    """Invert the layout for debugging: which pattern minted ``iri``, with what values.

    Returns ``None`` for an IRI outside the corpus base and profile. Multi-
    segment placeholders (observation keys, quality paths, agent paths) come
    back as decoded segments joined by ``/``; use ``iri`` itself when exact
    reconstruction matters.
    """
    c = _cfg(cfg)
    if iri.startswith(c.sdpv):
        return ParsedIRI("sdpv", {"term": iri[len(c.sdpv):]}, iri)
    if iri.startswith(c.profile_base):
        rest = iri[len(c.profile_base):].split("/")
        parts = {"term": rest[0]} if len(rest) == 1 else {"scheme": rest[0], "concept": "/".join(rest[1:])}
        return ParsedIRI("profile", parts, iri)
    if not iri.startswith(c.base):
        return None
    segs = iri[len(c.base):].split("/")
    head = segs[0]
    if head not in TOP_LEVEL:
        return None
    if head == "def":
        return ParsedIRI("legacy-def", {"term": "/".join(segs[1:])}, iri)
    if head == "graph" and len(segs) >= 2 and segs[1] in ("corpus", "vocab"):
        key = "corpus_graph" if segs[1] == "corpus" else "vocab_graph"
        names = ("version", "name") if key == "corpus_graph" else ("key", "pin")
        return ParsedIRI(key, {n: unsegment(v) for n, v in zip(names, segs[2:])}, iri)
    if head == "dataset":
        for key in ("column", "table", "distribution", "dataset"):
            tmpl = LAYOUT[key].split("/")
            if len(tmpl) == len(segs) and all(t == s for t, s in zip(tmpl, segs) if not t.startswith("{")):
                return ParsedIRI(key, {t[1:-1]: unsegment(s) for t, s in zip(tmpl, segs) if t.startswith("{")}, iri)
        return ParsedIRI("dataset", {"path": "/".join(unsegment(s) for s in segs[1:])}, iri)
    if head == "code":
        if len(segs) < 3:
            return None
        return ParsedIRI("code", {"scheme": "/".join(segs[1:-1]), "value": unsegment(segs[-1])}, iri)
    key = head if head in LAYOUT else None
    if key is None:
        return None
    tmpl = LAYOUT[key].split("/")
    names = [t[1:-1] for t in tmpl[1:]]
    values = segs[1:]
    parts: dict[str, str] = {}
    for i, name in enumerate(names):
        if i == len(names) - 1:
            parts[name] = "/".join(unsegment(v) for v in values[i:])
        elif i < len(values):
            parts[name] = unsegment(values[i])
    return ParsedIRI(key, parts, iri)
