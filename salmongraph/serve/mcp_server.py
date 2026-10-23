"""Agent-facing MCP server over the corpus: SPARQL for meaning, SQL for numbers (ADR-0001 D8). STUB.

Built with the ``mcp`` package (FastMCP), stdio transport by default. Tools:

``sparql(query: str, view: str = "reviewed") -> dict``
    "what does this mean and where is it": read-only SPARQL over the store,
    default graph = union of named graphs; results as SPARQL JSON, capped rows.
``sql(query: str) -> dict``
    "give me the numbers": read-only DuckDB over the release's observation
    Parquet (one view per dataset release, named ``<slug>__<version>``, plus
    ``observations`` over all); SELECT only.
``describe(iri: str, view: str = "reviewed") -> dict``
    every quad about ``iri`` with its graph, its review status and, for
    corpus IRIs, ``iri.parse(iri)``.
``datasets() -> list[dict]``
    the catalog: dataset releases, versions, licences, graph IRIs, counts.
``review_queue(limit: int = 50) -> list[dict]``
    pending review items (``review.review_queue``), critical first.

Every result states the view it came from, and every row derived from an
agent-generated assertion carries its review status (ADR-0001 D6: "the status
is visible in every release and query result"). The server never writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .._stub import not_yet

__all__ = ["TOOLS", "build_server", "main"]

TOOLS = ("sparql", "sql", "describe", "datasets", "review_queue")


def build_server(store_dir: Path, parquet_dir: Path, *, name: str = "salmon-corpus") -> Any:
    """A FastMCP server exposing :data:`TOOLS` over a store and its observation Parquet."""
    raise not_yet("serve.mcp_server.build_server")


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m salmongraph.serve.mcp_server STORE_DIR PARQUET_DIR``."""
    raise not_yet("serve.mcp_server.main")
