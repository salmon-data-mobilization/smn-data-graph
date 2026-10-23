"""salmongraph: the graph layer of the salmon data corpus.

Staged here (ADR-0001 D3) and written so it can move into metasalmonpy (and
metasalmon, under the mirror contract) after PICES. Read ``INTERFACES.md`` in
this directory before building on it.

Implemented in this first version:

* ``config``     the single source of IRI layout and namespaces;
* ``iri``        minting helpers (``ident()`` and the rest of section 6.2);
* ``vocab``      ``VocabIndex``: the IRI guard over smn, gcdfo and the PSC CV;
* ``graph``      ``GraphBuilder``: quads in named graphs, RDF 1.2 reifiers;
* ``io.det``     deterministic serialisation, sha256, portable paths;
* ``provenance`` ADR-0001 D6 marks on agent-derived content.

Every other module is a documented stub that raises ``NotImplementedError``.
Importing the package imports nothing heavy; import the modules you need.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
