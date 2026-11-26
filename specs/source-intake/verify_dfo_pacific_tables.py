"""Reverse the DFO lexical projections and compare each selected CSV cell with the pinned input."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import yaml


def check_table(spec, table, source, packaged):
    # Read the publisher artifact independently of the executor and its parser.
    slug = spec["slug"]
    table_id = table["id"]
    if slug == "dfo-bc-lake-acoustic-targets":
        name = {
            "survey_inventory": "output/Target_OUTPUT_data_INVENTORY_(1977_2007).csv",
            "great_central_lake_targets": "output/Target_OUTPUT_data_FINAL_(1977_2007).csv",
        }[table_id]
        with ZipFile(source) as archive:
            payload = archive.read(name)
    else:
        payload = source.read_bytes()
    encoding = "cp1252" if slug in {"dfo-bc-lake-acoustic-targets", "dfo-ricker-beam-trawl", "dfo-pacific-estuary-habitat"} else "utf-8-sig"
    original = csv.reader(io.StringIO(payload.decode(encoding), newline=""), strict=True)
    if slug in {"dfo-pacific-postseason-catch", "dfo-sep-postseason-production"}:
        title = next(original)
        if sum(bool(cell) for cell in title) != 1 or not title[0]:
            raise ValueError(f"{table_id}: publisher title record differs")
    header = next(original)
    with packaged.open(encoding="utf-8", newline="") as file:
        output = csv.reader(file, strict=True)
        fields = next(output)
        ordinal = fields[0] == "source_record_number"
        has_padding = fields[-1] == "source_cell_padding"
        core_fields = fields[int(ordinal):len(fields) - int(has_padding)]
        omitted = len(header) - len(core_fields)
        if omitted != (13 if slug == "dfo-sep-postseason-production" else 0) or core_fields + [""] * omitted != header:
            raise ValueError(f"{table_id}: source header reconstruction differs")
        selected = 0
        padding_count = 0
        for number, original_cells in enumerate(original, start=1):
            if len(original_cells) != len(header):
                raise ValueError(f"{table_id}: publisher input has a ragged record")
            if slug == "dfo-atlantic-salmon-watch-bc" and number > 117:
                if any(original_cells) or number > 142:
                    raise ValueError("Expected an empty trailing export record")
                continue
            if table_id == "great_central_lake_targets" and original_cells[header.index("lake_code/code du lac")] != "1":
                continue
            cells = next(output, None)
            if cells is None or len(cells) != len(fields):
                raise ValueError(f"{table_id}: missing or incomplete packaged row")
            if ordinal and cells.pop(0) != str(number):
                raise ValueError(f"{table_id}: incorrect source record number at row {number}")
            if has_padding:
                borders = json.loads(cells.pop() or "{}")
                for key, (prefix, suffix) in borders.items():
                    index = int(key) - 1
                    if not (0 <= index < len(cells)) or not (prefix or suffix) or (prefix + suffix).strip(" \r\n\t"):
                        raise ValueError(f"{table_id}: invalid padding at row {number}")
                    cells[index] = prefix + cells[index] + suffix
                padding_count += len(borders)
            if cells + [""] * omitted != original_cells:
                raise ValueError(f"{table_id}: publisher values differ at original record {number}")
            selected += 1
        if next(output, None) is not None or not selected:
            raise ValueError(f"{table_id}: unexpected number of output records")
        if slug == "dfo-atlantic-salmon-watch-bc" and (number, selected) != (142, 117):
            raise ValueError("Incomplete source or unexpected number of reports")
    return {"records": selected, "source_fields": len(core_fields), "source_cells": selected * len(core_fields), "padding_cells_restored": padding_count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    args = parser.parse_args()
    spec = yaml.safe_load(args.spec.read_text(encoding="utf-8"))
    for file in spec["source"]["files"]:
        if hashlib.sha256((args.raw_dir / file["name"]).read_bytes()).hexdigest() != file["sha256"]:
            raise ValueError(f"Input digest differs for {file['name']}")
    results = {}
    for table in spec["tables"]:
        packaged = args.build_dir / "sdp" / "data" / f"{table['id']}.csv"
        results[table["id"]] = check_table(spec, table, args.raw_dir / table["file"], packaged)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
