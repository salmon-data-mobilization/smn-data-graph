"""Source-reference admission from genuine SDK943 bytes, never observation inference."""
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

from salmongraph import contribution, discovery, iri, review
from salmongraph.graph import N

FIXTURE = Path(__file__).with_name("fixtures") / "fictional-rich-native.json"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_a, **_k):
        raise AssertionError("Pure rich admission must not access a network")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


def fixture():
    return json.loads(FIXTURE.read_text())


def compile_one(candidate, current):
    result = contribution.preview(candidate, current=current)
    compiled = contribution.admit(candidate, current=current, consent={
        "version": "confirmed-source-contribution-consent/2", "accepted": True,
        "previewSha256": result["sha256"]})
    return result, compiled["graphBytes"]


@pytest.mark.parametrize("name", ["fictional-rich-native.json", "fictional-rich-mapping-native.json"])
def test_native_reference_metadata_and_full_literal_grid_are_real_fixture_evidence(name):
    value = json.loads(FIXTURE.with_name(name).read_text()); native = value["nativeResult"]
    assert native["engine"]["sourceCommit"] == "943fe1f50d7ac5b88b8be81250dca2e7aeb0f632"
    assert native["networkAttempts"] == 0
    files = {f["path"]: f["content"] for f in native["files"]}
    for f in value["current"]["nativeArtifacts"]:
        data = files[f["path"]].encode(); assert len(data) == f["bytes"]
        assert hashlib.sha256(data).hexdigest() == f["sha256"]
    assert list(csv.reader(io.StringIO(files["data/source.csv"]))) == list(csv.reader(io.StringIO(value["sourceCsv"])))
    table = next(csv.DictReader(io.StringIO(files["metadata/tables.csv"])))
    assert table["method_iri"] == value["current"]["projection"]["procedure"]["methodIri"]
    code = next(csv.DictReader(io.StringIO(files["metadata/codes.csv"])))
    assert code["term_iri"] == value["current"]["projection"]["identifiers"][0]["termIri"]
    assert "Authority version: 2026-1" in code["code_description"]


def test_rich_native_references_are_critical_pending_without_observation_or_population_inference(tmp_path):
    value = fixture(); candidate, current = value["candidate"], value["current"]
    result, data = compile_one(candidate, current)
    rows = list(ox.parse(data, format=ox.RdfFormat.N_QUADS)); queue = review.review_queue(rows)
    assert result["schema"] == "confirmed-source-contribution-preview/2"
    assert len(queue) == 4 and all(r.criticality == "critical" and r.status == "awaitingReview" for r in queue)
    assert not any(q.predicate in {N("qb:concept"), N("dcterms:references"), N("sosa:usedProcedure")} for q in rows)
    assert not any(q.predicate == N("rdf:type") and q.object in {N("qb:Observation"), N("smn:Population"), N("gcdfo:ConservationUnit")} for q in rows)
    other = copy.deepcopy(candidate); other["dataset"]["version"] = "fixture-2"
    other["dataset"]["iri"] = iri.dataset(other["dataset"]["slug"], "fixture-2")
    _, other_data = compile_one(other, current)
    store_path = tmp_path / "private-allowed"; store = ox.Store(store_path)
    store.extend(rows); store.extend(ox.parse(other_data, format=ox.RdfFormat.N_QUADS)); store.flush(); del store; gc.collect()
    args = {"project_datasets": [candidate["dataset"]["iri"]]}
    assert discovery.discover(store_path, **args)["paths"] == []
    found = discovery.discover(store_path, include_pending=True, **args)
    assert found["query_status"] == "complete"
    assert sorted(p["family"] for p in found["paths"]) == ["measurement", "population", "procedure", "procedure"]
    refs = [p for p in found["paths"] if p["family"] != "measurement"]
    assert all(p["match_basis"] == "native_metadata_reference" for p in refs)
    assert all(not p["project"]["asserted"] and not p["candidate"]["asserted"] for p in refs)
    assert all(p["project"]["native_reference"]["field"] == p["candidate"]["native_reference"]["field"] for p in refs)


def discover_rows(tmp_path, rows, dataset, **options):
    path = tmp_path / 'snapshot'; store = ox.Store(path); store.extend(rows); store.flush(); del store; gc.collect()
    return discovery.discover(path, project_datasets=[dataset], include_pending=True, **options)


