"""Local read-only SPARQL endpoint over a corpus store (ADR-0001 D8). STUB.

For the demo and early use: an HTTP endpoint following the SPARQL 1.1
Protocol (``GET``/``POST /sparql``, results as SPARQL JSON or CSV) over the
on-disk store ``build/corpus/<version>/store/`` opened read-only
(``pyoxigraph.Store.read_only``). Binds to ``127.0.0.1`` by default; updates
are refused. The ``view`` query parameter selects ``reviewed`` (default) or
``full`` (``review.view_store``). Queries run with the default graph as the
union of all named graphs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .._stub import not_yet

__all__ = ["query", "serve", "main"]


def query(store_dir: Path, sparql: str, *, view: str = "reviewed") -> dict[str, Any]:
    """Run one SELECT/ASK/CONSTRUCT against the store; SPARQL JSON results as a dict."""
    raise not_yet("serve.sparql_server.query")


def serve(store_dir: Path, *, host: str = "127.0.0.1", port: int = 7878) -> None:
    """Serve the store read-only until interrupted."""
    raise not_yet("serve.sparql_server.serve")


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m salmongraph.serve.sparql_server STORE_DIR [--host H] [--port P]``."""
    raise not_yet("serve.sparql_server.main")
