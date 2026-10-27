"""Dataset graph builder: quads in named graphs, typed literals, RDF 1.2 reifiers.

A port of ``pipelines/corpuslib.G`` (which keeps working unchanged for the
NuSEDS pipeline), with four differences:

* every quad goes into a **named** graph (the default graph is refused);
* quads are de-duplicated as they are added;
* vocabulary IRIs are checked against a :class:`~salmongraph.vocab.VocabIndex`
  for **smn, gcdfo and the PSC CV**, including IRIs inside triple terms;
* output is deterministic (sorted N-Quads / TriG via ``salmongraph.io.det``).

Statement-level provenance uses RDF 1.2 reifiers (ADR-0001 D7)::

    b.reify(xw, s, "skos:closeMatch", o, graph)
    # writes:  <xw> rdf:reifies <<( <s> skos:closeMatch <o> )>> .

A reifier does not assert its triple; pass ``assert_triple=True`` (or add the
triple yourself) when the statement is also asserted. pyshacl (on rdflib)
cannot read triple terms; ``validate.py`` strips them before SHACL.
"""

from __future__ import annotations

import datetime as _dt
import decimal
import hashlib
import math
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Iterator, Mapping, Union

import pyoxigraph as ox

from . import config as _config
from .config import Config
from .io import det

if TYPE_CHECKING:  # pragma: no cover
    from .vocab import VocabIndex

__all__ = ["RDF_REIFIES", "expand", "N", "L", "GraphBuilder", "G", "Term"]

RDF_REIFIES = _config.STATIC_NS["rdf"] + "reifies"
XSD = _config.STATIC_NS["xsd"]

Term = Union[ox.NamedNode, ox.BlankNode, ox.Literal, ox.Triple]


def expand(curie_or_iri: str | None, *, cfg: Config | None = None) -> str | None:
    """CURIE to IRI with the configured prefixes; IRIs pass through.

    Same contract as ``corpuslib.expand``: ``None``, ``""``, ``"nan"`` and
    ``"<NA>"`` give ``None``; an unknown prefix is returned unchanged (and
    then fails as an IRI in :func:`N`).
    """
    if curie_or_iri is None or str(curie_or_iri) in ("", "nan", "<NA>"):
        return None
    s = str(curie_or_iri)
    if s.startswith(("http://", "https://", "urn:")):
        return s
    c = cfg if cfg is not None else _config.current()
    pfx, sep, local = s.partition(":")
    prefixes = c.prefixes
    return prefixes[pfx] + local if sep and pfx in prefixes else s


def N(iri_or_curie: str | ox.NamedNode, *, cfg: Config | None = None) -> ox.NamedNode:
    """A NamedNode from an IRI or a CURIE (``"skos:prefLabel"``)."""
    if isinstance(iri_or_curie, ox.NamedNode):
        return iri_or_curie
    iri = expand(iri_or_curie, cfg=cfg)
    if iri is None:
        raise ValueError(f"cannot make an IRI from {iri_or_curie!r}")
    return ox.NamedNode(iri)


def _plain(value: object) -> object:
    item = getattr(value, "item", None)
    if callable(item) and type(value).__module__.split(".")[0] in ("numpy", "pandas"):
        try:
            return item()
        except (TypeError, ValueError):
            return value
    return value


def L(value: object, dtype: str | None = None, lang: str | None = None) -> ox.Literal:
    """A typed literal, as ``corpuslib.L`` with more types.

    ``bool`` -> xsd:boolean; ``int`` -> xsd:integer; ``float`` -> xsd:double
    (``repr``, so the lexical form is stable; NaN/INF in xsd form);
    ``Decimal`` -> xsd:decimal; ``datetime.date`` -> xsd:date;
    ``datetime.datetime`` -> xsd:dateTime; ``str`` -> plain string. numpy and
    pandas scalars are unwrapped first, so ``np.int64(7)`` is an xsd:integer,
    not the string "7". Missing values (``None``, NaN with no dtype, pandas
    NA) are refused: skip them, never write them.
    """
    value = _plain(value)
    if value is None or type(value).__name__ in ("NAType", "NaTType"):
        raise ValueError("refusing to write a missing value as a literal")
    if lang:
        return ox.Literal(str(value), language=lang)
    if dtype:
        return ox.Literal(str(value), datatype=N(dtype))
    if isinstance(value, bool):
        return ox.Literal("true" if value else "false", datatype=ox.NamedNode(XSD + "boolean"))
    if isinstance(value, int):
        return ox.Literal(str(value), datatype=ox.NamedNode(XSD + "integer"))
    if isinstance(value, float):
        if math.isnan(value):
            raise ValueError("refusing to write NaN as a literal; skip missing values")
        lex = "INF" if value == math.inf else "-INF" if value == -math.inf else repr(value)
        return ox.Literal(lex, datatype=ox.NamedNode(XSD + "double"))
    if isinstance(value, decimal.Decimal):
        return ox.Literal(str(value), datatype=ox.NamedNode(XSD + "decimal"))
    if isinstance(value, _dt.datetime):
        return ox.Literal(value.isoformat(), datatype=ox.NamedNode(XSD + "dateTime"))
    if isinstance(value, _dt.date):
        return ox.Literal(value.isoformat(), datatype=ox.NamedNode(XSD + "date"))
    return ox.Literal(str(value))


