"""Compare a declared set of eligible fish to an independently enumerated candidate roster."""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re


def read_table(path, required):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        if len(set(headers)) != len(headers) or not set(required).issubset(headers):
            raise ValueError(f"{path.name}: missing or duplicate columns")
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"{path.name}:{line}: malformed row")
            yield row


def key_for(row, names):
    key = tuple(row[name] for name in names)
    if any(not part.strip() for part in key):
        raise ValueError(f"Empty identity or stratum field in {names}")
    return key


def audit(roster, selection, keys, strata, outcome, missing):
    if not keys or not strata or len(set(keys)) != len(keys) or len(set(strata)) != len(strata):
        raise ValueError("Specify distinct key columns and distinct stratum columns")
    if any(re.fullmatch(r"[0-9]+", code.strip()) for code in missing):
        raise ValueError("A nonnegative count cannot be a missing code")
    candidates = {}
    for row in read_table(roster, [*keys, *strata, outcome]):
        key = key_for(row, keys)
        if key in candidates:
            raise ValueError(f"Repeated candidate roster key {key}")
        token = row[outcome].strip()
        if token in missing:
            group = "missing"
        elif re.fullmatch(r"[0-9]+", token):
            group = "zero" if int(token) == 0 else "positive"
        else:
            raise ValueError(f"Undeclared missing or invalid count {token!r}")
        candidates[key] = key_for(row, strata), group
    if not candidates:
        raise ValueError("Empty candidate roster")
    selected = set()
    for row in read_table(selection, [*keys, *strata]):
        key = key_for(row, keys)
        if key in selected or key not in candidates or key_for(row, strata) != candidates[key][0]:
            raise ValueError(f"Repeated, unrecognized, or differently stratified selected key {key}")
        selected.add(key)

    counts = defaultdict(Counter)
    for key, (stratum, group) in candidates.items():
        counts[stratum][group, "retained" if key in selected else "excluded"] += 1
    cells = []
    for stratum, tally in sorted(counts.items()):
        by_group = {group: {state: tally[group, state] for state in ("retained", "excluded")}
                    for group in ("zero", "positive", "missing")}
        available = {group for group in ("zero", "positive") if sum(by_group[group].values())}
        retained = {group for group in available if by_group[group]["retained"]}
        if not available:
            status = "no_observed_outcomes_in_roster"
        elif not retained:
            status = "no_observed_candidates_retained"
        elif len(available) < 2:
            status = "single_observed_outcome_class_in_roster"
        elif retained != available:
            status = "entire_observed_outcome_class_excluded"
        else:
            status = "both_observed_classes_retained"
        cells.append({"stratum": dict(zip(strata, stratum)), "counts": by_group, "status": status})
    return {"candidate_count": len(candidates), "selected_count": len(selected), "strata": cells,
            "lost_outcome_support": any(c["status"] in {"entire_observed_outcome_class_excluded", "no_observed_candidates_retained"} for c in cells)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roster", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("--key", required=True, action="append")
    parser.add_argument("--stratum", required=True, action="append")
    parser.add_argument("--outcome", required=True, help="Source nonnegative integer count, zero retained explicitly")
    parser.add_argument("--missing-code", action="append", default=[""])
    args = parser.parse_args()
    try:
        result = audit(args.roster, args.selection, args.key, args.stratum, args.outcome, set(args.missing_code))
        result["inputs"] = {name: {"filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                            for name, path in (("roster", args.roster), ("selection", args.selection))}
        print(json.dumps(result, indent=2))
        return 2 if result["lost_outcome_support"] else 0
    except (OSError, ValueError, csv.Error) as error:
        parser.exit(1, f"Candidate denominator audit failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())

