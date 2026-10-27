"""Local read-only SPARQL queries over a corpus store (ADR-0001 D8).

The local ``query`` callable supports SELECT/ASK and native SPARQL JSON.
It opens the on-disk store with ``pyoxigraph.Store.read_only`` and queries
an in-memory ``review.view_store`` (reviewed by default, full by explicit
opt-in). Only valid named-graph stores are supported: existing review gates
refuse any stored default-graph quad. The query's default graph is the union
of the view's named graphs. No ledger is applied and no legacy representation
is converted.

HTTP endpoint and CLI: STUB. The planned endpoint binds to ``127.0.0.1``
and uses the SPARQL 1.1 Protocol; no listener is implemented here.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

import pyoxigraph as ox
from pyparsing import ParseBaseException, ParseResults
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue

from .. import review
from .._stub import not_yet

__all__ = ["query", "serve", "main"]


def _check_local_query(sparql: str) -> None:
    """Parse the complete query and refuse network/dataset operations.

    RDFLib's parser expands SPARQL Unicode escapes before parsing. Walk
    every structural child, including subqueries, EXISTS and SILENT SERVICE.
    Inspect ParseResults' positional children before Mapping: ParseResults
    also implements Mapping, but its named values alone omit query nodes.
    No query evaluation or external resource loading occurs in this parser.
    """
    if not isinstance(sparql, str) or not sparql.strip():
        raise ValueError("query: sparql must be a nonempty SELECT/ASK string")
    try:
        parsed = parseQuery(sparql)
    except (ParseBaseException, ValueError, RecursionError) as exc:
        raise ValueError("query: invalid or unsupported SPARQL query") from exc
    if parsed[1].name not in ("SelectQuery", "AskQuery"):
        raise NotImplementedError("query: only SELECT and ASK results are supported; "
                                  "CONSTRUCT/DESCRIBE have no supported result contract")
    pending, seen = [parsed], set()
    while pending:
        node = pending.pop()
        if isinstance(node, (Mapping, ParseResults, list, tuple)):
            if id(node) in seen:
                continue
            seen.add(id(node))
        if isinstance(node, CompValue):
            if node.name == "ServiceGraphPattern":
                raise ValueError("query: SERVICE is disabled for local offline queries")
            if node.name == "DatasetClause":
                raise ValueError("query: FROM dataset clauses are disabled for local offline queries")
        if isinstance(node, ParseResults):
            pending.extend(node)
            pending.extend(node.values())
        elif isinstance(node, Mapping):
            pending.extend(node.values())
        elif isinstance(node, (list, tuple)):
            pending.extend(node)


def query(store_dir: Path, sparql: str, *, view: str = "reviewed") -> dict[str, Any]:
    """Run a local SELECT/ASK and return PyOxigraph's SPARQL JSON as a dict.

    SERVICE, FROM, updates and unsupported parse forms are refused before
    opening the store. Existing review gates apply without a full-view
    fallback; stored default-graph quads are refused, never filtered out.
    Native serialization preserves RDF terms, unbound variables
    and query ordering; callers use ORDER BY when row order matters.
    CONSTRUCT/DESCRIBE remain unsupported. No source bytes are written.
    """
    _check_local_query(sparql)
    try:
        path = Path(store_dir)
    except (TypeError, ValueError) as exc:
        raise ValueError("query: store_dir must be an existing store directory") from exc
    if not path.is_dir():
        raise ValueError("query: store_dir must be an existing store directory")
    try:
        source = ox.Store.read_only(str(path))
    except (OSError, RuntimeError) as exc:
        raise ValueError("query: could not open an existing read-only Oxigraph store") from exc
    try:
        selected = review.view_store(source, view)
    finally:
        del source
    # The union flag in PyOxigraph also includes stored default-graph facts.
    # An explicit list (even []) implements the promised named-graph union.
    try:
        result = selected.query(sparql, default_graph=list(selected.named_graphs()))
    except SyntaxError as exc:
        raise ValueError("query: invalid or unsupported SPARQL query") from exc
    return json.loads(result.serialize(format=ox.QueryResultsFormat.JSON))


def serve(store_dir: Path, *, host: str = "127.0.0.1", port: int = 7878) -> None:
    """Serve the store read-only until interrupted."""
    raise not_yet("serve.sparql_server.serve")


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m salmongraph.serve.sparql_server STORE_DIR [--host H] [--port P]``."""
    raise not_yet("serve.sparql_server.main")
