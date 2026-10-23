"""VoID + DCAT descriptions of dataset releases, the corpus release and every graph. STUB.

ADR-0001 D7: one combined store with one named graph per dataset release,
described with VoID and DCAT. The descriptions go to the shared ``catalog``
graph (``iri.corpus_graph("catalog", corpus_version)``) and are exported as
``dist/corpus-<version>/void.ttl``.

Pattern::

    <release/2026.10.27> a dcat:Dataset, void:Dataset ;
        dcterms:title "..."@en ; pav:version "2026.10.27" ; dcterms:issued "2026-10-27"^^xsd:date ;
        dcterms:license <...most restrictive applicable...> ;
        void:subset <dataset/psc-fraser-sr/2026.05.07>, ... ;
        prov:wasGeneratedBy <activity/release/2026.10.27> .
    <dataset/psc-fraser-sr/2026.05.07> a dcat:Dataset, void:Dataset ;
        void:subset <graph/psc-fraser-sr/2026.05.07/metadata>, ... ;
        dcterms:license <...> ; dcterms:rights "attribution" .
    <graph/psc-fraser-sr/2026.05.07/metadata> a void:Dataset ; void:triples 1234 .
    <graph/vocab/gcdfo/sha256-...> a void:Dataset ; ... (VocabIndex.provenance)

The named-graph IRI is itself the ``void:Dataset`` describing that graph;
``void:triples`` counts its quads. Counts come from the store, so they are
deterministic for the same inputs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Sequence

from ._stub import not_yet

if TYPE_CHECKING:  # pragma: no cover
    import pyoxigraph as ox

    from .graph import GraphBuilder
    from .vocab import VocabIndex

__all__ = ["graph_triple_counts", "describe_dataset_release", "describe_corpus_release"]


def graph_triple_counts(store: "ox.Store") -> dict[str, int]:
    """Quads per named graph in ``store``, sorted by graph IRI."""
    raise not_yet("catalog.graph_triple_counts")


def describe_dataset_release(builder: "GraphBuilder", *, slug: str, version: str,
                             graphs: Mapping[str, str], counts: Mapping[str, int], graph: str) -> str:
    """VoID/DCAT for one dataset release and its named graphs; returns the dataset IRI.

    The DCAT core (title, licence, attribution, distributions) is already in
    the dataset's own ``metadata`` graph; this adds the VoID structure.
    """
    raise not_yet("catalog.describe_dataset_release")


def describe_corpus_release(builder: "GraphBuilder", *, corpus_version: str, build_date: str,
                            datasets: Sequence[str], shared_graphs: Mapping[str, str],
                            vocab: "VocabIndex", counts: Mapping[str, int], graph: str) -> str:
    """VoID/DCAT for the corpus release; returns ``iri.release(corpus_version)``."""
    raise not_yet("catalog.describe_corpus_release")
