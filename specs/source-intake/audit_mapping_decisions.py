"""Test a mapping decision register against an exported RDF profile and draw a reproducible review sample."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDFS, SKOS


def rank(seed, dataset, identifier):
    return hashlib.sha256(f"{seed}\n{dataset}\n{identifier}".encode()).hexdigest()


def foreign_labels(graph, owned_namespaces):
    """Find labels the profile assigns to terms owned by another vocabulary."""
    labels = []
    for predicate in (RDFS.label, SKOS.prefLabel, SKOS.altLabel, SKOS.hiddenLabel):
        for subject, value in graph.subject_objects(predicate):
            if isinstance(subject, URIRef) and not str(subject).startswith(tuple(owned_namespaces)):
                labels.append({"subject": str(subject), "predicate": str(predicate), "value": value.n3()})
    return sorted(labels, key=lambda row: (row["subject"], row["predicate"], row["value"]))


def iri(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>]+", value):
        raise ValueError(f"Expected an absolute IRI, received {value!r}")
    return URIRef(value)


def check_triple(graph, triple, expected):
    known_subject = any(graph.predicate_objects(triple[0]))
    asserted = triple in graph
    return {"subject_present": known_subject, "triple_present": asserted, "matches_export": known_subject and asserted == expected}


def check_scope(graph, rules):
    """Check independently specified triples, including single-scope restrictions."""
    if not isinstance(rules, list) or not rules:
        raise ValueError("Supply a nonempty array of scope propositions")
    checked = []
    identifiers = set()
    triples = set()
    for rule in rules:
        required_fields = {"id", "expect", "subject", "predicate", "object"}
        if not isinstance(rule, dict) or not required_fields <= rule.keys() or rule.keys() - required_fields - {"only_subject", "only_object"}:
            raise ValueError("Unknown or missing scope proposition fields")
        identifier, expect = rule["id"], rule["expect"]
        if not isinstance(identifier, str) or not identifier.strip() or identifier in identifiers or expect not in ("required", "forbidden"):
            raise ValueError("Expected a unique nonempty id and required or forbidden expectation")
        identifiers.add(identifier)
        for flag in ("only_subject", "only_object"):
            if flag in rule and (not isinstance(rule[flag], bool) or expect != "required"):
                raise ValueError(f"{flag} is a boolean option for a required proposition")
        value = rule["object"]
        if isinstance(value, dict):
            if set(value) != {"value", "datatype"} or not isinstance(value["value"], str):
                raise ValueError("A literal object needs a string value and an absolute datatype IRI")
            obj = Literal(value["value"], datatype=iri(value["datatype"]), normalize=False)
        else:
            obj = iri(value)
        subject, predicate = iri(rule["subject"]), iri(rule["predicate"])
        triple = subject, predicate, obj
        if triple in triples:
            raise ValueError(f"Repeated scope proposition at {identifier}")
        triples.add(triple)
        result = {**rule, **check_triple(graph, triple, expect == "required")}
        if rule.get("only_subject"):
            result["unexpected_subjects"] = sorted(s.n3() for s in graph.subjects(predicate, obj) if s != subject)
        if rule.get("only_object"):
            result["unexpected_objects"] = sorted(o.n3() for o in graph.objects(subject, predicate) if o != obj)
        if result.get("unexpected_subjects") or result.get("unexpected_objects"):
            result["matches_export"] = False
        checked.append(result)
    return {"checked": checked, "matches_export": all(row["matches_export"] for row in checked)}


def check_decisions(graph, records, dataset, seed, per_status):
    if not isinstance(records, list) or not records or per_status < 1:
        raise ValueError("Supply a nonempty decision array and a positive sample size")
    identifiers = set()
    triples = set()
    counts = Counter()
    results = []
    for record in records:
        for key in ("id", "status", "table", "claim", "source_url", "locator", "reason", "subject", "predicate", "object"):
            if not isinstance(record.get(key), str) or not record[key].strip():
                raise ValueError(f"Missing text in decision field {key}")
        identifier, status = record["id"], record["status"]
        if identifier in identifiers or status not in {"accepted", "abstained"}:
            raise ValueError(f"Duplicate identifier or unknown status for {identifier}")
        identifiers.add(identifier)
        triple = tuple(iri(record[k]) for k in ("subject", "predicate", "object"))
        if triple in triples:
            raise ValueError(f"Repeated RDF proposition at {identifier}")
        triples.add(triple)
        result = {"id": identifier, "status": status, **check_triple(graph, triple, status == "accepted")}
        counts[status] += 1
        results.append(result)
    selected = {}
    for status in ("accepted", "abstained"):
        if counts[status] < per_status:
            raise ValueError(f"Cannot draw {per_status} from {counts[status]} {status} decisions")
        ids = [r["id"] for r in results if r["status"] == status]
        selected[status] = sorted(ids, key=lambda i: (rank(seed, dataset, i), i))[:per_status]
    return {"dataset": dataset, "seed": seed, "population": dict(counts), "sample": selected,
            "checked": sorted(results, key=lambda r: r["id"]), "matches_export": all(r["matches_export"] for r in results)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("register", nargs="?", type=Path)
    parser.add_argument("--scope-propositions", type=Path, help="Independent required/forbidden triples for this exported profile")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--seed", help="Review sampling seed when a decision register is supplied")
    parser.add_argument("--per-status", type=int, default=2)
    parser.add_argument("--owned-namespace", action="append", help="Check for labels on external terms. Repeat for each namespace the profile owns.")
    args = parser.parse_args()
    if not args.register and not args.scope_propositions:
        parser.error("Supply a register, an independent scope contract, or both")
    if args.register and args.seed is None:
        parser.error("Supply --seed to sample a decision register")
    graph = Graph().parse(args.profile, format="turtle")
    try:
        result = {"dataset": args.dataset, "matches_export": True}
        if args.register:
            result = check_decisions(graph, json.loads(args.register.read_text()), args.dataset, args.seed, args.per_status)
        if args.scope_propositions:
            result["scope"] = check_scope(graph, json.loads(args.scope_propositions.read_text()))
            result["matches_export"] = result["matches_export"] and result["scope"]["matches_export"]
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.exit(2, f"{exc}\n")
    if args.owned_namespace:
        if not all(ns.endswith(("/", "#", ":")) for ns in args.owned_namespace):
            parser.error("An owned namespace must end with /, # or : to delimit its terms")
        result["foreign_labels"] = foreign_labels(graph, args.owned_namespace)
    print(json.dumps(result, indent=2))
    return int(not result["matches_export"] or bool(result.get("foreign_labels")))


if __name__ == "__main__":
    raise SystemExit(main())
