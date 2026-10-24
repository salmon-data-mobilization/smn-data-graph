"""Local SHACL gate for the bounded corpus structural contract.

The build fails on a violation (ADR-0001 D7). pyshacl 0.40.1 runs on rdflib,
which cannot read RDF 1.2 triple terms, so before validation every quad
``?r rdf:reifies <<( s p o )>>`` is rewritten as
``?r rdf:reifies "<N-Triples of s p o>"`` (a plain literal). Shapes can then
target reifiers with ``sh:targetSubjectsOf rdf:reifies`` and check the
reifier's own properties; they never see inside the triple term
(architecture.md section 10). No other quad is changed.

Validation runs over the union of the given named graphs (default: all),
because a shape on an observation needs the metadata graph's structure
definition. Each violation is reported with the named graph(s) that hold its
focus node.

The original-quad gate also checks required observation semantic slots using
live bindings or complete pending critical candidates, without asserting
shadow triples. Pending SPOs must not be live anywhere in the input,
even outside a selected SHACL union. RDF 1.2 and legacy RDF 1.1 reifiers are
recognized; malformed/unsupported encodings fail closed. This is structural
validation, not scientific approval, source-semantic inference, a vocabulary
pin check or release certification. Only local Turtle shapes are accepted;
remote imports, JavaScript and network-capable SPARQL clauses are refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import re
from typing import Iterable, Sequence

import pyoxigraph as ox

from . import config, provenance
from .graph import RDF_REIFIES
from .shapes import shape_files

_RDF = config.STATIC_NS["rdf"]
_QB = config.STATIC_NS["qb"]
_SOSA = config.STATIC_NS["sosa"]
_QUDT = config.STATIC_NS["qudt"]
_CSVW = config.STATIC_NS["csvw"]
_PROV = config.STATIC_NS["prov"]
_DCT = config.STATIC_NS["dcterms"]
_XSD = config.STATIC_NS["xsd"]
_SHAPE = "urn:salmongraph:validation:"
_NUMERIC = {"decimal", "float", "double", "integer", "int", "long", "short", "byte",
            "nonNegativeInteger", "positiveInteger", "nonPositiveInteger", "negativeInteger",
            "unsignedLong", "unsignedInt", "unsignedShort", "unsignedByte"}

__all__ = ["ShaclViolationError", "Violation", "ValidationReport", "for_shacl", "validate",
           "assert_valid"]


@dataclass(frozen=True)
class Violation:
    """One SHACL result."""

    focus: str
    path: str | None
    shape: str
    message: str
    severity: str                       # "Violation" | "Warning" | "Info"
    graphs: tuple[str, ...] = ()        # named graphs holding the focus node


@dataclass
class ValidationReport:
    """Outcome of :func:`validate`. ``conforms`` ignores Warning and Info results."""

    conforms: bool
    violations: list[Violation] = field(default_factory=list)   # sorted by (focus, shape, path)
    text: str = ""                                              # pyshacl's text report


class ShaclViolationError(RuntimeError):
    """Raised by :func:`assert_valid`; carries the report."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        count = sum(v.severity not in {"Warning", "Info"} for v in report.violations)
        super().__init__(f"{count} SHACL violation(s)")


def for_shacl(quads: Iterable["ox.Quad"]) -> list["ox.Quad"]:
    """The triple-term rewrite described in the module docstring (pure, deterministic)."""
    rewritten = []
    for q in quads:
        if q.predicate.value == RDF_REIFIES and isinstance(q.object, ox.Triple):
            q = ox.Quad(q.subject, q.predicate, ox.Literal(f"{q.object} ."), q.graph_name)
        rewritten.append(q)
    return sorted(rewritten, key=str)


def _name(term) -> str:
    return term.value if isinstance(term, ox.NamedNode) else str(term)


def _nodes(term):
    yield term
    if isinstance(term, ox.Triple):
        yield from _nodes(term.subject)
        yield term.predicate
        yield from _nodes(term.object)


def _violation(focus, shape, message, membership, path=None):
    return Violation(_name(focus), path, _SHAPE + shape, message, "Violation",
                     tuple(sorted(membership.get(focus, ()))))


