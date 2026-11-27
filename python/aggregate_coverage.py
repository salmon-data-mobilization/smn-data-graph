"""Audit one pair of published additive estimates against an explicit atom partition."""

import argparse
import json
import re
import sys
from collections import defaultdict
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from rdflib import BNode, Dataset, Literal, Namespace, RDF, URIRef, XSD


COV = Namespace("urn:smn:aggregate-audit:")
QUERY = Path(__file__).with_suffix(".rq")
UNKNOWN = {"unknown", "unresolved", "unspecified", "na", "n/a"}
DIMENSIONS = ("frame", "species", "year", "measure", "unit", "statistic")
# Free-text evidence may contain a source locator; an explicit locator field
# also supports publisher-specific location schemes.
LOCATOR = re.compile(
    r"\b(table|tab\.|appendix|figure|fig\.|row|column|cell|line|record|page|"
    r"sheet|field|section|variable|xpath|jsonpath|feature|id|key)\b\s*[:#=]?\s*\S"
    r"|\bp{1,2}\.\s*\d|#(?:page=|L)\d|\w+\.(?:csv|tsv|xlsx|parquet)\b.*[=:]",
    re.I,
)


def need(condition, message):
    if not condition:
        raise ValueError(message)


def string(value, label):
    need(isinstance(value, str) and value.strip(), f"{label} requires nonempty text")
    return value.strip()


def iri(value):
    value = string(value, "IRI")
    need(re.fullmatch(r'[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>"{}|\\^`]+', value),
         f"invalid absolute IRI: {value!r}")
    return URIRef(value)


def array(parent, name):
    value = parent.get(name)
    need(isinstance(value, list), f"{name} requires an array")
    return value


def flag(obj, name):
    value = obj.get(name)
    need(type(value) is bool, f"{name} requires true or false")
    return value


def quantity(value):
    need(type(value) is int or (isinstance(value, str) and
         re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value)), "use integers or exact nonnegative decimal strings")
    result = Decimal(value)
    need(result >= 0, "counts must be nonnegative")
    return result


def display(value):
    """Render sums of finite base-ten decimals exactly, including trailing units."""
    if value.denominator == 1:
        return value.numerator
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    places = max(twos, fives)
    digits = str(value.numerator * 2 ** (places - twos) * 5 ** (places - fives)).zfill(places + 1)
    return f"{digits[:-places]}.{digits[-places:]}"


def evidence(obj, label, issues):
    text = obj.get("evidence")
    locator = obj.get("locator")
    if not isinstance(text, str) or not text.strip():
        issues.append(f"{label}: missing source evidence")
        return ""
    if isinstance(locator, str) and locator.strip():
        return f"{text} | {locator}"
    if not LOCATOR.search(text):
        issues.append(f"{label}: missing source locator")
        return ""
    return text


def write_dimensions(graph, subject, obj):
    for key in DIMENSIONS:
        value = obj.get(key)
        if key == "frame":
            node = iri(value)
        elif key == "year":
            need(type(value) is int, "year requires an integer return year")
            node = Literal(value)
        else:
            node = Literal(string(value, key))
        graph.add((subject, COV[key], node))


