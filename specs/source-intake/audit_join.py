"""Measure an exact lexical CSV join before using it to attach scientific observations."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def read_keys(path, fields, null_tokens):
    """Count whole composite keys. A missing component never matches another missing value."""
    counts = Counter()
    missing = 0
    if not fields or len(set(fields)) != len(fields):
        raise ValueError("Supply one or more distinct key columns on each side")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader, [])
        for field in fields:
            if header.count(field) != 1:
                raise ValueError(f"{path}: expected exactly one header named {field!r}")
        positions = [header.index(field) for field in fields]
        for row in reader:
            if len(row) != len(header):
                raise ValueError(f"{path}, line {reader.line_num}: wrong number of fields")
            key = tuple(row[position] for position in positions)
            if any(value in null_tokens for value in key):
                missing += 1
            else:
                counts[key] += 1
    return counts, missing


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


def audit(left, right, left_key, right_key, null_tokens):
    if len(left_key) != len(right_key):
        raise ValueError("Left and right keys must have the same number of components")
    a, a_null = read_keys(left, left_key, null_tokens)
    b, b_null = read_keys(right, right_key, null_tokens)
    return {
        "left_key": left_key,
        "right_key": right_key,
        "null_tokens": sorted(null_tokens),
        "left": side_summary(a, a_null, b),
        "right": side_summary(b, b_null, a),
        "shared_complete_keys": len(a.keys() & b.keys()),
        "inner_rows": sum(n * b[key] for key, n in a.items()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--left-key", nargs="+", required=True)
    parser.add_argument("--right-key", nargs="+", help="Defaults to the left key names")
    parser.add_argument("--null-token", action="append", default=[], help="Additional literal missing token; empty text is always missing")
    parser.add_argument("--require-single-match", action="store_true", help="Fail unless the nonempty left file has exactly one right match for every row")
    args = parser.parse_args()
    try:
        result = audit(args.left, args.right, args.left_key, args.right_key or args.left_key, {"", *args.null_token})
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    left = result["left"]
    if args.require_single_match and (left["rows"] == 0 or left["rows"] != left["rows_matching_once"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
