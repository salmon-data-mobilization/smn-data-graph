"""Closed native metadata references; no observation or biological inference.

The trusted caller supplies separately verified SDK artifacts. These reference
records preserve exact native fields and qualified code identities. They never
turn a code label, a scoped mapping or a method citation into an observed fact.
"""
import json
import pyoxigraph as ox
from . import contribution as c
from . import iri, provenance
from .graph import L

CONTEXT_TYPE = "sdp-native-reference/1"
PENDING_TYPE = "saved-source-pending-mapping/1"
ID_FIELDS = ("columnOrdinal", "columnName", "nativeKey", "label", "vocabularyIri", "termIri", "termType", "description", "authorityName", "authorityVersion", "mappings")
MAPPING_FIELDS = ("mappingSetId", "mappingSetVersion", "licenseIri", "subjectSource", "subjectSourceVersion", "objectSource", "objectSourceVersion", "subjectId", "objectId", "predicateId", "mappingJustification", "mappingSource", "evidenceCitation", "evidenceSha256", "uncertainty", "scopeNote")


def pending_evidence(value):
    """A closed saved-source record, explicitly separate from SDK output/review."""
    c._object(value, ("index", "columnOrdinal", "columnName", "source", "target",
        "predicateIri", "evidence", "uncertainty", "scope", "sourceDecision", "origin"))
    if type(value["index"]) is not int or not 0 <= value["index"] < 256: c._refuse()
    _coordinates(value)
    if value["origin"] != "current-saved-source-mapping" or value["sourceDecision"] not in ("unresolved", "reviewed-scoped"): c._refuse()
    for side in (value["source"], value["target"]):
        c._object(side, ("nativeKey", "termIri", "termType", "authorityName", "authorityVersion", "vocabularyIri", "evidence"))
        for key in ("nativeKey", "authorityName", "authorityVersion"): c._text(side[key])
        for key in ("termIri", "vocabularyIri"): c._iri(side[key])
        if side["termType"] not in ("owl_named_individual", "skos_concept"): c._refuse()
        c._evidence(side["evidence"])
    c._iri(value["predicateIri"]); c._evidence(value["evidence"])
    c._sha(value["evidence"]["sha256"])
    c._text(value["uncertainty"]); _scope(value["scope"], "dataset-identifier")
    return value


def validate_pending(candidate, current):
    rows = current["pendingEvidence"]
    selected = candidate["pendingEvidence"]
    if type(rows) is not list or not 1 <= len(rows) <= 256 or type(selected) is not list or not 1 <= len(selected) <= 256: c._refuse()
    known, previous = {}, -1
    for row in rows:
        pending_evidence(row)
        if row["index"] <= previous: c._refuse()
        previous = row["index"]; known[row["index"]] = row
    previous = -1
    for row in selected:
        pending_evidence(row)
        if row["index"] <= previous or row != known.get(row["index"]): c._refuse("contribution_changed")
        previous = row["index"]


def parse_pending_context(text):
    if not isinstance(text, ox.Literal): return None
    try:
        value = json.loads(text.value)
        c._object(value, ("schema", "row"))
        if value["schema"] != PENDING_TYPE: return None
        pending_evidence(value["row"])
        return value["row"]
    except (ValueError, TypeError, AttributeError, KeyError): return None


def _scope(value, kind, required=True):
    c._object(value, ("kind", "note")); c._text(value["note"], required=required)
    if value["kind"] != kind: c._refuse()


def _procedure(value):
    if value is None: return
    if type(value) is not dict: c._refuse()
    if value.get("kind") == "table-constant":
        c._object(value, ("kind", "protocolIri", "protocolCitation", "methodIri"))
        for key in ("protocolIri", "methodIri"):
            c._text(value[key], required=False)
            if value[key]: c._iri(value[key])
        c._text(value["protocolCitation"], required=False)
    elif value.get("kind") == "record-varying-unresolved":
        c._object(value, ("kind", "columnOrdinal", "columnName")); _coordinates(value)
    else: c._refuse()


def _coordinates(value):
    if type(value["columnOrdinal"]) is not int or not 0 <= value["columnOrdinal"] < 128: c._refuse()
    c._text(value["columnName"], 500)


def _identifier(value):
    c._object(value, ID_FIELDS); _coordinates(value)
    for key in ("nativeKey", "authorityName", "authorityVersion"): c._text(value[key])
    for key in ("label", "description"): c._text(value[key], required=False)
    if value["vocabularyIri"] is not None: c._iri(value["vocabularyIri"])
    if value["termIri"] is None:
        if value["termType"] is not None: c._refuse()
    else:
        c._iri(value["termIri"])
        if value["termType"] not in ("owl_named_individual", "skos_concept"): c._refuse()
    if type(value["mappings"]) is not list or len(value["mappings"]) > 16: c._refuse()
    for mapping in value["mappings"]:
        c._object(mapping, MAPPING_FIELDS)
        for key in MAPPING_FIELDS: c._text(mapping[key])
        for key in ("mappingSetId", "licenseIri", "subjectSource", "objectSource", "subjectId", "objectId", "predicateId", "mappingSource"): c._iri(mapping[key])
        c._sha(mapping["evidenceSha256"])
        if (mapping["subjectId"] != value["termIri"] or mapping["subjectSource"] != value["vocabularyIri"]
                or mapping["subjectSourceVersion"] != value["authorityVersion"]): c._refuse("contribution_changed")


