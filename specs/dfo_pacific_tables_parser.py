"""Build lexical tables from the pinned DFO Pacific CSV distributions."""

import csv
import io
import json
from zipfile import ZipFile

import pandas as pd


ACOUSTIC_MEMBERS = {
    "survey_inventory": "output/Target_OUTPUT_data_INVENTORY_(1977_2007).csv",
    "great_central_lake_targets": "output/Target_OUTPUT_data_FINAL_(1977_2007).csv",
}
LEGACY_ENCODING = {"dfo-bc-lake-acoustic-targets", "dfo-ricker-beam-trawl", "dfo-pacific-estuary-habitat"}
TITLE_RECORD = {"dfo-pacific-postseason-catch", "dfo-sep-postseason-production"}
PADDING = " \t\r\n"


def _preserve_padding(records):
    """Separate whitespace the SDK trims. Store the exact prefix and suffix by source position."""
    for row in records:
        borders = {}
        for index, original in enumerate(row):
            trimmed = original.strip(PADDING)
            if original == trimmed:
                continue
            start = len(original) - len(original.lstrip(PADDING))
            borders[str(index + 1)] = [original[:start], original[start + len(trimmed):]]
            row[index] = trimmed
        row.append(json.dumps(borders, separators=(",", ":")) if borders else "")


def parse(*, spec, raw_dir):
    frames = {}
    for table in spec.tables:
        key = table["id"]
        path = raw_dir / table["file"]
        if spec.slug == "dfo-bc-lake-acoustic-targets":
            with ZipFile(path) as archive:
                data = archive.read(ACOUSTIC_MEMBERS[key])
        else:
            data = path.read_bytes()
        encoding = "cp1252" if spec.slug in LEGACY_ENCODING else "utf-8-sig"
        reader = csv.reader(io.StringIO(data.decode(encoding), newline=""), strict=True)
        if spec.slug in TITLE_RECORD:
            title = next(reader)
            if not title[0] or any(title[1:]):
                raise ValueError(f"{key}: expected one source title in the first record")
        header = next(reader)
        width = len(header)
        if spec.slug == "dfo-sep-postseason-production":
            # The publisher spreadsheet export has 13 named fields followed by empty columns.
            while header and header[-1] == "":
                header.pop()
        records = []
        record_numbers = []
        blank_tail = 0
        lake_index = header.index("lake_code/code du lac") if key == "great_central_lake_targets" else None
        for number, row in enumerate(reader, start=1):
            if len(row) != width or any(row[len(header):]):
                raise ValueError(f"{key}: source width or trailing padding changed")
            if spec.slug == "dfo-atlantic-salmon-watch-bc" and not any(row):
                blank_tail += 1
                continue
            if blank_tail:
                raise ValueError(f"{key}: nonempty data follows the source's blank record padding")
            if lake_index is not None and row[lake_index] != "1":
                continue
            records.append(row[:len(header)])
            record_numbers.append(str(number))
        if spec.slug == "dfo-atlantic-salmon-watch-bc" and blank_tail != 25:
            raise ValueError(f"{key}: expected 25 fully blank trailing CSV records")
        names = [column["name"] for column in table["columns"]]
        if "source_cell_padding" in names:
            _preserve_padding(records)
            header.append("source_cell_padding")
        frame = pd.DataFrame(records, columns=header, dtype=object)
        if "source_record_number" in names:
            frame.insert(0, "source_record_number", record_numbers)
        if list(frame.columns) != names:
            raise ValueError(f"{key}: source headers differ from the Spec")
        frames[key] = frame
    return frames