class GraphBuilder:
    """Collects quads into named graphs and checks vocabulary IRIs as it goes.

    Parameters
    ----------
    vocab:
        A :class:`~salmongraph.vocab.VocabIndex`. When given, every IRI in the
        smn, gcdfo or PSC namespaces is checked; :meth:`undeclared` lists the
        failures and :meth:`assert_vocab` raises on them. Without it nothing is
        checked (fine for unit tests, never for a build).
    cfg:
        IRI layout for CURIE expansion and serialisation prefixes (default:
        ``config.current()``).

    The builder is append-only, except :meth:`discard`, which only
    ``review.apply_decisions`` uses (a human decision replaces the agent's
    review status). ``quads`` keeps first-insertion order; every writer sorts.
    """

    def __init__(self, vocab: "VocabIndex | None" = None, *, cfg: Config | None = None) -> None:
        self.vocab = vocab
        self.cfg = cfg if cfg is not None else _config.current()
        self._quads: dict[ox.Quad, None] = {}
        self._guarded: set[str] = set()
        #: Targets already given D6 marks (maintained by ``salmongraph.provenance``).
        self.marked: dict[str, str] = {}

    # -- terms --------------------------------------------------------------
    def node(self, x: object) -> ox.NamedNode | ox.BlankNode:
        """Subject term from an IRI, CURIE, NamedNode or BlankNode."""
        if isinstance(x, (ox.NamedNode, ox.BlankNode)):
            return x
        return N(str(x), cfg=self.cfg)

    def term(self, x: object) -> Term:
        """Object term: an RDF term passes through; a string is an IRI or CURIE.

        Use :func:`L` for literals: a bare string is never taken as a literal.
        """
        if isinstance(x, (ox.NamedNode, ox.BlankNode, ox.Literal, ox.Triple)):
            return x
        return N(str(x), cfg=self.cfg)

    @staticmethod
    def bnode(*key: object) -> ox.BlankNode:
        """A blank node with a deterministic label derived from ``key``.

        Include the owning subject in the key (``b.bnode(target, "evidence",
        text)``) so two unrelated nodes never share a label when graphs merge.
        """
        if not key:
            raise ValueError("bnode() needs a key; random blank nodes break determinism")
        h = hashlib.sha256("\x1f".join(str(k) for k in key).encode("utf-8")).hexdigest()
        return ox.BlankNode("b" + h[:24])

    # -- adding -------------------------------------------------------------
    def add(self, s: object, p: object, o: object, graph: str | ox.NamedNode) -> ox.Quad:
        """Add one quad to the named graph ``graph``; returns it."""
        sn = self.node(s)
        pn = N(p, cfg=self.cfg) if not isinstance(p, ox.NamedNode) else p
        on = self.term(o)
        gn = N(graph, cfg=self.cfg) if not isinstance(graph, ox.NamedNode) else graph
        q = ox.Quad(sn, pn, on, gn)
        if q not in self._quads:
            self._quads[q] = None
            self._note(sn), self._note(pn), self._note(on), self._note(gn)
        return q

    def extend(self, quads: Iterable[ox.Quad]) -> None:
        """Add existing quads (each must be in a named graph)."""
        for q in quads:
            if isinstance(q.graph_name, ox.DefaultGraph):
                raise ValueError(f"quad in the default graph: {q}")
            self.add(q.subject, q.predicate, q.object, q.graph_name)

    def discard(self, quads: Iterable[ox.Quad]) -> int:
        """Remove quads; returns how many were present.

        Only for review decisions (``review.apply_decisions``), which replace
        an agent status. Vocabulary IRIs already noted stay checked.
        """
        removed = 0
        for q in quads:
            if q in self._quads:
                del self._quads[q]
                removed += 1
        return removed

    def type(self, s: object, cls: object, graph: str) -> ox.Quad:
        """``s rdf:type cls``."""
        return self.add(s, "rdf:type", cls, graph)

    def label(self, s: object, text: object, graph: str, *, lang: str | None = "en",
              predicate: str = "rdfs:label") -> ox.Quad:
        """A label (default ``rdfs:label``, ``@en``). Use ``lang=None`` for a source's verbatim name."""
        lit = ox.Literal(str(text), language=lang) if lang else ox.Literal(str(text))
        return self.add(s, predicate, lit, graph)

    def reify(self, reifier: str | ox.NamedNode, s: object, p: object, o: object,
              graph: str, *, assert_triple: bool = False) -> ox.NamedNode:
        """Write ``reifier rdf:reifies <<( s p o )>>`` into ``graph``; returns the reifier.

        The reifier must be an IRI, so review decisions can key on it.
        With ``assert_triple=True`` the triple ``s p o`` is asserted in the
        same graph as well.
        """
        r = N(reifier, cfg=self.cfg) if not isinstance(reifier, ox.NamedNode) else reifier
        t = ox.Triple(self.node(s), N(p, cfg=self.cfg) if not isinstance(p, ox.NamedNode) else p,
                      self.term(o))
        if assert_triple:
            self.add(t.subject, t.predicate, t.object, graph)
        self.add(r, RDF_REIFIES, t, graph)
        return r

    # -- vocabulary guard ----------------------------------------------------
    def _note(self, t: object) -> None:
        if isinstance(t, ox.NamedNode):
            if self.vocab is not None and self.vocab.is_guarded(t.value):
                self._guarded.add(t.value)
        elif isinstance(t, ox.Literal):
            self._note(t.datatype)
        elif isinstance(t, ox.Triple):
            self._note(t.subject), self._note(t.predicate), self._note(t.object)

    def undeclared(self) -> list[str]:
        """Sorted smn / gcdfo / PSC IRIs used here that the pinned sources do not declare."""
        if self.vocab is None:
            return []
        return self.vocab.check(self._guarded)

    def assert_vocab(self) -> None:
        """Raise :class:`~salmongraph.vocab.UndeclaredIRIError` if :meth:`undeclared` is not empty."""
        bad = self.undeclared()
        if bad:
            from .vocab import UndeclaredIRIError
            raise UndeclaredIRIError(bad)

    # -- reading -------------------------------------------------------------
    @property
    def quads(self) -> list[ox.Quad]:
        """Unique quads, in first-insertion order (writers sort)."""
        return list(self._quads)

    def __len__(self) -> int:
        return len(self._quads)

    def __iter__(self) -> Iterator[ox.Quad]:
        return iter(list(self._quads))

    def graphs(self) -> dict[str, int]:
        """Quad count per named graph, sorted by graph IRI."""
        counts: dict[str, int] = {}
        for q in self._quads:
            g = q.graph_name.value  # type: ignore[union-attr]
            counts[g] = counts.get(g, 0) + 1
        return {k: counts[k] for k in sorted(counts)}

    def to_store(self, store: ox.Store | None = None) -> ox.Store:
        """Load the quads into ``store`` (a new in-memory store by default)."""
        st = store if store is not None else ox.Store()
        st.extend(self._quads)
        return st

    # -- writing -------------------------------------------------------------
    def nquads(self) -> bytes:
        """Sorted N-Quads bytes."""
        return det.nquads_bytes(self._quads)

    def trig(self, prefixes: Mapping[str, str] | None = None) -> bytes:
        """Sorted TriG bytes with a sorted header of the prefixes used."""
        return det.trig_bytes(self._quads, prefixes if prefixes is not None else self.cfg.prefixes)

    def write_nquads(self, path: str | Path, *, gzip: bool | None = None) -> Path:
        """Write :meth:`nquads` (gzip when ``path`` ends in ``.gz``, mtime 0)."""
        return det.write_bytes(path, self.nquads(), gzip=gzip)

    def write_trig(self, path: str | Path, *, gzip: bool | None = None,
                   prefixes: Mapping[str, str] | None = None) -> Path:
        """Write :meth:`trig` (gzip when ``path`` ends in ``.gz``, mtime 0)."""
        return det.write_bytes(path, self.trig(prefixes), gzip=gzip)


#: Short alias, for code ported from ``corpuslib.G``.
G = GraphBuilder