def validate(candidate, current):
    p = current["projection"]; _procedure(p.get("procedure"))
    native_identifiers = p.get("identifiers", [])
    if type(native_identifiers) is not list or len(native_identifiers) > 64: c._refuse()
    slots, sets = set(), set()
    for item in native_identifiers:
        _identifier(item); slot = (item["columnOrdinal"], item["nativeKey"])
        if slot in slots: c._refuse()
        slots.add(slot)
        for mapping in item["mappings"]:
            if mapping["mappingSetId"] in sets or len(sets) >= 256: c._refuse()
            sets.add(mapping["mappingSetId"])
    known = current["identifierUnderstanding"]
    if type(known) is not list or len(known) != len(native_identifiers): c._refuse()
    for index, item in enumerate(known):
        c._object(item, ("index", "evidence", "scope"))
        if type(item["index"]) is not int or item["index"] != index: c._refuse()
        c._evidence(item["evidence"]); _scope(item["scope"], "dataset-identifier", required=False)
    pu = current["procedureUnderstanding"]
    if p.get("procedure") is None:
        if pu is not None: c._refuse()
    else:
        c._object(pu, ("evidence", "scope")); c._evidence(pu["evidence"])
        _scope(pu["scope"], "table" if p["procedure"]["kind"] == "table-constant" else "records")
    selected = candidate["procedure"]
    if selected is not None:
        _selection(selected, p["procedure"], pu)
        if p["procedure"]["kind"] != "table-constant" or not (p["procedure"]["methodIri"] or p["procedure"]["protocolIri"]): c._refuse("unsupported_contribution")
    identifiers = candidate["identifiers"]
    if type(identifiers) is not list or len(identifiers) > 64: c._refuse()
    prior = -1
    for item in identifiers:
        c._object(item, ("index", "annotation", "evidence", "scope", "sourceAuthority", "status")); index = item["index"]
        if type(index) is not int or not prior < index < len(native_identifiers): c._refuse()
        prior = index
        _selection({k:v for k,v in item.items() if k != "index"}, native_identifiers[index], known[index])
        if not item["annotation"]["termIri"]: c._refuse("unsupported_contribution")
    if not (candidate["columns"] or selected or identifiers or candidate.get("pendingEvidence")): c._refuse()
    paths = {f["path"] for f in current["nativeArtifacts"]}
    if ("metadata/codes.csv" in paths) != bool(native_identifiers): c._refuse("contribution_changed")
    semantic = {path for path in paths if path.startswith("metadata/semantic/")}
    if len(semantic) != (len(sets) + 1 if sets else 0) or bool(sets) != ("metadata/semantic/mapping-sets.json" in paths): c._refuse("contribution_changed")
    if candidate["schema"] == "confirmed-source-contribution/3": validate_pending(candidate, current)


def _selection(value, native, understanding):
    c._object(value, ("annotation", "evidence", "scope", "sourceAuthority", "status"))
    if native is None or understanding is None or value["annotation"] != native or any(value[k] != understanding[k] for k in ("evidence", "scope")): c._refuse("contribution_changed")
    c._text(value["scope"]["note"])
    if value["sourceAuthority"] != "depositor_confirmed" or value["status"] != "awaitingReview": c._refuse("unsupported_contribution")


