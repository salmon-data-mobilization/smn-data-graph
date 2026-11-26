"""Read DFO's bilingual lookup as lexical CSV, with its original header encoding."""

import csv

import pandas as pd


def parse(*, spec, raw_dir):
    (table,) = spec.tables
    with (raw_dir / table["file"]).open(encoding="latin-1", newline="") as source:
        header, *rows = csv.reader(source, strict=True)
    if header != [field["name"] for field in table["columns"]]:
        raise ValueError("DFO lookup headers differ from the pinned schema")
    if any(len(row) != len(header) for row in rows):
        raise ValueError("DFO lookup CSV has an inconsistent record width")
    return {table["id"]: pd.DataFrame(rows, columns=header, dtype=object)}
