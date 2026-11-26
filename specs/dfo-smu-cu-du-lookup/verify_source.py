"""Verify all original DFO lookup fields, row order, bilingual headers and blanks."""

import argparse
import csv
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    args = parser.parse_args()
    source = args.raw_dir / "SMU_CU_DU_Lookup_Table_7172025.csv"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != "d10eec5b8a5b46dab4b73daeeb97d125cbbd4a781f46fa2f2a17b9c740ccf102":
        raise ValueError("DFO lookup input differs from the pinned Open Canada attachment")
    with source.open(encoding="latin-1", newline="") as file:
        header, *rows = csv.reader(file, strict=True)
    with (args.build_dir / "sdp/data/unit_lookup.csv").open(encoding="utf-8", newline="") as file:
        output_header, *output_rows = csv.reader(file, strict=True)
    if header != output_header or rows != output_rows:
        raise ValueError("DFO lookup differs in header spelling, cell content or row order")
    if len(rows) != 484 or len(header) != 13 or any(len(row) != 13 for row in rows):
        raise ValueError("DFO lookup dimensions differ")
    cu = header.index("Full CU Index/Index complet des UC")
    smu = header.index("Full SMU Index/Index Complet des UGS")
    du = header.index("Full DU Index/Index complet de l'UD")
    cu_indexes = {row[cu] for row in rows}
    if "" in cu_indexes or len(cu_indexes) != len(rows):
        raise ValueError("Source-local CU index is missing or duplicated")
    counts = {
        "blank_smu_index_cells": sum(row[smu] == "" for row in rows),
        "blank_du_index_cells": sum(row[du] == "" for row in rows),
        "semicolon_delimited_du_index_cells": sum(";" in row[du] for row in rows),
        "literal_NA_or_not_assigned_cells": sum(cell.casefold() in {"na", "n/a", "not assigned"} for row in rows for cell in row),
    }
    if tuple(counts.values()) != (84, 182, 8, 0):
        raise ValueError("DFO lookup assignment field profile differs from the pinned source")
    print(json.dumps({"data_rows": len(rows), "fields": len(header), "source_cells_verified": len(rows) * len(header), "sha256": digest, **counts}, indent=2))


if __name__ == "__main__":
    main()
