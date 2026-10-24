"""Malick Anvik lexical source fidelity, source pins, and current-format admission.

No research result or age convention is a test fixture. Actual-source cases
require an explicit local cache path; no test fetches a source or installs SDKs.
"""
from dataclasses import replace
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import socket
from zipfile import ZipFile

import metasalmonpy as ms
import pandas as pd
import pyarrow.parquet as pq
import pyoxigraph as ox
import pytest
import yaml

from conftest import tiny_sources
from salmongraph import combine, config, iri
from salmongraph.executor import build_dataset
from salmongraph.spec import SpecError, load_spec, validate_spec
from salmongraph.vocab import VocabIndex, VocabSource, PSC_DOCUMENT_PATTERNS
from specs import malick_anvik_parser as parser

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "specs/malick-chum-anvik/malick-chum-anvik.yaml"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    attempted = []
    def blocked(*a, **kw):
        attempted.append(True)
        raise AssertionError("Malick tests must not attempt network")
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr",
                 "getnameinfo", "create_connection"):
        monkeypatch.setattr(socket, name, blocked)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, blocked)
    yield
    assert attempted == []


@pytest.fixture
def spec():
    return load_spec(SPEC)


@pytest.fixture
def tiny_vocab():
    return VocabIndex(tiny_sources(), offline=True)


@pytest.fixture
def actual_raw():
    supplied = os.environ.get("MALICK_ANVIK_SOURCE_DIR")
    if not supplied:
        pytest.skip("Actual deposited bytes require explicit MALICK_ANVIK_SOURCE_DIR")
    return Path(supplied)


@pytest.fixture
def actual_vocab():
    supplied = os.environ.get("MALICK_ANVIK_VOCAB_DIR")
    if not supplied:
        pytest.skip("Actual frozen vocabularies require explicit MALICK_ANVIK_VOCAB_DIR")
    folder = Path(supplied)
    return VocabIndex([
        VocabSource("smn", config.SMN_NS, "Explicit cached smn bytes", folder / "smn.ttl"),
        VocabSource("gcdfo", config.GCDFO_NS, "Explicit cached gcdfo bytes", folder / "gcdfo.ttl"),
        VocabSource("psc", config.PSC_VOCAB_NS, "Explicit cached PSC bytes", folder / "psc.ttl",
                    non_term=PSC_DOCUMENT_PATTERNS)], offline=True)


def source_rows(raw):
    with ZipFile(raw / parser.ARCHIVE_NAME) as archive:
        return {table: list(csv.reader(io.StringIO(
            archive.read(parser.PREFIX + table + ".csv").decode()), strict=True))
            for table in parser.HEADERS}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_saved_spec_is_wholly_lexical_with_truthful_original_zip(spec, tiny_vocab):
    assert validate_spec(spec, tiny_vocab) == []
    assert spec.version == "v1.1" and spec.public is True
    assert spec.source["licence"] == "https://creativecommons.org/publicdomain/zero/1.0/"
    assert spec.source["files"] == [{"name": parser.ARCHIVE_NAME,
        "url": parser.ARCHIVE_URL, "sha256": parser.ARCHIVE_SHA256}]
    assert spec.parser == "specs.malick_anvik_parser:parse"
    assert not spec.identity and not spec.observations and not spec.term_requests
    assert [t["id"] for t in spec.tables] == list(parser.HEADERS)
    for table in spec.tables:
        assert table["file"] == parser.ARCHIVE_NAME
        assert [c["name"] for c in table["columns"]] == list(parser.HEADERS[table["id"]])
        for column in table["columns"]:
            assert column["datatype"] == "string" and column["role"] == "attribute"
            assert "mark" not in column and not column.get("codes")
            assert all(column.get(k) is None for k in
                ("concept", "unit", "year_basis", "age_notation", "method",
                 "estimate_type", "decomposition"))


