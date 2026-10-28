"""Pure D05 boundary over genuine generated native bytes; all cells are fictional."""
import copy
import csv
import gc
import hashlib
import io
import json
from pathlib import Path
import socket

import pyoxigraph as ox
import pytest

from salmongraph import config, contribution, discovery, iri, provenance, review
from salmongraph.graph import GraphBuilder, L, N
from salmongraph.io import det

FIXTURE = Path(__file__).with_name("fixtures") / "fictional-d01-native.json"
B = "https://example.test/fictional-d05/"


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("D05 must not access a network")
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    yield
    assert attempts == []


@pytest.fixture
def inputs():
    before = (FIXTURE.stat().st_mtime_ns, sha(FIXTURE.read_bytes()))
    value = json.loads(FIXTURE.read_text())
    yield value, value["candidate"], value["current"]
    assert (FIXTURE.stat().st_mtime_ns, sha(FIXTURE.read_bytes())) == before


def consent(preview):
    return {"version": "confirmed-column-contribution-consent/1", "accepted": True,
            "previewSha256": preview["sha256"]}


def admit(candidate, current):
    preview = contribution.preview(candidate, current=current)
    return preview, contribution.admit(candidate, current=current, consent=consent(preview))


def test_actual_native_dictionary_and_complete_grid_are_the_fixture_source(inputs):
    fixture, candidate, current = inputs
    result = fixture["nativeResult"]
    assert result["schema"] == "research-metasalmonpy-package/2"
    assert result["engine"]["sourceCommit"] == "943fe1f50d7ac5b88b8be81250dca2e7aeb0f632"
    assert result["engine"]["pythonFileCount"] == 52
    assert result["networkAttempts"] == 0
    assert result["validation"]["structural"]["status"] == "passed"
    assert result["validation"]["publicationReady"] is False
    files = {f["path"]: f for f in result["files"]}
    for record in current["nativeArtifacts"]:
        data = files[record["path"]]["content"].encode()
        assert len(data) == record["bytes"] and sha(data) == record["sha256"]
    native = list(csv.reader(io.StringIO(files["data/source.csv"]["content"], newline="")))
    assert native == list(csv.reader(io.StringIO(fixture["sourceCsv"], newline="")))
    assert native[1][0] == "001" and native[1][2] == "NO SURVEY"
    assert native[2][1] == "NA" and native[3][1:] == ["", "", ""]
    dictionary = list(csv.DictReader(io.StringIO(files["metadata/column_dictionary.csv"]["content"])))
    column = next(row for row in dictionary if row["column_name"] == "temperature")
    selected = candidate["columns"][0]["annotation"]
    assert (column["term_iri"], column["column_role"], column["value_type"]) == (
        selected["termIri"], selected["columnRole"], selected["valueType"])
    assert current["projection"] == result["confirmedSemantics"]


def test_explicit_preview_is_exact_deterministic_and_does_not_claim_authority(inputs):
    fixture, candidate, current = inputs
    original = copy.deepcopy((candidate, current))
    preview, compiled = admit(candidate, current)
    assert (candidate, current) == original
    assert contribution.preview(candidate, current=current) == preview
    assert contribution.admit(candidate, current=current, consent=consent(preview)) == compiled
    assert preview["candidate"] == candidate
    assert sha(compiled["graphBytes"]) == preview["graph"]["sha256"]
    assert compiled["graphBytes"].decode() == preview["graph"]["content"]
    assert compiled["receipt"]["status"] == "compiled_not_persisted"
    assert compiled["receipt"]["nativeVerification"] == "trusted_caller_binding_not_runtime_attestation"
    assert compiled["receipt"]["audience"] == {"kind": "private-project"}
    assert compiled["receipt"]["sharedRelationshipAccepted"] is False
    assert compiled["receipt"]["authorizationPerformed"] is False
    assert compiled["receipt"]["durabilityProvided"] is False
    assert compiled["receipt"]["idempotencyProvided"] is False
    wire = json.dumps(preview)
    for excluded in ("FICTIONAL_RAW_PRIVATE_CELL", "FICTIONAL_OTHER_PRIVATE_CELL", "NO SURVEY", "private_note", "actorId", "projectId", "sourceVersionId", "modelId"):
        assert excluded not in wire
    for generated in preview["generatedIris"]:
        assert generated in preview["graph"]["content"]
    assert preview["generatedIris"]
    assert fixture["sourceCsv"] not in wire