def other_rows(value):
    other = copy.deepcopy(value['candidate']); other['dataset']['version'] = 'fixture-other'
    other['dataset']['iri'] = iri.dataset(other['dataset']['slug'], 'fixture-other')
    return other, list(ox.parse(compile_one(other, value['current'])[1], format=ox.RdfFormat.N_QUADS))


@pytest.mark.parametrize('field,changed', [('authorityVersion','2026-2'), ('authorityName','Different authority'),
    ('nativeKey','N-8'), ('vocabularyIri','https://example.invalid/different'), ('termType','skos_concept')])
def test_exact_iri_and_same_label_do_not_join_different_native_identity_context(tmp_path, field, changed):
    value=fixture(); rows=list(ox.parse(compile_one(value['candidate'],value['current'])[1],format=ox.RdfFormat.N_QUADS)); _, other=other_rows(value)
    # Explicit admitted RDF-fixture mutation: source identity qualifiers differ.
    # This checks the query boundary, not a claim of fresh SDK generation.
    altered=[]
    contexts={q.subject for q in other if q.predicate==N("dcterms:type") and q.object==ox.Literal("sdp-native-reference/1")}
    for q in other:
        if q.subject in contexts and q.predicate==N('prov:value') and isinstance(q.object,ox.Literal):
            context=json.loads(q.object.value)
            if context.get('family')=='population': context[field]=changed; q=ox.Quad(q.subject,q.predicate,ox.Literal(json.dumps(context)),q.graph_name)
        altered.append(q)
    result=discover_rows(tmp_path,rows+altered,value['candidate']['dataset']['iri'])
    assert result['query_status']=='complete'
    assert sorted(p['family'] for p in result['paths'])==['measurement','procedure','procedure']


@pytest.mark.parametrize('fault', ['annotation','evidence','scope','accepted','private','column','missing','empty'])
def test_native_selected_content_requires_exact_independent_saved_context(fault):
    value=fixture(); candidate=value['candidate']; current=value['current']
    if fault=='annotation': candidate['identifiers'][0]['annotation']=dict(candidate['identifiers'][0]['annotation'],authorityVersion='2027')
    if fault=='evidence': candidate['procedure']['evidence']={'citation':'Not saved source evidence','sha256':None}
    if fault=='scope': candidate['identifiers'][0]['scope']={'kind':'dataset-identifier','note':'Not saved scope'}
    if fault=='accepted': candidate['procedure']['status']='humanAccepted'
    if fault=='private': candidate['procedure']['actorId']='PRIVATE'
    if fault=='column': candidate['identifiers'][0]['index']=True
    if fault=='missing': del current['identifierUnderstanding']
    if fault=='empty': candidate.update(columns=[],procedure=None,identifiers=[])
    with pytest.raises(contribution.ContributionError): contribution.preview(candidate,current=current)


def test_reference_only_selection_has_no_unselected_column_concept_claim():
    value=fixture(); value['candidate']['columns']=[]; value['candidate']['procedure']=None
    result,data=compile_one(value['candidate'],value['current'])
    assert result['pendingRelationships']==1
    assert 'http://purl.org/linked-data/cube#concept' not in data.decode()
    assert 'tables.method_iri' not in data.decode()
    assert 'codes.term_iri' in data.decode()


def test_native_reference_global_pending_floor_cannot_be_evaded_by_graph_filter(tmp_path):
    value=fixture(); _,data=compile_one(value['candidate'],value['current']); rows=list(ox.parse(data,format=ox.RdfFormat.N_QUADS)); _,other=other_rows(value)
    from salmongraph.graph import RDF_REIFIES
    asserted=ox.NamedNode('urn:fictional:asserted-only'); extras=[]
    for q in rows+other:
        if q.predicate==N(RDF_REIFIES) and isinstance(q.object,ox.Triple) and q.object.predicate==N('dcterms:references'):
            extras.append(ox.Quad(q.object.subject,q.object.predicate,q.object.object,asserted))
        elif q.predicate.value!=RDF_REIFIES: extras.append(ox.Quad(q.subject,q.predicate,q.object,asserted))
    result=discover_rows(tmp_path,rows+other+extras,value['candidate']['dataset']['iri'],graphs=[asserted.value])
    # Original critical pending records stay authoritative before graph filters.
    assert result['pending_targets']==8
    assert result['paths']==[]


