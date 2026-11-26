"""Read the selected Figshare data tables into lexical Spec v1 resources."""

import csv
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pandas as pd


# The Hood Canal projection excludes formula-derived fields, genotypes and notes.
WORKBOOK_COLUMNS = {
    "hood-canal-steelhead-monitoring": ("A", "C", "D", "E", "F", "G", "I", "J"),
    "methow-river-fish-production": tuple("ABCDEFGHIJKL"),
}
ELWHA_MEMBER = "Data/outMigrantDat.csv"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _workbook_rows(path, columns):
    """Keep the stored Excel numeric text and resolve its shared-string indices."""
    with ZipFile(path) as archive:
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        if [sheet.get("name") for sheet in book.iter(NS + "sheet")] != ["Sheet1"]:
            raise ValueError("Expected the published single-sheet workbook")
        strings = [
            "".join(text.text or "" for text in item.iter(NS + "t"))
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))
        ]
        with archive.open("xl/worksheets/sheet1.xml") as sheet:
            expected = 1
            for _, row in ET.iterparse(sheet, events=("end",)):
                if row.tag != NS + "row":
                    continue
                if int(row.get("r")) != expected:
                    raise ValueError("Unexpected source worksheet row sequence")
                expected += 1
                values = {}
                for cell in row.findall(NS + "c"):
                    col = re.sub(r"[0-9]+$", "", cell.get("r"))
                    if col not in columns:
                        continue
                    if cell.find(NS + "f") is not None or cell.get("t", "n") not in {"n", "s"}:
                        raise ValueError("Unexpected formula or cell type in selected worksheet fields")
                    value = cell.findtext(NS + "v", "")
                    values[col] = strings[int(value)] if cell.get("t") == "s" else value
                yield [values.get(column, "") for column in columns]
                row.clear()


def _source_rows(path, slug):
    if path.suffix == ".xlsx":
        yield from _workbook_rows(path, WORKBOOK_COLUMNS[slug])
    elif path.suffix == ".zip":
        if slug != "elwha-chinook-outmigration":
            raise ValueError("Unexpected ZIP input")
        with ZipFile(path) as archive, archive.open(ELWHA_MEMBER) as member:
            with io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as text:
                yield from csv.reader(text, strict=True)
    else:
        with path.open(encoding="utf-8-sig", newline="") as text:
            yield from csv.reader(text, strict=True)


def parse(*, spec, raw_dir):
    frames = {}
    for table in spec.tables:
        rows = _source_rows(Path(raw_dir) / table["file"], spec.slug)
        header = next(rows)
        names = [name if name and header.count(name) == 1 else f"source_column_{i}" for i, name in enumerate(header, 1)]
        padded = spec.slug == "puget-sound-edge-habitat-fish"
        fields = ["source_record_number", *names]
        if padded:
            fields.append("source_edge_whitespace")
        if fields != [column["name"] for column in table["columns"]]:
            raise ValueError("Source file headers differ from the Spec")
        records = []
        for ordinal, row in enumerate(rows, 1):
            if len(row) != len(header):
                raise ValueError(f"Ragged source record {ordinal}")
            whitespace = {str(i): val for i, val in enumerate(row, 1) if val != val.strip(" \t\r\n")}
            if whitespace and not padded:
                raise ValueError(f"Unexpected padded value at source record {ordinal}")
            if padded:
                row = [val.strip(" \t\r\n") for val in row]
                row.append(json.dumps(whitespace, ensure_ascii=False, separators=(",", ":")) if whitespace else "")
            records.append([str(ordinal), *row])
        frames[table["id"]] = pd.DataFrame(records, columns=fields, dtype=object)
    return frames