def v2_empty(candidate, current):
    """Exact current app projection shape after clearing procedure/identifiers.

    This changes fictional current authority metadata only; native fixture bytes
    are unchanged. It is not a fresh SDK runtime or app confirmation attestation.
    """
    old = current["projection"]
    projection = {"schema": "confirmed-source-semantics/2", "sourceSha256": old["sourceSha256"],
        "vocabulary": old["vocabulary"], "columns": old["columns"],
        "procedure": None, "identifiers": [], "sharedRelationshipEligible": False}
    current["projection"] = projection
    current["semanticRevision"] += 2
    current["semanticStateSha256"] = sha(json.dumps({"fictional": "v2-cleared-confirmed-state", "projection": projection},
        ensure_ascii=False, separators=(",", ":")).encode())
    candidate["binding"].update(semanticRevision=current["semanticRevision"], semanticStateSha256=current["semanticStateSha256"],
        projectionSha256=sha(json.dumps(projection, ensure_ascii=False, separators=(",", ":")).encode()))


@pytest.mark.parametrize("version", ["v1", "v2-empty"])
def test_compiled_admission_reopens_in_real_query_with_pending_evidence(inputs, tmp_path, version):
    _, candidate, current = inputs
    if version == "v2-empty":
        v2_empty(candidate, current)
    preview, compiled = admit(candidate, current)
    rows = list(ox.parse(compiled["graphBytes"], format=ox.RdfFormat.N_QUADS))
    queue = review.review_queue(rows)
    assert len(queue) == 1 and queue[0].status == "awaitingReview" and queue[0].criticality == "critical"
    assert queue[0].confidence == "high" and queue[0].evidence
    assert "humanAccepted" not in {row.status for row in queue}
    subject = next(q.object.subject for q in rows if q.predicate == N("rdf:reifies"))
    target = N(candidate["columns"][0]["annotation"]["termIri"])
    assert not any(q.subject == subject and q.predicate == N("qb:concept") and q.object == target for q in rows)
    other = GraphBuilder()
    dataset, table, schema, column, graph = (B + "other/" + v for v in ("dataset", "table", "schema", "column", "graph"))
    other.type(dataset, "dcat:Dataset", graph)
    other.add(dataset, "pav:version", L("openly-fictional-v1"), graph)
    other.add(dataset, "dcterms:source", B + "other/source", graph)
    other.add(dataset, "dcterms:hasPart", table, graph)
    other.add(table, "csvw:tableSchema", schema, graph)
    other.add(schema, "csvw:column", column, graph)
    other.reify(B + "other/source-statement", column, "qb:concept", target, graph, assert_triple=True)
    other.add(B + "other/source-statement", "dcterms:source", B + "other/source", graph)
    store_path = tmp_path / "authorized-fictional-store"
    store = ox.Store(store_path)
    store.extend(rows + other.quads); store.flush(); del store; gc.collect()
    inventory = lambda: {str(p.relative_to(store_path)): (p.stat().st_mtime_ns, sha(p.read_bytes())) for p in store_path.rglob("*") if p.is_file()}
    before = inventory()
    kwargs = {"project_datasets": [candidate["dataset"]["iri"]], "families": ["measurement"]}
    assert discovery.discover(store_path, **kwargs)["paths"] == []
    found = discovery.discover(store_path, include_pending=True, **kwargs)
    assert found["query_status"] == "complete" and found["has_more"] is False
    assert len(found["paths"]) == 1
    path = found["paths"][0]
    assert path["dataset"] == dataset and path["shared_iri"] == target.value
    assert path["path_state"] == "awaiting_review"
    assert path["project"]["asserted"] is False and path["project"]["authority"] == "awaiting_review"
    assert path["project"]["recorded_review_status"] == ["awaitingReview"]
    assert path["candidate"]["authority"] == "source_stated" and path["candidate"]["asserted"] is True
    assert candidate["columns"][0]["evidence"]["citation"] in " ".join(path["project"]["evidence"])
    assert preview["graph"]["sha256"] in compiled["receipt"]["graphSha256"]
    gc.collect(); assert inventory() == before


