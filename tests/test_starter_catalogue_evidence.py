"""Offline controls for a prepared catalogue, not observation/semantic admission.

The fixture records publisher assertions. These checks prevent the preparation
from silently becoming a harmonized dataset, a release grant, or a count of
independent measurement streams. They do not certify the publisher's science.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

PATH = Path(__file__).resolve().parents[1] / "specs/starter-corpus/catalogue-evidence.json"
EXPECTED_KEYS = {"sasap", "npafc-ipsdl", "sasap-asl", "sasap-covariates", "sasap-abundance"}
RECORD_FIELDS = {
    "key", "kind", "title", "identifiers", "version", "publisher",
    "declared_coverage", "rights", "provenance", "access", "quality_flags", "readiness",
}
READY = {
    "catalogue_status": "prepared_for_review",
    "observation_files_fetched": False,
    "observation_rows_in_fixture": 0,
    "graph_loaded": False,
    "semantic_mappings_accepted": False,
    "publication_approved": False,
}
RELATIONS = {
    "compiled_from", "largerWorkCitation", "described_by", "obsoletes",
    "project_association", "cited_input", "initiative_acknowledgement",
}


def load():
    return json.loads(PATH.read_text(encoding="utf-8"))


def validate_fixture(doc):
    """Closed fixture contract: reject unevidenced claims and expanded payloads."""
    assert set(doc) == {"schema", "observed_at", "purpose", "curated_counts", "sources", "records"}
    assert doc["schema"] == "starter-corpus-catalogue-evidence/1"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT.+Z", doc["observed_at"])
    assert doc["curated_counts"] == {"collections": 1, "datasets": 4}
    sources = {s["id"]: s for s in doc["sources"]}
    assert len(sources) == len(doc["sources"]) == 8
    for source in sources.values():
        assert set(source) == {"id", "url", "format", "observed_at", "sha256", "bytes", "snapshot_file"}
        assert urlparse(source["url"]).scheme == "https"
        assert source["format"] in {"html", "xml", "json", "pdf"}
        assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
        assert type(source["bytes"]) is int and source["bytes"] > 0
        assert Path(source["snapshot_file"]).name == source["snapshot_file"]
        assert source["observed_at"] == doc["observed_at"]

    def evidence(item):
        refs = item["source_refs"]
        assert refs and len(refs) == len(set(refs)) and set(refs) <= sources.keys()

    records = {r["key"]: r for r in doc["records"]}
    assert set(records) == EXPECTED_KEYS and len(doc["records"]) == len(records)
    assert sum(r["kind"] == "dataset" for r in records.values()) == 4
    assert sum(r["kind"] == "collection" for r in records.values()) == 1
    dois = []
    for record in records.values():
        assert set(record) == RECORD_FIELDS
        assert record["kind"] in {"dataset", "collection"}
        assert record["readiness"] == READY
        assert type(record["readiness"]["observation_rows_in_fixture"]) is int
        assert all(record["readiness"][name] is False for name in [
            "observation_files_fetched", "graph_loaded", "semantic_mappings_accepted", "publication_approved",
        ])
        for field in ["title", "version", "publisher", "declared_coverage"]:
            claim = record[field]
            assert set(claim) == {"value", "source_refs", "assertion"}
            assert claim["assertion"] == "publisher_declared"
            evidence(claim)
        assert record["title"]["value"]
        assert isinstance(record["title"]["value"], str)
        assert record["version"]["value"] is None or isinstance(record["version"]["value"], str)
        publisher = record["publisher"]["value"]
        assert {"name", "role"} <= publisher.keys() <= {"name", "role", "creators"}
        coverage = record["declared_coverage"]["value"]
        required = {"spatial", "temporal", "species", "measurements", "spatial_bounds_verbatim"}
        assert required <= coverage.keys() <= required | {
            "reference_dates_verbatim", "publication_date_index", "metadata_uploaded",
        }
        assert all(isinstance(coverage[name], list) and all(isinstance(v, str) for v in coverage[name])
                   for name in ["spatial", "species", "measurements"])
        assert coverage["temporal"] is None or (
            set(coverage["temporal"]) == {"begin", "end"}
            and all(isinstance(v, str) for v in coverage["temporal"].values())
        )
        for bounds in coverage["spatial_bounds_verbatim"]:
            assert set(bounds) in [
                {"bbox-east-long", "bbox-north-lat", "bbox-south-lat", "bbox-west-long"},
                {"westBoundingCoordinate", "eastBoundingCoordinate", "northBoundingCoordinate", "southBoundingCoordinate"},
            ]
            assert all(isinstance(v, str) for v in bounds.values())
        assert set(record["identifiers"]) == {"doi", "provider_record"}
        doi = record["identifiers"]["doi"]
        if doi is not None:
            assert re.fullmatch(r"10\.\d{4,9}/\S+", doi)
            dois.append(doi.casefold())
        assert set(record["rights"]) == {"license_uri", "label", "scope", "source_refs"}
        evidence(record["rights"])
        for relation in record["provenance"]:
            assert set(relation) in [
                {"relation", "target", "source_refs", "assertion"},
                {"relation", "target", "source_refs", "assertion", "note"},
            ]
            assert relation["relation"] in RELATIONS and relation["target"]
            assert relation["assertion"] == "publisher_declared"
            evidence(relation)
        assert record["quality_flags"]
        for flag in record["quality_flags"]:
            assert set(flag) == {"code", "note", "source_refs"} and flag["code"] and flag["note"]
            evidence(flag)
        assert set(record["access"]) == {"landing_url", "metadata_url"}
        assert all(urlparse(u).scheme == "https" for u in record["access"].values())
    assert len(dois) == len(set(dois)) == 4
    return records


def test_catalogue_has_closed_evidenced_metadata_only_contract():
    validate_fixture(load())


@pytest.mark.parametrize("mutate", [
    lambda d: d["records"][0].update(observations=[{"value": 1}]),
    lambda d: d["records"][0]["declared_coverage"]["value"].update(observations=[{"value": 1}]),
    lambda d: d["records"][0]["publisher"]["value"].update(observations=[{"value": 1}]),
    lambda d: d["records"][0]["readiness"].update(publication_approved=True),
    lambda d: d["records"][0]["readiness"].update(graph_loaded=True),
    lambda d: d["records"][0]["title"].update(source_refs=[]),
    lambda d: d["records"][0]["title"].update(assertion="scientifically_accepted"),
    lambda d: d["records"][1]["provenance"][0].update(relation="same_as"),
    lambda d: d["records"][1]["provenance"][0].update(source_refs=["missing"]),
    lambda d: d["curated_counts"].update(datasets=115),
    lambda d: d["records"].append(copy.deepcopy(d["records"][0])),
])
def test_expansion_or_false_readiness_is_refused(mutate):
    doc = load()
    mutate(doc)
    with pytest.raises(AssertionError):
        validate_fixture(doc)


def test_collection_rights_versions_and_revision_lineage_remain_separate():
    records = validate_fixture(load())
    assert records["sasap"]["rights"]["license_uri"] is None
    assert records["sasap"]["identifiers"]["doi"] is None
    assert records["npafc-ipsdl"]["version"]["value"] == "1.5.1"
    for key in EXPECTED_KEYS - {"npafc-ipsdl"}:
        assert records[key]["version"]["value"] is None
    assert records["sasap-asl"]["rights"]["license_uri"].endswith("/by/4.0/")
    assert records["sasap-covariates"]["rights"]["license_uri"].endswith("/zero/1.0/")
    abundance = records["sasap-abundance"]
    assert any(r["relation"] == "obsoletes" and r["target"] == "doi:10.5063/F1BR8QG4"
               for r in abundance["provenance"])
    assert "doi:10.5063/F1BR8QG4" not in {r["identifiers"]["provider_record"] for r in records.values()}
    assert len([r for r in abundance["provenance"] if r["relation"] == "cited_input"]) == 4
    covariates = records["sasap-covariates"]
    assert any(r["relation"] == "initiative_acknowledgement" for r in covariates["provenance"])
    # Neither project association nor funding establishes portal membership.
    assert records["sasap"]["provenance"] == []
    assert all(r["target"] != covariates["identifiers"]["provider_record"]
               for r in records["sasap"]["provenance"])


def test_provider_bounds_and_scientific_limits_are_not_repaired_or_erased():
    records = validate_fixture(load())
    archive = records["npafc-ipsdl"]
    assert archive["declared_coverage"]["value"]["spatial_bounds_verbatim"] == [{
        "bbox-east-long": "-131.0", "bbox-north-lat": "34.21",
        "bbox-south-lat": "57.64", "bbox-west-long": "-217.1",
    }]
    assert any(f["code"] == "publisher_bounds_need_review" for f in archive["quality_flags"])
    drivers = records["sasap-covariates"]["declared_coverage"]["value"]
    assert drivers["spatial_bounds_verbatim"] == [{
        "westBoundingCoordinate": "-180", "eastBoundingCoordinate": "-130",
        "northBoundingCoordinate": "53", "southBoundingCoordinate": "71",
    }]
    assert any(f["code"] == "regional_accounting_not_natal_origin"
               for f in records["sasap-abundance"]["quality_flags"])
    assert any(f["code"] == "representative_point_not_footprint"
               for f in records["sasap-asl"]["quality_flags"])