def compile_references(b, candidate, cfg, graph, table, schema, source_record, projection_record):
    dataset, source, review = candidate["dataset"], candidate["source"], candidate["review"]
    generated, pending = set(), []
    def marked(subject, predicate, target, key, selected, context=None):
        assertion = iri.xwalk("confirmed-native-reference", iri.stable_key(dataset["iri"], key, subject, predicate, target, length=64), cfg=cfg)
        generated.add(assertion)
        provenance.mark_statement(b, assertion, subject, predicate, target, graph=graph,
            agent=review["attributionIri"], activity=review["activityIri"], evidence=[selected["evidence"]["citation"], *review["evidence"]],
            confidence=review["confidence"], criticality="critical", assert_triple=False, date=review["date"])
        b.add(assertion, "dcterms:source", source["authorityIri"], graph)
        b.add(assertion, "dcterms:description", L(selected["scope"]["note"]), graph)
        b.add(assertion, "prov:wasDerivedFrom", source_record, graph); b.add(assertion, "prov:wasDerivedFrom", projection_record, graph)
        if selected["evidence"]["sha256"]: b.add(assertion, "dcterms:identifier", L("evidence sha256:" + selected["evidence"]["sha256"]), graph)
        if context:
            b.add(assertion, "dcterms:type", L(CONTEXT_TYPE), graph); b.add(assertion, "prov:value", L(c._wire(context).decode()), graph)
        pending.append((subject, predicate, target))
        return assertion
    def reference(key, parent, target, selected, context):
        node = iri.distribution(dataset["slug"], dataset["version"], key, cfg=cfg); generated.add(node)
        b.type(node, "prov:Entity", graph); b.add(node, "dcterms:isPartOf", parent, graph)
        marked(node, "dcterms:references", target, key, selected, context)
    procedure = candidate["procedure"]
    if procedure:
        p = procedure["annotation"]
        for field, native in (("methodIri", "tables.method_iri"), ("protocolIri", "tables.protocol_iri")):
            if p[field]: reference("native-"+native.rsplit(".", 1)[-1].replace("_", "-"), table, p[field], procedure,
                {"schema": CONTEXT_TYPE, "family": "procedure", "field": native, "scope": "table", "protocolCitation": p["protocolCitation"]})
    for selected in candidate["identifiers"]:
        p = selected["annotation"]; column = iri.column(dataset["slug"], dataset["version"], "source", f"ordinal-{p['columnOrdinal']}", cfg=cfg)
        generated.add(column); b.add(schema, "csvw:column", column, graph); b.type(column, "csvw:Column", graph)
        b.add(column, "csvw:name", L(p["columnName"]), graph); b.add(column, "csvw:number", L(p["columnOrdinal"]+1), graph)
        context = {"schema": CONTEXT_TYPE, "family": "population", "field": "codes.term_iri", "scope": "code-reference",
            **{key:p[key] for key in ("columnOrdinal", "nativeKey", "authorityName", "authorityVersion", "vocabularyIri", "termType")}}
        reference("native-code-"+str(selected["index"]), column, p["termIri"], selected, context)
        for mapping in p["mappings"]:
            selection = {"evidence":{"citation":mapping["evidenceCitation"],"sha256":mapping["evidenceSha256"]},"scope":{"note":mapping["scopeNote"]}}
            assertion = marked(mapping["subjectId"], mapping["predicateId"], mapping["objectId"], "mapping-"+mapping["mappingSetId"], selection)
            b.add(assertion, "prov:value", L(c._wire(mapping).decode()), graph)
    for row in candidate.get("pendingEvidence", []):
        # This is saved source evidence, never relabelled as an SDK-authored file.
        column = iri.column(dataset["slug"], dataset["version"], "source", f"ordinal-{row['columnOrdinal']}", cfg=cfg)
        generated.add(column); b.add(schema, "csvw:column", column, graph); b.type(column, "csvw:Column", graph)
        b.add(column, "csvw:name", L(row["columnName"]), graph); b.add(column, "csvw:number", L(row["columnOrdinal"] + 1), graph)
        assertion = marked(row["source"]["termIri"], row["predicateIri"], row["target"]["termIri"],
            "saved-mapping-" + c._digest(row), row)
        b.add(assertion, "dcterms:isPartOf", column, graph)
        b.add(assertion, "dcterms:type", L(PENDING_TYPE), graph)
        b.add(assertion, "prov:value", L(c._wire({"schema": PENDING_TYPE, "row": row}).decode()), graph)
    return generated, pending


def parse_context(text):
    """Decode only our closed native-field description, not arbitrary RDF policy."""
    if not isinstance(text, ox.Literal): return None
    try:
        value = json.loads(text.value)
        base = ("schema", "family", "field", "scope")
        if value.get("schema") != CONTEXT_TYPE: return None
        if value.get("family") == "procedure":
            c._object(value, (*base, "protocolCitation")); c._text(value["protocolCitation"], required=False)
            if value["field"] not in ("tables.method_iri", "tables.protocol_iri") or value["scope"] != "table": return None
        elif value.get("family") == "population":
            c._object(value, (*base, "columnOrdinal", "nativeKey", "authorityName", "authorityVersion", "vocabularyIri", "termType"))
            if value["field"] != "codes.term_iri" or value["scope"] != "code-reference" or type(value["columnOrdinal"]) is not int or not 0 <= value["columnOrdinal"] < 128: return None
            for key in ("nativeKey", "authorityName", "authorityVersion"): c._text(value[key])
            if value["vocabularyIri"] is not None: c._iri(value["vocabularyIri"])
            if value["termType"] not in ("owl_named_individual", "skos_concept"): return None
        else: return None
        return value
    except (ValueError, TypeError, AttributeError): return None


def match_key(context):
    fields = ("family", "field", "scope") + (("nativeKey", "authorityName", "authorityVersion", "vocabularyIri", "termType") if context["family"] == "population" else ())
    return tuple(context[field] for field in fields)
