"""Independently compare a West Coast package with its published CSV or Excel cells."""

import argparse
import csv
from decimal import Decimal
from itertools import zip_longest
import io
import json
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook
from salmongraph.spec import load_spec


def _original(path, slug):
    if path.suffix == ".xlsx":
        workbook = load_workbook(path, read_only=True, data_only=False)
        try:
            if workbook.sheetnames != ["Sheet1"]:
                raise ValueError("Unexpected sheet inventory")
            # Use the independent Excel reader and explicit zero-based source positions.
            selected = (0, 2, 3, 4, 5, 6, 8, 9) if slug == "hood-canal-steelhead-monitoring" else tuple(range(12))
            for row in workbook.active.values:
                yield [row[i] for i in selected]
        finally:
            workbook.close()
    elif path.suffix == ".zip":
        with ZipFile(path) as z, z.open("Data/outMigrantDat.csv") as f:
            with io.TextIOWrapper(f, encoding="utf-8-sig", newline="") as src:
                yield from csv.reader(src, strict=True)
    else:
        with path.open(encoding="utf-8-sig", newline="") as src:
            yield from csv.reader(src, strict=True)


def _same_cell(raw, saved):
    if raw is None:
        return saved == ""
    if isinstance(raw, float):
        return float(saved) == raw
    if isinstance(raw, int):
        return Decimal(saved) == raw
    return raw == saved


def verify(spec, raw_dir, build_dir):
    total = 0
    for table in spec.tables:
        source = raw_dir / table["file"]
        rows = _original(source, spec.slug)
        header = next(rows)
        labels = [h if h and header.count(h) == 1 else f"source_column_{pos}" for pos, h in enumerate(header, 1)]
        padded = spec.slug == "puget-sound-edge-habitat-fish"
        fields = ["source_record_number", *labels] + (["source_edge_whitespace"] if padded else [])
        packaged = build_dir / "sdp" / "data" / (table["id"] + ".csv")
        with packaged.open(encoding="utf-8", newline="") as text:
            actual = csv.reader(text, strict=True)
            if next(actual) != fields:
                raise ValueError(f"{packaged.name}: header differs")
            for ordinal, (row, output) in enumerate(zip_longest(rows, actual), 1):
                if row is None or output is None or len(output) != len(fields) or output[0] != str(ordinal):
                    raise ValueError(f"{packaged.name}: source ordinal or record count differs at {ordinal}")
                values = output[1:len(header)+1]
                padding = json.loads(output[-1]) if padded and output[-1] else {}
                for key, original in padding.items():
                    index = int(key) - 1
                    if not 0 <= index < len(values) or original == values[index] or original.strip(" \t\r\n") != values[index]:
                        raise ValueError("Invalid source whitespace record")
                    values[index] = original
                if len(row) != len(values) or not all(_same_cell(a, b) for a, b in zip(row, values)):
                    raise ValueError(f"{packaged.name}: source cell differs at {ordinal}")
                total += 1
    print(f"{spec.slug}: verified {total:,} source records")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("--spec", "--raw-dir", "--build-dir"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    verify(load_spec(args.spec), args.raw_dir, args.build_dir)
