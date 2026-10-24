"""Local SHACL shapes for the bounded corpus contract (architecture.md section 10).

The default files are loaded together as one local Turtle shapes graph:
``agent-derived.ttl``, ``assertions.ttl``, ``observations.ttl`` and
``datasets.ttl``. They enforce complete D6 marks, retained source-assertion
provenance, dataset metadata and the live observation structure. The original
quad gate in ``validate.py`` additionally checks pending semantic bindings
and prevents live pending critical statements. Source-dependent abundance,
age, estimate-type and licence interpretations are not scientific approval
from these shapes; vocabulary declaration at a pin remains VocabIndex's job.

The full architecture's intended families (not all implemented here) are::

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

__all__ = ["SHAPES_DIR", "shape_files"]

#: This directory.
SHAPES_DIR = Path(__file__).resolve().parent


def shape_files() -> list[Path]:
    """Every ``*.ttl`` shape file in :data:`SHAPES_DIR`, sorted by name."""
    files = sorted(SHAPES_DIR.glob("*.ttl"), key=lambda p: p.name)
    if not files:
        raise ValueError("no local default SHACL shape files are installed")
    return files
