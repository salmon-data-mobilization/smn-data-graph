"""Deterministic serialisation: the same quads give the same bytes, everywhere.

Rules (the corpus determinism contract):

* quads are de-duplicated and sorted by (graph, subject, predicate, object),
  each compared by its N-Triples form, before anything is written;
* TriG gets a prefix header written here (sorted, only the prefixes the
  quads use), because the serialiser's own header order is an
  implementation detail;
* gzip is written with ``mtime=0`` and no file name in the header;
* JSON is written with sorted keys, two-space indent and a final newline;
* CSV uses ``\\n`` line ends and the row order the caller gives (sort first);
* paths written into outputs go through :func:`portable_path`, never absolute.

Blank nodes: labels are written as given. Use deterministic labels
(``GraphBuilder.bnode(key)``); a random ``BlankNode()`` breaks byte identity.

Compressed bytes depend on the zlib build. Record :func:`sha256_bytes` of the
uncompressed content beside the ``.gz`` digest when two machines must agree.
"""

from __future__ import annotations

import csv
import gzip as _gzip
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pyoxigraph as ox

from .. import config as _config

__all__ = [
    "term_key", "quad_key", "sorted_quads", "nquads_bytes", "trig_bytes", "used_prefixes",
    "gzip_bytes", "write_bytes", "write_text", "json_bytes", "write_json", "csv_bytes",
    "write_csv", "sha256_bytes", "sha256_file", "portable_path", "file_record",
]


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------

def term_key(term: object) -> str:
    """N-Triples form of a term (``""`` for the default graph): the sort key."""
    if term is None or isinstance(term, ox.DefaultGraph):
        return ""
    if isinstance(term, ox.Triple):
        return f"<<( {term_key(term.subject)} {term_key(term.predicate)} {term_key(term.object)} )>>"
    return str(term)


def quad_key(q: ox.Quad) -> tuple[str, str, str, str]:
    """Sort key of a quad: graph first, so each named graph is one block."""
    return (term_key(q.graph_name), term_key(q.subject), term_key(q.predicate), term_key(q.object))


def sorted_quads(quads: Iterable[ox.Quad]) -> list[ox.Quad]:
    """Unique quads in canonical order."""
    return sorted(set(quads), key=quad_key)


# --------------------------------------------------------------------------
# RDF
# --------------------------------------------------------------------------

def nquads_bytes(quads: Iterable[ox.Quad]) -> bytes:
    """Sorted N-Quads (RDF 1.2: triple terms as ``<<( s p o )>>``)."""
    return ox.serialize(sorted_quads(quads), format=ox.RdfFormat.N_QUADS)


def _iris(quads: Iterable[ox.Quad]) -> set[str]:
    out: set[str] = set()

    def visit(t: object) -> None:
        if isinstance(t, ox.NamedNode):
            out.add(t.value)
        elif isinstance(t, ox.Literal):
            out.add(t.datatype.value)
        elif isinstance(t, ox.Triple):
            visit(t.subject), visit(t.predicate), visit(t.object)

    for q in quads:
        visit(q.subject), visit(q.predicate), visit(q.object), visit(q.graph_name)
    return out


def used_prefixes(quads: Sequence[ox.Quad], prefixes: Mapping[str, str]) -> dict[str, str]:
    """The entries of ``prefixes`` whose namespace starts at least one IRI in ``quads``."""
    iris = _iris(quads)
    return {k: v for k, v in sorted(prefixes.items()) if any(i.startswith(v) for i in iris)}


