"""Identity layers: authority nodes, published membership, crosswalks, selection sets. STUB.

The identity model of architecture.md section 8 (ADR-0001 D5). Four layers,
never collapsed into one hierarchy:

1. **Authority nodes** -- one per unit per authority, ``iri.ident(kind,
   authority, local_id)``, with the source's label verbatim, its key,
   species (NCBITaxon), region where stated, and ``dcterms:source``. Never
   merged.
2. **Published membership** -- roll-ups ingested from authoritative sources
   (first: the DFO SMU-CU-DU crosswalk), each a reifier
   ``iri.membership(source, version, key)`` with ``dcterms:source``,
   ``pav:version`` and a validity period. Validity reuses schema.org
   (``schema:validFrom`` / ``schema:validThrough``, xsd:date) rather than a
   corp: term. Never inferred transitively without saying so.
3. **Crosswalks** -- equivalence between authorities as SSSOM-style reified
   assertions ``iri.xwalk(mapping_set, iri.stable_key(s, p, o))`` with
   ``sssom:mapping_justification`` (a ``semapv:`` IRI), ``sssom:confidence``
   when a score exists, evidence and D6 marks. ``skos:exactMatch`` only when
   the numbers prove it (identical totals within 0.5% for at least 90% of
   shared years); ``skos:closeMatch`` for the same unit with different
   numbers; ``skos:broadMatch`` / ``skos:narrowMatch`` for aggregates.
   Agent-derived crosswalks are always critical, so always awaitingReview.
   A published crosswalk is not agent-derived: cite the source and version.
4. **Selection sets** -- named, versioned sets for one analysis,
   ``iri.selection(name, version)``. Recommended pattern (reuse first): the
   set is a ``prov:Collection`` with ``prov:hadMember`` per included unit; an
   exclusion is a reified ``<set> corp:excludes <unit>`` (no PROV/DCAT/schema.org
   term says "deliberately not a member"; mint it only with that note); each
   inclusion's or exclusion's rationale is ``skos:scopeNote`` on its reifier.

Graphs: authority nodes a dataset mentions go to that dataset's ``identity``
graph (executor); nodes from published identity sources, membership,
crosswalks and selection sets go to the shared ``identity``, ``membership``
and ``crosswalk`` graphs (``iri.corpus_graph``).

Published identity sources, in order of adoption: DFO SMU-CU-DU crosswalk
(``pacific_salmon_smu_cu_du_x_walk.csv`` with ``DataDictionary.schema.yaml``,
GitHub ``dfo-pacific-science/Salmon-SMU-CU-DU-Crosswalk``; record the commit
or Open Canada version), PSC Fraser production stock definitions, NOAA
ESU/DPS lists, ADF&G stock lists, PSC CTC registers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Sequence

from ._stub import not_yet

if TYPE_CHECKING:  # pragma: no cover
    from .graph import GraphBuilder

__all__ = ["MembershipRow", "authority_node", "load_dfo_smu_cu_du", "add_membership",
           "add_crosswalk", "selection_set"]


@dataclass(frozen=True)
class MembershipRow:
    """One published membership: ``member`` belongs to ``group`` per ``source`` at ``source_version``."""

    member: str            # identity node IRI (e.g. iri.ident("cu", "dfo", "CK-01"))
    group: str             # identity node IRI (e.g. iri.ident("smu", "dfo", "..."))
    source: str            # membership source name, kebab (e.g. "dfo-smu-cu")
    source_version: str    # e.g. "2025-11-28" or a git commit
    key: str               # the member's key in the source; becomes the reifier IRI's last segment
    source_iri: str        # where it is published (dcterms:source)
    valid_from: str | None = None
    valid_to: str | None = None


def authority_node(builder: "GraphBuilder", kind: str, authority: str, local_id: object, *,
                   graph: str, label: str, source: str, types: Sequence[str] = (),
                   species: str | None = None, region: str | None = None,
                   identifier: str | None = None) -> str:
    """Write one authority node (layer 1); returns its IRI.

    ``label`` is the source's own name, verbatim (``rdfs:label``, no language
    tag unless the source gives one); ``source`` the dataset or register IRI
    (``dcterms:source``); ``identifier`` the source key as
    ``dcterms:identifier "<authority>:<key>"``; ``species`` an NCBITaxon IRI.
    """
    raise not_yet("identity.authority_node")


def load_dfo_smu_cu_du(path: Path, *, source_version: str) -> list[MembershipRow]:
    """Read the DFO SMU-CU-DU crosswalk CSV into membership rows (CU -> SMU, DU -> CU as published).

    Validates columns against the clone's ``DataDictionary.schema.yaml``.
    ``source_version`` is the crosswalk's dated version or git commit.
    """
    raise not_yet("identity.load_dfo_smu_cu_du")


def add_membership(builder: "GraphBuilder", row: MembershipRow, *, graph: str,
                   predicate: str = "skos:broader", assert_triple: bool = True) -> str:
    """Write a published membership as a reifier (layer 2); returns the reifier IRI.

    Not agent-derived, so no D6 marks: ``dcterms:source``, ``pav:version``,
    ``schema:validFrom`` / ``schema:validThrough`` on the reifier instead.
    """
    raise not_yet("identity.add_membership")


def add_crosswalk(builder: "GraphBuilder", subject: str, predicate: str, obj: str, *,
                  mapping_set: str, graph: str, justification: str,
                  evidence: str | Sequence[str], confidence_score: float | None = None,
                  published_source: str | None = None, agent: str | None = None,
                  activity: str | None = None, confidence: str | None = None,
                  date: str | None = None) -> str:
    """Write one crosswalk assertion (layer 3) as a reified statement; returns the reifier IRI.

    Either ``published_source`` (a published crosswalk: cite it, no D6
    marks) or ``agent`` + ``activity`` + ``confidence`` (agent-derived:
    ``provenance.mark_statement`` with criticality ``critical``) must be
    given. ``justification`` is a ``semapv:`` IRI; ``confidence_score`` is
    ``sssom:confidence`` in [0, 1].
    """
    raise not_yet("identity.add_crosswalk")


def selection_set(builder: "GraphBuilder", name: str, version: str, *, graph: str, label: str,
                  includes: Mapping[str, str], excludes: Mapping[str, str],
                  agent: str | None = None, activity: str | None = None) -> str:
    """Write a selection set (layer 4); returns its IRI.

    ``includes`` / ``excludes`` map a unit IRI to its rationale. Pattern in
    the module docstring. Agent-proposed sets are marked (critical: they
    change which units a number covers).
    """
    raise not_yet("identity.selection_set")
