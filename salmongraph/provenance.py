"""ADR-0001 D6 marks on agent-derived content, and the PROV nodes they point to.

Every assertion a source does not state is agent-derived and carries:

======================  =====================================================
mark                    RDF (on the marked node or reifier)
======================  =====================================================
agent and model         ``prov:wasAttributedTo <agent>`` (see :func:`ai_agent`)
activity and date       ``prov:wasGeneratedBy <activity>`` (the activity has
                        ``dcterms:date``); optional ``dcterms:created`` on the
                        target
evidence                ``prov:wasDerivedFrom <iri>`` for a cited resource, or
                        ``prov:wasDerivedFrom _:e . _:e a prov:Entity ;
                        prov:value "text"`` for match statistics, a quoted
                        passage or the rule used
confidence              ``corp:confidence corp:highConfidence`` (or medium, low)
criticality             ``corp:criticality corp:critical`` (or ``corp:nonCritical``)
review status           ``corp:reviewStatus corp:agentAccepted`` only when high
                        and non-critical, else ``corp:awaitingReview``
======================  =====================================================

What to mark (INTERFACES.md, "D6 marks"):

* when one **statement** about an existing node is agent-derived (a mapping,
  a decomposition link, an identity link, a membership), reify it and mark
  the reifier: :func:`mark_statement`;
* when a **node** is agent-generated as a whole (a proposed profile concept, a
  selection-set entry, a discrepancy explanation), mark the node:
  :func:`mark_derived`.

Write the marks into the same named graph as the statement they mark. A
target is marked once per builder; review decisions (``review.py``) key on the
target IRI, so build it with ``iri.stable_key`` and never from a row number.

**Corpus profile terms minted here** (checked 2026-10-23 against PROV, PAV,
DQV, SSSOM, VoID, DCAT and schema.org; reasons in INTERFACES.md):
``corp:confidence``, ``corp:criticality``, ``corp:reviewStatus``; the schemes
``corp:confidenceLevels``, ``corp:criticalityLevels``, ``corp:reviewStatuses``;
and their ten value concepts. :func:`profile_vocabulary` declares them all.

Stable for downstream modules: the signatures of :func:`mark_derived`,
:func:`mark_statement`, :func:`review_status`, :func:`criticality_of`,
:func:`terms`, :func:`software_agent`, :func:`ai_agent`,
:func:`person_agent` and :func:`activity_node`. Extend by adding keyword
arguments with defaults; review queues, views and human decisions belong in
``review.py``, the run ledger in ``ledger.py``.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Iterable, Sequence, Union

import pyoxigraph as ox

from . import iri as _iri
from .config import Config
from .graph import GraphBuilder, L

__all__ = [
    "CONFIDENCE_LEVELS", "CRITICALITY_LEVELS", "REVIEW_STATUSES", "REVIEWED_STATUSES",
    "CRITICAL_ASPECTS", "NON_CRITICAL_ASPECTS", "ProfileTerms", "terms", "criticality_of",
    "review_status", "token_of", "profile_vocabulary", "mark_derived", "mark_statement",
    "software_agent", "ai_agent", "person_agent", "activity_node",
]

CONFIDENCE_LEVELS = ("high", "medium", "low")
CRITICALITY_LEVELS = ("critical", "non-critical")
#: ``agentAccepted`` and ``awaitingReview`` are set here; the human decisions
#: (``humanAccepted``, ``humanAmended``, ``rejected``) are set by ``review.py``.
REVIEW_STATUSES = ("agentAccepted", "awaitingReview", "humanAccepted", "humanAmended", "rejected")
#: Statuses the reviewed view keeps (architecture.md section 11).
REVIEWED_STATUSES = frozenset({"agentAccepted", "humanAccepted", "humanAmended"})

#: What makes an assertion critical: it can change a number or a join (ADR-0001 D6).
CRITICAL_ASPECTS = frozenset({
    "identity-equivalence",   # skos:exactMatch / closeMatch / broadMatch between authorities
    "membership",             # CU -> SMU, population -> CU, stock -> aggregate
    "measure-counts",         # sex, the "effective" adjustment, origin, life stage, jacks
    "unit-scale",
    "year-basis",             # brood year vs return year
    "age-notation",           # Gilbert-Rich vs European
    "estimate-type",
    "licence",                # licence or access terms
})
#: Examples of non-critical content.
NON_CRITICAL_ASPECTS = frozenset({"label", "description", "keyword", "documentation-link"})

_VALUE_LOCAL = {
    "high": "highConfidence", "medium": "mediumConfidence", "low": "lowConfidence",
    "critical": "critical", "non-critical": "nonCritical",
    "agentAccepted": "agentAccepted", "awaitingReview": "awaitingReview",
    "humanAccepted": "humanAccepted", "humanAmended": "humanAmended", "rejected": "rejected",
}

Evidence = Union[str, Sequence[str]]


@dataclass(frozen=True)
class ProfileTerms:
    """The corp: IRIs of the D6 marks under one configuration."""

    confidence: str
    criticality: str
    review_status: str
    schemes: dict[str, str]   # "confidence" | "criticality" | "reviewStatus" -> scheme IRI
    values: dict[str, str]    # token ("high", "non-critical", "awaitingReview", ...) -> concept IRI


def terms(cfg: Config | None = None) -> ProfileTerms:
    """corp: IRIs for the marks, under ``cfg`` (default: current configuration)."""
    t = lambda name: _iri.profile_term(name, cfg=cfg)  # noqa: E731
    return ProfileTerms(
        confidence=t("confidence"), criticality=t("criticality"), review_status=t("reviewStatus"),
        schemes={"confidence": t("confidenceLevels"), "criticality": t("criticalityLevels"),
                 "reviewStatus": t("reviewStatuses")},
        values={token: t(local) for token, local in _VALUE_LOCAL.items()},
    )


def token_of(concept_iri: str, cfg: Config | None = None) -> str | None:
    """Inverse of ``terms().values``: the ADR token for a value concept IRI, else None."""
    for token, value in terms(cfg).values.items():
        if value == concept_iri:
            return token
    return None


def criticality_of(aspect: str) -> str:
    """``"critical"`` or ``"non-critical"`` for an aspect token (see :data:`CRITICAL_ASPECTS`).

    Use this rather than choosing a criticality by hand, so the ADR rule lives
    in one place. Unknown aspects are refused.
    """
    if aspect in CRITICAL_ASPECTS:
        return "critical"
    if aspect in NON_CRITICAL_ASPECTS:
        return "non-critical"
    raise ValueError(f"unknown aspect {aspect!r}; critical: {sorted(CRITICAL_ASPECTS)}, "
                     f"non-critical: {sorted(NON_CRITICAL_ASPECTS)}")


def review_status(confidence: str, criticality: str) -> str:
    """``agentAccepted`` only for high confidence and non-critical; else ``awaitingReview``."""
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"confidence must be one of {CONFIDENCE_LEVELS}, got {confidence!r}")
    if criticality not in CRITICALITY_LEVELS:
        raise ValueError(f"criticality must be one of {CRITICALITY_LEVELS}, got {criticality!r}")
    return "agentAccepted" if (confidence, criticality) == ("high", "non-critical") else "awaitingReview"


# --------------------------------------------------------------------------
# The profile vocabulary itself
# --------------------------------------------------------------------------

_DEFS = {
    "confidence": ("confidence", "How sure the asserting agent is of an agent-derived assertion: high, "
                   "medium or low (ADR-0001 D6). Ordinal; sssom:confidence, when also given, is the "
                   "numeric score of a mapping."),
    "criticality": ("criticality", "Whether an agent-derived assertion can change a number or a join "
                    "(critical) or not (non-critical), per ADR-0001 D6."),
    "reviewStatus": ("review status", "Where an agent-derived assertion stands in review: "
                     "agentAccepted (high confidence and non-critical), awaitingReview, or a human "
                     "decision (humanAccepted, humanAmended, rejected)."),
}
_SCHEME_LABELS = {"confidence": "Confidence levels", "criticality": "Criticality levels",
                  "reviewStatus": "Review statuses"}
_VALUE_DEFS = {
    "high": "The agent's evidence directly supports the assertion.",
    "medium": "The evidence supports the assertion with gaps or assumptions.",
    "low": "The assertion is a guess the evidence barely supports.",
    "critical": "Can change a number or a join: identity equivalence or membership, what a measure "
                "counts, unit or scale, year basis, age notation, estimate type, licence or access.",
    "non-critical": "Cannot change a number or a join: labels, descriptions, keywords, documentation links.",
    "agentAccepted": "High confidence and non-critical: used, and still marked as agent-generated.",
    "awaitingReview": "Excluded from reviewed views until a person decides.",
    "humanAccepted": "A person accepted the assertion as stated.",
    "humanAmended": "A person accepted an amended form of the assertion.",
    "rejected": "A person rejected the assertion; kept for the record, excluded from every view but the full one.",
}
_SCHEME_OF = {"high": "confidence", "medium": "confidence", "low": "confidence",
              "critical": "criticality", "non-critical": "criticality"}
_NOTE = ("Provisional corpus profile term (salmongraph). Checked 2026-10-23 against PROV, PAV, DQV, "
         "SSSOM, VoID, DCAT and schema.org; salmongraph/INTERFACES.md records why none fits.")


def profile_vocabulary(graph: str, *, cfg: Config | None = None) -> list[ox.Quad]:
    """Declarations of every corp: term this module uses, as quads in ``graph``.

    Write them once per release into the ``vocab-pins`` or ``catalog`` graph, so
    the profile terms are self-describing in every store.
    """
    b = GraphBuilder(cfg=cfg)
    T = terms(b.cfg)
    root = _iri.check_mintable(b.cfg.profile_base, cfg=b.cfg)
    b.type(root, "owl:Ontology", graph)
    b.label(root, "Salmon data corpus profile (provisional)", graph)
    b.add(root, "skos:editorialNote", ox.Literal(_NOTE, language="en"), graph)
    for key, prop in (("confidence", T.confidence), ("criticality", T.criticality),
                      ("reviewStatus", T.review_status)):
        label, definition = _DEFS[key]
        b.type(prop, "owl:ObjectProperty", graph)
        b.label(prop, label, graph)
        b.add(prop, "skos:definition", ox.Literal(definition, language="en"), graph)
        b.add(prop, "rdfs:isDefinedBy", root, graph)
        b.add(prop, "rdfs:range", "skos:Concept", graph)
        b.add(prop, "skos:editorialNote", ox.Literal(_NOTE, language="en"), graph)
        scheme = T.schemes[key]
        b.type(scheme, "skos:ConceptScheme", graph)
        b.label(scheme, _SCHEME_LABELS[key], graph, predicate="skos:prefLabel")
        b.add(scheme, "rdfs:isDefinedBy", root, graph)
    for token, concept in T.values.items():
        scheme = T.schemes[_SCHEME_OF.get(token, "reviewStatus")]
        b.type(concept, "skos:Concept", graph)
        b.add(concept, "skos:inScheme", scheme, graph)
        b.add(scheme, "skos:hasTopConcept", concept, graph)
        b.label(concept, token, graph, predicate="skos:prefLabel")
        b.add(concept, "skos:notation", ox.Literal(token), graph)
        b.add(concept, "skos:definition", ox.Literal(_VALUE_DEFS[token], language="en"), graph)
        b.add(concept, "rdfs:isDefinedBy", root, graph)
    return b.quads


# --------------------------------------------------------------------------
# Marks
# --------------------------------------------------------------------------

_IRI_RE = re.compile(r"^(https?://|urn:)\S+$")


def _iri_of(x: object, what: str) -> str:
    if isinstance(x, ox.NamedNode):
        return x.value
    if isinstance(x, str) and _IRI_RE.match(x):
        return x
    raise ValueError(f"{what} must be an absolute IRI (review decisions key on it); got {x!r}")


def _iris(x: object, what: str) -> list[str]:
    if isinstance(x, (str, ox.NamedNode)):
        return [_iri_of(x, what)]
    out = [_iri_of(v, what) for v in x]  # type: ignore[union-attr]
    if not out:
        raise ValueError(f"{what} is required")
    return out


def _date_literal(value: object) -> ox.Literal:
    if isinstance(value, (_dt.date, _dt.datetime)):
        return L(value)
    s = str(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return L(s, "xsd:date")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})", s):
        return L(s, "xsd:dateTime")
    raise ValueError(f"date must be YYYY-MM-DD or an ISO date-time with a zone, got {value!r}")


def _evidence(value: Evidence) -> list[str]:
    items = [value] if isinstance(value, str) else list(value)
    items = [str(i).strip() for i in items if str(i).strip()]
    if not items:
        raise ValueError("evidence is required (ADR-0001 D6): the source passage, the match "
                         "statistics or the rule used")
    return items


def mark_derived(builder: GraphBuilder, target: str | ox.NamedNode, *, agent: str | Sequence[str],
                 activity: str, evidence: Evidence, confidence: str, criticality: str, graph: str,
                 date: str | _dt.date | None = None) -> str:
    """Write the D6 marks on ``target`` (a node or a reifier) into ``graph``; return the status.

    Parameters
    ----------
    builder:
        The graph builder to write into.
    target:
        IRI of the agent-generated node, or of the reifier of an
        agent-generated statement (see :func:`mark_statement`).
    agent:
        IRI(s) of the asserting agent(s): normally :func:`ai_agent` (the
        model) for an agent run; a software agent for a rule-based derivation.
    activity:
        IRI of the run or build activity (:func:`activity_node`), which
        carries the date.
    evidence:
        One or more items. An absolute IRI becomes ``prov:wasDerivedFrom
        <iri>``; any other text becomes a ``prov:Entity`` with ``prov:value``.
    confidence:
        ``"high"``, ``"medium"`` or ``"low"``.
    criticality:
        ``"critical"`` or ``"non-critical"``; prefer :func:`criticality_of`.
    graph:
        Named graph: the graph of the statement being marked.
    date:
        Optional ``dcterms:created`` on the target (YYYY-MM-DD from the
        inputs or the build-date argument, never the wall clock).

    Returns
    -------
    str
        ``"agentAccepted"`` or ``"awaitingReview"`` (see :func:`review_status`).

    Raises
    ------
    ValueError
        On an unknown token, a missing evidence item, a non-IRI target, or a
        target this builder has already marked.
    """
    status = review_status(confidence, criticality)
    t = _iri_of(target, "target")
    if t in builder.marked:
        raise ValueError(f"{t} is already marked ({builder.marked[t]}); mark a target once")
    agents = _iris(agent, "agent")
    act = _iri_of(activity, "activity")
    items = _evidence(evidence)
    T = terms(builder.cfg)
    for a in agents:
        builder.add(t, "prov:wasAttributedTo", a, graph)
    builder.add(t, "prov:wasGeneratedBy", act, graph)
    for item in items:
        if _IRI_RE.match(item):
            builder.add(t, "prov:wasDerivedFrom", item, graph)
        else:
            e = builder.bnode(t, "evidence", item)
            builder.add(t, "prov:wasDerivedFrom", e, graph)
            builder.add(e, "rdf:type", "prov:Entity", graph)
            builder.add(e, "prov:value", ox.Literal(item), graph)
    builder.add(t, T.confidence, T.values[confidence], graph)
    builder.add(t, T.criticality, T.values[criticality], graph)
    builder.add(t, T.review_status, T.values[status], graph)
    if date is not None:
        builder.add(t, "dcterms:created", _date_literal(date), graph)
    builder.marked[t] = status
    return status


def mark_statement(builder: GraphBuilder, reifier: str, s: object, p: object, o: object, *,
                   graph: str, agent: str | Sequence[str], activity: str, evidence: Evidence,
                   confidence: str, criticality: str, assert_triple: bool = True,
                   date: str | _dt.date | None = None) -> str:
    """Reify ``s p o`` as ``reifier`` (asserting it unless ``assert_triple=False``) and mark the reifier.

    The usual call for an agent-derived mapping, identity link or membership::

        r = iri.xwalk("sasap-psc-fraser", iri.stable_key(s, "skos:closeMatch", o))
        mark_statement(b, r, s, "skos:closeMatch", o, graph=XW, agent=model,
                       activity=run, evidence="totals agree within 0.5% for 66/68 years",
                       confidence="high", criticality=criticality_of("identity-equivalence"))

    Returns the review status, as :func:`mark_derived`.
    """
    builder.reify(reifier, s, p, o, graph, assert_triple=assert_triple)
    return mark_derived(builder, reifier, agent=agent, activity=activity, evidence=evidence,
                        confidence=confidence, criticality=criticality, graph=graph, date=date)


# --------------------------------------------------------------------------
# Agents and activities
# --------------------------------------------------------------------------

def software_agent(builder: GraphBuilder, name: str, version: str, *, graph: str,
                   label: str | None = None) -> str:
    """A ``prov:SoftwareAgent`` at ``agent/software/{name}/{version}``; returns its IRI."""
    a = _iri.software_agent(name, version, cfg=builder.cfg)
    builder.type(a, "prov:SoftwareAgent", graph)
    builder.label(a, label or f"{name} {version}", graph, lang=None)
    builder.add(a, "schema:name", ox.Literal(name), graph)
    builder.add(a, "schema:softwareVersion", ox.Literal(str(version)), graph)
    return a


def ai_agent(builder: GraphBuilder, model: str, *, graph: str, label: str | None = None,
             on_behalf_of: str | None = None) -> str:
    """An AI model as a ``prov:SoftwareAgent`` at ``agent/model/{model}``; returns its IRI.

    ``model`` is the exact model identifier the run used. ``on_behalf_of``
    (a person or organisation IRI) adds ``prov:actedOnBehalfOf``.
    """
    a = _iri.model_agent(model, cfg=builder.cfg)
    builder.type(a, "prov:SoftwareAgent", graph)
    builder.label(a, label or f"AI model {model}", graph, lang=None)
    builder.add(a, "schema:identifier", ox.Literal(str(model)), graph)
    if on_behalf_of:
        builder.add(a, "prov:actedOnBehalfOf", _iri_of(on_behalf_of, "on_behalf_of"), graph)
    return a


def person_agent(builder: GraphBuilder, name: str, *, graph: str, orcid: str | None = None) -> str:
    """A ``prov:Person`` (also ``foaf:Person``): the ORCID IRI when given, else ``agent/person/{slug}``."""
    if orcid:
        if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", orcid):
            raise ValueError(f"not an ORCID iD: {orcid!r}")
        a = f"https://orcid.org/{orcid}"
    else:
        a = _iri.person_agent(name, cfg=builder.cfg)
    builder.type(a, "prov:Person", graph)
    builder.type(a, "foaf:Person", graph)
    builder.add(a, "foaf:name", ox.Literal(name), graph)
    return a


def activity_node(builder: GraphBuilder, activity: str, *, graph: str, label: str,
                  date: str | _dt.date, used: Iterable[str] = (),
                  associated_with: Iterable[str] = (), informed_by: Iterable[str] = (),
                  started_at: str | None = None, ended_at: str | None = None) -> str:
    """A ``prov:Activity`` with its date, inputs and agents; returns its IRI.

    ``activity`` is an IRI from ``iri.activity(kind, ...)``. ``date``
    (YYYY-MM-DD) comes from the inputs or the build-date argument, never the
    wall clock; ``started_at`` / ``ended_at`` are optional ISO date-times with
    a zone, for runs whose times are recorded inputs (e.g. the run ledger).
    """
    a = _iri_of(activity, "activity")
    builder.type(a, "prov:Activity", graph)
    builder.label(a, label, graph)
    builder.add(a, "dcterms:date", _date_literal(date), graph)
    for u in used:
        builder.add(a, "prov:used", _iri_of(u, "used"), graph)
    for ag in associated_with:
        builder.add(a, "prov:wasAssociatedWith", _iri_of(ag, "associated_with"), graph)
    for i in informed_by:
        builder.add(a, "prov:wasInformedBy", _iri_of(i, "informed_by"), graph)
    for pred, value in (("prov:startedAtTime", started_at), ("prov:endedAtTime", ended_at)):
        if value:
            lit = _date_literal(value)
            if lit.datatype.value.rsplit("#", 1)[-1] != "dateTime":
                raise ValueError(f"{pred} needs an ISO date-time with a zone, got {value!r}")
            builder.add(a, pred, lit, graph)
    return a
