"""Corpus release packaging: ``dist/corpus-<version>/`` and ``releases/<version>/manifest.json``. STUB.

Every release is versioned and immutable (architecture.md 14). Release
outputs::

    dist/corpus-<version>/              (git-ignored; uploaded by Brett to Zenodo / KNB)
      corpus.trig.gz                    every named graph in the release, sorted, gzip mtime 0
      void.ttl                          the catalog graph (catalog.py)
      observations/<slug>/<dataset-version>.parquet
      schemaorg/<slug>/<dataset-version>.jsonld
      sdp/<slug>/<dataset-version>/     each SDP as built (also published to KNB on its own)
      review-queue.csv                  corpus-wide (review.REVIEW_QUEUE_COLUMNS)
      ledger.csv                        the ledger rows of the included datasets
      ATTRIBUTION.md                    each dataset's licence and attribution, verbatim
      manifest.json                     see below
      SHA256SUMS                        sha256sum format, sorted by path

    releases/<version>/manifest.json    (committed) the same manifest.json, byte for byte

``manifest.json`` (canonical JSON, ``io.det.write_json``)::

    {"corpus_version", "build_date", "base", "profile_base", "public": bool,
     "files": [{"path", "bytes", "sha256", "content_sha256"?}],   # content_sha256: of the
                                                                  # uncompressed bytes of a .gz
     "datasets": [{"slug", "version", "iri", "licence", "redistribution", "build_manifest_sha256"}],
     "excluded": [{"slug", "version", "reason"}],                  # e.g. redistribution unconfirmed
     "vocab_pins": VocabIndex.pins_dict(),
     "tool_versions": {"salmongraph", "metasalmonpy", "pyoxigraph", "pyshacl", "pyarrow", "duckdb", "python"},
     "review_status_counts": review.status_counts(...),
     "graphs": {graph IRI: quad count}}

Licensing (ADR-0001 D2, architecture.md 16): a public release includes only
datasets whose spec says ``redistribution: confirmed``; the rest are listed
under ``excluded`` with the reason. A local release (``public=False``) may
include them and says so in the manifest; it is never uploaded. Derived
graphs carry the most restrictive applicable terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from ._stub import not_yet
from .config import ROOT

if TYPE_CHECKING:  # pragma: no cover
    from .combine import CombineResult

__all__ = ["DIST_DIR", "RELEASES_DIR", "ReleaseResult", "dist_dir", "build_release",
           "verify_release"]

#: ``dist/`` at the repository root (git-ignored).
DIST_DIR = ROOT / "dist"
#: ``releases/`` at the repository root (manifests are committed).
RELEASES_DIR = ROOT / "releases"


@dataclass
class ReleaseResult:
    """What :func:`build_release` wrote."""

    corpus_version: str
    dist_dir: Path
    manifest_path: Path            # releases/<version>/manifest.json
    public: bool
    files: list[dict] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)


def dist_dir(corpus_version: str) -> Path:
    """``dist/corpus-<segment(corpus_version)>/``."""
    raise not_yet("release.dist_dir")


def build_release(combined: "CombineResult", *, build_dirs: Sequence[Path], build_date: str,
                  public: bool = True) -> ReleaseResult:
    """Package a combined corpus as an immutable release; refuses to overwrite an existing one."""
    raise not_yet("release.build_release")


def verify_release(path: Path) -> list[str]:
    """Re-hash every file in a release directory against its manifest; returns problems (empty = good)."""
    raise not_yet("release.verify_release")
