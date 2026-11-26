"""Compare all six packaged tables with the three pinned DFO originals, cell for cell."""

import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path


def compare(source, packaged, *, table, digest, nrows, ncols):
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise ValueError(f"{source.name}: input SHA-256 differs from the DFO snapshot")
    with source.open(encoding="utf-8-sig", newline="") as original, packaged.open(encoding="utf-8", newline="") as built:
        original_rows = csv.reader(original, strict=True)
        built_rows = csv.reader(built, strict=True)
        source_header = next(original_rows)
        package_header = next(built_rows)
        if package_header.pop() != "source_columns_with_trailing_space":
            raise ValueError(f"{table}: missing lexical reconstruction column")
        if table == "annual":
            if package_header[-2:] != ["unnamed_source_column_60", "unnamed_source_column_61"]:
                raise ValueError("Annual positional column aliases changed")
            package_header[-2:] = ["", ""]
        else:
            if package_header.pop(0) != "source_record_number":
                raise ValueError("Summary record key is missing")
        if len(source_header) != ncols or source_header != package_header:
            raise ValueError(f"{table}: source headers differ")
        count = 0
        restored = 0
        for count, (left, right) in enumerate(itertools.zip_longest(original_rows, built_rows), start=1):
            if left is None or right is None:
                raise ValueError(f"{table}: row count differs at data record {count}")
            if table == "series_summary" and (not right or right.pop(0) != str(count)):
                raise ValueError(f"{table}: derived ordinal differs at data record {count}")
            # The original bytes independently identify every permitted position.
            positions = [pos for pos, value in enumerate(left, start=1) if value.endswith(" ")]
            if right.pop() != "|".join(map(str, positions)):
                raise ValueError(f"{table}: incorrect source padding map at data record {count}")
            for position in positions:
                right[position - 1] += " "
            restored += len(positions)
            if len(left) != ncols or left != right:
                raise ValueError(f"{table}: source cells differ at data record {count}")
        if count != nrows:
            raise ValueError(f"{table}: expected {nrows} source records, got {count}")
        if restored != {"annual": 69, "series_summary": 8}[table]:
            raise ValueError(f"{table}: unexpected number of terminal spaces restored")
        return {"records": count, "source_fields": ncols, "source_cells_checked": count * ncols, "terminal_spaces_restored": restored}


def compare_decadal(source, packaged):
    digest = "84f9847d09ed76e0ab6c72f4d1f82445eb9b23c31b3e08dac4ddd66e647f20ae"
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise ValueError("Decadal input SHA-256 differs from the DFO snapshot")
    # Independent of the parser's header detection: rebuild all four original CSV blocks,
    # including their headers and right-hand padding, and compare the entire cell grid.
    reconstructed = []
    results = {}
    for table, count, width in [("decadal_sockeye", 24, 91), ("decadal_pink_even", 18, 22), ("decadal_pink_odd", 21, 25), ("decadal_chum", 24, 33)]:
        with (packaged / f"{table}.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle, strict=True))
        if len(rows) != count + 1 or any(len(row) != width for row in rows):
            raise ValueError(f"{table}: packaged block shape differs")
        reconstructed.extend(row + [""] * (91 - width) for row in rows)
        results[table] = {"records": count, "source_fields": width, "source_cells_checked": count * width}
    with source.open(encoding="utf-8-sig", newline="") as handle:
        if reconstructed != list(csv.reader(handle, strict=True)):
            raise ValueError("Decadal blocks do not reproduce the full 91-by-91 original CSV grid")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    args = parser.parse_args()
    packaged = args.build_dir / "sdp" / "data"
    results = {}
    for table, filename, digest, nrows, ncols in [
        ("annual", "Salmon_RS_Database.csv", "e5ea38b0109a8b2018ac94b7bbca0a2e2865a9f59fcddda4121aeb2f0ae1f3e5", 8093, 61),
        ("series_summary", "Salmon_RS_Time_Series_Summary.csv", "2dcffdbb5b428fb27b8465326213fd094bb3934bd3ee8945936971c930f5cb6c", 160, 25),
    ]:
        results[table] = compare(args.raw_dir / filename, packaged / f"{table}.csv", table=table, digest=digest, nrows=nrows, ncols=ncols)
    results.update(compare_decadal(args.raw_dir / "Salmon_RS_Decadal_Summary.csv", packaged))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
