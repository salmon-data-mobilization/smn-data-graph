"""Review queues, human decisions and reviewed views (ADR-0001 D6; architecture.md 11).

Built on the marks ``provenance.mark_derived`` and ``provenance.mark_statement``
write. Six jobs:

**Queue.** Every target whose ``corp:reviewStatus`` is ``awaitingReview``,
and every ``agentAccepted`` target the D6 rule does not allow (below),
one row each, sorted: critical first, then by how many downstream joins
depend on it (observations whose ``review_status`` it decides, crosswalk
links through it), then by target IRI. Written as CSV with
:data:`REVIEW_QUEUE_COLUMNS` (``review-queue.csv`` in each dataset build and in
each release). The queue never suggests a decision.

**Criticality floor** (design review S6a). An agent may raise criticality,
never lower it. A statement whose predicate is in
``provenance.CRITICAL_PREDICATES`` (identity and membership links and their
validity, I-ADOPT decomposition, measure concept, unit, cube dimension,
method, licence), or one the store declares a sub-property, equivalent or
inverse of such a predicate, is critical whatever its mark says, so ``agentAccepted`` on it is pending in
effect, as is ``agentAccepted`` on any target whose own marks are not high
confidence and non-critical. Such a target is queued with its recorded status
and its effective criticality, the reviewed view leaves it out, and applying a
ledger refuses it while its triple is asserted, until a person decides it. A
node target (marked whole by ``mark_derived``) is under the floor when its own
content asserts such a link (one no review target or amendment of its own
governs). A node asserts its content by definition, so applying a ledger
refuses that node in every state but ``humanAccepted``: pending, rejected or
agent-accepted, its critical links would otherwise be live triples. A producer
keeps such a link statement-only by reifying it with ``mark_statement``.

**Assertion keys** (design review E6). A decision attaches to an assertion by
its content, never by its reifier IRI or a sequence number.
:func:`assertion_key` is the SHA-256 of :data:`KEY_SCHEME`, the N-Triples forms
of subject, predicate and object, and the **mapping set**. The mapping set of
a reifier is the namespace it was minted in: its IRI up to and including the
last ``/`` (:func:`mapping_set_of`; ``xwalk/{set}/``,
``membership/{source}/{version}/``, the legacy ``assertion/{slug}/``). A
rebuild that renumbers or re-hashes reifiers keeps every key, and the same
triple proposed in two mapping sets is two review records. A node target
(marked whole by ``mark_derived``) is keyed by its IRI **and its content**
(:func:`node_key` over :func:`node_content`, which the ledger row records), so
a rebuild that gives the IRI other content reports the decision missing
instead of approving content nobody reviewed. Statements about the node that
have their own review records, its D6 record and curation marks are not part
of its content. A statement, or a node's content, with a blank node has no
stable key and cannot be decided.

**Decision ledger.** A person records decisions in ``reviews/decisions.csv``
(committed; :data:`DECISION_COLUMNS`), keyed by assertion key. The ledger is
append-only: rows are never edited or removed, and :func:`load_decisions`
accepts only the canonical bytes that :func:`append_decision` writes. A key
has at most one effective decision; a later row for the same key must name
the :func:`decision_id` of the row it replaces in ``supersedes``, so a change
of mind is explicit and two conflicting rows fail. ``target`` records the IRI
the person saw, for audit; matching uses the key. :func:`record_decision` is
the tool a person uses. Agents never write decision rows, and nothing here
infers, suggests or defaults a decision.

**Applying decisions.** :func:`apply_ledger` turns an agent-built store into
the decided store, deterministically. Every target keeps exactly **one**
``corp:reviewStatus``: the decision replaces the agent status in the graphs
that held it. In the review graph the target gets ``pav:curatedBy`` (a
``prov:Person``, ORCID when known) and ``pav:curatedOn`` (xsd:dateTime, only
when a time was recorded; a date-only decision uses ``dcterms:date`` with
xsd:date rather than inventing a time), the note as ``skos:editorialNote``,
``sssom:reviewer_id`` on SSSOM mappings, and a ``prov:Activity`` at
``activity/review/{decision_id}`` that ``prov:used`` it (also typed
``semapv:MappingReview`` when the target is an SSSOM mapping, one with a
``sssom:mapping_justification``). Then, by decision:

* ``humanAccepted``: the reified triple is asserted in the reifier's graphs;
* ``rejected``: nothing is asserted (an agent-accepted triple is withdrawn);
* ``humanAmended``: the original stays statement-only, and the amended triple
  is asserted with its own reifier at ``xwalk/review-amendment/{key}``, which
  ``prov:wasRevisionOf`` and ``prov:wasDerivedFrom`` the original and carries
  ``sssom:mapping_justification semapv:ManualMappingCuration`` (a person made it).

Criticality and confidence are never changed, and no decision asserts a
triple whose subject is an IRI under the smn, gcdfo or PSC namespaces. No
sub-tree is exempt: the corpus has its own root and mints nothing under
``https://w3id.org/smn/``, so ``smn/data/`` and ``smn/profile/corpus/`` (the
D10 proposal) are refused like any smn IRI. Pending assertions with no
decision stay statement-only. Decisions whose key matches nothing are
reported in :attr:`LedgerApplication.missing`, never dropped silently.
Re-applying the same ledger to a decided store changes nothing; a store
decided with another ledger is refused (apply to the agent-built store). The
dataset build does not apply decisions; it records the ledger state
(:func:`ledger_state`) and a release applies a snapshot of the ledger
(:func:`snapshot_decisions`) when it materialises its views.

**Views.** In a decided store both views keep pending and rejected statements,
and the critical links of pending and rejected node targets,
**statement-only**: their reifiers, marks and evidence remain, their triples
are not asserted (:func:`apply_ledger` guarantees it). The other content of a
pending or rejected node target stays in the full view. The reviewed view
(:func:`view_quads`, :func:`view_store`) enforces it for any store: it keeps a
live triple only when a source states it or a reviewed status supports it
(``humanAccepted``, an amendment, or an ``agentAccepted`` the D6 rule and the
criticality floor allow), removes any live triple whose only support is
pending, rejected or amended away, refuses a triple that is both, and strips a
pending or rejected node target to its D6 record (with the blank-node
structure only its stripped content reached). It refuses a human status
without the record :func:`apply_ledger` writes, so a hand-set approval is no
proof. The full view is the store as given, with status shown.
:func:`materialise_views` applies a ledger and returns both.

The dependent facts an acceptance implies are asserted only for the year
basis (an observation's canonical year, as the compiler does for a live
binding). Observation Parquet is not rewritten: its ``review_status`` has no
target IRI to decide it by.

**Legacy statements.** The legacy NuSEDS pipeline writes candidates as RDF 1.1
``rdf:Statement`` nodes with ``dcterms:source`` evidence and an
``rdfs:comment`` holding the source pairing context.
:func:`convert_legacy_statements` rewrites them as RDF 1.2 reifiers (same
IRI, same graph), keeps every original property, adds ``prov:wasDerivedFrom``
for each cited source and the context as a ``prov:Entity`` value, and maps a
legacy profile namespace onto the current one. A statement node under the smn,
gcdfo or PSC namespaces is refused, since converting writes triples about it.
Applying decisions and building views refuse unconverted legacy targets. Every
reader of review marks (queue, counts, keys, node content, decisions,
application, the reviewed view) also refuses a ``reviewStatus`` predicate in
another profile namespace: when the base moves, the legacy NuSEDS graph keeps
its original profile IRIs, and its candidates would otherwise not be targets at
all (convert them with ``legacy_profile=`` first).

No function here establishes scientific correctness, reviewer identity or
publication readiness; a recorded decision is the reviewer's claim.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace
import csv
import datetime as _dt
import hashlib
import io
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Mapping, Sequence

import pyoxigraph as ox

from . import config, iri, provenance
from .config import ROOT
from .graph import RDF_REIFIES, GraphBuilder, N, expand
from .io import det

if TYPE_CHECKING:  # pragma: no cover
    from .vocab import VocabIndex

__all__ = ["REVIEW_QUEUE_COLUMNS", "DECISION_COLUMNS", "DECISION_TOKENS", "DECISIONS_PATH", "VIEWS",
           "KEY_SCHEME", "AMENDMENT_MAPPING_SET", "LedgerError", "ReviewItem", "Decision",
           "LedgerApplication", "MaterialisedViews", "LegacyConversion", "review_queue",
           "write_review_queue", "assertion_key", "node_key", "node_content", "mapping_set_of", "review_keys",
           "decision_id", "load_decisions", "effective_decisions", "append_decision",
           "record_decision", "ledger_state", "snapshot_decisions", "verify_decisions_snapshot",
           "apply_ledger", "apply_decisions", "view_quads", "view_store", "materialise_views",
           "convert_legacy_statements", "status_counts"]

REVIEW_QUEUE_COLUMNS = ("target", "status", "criticality", "confidence", "statement", "graph",
                        "agent", "activity", "date", "evidence", "suggested_decision",
                        "downstream_joins")
#: Columns of ``reviews/decisions.csv``, in file order.
DECISION_COLUMNS = ("key", "target", "subject", "predicate", "object", "mapping_set", "node_content",
                    "decision", "reviewer", "reviewer_orcid", "date", "amended_object", "note",
                    "review_minutes", "supersedes")
#: The decisions a person can record (``provenance.REVIEW_STATUSES`` minus the agent ones).
DECISION_TOKENS = ("humanAccepted", "humanAmended", "rejected")
#: ``reviews/decisions.csv`` at the repository root (committed).
DECISIONS_PATH = ROOT / "reviews" / "decisions.csv"
VIEWS = ("reviewed", "full")
#: Version tag hashed into every assertion key; change it only with a key migration.
#: ``/2`` (2026-10-24) keys a node target by its content as well as its IRI; no
#: ledger row was ever written under ``/1``, so there was nothing to migrate.
KEY_SCHEME = "salmongraph-assertion-key/2"
#: Mapping-set name of the reifiers that carry human-amended statements.
AMENDMENT_MAPPING_SET = "review-amendment"


class LedgerError(ValueError):
    """A decision, the decision ledger or its application breaks the review contract."""


@dataclass(frozen=True)
class ReviewItem:
    """One queue row; fields match :data:`REVIEW_QUEUE_COLUMNS`."""

    target: str
    status: str
    criticality: str
    confidence: str
    statement: str          # N-Triples of the reified triple, or "" for a node target
    graph: str
    agent: str
    activity: str
    date: str
    evidence: str           # items joined with " | "
    suggested_decision: str
    downstream_joins: int


@dataclass(frozen=True)
class Decision:
    """One row of ``reviews/decisions.csv``; fields match :data:`DECISION_COLUMNS`.

    ``subject``, ``predicate``, ``object`` and ``amended_object`` are canonical
    N-Triples terms; all four and ``mapping_set`` are empty for a node target.
    ``node_content`` is :func:`node_content` of a node target (the SHA-256 of
    the content the person reviewed) and empty for a statement. ``key`` may be
    left empty when building a row: :func:`append_decision` computes it from
    the content (and refuses a key that disagrees).
    """

    target: str
    decision: str           # humanAccepted | humanAmended | rejected
    reviewer: str
    date: str               # YYYY-MM-DD, or an ISO date-time with a zone
    reviewer_orcid: str | None = None
    amended_object: str | None = None
    note: str | None = None
    key: str = ""
    subject: str = ""
    predicate: str = ""
    object: str = ""
    mapping_set: str = ""
    node_content: str = ""
    review_minutes: float | None = None
    supersedes: str | None = None


def review_queue(data: "ox.Store | Iterable[ox.Quad]", *, graphs: Sequence[str] | None = None) -> list[ReviewItem]:
    """Actual pending records, critical first, then recorded dependencies, then IRI.

    A record is pending when it awaits review, or when it is ``agentAccepted``
    although its marks or its predicate do not allow that (low or medium
    confidence, a critical label, or a predicate with a criticality floor,
    :func:`provenance.criticality_floor` closed over the sub-, equivalent and
    inverse properties the data declares; or a node whose own content asserts
    such a predicate): such a row keeps its recorded
    status, so the mislabel stays visible. ``criticality`` is the effective
    one: the recorded label, raised to ``critical`` by the predicate's floor
    (an agent may raise criticality, never lower it; design review S6a).
    ``graphs`` selects targets by the graphs containing their pending status.
    The full supplied data still determines consistency, evidence, dates and
    dependency counts; counts are not limited to the selected target graphs.
    Multivalued graph/agent/activity/date fields are sorted display lists joined
    with ``" | "``, not an assertion that they represent one activity or date.
    No date, confidence, model, approval or suggested decision is inferred.
    """
    index = _ReviewIndex(data)
    statuses = index.statuses()
    selected = None if graphs is None else {N(graph) for graph in graphs}
    rows = []
    for target, status in statuses.items():
        if status not in ("awaitingReview", "agentAccepted"):
            continue
        statement = index.statement(target)
        if status == "agentAccepted" and _agent_acceptable(index, target, statement):
            continue
        status_graphs = index.graphs(target, index.terms.review_status)
        criticality = _effective_criticality(index, target, statement)
        confidence = index.ordinal(target, index.terms.confidence, provenance.CONFIDENCE_LEVELS)
        agents = index.iris(target, index.ns["prov"] + "wasAttributedTo")
        activities = index.iris(target, index.ns["prov"] + "wasGeneratedBy")
        dates = index.dates(target, index.ns["dcterms"] + "created")
        for activity in activities:
            dates.update(index.dates(ox.NamedNode(activity), index.ns["dcterms"] + "date"))
        evidence = index.evidence(target)
        if not evidence:
            raise ValueError(f"pending target {target.value}: evidence is required")
        if selected is not None and not selected & status_graphs:
            continue
        rows.append(ReviewItem(
            target=target.value, status=status, criticality=criticality, confidence=confidence,
            statement=(str(statement) + " .") if statement is not None else "",
            graph=" | ".join(sorted(_review_graph_name(graph) for graph in status_graphs)),
            agent=" | ".join(sorted(agents)), activity=" | ".join(sorted(activities)),
            date=" | ".join(sorted(dates)), evidence=" | ".join(sorted(evidence)),
            suggested_decision="", downstream_joins=index.downstream(target, statement),
        ))
    return sorted(rows, key=_review_order)


def write_review_queue(items: Sequence[ReviewItem], path: Path) -> Path:
    """CSV with :data:`REVIEW_QUEUE_COLUMNS` via ``io.det.write_csv``."""
    seen = set()
    for item in items:
        if not isinstance(item, ReviewItem) or not (
                item.status == "awaitingReview"
                or (item.status == "agentAccepted" and (item.criticality, item.confidence) != ("non-critical", "high"))):
            raise ValueError("review queue contains a non-pending record")
        if item.target in seen:
            raise ValueError(f"duplicate review target {item.target!r}")
        seen.add(item.target)
        N(item.target)
        if (item.confidence not in provenance.CONFIDENCE_LEVELS
                or item.criticality not in provenance.CRITICALITY_LEVELS
                or not isinstance(item.downstream_joins, int) or isinstance(item.downstream_joins, bool)
                or item.downstream_joins < 0):
            raise ValueError(f"invalid review queue fields for {item.target!r}")
        if item.suggested_decision:
            raise ValueError("this queue does not generate or approve review decisions")
        if not all(isinstance(getattr(item, field), str) and getattr(item, field).strip()
                   for field in ("target", "graph", "agent", "activity", "evidence")):
            raise ValueError(f"review queue {item.target!r}: required recorded fields are missing")
    return det.write_csv(path, REVIEW_QUEUE_COLUMNS,
                         ([getattr(item, field) for field in REVIEW_QUEUE_COLUMNS]
                          for item in sorted(items, key=_review_order)))


# --------------------------------------------------------------------------
# Assertion keys (E6)
# --------------------------------------------------------------------------

def assertion_key(subject: object, predicate: object, obj: object, mapping_set: str) -> str:
    """Content key of a statement: SHA-256 hex of the scheme, the three terms and the mapping set.

    Terms are RDF terms, absolute IRIs, CURIEs or N-Triples text (``'"x"@en'``).
    The subject and predicate must be IRIs and no term may contain a blank
    node: blank-node labels are re-scoped when builds are combined, so such a
    statement has no stable key. ``mapping_set`` is :func:`mapping_set_of` the
    reifier (an absolute IRI ending in ``/`` or ``:``).
    """
    s, p, o = (_term(value, what) for value, what in ((subject, "subject"), (predicate, "predicate"),
                                                       (obj, "object")))
    if not isinstance(s, ox.NamedNode) or not isinstance(p, ox.NamedNode):
        raise LedgerError("assertion keys need an IRI subject and predicate")
    if _has_blank(o):
        raise LedgerError("a statement with a blank node has no stable assertion key")
    payload = "\n".join((KEY_SCHEME, "statement", det.term_key(s), det.term_key(p), det.term_key(o),
                         _mapping_set(mapping_set)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def node_key(target: object, content: str) -> str:
    """Content key of a node target (one ``mark_derived`` marked as a whole).

    SHA-256 hex of the scheme, the node's IRI and ``content``, the
    :func:`node_content` digest of what the node says. A rebuild that keeps
    the IRI but changes the content changes the key, so an earlier decision
    is reported missing instead of approving content nobody reviewed.
    """
    if not isinstance(content, str) or not _HEX64.fullmatch(content):
        raise LedgerError(f"node content must be a SHA-256 hex digest, got {content!r}")
    payload = "\n".join((KEY_SCHEME, "node", _absolute_iri(target, "target"), content))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def node_content(data: "ox.Store | Iterable[ox.Quad]", target: object) -> str | None:
    """SHA-256 hex of a node target's own content in ``data``; ``None`` when it has no stable form.

    The content is every triple with the node as subject, in any graph, as
    sorted canonical N-Triples lines, leaving out: its D6 record and the
    curation marks a decision writes (:func:`_record_predicates`); triples
    that a review target or a review amendment reifies, which their own
    decisions govern (a selection set's entries, say); and the canonical
    year (``smn:broodYear`` / ``smn:returnYear``) that a year-basis decision
    derives. Graph names do not count, so a duplicate copy of a graph keeps
    the digest. A blank node in the content has no stable label across
    combined builds, so such a node has no key and cannot be decided.
    """
    node = N(_absolute_iri(target, "target"))
    index = _ReviewIndex(_unique_quads(data))
    return _node_content(index, node, index.governed())


def mapping_set_of(target: object) -> str:
    """The namespace a reifier was minted in: its IRI up to and including the last ``/``.

    ``.../xwalk/sasap-psc-fraser/7`` gives ``.../xwalk/sasap-psc-fraser/``. A
    ``urn:`` IRI uses its last ``:``. An IRI with no path segment is refused.
    """
    value = _absolute_iri(target, "reifier")
    scheme, _, rest = value.partition(":")
    if rest.startswith("//"):
        start = rest.find("/", 2)
        cut = value.rfind("/")
        if start < 0 or cut < len(scheme) + 1 + start:
            raise LedgerError(f"reifier {value!r} has no path, so it has no mapping set")
        return value[:cut + 1]
    cut = value.rfind(":")
    if cut <= len(scheme):
        raise LedgerError(f"reifier {value!r} has no namespace, so it has no mapping set")
    return value[:cut + 1]


def review_keys(data: "ox.Store | Iterable[ox.Quad]") -> dict[str, str | None]:
    """``{target IRI: assertion key}`` for every review target (``None`` when it has no stable key)."""
    return {t.node.value: t.key for t in _targets(_ReviewIndex(_unique_quads(data))).values()}


# --------------------------------------------------------------------------
# The decision ledger (reviews/decisions.csv)
# --------------------------------------------------------------------------

def decision_id(decision: Decision) -> str:
    """Short stable id of one ledger row: 16 hex digits of SHA-256 over its canonical values."""
    values = _row_values(_check_decision(decision))
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()[:16]


def load_decisions(path: Path = DECISIONS_PATH) -> list[Decision]:
    """Every row of the ledger, in file order, validated; ``[]`` when the file does not exist.

    Refuses an unknown header, a non-canonical value or byte form (write rows
    with :func:`append_decision` / :func:`record_decision`), an unknown decision
    token, an invalid date or ORCID, a key that disagrees with its content, an
    amendment without an amended object, and a second row for a key that does
    not name the row it supersedes.
    """
    path = Path(path)
    if not path.exists():
        return []
    if not path.is_file():
        raise LedgerError("the decision ledger must be a regular file")
    decisions = _parse_ledger(path.read_bytes())
    effective_decisions(decisions)
    return decisions


def effective_decisions(decisions: Sequence[Decision]) -> dict[str, Decision]:
    """``{key: decision}`` after supersession, sorted by key; validates the supersession chains."""
    current: dict[str, Decision] = {}
    seen = set()
    for raw in decisions:
        d = _check_decision(raw)
        did = decision_id(d)
        if did in seen:
            raise LedgerError(f"duplicate decision row {did}")
        seen.add(did)
        prior = current.get(d.key)
        if prior is None:
            if d.supersedes:
                raise LedgerError(f"decision {did} supersedes {d.supersedes}, which is not an earlier "
                                  "decision on the same key")
        else:
            if d.supersedes != decision_id(prior):
                raise LedgerError(f"key {d.key} is already decided by {decision_id(prior)}; a later row "
                                  "must name it in 'supersedes'")
            if _dated_before(d.date, prior.date):
                raise LedgerError(f"decision {did} is dated before the decision it supersedes")
        current[d.key] = d
    return dict(sorted(current.items()))


def append_decision(decision: Decision, path: Path = DECISIONS_PATH) -> Decision:
    """Validate ``decision`` against the ledger and append it; returns the stored (keyed) row.

    Creates the file with its header when missing. The existing bytes are
    kept exactly (the new file starts with them), so a release snapshot stays
    a prefix of every later ledger. Single writer: do not append concurrently.
    """
    path = Path(path)
    header = det.csv_bytes(DECISION_COLUMNS, [])
    if path.exists() and not path.is_file():
        raise LedgerError("the decision ledger must be a regular file")
    before = path.read_bytes() if path.exists() else header
    existing = _parse_ledger(before)
    d = _check_decision(decision)
    effective_decisions([*existing, d])
    row = det.csv_bytes(DECISION_COLUMNS, [_row_values(d)])[len(header):]
    if path.exists() and path.read_bytes() != before:
        raise LedgerError("the decision ledger changed while appending; retry")
    det.write_bytes(path, before + row, gzip=False)
    return d


def record_decision(data: "ox.Store | Iterable[ox.Quad]", target: str, decision: str, *,
                    reviewer: str, date: str, reviewer_orcid: str | None = None,
                    amended_object: str | None = None, note: str | None = None,
                    review_minutes: float | None = None, supersedes: str | None = None,
                    path: Path = DECISIONS_PATH) -> Decision:
    """Record a person's decision on ``target`` (a review target in ``data``); returns the row.

    The key, statement and mapping set are taken from ``data``, so the row
    names exactly the assertion the person reviewed. ``amended_object`` is an
    IRI, CURIE or N-Triples literal. Changing an earlier decision needs
    ``supersedes=decision_id(earlier)``. This is a tool for people; agents and
    pipelines never call it.
    """
    targets = _targets(_ReviewIndex(_unique_quads(data)))
    t = targets.get(N(target))
    if t is None:
        raise LedgerError(f"{target!r} is not a review target in the supplied data")
    _refuse_legacy([t])
    if t.key is None:
        what = "reifies a statement with" if t.statement is not None else "has content with"
        raise LedgerError(f"{target!r} {what} a blank node; it has no stable key")
    fields = {"node_content": t.content}
    if t.statement is not None:
        fields = {"subject": det.term_key(t.statement.subject), "predicate": det.term_key(t.statement.predicate),
                  "object": det.term_key(t.statement.object), "mapping_set": mapping_set_of(t.node)}
    amended = det.term_key(_term(amended_object, "amended_object")) if amended_object else None
    row = Decision(target=t.node.value, decision=decision, reviewer=reviewer, date=date,
                   reviewer_orcid=reviewer_orcid or None, amended_object=amended, note=note or None,
                   key=t.key, review_minutes=review_minutes, supersedes=supersedes, **fields)
    return append_decision(row, path)


def ledger_state(path: Path = DECISIONS_PATH) -> dict:
    """What a dataset build records about the ledger: presence, sha256 and row counts.

    The dataset build validates the ledger but does not apply it: decisions
    are applied when views are materialised (:func:`apply_ledger`).
    """
    path = Path(path)
    if not path.exists():
        return {"status": "none_present"}
    if not path.is_file():
        raise LedgerError("the decision ledger must be a regular file")
    data = path.read_bytes()
    decisions = _parse_ledger(data)
    effective = effective_decisions(decisions)
    if not decisions:
        return {"status": "no_decision_rows", "sha256": det.sha256_bytes(data)}
    return {"status": "recorded_not_applied", "sha256": det.sha256_bytes(data), "rows": len(decisions),
            "effective": len(effective), "applied_by": "salmongraph.review.apply_ledger"}


def snapshot_decisions(dest: Path, path: Path = DECISIONS_PATH) -> dict:
    """Copy the ledger byte for byte to ``dest`` (a release's ``decisions.csv``); returns its record.

    A missing ledger is snapshotted as its header alone, an explicit "no
    decisions". The record (portable paths, bytes, sha256, row and effective
    counts, key scheme) belongs in the release manifest.
    """
    path, dest = Path(path), Path(dest)
    present = path.exists()
    data = path.read_bytes() if present else det.csv_bytes(DECISION_COLUMNS, [])
    decisions = _parse_ledger(data)
    effective = effective_decisions(decisions)
    det.write_bytes(dest, data, gzip=False)
    return {"path": det.portable_path(dest), "source": det.portable_path(path), "present": present,
            "bytes": len(data), "sha256": det.sha256_bytes(data), "rows": len(decisions),
            "effective": len(effective), "key_scheme": KEY_SCHEME}


def verify_decisions_snapshot(snapshot: Path, path: Path = DECISIONS_PATH) -> list[str]:
    """Problems (``[]`` = none): both ledgers must be valid, and ``path`` must extend ``snapshot``."""
    problems = []
    try:
        old = Path(snapshot).read_bytes()
        effective_decisions(_parse_ledger(old))
    except (OSError, ValueError) as exc:
        return [f"snapshot is unreadable or invalid: {exc}"]
    path = Path(path)
    current = path.read_bytes() if path.exists() else det.csv_bytes(DECISION_COLUMNS, [])
    try:
        effective_decisions(_parse_ledger(current))
    except ValueError as exc:
        problems.append(f"current ledger is invalid: {exc}")
    if not current.startswith(old):
        problems.append("the ledger was edited or truncated after the snapshot; it is append-only")
    return problems


# --------------------------------------------------------------------------
# Applying decisions and building views
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LedgerApplication:
    """Result of :func:`apply_ledger`."""

    quads: tuple[ox.Quad, ...]                         # the decided store, sorted
    applied: tuple[tuple[str, str, tuple[str, ...]], ...]   # (key, decision, targets), by key
    missing: tuple[Decision, ...]                      # effective decisions that matched nothing
    retargeted: tuple[tuple[str, str, tuple[str, ...]], ...]  # (key, recorded target, actual targets)

    def missing_targets(self) -> list[str]:
        """Recorded target IRIs of the decisions that matched nothing, sorted."""
        return sorted(d.target for d in self.missing)

    def report(self) -> dict:
        """JSON-ready summary for a manifest or report."""
        return {"applied": [{"key": k, "decision": d, "targets": list(t)} for k, d, t in self.applied],
                "missing": [{"key": d.key, "decision": d.decision, "target": d.target} for d in self.missing],
                "retargeted": [{"key": k, "recorded_target": r, "targets": list(t)} for k, r, t in self.retargeted]}


@dataclass(frozen=True)
class MaterialisedViews:
    """Result of :func:`materialise_views`: both views of one decided store."""

    full: tuple[ox.Quad, ...]
    reviewed: tuple[ox.Quad, ...]
    application: LedgerApplication


def apply_ledger(data: "ox.Store | Iterable[ox.Quad]", decisions: Sequence[Decision], *,
                 review_graph: str, vocab: "VocabIndex | None" = None) -> LedgerApplication:
    """The decided store: ``data`` with every effective decision applied (module docstring).

    ``review_graph`` (normally ``iri.corpus_graph("review", cv)``) receives the
    decision records. With ``vocab``, amended objects and every other new IRI
    are checked against the pinned vocabularies. Raises :class:`LedgerError`
    on unconverted legacy statements, a store decided with another ledger,
    curation marks that a decision would duplicate, an amendment of a node
    target, or any pending, rejected or amended-away triple left asserted.
    """
    quads = _unique_quads(data)
    present = set(quads)
    review = N(review_graph)
    effective = effective_decisions(decisions)
    index = _ReviewIndex(quads)
    targets = _targets(index)
    _refuse_legacy(targets.values())
    by_key = defaultdict(list)
    for t in targets.values():
        if t.key is not None:
            by_key[t.key].append(t)
    for t in targets.values():
        if t.status in DECISION_TOKENS and t.key not in effective:
            raise LedgerError(f"{t.node.value} carries a human decision ({t.status}) that the ledger does "
                              "not record; apply the ledger to the agent-built store")
    remove, add, final = set(), set(), {}
    applied, missing, retargeted = [], [], []
    for key, d in effective.items():
        matched = sorted(by_key.get(key, ()), key=lambda t: t.node.value)
        if not matched:
            missing.append(d)
            continue
        names = tuple(t.node.value for t in matched)
        if names != (d.target,):
            retargeted.append((key, d.target, names))
        for t in matched:
            final[t.node] = d.decision
            gone, new = _decision_effects(index, t, d, review)
            if t.status in DECISION_TOKENS:
                marks = {(p, o) for p in _CURATION for o in index.objects(t.node, p)}
                expected = {(q.predicate.value, q.object) for q in new
                            if q.subject == t.node and q.predicate.value in _CURATION}
                if t.status != d.decision or not new <= present or marks != expected:
                    raise LedgerError(f"{t.node.value} was decided with a different ledger; apply the "
                                      "ledger to the agent-built store")
                continue
            if any(index.objects(t.node, predicate) for predicate in _CURATION):
                raise LedgerError(f"{t.node.value} already carries curation marks; refusing to add a "
                                  "second decision record")
            remove |= gone
            add |= new
        applied.append((key, d.decision, names))
    about_terms = sorted({q.subject.value for q in add - present if _vocabulary_term(q.subject)})
    if about_terms:
        raise LedgerError(f"a decision would assert a triple about the vocabulary term {about_terms[0]}; "
                          "the corpus never adds statements whose subject is an smn, gcdfo or PSC IRI")
    result = det.sorted_quads((present - (remove - add)) | add)
    if vocab is not None:
        bad = vocab.check({term.value for q in add for term in _named(q)})
        if bad:
            from .vocab import UndeclaredIRIError
            raise UndeclaredIRIError(bad)
    _check_statement_only(result, targets, final)
    return LedgerApplication(tuple(result), tuple(applied), tuple(missing), tuple(retargeted))


def apply_decisions(builder: "GraphBuilder", decisions: Sequence[Decision], *, graph: str) -> list[str]:
    """Apply decisions to the marks in ``builder`` (as :func:`apply_ledger`); returns missing targets.

    ``graph`` is the review graph. The decision replaces the agent status, so
    this is the one caller of ``GraphBuilder.discard``. Returned: the recorded
    target IRIs of decisions whose key matched nothing, sorted.
    """
    result = apply_ledger(builder.quads, decisions, review_graph=graph, vocab=builder.vocab)
    new, old = set(result.quads), set(builder.quads)
    builder.discard(old - new)
    builder.extend(det.sorted_quads(new - old))
    for target, token in _ReviewIndex(result.quads).statuses().items():
        if target.value in builder.marked:
            builder.marked[target.value] = token
    return result.missing_targets()


def view_quads(data: "ox.Store | Iterable[ox.Quad]", view: str = "reviewed") -> list[ox.Quad]:
    """Sorted quads of ``view`` (``"reviewed"`` or ``"full"``); see the module docstring."""
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}, got {view!r}")
    quads = _unique_quads(data)
    if view == "full":
        return det.sorted_quads(quads)
    index = _ReviewIndex(quads)
    targets = _targets(index)
    _refuse_legacy(targets.values())
    _refuse_unrecorded_decisions(index, quads, targets.values())
    supported, unsupported = set(), defaultdict(list)
    for t in targets.values():
        if t.statement is None:
            continue
        spo = (t.statement.subject, t.statement.predicate, t.statement.object)
        if _supports(index, t, t.status):
            supported.add(spo)
        else:
            unsupported[spo].append(t.node.value)
    for q in quads:
        if q.predicate.value == RDF_REIFIES and q.subject not in targets and isinstance(q.object, ox.Triple):
            supported.add((q.object.subject, q.object.predicate, q.object.object))
    clash = sorted(str(spo) for spo in set(unsupported) & supported)
    if clash:
        raise LedgerError("a triple is both supported by a reviewed or source reifier and proposed by a "
                          f"pending, rejected or amended assertion; decide both: {clash[0]}")
    hidden = {t.node for t in targets.values()
              if t.statement is None and (t.status in ("awaitingReview", "rejected")
                                          or (t.status == "agentAccepted"
                                              and not _agent_acceptable(index, t.node, None)))}
    record = _record_predicates()
    kept, dropped = [], []
    for q in quads:
        if ((q.subject, q.predicate, q.object) in unsupported
                or (q.subject in hidden and q.predicate.value not in record)):
            dropped.append(q)
        else:
            kept.append(q)
    return det.sorted_quads(_drop_orphans(kept, dropped))


def view_store(store: "ox.Store | Iterable[ox.Quad]", view: str = "reviewed") -> "ox.Store":
    """A new in-memory store holding only what ``view`` shows (``"reviewed"`` or ``"full"``)."""
    result = ox.Store()
    result.extend(view_quads(store, view))
    return result


def materialise_views(data: "ox.Store | Iterable[ox.Quad]", decisions: Sequence[Decision], *,
                      review_graph: str, vocab: "VocabIndex | None" = None) -> MaterialisedViews:
    """Apply ``decisions`` (:func:`apply_ledger`) and return the full and reviewed views."""
    application = apply_ledger(data, decisions, review_graph=review_graph, vocab=vocab)
    return MaterialisedViews(full=application.quads,
                             reviewed=tuple(view_quads(application.quads, "reviewed")),
                             application=application)


# --------------------------------------------------------------------------
# Legacy RDF 1.1 statements
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LegacyConversion:
    """Result of :func:`convert_legacy_statements`."""

    quads: tuple[ox.Quad, ...]      # sorted
    converted: tuple[str, ...]      # IRIs of the converted statements, sorted


def convert_legacy_statements(data: "ox.Store | Iterable[ox.Quad]", *,
                              legacy_profile: str | None = None) -> LegacyConversion:
    """Rewrite RDF 1.1 ``rdf:Statement`` review targets as RDF 1.2 reifiers, losing nothing.

    A legacy target is a node with ``rdf:subject``/``rdf:predicate``/``rdf:object``
    (or typed ``rdf:Statement``) and a review status. Each keeps its IRI and
    every other property; ``rdf:reifies <<( s p o )>>`` replaces the four RDF
    1.1 quads in the graphs holding its status. ``dcterms:source`` IRIs are
    also written as ``prov:wasDerivedFrom``, and each ``rdfs:comment`` (the
    source pairing context) as a ``prov:Entity`` evidence value, so the review
    queue shows them. D6 marks in ``legacy_profile`` (default: the current
    profile namespace, which is where the legacy pipeline writes them under
    the same base) are mapped onto the current profile terms. A
    ``rdf:Statement`` without a review status is source data and is left
    alone. Refuses ambiguous or blank-node statements, mixed encodings,
    another review-profile namespace, missing evidence or ordinals, and a
    pending statement whose triple is asserted anywhere. Converting twice is
    a no-op.
    """
    cfg = config.current()
    terms = provenance.terms()
    old = legacy_profile if legacy_profile is not None else cfg.profile_base
    if not isinstance(old, str) or not re.match(r"^(https?://|urn:)\S+[/#:]$", old):
        raise LedgerError("legacy_profile must be an absolute namespace IRI ending in '/', '#' or ':'")
    mapping = {}
    for current in (terms.confidence, terms.criticality, terms.review_status, *terms.values.values()):
        if not current.startswith(cfg.profile_base):
            raise LedgerError("profile terms are not under the configured profile base")
        mapping[old + current[len(cfg.profile_base):]] = current
    marks = {terms.confidence, terms.criticality, terms.review_status}
    statuses = {terms.review_status, old + "reviewStatus"}
    quads = _unique_quads(data)
    for q in quads:
        if q.predicate.value.endswith(_STATUS_SUFFIXES) and q.predicate.value not in statuses:
            raise LedgerError(f"unsupported review profile namespace: {q.predicate.value}")
    by_subject = defaultdict(list)
    for q in quads:
        by_subject[q.subject].append(q)
    parts = {_RDF + part for part in ("subject", "predicate", "object")}
    statement_type = ox.NamedNode(_RDF + "Statement")

    def encoding(q):
        return q.predicate.value in parts or (q.predicate.value == _RDF + "type" and q.object == statement_type)

    remove, add, converted = set(), set(), []
    for subject in sorted(by_subject, key=str):
        own = by_subject[subject]
        if not any(encoding(q) for q in own) or not any(q.predicate.value in statuses for q in own):
            continue
        if not isinstance(subject, ox.NamedNode):
            raise LedgerError("legacy review statements must have stable IRIs")
        if _vocabulary_term(subject):
            raise LedgerError(f"{subject.value}: converting would add statements about an smn, gcdfo or PSC "
                              "IRI; the corpus never writes triples with such a subject")
        values = {part: {q.object for q in own if q.predicate.value == part} for part in sorted(parts)}
        if any(len(v) != 1 for v in values.values()):
            raise LedgerError(f"{subject.value}: incomplete or ambiguous RDF 1.1 statement")
        s, p, o = (next(iter(values[_RDF + part])) for part in ("subject", "predicate", "object"))
        if not isinstance(s, ox.NamedNode) or not isinstance(p, ox.NamedNode) or _has_blank(o):
            raise LedgerError(f"{subject.value}: legacy statements need IRI subjects and no blank nodes")
        if any(q.predicate.value == RDF_REIFIES for q in own):
            raise LedgerError(f"{subject.value}: mixed RDF 1.1 and RDF 1.2 encodings")
        graphs = sorted({q.graph_name for q in own if q.predicate.value in statuses}, key=str)
        for q in own:
            if encoding(q):
                remove.add(q)
                continue
            predicate = ox.NamedNode(mapping.get(q.predicate.value, q.predicate.value))
            obj = q.object
            if predicate.value in marks and isinstance(obj, ox.NamedNode) and obj.value in mapping:
                obj = ox.NamedNode(mapping[obj.value])
            if (predicate, obj) != (q.predicate, q.object):
                remove.add(q)
                add.add(ox.Quad(subject, predicate, obj, q.graph_name))
            if q.predicate.value == _DCT + "source" and isinstance(q.object, ox.NamedNode):
                add.add(ox.Quad(subject, ox.NamedNode(_PROV + "wasDerivedFrom"), q.object, q.graph_name))
            if (q.predicate.value == _RDFS + "comment" and isinstance(q.object, ox.Literal)
                    and q.object.value.strip()):
                entity = GraphBuilder.bnode(subject.value, "evidence", q.object.value)
                add.update((ox.Quad(subject, ox.NamedNode(_PROV + "wasDerivedFrom"), entity, q.graph_name),
                            ox.Quad(entity, ox.NamedNode(_RDF + "type"), ox.NamedNode(_PROV + "Entity"), q.graph_name),
                            ox.Quad(entity, ox.NamedNode(_PROV + "value"), q.object, q.graph_name)))
        for graph in graphs:
            add.add(ox.Quad(subject, ox.NamedNode(RDF_REIFIES), ox.Triple(s, p, o), graph))
        converted.append(subject.value)
    result = det.sorted_quads([q for q in quads if q not in remove] + sorted(add, key=det.quad_key))
    index = _ReviewIndex(result)
    found = index.statuses()
    live = {(q.subject, q.predicate, q.object) for q in result}
    for value in converted:
        node = ox.NamedNode(value)
        index.ordinal(node, terms.criticality, provenance.CRITICALITY_LEVELS)
        index.ordinal(node, terms.confidence, provenance.CONFIDENCE_LEVELS)
        if not index.evidence(node):
            raise LedgerError(f"{value}: legacy statement has no source evidence")
        triple = index.statement(node)
        if found[node] not in provenance.REVIEWED_STATUSES and (triple.subject, triple.predicate, triple.object) in live:
            raise LedgerError(f"{value}: pending legacy statement is also asserted (statement-only rule)")
    return LegacyConversion(tuple(result), tuple(converted))


def status_counts(data: "ox.Store | Iterable[ox.Quad]") -> dict[str, int]:
    """Count of targets per review status token (for reports and the release manifest)."""
    counts = Counter(_ReviewIndex(data).statuses().values())
    return dict(sorted(counts.items()))


def _review_order(item: ReviewItem):
    return (item.criticality != "critical", -item.downstream_joins, item.target)


def _review_graph_name(graph) -> str:
    if not isinstance(graph, ox.NamedNode):
        raise ValueError("review marks must be in a named graph")
    return graph.value


class _ReviewIndex:
    """Read-only, duplicate-insensitive access to original quads and proof paths."""

    def __init__(self, data):
        self.ns = config.current().ns
        self.terms = provenance.terms()
        self.by_sp, self.by_sp_graph, self.incoming = defaultdict(set), defaultdict(set), defaultdict(set)
        self.predicates, self.reified = defaultdict(set), defaultdict(set)
        self.subjects = set()
        self.derived = self.ns["prov"] + "wasDerivedFrom"
        self.rdf_type = self.ns["rdf"] + "type"
        for quad in data:
            if not isinstance(quad, ox.Quad):
                raise ValueError("review input must contain RDF quads")
            if (quad.predicate.value.endswith(_STATUS_SUFFIXES)
                    and quad.predicate.value != self.terms.review_status):
                # Another profile's review marks (the legacy NuSEDS graph keeps
                # its original namespace when the base moves) would otherwise
                # be invisible here: no target, no queue row, no protection.
                raise LedgerError(f"review status in another profile namespace: {quad.predicate.value}; "
                                  "convert it with review.convert_legacy_statements(data, legacy_profile=...) "
                                  "first")
            self.by_sp[quad.subject, quad.predicate.value].add(quad.object)
            self.by_sp_graph[quad.subject, quad.predicate.value].add(quad.graph_name)
            self.predicates[quad.subject].add(quad.predicate.value)
            self.subjects.add(quad.subject)
            if quad.predicate.value == RDF_REIFIES and isinstance(quad.object, ox.Triple):
                self.reified[quad.subject].add(quad.object)
            if quad.predicate.value == self.derived:
                if not isinstance(quad.object, (ox.NamedNode, ox.BlankNode)):
                    raise ValueError("prov:wasDerivedFrom must refer to an entity, not a literal/triple")
                self.incoming[quad.object].add(quad.subject)
        self._statements = {}
        self._governed = None
        self._floors = None

    def governed(self):
        """:func:`_governed_statements` of this index (cached; the index is read-only)."""
        if self._governed is None:
            self._governed = _governed_statements(self, self.statuses())
        return self._governed

    def floor(self, predicate) -> str | None:
        """The critical aspect of ``predicate`` here: the floor table closed over this store's property axioms.

        ``provenance.CRITICAL_PREDICATES``, plus every predicate this store
        asserts to be an ``rdfs:subPropertyOf`` (transitively), an
        ``owl:equivalentProperty`` or an ``owl:inverseOf`` of a floor
        predicate: a statement with such a predicate entails the floor one, so
        it is no less critical (the legacy NuSEDS graph declares
        ``def:conservationUnit rdfs:subPropertyOf gcdfo:hasConservationUnit``).
        Only asserted axioms count, so a pending one stays without effect.
        Where several floor predicates are reachable, the first aspect by name.
        """
        if self._floors is None:
            self._floors = _closed_floor(self)
        return self._floors.get(predicate.value if isinstance(predicate, ox.NamedNode) else predicate)

    def objects(self, subject, predicate):
        return self.by_sp.get((subject, predicate), set())

    def graphs(self, subject, predicate):
        return self.by_sp_graph.get((subject, predicate), set())

    def statuses(self):
        output = {}
        for subject in sorted(self.subjects, key=str):
            values = self.objects(subject, self.terms.review_status)
            if not values:
                continue
            if not isinstance(subject, ox.NamedNode):
                raise ValueError("review targets must have stable IRIs")
            if len(values) != 1:
                raise ValueError(f"target {subject.value}: conflicting/multiple review statuses")
            value = next(iter(values))
            token = provenance.token_of(value.value) if isinstance(value, ox.NamedNode) else None
            if token not in provenance.REVIEW_STATUSES:
                raise ValueError(f"target {subject.value}: unknown review status")
            for graph in self.graphs(subject, self.terms.review_status):
                _review_graph_name(graph)
            output[subject] = token
        return output

    def ordinal(self, target, predicate, allowed):
        values = self.objects(target, predicate)
        if len(values) != 1:
            raise ValueError(f"review target {target.value}: missing or conflicting {predicate}")
        value = next(iter(values))
        token = provenance.token_of(value.value) if isinstance(value, ox.NamedNode) else None
        if token not in allowed:
            raise ValueError(f"review target {target.value}: unknown ordinal {predicate}")
        return token

    def iris(self, target, predicate):
        values = self.objects(target, predicate)
        if not values or not all(isinstance(value, ox.NamedNode) for value in values):
            raise ValueError(f"pending target {target.value}: {predicate} requires actual IRI values")
        return {value.value for value in values}

    def dates(self, target, predicate):
        output = set()
        for value in self.objects(target, predicate):
            if not isinstance(value, ox.Literal) or not value.value.strip():
                raise ValueError(f"review target/activity {target}: invalid recorded date")
            try:
                if "T" in value.value:
                    _dt.datetime.fromisoformat(value.value.replace("Z", "+00:00"))
                else:
                    _dt.date.fromisoformat(value.value)
            except ValueError as exc:
                raise ValueError(f"review target/activity {target}: invalid recorded date") from exc
            output.add(value.value)
        return output

    def statement(self, target):
        if target in self._statements:
            return self._statements[target]
        modern = self.objects(target, self.ns["rdf"] + "reifies")
        legacy = [self.objects(target, self.ns["rdf"] + part) for part in ("subject", "predicate", "object")]
        if (not modern and not any(legacy)
                and ox.NamedNode(self.ns["rdf"] + "Statement") in self.objects(target, self.rdf_type)):
            raise ValueError(f"review target {target}: RDF statement has no reified SPO")
        statement = None
        if modern:
            if len(modern) != 1 or not isinstance(next(iter(modern)), ox.Triple):
                raise ValueError(f"review target {target}: malformed or ambiguous RDF 1.2 reifier")
            statement = next(iter(modern))
        if any(legacy):
            if any(len(values) != 1 for values in legacy):
                raise ValueError(f"review target {target}: incomplete or ambiguous RDF 1.1 reifier")
            s, p, o = (next(iter(values)) for values in legacy)
            if not isinstance(s, (ox.NamedNode, ox.BlankNode)) or not isinstance(p, ox.NamedNode):
                raise ValueError(f"review target {target}: invalid RDF 1.1 statement terms")
            old_statement = ox.Triple(s, p, o)
            if statement is not None and old_statement != statement:
                raise ValueError(f"review target {target}: conflicting reification encodings")
            statement = old_statement
        self._statements[target] = statement
        return statement

    def evidence(self, target):
        output, seen = set(), {target}
        content, parents = set(), defaultdict(set)
        queue = deque(self.objects(target, self.derived))
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            if isinstance(node, ox.NamedNode):
                output.add(node.value)
                content.add(node)
            values = self.objects(node, self.ns["prov"] + "value")
            for value in values:
                if not isinstance(value, ox.Literal) or not value.value.strip():
                    raise ValueError(f"review target {target}: malformed evidence value")
                output.add(value.value)
                content.add(node)
            dependencies = self.objects(node, self.derived)
            if isinstance(node, ox.BlankNode) and not values and not dependencies:
                raise ValueError(f"review target {target}: evidence blank node has no content")
            for dependency in dependencies:
                parents[dependency].add(node)
            queue.extend(dependencies)
        # A blank-node cycle is not evidence by itself. Propagate actual IRI
        # or literal content through the proof graph without recursive calls.
        queue = deque(content)
        while queue:
            for parent in parents.get(queue.popleft(), ()):
                if parent not in content:
                    content.add(parent)
                    queue.append(parent)
        if any(isinstance(node, ox.BlankNode) and node not in content for node in seen):
            raise ValueError(f"review target {target}: evidence cycle has no recorded content")
        return output

    def downstream(self, target, statement):
        anchors = {target}
        if statement is not None and ox.NamedNode(self.ns["csvw"] + "Column") in self.objects(statement.subject, self.rdf_type):
            anchors.add(statement.subject)
        seen, endpoints, queue = set(), set(), deque(anchors)
        observation_types = {ox.NamedNode(self.ns[namespace] + "Observation") for namespace in ("qb", "sosa")}
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            if node != target and (self.objects(node, self.rdf_type) & observation_types
                                   or self.statement(node) is not None):
                endpoints.add(node)
            queue.extend(self.incoming.get(node, ()))
        return len(endpoints)


# --------------------------------------------------------------------------
# Internals: terms, ledger rows, decision effects, the statement-only check
# --------------------------------------------------------------------------

_NS = config.STATIC_NS
_RDF, _RDFS, _DCT, _PROV = _NS["rdf"], _NS["rdfs"], _NS["dcterms"], _NS["prov"]
_PAV, _SKOS, _SSSOM, _SEMAPV = _NS["pav"], _NS["skos"], _NS["sssom"], _NS["semapv"]
_QB, _SOSA, _CSVW, _XSD = _NS["qb"], _NS["sosa"], _NS["csvw"], _NS["xsd"]
_OWL = _NS["owl"]
#: How a review-status predicate in any profile namespace ends; ``legacy_profile`` may end in
#: ``/``, ``#`` or ``:``, so a ``urn:`` profile is recognised (and refused unconverted) too.
_STATUS_SUFFIXES = ("/reviewStatus", "#reviewStatus", ":reviewStatus")
_YEAR_BASES = frozenset({config.SMN_NS + "broodYear", config.SMN_NS + "returnYear"})
#: What a decision writes on its target, in the review graph.
_CURATION = frozenset({_PAV + "curatedBy", _PAV + "curatedOn", _DCT + "date", _SKOS + "editorialNote",
                       _SSSOM + "reviewer_id"})
_ORCID = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})")
_HEX16 = re.compile(r"[0-9a-f]{16}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ABSOLUTE = re.compile(r"^(https?://|urn:)[^\s<>\"{}|\\^`]+$")
_KEY_COLUMNS = ("key", "subject", "predicate", "object", "mapping_set", "node_content")


@dataclass(frozen=True)
class _Target:
    node: ox.NamedNode
    status: str
    statement: ox.Triple | None
    key: str | None
    status_graphs: frozenset
    reifier_graphs: frozenset
    legacy: bool
    content: str | None = None      # node_content of a node target; None for a statement


def _unique_quads(data) -> list[ox.Quad]:
    out = {}
    for q in data:
        if not isinstance(q, ox.Quad):
            raise ValueError("review input must contain RDF quads")
        if isinstance(q.graph_name, ox.DefaultGraph):
            raise ValueError("review input must be in named graphs")
        out[q] = None
    return list(out)


def _governed_statements(index: _ReviewIndex, statuses: Mapping[ox.NamedNode, str]) -> set[tuple]:
    """SPOs whose assertion a decision on their own reifier governs: review targets and amendments.

    A node target's content leaves these out, so accepting (or amending) a
    statement about the node never changes the node's key.
    """
    governed = set()
    for node in statuses:
        statement = index.statement(node)
        if statement is not None:
            governed.add((statement.subject, statement.predicate, statement.object))
    amendments = mapping_set_of(iri.xwalk(AMENDMENT_MAPPING_SET, "0"))
    for reifier, triples in index.reified.items():
        if isinstance(reifier, ox.NamedNode) and reifier.value.startswith(amendments):
            governed.update((t.subject, t.predicate, t.object) for t in triples)
    return governed


def _node_content(index: _ReviewIndex, node: ox.NamedNode, governed: set,
                  skipped: frozenset[str] | None = None) -> str | None:
    """:func:`node_content` over an index; ``governed`` from :func:`_governed_statements`."""
    if skipped is None:
        skipped = _record_predicates() | _YEAR_BASES
    lines = set()
    for predicate in index.predicates.get(node, ()):
        if predicate in skipped:
            continue
        p = ox.NamedNode(predicate)
        for obj in index.objects(node, predicate):
            if (node, p, obj) in governed:
                continue
            if _has_blank(obj):
                return None
            lines.add(f"{det.term_key(node)} {det.term_key(p)} {det.term_key(obj)} .")
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def _targets(index: _ReviewIndex) -> dict[ox.NamedNode, _Target]:
    out = {}
    statuses = index.statuses()
    governed = index.governed()
    skipped = _record_predicates() | _YEAR_BASES
    for node, status in statuses.items():
        statement = index.statement(node)
        legacy = any(index.objects(node, _RDF + part) for part in ("subject", "predicate", "object"))
        content = None
        if statement is None:
            content = _node_content(index, node, governed, skipped)
            key = None if content is None else node_key(node, content)
        elif isinstance(statement.subject, ox.NamedNode) and not _has_blank(statement.object):
            key = assertion_key(statement.subject, statement.predicate, statement.object, mapping_set_of(node))
        else:
            key = None
        out[node] = _Target(node, status, statement, key,
                            frozenset(index.graphs(node, index.terms.review_status)),
                            frozenset(index.graphs(node, RDF_REIFIES)) if statement is not None else frozenset(),
                            legacy, content)
    return out


def _refuse_unrecorded_decisions(index: _ReviewIndex, quads: Sequence[ox.Quad], targets: Iterable[_Target]) -> None:
    """Fail when a target carries a human status without the record :func:`apply_ledger` writes.

    The record is ``pav:curatedBy`` on the target and a ``prov:Activity`` that
    ``prov:used`` it. A status set by hand, with no decision behind it, is no
    review proof, so the reviewed view refuses it rather than trusting it
    (``apply_ledger`` refuses it too, as a status the ledger lacks). This
    checks that a record is present, not who made it.
    """
    activity = ox.NamedNode(_PROV + "Activity")
    used = {q.object for q in quads
            if q.predicate.value == _PROV + "used" and activity in index.objects(q.subject, index.rdf_type)}
    bare = sorted((t.node.value, t.status) for t in targets
                  if t.status in DECISION_TOKENS and not (index.objects(t.node, _PAV + "curatedBy") and t.node in used))
    if bare:
        node, status = bare[0]
        raise LedgerError(f"{node} carries a human decision ({status}) without its decision record "
                          "(pav:curatedBy and a review activity that prov:used it); build reviewed views from "
                          "review.materialise_views, never from hand-set statuses")


def _refuse_legacy(targets: Iterable[_Target]) -> None:
    legacy = sorted(t.node.value for t in targets if t.legacy)
    if legacy:
        raise LedgerError(f"unconverted RDF 1.1 review statement {legacy[0]}; run "
                          "review.convert_legacy_statements first")


def _has_blank(term) -> bool:
    if isinstance(term, ox.BlankNode):
        return True
    if isinstance(term, ox.Triple):
        return any(_has_blank(t) for t in (term.subject, term.predicate, term.object))
    return False


def _named(q: ox.Quad):
    stack = [q.subject, q.predicate, q.object, q.graph_name]
    while stack:
        term = stack.pop()
        if isinstance(term, ox.NamedNode):
            yield term
        elif isinstance(term, ox.Triple):
            stack.extend((term.subject, term.predicate, term.object))
        elif isinstance(term, ox.Literal):
            yield term.datatype


def _vocabulary_term(term) -> bool:
    """Any IRI under the smn, gcdfo or PSC namespaces, with no sub-tree exemption.

    The corpus has its own root and mints nothing under ``https://w3id.org/smn/``,
    so ``smn/data/`` and ``smn/profile/corpus/`` (the D10 proposal) are smn's
    space like any other smn IRI. ``config.excluded_subtrees`` is not consulted:
    it tells the vocabulary guard what is not a declared term, which is no
    licence to write statements there.
    """
    return isinstance(term, ox.NamedNode) and any(term.value.startswith(ns)
                                                  for ns in config.VOCAB_NAMESPACES.values())


def _absolute_iri(value, what: str) -> str:
    if isinstance(value, ox.NamedNode):
        return value.value
    if isinstance(value, str) and _ABSOLUTE.match(value):
        return value
    raise LedgerError(f"{what} must be an absolute IRI, got {value!r}")


def _mapping_set(value) -> str:
    if not isinstance(value, str) or not _ABSOLUTE.match(value) or value[-1] not in "/:":
        raise LedgerError(f"mapping_set must be an absolute IRI ending in '/' or ':', got {value!r}")
    return value


def _term(value, what: str):
    """An RDF term from a term, an absolute IRI, a CURIE or N-Triples term text."""
    if isinstance(value, (ox.NamedNode, ox.BlankNode, ox.Literal, ox.Triple)):
        return value
    if not isinstance(value, str) or not value or value != value.strip():
        raise LedgerError(f"{what}: expected an RDF term, got {value!r}")
    if value.startswith(("<", '"', "_:")):
        try:
            parsed = list(ox.parse(f"<urn:salmongraph:s> <urn:salmongraph:p> {value} .",
                                   format=ox.RdfFormat.N_TRIPLES))
        except (SyntaxError, ValueError, OSError) as exc:
            raise LedgerError(f"{what}: not one N-Triples term: {value!r}") from exc
        if len(parsed) != 1:
            raise LedgerError(f"{what}: not one N-Triples term: {value!r}")
        return parsed[0].object
    expanded = expand(value)
    if not isinstance(expanded, str) or not _ABSOLUTE.match(expanded):
        raise LedgerError(f"{what}: not an absolute IRI, a known CURIE or an N-Triples term: {value!r}")
    return ox.NamedNode(expanded)


def _canonical(text, what: str):
    term = _term(text, what)
    if not isinstance(text, str) or det.term_key(term) != text:
        raise LedgerError(f"{what} must be a canonical N-Triples term: {det.term_key(term)}")
    return term


def _check_date(value) -> str:
    if isinstance(value, str):
        try:
            if _DATE.fullmatch(value):
                _dt.date.fromisoformat(value)
                return value
            if _DATETIME.fullmatch(value):
                _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
                return value
        except ValueError:
            pass
    raise LedgerError(f"date must be YYYY-MM-DD or an ISO date-time with a zone, got {value!r}")


def _dated_before(later: str, earlier: str) -> bool:
    """Whether ``later`` (a superseding row's date) is before ``earlier``.

    Two date-times compare as instants, so a zone offset cannot make a later
    decision look earlier. A date-only value has no zone, so any comparison
    with one uses the calendar dates as written.
    """
    if _DATETIME.fullmatch(later) and _DATETIME.fullmatch(earlier):
        def instant(value):
            return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return instant(later) < instant(earlier)
    return later[:10] < earlier[:10]


def _date_literal(value: str) -> ox.Literal:
    kind = "date" if _DATE.fullmatch(value) else "dateTime"
    return ox.Literal(value, datatype=ox.NamedNode(_XSD + kind))


def _minutes(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LedgerError("review_minutes must be a number of minutes")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise LedgerError("review_minutes must be finite and not negative")
    return value


def _minutes_text(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if value.is_integer() else repr(value)


def _check_decision(d: Decision) -> Decision:
    """A normalised copy of ``d`` with its computed key, or :class:`LedgerError`."""
    if not isinstance(d, Decision):
        raise LedgerError("expected a review.Decision")
    if d.decision not in DECISION_TOKENS:
        raise LedgerError(f"unknown decision {d.decision!r}; expected one of {DECISION_TOKENS}")
    target = _absolute_iri(d.target, "target")
    if (not isinstance(d.reviewer, str) or not d.reviewer.strip() or d.reviewer != d.reviewer.strip()
            or any(c in d.reviewer for c in "\r\n")):
        raise LedgerError("reviewer: the person's name is required, on one line, without surrounding spaces")
    orcid = d.reviewer_orcid or None
    if orcid is not None and not (isinstance(orcid, str) and _ORCID.fullmatch(orcid)):
        raise LedgerError(f"reviewer_orcid is not an ORCID iD: {orcid!r}")
    _check_date(d.date)
    statement = any((d.subject, d.predicate, d.object))
    obj = None
    if statement:
        if not (d.subject and d.predicate and d.object and d.mapping_set):
            raise LedgerError("a statement decision needs subject, predicate, object and mapping_set")
        if d.node_content:
            raise LedgerError("node_content is only recorded for node decisions")
        subject, predicate, obj = (_canonical(getattr(d, f), f) for f in ("subject", "predicate", "object"))
        key = assertion_key(subject, predicate, obj, d.mapping_set)
    else:
        if d.mapping_set:
            raise LedgerError("mapping_set is only recorded for statement decisions")
        if not d.node_content:
            raise LedgerError("a node decision needs node_content, the digest of the content reviewed "
                              "(review.node_content)")
        key = node_key(target, d.node_content)
    if d.key and d.key != key:
        raise LedgerError(f"key {d.key} does not match the decision's content ({key})")
    amended = d.amended_object or None
    if d.decision == "humanAmended":
        if not statement or amended is None:
            raise LedgerError("humanAmended needs a statement target and an amended_object")
        replacement = _canonical(amended, "amended_object")
        if _has_blank(replacement):
            raise LedgerError("amended_object must not contain a blank node")
        if replacement == obj:
            raise LedgerError("amended_object equals the original object; record humanAccepted instead")
    elif amended is not None:
        raise LedgerError("amended_object is only recorded with humanAmended")
    note = d.note or None
    if note is not None and (not isinstance(note, str) or not note.strip()):
        raise LedgerError("note must be text")
    supersedes = d.supersedes or None
    if supersedes is not None and not (isinstance(supersedes, str) and _HEX16.fullmatch(supersedes)):
        raise LedgerError(f"supersedes must be a decision_id (16 hex digits), got {supersedes!r}")
    return replace(d, key=key, reviewer_orcid=orcid, amended_object=amended, note=note,
                   review_minutes=_minutes(d.review_minutes), supersedes=supersedes)


def _row_values(d: Decision) -> list[str]:
    def text(column):
        if column == "review_minutes":
            return _minutes_text(d.review_minutes)
        value = getattr(d, column)
        return "" if value is None else str(value)
    return [text(column) for column in DECISION_COLUMNS]


def _parse_ledger(data: bytes) -> list[Decision]:
    """Decisions from ledger bytes; only the canonical form :func:`append_decision` writes is accepted."""
    if data.startswith(b"\xef\xbb\xbf"):
        raise LedgerError("the decision ledger must be UTF-8 without a byte-order mark")
    try:
        text = data.decode("utf-8")
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise LedgerError(f"the decision ledger is not valid UTF-8 CSV: {exc}") from exc
    if not rows or tuple(rows[0]) != DECISION_COLUMNS:
        raise LedgerError("unrecognized decision ledger header; expected review.DECISION_COLUMNS")
    decisions = []
    for line, row in enumerate(rows[1:], start=2):
        if len(row) != len(DECISION_COLUMNS):
            raise LedgerError(f"decision ledger row {line}: expected {len(DECISION_COLUMNS)} fields")
        values = dict(zip(DECISION_COLUMNS, row))
        minutes = values.pop("review_minutes")
        try:
            minutes_value = float(minutes) if minutes else None
        except ValueError as exc:
            raise LedgerError(f"decision ledger row {line}: review_minutes is not a number") from exc
        fields = {k: v if v or k in _KEY_COLUMNS else None for k, v in values.items()}
        for required in ("target", "decision", "reviewer", "date"):
            fields[required] = values[required]
        try:
            decision = _check_decision(Decision(**fields, review_minutes=minutes_value))
        except LedgerError as exc:
            raise LedgerError(f"decision ledger row {line}: {exc}") from exc
        if _row_values(decision) != row:
            raise LedgerError(f"decision ledger row {line} is not in canonical form; write rows with "
                              "review.append_decision")
        decisions.append(decision)
    if det.csv_bytes(DECISION_COLUMNS, [_row_values(d) for d in decisions]) != data:
        raise LedgerError("the decision ledger is not in canonical CSV form (quoting, line ends); write "
                          "rows with review.append_decision")
    return decisions


def _reviewer(d: Decision, review: ox.NamedNode) -> tuple[ox.NamedNode, set[ox.Quad]]:
    builder = GraphBuilder()
    person = provenance.person_agent(builder, d.reviewer, graph=review.value, orcid=d.reviewer_orcid)
    return ox.NamedNode(person), set(builder.quads)


def _decision_effects(index: _ReviewIndex, t: _Target, d: Decision,
                      review: ox.NamedNode) -> tuple[set[ox.Quad], set[ox.Quad]]:
    """The quads one decision removes and adds for one target (deterministic)."""
    Q, Nn = ox.Quad, ox.NamedNode
    node, terms = t.node, index.terms
    status = Nn(terms.review_status)
    remove = {Q(node, status, value, g) for value in index.objects(node, terms.review_status)
              for g in t.status_graphs}
    add = {Q(node, status, Nn(terms.values[d.decision]), g) for g in t.status_graphs}
    person, people = _reviewer(d, review)
    when = _date_literal(d.date)
    stamp = Nn(_PAV + "curatedOn") if when.datatype.value.endswith("dateTime") else Nn(_DCT + "date")
    activity = Nn(iri.activity("review", decision_id(d)))
    add |= people | {
        Q(node, Nn(_PAV + "curatedBy"), person, review), Q(node, stamp, when, review),
        Q(activity, Nn(_RDF + "type"), Nn(_PROV + "Activity"), review),
        Q(activity, Nn(_RDFS + "label"), ox.Literal("Human review decision", language="en"), review),
        Q(activity, Nn(_DCT + "date"), when, review),
        Q(activity, Nn(_PROV + "wasAssociatedWith"), person, review),
        Q(activity, Nn(_PROV + "used"), node, review),
    }
    if d.note:
        add.add(Q(node, Nn(_SKOS + "editorialNote"), ox.Literal(d.note), review))
    if index.objects(node, _SSSOM + "mapping_justification"):           # an SSSOM mapping: SEMAPV's review
        add |= {Q(node, Nn(_SSSOM + "reviewer_id"), person, review),
                Q(activity, Nn(_RDF + "type"), Nn(_SEMAPV + "MappingReview"), review)}
    if t.statement is None:
        if d.decision == "humanAmended":
            raise LedgerError(f"{node.value}: humanAmended needs a statement target")
        return remove, add
    s, p, o = t.statement.subject, t.statement.predicate, t.statement.object
    if d.decision == "humanAccepted":
        add |= {Q(s, p, o, g) for g in t.reifier_graphs}
        add |= _year_dependencies(index, node, s, p, o)
        return remove, add
    remove |= {Q(s, p, o, g) for g in t.reifier_graphs}   # withdraws an agent-accepted assertion
    if d.decision == "humanAmended":
        amended = _term(d.amended_object, "amended_object")
        revision = Nn(iri.xwalk(AMENDMENT_MAPPING_SET, iri.stable_key(d.key, det.term_key(amended))))
        for g in t.reifier_graphs:
            add |= {Q(revision, Nn(RDF_REIFIES), ox.Triple(s, p, amended), g), Q(s, p, amended, g),
                    Q(revision, Nn(_SSSOM + "mapping_justification"), Nn(_SEMAPV + "ManualMappingCuration"), g),
                    Q(revision, Nn(_PROV + "wasDerivedFrom"), node, g),
                    Q(revision, Nn(_PROV + "wasRevisionOf"), node, g)}
        add |= {Q(revision, Nn(_PAV + "curatedBy"), person, review), Q(revision, stamp, when, review),
                Q(activity, Nn(_PROV + "generated"), revision, review)}
        add |= _year_dependencies(index, node, s, p, amended, revision=revision)
    return remove, add


def _year_dependencies(index: _ReviewIndex, target, s, p, o, revision=None) -> set[ox.Quad]:
    """Canonical-year facts that follow from an accepted year-basis binding.

    Mirrors the compiler's live-binding rule (``_compile.py``) and the
    validator's year trace: an observation that ``prov:wasDerivedFrom`` the
    year component gets ``<basis> <its source-year value>``, copied from its
    one source year column. Anything that does not match that exact shape is
    left to validation.
    """
    if p.value != _QB + "dimension" or not isinstance(o, ox.NamedNode) or o.value not in _YEAR_BASES:
        return set()
    column_type = ox.NamedNode(_CSVW + "Column")
    observation_types = {ox.NamedNode(_QB + "Observation"), ox.NamedNode(_SOSA + "Observation")}
    years = {c for c in index.objects(s, _PROV + "wasDerivedFrom")
             if isinstance(c, ox.NamedNode) and column_type in index.objects(c, index.rdf_type)}
    out = set()
    for obs in index.incoming.get(s, set()):
        if not index.objects(obs, index.rdf_type) & observation_types:
            continue
        candidates = years - index.objects(obs, _SOSA + "observedProperty")
        if len(candidates) != 1:
            continue
        column = next(iter(candidates))
        values = index.objects(obs, column.value)
        if len(values) != 1:
            continue
        value = next(iter(values))
        if not isinstance(value, ox.Literal) or value.datatype.value != _XSD + "gYear":
            continue
        for graph in index.graphs(obs, column.value):
            out.add(ox.Quad(obs, o, value, graph))
            if revision is not None:
                out.add(ox.Quad(obs, ox.NamedNode(_PROV + "wasDerivedFrom"), revision, graph))
    return out


def _record_predicates() -> frozenset[str]:
    """Predicates that make up a target's D6 record (kept for a pending node target)."""
    terms = provenance.terms()
    return frozenset({RDF_REIFIES, _PROV + "wasAttributedTo", _PROV + "wasGeneratedBy", _PROV + "wasDerivedFrom",
                      _DCT + "created", terms.confidence, terms.criticality, terms.review_status}) | _CURATION


_PROPERTY_AXIOMS = frozenset({_RDFS + "subPropertyOf", _OWL + "equivalentProperty", _OWL + "inverseOf"})


def _closed_floor(index: _ReviewIndex) -> dict[str, str]:
    """``provenance.CRITICAL_PREDICATES`` closed over the property axioms ``index`` asserts (:meth:`_ReviewIndex.floor`)."""
    entails = defaultdict(set)          # predicate -> predicates a statement with it entails
    for (subject, predicate), objects in index.by_sp.items():
        if predicate not in _PROPERTY_AXIOMS or not isinstance(subject, ox.NamedNode):
            continue
        for obj in objects:
            if isinstance(obj, ox.NamedNode):
                entails[subject.value].add(obj.value)
                if predicate != _RDFS + "subPropertyOf":      # equivalence and inverse hold both ways
                    entails[obj.value].add(subject.value)
    table = provenance.CRITICAL_PREDICATES
    floors = dict(table)
    for start in entails:
        if start in table:
            continue
        seen, queue, aspects = {start}, deque([start]), set()
        while queue:
            for nxt in entails.get(queue.popleft(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
                    if nxt in table:
                        aspects.add(table[nxt])
        if aspects:
            floors[start] = min(aspects)
    return floors


def _node_floor(index: _ReviewIndex, node: ox.NamedNode) -> tuple[ox.Triple, str] | None:
    """The first critical link a node target's own content asserts, with its aspect; ``None`` if none.

    A node target (marked whole by ``mark_derived``) is critical in effect
    when any triple with the node as subject, outside its D6 record and
    curation marks and not governed by a review target or amendment of its
    own (:func:`_governed_statements`), has a predicate with a criticality
    floor. The canonical year counts here, although :func:`node_content`
    leaves it out of the key: a year asserted on a pending node is a pending
    critical value. Such a link is the node's to assert only once a person
    accepts the node; a producer keeps it statement-only by reifying it with
    ``provenance.mark_statement`` instead (design review S6a, S6c).
    """
    governed, record = index.governed(), _record_predicates()
    found = []
    for predicate in index.predicates.get(node, ()):
        aspect = index.floor(predicate)
        if aspect is None or predicate in record:
            continue
        p = ox.NamedNode(predicate)
        for obj in index.objects(node, predicate):
            if (node, p, obj) not in governed:
                found.append((det.term_key(p), det.term_key(obj), ox.Triple(node, p, obj), aspect))
    if not found:
        return None
    first = min(found, key=lambda f: f[:2])
    return first[2], first[3]


def _floor_link(index: _ReviewIndex, node: ox.NamedNode,
                statement: ox.Triple | None) -> tuple[ox.Triple, str] | None:
    """The critical link that puts ``node`` under the criticality floor, with its aspect, or ``None``.

    For a statement target, its reified triple when the predicate has a floor;
    for a node target, :func:`_node_floor`.
    """
    if statement is None:
        return _node_floor(index, node)
    aspect = index.floor(statement.predicate)
    return None if aspect is None else (statement, aspect)


def _agent_acceptable(index: _ReviewIndex, node: ox.NamedNode, statement: ox.Triple | None) -> bool:
    """Whether an ``agentAccepted`` status on ``node`` is one the D6 rule allows.

    Only high-confidence, non-critical assertions are agent-accepted, and the
    criticality is the effective one: a statement whose predicate has a floor
    (:meth:`_ReviewIndex.floor`: ``provenance.criticality_floor`` closed over
    the store's sub-property, equivalence and inverse axioms), or a node target whose own
    content asserts such a link (:func:`_node_floor`), is critical whatever
    its mark says, because an agent may raise criticality, never lower it
    (design review S6a). Missing or conflicting marks fail (an unmarked
    acceptance is no proof).
    """
    confidence = index.ordinal(node, index.terms.confidence, provenance.CONFIDENCE_LEVELS)
    criticality = index.ordinal(node, index.terms.criticality, provenance.CRITICALITY_LEVELS)
    if _floor_link(index, node, statement) is not None:
        return False
    return provenance.review_status(confidence, criticality) == "agentAccepted"


def _effective_criticality(index: _ReviewIndex, node: ox.NamedNode, statement: ox.Triple | None) -> str:
    """The recorded criticality, raised to ``critical`` by the floor (:func:`_floor_link`)."""
    declared = index.ordinal(node, index.terms.criticality, provenance.CRITICALITY_LEVELS)
    if _floor_link(index, node, statement) is not None:
        return "critical"
    return declared


def _supports(index: _ReviewIndex, t: _Target, status: str) -> bool:
    """Whether ``status`` on statement target ``t`` lets its reified triple be asserted."""
    if status == "humanAccepted":
        return True
    return status == "agentAccepted" and _agent_acceptable(index, t.node, t.statement)


def _blank_terms(term):
    """Blank nodes that ``term`` refers to, inside triple terms too."""
    if isinstance(term, ox.BlankNode):
        yield term
    elif isinstance(term, ox.Triple):
        yield from _blank_terms(term.subject)
        yield from _blank_terms(term.object)


def _drop_orphans(kept: list[ox.Quad], dropped: Sequence[ox.Quad]) -> list[ox.Quad]:
    """``kept`` minus the blank-node structure that only ``dropped`` quads reached.

    Stripping a pending node target's content (or an unsupported triple)
    would otherwise leave the blank nodes it pointed to, and their triples,
    behind as orphans. A blank node any kept quad still refers to stays.
    """
    candidates = {b for q in dropped for b in _blank_terms(q.object)}
    while candidates:
        referenced = {b for q in kept for b in _blank_terms(q.object)}
        orphans = candidates - referenced
        if not orphans:
            break
        removed = [q for q in kept if q.subject in orphans]
        kept = [q for q in kept if q.subject not in orphans]
        candidates = {b for q in removed for b in _blank_terms(q.object)}
    return kept


def _check_statement_only(quads: Sequence[ox.Quad], targets: Mapping[ox.NamedNode, _Target],
                          final: Mapping[ox.NamedNode, str]) -> None:
    """Fail when any pending, rejected or amended-away triple is asserted in any graph of ``quads``.

    ``targets`` are the input's review targets and ``final`` their decided
    statuses; a decision never creates a target, so this covers the output.
    An undecided ``agentAccepted`` statement that the D6 rule does not allow
    (:func:`_agent_acceptable`) counts as pending.

    A node target's own content is asserted by definition, so a node whose
    content holds a critical link (:func:`_node_floor`) fails unless a person
    accepted it: pending, rejected and agent-accepted alike. Floors are read
    from the decided store ``quads`` itself, since an accepted decision can
    assert a property axiom or a node's canonical year.
    """
    live = {(q.subject, q.predicate, q.object) for q in quads}
    built = []

    def out() -> _ReviewIndex:
        if not built:
            built.append(_ReviewIndex(quads))
        return built[0]

    for t in sorted(targets.values(), key=lambda t: t.node.value):
        status = final.get(t.node, t.status)
        if t.statement is None:
            if status == "humanAccepted":
                continue
            link = _node_floor(out(), t.node)
            if link is None:
                continue
            triple, aspect = link
            what = f"its own content asserts {det.term_key(triple.predicate)} {det.term_key(triple.object)}"
            if status == "agentAccepted":
                raise LedgerError(f"criticality floor: node target {t.node.value} is agentAccepted, but {what}, "
                                  f"which is always critical ({aspect}); an agent may raise criticality, never "
                                  "lower it, so a person must accept the node (review.record_decision) before "
                                  "that link is asserted, or the producer must reify it with "
                                  "provenance.mark_statement")
            raise LedgerError(f"statement-only rule: node target {t.node.value} is {status} but {what}, a "
                              f"critical link ({aspect}); only a person's acceptance of the node asserts it. "
                              "Reify such links with provenance.mark_statement so they stay statement-only "
                              "until decided")
        if ((t.statement.subject, t.statement.predicate, t.statement.object) not in live
                or _supports(out(), t, status)):
            continue
        if status == "agentAccepted":
            aspect = out().floor(t.statement.predicate)
            why = (f"its predicate {t.statement.predicate.value} is always critical ({aspect})" if aspect
                   else "its marks are not high confidence and non-critical")
            raise LedgerError(f"criticality floor: {t.node.value} is agentAccepted, but {why}; an agent may "
                              "raise criticality, never lower it, so a person must decide it "
                              "(review.record_decision) before its triple is asserted")
        raise LedgerError(f"statement-only rule: {t.node.value} is {status} but its triple is "
                          "asserted; decide every assertion of that triple")
