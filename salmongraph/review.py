"""Review queues, views and human decisions (ADR-0001 D6; architecture.md 11). STUB.

Built on the marks ``provenance.mark_derived`` writes. Three jobs:

**Queue.** Every target whose ``corp:reviewStatus`` is ``awaitingReview``,
one row each, sorted: critical first, then by how many downstream joins
depend on it (observations whose ``review_status`` it decides, crosswalk
links through it), then by target IRI. Written as CSV with
:data:`REVIEW_QUEUE_COLUMNS` (``review-queue.csv`` in each dataset build and in
each release).

**Decisions as data.** A person records decisions in ``reviews/decisions.csv``
(committed; :data:`DECISION_COLUMNS`), keyed by target IRI. A decision is
applied at build time, so every built store holds exactly **one**
``corp:reviewStatus`` per target: the decision replaces the agent status,
and the decision's reviewer and date go on the target as ``pav:curatedBy``
(a ``prov:Person``, ORCID when known) and ``pav:curatedOn`` (xsd:dateTime,
only when a time was recorded; a date-only decision uses ``dcterms:date``
with xsd:date rather than inventing a time), with the note as
``skos:editorialNote``. ``humanAmended`` carries the amended statement as a
new reifier that ``prov:wasRevisionOf`` the original. Decisions on targets
that no longer exist are reported, never dropped silently.

**Views.** The reviewed view keeps statements with no marks (stated by a
source) plus targets whose status is in ``provenance.REVIEWED_STATUSES``; an
asserted triple whose reifier is ``awaitingReview`` or ``rejected`` is
excluded too. The full view keeps everything, with status shown. Every
query surface (MCP, SPARQL endpoint, release) offers both.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import datetime as _dt
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

import pyoxigraph as ox

from . import config, provenance
from ._stub import not_yet
from .config import ROOT
from .graph import N
from .io import det

if TYPE_CHECKING:  # pragma: no cover
    import pyoxigraph as ox

    from .graph import GraphBuilder

__all__ = ["REVIEW_QUEUE_COLUMNS", "DECISION_COLUMNS", "DECISIONS_PATH", "VIEWS", "ReviewItem",
           "Decision", "review_queue", "write_review_queue", "load_decisions", "apply_decisions",
           "view_store", "status_counts"]

REVIEW_QUEUE_COLUMNS = ("target", "status", "criticality", "confidence", "statement", "graph",
                        "agent", "activity", "date", "evidence", "suggested_decision",
                        "downstream_joins")
DECISION_COLUMNS = ("target", "decision", "reviewer", "reviewer_orcid", "date",
                    "amended_object", "note")
#: ``reviews/decisions.csv`` at the repository root (committed).
DECISIONS_PATH = ROOT / "reviews" / "decisions.csv"
VIEWS = ("reviewed", "full")


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
    """One row of ``reviews/decisions.csv``."""

    target: str
    decision: str           # humanAccepted | humanAmended | rejected
    reviewer: str
    date: str
    reviewer_orcid: str | None = None
    amended_object: str | None = None
    note: str | None = None


def review_queue(data: "ox.Store | Iterable[ox.Quad]", *, graphs: Sequence[str] | None = None) -> list[ReviewItem]:
    """Actual pending records, critical first, then recorded dependencies, then IRI.

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
        if status != "awaitingReview":
            continue
        status_graphs = index.graphs(target, index.terms.review_status)
        criticality = index.ordinal(target, index.terms.criticality, provenance.CRITICALITY_LEVELS)
        confidence = index.ordinal(target, index.terms.confidence, provenance.CONFIDENCE_LEVELS)
        statement = index.statement(target)
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
        if not isinstance(item, ReviewItem) or item.status != "awaitingReview":
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


def load_decisions(path: Path = DECISIONS_PATH) -> list[Decision]:
    """Read and validate decisions (known decision tokens, dates, one decision per target)."""
    raise not_yet("review.load_decisions")


def apply_decisions(builder: "GraphBuilder", decisions: Sequence[Decision], *, graph: str) -> list[str]:
    """Apply decisions to the marks in ``builder``; returns targets that were not found."""
    raise not_yet("review.apply_decisions")


def view_store(store: "ox.Store", view: str = "reviewed") -> "ox.Store":
    """A store holding only what ``view`` shows (``"reviewed"`` or ``"full"``)."""
    raise not_yet("review.view_store")


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
        self.subjects = set()
        self.derived = self.ns["prov"] + "wasDerivedFrom"
        self.rdf_type = self.ns["rdf"] + "type"
        for quad in data:
            if not isinstance(quad, ox.Quad):
                raise ValueError("review input must contain RDF quads")
            self.by_sp[quad.subject, quad.predicate.value].add(quad.object)
            self.by_sp_graph[quad.subject, quad.predicate.value].add(quad.graph_name)
            self.subjects.add(quad.subject)
            if quad.predicate.value == self.derived:
                if not isinstance(quad.object, (ox.NamedNode, ox.BlankNode)):
                    raise ValueError("prov:wasDerivedFrom must refer to an entity, not a literal/triple")
                self.incoming[quad.object].add(quad.subject)
        self._statements = {}

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
            raise ValueError(f"pending target {target.value}: missing or conflicting {predicate}")
        value = next(iter(values))
        token = provenance.token_of(value.value) if isinstance(value, ox.NamedNode) else None
        if token not in allowed:
            raise ValueError(f"pending target {target.value}: unknown ordinal {predicate}")
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
