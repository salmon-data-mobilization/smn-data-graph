"""Bounded local connected discovery, without admission or semantic inference.

The caller supplies an already admitted, access-appropriate named-graph store.
Only existing RDF slots are read: DCAT datasets/CSVW columns, QB observations,
``qb:concept``, ``sosa:usedProcedure`` and explicitly typed population identities.
An exact shared IRI is a discovery connection, never a pooling recommendation.
No query text, remote endpoint, review decision or write operation is accepted.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Sequence

import pyoxigraph as ox

from . import provenance, review
from .graph import N, RDF_REIFIES

__all__ = ["discover", "FAMILIES", "MAX_SCAN_QUADS", "MAX_READ_PATTERNS"]

FAMILIES = ("measurement", "procedure", "population")
MAX_SCAN_QUADS = 50_000
MAX_READ_PATTERNS = 10_000
_POPULATION_TYPES = {N(name) for name in ("smn:Population", "smn:Deme", "smn:Stock",
    "gcdfo:ConservationUnit", "gcdfo:StockManagementUnit")}


def _iris(values, label, *, allow_empty=False):
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"discovery: {label} must be a sequence of absolute IRIs")
    if len(values) > 128 or not values and not allow_empty:
        raise ValueError(f"discovery: {label} needs 1..128 absolute IRIs")
    result = set()
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError(f"discovery: {label} must contain absolute IRI strings")
        try:
            result.add(ox.NamedNode(value))  # No CURIE expansion or query interpolation.
        except ValueError as exc:
            raise ValueError(f"discovery: {label} must contain absolute IRIs") from exc
    return result


class _Evidence:
    def __init__(self, quads, pending, selected):
        self.selected = selected
        self.objects = defaultdict(set)
        self.graphs = defaultdict(set)
        self.records = defaultdict(set)
        for q in quads:
            self.objects[q.subject, q.predicate].add(q.object)
            self.graphs[q.subject, q.predicate, q.object].add(q.graph_name.value)
            if q.predicate.value == RDF_REIFIES and isinstance(q.object, ox.Triple):
                t = q.object
                self.records[t.subject, t.predicate, t.object].add(q.subject)
        # This is the complete original store's effective pending set, never a
        # recomputation on display-filtered or incomplete evidence.
        self.pending = pending

    def get(self, node, predicate):
        return self.objects[node, N(predicate)]

    def edge(self, subject, predicate, obj):
        records = sorted(self.records[subject, predicate, obj], key=str)
        status = provenance.terms().review_status
        targets = [*records, subject] if self.objects[subject, N(status)] else records
        recorded = sorted({provenance.token_of(v.value) or v.value
            for record in targets for v in self.objects[record, N(status)]
            if isinstance(v, ox.NamedNode)})
        live_graphs = sorted(g for g in self.graphs[subject, predicate, obj]
                             if self.selected is None or N(g) in self.selected)
        pending = any(r in self.pending for r in targets)
        if pending:
            authority = "awaiting_review"
        elif "humanAccepted" in recorded:
            authority = "human_accepted"
        elif "agentAccepted" in recorded:
            authority = "agent_accepted"
        elif any(self.get(r, "dcterms:source") for r in records):
            authority = "source_stated"
        else:
            authority = "unmarked"  # No mark is not proof of a source or person.
        evidence = {str(v) for node in [subject, *records]
                    for p in ("dcterms:source", "prov:wasDerivedFrom", "dcterms:description")
                    for v in self.get(node, p)}
        # Follow the already loaded proof resources, including nested/cyclic
        # blank-node evidence; an immediate blank-node ID is not its text.
        todo, visited = [subject, *records], set()
        while todo:
            node = todo.pop()
            if node in visited:
                continue
            visited.add(node)
            evidence.update(str(v) for v in self.get(node, "prov:value"))
            resources = self.get(node, "prov:wasDerivedFrom")
            evidence.update(str(v) for v in resources)
            todo.extend(v for v in resources if isinstance(v, (ox.NamedNode, ox.BlankNode)))
        return {"subject": subject.value, "predicate": predicate.value, "object": obj.value,
            "graphs": live_graphs or sorted({g for r in records
                for g in self.graphs[r, N(RDF_REIFIES), ox.Triple(subject, predicate, obj)]}),
            "asserted": bool(live_graphs), "authority": authority,
            "recorded_review_status": recorded, "records": [r.value for r in records],
            "evidence": sorted(evidence),
            "units": sorted(str(v) for v in self.get(subject, "qudt:unit")),
            "scope": {p: sorted(str(v) for v in self.get(subject, p)) for p in
                ("dcterms:spatial", "dcterms:temporal", "sssom:mapping_justification")
                if self.get(subject, p)}}

    def source(self, dataset):
        return {"iri": dataset.value,
            "versions": sorted(v.value for v in self.get(dataset, "pav:version")
                               if isinstance(v, ox.Literal)),
            "sources": sorted(str(v) for p in ("dcterms:source", "prov:wasDerivedFrom")
                              for v in self.get(dataset, p)),
            "graphs": sorted({g for (s, _, _), names in self.graphs.items()
                              if s == dataset for g in names})}

class _ReadLimit(Exception):
    """The targeted result/proof budget was exhausted; no partial proof escapes."""


class _Reader:
    """Indexed reads from one globally reviewed snapshot, with a separate budget.

    Global review intentionally remains O(total store). The budget counts unique
    quads visited by these fixed local patterns, including excluded graph hits;
    it is not a claim about native query-engine or review-materialization memory.
    """
    def __init__(self, source, selected, pending_rows):
        self.source, self.selected = source, selected
        self.visited, self.pattern_count = set(), 0
        self.pending_sp, self.pending_po, self.pending_o = defaultdict(set), defaultdict(set), defaultdict(set)
        for row in pending_rows:
            # Global effective review is already determined on the ORIGINAL
            # source, before view_store strips any pending node content.
            for q in source.quads_for_pattern(N(row.target), N(RDF_REIFIES), None, None):
                if isinstance(q.object, ox.Triple) and (selected is None or q.graph_name in selected):
                    t = q.object
                    self.pending_sp[t.subject, t.predicate].add(t.object)
                    self.pending_po[t.predicate, t.object].add(t.subject)
                    self.pending_o[t.object].add((t.subject, t.predicate))

    def find(self, subject=None, predicate=None, obj=None, *, eligible=True):
        self.pattern_count += 1
        if self.pattern_count > MAX_READ_PATTERNS:
            raise _ReadLimit("targeted_pattern_limit")
        for q in self.source.quads_for_pattern(subject, predicate, obj, None):
            self.visited.add(q)
            if len(self.visited) > MAX_SCAN_QUADS:
                raise _ReadLimit("targeted_quad_limit")
            if not eligible or self.selected is None or q.graph_name in self.selected:
                yield q

    def values(self, subject, predicate):
        return {q.object for q in self.find(subject, N(predicate))}

    def semantic(self, subject, predicate, include_pending):
        values = self.values(subject, predicate.value)
        if include_pending:
            values |= self.pending_sp[subject, predicate]
        return {v for v in values if isinstance(v, ox.NamedNode)}

    def population_types(self, obj):
        return self.values(obj, "rdf:type") & _POPULATION_TYPES

    def population_slot(self, predicate):
        return predicate == N("sosa:hasFeatureOfInterest") or bool(
            self.values(predicate, "rdf:type") & {N("qb:DimensionProperty"), N("qb:AttributeProperty")})

    def ancestors(self, table):
        # Exact inverse membership edges, not an IRI-prefix or label match.
        paths, todo = {table: []}, [table]
        while todo:
            child = todo.pop(0)
            parents = sorted({q.subject for q in self.find(None, N("dcterms:hasPart"), child)}, key=str)
            for parent in parents:
                if isinstance(parent, ox.NamedNode) and parent not in paths:
                    paths[parent] = [(parent, N("dcterms:hasPart"), child), *paths[child]]
                    todo.append(parent)
        return {d: path for d, path in paths.items() if N("dcat:Dataset") in self.values(d, "rdf:type")}

    def memberships(self, subject, family):
        found = {}
        if family != "population":
            schemas = sorted({q.subject for q in self.find(None, N("csvw:column"), subject)}, key=str)
            for schema in schemas:
                tables = sorted({q.subject for q in self.find(None, N("csvw:tableSchema"), schema)}, key=str)
                for table in tables:
                    for dataset, path in self.ancestors(table).items():
                        found.setdefault(dataset, [*path, (table, N("csvw:tableSchema"), schema),
                                                   (schema, N("csvw:column"), subject)])
        if family != "measurement":
            for table in sorted(self.values(subject, "qb:dataSet"), key=str):
                for dataset, path in self.ancestors(table).items():
                    found.setdefault(dataset, [*path, (subject, N("qb:dataSet"), table)])
        return found

    def project_facts(self, dataset, families, include_pending):
        if N("dcat:Dataset") not in self.values(dataset, "rdf:type"):
            return []
        members, todo = {dataset}, [dataset]
        while todo:
            parent = todo.pop()
            for child in self.values(parent, "dcterms:hasPart"):
                if child not in members:
                    members.add(child); todo.append(child)
        columns, observations = set(), set()
        for table in sorted(members, key=str):
            for schema in self.values(table, "csvw:tableSchema"):
                columns |= {v for v in self.values(schema, "csvw:column") if isinstance(v, ox.NamedNode)}
            observations |= {q.subject for q in self.find(None, N("qb:dataSet"), table)
                             if isinstance(q.subject, ox.NamedNode)}
        facts = []
        for family, predicate, subjects in (("measurement", N("qb:concept"), columns),
                ("procedure", N("sosa:usedProcedure"), columns | observations)):
            if family in families:
                for subject in sorted(subjects, key=str):
                    for obj in sorted(self.semantic(subject, predicate, include_pending), key=str):
                        facts.append((dataset, family, obj, subject, predicate))
        if "population" in families:
            for subject in sorted(observations, key=str):
                possible = {(q.predicate, q.object) for q in self.find(subject)}
                if include_pending:
                    possible |= {(p, o) for (s, p), values in self.pending_sp.items() if s == subject for o in values}
                for predicate, obj in sorted(possible, key=str):
                    if isinstance(obj, ox.NamedNode) and self.population_slot(predicate) and self.population_types(obj):
                        facts.append((dataset, "population", obj, subject, predicate))
        return facts

    def candidates(self, family, obj, include_pending):
        if family == "population":
            pairs = {(q.subject, q.predicate) for q in self.find(None, None, obj)}
            if include_pending:
                pairs |= self.pending_o[obj]
            return sorted(((s, p) for s, p in pairs if isinstance(s, ox.NamedNode)
                           and self.population_slot(p)), key=str)
        predicate = N("qb:concept" if family == "measurement" else "sosa:usedProcedure")
        subjects = {q.subject for q in self.find(None, predicate, obj)}
        if include_pending:
            subjects |= self.pending_po[predicate, obj]
        return [(s, predicate) for s in sorted(subjects, key=str) if isinstance(s, ox.NamedNode)]


class _Proof:
    """Complete outgoing endpoint/record/evidence context for selected paths."""
    def __init__(self, reader):
        self.reader, self.quads, self.loaded = reader, set(), set()

    def node(self, node):
        todo = [node]
        while todo:
            subject = todo.pop()
            if subject in self.loaded:
                continue
            self.loaded.add(subject)
            rows = list(self.reader.find(subject, eligible=False))
            self.quads.update(rows)
            # Proof resources may be blank nodes and may form cycles. Never
            # recurse through all vocabulary/object IRIs as a fabricated graph.
            todo.extend(q.object for q in rows if q.predicate in
                {N("prov:wasDerivedFrom"), N("prov:wasGeneratedBy")}
                and isinstance(q.object, (ox.NamedNode, ox.BlankNode)))

    def edge(self, subject, predicate, obj):
        self.node(subject)
        self.quads.update(self.reader.find(subject, predicate, obj, eligible=False))
        for q in self.reader.find(None, N(RDF_REIFIES), ox.Triple(subject, predicate, obj), eligible=False):
            self.quads.add(q)
            self.node(q.subject)


def discover(store_dir: Path, *, project_datasets: Sequence[str], families: Sequence[str] = FAMILIES,
             graphs: Sequence[str] | None = None, include_pending: bool = False,
             limit: int = 50) -> dict:
    """Find OTHER datasets via exact shared IRIs and indexed evidence reads.

    Existing global review and criticality rules run on one original read-only
    snapshot before graph filters. Global review still materializes the store;
    only discovery's subsequent indexed reads and returned proofs are bounded.
    Exhausting that separate budget refuses all paths rather than certifying
    incomplete evidence. This is not an authorization or admission service.
    """
    projects = _iris(project_datasets, "project_datasets")
    selected = None if graphs is None else _iris(graphs, "graphs", allow_empty=True)
    if isinstance(families, (str, bytes)) or not isinstance(families, Sequence) or not families or any(f not in FAMILIES for f in families):
        raise ValueError(f"discovery: families must be a nonempty subset of {FAMILIES}")
    if type(limit) is not int or not 1 <= limit <= 100 or type(include_pending) is not bool:
        raise ValueError("discovery: limit must be 1..100 and include_pending must be boolean")
    try:
        path = Path(store_dir)
    except (TypeError, ValueError) as exc:
        raise ValueError("discovery: store_dir must be an existing store directory") from exc
    if not path.is_dir():
        raise ValueError("discovery: store_dir must be an existing store directory")
    try:
        original = ox.Store.read_only(str(path))
    except (OSError, RuntimeError) as exc:
        raise ValueError("discovery: could not open an existing read-only Oxigraph store") from exc
    try:
        # The original source matters: view_store may strip a pending whole
        # node's critical content. A later queue over that view could forget why
        # the original node was pending. Do not duplicate that policy here.
        pending_rows = review.review_queue(original)
        pending = {N(row.target) for row in pending_rows}
        reviewed = review.view_store(original, "reviewed")
        reader = _Reader(reviewed, selected, pending_rows)
        response = {"paths": [], "limit": limit, "has_more": False,
            "scan_limit": MAX_SCAN_QUADS, "scanned_quads": 0, "scan_truncated": False,
            "read_pattern_limit": MAX_READ_PATTERNS, "partial_reason": None,
            "view": "reviewed", "families": sorted(set(families)), "include_pending": include_pending,
            "graphs": None if selected is None else sorted(g.value for g in selected),
            "query_engine": "pyoxigraph-indexed-patterns", "query_status": "complete",
            "reviewed_quads": len(reviewed), "pending_targets": len(pending),
            "review_materialization": "global_O(total_store)", "evidence_quads": 0,
            "resource_scope": "scan_limit bounds targeted distinct quad reads, not global review or native memory",
            "scope": "Exact IRI discovery only; no scientific compatibility, admission or publication inferred."}
        try:
            facts = sorted((f for d in sorted(projects, key=str)
                for f in reader.project_facts(d, families, include_pending)), key=str)
            matches, seen = [], set()
            for dataset, family, obj, subject, predicate in facts:
                membership = reader.memberships(subject, family).get(dataset)
                if membership is None:
                    continue
                for other_subject, other_predicate in reader.candidates(family, obj, include_pending):
                    for other, other_membership in sorted(reader.memberships(other_subject, family).items(), key=lambda row: str(row[0])):
                        if other in projects:
                            continue
                        key = (dataset, family, obj, subject, other, other_subject, predicate, other_predicate)
                        if key in seen:
                            continue
                        seen.add(key)
                        matches.append((dataset, family, obj, subject, predicate, membership,
                                        other, other_subject, other_predicate, other_membership))
                        if len(matches) > limit:
                            break
                    if len(matches) > limit:
                        break
                if len(matches) > limit:
                    break
            response["has_more"] = len(matches) > limit
            proof = _Proof(reader)
            for dataset, family, obj, subject, predicate, membership, other, other_subject, other_predicate, other_membership in matches[:limit]:
                proof.node(dataset); proof.node(other)
                for edge in [(subject, predicate, obj), (other_subject, other_predicate, obj), *membership, *other_membership]:
                    proof.edge(*edge)
                if family == "population":
                    proof.node(obj)
            evidence = _Evidence(proof.quads, pending, selected)
            response["evidence_quads"] = len(proof.quads)
            for dataset, family, obj, subject, predicate, membership, other, other_subject, other_predicate, other_membership in matches[:limit]:
                edge = {**evidence.edge(subject, predicate, obj),
                        "membership": [evidence.edge(*triple) for triple in membership]}
                candidate = {**evidence.edge(other_subject, other_predicate, obj),
                             "membership": [evidence.edge(*triple) for triple in other_membership]}
                if family == "population":
                    types = sorted(v.value for v in reader.population_types(obj))
                    edge["identity_types"] = candidate["identity_types"] = types
                is_pending = not edge["asserted"] or not candidate["asserted"]
                response["paths"].append({"project_dataset": dataset.value, "dataset": other.value,
                    "family": family, "shared_iri": obj.value, "match": "exact_iri",
                    "path_state": "awaiting_review" if is_pending else "asserted",
                    "project": edge, "candidate": candidate,
                    "project_source": evidence.source(dataset), "candidate_source": evidence.source(other)})
        except _ReadLimit as exc:
            response.update(paths=[], has_more=True, scan_truncated=True,
                            query_status="partial_evidence_refused", partial_reason=str(exc), evidence_quads=0)
        response["scanned_quads"] = min(len(reader.visited), MAX_SCAN_QUADS)
        response["read_pattern_count"] = min(reader.pattern_count, MAX_READ_PATTERNS)
        return response
    finally:
        del original
