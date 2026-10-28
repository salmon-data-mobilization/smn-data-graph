"""Local connected discovery and pure confirmed-source contribution compilation.

``discovery.discover`` queries an already admitted store. The separate
``contribution.preview`` / ``contribution.admit`` functions compile explicitly
selected source understanding to pending RDF with exact-preview consent. They do
not authenticate, verify an SDK runtime, persist or load a store, or publish.

Configuration, review and provenance retain existing namespace/criticality rules.
Callers own fresh permissions, verified native bindings and durable admission.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
