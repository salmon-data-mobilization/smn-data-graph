"""Declarative dataset specifications: ``specs/<slug>.yaml`` (ADR-0001 D11). STUB.

A spec says everything the shared executor needs to turn a source into a
Salmon Data Package, dataset graphs and Parquet, so that agents write and
justify YAML and the executor, not the agent, writes the RDF. The YAML keys
below are the contract between this module and ``executor.py``; this module
owns parsing, defaults and validation.

File location: ``specs/<slug>.yaml`` at the repository root (one file per
dataset; ``slug`` is a kebab name, never ``corpus`` or ``vocab``).

YAML shape (``spec_version: 1``; every IRI may be a CURIE with a
``config.STATIC_NS`` prefix or ``corp:``)::

    spec_version: 1
    slug: psc-fraser-sr
    version: "2026.05.07"            # the source's version; part of every IRI
    title: "..."
    description: "..."
    source:
      publisher: "Pacific Salmon Commission"
      landing_page: https://...
      doi: 10.xxxx/yyyy                # optional
      licence: https://creativecommons.org/licenses/by/4.0/
      redistribution: confirmed        # or "unconfirmed": never in a public release (D2)
      attribution: "..."
      files:
        - {name: sr_summary.csv, url: https://..., sha256: <hex>}
    parser: csv                        # csv | xlsx | "module:function" for bespoke parsing (D11)
    tables:
      - id: sr_summary
        file: sr_summary.csv
        keys: [production_stock_code, brood_year]
        columns:
          - name: total_broodyr_EFS
            role: measure              # identifier | dimension | measure | attribute
            label: "..."
            description: "..."         # from the source; "[agent] ..." when written by the agent
            datatype: number
            concept: psc:PSC-CV-000035 # compound variable: PSC, gcdfo or corp: profile concept
            decomposition:             # I-ADOPT, only when the concept is a corp: profile concept
              property: smn:Abundance
              object_of_interest: smn:Stock
              constraints: [smn:BroodYearBasis, corp:constraint/female]   # atomic parts only
              statistical_modifier: null
            unit: unit:NUM
            year_basis: smn:broodYear  # or smn:returnYear
            age_notation: null         # smn:GilbertRichAgeNotation | smn:EuropeanAgeNotation
            estimate_type: null        # gcdfo concept, when the source states one
            method: null               # gcdfo method concept (ADR-0001 D13)
            uncertainty: {standard_error: null, cv: null, lower: null, upper: null}  # column names
            codes: {}                  # source code value -> vocabulary IRI (or null = gap)
            mark:                      # present when the semantics are agent-derived (D6)
              aspect: measure-counts   # provenance.CRITICAL_ASPECTS / NON_CRITICAL_ASPECTS
              confidence: high
              evidence: ["PSC SR documentation p. 4: ...", https://...]
    identity:
      - {table: sr_summary, column: production_stock_code, kind: stock, authority: psc-frsk,
         label_column: stock_name, species: Sockeye}
    observations:
      - table: sr_summary
        key: [production_stock_code, brood_year]   # + the measure, added by the executor
        dimensions: [production_stock_code, brood_year]
        measures: [total_broodyr_EFS]
    cross_source_checks:
      - id: efs-vs-sasap-total
        other: sasap-sockeye-brood
        join: stock                     # via the crosswalk graph
        measure: total_broodyr_EFS
        other_measure: TotalEscapement
        tolerance: 0.005
        expect: "SASAP TotalEscapement equals PSC EFS for 18 Fraser stocks"
    term_requests:                      # atomic gaps only (smn ADR-0002 decision 6)
      - {profile_concept: corp:constraint/female, says: "...", mint_in: smn, columns: [...]}

Rules ``validate_spec`` enforces (each failure is a message, not an exception):
every vocabulary IRI is declared at its pin (``VocabIndex.check``); no
compound variable is given an smn or gcdfo IRI it does not have; every
measure has a unit and a year basis; every age-class column has an age
notation; ``redistribution`` is present; each ``mark`` has a known aspect, a
confidence and at least one evidence item; no ``def:`` IRI anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from ._stub import not_yet
from .config import ROOT

if TYPE_CHECKING:  # pragma: no cover
    from .vocab import VocabIndex

__all__ = ["SPEC_VERSION", "SPECS_DIR", "SpecError", "DatasetSpec", "spec_path", "load_spec",
           "validate_spec", "spec_sha256"]

SPEC_VERSION = 1
#: ``specs/`` at the repository root.
SPECS_DIR = ROOT / "specs"


class SpecError(ValueError):
    """A spec cannot be parsed into a :class:`DatasetSpec` (malformed YAML or missing keys)."""


@dataclass(frozen=True)
class DatasetSpec:
    """A parsed spec. Field names follow the YAML keys in the module docstring.

    ``source``, ``tables``, ``identity``, ``observations``,
    ``cross_source_checks`` and ``term_requests`` stay plain mappings/lists in
    this first contract; the spec engineer may replace them with typed
    dataclasses as long as the YAML keys do not change.
    """

    spec_version: int
    slug: str
    version: str
    title: str
    description: str
    source: Mapping[str, Any]
    parser: str
    tables: tuple[Mapping[str, Any], ...]
    identity: tuple[Mapping[str, Any], ...] = ()
    observations: tuple[Mapping[str, Any], ...] = ()
    cross_source_checks: tuple[Mapping[str, Any], ...] = ()
    term_requests: tuple[Mapping[str, Any], ...] = ()
    path: Path | None = field(default=None, compare=False)

    @property
    def public(self) -> bool:
        """True only when ``source.redistribution == "confirmed"`` (ADR-0001 D2)."""
        return self.source.get("redistribution") == "confirmed"


def spec_path(slug: str) -> Path:
    """``specs/<slug>.yaml`` for a dataset slug."""
    raise not_yet("spec.spec_path")


def load_spec(path_or_slug: str | Path) -> DatasetSpec:
    """Parse ``specs/<slug>.yaml`` (or a path) into a :class:`DatasetSpec`.

    Expands CURIEs with ``config.current().prefixes``; applies defaults;
    raises :class:`SpecError` on malformed input. Does not check vocabulary
    IRIs (that is :func:`validate_spec`).
    """
    raise not_yet("spec.load_spec")


def validate_spec(spec: DatasetSpec, vocab: "VocabIndex") -> list[str]:
    """Problems with ``spec``, one message each, sorted; empty means valid.

    See the module docstring for the rules. The executor refuses to build a
    spec with problems.
    """
    raise not_yet("spec.validate_spec")


def spec_sha256(spec: DatasetSpec) -> str:
    """sha256 of the spec file's bytes, for the build manifest and provenance."""
    raise not_yet("spec.spec_sha256")
