"""Privately check whether one proposed SDP table declares the publisher fields an analysis needs."""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
import os
from pathlib import Path


def unique_names(values, label):
    if not values or any(not name.strip() for name in values) or len(values) != len(set(values)):
        raise ValueError(f"{label} must contain nonempty, distinct names")
    return values


def csv_rows(raw):
    return csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)


def audit(header_bytes, dictionary_bytes, source_scope, native_scope, required, aliases):
    if any(not value.strip() for value in (*source_scope, *native_scope)) or len(source_scope) != 2 or len(native_scope) != 2:
        raise ValueError("Specify dataset and table identifiers for both input scopes")
    publisher_rows = csv_rows(header_bytes)
    publisher = unique_names(next(publisher_rows, []), "Publisher header")
    if next(publisher_rows, None) is not None:
        raise ValueError("Supply only the publisher header as a single CSV record")

    dictionary_rows = csv_rows(dictionary_bytes)
    columns = unique_names(next(dictionary_rows, []), "SDP dictionary header")
    identity = ("dataset_id", "table_id", "column_name")
    if not set(identity).issubset(columns):
        raise ValueError(f"SDP dictionary header requires {identity}")
    positions = [columns.index(name) for name in identity]
    all_keys = set()
    for row in dictionary_rows:
        if len(row) != len(columns):
            raise ValueError(f"Malformed SDP dictionary record at line {dictionary_rows.line_num}")
        key = tuple(row[i] for i in positions)
        if not all(value.strip() for value in key) or key in all_keys:
            raise ValueError(f"Empty or duplicate qualified SDP field at line {dictionary_rows.line_num}: {key}")
        all_keys.add(key)
    native = {field for dataset, table, field in all_keys if (dataset, table) == tuple(native_scope)}
    if not native:
        raise ValueError(f"No dictionary columns for specified SDP table {tuple(native_scope)}")

    unique_names(required, "Required publisher fields")
    renamed = {}
    for old, new in aliases:
        if old not in publisher or new not in native or old in renamed:
            raise ValueError(f"Invalid or repeated explicit alias: {old!r} -> {new!r}")
        renamed[old] = new
    # Check every source field, including fields outside the requested analysis.
    owners = {}
    for source in publisher:
        target = renamed.get(source, source)
        if target in native:
            if target in owners:
                raise ValueError(f"Ambiguous native column {target!r} for both {owners[target]!r} and {source!r}")
            owners[target] = source

    source_table = dict(zip(identity[:2], source_scope))
    native_table = dict(zip(identity[:2], native_scope))
    findings = []
    for source in required:
        target = renamed.get(source, source)
        in_publisher = source in publisher
        in_native = target in native
        if not in_publisher:
            status = "absent_from_publisher_header"
        elif not in_native:
            status = "lost_in_projection"
        else:
            status = "declared_in_both"
        findings.append({"publisher": {**source_table, "column_name": source}, "in_publisher_header": in_publisher,
                         "native": {**native_table, "column_name": target}, "in_native_dictionary": in_native,
                         "name_rule": "explicit_alias" if source in renamed else "exact", "status": status})

    return {"audience": "independent_reader_private", "semantics_verified": False,
            "publisher_header_sha256": hashlib.sha256(header_bytes).hexdigest(),
            "native_dictionary_sha256": hashlib.sha256(dictionary_bytes).hexdigest(),
            "publisher_column_count": len(publisher), "native_table_column_count": len(native),
            "aliases": renamed, "status_counts": dict(Counter(f["status"] for f in findings)), "fields": findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("publisher_header", type=Path, help="Header-only UTF-8 CSV for the source dataset and table")
    parser.add_argument("native_dictionary", type=Path, help="SDP metadata/column_dictionary.csv")
    parser.add_argument("--source", required=True, nargs=2, metavar=("DATASET", "TABLE"))
    parser.add_argument("--native", required=True, nargs=2, metavar=("DATASET", "TABLE"))
    parser.add_argument("--require", required=True, action="append", metavar="SOURCE_FIELD")
    parser.add_argument("--alias", action="append", default=[], nargs=2, metavar=("SOURCE_FIELD", "NATIVE_FIELD"))
    parser.add_argument("--output", type=Path, required=True, help="New private JSON receipt path; existing files are refused")
    args = parser.parse_args()
    try:
        result = audit(args.publisher_header.read_bytes(), args.native_dictionary.read_bytes(),
                       args.source, args.native, args.require, args.alias)
        with open(args.output, "x", encoding="utf-8", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 2 if any(f["status"] != "declared_in_both" for f in result["fields"]) else 0
    except (OSError, ValueError, csv.Error) as error:
        parser.exit(1, f"Schema projection preflight failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
