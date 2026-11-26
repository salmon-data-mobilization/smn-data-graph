"""Test a mapping decision register against an exported RDF profile and draw a reproducible review sample."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from rdflib import Graph, URIRef


def rank(seed, dataset, identifier):
    return hashlib.sha256(f"{seed}\n{dataset}\n{identifier}".encode()).hexdigest()


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
        values = [record[k] for k in ("subject", "predicate", "object")]
        if not all(re.fullmatch(r"[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>]+", s) for s in values):
            raise ValueError(f"{identifier} needs three absolute IRIs")
        triple = tuple(URIRef(s) for s in values)
        if triple in triples:
            raise ValueError(f"Repeated RDF proposition at {identifier}")
        triples.add(triple)
        known_subject = any(graph.predicate_objects(triple[0]))
        asserted = triple in graph
        result = {"id": identifier, "status": status, "subject_present": known_subject, "triple_present": asserted,
                  "matches_export": known_subject and asserted == (status == "accepted")}
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
    parser.add_argument("register", type=Path)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--per-status", type=int, default=2)
    args = parser.parse_args()
    graph = Graph().parse(args.profile, format="turtle")
    try:
        result = check_decisions(graph, json.loads(args.register.read_text()), args.dataset, args.seed, args.per_status)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(result, indent=2))
    return int(not result["matches_export"])


if __name__ == "__main__":
    raise SystemExit(main())