def _original_gate(quads, selected, membership):
    """Inspect exact RDF terms, never strings containing quoted SPOs."""
    values, live = {}, set()
    for q in quads:
        values.setdefault((q.subject, q.predicate.value), set()).add(q.object)
        live.add((q.subject, q.predicate, q.object))
    selected_values = {}
    for q in selected:
        selected_values.setdefault((q.subject, q.predicate.value), set()).add(q.object)
    get = lambda s, p: values.get((s, p), set())
    local = lambda s, p: selected_values.get((s, p), set())
    T = provenance.terms()
    critical, pending = ox.NamedNode(T.values["critical"]), ox.NamedNode(T.values["awaitingReview"])
    reifiers = {q.subject for q in quads if q.predicate.value in
                {RDF_REIFIES, _RDF + "subject", _RDF + "predicate", _RDF + "object"}
                or (q.predicate.value == _RDF + "type" and q.object == ox.NamedNode(_RDF + "Statement"))}
    errors, candidates = [], {}
    for r in sorted(reifiers, key=str):
        triples = set()
        encoded = get(r, RDF_REIFIES)
        legacy = [get(r, _RDF + part) for part in ("subject", "predicate", "object")]
        bad = False
        if encoded:
            if len(encoded) != 1 or not all(isinstance(t, ox.Triple) for t in encoded):
                bad = True
            else:
                t = next(iter(encoded))
                if isinstance(t.subject, ox.Triple) or isinstance(t.object, ox.Triple):
                    bad = True
                else:
                    triples.add((t.subject, t.predicate, t.object))
        if any(legacy):
            if any(len(v) != 1 for v in legacy):
                bad = True
            else:
                s, p, o = (next(iter(v)) for v in legacy)
                if not isinstance(s, (ox.NamedNode, ox.BlankNode)) or not isinstance(p, ox.NamedNode) or isinstance(o, ox.Triple):
                    bad = True
                else:
                    triples.add((s, p, o))
        if bad or len(triples) != 1:
            errors.append(_violation(r, "ReifierEncoding", "Expected one exact RDF 1.2 triple term or complete, unambiguous legacy RDF 1.1 statement.", membership))
            continue
        triple = next(iter(triples))
        is_pending = pending in get(r, T.review_status)
        if is_pending and triple in live:
            errors.append(_violation(r, "PendingStatement", "Pending SPO is asserted in an input graph; retain the candidate without a live assertion.", membership, triple[1].value))
        # Completeness only counts candidates with their explicit D6 evidence.
        confidence = local(r, T.confidence)
        activities = local(r, _PROV + "wasGeneratedBy")
        agents = local(r, _PROV + "wasAttributedTo")
        evidence = local(r, _PROV + "wasDerivedFrom")
        dated = (len(activities) == 1 and all(isinstance(a, ox.NamedNode) for a in activities)
                 and all(len(local(a, _DCT + "date")) == 1
                         and all(isinstance(d, ox.Literal) and d.datatype.value in
                                 {_XSD + "date", _XSD + "dateTime"} and _rdfterm(d).ill_typed is not True
                                 for d in local(a, _DCT + "date")) for a in activities))
        evidence_complete = bool(evidence) and all(
            isinstance(e, ox.NamedNode) or isinstance(e, ox.BlankNode)
            and ox.NamedNode(_PROV + "Entity") in local(e, _RDF + "type")
            and bool(local(e, _PROV + "value"))
            and all(isinstance(v, ox.Literal) and v.datatype.value == _XSD + "string"
                    and v.value.strip() for v in local(e, _PROV + "value")) for e in evidence)
        complete = (local(r, T.criticality) == {critical} and local(r, T.review_status) == {pending}
                    and (bool(local(r, RDF_REIFIES)) or all(local(r, _RDF + part) for part in ("subject", "predicate", "object")))
                    and len(confidence) == 1
                    and confidence <= {ox.NamedNode(T.values[c]) for c in provenance.CONFIDENCE_LEVELS}
                    and bool(agents) and all(isinstance(a, ox.NamedNode) for a in agents)
                    and evidence_complete and dated)
        if complete:
            candidates.setdefault((triple[0], triple[1].value), set()).add(triple[2])
    def bindings(s, p):
        return local(s, p) | candidates.get((s, p), set())
    for q in selected:
        if q.predicate.value in {_SOSA + "hasSimpleResult", _QUDT + "standardUncertainty"}:
            try:
                numeric = (isinstance(q.object, ox.Literal)
                           and q.object.datatype.value in {_XSD + name for name in _NUMERIC}
                           and math.isfinite(float(q.object.value)))
            except ValueError:
                numeric = False
            if not numeric:
                errors.append(_violation(q.subject, "NumericLiteral", "Expected a finite numeric literal.", membership, q.predicate.value))
    observations = {q.subject for q in selected if q.predicate.value == _RDF + "type"
                    and q.object in {ox.NamedNode(_QB + "Observation"), ox.NamedNode(_SOSA + "Observation")}}
    year_predicates = {config.SMN_NS + "broodYear", config.SMN_NS + "returnYear"}
    def year_literal(value):
        return (isinstance(value, ox.Literal) and value.datatype.value == _XSD + "gYear"
                and _rdfterm(value).ill_typed is not True)
    for obs in sorted(observations, key=str):
        columns = local(obs, _SOSA + "observedProperty")
        if len(columns) != 1 or not all(isinstance(c, ox.NamedNode) for c in columns):
            continue  # The live source-column relationship has a SHACL min/max gate.
        column = next(iter(columns))
        for predicate in (_QB + "concept", _QUDT + "unit"):
            bound = bindings(column, predicate)
            if len(bound) != 1 or not all(isinstance(v, ox.NamedNode) for v in bound):
                errors.append(_violation(column, "ObservationSemanticSlot", "Source measure column needs one IRI binding, live or a complete pending critical candidate.", membership, predicate))
        obs_units, column_units = local(obs, _QUDT + "unit"), local(column, _QUDT + "unit")
        if obs_units and (not column_units or obs_units != column_units):
            errors.append(_violation(obs, "ObservationUnitDependency", "Observation unit must agree with a live source-column unit; pending column semantics must not be materialized.", membership, _QUDT + "unit"))
        seen_year_components = set()
        for dataset in local(obs, _QB + "dataSet"):
            structures = local(dataset, _QB + "structure")
            if len(structures) != 1 or not all(isinstance(s, ox.NamedNode) for s in structures):
                errors.append(_violation(obs, "ObservationStructure", "Observation dataset must have exactly one explicit data structure.", membership, _QB + "structure"))
            for structure in structures:
                components = local(structure, _QB + "component")
                measures = {m for component in components for m in local(component, _QB + "measure")}
                if measures != {column}:
                    errors.append(_violation(obs, "ObservationMeasureStructure", "Data structure must name this observation's source measure column exactly once.", membership, _QB + "measure"))
                for component in components:
                    for attribute in local(component, _QB + "attribute"):
                        required = local(component, _QB + "componentRequired")
                        bound = bindings(obs, attribute.value) if isinstance(attribute, ox.NamedNode) else set()
                        optional = required == {ox.Literal(False)}
                        if (required not in ({ox.Literal(False)}, {ox.Literal(True)})
                                or len(bound) > 1 or not all(isinstance(v, (ox.NamedNode, ox.Literal)) for v in bound)
                                or not optional and not bound):
                            errors.append(_violation(obs, "ObservationAttribute", "Source attribute needs an explicit componentRequired flag and at most one scalar value; a required attribute cannot be missing.", membership, _name(attribute)))
                    dimensions = bindings(component, _QB + "dimension")
                    if any(isinstance(d, ox.NamedNode) and d.value in year_predicates for d in dimensions) and len(dimensions) != 1:
                        errors.append(_violation(obs, "ObservationYearStructure", "Year component has conflicting basis bindings.", membership))
                    for dimension in dimensions:
                        if isinstance(dimension, ox.NamedNode) and dimension.value in year_predicates:
                            seen_year_components.add(component)
                            derived = local(component, _PROV + "wasDerivedFrom")
                            year_columns = {c for c in derived if isinstance(c, ox.NamedNode) and c != column and
                                            ox.NamedNode(_CSVW + "Column") in local(c, _RDF + "type")}
                            if (column not in derived or component not in local(obs, _PROV + "wasDerivedFrom")
                                    or len(year_columns) != 1):
                                errors.append(_violation(obs, "ObservationYearTrace", "Year component must trace this measure column and one source year column, and be an observation dependency.", membership))
                                continue
                            source_year = next(iter(year_columns))
                            raw_years = local(obs, source_year.value)
                            if len(raw_years) != 1 or not all(year_literal(v) for v in raw_years):
                                errors.append(_violation(obs, "ObservationYear", "Expected one factual source-year-column gYear value.", membership, source_year.value))
                            canonical = local(obs, dimension.value)
                            live_binding = dimension in local(component, _QB + "dimension")
                            if (live_binding and canonical != raw_years) or (not live_binding and canonical):
                                errors.append(_violation(obs, "ObservationYearDependency", "Canonical year may only follow a live component binding and must match the factual source year.", membership, dimension.value))
                        elif not isinstance(dimension, ox.NamedNode) or len(bindings(obs, dimension.value)) != 1:
                            errors.append(_violation(obs, "ObservationDimension", "Observation is missing a dimension declared by its data structure.", membership, _name(dimension)))
        if len(seen_year_components) != 1:
            errors.append(_violation(obs, "ObservationYearStructure", "Expected exactly one measure-specific year component with a live or complete pending brood/return-year binding.", membership))
    return errors


