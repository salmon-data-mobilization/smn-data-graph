"""Look up a stream's documented roles for an exact product, method and return year."""

import argparse
from collections import defaultdict
import json
from pathlib import Path


VERSION = 1
SCOPE = ("stream", "signal", "series", "edition", "method")
ROLES = ("monitoring", "estimator_input", "standalone_subset")
CLAIM_FIELDS = {*SCOPE, "first_year", "last_year", "role", "assertion", "evidence"}
QUERY_FIELDS = {*SCOPE, "return_year"}


def check_fields(record, expected, label):
    if not isinstance(record, dict) or set(record) != expected:
        raise ValueError(f"{label} must have exactly these fields: {', '.join(sorted(expected))}")


def records(document, name):
    check_fields(document, {"version", name}, f"{name} document")
    if type(document["version"]) is not int or document["version"] != VERSION:
        raise ValueError(f"{name} requires integer version {VERSION}")
    if not isinstance(document[name], list):
        raise ValueError(f"{name} must be a JSON array")
    return document[name]


def scope(record, fields, label):
    check_fields(record, fields, label)
    for field in SCOPE:
        value = record[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label}.{field} requires a nonempty string")
    return tuple(record[field] for field in SCOPE)


def year(record, field, label):
    value = record[field]
    if type(value) is not int:
        raise ValueError(f"{label}.{field} requires an integer return year")
    return value


def index_claims(document):
    by_scope = defaultdict(list)
    for position, claim in enumerate(records(document, "claims")):
        label = f"claims[{position}]"
        key = scope(claim, CLAIM_FIELDS, label)
        first = year(claim, "first_year", label)
        last = year(claim, "last_year", label)
        if first > last:
            raise ValueError(f"{label}.first_year exceeds last_year")
        if claim["role"] not in ROLES or claim["assertion"] not in ("include", "exclude"):
            raise ValueError(f"{label} has an unknown role or assertion")
        if not isinstance(claim["evidence"], str) or not claim["evidence"].strip():
            raise ValueError(f"{label}.evidence requires a nonempty source locator")
        by_scope[key].append(claim)
    return by_scope


def resolve(claims, return_year):
    evidence = {role: {"include": set(), "exclude": set()} for role in ROLES}
    for claim in claims:
        if claim["first_year"] <= return_year <= claim["last_year"]:
            evidence[claim["role"]][claim["assertion"]].add(claim["evidence"])

    roles = {}
    for role, assertions in evidence.items():
        included, excluded = assertions["include"], assertions["exclude"]
        if included and excluded:
            status = "contradiction"
        elif included:
            status = "supported"
        elif excluded:
            status = "excluded"
        else:
            status = "abstain"
        roles[role] = {
            "status": status,
            "include_evidence": sorted(included),
            "exclude_evidence": sorted(excluded),
        }
    return roles


def audit(claims_document, queries_document):
    indexed = index_claims(claims_document)
    results = []
    for position, query in enumerate(records(queries_document, "queries")):
        label = f"queries[{position}]"
        key = scope(query, QUERY_FIELDS, label)
        return_year = year(query, "return_year", label)
        results.append({"query": query, "roles": resolve(indexed.get(key, ()), return_year)})
    return {"version": VERSION, "results": results}


def unique_fields(pairs):
    record = {}
    for name, value in pairs:
        if name in record:
            raise ValueError(f"Duplicate JSON field {name!r}")
        record[name] = value
    return record


def read_document(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=unique_fields)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("claims", type=Path, help="Versioned JSON register of evidence-backed role assertions")
    parser.add_argument("queries", type=Path, help="Versioned JSON batch of exact return-year queries")
    args = parser.parse_args()
    try:
        result = audit(read_document(args.claims), read_document(args.queries))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Scoped role lookup failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
