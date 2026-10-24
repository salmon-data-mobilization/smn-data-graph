"""Bounded SDP -> RDF compiler behind :mod:`salmongraph.executor`.

The package and saved spec are inputs, not invitations to infer biology. The
observation writer supplies the validated numeric projection and all keys.
Source columns are the local observed variables; their biological concepts,
units and year interpretations can be held as column-level pending statements.
Review acceptance and subsequent materialization are separate operations.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import tempfile

import pyarrow.parquet as pq
import pyoxigraph as ox

from . import __version__, config, iri, provenance
from .graph import GraphBuilder, L, N, expand
from .spec import SpecError, _column_requires_critical_mark, spec_sha256


def _text(value):
    """Metadata blanks are absent, including pandas missing scalar values."""
    from .executor import _obs_missing
    return None if _obs_missing(value) else str(value)


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise SpecError("compiler: explicit build_date must be YYYY-MM-DD")
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise SpecError("compiler: invalid build_date") from exc
    return value


def _child(parent, *parts):
    """Structural nodes remain inside a minted table IRI, with encoded keys."""
    return iri.check_mintable(parent + "/" + "/".join(iri.segment(p) for p in parts))


def compile_dataset_graph(spec, sdp_dir, *, builder, build_date, run=None):
    """Compile declared source facts and interpretations transactionally.

    The caller supplies a vocabulary-guarded builder, saved spec and explicit
    date. Existing semantic extensions are always read with genuine SDK
    validators; absence does not cause a feature to be invented. No package,
    environment, network resource or caller-owned output file is changed.
    """
    if builder.vocab is None:
        raise SpecError("compiler: a pinned VocabIndex is required")
    if builder.vocab.cfg != builder.cfg:
        raise SpecError("compiler: builder and vocabulary configurations differ")
    date = _date(build_date)
    if run is not None:
        _date(run.date)
    with config.override(builder.cfg):
        compiler = _Compiler(spec, Path(sdp_dir), builder, date, run)
        compiler.compile()
        compiler.b.assert_vocab()
        overlap = set(builder.marked) & set(compiler.b.marked)
        if overlap:
            raise SpecError("compiler: review target already marked: " + sorted(overlap)[0])
        # Check pending SPOs against the caller's existing union as well as
        # this staged graph. A failed compilation never partly extends it.
        pending = {r for r, status in compiler.b.marked.items() if status == "awaitingReview"}
        existing = {(q.subject, q.predicate, q.object) for q in builder.quads}
        for q in compiler.b.quads:
            if (isinstance(q.subject, ox.NamedNode) and q.subject.value in pending
                    and isinstance(q.object, ox.Triple)
                    and (q.object.subject, q.object.predicate, q.object.object) in existing):
                raise SpecError("compiler: pending interpretation is already live in caller graph")
        builder.extend(compiler.b.quads)
        builder.marked.update(compiler.b.marked)
        return compiler.graphs


class _Compiler:
    def __init__(self, spec, root, builder, date, run):
        self.spec, self.root, self.date, self.run = spec, root, date, run
        self.b = GraphBuilder(builder.vocab, cfg=builder.cfg)
        self.graphs = iri.dataset_graphs(spec.slug, spec.version)
        self.dataset = iri.dataset(spec.slug, spec.version)
        self.columns = {(t["id"], c["name"]): c for t in spec.tables for c in t["columns"]}
        self.dependencies = {}
        self.bindings = {}
        self.mark_cache = {}
        self.agent = self.agent_activity = None

    def col(self, table, name):
        return iri.column(self.spec.slug, self.spec.version, table, name)

    def gap(self, target, text, graph=None):
        self.b.add(target, "skos:note", L("RDF gap: " + text), graph or self.graphs["metadata"])

    def binding(self, s, p, o, graph, column=None, *, key=None):
        """A semantic link; marks attach to the assertion, never its endpoint."""
        mark = column.get("mark") if column else None
        if not mark:
            self.b.add(s, p, o, graph)
            return True, None
        if self.run is None:
            raise SpecError("compiler: an explicit mark requires the actual AgentRun")
        cache_key = (s, expand(p), str(o), graph)
        if cache_key in self.mark_cache:
            return self.mark_cache[cache_key]
        if self.agent is None:
            self.agent = provenance.ai_agent(self.b, self.run.model, graph=self.graphs["provenance"])
            self.agent_activity = provenance.activity_node(
                self.b, iri.activity("agent-run", self.run.run_id), graph=self.graphs["provenance"],
                label="Recorded semantic interpretation run", date=self.run.date,
                associated_with=[self.agent])
        reifier = iri.xwalk(self.spec.slug, iri.stable_key(self.spec.version, key or "binding", *cache_key))
        status = provenance.mark_statement(
            self.b, reifier, s, p, o, graph=graph, agent=self.agent, activity=self.agent_activity,
            evidence=mark["evidence"], confidence=mark["confidence"],
            criticality=provenance.criticality_of(mark["aspect"]), date=self.run.date)
        self.b.add(s, "prov:wasDerivedFrom", reifier, graph)
        self.mark_cache[cache_key] = (status in provenance.REVIEWED_STATUSES, reifier)
        return self.mark_cache[cache_key]

    def compile(self):
        import metasalmonpy as ms
        from .executor import write_observations

        self.spec_hash = spec_sha256(self.spec)
        # This entry point is callable without the orchestrator's Spec gate.
        # A spelling/description mark cannot govern biological/measurement
        # bindings. Use the Spec gate's classifier so direct compilation has
        # the same conservative scope, without rewriting the actual evidence.
        years = {(block["table"], block.get("year_column")) for block in self.spec.observations}
        for key, column in self.columns.items():
            mark = column.get("mark")
            if (mark and _column_requires_critical_mark(column, referenced_year=key in years)
                    and provenance.criticality_of(mark["aspect"]) != "critical"):
                if key in years:
                    raise SpecError("compiler: a year_column mark governing year basis must be critical")
                raise SpecError(f"compiler: semantic column mark at {key!r} must be critical")
        self.package = ms.read_salmon_datapackage(str(self.root))
        self.frames = self.package["resources"]
        self.package_tables = {}
        for row in self.package["tables"].to_dict("records"):
            table_id = str(row["table_id"])
            if table_id in self.package_tables:
                raise SpecError(f"compiler: duplicate package table {table_id!r}")
            self.package_tables[table_id] = row
        self.dictionary = {}
        for row in self.package["dictionary"].to_dict("records"):
            key = (str(row["table_id"]), str(row["column_name"]))
            if key in self.dictionary:
                raise SpecError(f"compiler: duplicate package dictionary row {key!r}")
            self.dictionary[key] = row
        for key, column in self.columns.items():
            if key not in self.dictionary or key[0] not in self.frames or key[1] not in self.frames[key[0]]:
                raise SpecError(f"compiler: missing package source column {key!r}")
            row = self.dictionary[key]
            for field, package_field in (("concept", "term_iri"), ("unit", "unit_iri")):
                declared, packaged = column.get(field), _text(row.get(package_field))
                if declared and (not packaged or expand(declared) != expand(packaged)):
                    raise SpecError(f"compiler: spec/package {field} disagreement at {key!r}")
            explicit = column.get("decomposition", {})
            for field, package_field in (("property", "property_iri"), ("object_of_interest", "entity_iri"),
                                         ("statistical_modifier", "statistical_modifier_iri")):
                declared, packaged = explicit.get(field), _text(row.get(package_field))
                if declared and packaged and expand(declared) != expand(packaged):
                    raise SpecError(f"compiler: spec/package decomposition {field} disagreement at {key!r}")
            constraints, packaged = explicit.get("constraints", []), _text(row.get("constraint_iri"))
            if constraints and packaged and expand(packaged) not in {expand(v) for v in constraints}:
                raise SpecError(f"compiler: spec/package decomposition constraints disagreement at {key!r}")
        # Validate the shared projection before creating any graph contents.
        # Its temporary file is not an exported artifact or an input rewrite.
        with tempfile.TemporaryDirectory(prefix="salmongraph-projection-") as directory:
            projection = Path(directory) / "observations.parquet"
            write_observations(self.spec, self.frames, projection)
            self.rows = pq.read_table(projection).to_pylist()
        self.extensions(ms)
        self.metadata(ms)
        self.identities()
        self.codes()
        self.decompositions()
        self.mappings(ms)
        self.observations()

    def extensions(self, ms):
        structure_paths = [self.root / "metadata/structure" / n for n in
                           ("observation_structures.csv", "observation_components.csv")]
        self.structures = (ms.read_sdp_observation_structures(self.root)
                           if any(p.exists() for p in structure_paths) else None)
        decomp_paths = [self.root / "metadata/semantic" / n for n in
                        ("measurement-decompositions.csv", "measurement-decompositions.json")]
        self.decomposition_rows = (ms.read_sdp_measurement_decompositions(self.root).to_dict("records")
                                   if any(p.exists() for p in decomp_paths) else [])
        if self.structures is not None:
            # Existing source structures must agree with the declared grain;
            # the compiler does not silently select a competing structure.
            components = self.structures["components"].to_dict("records")
            for block in self.spec.observations:
                for measure in block["measures"]:
                    groups = {}
                    for row in components:
                        if str(row["table_id"]) == block["table"]:
                            groups.setdefault(row["observation_structure_id"], []).append(row)
                    matches = [rows for rows in groups.values() if any(
                        r["component_role"] == "measure" and r["column_name"] == measure for r in rows)]
                    if len(matches) != 1:
                        raise SpecError(f"compiler: package structure is ambiguous/missing for {measure!r}")
                    dims = {r["column_name"] for r in matches[0] if r["component_role"] == "dimension"}
                    required = set(block["dimensions"]) & set(block["key"])
                    required.add(block["year_column"])
                    optional = set(block["dimensions"]) - required
                    attrs = {r["column_name"] for r in matches[0] if r["component_role"] == "attribute"}
                    if dims != required or not optional <= attrs:
                        raise SpecError(f"compiler: package/spec observation grain differs for {measure!r}")

    def metadata(self, ms):
        b, graph, pg = self.b, self.graphs["metadata"], self.graphs["provenance"]
        b.type(self.dataset, "dcat:Dataset", graph)
        b.add(self.dataset, "dcterms:title", L(self.spec.title), graph)
        b.add(self.dataset, "dcterms:description", L(self.spec.description), graph)
        b.add(self.dataset, "dcterms:created", L(self.date, "xsd:date"), graph)
        b.add(self.dataset, "pav:version", L(self.spec.version), graph)
        source = self.spec.source
        for name in ("landing_page", "publisher", "attribution"):
            if not _text(source.get(name)):
                raise SpecError(f"compiler: source.{name} is required")
        if "licence" not in source:
            raise SpecError("compiler: source.licence must explicitly record an IRI or null")
        if source["licence"] is None and source.get("redistribution") == "unconfirmed":
            self.gap(self.dataset, "publication licence and redistribution grant are unconfirmed; private draft only.")
        elif not _text(source["licence"]):
            raise SpecError("compiler: confirmed redistribution requires a real source.licence IRI")
        else:
            b.add(self.dataset, "dcterms:license", expand(source["licence"]), graph)
        b.add(self.dataset, "dcat:landingPage", source["landing_page"], graph)
        publisher = source["publisher"]
        b.add(self.dataset, "dcterms:publisher", publisher if publisher.startswith(("http:", "https:", "urn:")) else L(publisher), graph)
        b.add(self.dataset, "dcterms:rights", L(source["attribution"]), graph)
        if source.get("doi"):
            b.add(self.dataset, "dcterms:identifier", L(source["doi"]), graph)
        b.add(self.dataset, "dcterms:accessRights", L("redistribution " + str(source.get("redistribution", "unconfirmed"))), graph)
        tool = provenance.software_agent(b, "salmongraph", __version__, graph=pg)
        sdk = provenance.software_agent(b, "metasalmonpy", ms.__version__, graph=pg)
        # A version label alone cannot distinguish a source checkout from a
        # release with the same label. Hash the actual executing sources too.
        for node, paths in ((tool, [Path(__file__)]), (sdk, [Path(ms.__file__), Path(ms.__file__).with_name("sssom.py")])):
            digest = hashlib.sha256()
            for path in paths:
                digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes())
            b.add(node, "dcterms:identifier", L("sha256:" + digest.hexdigest()), pg)
        activity = provenance.activity_node(
            b, iri.activity("build", self.spec.slug, self.spec.version, self.date, self.spec_hash),
            graph=pg, label="SDP graph compilation", date=self.date, associated_with=[tool, sdk])
        b.add(self.dataset, "prov:wasGeneratedBy", activity, pg)
        spec_node = iri.distribution(self.spec.slug, self.spec.version, "spec")
        b.type(spec_node, "prov:Entity", pg)
        b.add(spec_node, "dcterms:identifier", L("sha256:" + self.spec_hash), pg)
        b.add(spec_node, "rdfs:label", L("Saved dataset specification"), pg)
        b.add(activity, "prov:used", spec_node, pg)
        for item in source.get("files", []):
            node = iri.distribution(self.spec.slug, self.spec.version, "source-" + iri.stable_key(item["name"]))
            b.type(node, "prov:Entity", pg)
            b.type(node, "dcat:Distribution", graph)
            b.add(self.dataset, "dcat:distribution", node, graph)
            b.add(node, "dcat:downloadURL", item["url"], graph)
            b.add(node, "rdfs:label", L(item["name"]), pg)
            b.add(node, "dcterms:identifier", L("sha256:" + item["sha256"]), pg)
            b.add(node, "prov:hadPrimarySource", item["url"], pg)
            b.add(activity, "prov:used", node, pg)
        # Hash the exact package inputs, using portable paths. Absolute local
        # paths and file mtimes never enter the reproducible graph.
        for path in sorted(self.root.rglob("*")):
            if path.is_symlink():
                raise SpecError("compiler: package input symlinks are unsupported")
            if not path.is_file() or path.name.startswith("."):
                continue
            relative = path.relative_to(self.root).as_posix()
            node = iri.distribution(self.spec.slug, self.spec.version, "sdp-" + iri.stable_key(relative))
            b.type(node, "prov:Entity", pg)
            b.add(node, "dcterms:identifier", L("sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()), pg)
            b.add(node, "rdfs:label", L(relative), pg)
            b.add(activity, "prov:used", node, pg)
        b.extend(b.vocab.provenance(pg))
        for key in sorted(b.vocab.pins):
            b.add(activity, "prov:used", b.vocab.graph_iri(key), pg)
        for table in self.spec.tables:
            table_id = table["id"]
            node = iri.table(self.spec.slug, self.spec.version, table_id)
            b.type(node, "csvw:Table", graph)
            schema = _child(node, "schema")
            b.type(schema, "csvw:Schema", graph)
            b.add(node, "csvw:tableSchema", schema, graph)
            b.add(self.dataset, "dcterms:hasPart", node, graph)
            packaged_file = _text(self.package_tables.get(table_id, {}).get("file_name"))
            if not packaged_file:
                raise SpecError(f"compiler: missing package file_name for {table_id!r}")
            b.add(node, "csvw:url", L(packaged_file), graph)
            b.add(node, "dcterms:identifier", L(table_id), graph)
            for column in table["columns"]:
                name, col = column["name"], self.col(table_id, column["name"])
                row = self.dictionary[(table_id, name)]
                b.add(schema, "csvw:column", col, graph)
                b.type(col, "csvw:Column", graph)
                b.add(col, "csvw:name", L(name), graph)
                b.add(col, "csvw:datatype", L(column["datatype"]), graph)
                for field, package_field, predicate in (("label", "column_label", "csvw:title"),
                                                          ("description", "column_description", "dcterms:description")):
                    value = column.get(field) or _text(row.get(package_field))
                    if value:
                        # A column's mark also governs explicit label text;
                        # source-native names and identifiers remain direct.
                        self.binding(col, predicate, L(value), graph, column if column.get(field) else None)
                self.dependencies[(table_id, name)] = {col}
                for field, predicate in (("concept", "qb:concept"), ("unit", "qudt:unit"),
                                         ("method", "sosa:usedProcedure")):
                    value = column.get(field)
                    if value:
                        live, reifier = self.binding(col, predicate, expand(value), graph, column)
                        self.bindings[(table_id, name, field)] = live
                        if reifier:
                            self.dependencies[(table_id, name)].add(reifier)
                if column.get("estimate_type"):
                    self.gap(col, "estimate_type retained in Parquet; no generic RDF classification predicate is declared.")
                if column.get("age_notation"):
                    self.gap(col, "age_notation retained in the saved spec; no generic RDF age-notation predicate is declared.")

    def identities(self):
        from .executor import _obs_key, _obs_missing
        b, graph = self.b, self.graphs["identity"]
        for identity in self.spec.identity:
            table, name = identity["table"], identity["column"]
            column = self.columns[(table, name)]
            frame = self.frames[table]
            for values in frame.itertuples(index=False, name=None):
                row = dict(zip(frame.columns, values))
                if _obs_missing(row[name]):
                    continue
                value = _obs_key(row[name], column, f"{table}.{name}")
                node = iri.ident(identity["kind"], identity["authority"], value)
                b.type(node, "prov:Entity", graph)
                b.add(node, "dcterms:identifier", L(str(value)), graph)
                b.add(node, "prov:wasDerivedFrom", self.col(table, name), graph)
                # kind is an IRI-layout token, not an inferred biological class.
                if identity.get("label_column"):
                    label = _text(row[identity["label_column"]])
                    if label:
                        self.binding(node, "rdfs:label", L(label), graph,
                                     self.columns[(table, identity["label_column"])])

    def codes(self):
        from .executor import _source_code_iri
        b, graph = self.b, self.graphs["mappings"]
        self.source_codes = set()
        for (table, name), column in sorted(self.columns.items()):
            codes = dict(column.get("codes", {}))
            package_codes = self.package.get("codes")
            rows = [] if package_codes is None else [r for r in package_codes.to_dict("records")
                    if str(r["table_id"]) == table and str(r["column_name"]) == name]
            for row in rows:
                codes.setdefault(str(row["code_value"]), _text(row.get("term_iri")))
            for value, target in sorted(codes.items()):
                node = _source_code_iri(self.spec.slug, table, name, value)
                scheme = iri.check_mintable(node.rsplit("/", 1)[0])
                b.type(scheme, "skos:ConceptScheme", graph)
                b.type(node, "skos:Concept", graph)
                b.add(node, "skos:inScheme", scheme, graph)
                b.add(node, "skos:notation", L(value), graph)
                b.add(node, "prov:wasDerivedFrom", self.col(table, name), graph)
                self.source_codes.add(node)
                for row in rows:
                    if str(row["code_value"]) == value:
                        for field, predicate in (("code_label", "skos:prefLabel"), ("code_description", "skos:definition")):
                            if _text(row.get(field)):
                                b.add(node, predicate, L(row[field]), graph)
                if target is None or expand(target) == expand("sssom:NoTermFound"):
                    self.gap(node, "source code has no target mapping; source identity is preserved.", graph)
                else:
                    # A target field is not a declared match predicate. Actual
                    # SSSOM below supplies exact/broad/close/narrow relations.
                    self.gap(node, "target-only code binding has no mapping predicate; use an explicit SSSOM row.", graph)

    def decompositions(self):
        b, graph = self.b, self.graphs["metadata"]
        roles = {"property": "iop:hasProperty", "entity": "iop:hasObjectOfInterest",
                 "constraint": "iop:hasConstraint", "statistical_modifier": "iop:hasStatisticalModifier",
                 "unit": "qudt:unit"}
        for (table, name), column in self.columns.items():
            if not column.get("concept"):
                continue
            variable = self.col(table, name)
            explicit = column.get("decomposition", {})
            parts = [("property", explicit.get("property")), ("entity", explicit.get("object_of_interest")),
                     ("statistical_modifier", explicit.get("statistical_modifier")),
                     *(("constraint", v) for v in explicit.get("constraints", []))]
            row = self.dictionary[(table, name)]
            parts.extend((role, _text(row.get(field))) for field, role in
                         (("property_iri", "property"), ("entity_iri", "entity"),
                          ("constraint_iri", "constraint"), ("statistical_modifier_iri", "statistical_modifier")))
            for role, target in parts:
                if target:
                    b.type(variable, "iop:Variable", graph)
                    self.binding(variable, roles[role], expand(target), graph, column)
        for row in self.decomposition_rows:
            table, name = str(row["table_id"]), str(row["column_name"])
            if (table, name) not in self.columns:
                continue
            variable, role = self.col(table, name), row["component_role"]
            if expand(row["measurement_concept_iri"]) != expand(self.columns[(table, name)].get("concept")):
                raise SpecError(f"compiler: decomposition measurement concept differs from source field {(table, name)!r}")
            b.type(variable, "iop:Variable", graph)
            if row["component_status"] == "gap":
                self.gap(self.col(table, name), f"decomposition {role}: {row['component_label']}; {row['rationale']}")
            elif _text(row.get("component_relation")):
                # Preserve ordered relationships in the validated package;
                # flat I-ADOPT triples would erase their dimension context.
                self.gap(self.col(table, name), "ordered decomposition relationship retained in SDP; not flattened into an ambiguous RDF edge.")
            else:
                self.binding(variable, roles[role], row["component_iri"], graph, self.columns[(table, name)])

    def mappings(self, ms):
        path = self.root / "metadata/semantic/mapping-sets.json"
        if not path.exists():
            return
        ms.validate_sdp_sssom(self.root)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        b, graph = self.b, self.graphs["mappings"]
        for entry in manifest["mapping_sets"]:
            mapping_set = ms.read_sssom_mapping_set(self.root / entry["path"])
            curies = mapping_set.metadata.get("curie_map", {})
            def full(value):
                value = str(value)
                prefix, sep, local = value.partition(":")
                return curies[prefix] + local if sep and prefix in curies else expand(value)
            for row in mapping_set.mappings.to_dict("records"):
                subject, predicate, target = (full(row[k]) for k in ("subject_id", "predicate_id", "object_id"))
                reifier = iri.xwalk(self.spec.slug, iri.stable_key(
                    self.spec.version, entry["mapping_set_id"], subject, predicate, target,
                    row["mapping_justification"]))
                if target == expand("sssom:NoTermFound"):
                    self.gap(subject, "SSSOM explicitly records NoTermFound; no equivalence is asserted.", graph)
                    continue
                agent_based = full(row["mapping_justification"]) == expand("semapv:AgentBasedMatching")
                if agent_based:
                    # The current build's run is not evidence of the original
                    # agent's identity, confidence or review decision. Keep a
                    # literal source inventory, never an incomplete semantic
                    # reifier that would appear to meet D6.
                    inventory = iri.distribution(self.spec.slug, self.spec.version, "unadmitted-" + iri.stable_key(reifier))
                    b.type(inventory, "prov:Entity", self.graphs["metadata"])
                    b.add(inventory, "prov:wasDerivedFrom", entry["mapping_set_id"], self.graphs["metadata"])
                    b.add(inventory, "prov:value", L(json.dumps(row, sort_keys=True, ensure_ascii=False)), self.graphs["metadata"])
                    self.gap(inventory, "inherited AgentBasedMatching row lacks its own D6 run/evidence; alignment is retained in SDP and source inventory only.")
                    continue
                b.reify(reifier, subject, predicate, target, graph, assert_triple=True)
                b.add(reifier, "sssom:mapping_justification", full(row["mapping_justification"]), graph)
                b.add(reifier, "prov:wasDerivedFrom", entry["mapping_set_id"], graph)
                for field, prop in (("author_id", "sssom:author_id"), ("comment", "rdfs:comment")):
                    if _text(row.get(field)):
                        # Multi-valued SSSOM author strings remain lossless
                        # literal metadata, not guessed person identities.
                        b.add(reifier, prop, L(row[field]), graph)

    def observations(self):
        from .executor import _obs_key
        b, graph, metadata = self.b, self.graphs["cube"], self.graphs["metadata"]
        projected = {row["obs_iri"]: row for row in self.rows}
        emitted = set()
        for block in self.spec.observations:
            table, year = block["table"], block["year_column"]
            table_node = iri.table(self.spec.slug, self.spec.version, table)
            columns = {c["name"]: c for t in self.spec.tables if t["id"] == table for c in t["columns"]}
            for measure in block["measures"]:
                column, variable = columns[measure], self.col(table, measure)
                concept = expand(column["concept"])
                dataset = _child(table_node, "cube", iri.stable_key(measure, *block["key"], *block["dimensions"]))
                dsd, year_component = _child(dataset, "structure"), _child(dataset, "structure", "year")
                b.type(dataset, "qb:DataSet", graph)
                b.add(self.dataset, "dcterms:hasPart", dataset, graph)
                b.add(dataset, "qb:structure", dsd, graph)
                b.type(dsd, "qb:DataStructureDefinition", graph)
                b.type(variable, "qb:MeasureProperty", metadata)
                measure_component = _child(dsd, "measure")
                b.add(dsd, "qb:component", measure_component, graph)
                b.type(measure_component, "qb:ComponentSpecification", graph)
                b.add(measure_component, "qb:measure", variable, graph)
                b.add(dsd, "qb:component", year_component, graph)
                b.type(year_component, "qb:ComponentSpecification", graph)
                year_mark = columns[year] if columns[year].get("mark") else column
                year_live, year_reifier = self.binding(year_component, "qb:dimension", expand(column["year_basis"]), graph, year_mark)
                for source_col in (self.col(table, year), variable):
                    b.add(year_component, "prov:wasDerivedFrom", source_col, graph)
                dimension_components = []
                for dimension in block["dimensions"]:
                    if dimension == year:
                        continue
                    prop, comp = self.col(table, dimension), _child(dsd, "dimension", dimension)
                    required = dimension in block["key"]
                    b.type(prop, "qb:DimensionProperty" if required else "qb:AttributeProperty", metadata)
                    b.add(dsd, "qb:component", comp, graph)
                    b.type(comp, "qb:ComponentSpecification", graph)
                    b.add(comp, "qb:dimension" if required else "qb:attribute", prop, graph)
                    if not required:
                        b.add(comp, "qb:componentRequired", L(False), graph)
                    dimension_components.append(dimension)
                for field, name in column.get("uncertainty", {}).items():
                    if name is not None:
                        prop, comp = self.col(table, name), _child(dsd, "attribute", name)
                        b.type(prop, "qb:AttributeProperty", metadata)
                        b.add(dsd, "qb:component", comp, graph)
                        b.type(comp, "qb:ComponentSpecification", graph)
                        b.add(comp, "qb:attribute", prop, graph)
                        b.add(comp, "qb:componentRequired", L(False), graph)
                        if field != "standard_error":
                            self.gap(prop, f"{field} source values and Parquet binding preserved; no generic RDF uncertainty relation is declared.")
                for values in self.frames[table].itertuples(index=False, name=None):
                    source = dict(zip(self.frames[table].columns, values))
                    keys = [_obs_key(source[name], columns[name], f"{table}.{name}") for name in block["key"]]
                    node = iri.obs(self.spec.slug, self.spec.version, *keys, concept)
                    row = projected.get(node)
                    if row is None:
                        continue
                    emitted.add(node)
                    b.type(node, "qb:Observation", graph)
                    b.type(node, "sosa:Observation", graph)
                    b.add(node, "qb:dataSet", dataset, graph)
                    b.add(node, "sosa:observedProperty", variable, graph)
                    b.add(node, "sosa:hasSimpleResult", L(row["value"]), graph)
                    b.add(node, variable, L(row["value"]), graph)
                    for name in block["key"]:
                        if name not in block["dimensions"]:
                            value = _obs_key(source[name], columns[name], f"{table}.{name}")
                            b.add(node, self.col(table, name), L(value), graph)
                    # Raw year is source fact, without implying which salmon
                    # calendar the source field denotes.
                    year_literal = L(_gyear(row["year"]), "xsd:gYear")
                    b.add(node, self.col(table, year), year_literal, graph)
                    if year_live:
                        b.add(node, row["year_basis_iri"], year_literal, graph)
                    if self.bindings.get((table, measure, "unit")):
                        b.add(node, "qudt:unit", row["unit_iri"], graph)
                    if row["method_iri"] and self.bindings.get((table, measure, "method")):
                        b.add(node, "sosa:usedProcedure", row["method_iri"], graph)
                    for dimension in dimension_components:
                        target = row[dimension + "_iri"]
                        if target is not None:
                            b.add(node, self.col(table, dimension), target, graph)
                    dependencies = set(block["key"]) | set(block["dimensions"]) | {measure}
                    for field, name in column.get("uncertainty", {}).items():
                        if name is not None and row.get(field) is not None:
                            b.add(node, self.col(table, name), L(row[field]), graph)
                            dependencies.add(name)
                            if field == "standard_error" and not columns[name].get("mark"):
                                b.add(node, "qudt:standardUncertainty", L(row[field]), graph)
                    for name in sorted(dependencies):
                        for dependency in sorted(self.dependencies[(table, name)]):
                            b.add(node, "prov:wasDerivedFrom", dependency, graph)
                    b.add(node, "prov:wasDerivedFrom", year_component, graph)
                    if year_reifier:
                        b.add(node, "prov:wasDerivedFrom", year_reifier, graph)
        if emitted != set(projected):
            raise SpecError("compiler: RDF observation keys differ from the shared Parquet projection")


def _gyear(year):
    """Stable XML Schema gYear lexical form, preserving the source integer."""
    return ("-" if year < 0 else "") + str(abs(year)).zfill(4)