def _rdfterm(term):
    from rdflib import BNode, Literal, URIRef
    if isinstance(term, ox.NamedNode):
        return URIRef(term.value)
    if isinstance(term, ox.BlankNode):
        return BNode(term.value)
    if isinstance(term, ox.Literal):
        if term.direction is not None:
            raise ValueError("directional RDF 1.2 language literals are unsupported by the SHACL view")
        return Literal(term.value, lang=term.language, datatype=None if term.language else URIRef(term.datatype.value), normalize=False)
    raise ValueError("unsupported RDF term outside the documented rdf:reifies rewrite")


def _load_shapes(paths):
    from rdflib import Graph, Literal, URIRef
    from rdflib.compare import to_canonical_graph
    from rdflib.namespace import OWL, RDF, SH
    result = Graph()
    for path in sorted({Path(p) for p in paths}, key=str):
        if path.suffix != ".ttl" or not path.is_file():
            raise ValueError(f"missing local Turtle shape file: {path.name}")
        parsed = Graph().parse(data=path.read_text(encoding="utf-8"), format="turtle", publicID="urn:salmongraph:shapes:")
        replacements = {"urn:salmongraph:profile:": config.current().profile_base,
                        "urn:salmongraph:sdpv:": config.current().sdpv}
        def configured(term):
            if isinstance(term, (URIRef, Literal)):
                value = str(term)
                for before, after in replacements.items():
                    value = value.replace(before, after)
                return URIRef(value) if isinstance(term, URIRef) else Literal(value, lang=term.language, datatype=term.datatype, normalize=False)
            return term
        for s, p, o in parsed:
            if (p == OWL.imports or str(p).startswith(str(SH) + "js")
                    or isinstance(o, URIRef) and str(o).startswith(str(SH) + "JS")):
                raise ValueError("shape imports and JavaScript are disabled")
            if p in {SH.rule, SH.target, SH.entailment}:
                raise ValueError("advanced SHACL rules, custom targets and entailment are unsupported")
            if p in (SH.select, SH.ask, SH.construct) and re.search(r"\b(SERVICE|FROM|LOAD)\b", str(o), re.I):
                raise ValueError("network-capable SPARQL clauses are disabled")
            result.add(tuple(configured(t) for t in (s, p, o)))
    if not any(result.subjects(RDF.type, SH.NodeShape)) and not any(result.subjects(RDF.type, SH.PropertyShape)):
        raise ValueError("shape set contains no declared SHACL node/property shapes")
    if not any(str(p).startswith(str(SH)) and p not in {SH.targetNode, SH.targetClass,
            SH.targetSubjectsOf, SH.targetObjectsOf, SH.name, SH.description, SH.message, SH.severity,
            SH.deactivated, SH.path} for _, p, _ in result):
        raise ValueError("shape set contains no SHACL constraints")
    canonical = Graph()
    for triple in to_canonical_graph(result):
        canonical.add(triple)
    return canonical