def trig_bytes(quads: Iterable[ox.Quad], prefixes: Mapping[str, str] | None = None, *,
               only_used: bool = True) -> bytes:
    """Sorted TriG with a sorted ``@prefix`` header.

    ``prefixes`` defaults to ``config.current().prefixes``. With
    ``only_used`` (the default) the header lists only prefixes the quads use.
    """
    qs = sorted_quads(quads)
    pmap = dict(prefixes if prefixes is not None else _config.current().prefixes)
    if only_used:
        pmap = used_prefixes(qs, pmap)
    else:
        pmap = {k: pmap[k] for k in sorted(pmap)}
    body = ox.serialize(qs, format=ox.RdfFormat.TRIG, prefixes=pmap)
    lines = body.split(b"\n")
    i = 0
    while i < len(lines) and lines[i].startswith(b"@prefix "):
        i += 1
    header = "".join(f"@prefix {k}: <{v}> .\n" for k, v in pmap.items()).encode("utf-8")
    rest = b"\n".join(lines[i:]).lstrip(b"\n")
    return header + (b"\n" if header and rest else b"") + rest


# --------------------------------------------------------------------------
# Bytes on disk
# --------------------------------------------------------------------------

def gzip_bytes(data: bytes, *, level: int = 9) -> bytes:
    """gzip with ``mtime=0`` and no file name: identical input gives identical output."""
    buf = io.BytesIO()
    with _gzip.GzipFile(filename="", mode="wb", fileobj=buf, compresslevel=level, mtime=0) as fh:
        fh.write(data)
    return buf.getvalue()


def write_bytes(path: str | os.PathLike, data: bytes, *, gzip: bool | None = None) -> Path:
    """Write atomically (temp file, then rename). ``gzip=None`` means: if ``path`` ends in ``.gz``."""
    path = Path(path)
    if gzip is None:
        gzip = path.suffix == ".gz"
    if gzip:
        data = gzip_bytes(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; outputs are meant to be shared
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def write_text(path: str | os.PathLike, text: str, *, gzip: bool | None = None) -> Path:
    """UTF-8 text through :func:`write_bytes`."""
    return write_bytes(path, text.encode("utf-8"), gzip=gzip)


def json_bytes(obj: Any) -> bytes:
    """Canonical JSON: sorted keys, two-space indent, UTF-8, final newline."""
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_json(path: str | os.PathLike, obj: Any) -> Path:
    """:func:`json_bytes` written atomically."""
    return write_bytes(path, json_bytes(obj), gzip=False)


def csv_bytes(header: Sequence[str], rows: Iterable[Sequence[object]]) -> bytes:
    """CSV with ``\\n`` line ends, minimal quoting, ``None`` as empty. Rows are written in the order given."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return buf.getvalue().encode("utf-8")


def write_csv(path: str | os.PathLike, header: Sequence[str], rows: Iterable[Sequence[object]]) -> Path:
    """:func:`csv_bytes` written atomically."""
    return write_bytes(path, csv_bytes(header, rows), gzip=False)


# --------------------------------------------------------------------------
# Checksums and paths
# --------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    """Hex sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    """Hex sha256 of a file, read in 1 MiB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def portable_path(path: str | os.PathLike, *, root: str | os.PathLike | None = None) -> str:
    """A path that reads the same on every machine.

    Relative to ``root`` (default: the repository root) when under it, else
    ``~/...`` when under the home directory, else ``<external>/<file name>``,
    so no absolute machine path ever reaches an output. Symlinks are not
    resolved: ``~/code/x`` stays ``~/code/x``.
    """
    p = Path(os.path.abspath(os.fspath(path)))
    base = Path(os.path.abspath(os.fspath(root))) if root is not None else _config.ROOT
    if p.is_relative_to(base):
        return p.relative_to(base).as_posix()
    home = Path(os.path.abspath(os.path.expanduser("~")))
    if p.is_relative_to(home):
        return "~/" + p.relative_to(home).as_posix()
    return "<external>/" + p.name


def file_record(path: str | os.PathLike, *, root: str | os.PathLike | None = None) -> dict[str, Any]:
    """``{"path", "bytes", "sha256"}`` for a manifest; ``path`` is portable."""
    p = Path(path)
    return {"path": portable_path(p, root=root), "bytes": p.stat().st_size, "sha256": sha256_file(p)}
