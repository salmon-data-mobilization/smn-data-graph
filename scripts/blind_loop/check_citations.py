#!/usr/bin/env python3
"""Check that a mapper's quotes and figure values appear in its cited documents.

Reads one mapper case folder (claims.json plus the files it cites) and reports,
for every evidence quote, whether the quote's words appear on the cited PDF
page, on an adjacent page, elsewhere in the document, or not at all. Matching
is on lower-cased alphanumeric tokens, so line breaks, hyphenation and
punctuation do not matter; a near match (token similarity >= 0.85 around a
shared four-word anchor) is reported separately. Figure values are checked the
same way. This checks transcription, not meaning: a found quote can still be
misread. Scanned pages without a text layer are reported as unchecked.
Exit codes: 0 report written, 2 missing or malformed input.
"""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

TOKEN = re.compile(r"[a-z0-9]+")
PAGE = re.compile(r"pdf\s*(?:page|pp?\.?)\s*(\d+)", re.I)


def tokens(text: str) -> list[str]:
    text = text.lower().replace("\u00ad", "")
    text = re.sub(r"-\s*\n\s*", "", text)
    return TOKEN.findall(text)


def pages_of(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True)
        return out.stdout.split("\f") if out.returncode == 0 else []
    if suffix in (".html", ".htm"):
        raw = path.read_text(errors="replace")
        raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
        return [html.unescape(re.sub(r"<[^>]+>", " ", raw))]
    if suffix == ".xlsx":
        with zipfile.ZipFile(path) as z:
            parts = [z.read(n).decode(errors="replace") for n in z.namelist() if n.endswith(".xml")]
        return [re.sub(r"<[^>]+>", " ", " ".join(parts))]
    return [path.read_text(errors="replace")]


def find(quote: list[str], page: list[str]) -> str | None:
    if not quote:
        return None
    hay, needle = " ".join(page), " ".join(quote)
    if f" {needle} " in f" {hay} ":
        return "exact"
    n = len(quote)
    anchors = {tuple(quote[i:i + 4]) for i in range(max(1, n - 3))}
    for i in range(len(page) - 3):
        if tuple(page[i:i + 4]) in anchors:
            lo = max(0, i - n)
            window = page[lo:i + 2 * n]
            m = SequenceMatcher(None, quote, window, autojunk=False)
            matched = sum(b.size for b in m.get_matching_blocks())
            if matched / n >= 0.85:
                return "near"
    return None


RANK = ["exact_on_page", "near_on_page", "adjacent_page", "elsewhere_in_document",
        "cited_page_has_no_text", "not_found", "no_text_layer"]


def locate_quote(text: str, pages: list[list[str]], cited: int | None) -> str:
    """Check each part of a quote elided with '…' or '...'; report the worst part."""
    parts = [tokens(p) for p in re.split(r"…|\.\.\.", text)]
    found = [locate(p, pages, cited) for p in parts if p]
    return max(found, key=RANK.index) if found else "no_quote"


def sparse(page: list[str], pages: list[list[str]]) -> bool:
    """A page with far less text than is usual for its document, such as a scanned table."""
    usual = sorted(len(p) for p in pages)[len(pages) // 2]
    return len(page) < 0.25 * max(usual, 40)


def locate(quote: list[str], pages: list[list[str]], cited: int | None) -> str:
    if not any(pages):
        return "no_text_layer"
    in_range = bool(cited) and 1 <= cited <= len(pages)
    if in_range:
        hit = find(quote, pages[cited - 1])
        if hit:
            return f"{hit}_on_page"
        for adj in (cited - 2, cited):
            if 0 <= adj < len(pages) and find(quote, pages[adj]):
                return "adjacent_page"
    for page in pages:
        if find(quote, page):
            return "elsewhere_in_document"
    if in_range and sparse(pages[cited - 1], pages):
        return "cited_page_has_no_text"
    return "not_found"


def cited_page(item: dict) -> int | None:
    for field in ("pdf_page", "page"):
        if isinstance(item.get(field), int):
            return item[field]
    m = PAGE.search(str(item.get("locator", "")))
    return int(m.group(1)) if m else None


def value_variants(value) -> list[list[str]]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return []
    forms = {str(value)}
    if float(value).is_integer():
        forms |= {str(int(value)), f"{int(value):,}"}
    return [tokens(f) for f in forms]


def by_hash(dirs: list[Path]) -> dict[str, Path]:
    index = {}
    for d in dirs:
        for f in d.rglob("*"):
            if f.is_file() and f.suffix.lower() in (".pdf", ".html", ".htm", ".csv", ".txt", ".xlsx"):
                index.setdefault(hashlib.sha256(f.read_bytes()).hexdigest(), f)
    return index


def check(folder: Path, roots: list[Path], packet: Path | None = None) -> dict:
    claims = json.loads((folder / "claims.json").read_text())
    files: dict[str, Path | None] = {}
    hashes: dict[str, Path] | None = None
    documents = claims.get("documents", [])
    if packet is not None:
        documents = json.loads((packet / "manifest.json").read_text())["documents"]
        roots = [packet, *roots]
    for doc in documents:
        rel = doc.get("file")
        cands = [r / rel for r in [folder, *roots] if rel] if rel else []
        path = next((c for c in cands if c.is_file()), None)
        if path is None and doc.get("sha256"):
            if hashes is None:
                hashes = by_hash([folder, *roots])
            path = hashes.get(doc["sha256"])
        files[doc.get("doc_id")] = path
    cache: dict[str, list[list[str]]] = {}

    def doc_pages(doc_id: str) -> list[list[str]] | None:
        path = files.get(doc_id)
        if path is None:
            return None
        if doc_id not in cache:
            cache[doc_id] = [tokens(p) for p in pages_of(path)]
        return cache[doc_id]

    quotes, values = [], []
    for c in claims.get("claims", []):
        for ev in c.get("evidence", []):
            pages = doc_pages(ev.get("doc_id"))
            text = str(ev.get("quote", ""))
            status = "doc_missing" if pages is None else locate_quote(text, pages, cited_page(ev))
            quotes.append({"claim_id": c.get("claim_id"), "doc_id": ev.get("doc_id"), "status": status})
    for f in claims.get("figures", []):
        pages = doc_pages(f.get("doc_id"))
        variants = value_variants(f.get("value"))
        if pages is None:
            status = "doc_missing"
        elif not variants:
            status = "not_numeric"
        else:
            found = [locate(v, pages, cited_page(f)) for v in variants]
            status = next((s for s in found if s.endswith("on_page")), None) or next(
                (s for s in found if s in ("adjacent_page", "elsewhere_in_document")), found[0])
        values.append({"figure_id": f.get("figure_id"), "doc_id": f.get("doc_id"), "status": status})

    def tally(rows):
        out: dict[str, int] = {}
        for r in rows:
            out[r["status"]] = out.get(r["status"], 0) + 1
        return dict(sorted(out.items()))

    return {"folder": str(folder), "quotes": tally(quotes), "values": tally(values),
            "quote_rows": quotes, "value_rows": values}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("folder", type=Path, help="mapper case folder containing claims.json")
    p.add_argument("--root", type=Path, action="append", default=[],
                   help="extra folder that document 'file' paths may be relative to (repeatable)")
    p.add_argument("--packet", type=Path, help="frozen case packet whose manifest.json lists the documents")
    a = p.parse_args(argv)
    try:
        print(json.dumps(check(a.folder, a.root, a.packet), indent=1))
    except (OSError, json.JSONDecodeError) as e:
        print(f"input error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
