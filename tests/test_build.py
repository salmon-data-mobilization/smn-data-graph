"""Genuine tiny offline builds; fictional fixture data is not salmon evidence."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket

import metasalmonpy as ms
import pandas as pd
import pyarrow.parquet as pq
import pytest
import yaml

from conftest import tiny_sources
from salmongraph import config, iri, provenance
from salmongraph.executor import AgentRun, build_dataset
from salmongraph.spec import SpecError, load_spec
from salmongraph.vocab import VocabIndex

CSV = ("stock,period,phase,count,flag,date\n"
       "001,2000,NA,0,true,2000-01-02\n"
       "NA,2001,null,-99,false,\n"
       "nan,2002,A,,true,2002-03-04\n")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("build tests must remain offline")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    yield
    assert attempts == [], "a swallowed network attempt cannot pass"


@pytest.fixture
def vocab(tmp_path):
    def make(cfg=None):
        sources = []
        for source in tiny_sources():
            path = tmp_path / f"{source.key}.ttl"
            text = source.path.read_text()
            if source.key == "smn":
                text += "\n" + "\n".join(
                    f"<https://w3id.org/smn/{term}> a <http://www.w3.org/2002/07/owl#DatatypeProperty> ."
                    for term in ("broodYear", "returnYear"))
            path.write_text(text)
            sources.append(replace(source, path=path))
        return VocabIndex(sources, cfg=cfg or config.current(), offline=True)
    return make


def document():
    return {
        "spec_version": 1, "slug": "fictional-build", "version": "v 1/2",
        "title": "Fictional build fixture", "description": "Software records, not biological evidence.",
        "source": {"publisher": "Fixture authority", "landing_page": "https://example.test/source",
                   "licence": "https://creativecommons.org/licenses/by/4.0/", "redistribution": "unconfirmed",
                   "attribution": "Fixture attribution", "files": [{"name": "source.csv",
                   "url": "https://example.test/source.csv", "sha256": "a" * 64}]},
        "parser": "csv", "tables": [{"id": "series", "file": "source.csv", "keys": ["stock", "period"], "columns": [
            {"name": "stock", "role": "identifier", "datatype": "string"},
            {"name": "period", "role": "dimension", "datatype": "integer"},
            {"name": "phase", "role": "dimension", "datatype": "string", "codes": {"NA": None, "null": None, "A": "gcdfo:MethodX"}},
            {"name": "count", "role": "measure", "datatype": "number", "concept": "psc:PSC-CV-999999", "unit": "unit:NUM", "year_basis": "smn:broodYear"},
            {"name": "flag", "role": "attribute", "datatype": "boolean"},
            {"name": "date", "role": "attribute", "datatype": "date"},
        ]}],
        "identity": [{"table": "series", "column": "stock", "kind": "stock", "authority": "fixture"}],
        "observations": [{"table": "series", "key": ["stock", "period"], "dimensions": ["stock", "period", "phase"],
                          "year_column": "period", "measures": ["count"]}],
        "cross_source_checks": [{"id": "future-check", "other": "other-source", "join": "stock", "measure": "count",
                                 "other_measure": "count", "tolerance": 0.0, "expect": "An unexecuted source comparison."}],
    }


def prepare(tmp_path, data=None, *, csv_text=CSV):
    data = copy.deepcopy(data or document())
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    source = raw / data["source"]["files"][0]["name"]
    if data["parser"] != "xlsx":
        source.write_text(csv_text)
    data["source"]["files"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return load_spec(path), raw


def bytes_tree(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def run(tmp_path, vocab, data=None, *, csv_text=CSV, **kwargs):
    spec, raw = prepare(tmp_path, data, csv_text=csv_text)
    result = build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw,
                           out_dir=tmp_path / "output", **kwargs)
    return spec, raw, result


# These deliberately tiny functions are actual project-local parser source,
# loaded from this file after source resolution/hash verification, not mocks.
def local_parser(*, spec, raw_dir):
    return {"series": pd.read_csv(raw_dir / "source.csv", dtype=str, keep_default_na=False)}


def wrong_parser(*, spec, raw_dir):
    return {"wrong-table": pd.DataFrame()}


def modifying_parser(*, spec, raw_dir):
    frames = local_parser(spec=spec, raw_dir=raw_dir)
    with (raw_dir / "source.csv").open("a") as handle:
        handle.write("changed-source\n")
    return frames


def network_parser(*, spec, raw_dir):
    try:
        socket.getaddrinfo("example.invalid", 443)
    except Exception:
        pass  # The builder must still reject swallowed network attempts.
    return local_parser(spec=spec, raw_dir=raw_dir)


def test_real_sdk_graph_shacl_parquet_queue_and_manifest(tmp_path, vocab):
    from metasalmonpy import sdp_schema
    before_source = getattr(sdp_schema, "_SOURCE_OVERRIDE", None)
    spec, raw, result = run(tmp_path, vocab)
    assert result.observations == 2 and result.shacl_conforms is True
    assert set(result.graphs) == set(config.DATASET_GRAPH_PARTS)
    manifest = json.loads((result.out_dir / "manifest.json").read_text())
    report = json.loads((result.out_dir / "report.json").read_text())
    for item in manifest["files"]:
        data = (result.out_dir / item["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"] and len(data) == item["bytes"]
    assert all(item["path"] != "manifest.json" for item in manifest["files"])
    assert manifest["tools"]["pyarrow"]
    assert manifest["tools"]["metasalmonpy"]["source_sha256"]
    assert manifest["tools"]["salmongraph"]["source_sha256"]
    assert any(item["path"] == "spec.schema.json" for item in manifest["tools"]["salmongraph"]["source_files"])
    assert any(item["path"].endswith("datasets.ttl") for item in manifest["tools"]["salmongraph"]["source_files"])
    assert any(item["path"] == "package_io.py" for item in manifest["tools"]["metasalmonpy"]["source_files"])
    assert manifest["sdp_schema"]["source"] == "vendored"
    assert manifest["configuration"] == {"base": config.current().base, "profile_base": config.current().profile_base, "sdpv": config.current().sdpv}
    assert report["publication_ready"] is False
    assert report["checks"]["cross_source"]["status"] == "not_run"
    assert report["checks"]["sdp"]["inference"] == {"seed_semantics": False, "llm_assess": False, "adopted_guesses": False}
    assert (raw / "source.csv").read_text() == CSV
    assert getattr(sdp_schema, "_SOURCE_OVERRIDE", None) == before_source
    # Use the real reader, explicitly vendored because its global default is auto.
    sdp_schema.set_sdp_schema_source("vendored")
    try:
        package = ms.read_salmon_datapackage(result.out_dir / "sdp")
    finally:
        sdp_schema.set_sdp_schema_source(before_source)
    frame = package["resources"]["series"]
    assert frame["stock"].tolist() == ["001", "NA", "nan"]
    assert frame["phase"].tolist() == ["NA", "null", "A"]
    assert frame["flag"].tolist() == [True, False, True]
    assert package["dataset"].iloc[0]["created"] == "2026-10-24"
    assert package["dataset"].iloc[0]["contact_email"].startswith("MISSING METADATA:")
    values = pq.read_table(result.out_dir / "observations.parquet")["value"].to_pylist()
    assert sorted(values) == [-99.0, 0.0]
    for payload in bytes_tree(result.out_dir).values():
        if payload[:4] != b"PAR1":
            assert str(tmp_path).encode() not in payload
            assert b".salmongraph-build-" not in payload


def test_repeated_build_bytes_and_clean_replacement(tmp_path, vocab):
    spec, raw, result = run(tmp_path, vocab)
    first = bytes_tree(result.out_dir)
    again = build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=result.out_dir)
    assert bytes_tree(again.out_dir) == first
    assert not list(tmp_path.glob(".salmongraph-*"))


def test_pending_semantics_yield_real_queue_and_no_live_equivalence(tmp_path, vocab):
    data = document()
    data["tables"][0]["columns"][3]["mark"] = {"aspect": "measure-counts", "confidence": "high", "evidence": ["Fixture interpretation needs human review."]}
    _, _, result = run(tmp_path, vocab, data, run=AgentRun("build-fixture", "actual-model", "2026-10-23"))
    report = json.loads((result.out_dir / "report.json").read_text())
    assert result.review_counts["awaitingReview"] > 0
    assert report["publication_ready"] is False
    rows = (result.out_dir / "review-queue.csv").read_text()
    assert "awaitingReview" in rows and "humanAccepted" not in rows
    assert set(pq.read_table(result.out_dir / "observations.parquet")["review_status"].to_pylist()) == {"awaitingReview"}


def test_alternate_base_flows_through_real_compiler_and_gate(tmp_path, vocab):
    cfg = config.Config(base="https://example.test/data/", profile_base="https://example.test/profile/")
    with config.override(cfg):
        spec, raw = prepare(tmp_path)
    result = build_dataset(spec, build_date="2026-10-24", vocab=vocab(cfg), raw_dir=raw, out_dir=tmp_path / "alternate")
    assert result.shacl_conforms is True
    manifest = json.loads((result.out_dir / "manifest.json").read_text())
    assert manifest["configuration"] == {"base": cfg.base, "profile_base": cfg.profile_base, "sdpv": cfg.sdpv}
    assert all(iri_.startswith(cfg.base) for iri_ in result.graphs.values())
    assert pq.read_table(result.out_dir / "observations.parquet")["dataset_iri"][0].as_py().startswith(cfg.base)


def test_explicit_xlsx_sheet_never_uses_first_sheet(tmp_path, vocab):
    import openpyxl
    raw = tmp_path / "raw"
    raw.mkdir()
    workbook = openpyxl.Workbook()
    workbook.active.title = "Wrong sheet"
    workbook.active.append(["unrelated", "data"])
    sheet = workbook.create_sheet("Explicit observations")
    sheet.append(["stock", "period", "phase", "count", "flag", "date"])
    sheet.append(["001", 2000, "NA", 0, True, None])
    workbook.save(raw / "source.xlsx")
    data = document()
    data["parser"] = "xlsx"
    data["tables"][0].update(file="source.xlsx", sheet="Explicit observations")
    data["source"]["files"][0]["name"] = "source.xlsx"
    spec, raw = prepare(tmp_path, data)
    result = build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=tmp_path / "xlsx")
    assert result.observations == 1 and result.shacl_conforms is True


def test_custom_parser_is_real_project_local_source_and_pinned(tmp_path, vocab):
    data = document()
    data["parser"] = "tests.test_build:local_parser"
    _, _, result = run(tmp_path, vocab, data)
    manifest = json.loads((result.out_dir / "manifest.json").read_text())
    assert manifest["parser"]["source_sha256"] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    assert result.observations == 2


@pytest.mark.parametrize("parser", ["os:system", "subprocess:run", "does_not_exist:parse", "tests.test_build:wrong_parser", "tests.test_build:network_parser"])
def test_unsafe_or_wrong_custom_parsers_fail_without_output(tmp_path, vocab, parser):
    data = document()
    data["parser"] = parser
    spec, raw = prepare(tmp_path, data)
    with pytest.raises(ValueError):
        build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=tmp_path / "no-output")
    assert not (tmp_path / "no-output").exists()


def test_source_change_during_real_parser_preserves_prior_build(tmp_path, vocab):
    _, _, result = run(tmp_path, vocab)
    before = bytes_tree(result.out_dir)
    data = document()
    data["parser"] = "tests.test_build:modifying_parser"
    spec, raw = prepare(tmp_path, data)
    with pytest.raises(ValueError, match="SHA-256 mismatch|changed"):
        build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=result.out_dir)
    assert bytes_tree(result.out_dir) == before


@pytest.mark.parametrize("kind", ["raw-hash", "saved-spec", "in-memory-spec", "unknown-term", "duplicate-key", "precision", "typed-null-token"])
def test_input_failure_keeps_prior_success(tmp_path, vocab, kind):
    spec, raw, result = run(tmp_path, vocab)
    before = bytes_tree(result.out_dir)
    if kind == "raw-hash":
        (raw / "source.csv").write_text(CSV + "changed\n")
    elif kind == "saved-spec":
        spec.path.write_text(spec.path.read_text() + "\n# changed\n")
    elif kind == "in-memory-spec":
        spec.source["publisher"] = "Unsaved source change"
    else:
        data = document()
        text = CSV
        if kind == "unknown-term":
            data["tables"][0]["columns"][3]["concept"] = "smn:NotDeclared"
        elif kind == "duplicate-key":
            text += "001,2000,A,1,true,\n"
        elif kind == "precision":
            text = text.replace(",0,true,", ",0.123456789123456789,true,")
        elif kind == "typed-null-token":
            text = text.replace(",0,true,", ",NA,true,")
        spec, raw = prepare(tmp_path, data, csv_text=text)
    with pytest.raises(ValueError):
        build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=result.out_dir)
    assert bytes_tree(result.out_dir) == before


@pytest.mark.parametrize("dirty", ["extra-file", "nested-manifest", "extra-empty-dir", "changed-file"])
def test_dirty_prior_target_is_never_removed(tmp_path, vocab, dirty):
    spec, raw, result = run(tmp_path, vocab)
    if dirty == "extra-file":
        (result.out_dir / "user-notes.txt").write_text("Keep this")
    elif dirty == "nested-manifest":
        (result.out_dir / "sdp/manifest.json").write_text("User file")
    elif dirty == "extra-empty-dir":
        (result.out_dir / "user-empty-directory").mkdir()
    else:
        (result.out_dir / "report.md").write_text("User edited report")
    before = bytes_tree(result.out_dir)
    with pytest.raises(ValueError, match="dirty|unrecognized"):
        build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=result.out_dir)
    assert bytes_tree(result.out_dir) == before


def test_unrecognized_destination_and_raw_symlinks_are_refused(tmp_path, vocab):
    spec, raw = prepare(tmp_path)
    output = tmp_path / "unrelated"
    output.mkdir()
    (output / "keep.txt").write_text("Unrelated user content")
    with pytest.raises(ValueError, match="recognized"):
        build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=output)
    assert (output / "keep.txt").read_text() == "Unrelated user content"
    (raw / "source.csv").rename(raw / "actual.csv")
    (raw / "source.csv").symlink_to(raw / "actual.csv")
    with pytest.raises(ValueError, match="symlink"):
        build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=tmp_path / "new")


def test_source_identifier_whitespace_loss_is_rejected_not_trimmed(tmp_path, vocab):
    spec, raw = prepare(tmp_path, csv_text=CSV.replace("001,2000,", " 001 ,2000,"))
    with pytest.raises(ValueError, match="round trip changed"):
        build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=tmp_path / "not-trimmed")
    assert (raw / "source.csv").read_text().startswith("stock,period,phase,count,flag,date\n 001 ,")
    assert not (tmp_path / "not-trimmed").exists()


def test_output_symlink_and_raw_directory_overlap_are_refused(tmp_path, vocab):
    spec, raw = prepare(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("Keep")
    link = tmp_path / "output-link"
    link.symlink_to(unrelated, target_is_directory=True)
    for output in (link, raw, tmp_path):
        with pytest.raises(ValueError):
            build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=output)
    assert (unrelated / "keep.txt").read_text() == "Keep"
    assert (raw / "source.csv").read_text() == CSV


@pytest.mark.parametrize("date", [None, "now", "2026-02-30", "2026-10-24T00:00:00Z", "20261024"])
def test_build_date_is_explicit_valid_iso_date_without_output(tmp_path, vocab, date):
    spec, raw = prepare(tmp_path)
    with pytest.raises(ValueError, match="build_date"):
        build_dataset(spec, build_date=date, vocab=vocab(), raw_dir=raw, out_dir=tmp_path / "bad-date")
    assert not (tmp_path / "bad-date").exists()


def test_empty_source_still_has_real_valid_package_and_fixed_projection_schema(tmp_path, vocab):
    _, _, result = run(tmp_path, vocab, csv_text=CSV.splitlines()[0] + "\n")
    assert result.observations == 0 and result.shacl_conforms is True
    table = pq.read_table(result.out_dir / "observations.parquet")
    assert table.num_rows == 0 and "value" in table.column_names and "stock_iri" in table.column_names


def test_explicit_validation_skip_is_not_reported_as_a_pass(tmp_path, vocab):
    _, _, prior = run(tmp_path, vocab)
    before = bytes_tree(prior.out_dir)
    spec, raw = prepare(tmp_path, csv_text=CSV.replace("001,2000,", "001,0,"))
    skipped = build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=tmp_path / "skipped", validate=False)
    report = json.loads((skipped.out_dir / "report.json").read_text())
    assert skipped.shacl_conforms is None
    assert report["checks"]["shacl"] == {"status": "skipped", "conforms": None}
    assert report["publication_ready"] is False
    assert bytes_tree(prior.out_dir) == before


def test_human_decisions_are_never_silently_ignored(tmp_path, vocab, monkeypatch):
    project = tmp_path / "isolated-project"
    (project / "reviews").mkdir(parents=True)
    (project / "reviews/decisions.csv").write_text(
        "target,decision,reviewer,reviewer_orcid,date,amended_object,note\n"
        "https://example.test/candidate,humanAccepted,Fixture reviewer,,2026-10-24,,Fictional test only\n")
    monkeypatch.setattr(config, "ROOT", project)
    spec, raw = prepare(tmp_path)
    with pytest.raises(ValueError, match="human review decisions exist"):
        build_dataset(spec, build_date="2026-10-24", vocab=vocab(), raw_dir=raw, out_dir=tmp_path / "not-approved")
    assert not (tmp_path / "not-approved").exists()


def test_unknown_licence_private_build_is_truthful_not_publication_ready(tmp_path, vocab):
    data = document()
    data["source"]["licence"] = None
    _, _, result = run(tmp_path, vocab, data)
    assert result.shacl_conforms is True
    report = json.loads((result.out_dir / "report.json").read_text())
    assert report["publication_ready"] is False
    assert any("licence URI is unknown" in gap for gap in report["publication_gaps"])
    dataset_text = (result.out_dir / "sdp/metadata/dataset.csv").read_text()
    assert "publicdomain" not in dataset_text.lower() and "CC0" not in dataset_text
