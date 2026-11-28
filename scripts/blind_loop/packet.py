#!/usr/bin/env python3
"""Freeze a case's document packet: manifest, page-level text and images of sparse pages.

Reads one or more librarian manifests (JSON lists of documents, each with a
local "file" path), merges them by SHA-256, copies each document into
<out>/docs/, and writes <out>/text/<doc_id>/page-NNN.txt for every PDF page.
Any other document (CSV, HTML, XLSX, TXT) becomes a single page-001.txt.
Pages whose text is much sparser than is usual for their document (usually
scanned tables) are also rendered to <out>/pages/<doc_id>/page-NNN.png.
Writes <out>/manifest.json and prints its SHA-256. The packet is meant to be
read without network access. Exit codes: 0 written, 2 missing or malformed input.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

FIELDS = ("title", "publisher", "year", "url", "rights", "collected_by", "relevance", "pages_of_interest")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pdf_pages(path: Path) -> list[str]:
    out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True)
    pages = out.stdout.split("\f") if out.returncode == 0 else []
    return pages[:-1] if pages and not pages[-1].strip() else pages


def other_text(path: Path) -> str:
    """A non-PDF document as one page of text, extracted as check_citations.py does: HTML without tags, XLSX
    cell text, anything else (CSV, TXT) as it is."""
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        with zipfile.ZipFile(path) as z:
            return re.sub(r"<[^>]+>", " ", " ".join(z.read(n).decode(errors="replace") for n in z.namelist()
                                                     if n.endswith(".xml")))
    text = path.read_text(errors="replace")
    if suffix in (".html", ".htm"):
        text = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", text)))
    return text


def render(path: Path, page: int, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    stem = dest.with_suffix("")
    subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", "110", "-png", "-singlefile",
                    str(path), str(stem)], capture_output=True)


def build(manifests: list[Path], out: Path) -> dict:
    merged: dict[str, dict] = {}
    for m in manifests:
        base = m.parent
        for doc in json.loads(m.read_text()):
            src = (base / doc["file"]).resolve()
            digest = sha256(src)
            entry = merged.setdefault(digest, {"sha256": digest, "found_by": [], "src": src})
            entry["found_by"].append(m.parent.name)
            for f in FIELDS:
                if doc.get(f) and not entry.get(f):
                    entry[f] = doc[f]
    docs = sorted(merged.values(), key=lambda d: (str(d.get("publisher", "")), str(d.get("year", "")),
                                                   str(d.get("title", ""))))
    (out / "docs").mkdir(parents=True, exist_ok=True)
    for i, d in enumerate(docs, 1):
        d["doc_id"] = f"D{i:02d}"
        src = d.pop("src")
        dest = out / "docs" / f"{d['doc_id']}{src.suffix.lower()}"
        shutil.copyfile(src, dest)
        d["file"] = str(dest.relative_to(out))
        if src.suffix.lower() == ".pdf":
            pages = pdf_pages(dest)
            usual = sorted(len(p) for p in pages)[len(pages) // 2] if pages else 0
            sparse = []
            for n, text in enumerate(pages, 1):
                tdir = out / "text" / d["doc_id"]
                tdir.mkdir(parents=True, exist_ok=True)
                (tdir / f"page-{n:03d}.txt").write_text(text)
                if len(text.strip()) < 0.25 * max(usual, 400):
                    render(dest, n, out / "pages" / d["doc_id"] / f"page-{n:03d}.png")
                    sparse.append(n)
            d["n_pages"] = len(pages)
            d["image_only_pages"] = sparse
        else:
            tdir = out / "text" / d["doc_id"]
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / "page-001.txt").write_text(other_text(dest))
            d["n_pages"], d["image_only_pages"] = 1, []
        d["found_by"] = sorted(set(d["found_by"]))
    manifest = {"documents": docs}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("out", type=Path, help="packet folder for one case")
    p.add_argument("manifests", type=Path, nargs="+", help="librarian manifest files")
    a = p.parse_args(argv)
    try:
        build(a.manifests, a.out)
    except (OSError, json.JSONDecodeError, KeyError) as e:
        print(f"input error: {e}", file=sys.stderr)
        return 2
    print(sha256(a.out / "manifest.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
