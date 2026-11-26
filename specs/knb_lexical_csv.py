"""Represent repeated source records and preserve cell padding in selected KNB CSVs."""

import csv
import json

import pandas as pd


def parse(*, spec, raw_dir):
    frames = {}
    for table in spec.tables:
        declared = [column["name"] for column in table["columns"]]
        with (raw_dir / table["file"]).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            raw_header = next(reader)
            # The Koyukuk file has one trailing space in its source header “Sex ”.
            names = [("Sex" if name == "Sex " and spec.slug == "koyukuk-chum-en-route-mortality" else name) for name in raw_header]
            for derived in ("source_record_number", "source_cell_padding"):
                if derived in names:
                    raise ValueError(f"Source column conflicts with derived field {derived}")
            add_record = "source_record_number" in declared
            add_padding = "source_cell_padding" in declared
            headers = names + (["source_record_number"] if add_record else []) + (["source_cell_padding"] if add_padding else [])
            if headers != declared or len(set(headers)) != len(headers):
                raise ValueError(f"Source and declared header differ in {table['id']}")
            records = []
            for number, cells in enumerate(reader, start=1):
                if len(cells) != len(raw_header):
                    raise ValueError(f"Unexpected CSV width at {table['id']} record {number}")
                padding = []
                for index, value in enumerate(cells):
                    # The SDK strips surrounding whitespace. Save its exact two ends separately.
                    if value != value.strip():
                        if not add_padding:
                            raise ValueError(f"Unrepresented cell padding in {table['id']}")
                        left = value[:len(value) - len(value.lstrip())]
                        remainder = value[len(left):]
                        right = remainder[len(remainder.rstrip()):]
                        padding.append([index + 1, left, right])
                        cells[index] = value.strip()
                if add_record:
                    cells.append(str(number))
                if add_padding:
                    cells.append(json.dumps(padding, ensure_ascii=True, separators=(",", ":")) if padding else "")
                records.append(cells)
        frames[table["id"]] = pd.DataFrame(records, columns=headers, dtype=object)
    return frames
