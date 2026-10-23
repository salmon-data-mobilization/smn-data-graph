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

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

from ._stub import not_yet
from .config import ROOT

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
    """Pending items, sorted as the module docstring says."""
    raise not_yet("review.review_queue")


def write_review_queue(items: Sequence[ReviewItem], path: Path) -> Path:
    """CSV with :data:`REVIEW_QUEUE_COLUMNS` via ``io.det.write_csv``."""
    raise not_yet("review.write_review_queue")


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
    raise not_yet("review.status_counts")
