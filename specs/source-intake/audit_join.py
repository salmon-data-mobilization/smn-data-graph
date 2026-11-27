"""Measure exact lexical CSV keys and proposed joins before attaching observations."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path


def records(path, fields, payload_fields=()):
    """Yield 1-based data record numbers, exact keys and selected payload values."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader, [])
        for group in (fields, payload_fields):
            if len(set(group)) != len(group):
                raise ValueError("Expected distinct column names in each field list")
        if not fields:
            raise ValueError("Supply at least one key column")
        for field in (*fields, *payload_fields):
            if header.count(field) != 1:
                raise ValueError(f"{path}: expected exactly one header named {field!r}")
        keys = [header.index(field) for field in fields]
        payload = [header.index(field) for field in payload_fields]
        for number, row in enumerate(reader, 1):
            if len(row) != len(header):
                raise ValueError(f"{path}, line {reader.line_num}: wrong number of fields")
            yield number, tuple(row[i] for i in keys), tuple(row[i] for i in payload)


def read_keys(path, fields, null_tokens):
    counts = Counter()
    missing = 0
    for _, key, _ in records(path, fields):
        if any(part in null_tokens for part in key):
            missing += 1
        else:
            counts[key] += 1
    return counts, missing


def distinct_paths(paths):
    if len({p.resolve() for p in paths}) != len(paths):
        raise ValueError("The same file was supplied more than once for one side or collection")
    return paths


def inventory(paths, fields, payload_fields, null_tokens):
    """Retain source locations and exact payload tuples within and across files."""
    groups = defaultdict(list)
    missing = []
    file_summaries = []
    for path in distinct_paths(paths):
        local = Counter()
        row_count = 0
        for number, key, values in records(path, fields, payload_fields):
            row_count += 1
            location = {"file": str(path), "record": number}
            if any(part in null_tokens for part in key):
                missing.append({**location, "key": key})
            else:
                local[key] += 1
                groups[key].append({**location, "payload": values})
        file_summaries.append({"file": str(path), "rows": row_count, "null_key_rows": row_count - sum(local.values()),
                               "repeated_complete_keys": sum(n > 1 for n in local.values())})
    repeats = []
    for key, rows in sorted(groups.items()):
        if len(rows) == 1:
            continue
        files = Counter(row["file"] for row in rows)
        values = {row["payload"] for row in rows}
        repeats.append({"key": key, "within_file": any(n > 1 for n in files.values()), "across_files": len(files) > 1,
                        "distinct_payloads": len(values), "repeated_payload_rows_beyond_first": len(rows) - len(values), "rows": rows})
    rows = sum(f["rows"] for f in file_summaries)
    return {"key_fields": fields, "payload_fields": payload_fields, "null_tokens": sorted(null_tokens), "files": file_summaries,
            "rows": rows, "distinct_complete_keys": len(groups), "null_key_rows": len(missing), "missing_keys": missing,
            "repeated_complete_keys": len(repeats), "within_file_repeated_keys": sum(r["within_file"] for r in repeats),
            "across_file_repeated_keys": sum(r["across_files"] for r in repeats),
            "consistent_repeated_keys": sum(r["distinct_payloads"] == 1 for r in repeats),
            "discordant_repeated_keys": sum(r["distinct_payloads"] > 1 for r in repeats), "repeats": repeats,
            "complete_unique_key": rows > 0 and not missing and not repeats}


def side_summary(counts, missing, other):
    return {
        "rows": sum(counts.values()) + missing,
        "null_key_rows": missing,
        "distinct_complete_keys": len(counts),
        "repeated_complete_keys": sum(n > 1 for n in counts.values()),
        "unmatched_complete_key_rows": sum(n for key, n in counts.items() if not other[key]),
        "rows_matching_once": sum(n for key, n in counts.items() if other[key] == 1),
        "rows_matching_multiple": sum(n for key, n in counts.items() if other[key] > 1),
    }


def combined_counts(paths, fields, null_tokens):
    counts = Counter()
    missing = 0
    for path in distinct_paths(paths):
        subset, nulls = read_keys(path, fields, null_tokens)
        counts.update(subset)
        missing += nulls
    return counts, missing


def audit(left, right, left_key, right_key, null_tokens, left_extra=(), right_extra=(), cardinality=None):
    if len(left_key) != len(right_key):
        raise ValueError("Left and right keys must have the same number of components")
    a, a_null = combined_counts([left, *left_extra], left_key, null_tokens)
    b, b_null = combined_counts([right, *right_extra], right_key, null_tokens)
    shared = a.keys() & b.keys()
    result = {
        "left_key": left_key, "right_key": right_key, "null_tokens": sorted(null_tokens),
        "left": side_summary(a, a_null, b), "right": side_summary(b, b_null, a),
        "shared_complete_keys": len(shared), "inner_rows": sum(a[k] * b[k] for k in shared),
        "many_to_many_keys": sum(a[k] > 1 and b[k] > 1 for k in shared),
    }
    if cardinality:
        left_limit, right_limit = cardinality.split("-to-")
        result["proposed_cardinality"] = cardinality
        result["cardinality_verified"] = bool(shared) and a_null == b_null == 0 and (
            left_limit == "many" or result["left"]["repeated_complete_keys"] == 0
        ) and (right_limit == "many" or result["right"]["repeated_complete_keys"] == 0)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path, nargs="?")
    parser.add_argument("right", type=Path, nargs="?")
    parser.add_argument("--left-key", nargs="+")
    parser.add_argument("--right-key", nargs="+", help="Defaults to the left key names")
    parser.add_argument("--left-extra", type=Path, action="append", default=[], help="Additional CSV on the left. Repeat for more files.")
    parser.add_argument("--right-extra", type=Path, action="append", default=[], help="Additional CSV on the right. Repeat for more files.")
    parser.add_argument("--expect-cardinality", choices=["one-to-one", "one-to-many", "many-to-one", "many-to-many"])
    parser.add_argument("--null-token", action="append", default=[], help="Additional literal missing key token; empty text is always missing")
    parser.add_argument("--require-single-match", action="store_true", help="Fail unless the nonempty left side has exactly one right match for every row")
    parser.add_argument("--files", type=Path, nargs="+", help="Inspect key and payload collisions in a collection of CSVs")
    parser.add_argument("--key", nargs="+", help="Key fields in the collection")
    parser.add_argument("--payload", nargs="+", help="Fields whose exact values should be compared among repeated keys")
    parser.add_argument("--expect-unique", action="store_true", help="Require a nonempty collection with complete, unique keys")
    args = parser.parse_args()
    nulls = {"", *args.null_token}
    try:
        if args.files:
            if not args.key or not args.payload or any((args.left, args.right, args.left_key, args.right_key, args.left_extra,
                                                       args.right_extra, args.require_single_match, args.expect_cardinality)):
                parser.error("--files requires --key and --payload and is separate from the two-sided join")
            result = inventory(args.files, args.key, args.payload, nulls)
            failed = args.expect_unique and not result["complete_unique_key"]
        else:
            if not all((args.left, args.right, args.left_key)) or any((args.key, args.payload, args.expect_unique)):
                parser.error("A join requires LEFT RIGHT --left-key; collection options require --files")
            result = audit(args.left, args.right, args.left_key, args.right_key or args.left_key, nulls,
                           args.left_extra, args.right_extra, args.expect_cardinality)
            left = result["left"]
            failed = result.get("cardinality_verified") is False or (
                args.require_single_match and (left["rows"] == 0 or left["rows"] != left["rows_matching_once"])
            )
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