def validate(data: "Iterable[ox.Quad] | ox.Store", *, shapes: Sequence[Path] | None = None,
             graphs: Sequence[str] | None = None) -> ValidationReport:
    """Validate ``data`` (quads or a store) against ``shapes`` (default ``shapes.shape_files()``)."""
    from rdflib import Graph
    from rdflib.namespace import RDF, SH
    import pyshacl
    quads = sorted(set(data), key=str)
    if not all(isinstance(q, ox.Quad) for q in quads):
        raise TypeError("validation input must contain pyoxigraph quads")
    available = {q.graph_name.value for q in quads if isinstance(q.graph_name, ox.NamedNode)}
    selected_names = available if graphs is None else set(graphs)
    selected = [q for q in quads if isinstance(q.graph_name, ox.NamedNode) and q.graph_name.value in selected_names]
    membership = {}
    for q in quads:
        graph = _name(q.graph_name) if not isinstance(q.graph_name, ox.DefaultGraph) else "(default)"
        for node in (*_nodes(q.subject), q.predicate, *_nodes(q.object)):
            membership.setdefault(node, set()).add(graph)
    violations = _original_gate(quads, selected, membership)
    for missing in sorted(selected_names - available):
        violations.append(Violation(missing, None, _SHAPE + "GraphSelection", "Requested named graph is absent.", "Violation"))
    for unsupported in sorted({q.graph_name for q in quads if not isinstance(q.graph_name, ox.NamedNode)}, key=str):
        violations.append(Violation(_name(unsupported), None, _SHAPE + "NamedGraphs", "Corpus validation requires IRI named graphs; default/blank-node graph names are unsupported.", "Violation"))
    try:
        paths = shape_files() if shapes is None else list(shapes)
        if not paths:
            raise ValueError("empty SHACL shape set is not a validation gate")
        shapes_graph = _load_shapes(paths)
        graph = Graph()
        graph_membership = {}
        for node, names in membership.items():
            if not isinstance(node, ox.Triple):
                graph_membership[_rdfterm(node)] = tuple(sorted(names))
        for q in for_shacl(selected):
            graph.add((_rdfterm(q.subject), _rdfterm(q.predicate), _rdfterm(q.object)))
        engine_conforms, report_graph, _ = pyshacl.validate(graph, shacl_graph=shapes_graph, advanced=False,
                inference="none", inplace=False, abort_on_first=False, allow_infos=True,
                allow_warnings=True, do_owl_imports=False, js=False, sparql_mode=False)
        if not isinstance(report_graph, Graph):
            raise ValueError("SHACL engine returned no result graph")
        if not engine_conforms and not any(report_graph.subjects(RDF.type, SH.ValidationResult)):
            raise ValueError("SHACL engine failed without validation results")
        for result in report_graph.subjects(RDF.type, SH.ValidationResult):
            focus = report_graph.value(result, SH.focusNode)
            path = report_graph.value(result, SH.resultPath)
            shape = report_graph.value(result, SH.sourceShape)
            severity = str(report_graph.value(result, SH.resultSeverity)).rsplit("#", 1)[-1]
            messages = sorted(str(m) for m in report_graph.objects(result, SH.resultMessage))
            violations.append(Violation(str(focus), str(path) if path is not None else None, str(shape),
                              " | ".join(messages), severity, graph_membership.get(focus, ())))
    except Exception as exc:
        # Missing/malformed/unsupported shapes or RDF must never look conformant.
        violations.append(Violation("", None, _SHAPE + "ValidationInput", f"Validation could not run: {type(exc).__name__}: {exc}", "Violation"))
    violations = sorted(set(violations), key=lambda v: (v.focus, v.shape, v.path or "", v.message, v.severity, v.graphs))
    conforms = not any(v.severity not in {"Info", "Warning"} for v in violations)
    text = f"Bounded structural SHACL validation: conforms={conforms}; selected_named_graphs={len(selected_names)}; selected_quads={len(selected)}\n"
    text += "\n".join(f"{v.severity}: {v.focus} [{v.shape}] {v.path or ''} {v.message}" for v in violations)
    return ValidationReport(conforms, violations, text)


def assert_valid(data: "Iterable[ox.Quad] | ox.Store", *, shapes: Sequence[Path] | None = None,
                 graphs: Sequence[str] | None = None) -> ValidationReport:
    """:func:`validate`, raising :class:`ShaclViolationError` unless it conforms."""
    report = validate(data, shapes=shapes, graphs=graphs)
    if not report.conforms:
        raise ShaclViolationError(report)
    return report