@pytest.mark.parametrize("change", ["numeric", "identity", "mark", "codes"])
def test_leaving_whole_lexical_boundary_restores_native_age_gate(tmp_path, tiny_vocab, change):
    data = yaml.safe_load(SPEC.read_text())
    if change == "numeric":
        data["tables"][0]["columns"][5]["datatype"] = "integer"
    elif change == "identity":
        data["identity"] = [{"table": "chum_data", "column": "stock.id",
                            "kind": "stock", "authority": "malick-native"}]
    elif change == "mark":
        data["tables"][0]["columns"][0]["mark"] = {
            "aspect": "label", "confidence": "high", "evidence": ["Software boundary fixture only"]}
    else:
        data["tables"][0]["columns"][1]["codes"] = {"2": None}
    path = tmp_path / "changed.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    errors = validate_spec(load_spec(path), tiny_vocab)
    assert any("age_notation" in e and "columns[15]" in e for e in errors)


def synthetic_rows():
    # Fictional lexical selection controls, not a replacement scientific source.
    rows = {"chum_data": [], "chum_info": [], "chum_sources": [["16", "Fixture A"], ["18", "Fixture B"]]}
    for i in range(22):
        row = ["349", "source species", "source stock", "source region", "source subregion",
               str(1900 + i), "001.2500", "", "", "", "2", "3", "4", "5", "", "avg"]
        rows["chum_data"].append(row)
    rows["chum_data"].insert(0, ["other"] + [""] * 15)
    rows["chum_info"] = [["349", "source species", "source stock", "r", "sr", "j",
                          "0.000", "-1.000", "16, 18", ""]]
    return rows


def test_selector_never_filters_use_age_year_or_values_and_preserves_inputs():
    rows = synthetic_rows()
    rows["chum_data"][2][8] = "1"
    rows["chum_data"][3][15] = "age4"
    original = copy.deepcopy(rows)
    selected = parser._select(rows)
    assert selected["chum_data"] == rows["chum_data"][1:]
    assert selected["chum_info"] == rows["chum_info"]
    assert selected["chum_sources"] == rows["chum_sources"]
    assert rows == original and all(isinstance(v, str) for row in selected["chum_data"] for v in row)


@pytest.mark.parametrize("fault", ["missing-stock", "duplicate-key", "source-link", "missing-source"])
def test_selector_fails_closed_on_native_key_or_source_link_loss(fault):
    rows = synthetic_rows()
    if fault == "missing-stock": rows["chum_data"].pop()
    elif fault == "duplicate-key": rows["chum_data"][2][5] = rows["chum_data"][1][5]
    elif fault == "source-link": rows["chum_info"][0][8] = "16, 99"
    else: rows["chum_sources"].pop()
    with pytest.raises(ValueError):
        parser._select(rows)


@pytest.mark.parametrize("table", list(parser.HEADERS))
def test_csv_member_schema_refuses_missing_or_renamed_columns(table):
    with pytest.raises(ValueError, match="schema/row count"):
        parser._csv(b"renamed\nvalue\n", table)


def test_actual_parser_matches_all_native_rows_cells_and_member_pins(spec, actual_raw):
    archive = actual_raw / parser.ARCHIVE_NAME
    before = sha(archive)
    assert before == parser.ARCHIVE_SHA256
    frames = parser.parse(spec=spec, raw_dir=actual_raw)
    rows = source_rows(actual_raw)
    selected = parser._select({name: grid[1:] for name, grid in rows.items()})
    assert {name: (len(frame), len(frame.columns)) for name, frame in frames.items()} == {
        "chum_data": (22, 16), "chum_info": (1, 10), "chum_sources": (2, 2)}
    assert sum(len(frame) * len(frame.columns) for frame in frames.values()) == 366
    for name, frame in frames.items():
        assert frame.values.tolist() == selected[name]
        assert list(frame.columns) == rows[name][0]
    with ZipFile(archive) as zipped:
        assert all(hashlib.sha256(zipped.read(parser.PREFIX + name)).hexdigest() == pin
                   for name, pin in parser.MEMBER_SHA256.items())
    assert frames["chum_data"]["age"].tolist() == ["data"] * 22
    assert frames["chum_data"]["use"].tolist() == ["1"] * 22
    assert all(value == "" for col in ("recruits.2", "recruits.7") for value in frames["chum_data"][col])
    assert frames["chum_info"]["source.id"].tolist() == ["16, 18"]
    assert sha(archive) == before