@pytest.mark.parametrize("field", ["confidence", "attributionIri", "activityIri", "evidence", "date"])
def test_missing_explicit_review_context_refuses(inputs, field):
    _, candidate, current = inputs
    del candidate["review"][field]
    with pytest.raises(contribution.ContributionError) as error:
        contribution.preview(candidate, current=current)
    assert error.value.code == "invalid_contribution"


@pytest.mark.parametrize("section", ["root", "column", "native", "review", "current"])
def test_raw_private_or_unknown_extra_fields_are_rejected(inputs, section):
    _, candidate, current = inputs
    selected = {"root": candidate, "column": candidate["columns"][0], "native": candidate["columns"][0]["annotation"], "review": candidate["review"], "current": current}[section]
    selected["privateNote"] = "FICTIONAL_PRIVATE_EXTRA"
    with pytest.raises(contribution.ContributionError):
        contribution.preview(candidate, current=current)


@pytest.mark.parametrize("field", ["semanticRevision", "semanticBasisSha256", "semanticStateSha256", "documentationRevision", "selectionRevision", "projectRevision"])
def test_stale_binding_refuses_without_repair_or_repin(inputs, field):
    _, candidate, current = inputs
    current[field] = current[field] + 1 if isinstance(current[field], int) else "0" * 64
    with pytest.raises(contribution.ContributionError) as error:
        contribution.preview(candidate, current=current)
    assert error.value.code == "contribution_changed"


@pytest.mark.parametrize("change", ["source", "sourceAuthority", "projection", "artifact", "evidence", "scope", "public", "accepted", "unit", "predicate", "dataset"])
def test_changed_or_unsupported_semantics_and_audience_refuse(inputs, change):
    _, candidate, current = inputs
    if change == "source": candidate["source"]["sha256"] = "0" * 64
    elif change == "sourceAuthority": candidate["source"]["authorityIri"] = B + "unbound-authority"
    elif change == "projection": candidate["binding"]["projectionSha256"] = "0" * 64
    elif change == "artifact": candidate["nativeArtifacts"][0]["sha256"] = "0" * 64
    elif change == "evidence": candidate["columns"][0]["evidence"]["citation"] = "Changed source evidence"
    elif change == "scope": candidate["columns"][0]["scope"]["kind"] = "all-datasets"
    elif change == "public": candidate["audience"]["kind"] = "public"
    elif change == "accepted": candidate["columns"][0]["status"] = "humanAccepted"
    elif change == "unit": candidate["columns"][0]["annotation"]["unitIri"] = B + "unit/not-supported-in-slice"
    elif change == "predicate": candidate["columns"][0]["predicate"] = N("owl:sameAs").value
    elif change == "dataset": candidate["dataset"]["iri"] = B + "unbound-dataset"
    with pytest.raises(contribution.ContributionError):
        contribution.preview(candidate, current=current)


def test_stale_preview_consent_and_scope_binding_cannot_be_reused(inputs):
    _, candidate, current = inputs
    preview = contribution.preview(candidate, current=current)
    for invalid in ({**consent(preview), "accepted": False}, {**consent(preview), "previewSha256": "0" * 64}, {**consent(preview), "actorId": "FICTIONAL_PRIVATE_ID"}):
        with pytest.raises(contribution.ContributionError):
            contribution.admit(candidate, current=current, consent=invalid)
    candidate["review"]["evidence"].append("An explicitly changed contribution-time explanation")
    with pytest.raises(contribution.ContributionError) as error:
        contribution.admit(candidate, current=current, consent=consent(preview))
    assert error.value.code == "contribution_preview_changed"