def build_dataset(payload, issues):
    target = payload["target"]
    sources = array(payload, "sources")
    need(len(sources) == 2, "exactly two published totals are required")
    dataset = Dataset()
    dataset.bind("cov", COV)
    scope = dataset.graph(COV.target)
    frame = iri(target["frame"])
    write_dimensions(scope, COV.target, target)
    frame_evidence = evidence(target, "target", issues)
    scope.add((frame, COV.evidence, Literal(frame_evidence)))
    target_atoms = [iri(a) for a in array(target, "atoms")]
    need(len(set(target_atoms)) == len(target_atoms), "duplicate target atom")
    complete_target = flag(target, "complete") if "complete" in target else True
    scope.add((frame, COV.complete, Literal(complete_target)))
    if not complete_target:
        issues.append("target: incomplete atomic partition")
    if not target_atoms:
        issues.append("target: missing atomic roster")
    aliases = {iri(a): iri(b) for a, b in target.get("aliases", {}).items()}
    need(all(a != b and b in target_atoms and a not in target_atoms for a, b in aliases.items()),
         "alias must map an alternate ID directly to a canonical target atom")
    for alias, atom in aliases.items():
        scope.add((alias, COV.aliasOf, atom))
    parents = set()
    for name, children in target.get("contains", {}).items():
        parent = iri(name)
        parents.add(aliases.get(parent, parent))
        need(isinstance(children, list) and children, "containment needs children")
        for child in children:
            scope.add((parent, COV.contains, iri(child)))
    for atom in target_atoms:
        if atom in parents:
            issues.append(f"target: nested aggregate declared as atom: {atom}")
        elif frame_evidence:
            scope.add((frame, COV.approvedAtom, atom))

    names = set()
    for source in sources:
        name = iri(source["graph"])
        need(name not in names and name != COV.target, "two distinct source graph IRIs are required")
        names.add(name)
        g = dataset.graph(name)
        g.add((name, RDF.type, COV.Source))
        write_dimensions(g, name, source)
        edition = string(source.get("version"), "source version")
        if edition.lower() in UNKNOWN:
            issues.append(f"{name}: unknown source edition")
        g.add((name, COV.version, Literal(edition)))
        g.add((name, COV.evidence, Literal(evidence(source, name, issues))))
        g.add((name, COV.reported, Literal(quantity(source["reported"]), datatype=XSD.decimal)))
        complete = flag(source, "complete")
        g.add((name, COV.complete, Literal(complete)))
        if not complete:
            issues.append(f"{name}: incomplete published roster")
        # A missing row cannot prove that the publisher excluded a stream.
        # Keep positively documented exclusions in the source's edition graph.
        if "exclusions" in source:
            for exclusion in array(source, "exclusions"):
                original = iri(exclusion["id"])
                atom = aliases.get(original, original)
                need(atom in target_atoms and atom not in parents, "exclusion must identify a target atom")
                proof = evidence(exclusion, f"{name}/exclusion/{atom}", issues)
                if proof:
                    assertion = BNode()
                    g.add((name, COV.exclusion, assertion))
                    g.add((assertion, COV.atom, atom))
                    g.add((assertion, COV.sourceAtom, original))
                    g.add((assertion, COV.evidence, Literal(proof)))
        if not array(source, "components"):
            issues.append(f"{name}: missing component roster")
        seen = set()
        for component in source["components"]:
            key = string(component.get("id"), "component id")
            need(key not in seen, f"{name}: duplicate component ID {key}")
            seen.add(key)
            member = BNode()
            g.add((name, COV.component, member))
            g.add((member, COV.localId, Literal(key)))
            source_evidence = evidence(component, f"{name}/{key}", issues)
            g.add((member, COV.evidence, Literal(source_evidence)))
            resolved = flag(component, "resolved") and bool(source_evidence)
            g.add((member, COV.resolved, Literal(resolved)))
            if not resolved or not array(component, "atoms"):
                issues.append(f"{name}/{key}: unresolved atomic coverage")
            for atom in component["atoms"]:
                original = iri(atom["id"])
                canonical = aliases.get(original, original)
                if canonical in parents or canonical not in target_atoms:
                    issues.append(f"{name}/{key}: non-atomic or out-of-target coverage {canonical}")
                role = string(atom.get("role"), "role")
                need(role in {"direct", "represented"}, "role must be direct or represented")
                support = BNode()
                g.add((member, COV.support, support))
                g.add((support, COV.sourceAtom, original))
                g.add((support, COV.atom, canonical))
                g.add((support, COV.role, Literal(role)))
                if atom.get("value") is not None:
                    g.add((support, COV.value, Literal(quantity(atom["value"]), datatype=XSD.decimal)))
                if atom.get("version") is not None:
                    version = string(atom["version"], "atom estimate version")
                    if version.lower() not in UNKNOWN:
                        g.add((support, COV.version, Literal(version)))
    return dataset