def test_parser_refuses_mutated_zip_and_false_subset_url(spec, actual_raw, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    payload = (actual_raw / parser.ARCHIVE_NAME).read_bytes()
    (raw / parser.ARCHIVE_NAME).write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
    with pytest.raises(ValueError, match="archive SHA256"):
        parser.parse(spec=spec, raw_dir=raw)
    source = copy.deepcopy(spec.source)
    source["files"][0]["url"] = "https://example.test/not-the-original-subset.csv"
    with pytest.raises(ValueError, match="actual original archive"):
        parser.parse(spec=replace(spec, source=source), raw_dir=actual_raw)


def test_parser_rejects_archive_symlink(spec, actual_raw, tmp_path):
    (tmp_path / parser.ARCHIVE_NAME).symlink_to(actual_raw / parser.ARCHIVE_NAME)
    with pytest.raises(ValueError, match="regular file"):
        parser.parse(spec=spec, raw_dir=tmp_path)


def test_actual_current_build_preserves_grid_and_loader_is_idempotent(spec, actual_raw, actual_vocab, tmp_path):
    original_hash = sha(actual_raw / parser.ARCHIVE_NAME)
    result = build_dataset(spec, build_date="2026-10-24", vocab=actual_vocab,
                           raw_dir=actual_raw, out_dir=tmp_path / "build")
    manifest = json.loads((result.out_dir / "manifest.json").read_text())
    assert manifest["schema"] == "salmongraph-build/1"
    assert manifest["observations"] == 0 and manifest["review_counts"] == {}
    assert manifest["publication_ready"] is False
    assert manifest["sources"][0]["sha256"] == parser.ARCHIVE_SHA256
    assert manifest["parser"]["source_sha256"] == sha(ROOT / "specs/malick_anvik_parser.py")
    assert pq.ParquetFile(result.out_dir / "observations.parquet").metadata.num_rows == 0
    expected = parser.parse(spec=spec, raw_dir=actual_raw)
    sdk_frames = ms.read_salmon_datapackage(str(result.out_dir / "sdp"))["resources"]
    for name, frame in expected.items():
        with (result.out_dir / "sdp/data" / (name + ".csv")).open(newline="") as handle:
            grid = list(csv.reader(handle, strict=True))
        assert grid == [list(frame.columns)] + frame.values.tolist()
        actual = sdk_frames[name]
        assert list(actual.columns) == list(frame.columns)
        for i, row in enumerate(frame.itertuples(index=False, name=None)):
            for j, value in enumerate(row):
                found = actual.iloc[i, j]
                assert (found == "" or pd.isna(found)) if value == "" else (isinstance(found, str) and found == value)
    store = ox.Store()
    report = combine.load_dataset_build(store, result.out_dir)
    before = set(store)
    assert combine.load_dataset_build(store, result.out_dir) == report and set(store) == before
    forbidden_types = {N for N in (config.STATIC_NS["qb"] + "Observation",
        config.STATIC_NS["smn"] + "Stock", config.STATIC_NS["smn"] + "Population")}
    assert not any(q.predicate.value == config.STATIC_NS["rdf"] + "type"
        and isinstance(q.object, ox.NamedNode) and q.object.value in forbidden_types for q in store)
    assert not any(q.predicate.value in {config.STATIC_NS["skos"] + "exactMatch",
        config.STATIC_NS["owl"] + "sameAs", config.current().profile_base + "reviewStatus"} for q in store)
    # A changed output fails the real current loader before caller mutation.
    with (result.out_dir / "sdp/data/chum_data.csv").open("a") as handle:
        handle.write("not declared by the manifest\n")
    with pytest.raises(ValueError):
        combine.load_dataset_build(store, result.out_dir)
    assert set(store) == before and sha(actual_raw / parser.ARCHIVE_NAME) == original_hash


def test_age_gate_build_refusal_preserves_existing_output(actual_raw, actual_vocab, tmp_path):
    data = yaml.safe_load(SPEC.read_text())
    data["tables"][0]["columns"][5]["datatype"] = "integer"
    path = tmp_path / "unreviewed.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    output = tmp_path / "existing"
    output.mkdir()
    (output / "user-owned").write_text("Preserve this output")
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(SpecError, match="age_notation"):
        build_dataset(load_spec(path), build_date="2026-10-24", vocab=actual_vocab,
                      raw_dir=actual_raw, out_dir=output)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before
