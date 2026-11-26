"""Check each source header and record against its independently reconstructed package CSV."""

import argparse
import csv
import hashlib
from itertools import zip_longest
import json
from pathlib import Path

import yaml


def verify(spec_path, raw_dir, build_dir):
    spec = yaml.safe_load(spec_path.read_text())
    hashes = {item["name"]: item["sha256"] for item in spec["source"]["files"]}
    for table in spec["tables"]:
        original = raw_dir / table["file"]
        if hashlib.sha256(original.read_bytes()).hexdigest() != hashes[original.name]:
            raise ValueError(f"Source hash mismatch in {original.name}")
        resource = build_dir / "sdp" / "data" / (table["id"] + ".csv")
        declared = [column["name"] for column in table["columns"]]
        with original.open(encoding="utf-8-sig", newline="") as source, resource.open(encoding="utf-8", newline="") as packaged:
            left, right = csv.reader(source, strict=True), csv.reader(packaged, strict=True)
            source_header, package_header = next(left), next(right)
            if package_header != declared:
                raise ValueError(f"Package header differs from Spec in {table['id']}")
            restored_header = [field for field in package_header if field not in ("source_record_number", "source_cell_padding")]
            if spec["slug"] == "koyukuk-chum-en-route-mortality":
                restored_header[restored_header.index("Sex")] = "Sex "
            if restored_header != source_header:
                raise ValueError(f"Source header differs in {table['id']}")
            total = 0
            for number, (expected, actual) in enumerate(zip_longest(left, right), start=1):
                if expected is None or actual is None or len(expected) != len(source_header) or len(actual) != len(declared):
                    raise ValueError(f"Different table dimensions in {table['id']}, row {number}")
                if "source_record_number" in declared and actual[declared.index("source_record_number")] != str(number):
                    raise ValueError(f"Incorrect source record ordinal in {table['id']}, row {number}")
                row = actual[:len(source_header)]
                if "source_cell_padding" in declared:
                    indexes = set()
                    for position, before, after in json.loads(actual[declared.index("source_cell_padding")] or "[]"):
                        if type(position) is not int or not 1 <= position <= len(row) or position in indexes or (before + after).strip() or not (before or after):
                            raise ValueError(f"Invalid source cell padding in {table['id']}, row {number}")
                        indexes.add(position)
                        row[position - 1] = before + row[position - 1] + after
                if row != expected:
                    raise ValueError(f"Source cell mismatch in {table['id']}, row {number}")
                total += len(row)
        print(f"{table['id']} verified {total} original source cells")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    args = parser.parse_args()
    verify(args.spec, args.raw_dir, args.build_dir)
