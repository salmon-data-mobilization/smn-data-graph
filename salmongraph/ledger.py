"""The run ledger: evidence for "describe once, integrate cheaply" (ADR-0001 D12). STUB.

One append-only CSV, ``runs/ledger.csv`` (committed), one row per dataset per
run, written after the run's report. Unlike build outputs, the ledger records
wall time and cost: it is a log of what happened, published with each release
(``dist/corpus-<version>/ledger.csv``).

Breakages are counted by kind: ``toolkit`` (a metasalmonpy / metasalmon
defect), ``vocabulary_gap`` (a needed term missing from smn, gcdfo or the PSC
CV), ``retrieval_miss`` (term search failed to find a term that exists, e.g.
``smn:EuropeanAgeNotation``), ``source_problem`` (the data or its
documentation).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ._stub import not_yet
from .config import ROOT

__all__ = ["LEDGER_PATH", "LEDGER_COLUMNS", "LedgerRow", "append_run", "read_ledger"]

#: ``runs/ledger.csv`` at the repository root.
LEDGER_PATH = ROOT / "runs" / "ledger.csv"
LEDGER_COLUMNS = (
    "run_id", "dataset", "dataset_version", "date", "model", "tool_versions",
    "agent_cost_usd", "agent_wall_minutes", "human_review_minutes",
    "breakages_toolkit", "breakages_vocabulary_gap", "breakages_retrieval_miss",
    "breakages_source_problem", "term_requests", "discrepancies",
    "shacl_violations_first_build", "notes",
)


@dataclass(frozen=True)
class LedgerRow:
    """One ledger row; fields match :data:`LEDGER_COLUMNS` (``tool_versions`` as ``name=version;...``)."""

    run_id: str
    dataset: str
    dataset_version: str
    date: str
    model: str
    tool_versions: str
    agent_cost_usd: float
    agent_wall_minutes: float
    human_review_minutes: float = 0.0
    breakages_toolkit: int = 0
    breakages_vocabulary_gap: int = 0
    breakages_retrieval_miss: int = 0
    breakages_source_problem: int = 0
    term_requests: int = 0
    discrepancies: int = 0
    shacl_violations_first_build: int = 0
    notes: str = ""


def append_run(row: LedgerRow, path: Path = LEDGER_PATH) -> None:
    """Append one row (creating the file with a header); refuses a duplicate (run_id, dataset)."""
    raise not_yet("ledger.append_run")


def read_ledger(path: Path = LEDGER_PATH) -> list[LedgerRow]:
    """All rows, in file order."""
    raise not_yet("ledger.read_ledger")