def assess(payload, trig=None):
    issues = []
    dataset = build_dataset(payload, issues)
    if trig is not None:
        dataset.serialize(destination=trig, format="trig")
    scope = dataset.graph(COV.target)
    frame = scope.value(COV.target, COV.frame)
    expected = set(scope.objects(frame, COV.approvedAtom))
    coverage_issues = bool(issues)
    if str(scope.value(COV.target, COV.statistic)) != "sum":
        issues.append("target statistic is not an additive sum")
    by_graph = defaultdict(lambda: defaultdict(list))
    shared = set()
    # The RDF query joins by the approved canonical atom, stock frame, species
    # and return year, independently of the reported value or its version.
    for row in dataset.query(QUERY.read_text()):
        by_graph[row.graph][row.atom].append(row)
        if row.otherGraph is not None:
            shared.add(row.atom)

    reports = []
    observed = set()
    values = defaultdict(list)
    for source in payload["sources"]:
        name = iri(source["graph"])
        g = dataset.graph(name)
        for key in DIMENSIONS:
            if g.value(name, COV[key]) != scope.value(COV.target, COV[key]):
                issues.append(f"{name}: target {key} differs")
                if key in {"frame", "species", "year"}:
                    coverage_issues = True
        rows = by_graph[name]
        observed.update(rows)
        subtotal = Fraction()
        documented = []
        placements = sum(len(v) for v in rows.values())
        # A local total can be reconciled only if all its placement records
        # participated, including every declared represented atom.
        complete = g.value(name, COV.complete).toPython() and bool(rows)
        complete &= placements == sum(1 for _ in g.subject_objects(COV.support))
        for member in g.objects(name, COV.component):
            complete &= g.value(member, COV.resolved).toPython() and bool(list(g.objects(member, COV.support)))
        for atom, entries in sorted(rows.items()):
            if len(entries) > 1:
                issues.append(f"{name}: repeated atom within published roster: {atom}")
                complete = False
            for entry in entries:
                amount = entry.value.toPython() if entry.value is not None else None
                version = str(entry.version) if entry.version is not None else None
                documented.append({"id": str(atom), "component": str(g.value(entry.component, COV.localId)),
                                   "role": str(entry.role), "value": str(amount) if amount is not None else None,
                                   "version": version})
                if amount is None:
                    issues.append(f"{name}: missing value for {atom}")
                    complete = False
                else:
                    subtotal += Fraction(amount)
                values[atom].append((amount, version))
        reported = Fraction(g.value(name, COV.reported).toPython())
        reconciled = complete and subtotal == reported
        if not reconciled:
            issues.append(f"{name}: published total could not be reconciled")
        reports.append({"graph": str(name), "version": source["version"], "reported": display(reported),
                        "component_sum": display(subtotal) if complete else None,
                        "reconciled": bool(reconciled), "memberships": documented})

    # Exclusivity needs both positive membership and the other source's
    # independently documented exclusion. Preserve these witnesses even when
    # additional streams or the amounts they contributed are unknown.
    names = [iri(source["graph"]) for source in payload["sources"]]
    excluded = {}
    comparable = True
    for name in names:
        g = dataset.graph(name)
        excluded[name] = {g.value(node, COV.atom) for node in g.objects(name, COV.exclusion)}
        conflicts = excluded[name].intersection(by_graph[name])
        if conflicts:
            issues.append(f"{name}: inclusion contradicts exclusion for {', '.join(map(str, sorted(conflicts)))}")
            comparable = False
        comparable &= all(g.value(name, COV[k]) == scope.value(COV.target, COV[k])
                          for k in ("year", "species", "frame"))
        comparable &= bool(str(g.value(name, COV.evidence))) and str(g.value(name, COV.version)).lower() not in UNKNOWN
    if not comparable:
        shared.clear()
        coverage_issues = True
    exclusive = {str(name): sorted(map(str, excluded[other].intersection(by_graph[name]))) if comparable else []
                 for name, other in ((names[0], names[1]), (names[1], names[0]))}

    if expected != observed:
        issues.append("target roster differs from covered union")
        coverage_issues = True
    for atom in sorted(shared):
        entries = values[atom]
        revisions = {version for _, version in entries}
        if None in revisions or len(revisions) != 1:
            issues.append(f"shared atom has unresolved or differing estimate versions: {atom}")
        if len({value for value, _ in entries}) != 1:
            issues.append(f"shared atom has differing estimates: {atom}")

    issues = sorted(set(issues))
    union_value = None
    decision = "withhold"
    if not issues:
        decision = "rebuild_union" if shared else "add_totals"
        # A key identifies a component in the accounting partition; two distinct
        # keys with equal amounts both contribute exactly once.
        union_value = display(sum((Fraction(v[0][0]) for v in values.values()), Fraction()))
    status = "overlap_demonstrated" if shared else ("unresolved" if coverage_issues else "disjoint")
    return {"decision": decision, "coverage_status": status, "directly_addable": decision == "add_totals",
            "union_value": union_value, "shared_atoms": sorted(map(str, shared)),
            "exclusive_witnesses": exclusive, "partial_overlap_proven": bool(shared and all(exclusive.values())),
            "sources": reports,
            "issues": issues}


def unique_keys(pairs):
    result = {}
    for key, val in pairs:
        need(key not in result, f"duplicate JSON field {key!r}")
        result[key] = val
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--trig", type=Path, help="write the named-graph evidence for inspection")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(), object_pairs_hook=unique_keys)
        result = assess(data, args.trig)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        parser.exit(2, f"invalid coverage input: {exc}\n")
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
