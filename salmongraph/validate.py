"""SHACL gate: validate corpus graphs against ``salmongraph/shapes/``. STUB.

The build fails on a violation (ADR-0001 D7). pyshacl 0.40.1 runs on rdflib,
which cannot read RDF 1.2 triple terms, so before validation every quad
``?r rdf:reifies <<( s p o )>>`` is rewritten as
``?r rdf:reifies "<N-Triples of s p o>"`` (a plain literal). Shapes can then
target reifiers with ``sh:targetSubjectsOf rdf:reifies`` and check the
reifier's own properties; they never see inside the triple term
(architecture.md section 10). No other quad is changed.

Validation runs over the union of the given named graphs (default: all),
because a shape on an observation needs the metadata graph's structure
definition. Each violation is reported with the named graph(s) that hold its
focus node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

from ._stub import not_yet

if TYPE_CHECKING:  # pragma: no cover
    import pyoxigraph as ox

__all__ = ["ShaclViolationError", "Violation", "ValidationReport", "for_shacl", "validate",
           "assert_valid"]


@dataclass(frozen=True)
class Violation:
    """One SHACL result."""

    focus: str
    path: str | None
    shape: str
    message: str
    severity: str                       # "Violation" | "Warning" | "Info"
    graphs: tuple[str, ...] = ()        # named graphs holding the focus node


@dataclass
class ValidationReport:
    """Outcome of :func:`validate`. ``conforms`` ignores Warning and Info results."""

    conforms: bool
    violations: list[Violation] = field(default_factory=list)   # sorted by (focus, shape, path)
    text: str = ""                                              # pyshacl's text report


class ShaclViolationError(RuntimeError):
    """Raised by :func:`assert_valid`; carries the report."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__(f"{len(report.violations)} SHACL violation(s)")


def for_shacl(quads: Iterable["ox.Quad"]) -> list["ox.Quad"]:
    """The triple-term rewrite described in the module docstring (pure, deterministic)."""
    raise not_yet("validate.for_shacl")


def validate(data: "Iterable[ox.Quad] | ox.Store", *, shapes: Sequence[Path] | None = None,
             graphs: Sequence[str] | None = None) -> ValidationReport:
    """Validate ``data`` (quads or a store) against ``shapes`` (default ``shapes.shape_files()``)."""
    raise not_yet("validate.validate")


def assert_valid(data: "Iterable[ox.Quad] | ox.Store", *, shapes: Sequence[Path] | None = None,
                 graphs: Sequence[str] | None = None) -> ValidationReport:
    """:func:`validate`, raising :class:`ShaclViolationError` unless it conforms."""
    raise not_yet("validate.assert_valid")
