"""Read exact decimals from a reviewed numeric view and its pinned source CSV."""

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from audit_measurement_types import decision_key, keyed_values, metadata, read_decisions, verify_view


def read_verified_decimals(package, decisions_path, source, source_sha256):
    """Return (primary key names, {key tuple: Decimal or None}) in source order.

    The caller supplies the expected hash from the publisher or verified intake
    manifest and the reviewed package metadata and decisions. Only a direct,
    one-to-one numeric view of the selected source measurement is eligible.
    """
    if not isinstance(source_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", source_sha256):
        raise ValueError("source_sha256 must be a 64-digit SHA-256 digest")
    source = decision_key(list(source))
    measurements, schemas = metadata(Path(package))
    decisions = read_decisions(Path(decisions_path), measurements)
    decision = decisions.get(source)
    if not decision or "view" not in decision:
        raise ValueError("the source field needs an explicit direct-view decision")
    view = decision_key(decision["view"])
    extra_missing = decision.get("source_missing_tokens", [])
    source_path, schema, columns, primary_key = schemas[source[:2]]

    # Keep the bytes used for comparison and returned values identical even if
    # a producer concurrently replaces the original CSV. The file is temporary.
    with TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "source.csv"
        digest = hashlib.sha256()
        with source_path.open("rb") as original, snapshot.open("wb") as saved:
            for chunk in iter(lambda: original.read(1024 * 1024), b""):
                digest.update(chunk)
                saved.write(chunk)
        if digest.hexdigest() != source_sha256.lower():
            raise ValueError("source CSV SHA-256 differs from the expected digest")
        source_schema = (snapshot, schema, columns, primary_key)
        schemas[source[:2]] = source_schema
        # Use the same scientific identity, unit, key, value and missingness
        # checks as the audit. Return the matched source's decimal precision.
        verify_view(source, view, measurements, schemas, extra_missing)
        key_names, values, _ = keyed_values(source, source_schema, "number", extra_missing)
    return key_names, values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("decisions", type=Path)
    parser.add_argument("--source", nargs=3, metavar=("DATASET", "TABLE", "COLUMN"), required=True)
    parser.add_argument("--source-sha256", required=True, help="expected byte hash of the package's source CSV")
    args = parser.parse_args()
    try:
        key_names, values = read_verified_decimals(args.package, args.decisions, args.source, args.source_sha256)
    except (OSError, KeyError, TypeError, ValueError, ArithmeticError, csv.Error) as error:
        parser.exit(2, f"cannot read verified numeric view: {error}\n")
    # A JSON numeric literal is routinely parsed as binary64. Use decimal
    # strings and null explicitly for a portable, lossless interchange.
    print(json.dumps({
        "source": args.source,
        "source_sha256": args.source_sha256.lower(),
        "key_columns": key_names,
        "rows": [[key, str(value) if value is not None else None] for key, value in values.items()],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
