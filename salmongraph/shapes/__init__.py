"""SHACL shapes for the corpus contract (architecture.md section 10). STUB package.

Shape files live in this directory as Turtle, one file per row of the
section 10 table, each file a self-contained shapes graph::

    abundance-columns.ttl     smn:Abundance variables declare object of interest, year basis,
                              unit and documented constraints
    age-columns.ttl           age-class columns declare smn:GilbertRichAgeNotation or
                              smn:EuropeanAgeNotation
    observations.ttl          dataset, measure, value, unit, every DSD dimension; uncertainty
                              numeric and non-negative
    estimates.ttl             estimate type where the source states one
    datasets.ttl              licence, attribution, source checksum, release version
    assertions.ttl            crosswalk and membership reifiers carry evidence, justification,
                              confidence, criticality
    agent-derived.ttl         D6 marks complete and the review status consistent with
                              provenance.review_status; exactly one corp:reviewStatus per target

Shapes reference corp: terms through the profile base of the configuration
they are loaded under; write them with the ``corp:`` prefix and let
``validate.py`` bind it (do not hard-code the base). Vocabulary IRIs in
shapes must pass the guard like any other.
"""

from __future__ import annotations

from pathlib import Path

from .._stub import not_yet

__all__ = ["SHAPES_DIR", "shape_files"]

#: This directory.
SHAPES_DIR = Path(__file__).resolve().parent


def shape_files() -> list[Path]:
    """Every ``*.ttl`` shape file in :data:`SHAPES_DIR`, sorted by name."""
    raise not_yet("shapes.shape_files")
