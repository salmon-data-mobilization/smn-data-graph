"""Read-only connected discovery over an already admitted local graph store.

The supported entrypoint is ``salmongraph.discovery.discover``. Configuration,
review, provenance and RDF helpers preserve the existing graph's namespace and
criticality rules; they are internal support for that query.

This standalone package does not build or admit source packages, publish data,
run an SDK bridge, or start a listener. The caller supplies the already admitted
store and enforces fresh permissions and project bindings.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