def test_explicit_existing_namespace_is_preserved_without_implicit_reminting(inputs):
    _, candidate, current = inputs
    before = config.current()
    cfg = config.Config(base="https://w3id.org/smn-data-graph/")
    with config.override(cfg):
        with pytest.raises(contribution.ContributionError):
            contribution.preview(candidate, current=current)
        candidate["dataset"]["iri"] = iri.dataset(candidate["dataset"]["slug"], candidate["dataset"]["version"])
        preview, compiled = admit(candidate, current)
        assert preview["namespace"]["base"] == cfg.base
        assert all(value.startswith(cfg.base) for value in preview["generatedIris"])
        assert candidate["columns"][0]["annotation"]["termIri"] in compiled["graphBytes"].decode()
    assert config.current() == before


@pytest.mark.parametrize("field", ["semanticRevision", "documentationRevision", "selectionRevision", "projectRevision"])
def test_boolean_revision_cannot_alias_an_integer_binding(inputs, field):
    _, candidate, current = inputs
    candidate["binding"][field] = True
    with pytest.raises(contribution.ContributionError):
        contribution.preview(candidate, current=current)


def test_size_bound_refuses_whole_candidate_with_generic_error(inputs):
    _, candidate, current = inputs
    candidate["review"]["evidence"] = ["FICTIONAL_PRIVATE_OVERLIMIT" * 25000]
    with pytest.raises(contribution.ContributionError) as error:
        contribution.preview(candidate, current=current)
    assert error.value.code == "contribution_limit"
    assert "FICTIONAL_PRIVATE_OVERLIMIT" not in str(error.value)


def test_known_v2_empty_extras_bind_actual_projection_without_downgrade(inputs):
    fixture, candidate, current = inputs
    # Pin the earlier v1 public preview bytes as well as its behavior.
    original = contribution.preview(candidate, current=current)
    assert original["sha256"] == "324eb9e03a7132635f04651d0fe1882c25bf2d0225c59d103a84de4bd86e6621"
    native_before = copy.deepcopy(fixture["nativeResult"])
    artifacts_before = copy.deepcopy(current["nativeArtifacts"])
    v2_empty(candidate, current)
    exact_projection = copy.deepcopy(current["projection"])
    preview, compiled = admit(candidate, current)
    assert current["projection"] == exact_projection
    assert preview["candidate"]["binding"]["projectionSha256"] == candidate["binding"]["projectionSha256"]
    assert compiled["receipt"]["binding"]["projectionSha256"] == candidate["binding"]["projectionSha256"]
    assert candidate["binding"]["projectionSha256"] != original["candidate"]["binding"]["projectionSha256"]
    assert "sha256:" + candidate["binding"]["projectionSha256"] in compiled["graphBytes"].decode()
    assert fixture["nativeResult"] == native_before and current["nativeArtifacts"] == artifacts_before
    assert preview["pendingRelationships"] == 1
    assert compiled["receipt"]["sharedRelationshipAccepted"] is False


@pytest.mark.parametrize("field,value", [
    ("procedure", {"kind": "table-constant", "methodIri": B + "procedure/not-admitted"}),
    ("procedure", {}), ("procedure", False),
    ("identifiers", [{"kind": "unresolved", "columnOrdinal": 0}]),
    ("identifiers", None), ("identifiers", {}),
])
def test_known_v2_nonempty_or_malformed_extras_are_not_silently_stripped(inputs, field, value):
    _, candidate, current = inputs
    v2_empty(candidate, current)
    current["projection"][field] = value
    candidate["binding"]["projectionSha256"] = sha(json.dumps(current["projection"], ensure_ascii=False, separators=(",", ":")).encode())
    with pytest.raises(contribution.ContributionError) as error:
        contribution.preview(candidate, current=current)
    assert error.value.code == "unsupported_contribution"


@pytest.mark.parametrize("change", ["missing-procedure", "missing-identifiers", "extra-private", "v1-with-extras"])
def test_projection_versions_keep_their_exact_closed_fields(inputs, change):
    _, candidate, current = inputs
    v2_empty(candidate, current)
    if change == "missing-procedure": del current["projection"]["procedure"]
    elif change == "missing-identifiers": del current["projection"]["identifiers"]
    elif change == "extra-private": current["projection"]["actorId"] = "FICTIONAL_PRIVATE"
    else: current["projection"]["schema"] = "confirmed-column-semantics/1"
    with pytest.raises(contribution.ContributionError):
        contribution.preview(candidate, current=current)
