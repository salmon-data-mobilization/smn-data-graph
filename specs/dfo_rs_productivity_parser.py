"""Prepare DFO's three complete CSV data files for the lexical Spec v1 executor."""

import csv

import pandas as pd


def _preserve_comment_padding(header, records, table):
    """Store the source location of each terminal space that the SDK strips on read."""
    fields, expected = {
        "annual": ({"Age comm", "Prod comm", "Esc comm"}, 69),
        "series_summary": ({"Stock, general (comments)", "Exploitation rate (comments)", "Escapement (comments)"}, 8),
    }[table]
    count = 0
    for row in records:
        positions = []
        for position, (field, value) in enumerate(zip(header, row), start=1):
            if value == value.strip():
                continue
            if field not in fields or value != value.strip() + " ":
                raise ValueError(f"Unexpected source whitespace in {table} field {field!r}")
            positions.append(str(position))
            row[position - 1] = value[:-1]
        count += len(positions)
        row.append("|".join(positions))
    if count != expected:
        raise ValueError(f"Expected {expected} comment cells with one terminal space in {table}, got {count}")
    header.append("source_columns_with_trailing_space")


def _decadal_frames(path):
    # Each repeated header identifies the geographical units for one brood line or species.
    # Only the rectangular file's empty right-hand padding lies outside each block.
    blocks = {}
    header = None
    records = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        marker = ["Species", "Decade", "DataQualityType"]
        for row in csv.reader(source, strict=True):
            if len(row) != 91:
                raise ValueError("Unexpected decadal CSV width")
            if row[:3] == marker:
                if header is not None and not records:
                    raise ValueError("Empty decadal block")
                header = row[:]
                while header and header[-1] == "":
                    header.pop()
                if len(header) < 4 or not all(header) or len(set(header)) != len(header):
                    raise ValueError("Decadal block has an empty or duplicate field name")
                records = []
            else:
                if header is None:
                    raise ValueError("Decadal CSV must start with a header")
                if any(row[len(header):]):
                    raise ValueError("Decadal summary has a value outside its block header")
                if not records:
                    if row[0] in blocks:
                        raise ValueError("Duplicate species block in decadal summary")
                    blocks[row[0]] = header, records
                elif row[0] != records[0][0]:
                    raise ValueError("Decadal species changed without a header")
                records.append(row[:len(header)])
    ids = {"Sockeye": "decadal_sockeye", "Pink (even)": "decadal_pink_even", "Pink (odd)": "decadal_pink_odd", "Chum": "decadal_chum"}
    if not records or set(blocks) != set(ids):
        raise ValueError("Unexpected species in decadal summary")
    return {ids[species]: pd.DataFrame(records, columns=header, dtype=object) for species, (header, records) in blocks.items()}


def parse(*, spec, raw_dir):
    """Preserve each source cell and its position; the executor checks input hashes."""
    frames = {}
    for table in spec.tables:
        if table["file"] == "Salmon_RS_Decadal_Summary.csv":
            if table["id"] not in frames:
                frames.update(_decadal_frames(raw_dir / table["file"]))
            if list(frames[table["id"]].columns) != [column["name"] for column in table["columns"]]:
                raise ValueError(f"{table['id']}: decadal headers differ from the source specification")
            continue
        with (raw_dir / table["file"]).open(encoding="utf-8-sig", newline="") as source:
            header, *records = csv.reader(source, strict=True)
        if any(len(row) != len(header) for row in records):
            raise ValueError(f"{table['file']}: inconsistent source row width")

        if table["id"] == "annual":
            # Name the two empty headers by their one-based source positions.
            if len(header) != 61 or header[-2:] != ["", ""] or any(not name for name in header[:-2]):
                raise ValueError("DFO annual data must have exactly two unnamed trailing fields")
            if any(row[-2:] != ["", ""] for row in records):
                raise ValueError("DFO annual unnamed fields contain unexpected values")
            header[-2:] = ["unnamed_source_column_60", "unnamed_source_column_61"]
            _preserve_comment_padding(header, records, table["id"])
            frame = pd.DataFrame(records, columns=header, dtype=object)
        elif table["id"] == "series_summary":
            # Preserve blank source identifiers and use only the physical CSV record as a local key.
            _preserve_comment_padding(header, records, table["id"])
            frame = pd.DataFrame(records, columns=header, dtype=object)
            frame.insert(0, "source_record_number", [str(i) for i in range(1, len(frame) + 1)])
        else:
            raise ValueError(f"Unexpected DFO table {table['id']!r}")

        if list(frame.columns) != [column["name"] for column in table["columns"]]:
            raise ValueError(f"{table['file']}: header differs from the source specification")
        frames[table["id"]] = frame
    return frames