def test_native_reference_query_budget_refuses_incomplete_evidence(tmp_path,monkeypatch):
    value=fixture(); _,data=compile_one(value['candidate'],value['current']); _,other=other_rows(value)
    monkeypatch.setattr(discovery,'MAX_READ_PATTERNS',3)
    result=discover_rows(tmp_path,list(ox.parse(data,format=ox.RdfFormat.N_QUADS))+other,value['candidate']['dataset']['iri'])
    assert result['paths']==[] and result['query_status']=='partial_evidence_refused'


def test_genuine_scoped_sssom_is_pending_with_provenance_and_never_identity_equivalence(tmp_path):
    value=json.loads(FIXTURE.with_name('fictional-rich-mapping-native.json').read_text())
    result,data=compile_one(value['candidate'],value['current']); mapping=value['candidate']['identifiers'][0]['annotation']['mappings'][0]
    files={f['path']:f for f in value['nativeResult']['files']}
    manifest=json.loads(files['metadata/semantic/mapping-sets.json']['content'])
    assert len(manifest['mapping_sets'])==1
    artifact=files[manifest['mapping_sets'][0]['path']]
    assert manifest['mapping_sets'][0]['sha256']==hashlib.sha256(artifact['content'].encode()).hexdigest()
    assert mapping['subjectId'] in artifact['content'] and mapping['objectId'] in artifact['content']
    assert mapping['scopeNote'] in artifact['content'] and mapping['uncertainty'] in artifact['content']
    assert result['pendingRelationships']==5
    rows=list(ox.parse(data,format=ox.RdfFormat.N_QUADS))
    assert not any(q.subject==N(mapping['subjectId']) and q.predicate==N(mapping['predicateId']) and q.object==N(mapping['objectId']) for q in rows)
    assert mapping['scopeNote'] in data.decode() and mapping['objectSourceVersion'] in data.decode()
    # The other native reference names the mapping's target. No scoped mapping
    # traversal may manufacture an exact identity match to the source code.
    other,other_data=other_rows(value); altered=[]
    from salmongraph.graph import RDF_REIFIES
    for q in other_data:
        if q.predicate==N(RDF_REIFIES) and isinstance(q.object,ox.Triple) and q.object.predicate==N('dcterms:references') and q.object.object==N(mapping['subjectId']):
            q=ox.Quad(q.subject,q.predicate,ox.Triple(q.object.subject,q.object.predicate,N(mapping['objectId'])),q.graph_name)
        altered.append(q)
    found=discover_rows(tmp_path,rows+altered,value['candidate']['dataset']['iri'])
    assert found['query_status']=='complete'
    assert sorted(p['family'] for p in found['paths'])==['measurement','procedure','procedure']


def test_native_method_reference_does_not_match_an_observed_procedure_use(tmp_path):
    value=fixture(); rows=list(ox.parse(compile_one(value['candidate'],value['current'])[1],format=ox.RdfFormat.N_QUADS)); _,other=other_rows(value)
    from salmongraph.graph import RDF_REIFIES
    method=value['candidate']['procedure']['annotation']['methodIri']; rewritten=[]
    for q in other:
        if q.predicate==N(RDF_REIFIES) and isinstance(q.object,ox.Triple) and q.object.predicate==N('dcterms:references') and q.object.object==N(method):
            subject=q.object.subject
            parent=next(row.object for row in other if row.subject==subject and row.predicate==N('dcterms:isPartOf'))
            rewritten.append(ox.Quad(subject,N('qb:dataSet'),parent,q.graph_name))
            q=ox.Quad(q.subject,q.predicate,ox.Triple(subject,N('sosa:usedProcedure'),q.object.object),q.graph_name)
        rewritten.append(q)
    found=discover_rows(tmp_path,rows+rewritten,value['candidate']['dataset']['iri'])
    assert found['query_status']=='complete'
    assert all(path['shared_iri']!=method for path in found['paths'])
    assert sorted(p['family'] for p in found['paths'])==['measurement','population','procedure']


def test_missing_native_critical_mark_cannot_become_a_source_accepted_reference(tmp_path):
    value=fixture(); rows=list(ox.parse(compile_one(value['candidate'],value['current'])[1],format=ox.RdfFormat.N_QUADS)); _,other=other_rows(value)
    from salmongraph import provenance
    contexts={q.subject for q in other if q.predicate==N('dcterms:type') and q.object==ox.Literal('sdp-native-reference/1')}
    altered=[q for q in other if not(q.subject in contexts and q.predicate==N(provenance.terms().criticality))]
    with pytest.raises(ValueError): discover_rows(tmp_path,rows+altered,value['candidate']['dataset']['iri'])
