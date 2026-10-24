"""Lossless source-local Anvik selection from the original CC0 Malick v1.1 ZIP.

This parser does not rename, type, impute, or filter age/use/year/value fields.
Only exact native stock.id349 and its literal info source.id links select rows.
No cross-dataset identity, age convention, biological mapping or approval is
created. It reads original archive members in memory, never extracts or writes.
The current executor resolves this file as specs.malick_anvik_parser:parse.
"""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pandas as pd

ARCHIVE_NAME = "pink-chum-database-1.1.zip"
ARCHIVE_URL = "https://zenodo.org/api/records/6478751/files/pink-chum-database-1.1.zip/content"
ARCHIVE_SHA256 = "1428be29011afff2fb17bac694aefe7998a2b5188f23b771be17de7643cfc9b5"
PREFIX = "pink-chum-database-1.1/"
MEMBER_SHA256 = {
    "chum_data.csv": "9dcb799bca4595f1d215d3b38d92c86dcf8f373beda401c7318ffc7b3d915bd0",
    "chum_info.csv": "f2f05843ca418a4f3a0ccb75fe97e7d5fb2b5f6a274a6333484e555bbf0396d7",
    "chum_sources.csv": "08022d86651cd22b4da8a9e59d856217a9bce689d6a7dd0c8e9002b957190ae1",
    "README.md": "59055172590e068a6151c24baedb7d9c4e7ff20c737f14441e36ad709a5fb621",
    "LICENSE": "36ffd9dc085d529a7e60e1276d73ae5a030b020313e6c5408593a6ae2af39673",
}
HEADERS = {
    "chum_data": ("stock.id", "species", "stock", "region", "sub.region", "brood.yr",
        "spawners", "recruits", "use", "recruits.2", "recruits.3", "recruits.4",
        "recruits.5", "recruits.6", "recruits.7", "age"),
    "chum_info": ("stock.id", "species", "stock", "region", "sub.region", "jurisdiction",
        "lat", "lon", "source.id", "comment"),
    "chum_sources": ("source.id", "source"),
}
FULL_ROWS = {"chum_data": 2001, "chum_info": 53, "chum_sources": 22}


def _csv(raw, table):
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8")), strict=True))
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Malick Anvik: malformed original CSV member") from exc
    if (not rows or tuple(rows[0]) != HEADERS[table]
            or len(rows) - 1 != FULL_ROWS[table]
            or any(len(row) != len(rows[0]) for row in rows[1:])):
        raise ValueError("Malick Anvik: original CSV schema/row count disagrees")
    return rows[1:]


def _select(rows):
    """Pure lexical row selection; age/use/year/value content is not a filter."""
    data = [row[:] for row in rows["chum_data"] if row[0] == "349"]
    info = [row[:] for row in rows["chum_info"] if row[0] == "349"]
    if len(data) != 22 or len(info) != 1:
        raise ValueError("Malick Anvik: exact native stock349 coverage is missing")
    # Strip only separator whitespace for selecting related rows. The native
    # source.id cell itself remains exactly '16, 18' in the returned info.
    links = tuple(value.strip() for value in info[0][8].split(","))
    if links != ("16", "18"):
        raise ValueError("Malick Anvik: native source.id links disagree")
    sources = [row[:] for row in rows["chum_sources"] if row[0] in links]
    if len(sources) != 2 or {row[0] for row in sources} != set(links):
        raise ValueError("Malick Anvik: linked source rows are missing/duplicated")
    keys = [(row[0], row[5]) for row in data]
    if any(not all(key) for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("Malick Anvik: native stock/brood keys are missing/duplicated")
    return {"chum_data": data, "chum_info": info, "chum_sources": sources}


def parse(*, spec, raw_dir):
    """Return the three source-local frames from the hash-pinned original ZIP."""
    expected = {"name": ARCHIVE_NAME, "url": ARCHIVE_URL, "sha256": ARCHIVE_SHA256}
    if list(spec.source["files"]) != [expected]:
        raise ValueError("Malick Anvik: Spec must identify the actual original archive bytes")
    path = Path(raw_dir) / ARCHIVE_NAME
    if path.is_symlink() or not path.is_file():
        raise ValueError("Malick Anvik: original archive must be a local regular file")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("Malick Anvik: original archive SHA256 mismatch")
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Malick Anvik: duplicate archive member names")
            members = {}
            for name, expected_sha in MEMBER_SHA256.items():
                payload = archive.read(PREFIX + name)
                if hashlib.sha256(payload).hexdigest() != expected_sha:
                    raise ValueError("Malick Anvik: original member SHA256 mismatch: " + name)
                members[name] = payload
    except (BadZipFile, KeyError, OSError) as exc:
        raise ValueError("Malick Anvik: original archive/member could not be read") from exc
    rows = {table: _csv(members[table + ".csv"], table) for table in HEADERS}
    selected = _select(rows)
    return {table: pd.DataFrame(selected[table], columns=list(HEADERS[table]), dtype=object)
            for table in HEADERS}
