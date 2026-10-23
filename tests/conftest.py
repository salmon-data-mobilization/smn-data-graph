"""Shared fixtures for the salmongraph tests.

The IRI-layout variables (``SALMONGRAPH_BASE``, ``..._PROFILE_BASE``,
``..._SDPV_NS``) are cleared for every test, so each test states the layout it
needs. The vocabulary source variables (``SALMONGRAPH_SMN_TTL``,
``..._GCDFO_TTL``, ``..._PSC_TTL``, ``..._VOCAB_CACHE``, ``..._OFFLINE``) are
left alone: they say where this machine keeps the real vocabularies.

``real_vocab`` loads the real smn, gcdfo and PSC CV once per session. On a
machine with no cache it downloads gcdfo and the PSC CV into
``data/raw/_vocab/`` (git-ignored). If a source cannot be loaded the tests
that need it **fail**: the positive controls are the evidence that the guard
can see the vocabularies at all, so they are never skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "salmongraph"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from salmongraph import config  # noqa: E402
from salmongraph.config import GCDFO_NS, PSC_VOCAB_NS, SMN_NS  # noqa: E402
from salmongraph.vocab import PSC_DOCUMENT_PATTERNS, VocabIndex, VocabSource  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_layout(monkeypatch):
    for name in (config.ENV_BASE, config.ENV_PROFILE_BASE, config.ENV_SDPV_NS):
        monkeypatch.delenv(name, raising=False)
    config.reset()
    yield
    config.reset()


@pytest.fixture(scope="session")
def real_vocab() -> VocabIndex:
    """smn + gcdfo + PSC CV from their configured pins, default layout."""
    return VocabIndex(cfg=config.Config())


def tiny_sources() -> list[VocabSource]:
    """Three small fixture vocabularies with explicit versions (no git, no network)."""
    return [
        VocabSource("smn", SMN_NS, "tiny smn", FIXTURES / "tiny-smn.ttl",
                    ontology_iri="https://w3id.org/smn", version="test-smn"),
        VocabSource("gcdfo", GCDFO_NS, "tiny gcdfo", FIXTURES / "tiny-gcdfo.ttl",
                    ontology_iri="https://w3id.org/gcdfo/salmon", version="test-gcdfo"),
        VocabSource("psc", PSC_VOCAB_NS, "tiny psc", FIXTURES / "tiny-psc.ttl",
                    ontology_iri=PSC_VOCAB_NS, version="test-psc", non_term=PSC_DOCUMENT_PATTERNS),
    ]


@pytest.fixture
def tiny_vocab() -> VocabIndex:
    """The fixture vocabularies under the default layout."""
    return VocabIndex(tiny_sources(), cfg=config.Config(), offline=True)
