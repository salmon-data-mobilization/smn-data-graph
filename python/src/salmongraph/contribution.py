"""Pure confirmed-column preview/compilation; not storage or authorization.

The trusted caller verifies the genuine native artifact and fresh D01 state.
This boundary compares that independently supplied state with a closed explicit
candidate, compiles pending RDF through the existing kernel, and binds consent
to the exact preview. It never reads source files, runs an SDK, or writes a store.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from urllib.parse import urlsplit

import pyoxigraph as ox

from . import config, iri, provenance, review
from .graph import GraphBuilder, L, N
from .io import det

__all__ = ["ContributionError", "preview", "admit"]
MAX_BYTES = 512 * 1024
MAX_GRAPH_BYTES = 4 * 1024 * 1024
_COLUMN_FIELDS = ("columnOrdinal", "columnName", "columnRole", "valueType", "termType", "termIri",
                  "propertyIri", "entityIri", "unitIri", "constraintIri", "statisticalModifierIri")
_IRI_FIELDS = _COLUMN_FIELDS[5:]
_REVISIONS = ("semanticRevision", "documentationRevision", "selectionRevision", "projectRevision")
_BINDING_FIELDS = (*_REVISIONS, "semanticBasisSha256", "semanticStateSha256", "projectionSha256", "nativeArtifactsSha256")
_FILES = {".sdp-package", "data/source.csv", "datapackage.json", "metadata/dataset.csv",
          "metadata/tables.csv", "metadata/column_dictionary.csv"}


class ContributionError(ValueError):
    """Bounded, source-independent refusal; input text never enters errors."""
    def __init__(self, code="invalid_contribution"):
        self.code = code
        super().__init__({"invalid_contribution": "Supply the closed, explicit contribution content and review context.",
            "contribution_changed": "Current source, native binding or confirmed understanding differs; review again.",
            "unsupported_contribution": "This slice accepts private, pending column-concept contributions only.",
            "contribution_preview_changed": "Review and authorize the exact current contribution preview.",
            "contribution_limit": "The contribution exceeds its declared bounded capacity."}[code])


def _refuse(code="invalid_contribution"):
    raise ContributionError(code)


def _object(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        _refuse()
    return value


def _text(value, maximum=4096, *, required=True):
    if type(value) is not str or len(value) > maximum or "\0" in value or required and not value.strip():
        _refuse()
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        _refuse()
    return value


def _sha(value):
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        _refuse()
    return value


def _iri(value):
    _text(value)
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("https", "http", "urn") or parsed.query or parsed.username or parsed.password
                or parsed.scheme != "urn" and not parsed.netloc or any(c.isspace() for c in value)):
            _refuse()
        ox.NamedNode(value)
    except (ValueError, TypeError):
        _refuse()
    return value


def _wire(value, *, sorted_keys=True):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=sorted_keys, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _refuse()


def _digest(value, *, sorted_keys=True):
    return hashlib.sha256(_wire(value, sorted_keys=sorted_keys)).hexdigest()


def _evidence(value):
    _object(value, ("citation", "sha256"))
    _text(value["citation"])
    if value["sha256"] is not None:
        _sha(value["sha256"])


def _scope(value):
    _object(value, ("kind", "note"))
    if value["kind"] != "dataset-column":
        _refuse("unsupported_contribution")
    _text(value["note"])


def _native_column(value):
    _object(value, _COLUMN_FIELDS)
    if type(value["columnOrdinal"]) is not int or not 0 <= value["columnOrdinal"] < 128:
        _refuse()
    _text(value["columnName"], 500)
    for field, allowed in (("columnRole", ("", "identifier", "attribute", "measurement", "temporal", "categorical")),
            ("valueType", ("", "string", "integer", "number", "boolean", "date", "datetime")),
            ("termType", ("", "owl_class", "owl_object_property", "skos_concept"))):
        if type(value[field]) is not str or value[field] not in allowed:
            _refuse()
    for field in _IRI_FIELDS:
        _text(value[field], required=False)
        if value[field]:
            _iri(value[field])


def _artifacts(value):
    if type(value) is not list or len(value) != len(_FILES):
        _refuse("unsupported_contribution")
    paths, size = [], 0
    for record in value:
        _object(record, ("path", "bytes", "sha256"))
        if type(record["path"]) is not str or record["path"] not in _FILES:
            _refuse("unsupported_contribution")
        if type(record["bytes"]) is not int or not 0 <= record["bytes"] <= 32 * 1024 * 1024:
            _refuse()
        _sha(record["sha256"]); paths.append(record["path"]); size += record["bytes"]
    if paths != sorted(_FILES) or size > 32 * 1024 * 1024:
        _refuse()


def _validate(candidate, current, cfg):
    # JSON capacity and exact allowlists apply to both trust sides; no raw table,
    # arbitrary triples, actor IDs or hidden private state can be spread out.
    if len(_wire(candidate)) > MAX_BYTES or len(_wire(current)) > MAX_BYTES:
        _refuse("contribution_limit")
    _object(current, ("schema", "projection", "understanding", "sourceAuthorityIri", *_REVISIONS,
                      "semanticBasisSha256", "semanticStateSha256", "nativeArtifacts"))
    if current["schema"] != "current-d01-contribution/1":
        _refuse()
    p = current["projection"]
    extended = type(p) is dict and p.get("schema") == "confirmed-source-semantics/2"
    p = _object(p, ("schema", "sourceSha256", "vocabulary", "columns", "sharedRelationshipEligible",
                    *(("procedure", "identifiers") if extended else ())))
    if p["schema"] not in ("confirmed-column-semantics/1", "confirmed-source-semantics/2") or p["sharedRelationshipEligible"] is not False:
        _refuse()
    # The current app retains its v2 envelope after clearing the extra families.
    # Accept that exact empty shape, while hashing the ACTUAL v2 projection.
    # Never downgrade it or silently drop nonempty procedure/identifier content.
    if extended and (p["procedure"] is not None or type(p["identifiers"]) is not list or p["identifiers"]):
        _refuse("unsupported_contribution")
    _sha(p["sourceSha256"]); _iri(current["sourceAuthorityIri"])
    vocab = _object(p["vocabulary"], ("id", "sha256")); _text(vocab["id"], 200); _sha(vocab["sha256"])
    if type(p["columns"]) is not list or not 1 <= len(p["columns"]) <= 128:
        _refuse()
    previous, native = -1, {}
    for column in p["columns"]:
        _native_column(column)
        ordinal = column["columnOrdinal"]
        if ordinal <= previous:
            _refuse()
        previous = ordinal; native[ordinal] = column
    understanding = current["understanding"]
    if type(understanding) is not list or len(understanding) != len(native):
        _refuse()
    known = {}
    for column in understanding:
        _object(column, ("columnOrdinal", "evidence", "scope"))
        ordinal = column["columnOrdinal"]
        if type(ordinal) is not int or ordinal not in native or ordinal in known:
            _refuse()
        _evidence(column["evidence"]); _scope(column["scope"]); known[ordinal] = column
    for field in _REVISIONS:
        if type(current[field]) is not int or not 1 <= current[field] <= 2**53 - 1:
            _refuse()
    for field in ("semanticBasisSha256", "semanticStateSha256"):
        _sha(current[field])
    _artifacts(current["nativeArtifacts"])
    _object(candidate, ("schema", "dataset", "source", "audience", "binding", "nativeArtifacts", "columns", "review"))
    if candidate["schema"] != "confirmed-column-contribution/1":
        _refuse()
    dataset = _object(candidate["dataset"], ("slug", "version", "iri"))
    _text(dataset["slug"], 80); _text(dataset["version"], 80); _iri(dataset["iri"])
    try:
        expected = iri.dataset(dataset["slug"], dataset["version"], cfg=cfg)
    except (ValueError, TypeError):
        _refuse()
    if dataset["iri"] != expected:
        _refuse("contribution_changed")
    source = _object(candidate["source"], ("sha256", "authorityIri")); _sha(source["sha256"]); _iri(source["authorityIri"])
    _object(candidate["audience"], ("kind",))
    if candidate["audience"]["kind"] != "private-project":
        _refuse("unsupported_contribution")
    binding = _object(candidate["binding"], _BINDING_FIELDS)
    for field in _REVISIONS:
        if type(binding[field]) is not int or not 1 <= binding[field] <= 2**53 - 1:
            _refuse()
    for field in ("semanticBasisSha256", "semanticStateSha256", "projectionSha256", "nativeArtifactsSha256"):
        _sha(binding[field])
    _artifacts(candidate["nativeArtifacts"])
    expected_binding = {key: current[key] for key in (*_REVISIONS, "semanticBasisSha256", "semanticStateSha256")}
    # These two hashes use the existing D01 JSON.stringify field order, not a
    # silently substituted graph-specific canonicalization or repinned snapshot.
    expected_binding.update(projectionSha256=_digest(p, sorted_keys=False),
                            nativeArtifactsSha256=_digest(current["nativeArtifacts"], sorted_keys=False))
    if (source["sha256"] != p["sourceSha256"] or source["authorityIri"] != current["sourceAuthorityIri"] or binding != expected_binding
            or candidate["nativeArtifacts"] != current["nativeArtifacts"]):
        _refuse("contribution_changed")
    columns = candidate["columns"]
    if type(columns) is not list or not 1 <= len(columns) <= 128:
        _refuse()
    previous = -1
    for column in columns:
        _object(column, ("annotation", "evidence", "scope", "sourceAuthority", "status"))
        annotation = column["annotation"]; _native_column(annotation)
        ordinal = annotation["columnOrdinal"]
        if ordinal <= previous or annotation != native.get(ordinal):
            _refuse("contribution_changed")
        previous = ordinal; _evidence(column["evidence"]); _scope(column["scope"])
        if any(column[key] != known[ordinal][key] for key in ("evidence", "scope")):
            _refuse("contribution_changed")
        if (column["sourceAuthority"] != "depositor_confirmed" or column["status"] != "awaitingReview"
                or not annotation["termIri"] or any(annotation[field] for field in _IRI_FIELDS if field != "termIri")):
            _refuse("unsupported_contribution")
    context = _object(candidate["review"], ("confidence", "attributionIri", "activityIri", "date", "evidence"))
    if type(context["confidence"]) is not str or context["confidence"] not in provenance.CONFIDENCE_LEVELS:
        _refuse()
    _iri(context["attributionIri"]); _iri(context["activityIri"]); _text(context["date"], 40)
    if type(context["evidence"]) is not list or not 1 <= len(context["evidence"]) <= 8:
        _refuse()
    for item in context["evidence"]:
        _text(item)


def _compile(candidate, cfg):
    dataset, source, context = candidate["dataset"], candidate["source"], candidate["review"]
    slug, version = dataset["slug"], dataset["version"]
    graphs = iri.dataset_graphs(slug, version, cfg=cfg)
    mg, pg = graphs["metadata"], graphs["provenance"]
    table = iri.table(slug, version, "source", cfg=cfg)
    schema = iri.distribution(slug, version, "column-schema", cfg=cfg)
    source_record = iri.distribution(slug, version, "confirmed-source", cfg=cfg)
    projection_record = iri.distribution(slug, version, "confirmed-projection", cfg=cfg)
    b = GraphBuilder(cfg=cfg)
    b.extend(provenance.profile_vocabulary(mg, cfg=cfg))
    generated = {dataset["iri"], table, schema, source_record, projection_record, mg, pg}
    b.type(dataset["iri"], "dcat:Dataset", mg)
    b.add(dataset["iri"], "pav:version", L(version), mg)
    b.add(dataset["iri"], "dcterms:source", source["authorityIri"], mg)
    b.add(dataset["iri"], "prov:wasDerivedFrom", source_record, pg)
    b.add(dataset["iri"], "dcterms:hasPart", table, mg)
    b.add(table, "csvw:tableSchema", schema, mg)
    for record, digest in ((source_record, source["sha256"]), (projection_record, candidate["binding"]["projectionSha256"])):
        b.type(record, "prov:Entity", pg); b.add(record, "dcterms:identifier", L("sha256:" + digest), pg)
    used = [source_record, projection_record]
    for index, record in enumerate(candidate["nativeArtifacts"]):
        node = iri.distribution(slug, version, f"native-{index}", cfg=cfg); generated.add(node); used.append(node)
        b.type(node, "prov:Entity", pg)
        b.add(node, "rdfs:label", L(record["path"]), pg)
        b.add(node, "dcterms:identifier", L("sha256:" + record["sha256"]), pg)
    provenance.activity_node(b, context["activityIri"], graph=pg,
        label="Explicit column contribution context; shared review not performed", date=context["date"],
        used=used, associated_with=[context["attributionIri"]])
    pending = []
    for selected in candidate["columns"]:
        annotation = selected["annotation"]
        column = iri.column(slug, version, "source", f"ordinal-{annotation['columnOrdinal']}", cfg=cfg)
        assertion = iri.xwalk("confirmed-column-contribution", iri.stable_key(dataset["iri"], source["sha256"],
            candidate["binding"]["projectionSha256"], annotation["columnOrdinal"], annotation["termIri"], length=64), cfg=cfg)
        generated.update((column, assertion))
        b.add(schema, "csvw:column", column, mg); b.type(column, "csvw:Column", mg)
        b.add(column, "csvw:name", L(annotation["columnName"]), mg)
        b.add(column, "csvw:number", L(annotation["columnOrdinal"] + 1), mg)
        status = provenance.mark_statement(b, assertion, column, "qb:concept", annotation["termIri"], graph=mg,
            agent=context["attributionIri"], activity=context["activityIri"],
            evidence=[selected["evidence"]["citation"], *context["evidence"]], confidence=context["confidence"],
            criticality=provenance.criticality_of("measure-counts"), assert_triple=False, date=context["date"])
        if status != "awaitingReview":
            _refuse()
        b.add(assertion, "dcterms:source", source["authorityIri"], mg)
        b.add(assertion, "dcterms:description", L(selected["scope"]["note"]), mg)
        b.add(assertion, "prov:wasDerivedFrom", source_record, mg)
        b.add(assertion, "prov:wasDerivedFrom", projection_record, mg)
        if selected["evidence"]["sha256"]:
            b.add(assertion, "dcterms:identifier", L("evidence sha256:" + selected["evidence"]["sha256"]), mg)
        pending.append((column, annotation["termIri"]))
    if any(value in generated for value in (source["authorityIri"], context["activityIri"], context["attributionIri"])):
        _refuse()
    if any(annotation["annotation"]["termIri"] in generated for annotation in candidate["columns"]):
        _refuse("unsupported_contribution")
    # Existing review validation, not a parallel acceptance policy. This raises
    # for malformed/missing marks and retains the reifiers without asserting SPOs.
    queue = review.review_queue(b.quads)
    rows = review.view_quads(b.quads)
    if len(queue) != len(pending) or any(q.subject == N(s) and q.predicate == N("qb:concept") and q.object == N(o)
                                       for s, o in pending for q in rows):
        _refuse()
    data = det.nquads_bytes(rows)
    if len(data) > MAX_GRAPH_BYTES:
        _refuse("contribution_limit")
    return data, sorted(generated), len(queue)


def preview(candidate, *, current):
    """Return every proposed byte/record IRI; no source or store I/O occurs.

    ``current`` must come independently from a trusted caller that verified D01
    confirmation, native artifact bytes, evidence freshness and project ACL. It
    is not a browser payload or an attestation made by this module.
    """
    cfg = config.current()
    try:
        _validate(candidate, current, cfg)
        data, generated, pending = _compile(candidate, cfg)
    except ContributionError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, RuntimeError):
        _refuse()
    result = {"schema": "confirmed-column-contribution-preview/1", "candidate": deepcopy(candidate),
        "namespace": {"base": cfg.base, "profileBase": cfg.profile_base, "sdpv": cfg.sdpv},
        "generatedIris": generated, "graph": {"mediaType": "application/n-quads", "content": data.decode("utf-8"),
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}, "pendingRelationships": pending,
        "nativeVerification": "trusted_caller_binding_not_runtime_attestation"}
    return {**result, "sha256": _digest(result)}


def admit(candidate, *, current, consent):
    """Compile exactly reviewed content; persistence/auth/idempotency are external."""
    result = preview(candidate, current=current)
    _object(consent, ("version", "accepted", "previewSha256"))
    if (consent["version"] != "confirmed-column-contribution-consent/1" or consent["accepted"] is not True
            or consent["previewSha256"] != result["sha256"]):
        _refuse("contribution_preview_changed")
    return {"schema": "compiled-column-contribution/1", "graphBytes": result["graph"]["content"].encode("utf-8"),
        "receipt": {"schema": "compiled-column-contribution-receipt/1", "status": "compiled_not_persisted",
            "previewSha256": result["sha256"], "graphSha256": result["graph"]["sha256"],
            "sourceSha256": candidate["source"]["sha256"], "binding": deepcopy(candidate["binding"]),
            "audience": deepcopy(candidate["audience"]), "datasetIri": candidate["dataset"]["iri"],
            "pendingRelationships": result["pendingRelationships"], "sharedRelationshipAccepted": False,
            "nativeVerification": result["nativeVerification"], "authorizationPerformed": False,
            "durabilityProvided": False, "idempotencyProvided": False, "publicationPerformed": False}}
