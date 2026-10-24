"""Offline checks of the original Ohlberger source and lexical current build.

Actual publisher bytes and vocabularies require explicit environment paths;
tests never fetch them. No private source table is embedded as a fixture.
"""
import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket

import metasalmonpy as ms
import pyarrow.parquet as pq
import pyoxigraph as ox
import pytest

from salmongraph import combine, config
from salmongraph.executor import build_dataset
from salmongraph.spec import SpecError, load_spec, validate_spec
from salmongraph.vocab import PSC_DOCUMENT_PATTERNS, VocabIndex, VocabSource

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "specs/ohlberger-pws-2021"
SPEC_PATH = FOLDER / "ohlberger-pws-2021.yaml"
EVIDENCE = json.loads((FOLDER / "source-evidence.json").read_text())
module_spec = importlib.util.spec_from_file_location("ohlberger_reproduce", FOLDER / "reproduce.py")
replayer = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(replayer)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    attempted = []
    def blocked(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("Ohlberger tests must not attempt network")
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
    return load_spec(SPEC_PATH)


@pytest.fixture
def actual_raw():
    supplied = os.environ.get("OHLBERGER_PWS_SOURCE_DIR")
    if not supplied:
        pytest.skip("Original deposited bytes require explicit OHLBERGER_PWS_SOURCE_DIR")
    return Path(supplied)


@pytest.fixture
def actual_vocab():
    supplied = os.environ.get("OHLBERGER_PWS_VOCAB_DIR")
    if not supplied:
        pytest.skip("Frozen local vocabularies require explicit OHLBERGER_PWS_VOCAB_DIR")
    folder = Path(supplied)
    return VocabIndex([
        VocabSource("smn", config.SMN_NS, "Explicit cached smn bytes", folder / "smn.ttl"),
        VocabSource("gcdfo", config.GCDFO_NS, "Explicit cached gcdfo bytes", folder / "gcdfo.ttl"),
        VocabSource("psc", config.PSC_VOCAB_NS, "Explicit cached PSC bytes", folder / "psc.ttl",
                    non_term=PSC_DOCUMENT_PATTERNS)], offline=True)


def file_hashes(folder):
    return {path.relative_to(folder).as_posix(): replayer.sha256(path)
            for path in folder.rglob("*") if path.is_file()}


def test_spec_truthfully_distinguishes_source_and_derived_version(spec, tiny_vocab):
    assert validate_spec(spec, tiny_vocab) == []
    assert spec.parser == "csv" and spec.public is True
    assert spec.version == "lexical-cfb985d80518"
    assert EVIDENCE["publisher_record"]["publisher_version"] is None
    assert EVIDENCE["publisher_record"]["resource_type"] == {
        "title": "Journal article", "type": "publication", "subtype": "article"}
    assert EVIDENCE["publisher_record"]["publication_date"] == "2021-12-14"
    assert spec.source["licence"] == "https://creativecommons.org/licenses/by/4.0/"
    assert spec.source["redistribution"] == "confirmed"
    assert "Ohlberger" in spec.source["attribution"] and "2021" in spec.source["attribution"]
    assert "10.5281/zenodo.5780246" in spec.source["attribution"]
    assert "Changes:" in spec.source["attribution"]
    assert len(spec.tables) == 1 and spec.tables[0]["keys"] == ["Year"]
    assert spec.tables[0]["file"] == replayer.LOCAL_ALIASES[replayer.CSV_NAME]
    assert {item["name"] for item in spec.source["files"]} == set(replayer.LOCAL_ALIASES.values())
    assert not spec.identity and not spec.observations and not spec.cross_source_checks and not spec.term_requests
    for column in spec.tables[0]["columns"]:
        assert column["role"] == "attribute" and column["datatype"] == "string"
        assert "mark" not in column and not column.get("codes")
        assert all(column.get(key) is None for key in (
            "concept", "unit", "year_basis", "age_notation", "method", "estimate_type", "decomposition"))


def test_year_scale_and_dictionary_ambiguity_stay_source_descriptions(spec):
    columns = {column["name"]: column for column in spec.tables[0]["columns"]}
    assert "return year" in columns["Year"]["description"]
    assert "two years prior (millions)" in columns["Spawners"]["description"]
    assert "millions" in columns["Escapement"]["description"]
    assert "pCO2 subpolar gyre" in columns["mean_pH"]["description"]
    assert "ambiguity" in columns["mean_pH"]["description"]
    assert columns["Year"]["name"] == "Year" and columns["mean_pH"]["label"] == "mean_pH"
    assert EVIDENCE["candidate_only_overlap_context"]["other_source_is_input"] is False


def test_actual_sources_match_pins_and_entire_unfiltered_grid(actual_raw, spec):
    originals = {alias: original for original, alias in replayer.LOCAL_ALIASES.items()}
    for item in spec.source["files"]:
        assert replayer.sha256(actual_raw / originals[item["name"]]) == item["sha256"]
        assert item["url"].startswith("https://zenodo.org/api/records/5780246/files/")
    payload = (actual_raw / replayer.CSV_NAME).read_bytes()
    assert payload.startswith(b"\xef\xbb\xbf")
    grid = replayer.source_grid(actual_raw)
    assert grid[0] == [column["name"] for column in spec.tables[0]["columns"]]
    assert len(grid) == 61 and all(len(row) == 26 for row in grid)
    assert len({row[0] for row in grid[1:]}) == 60
    assert grid[1][0] == "1960" and grid[-1][0] == "2019"
    assert sum(value == "NA" for row in grid[1:] for value in row) == 197
    assert not any(value == "" for row in grid[1:] for value in row)
    assert grid[1][grid[0].index("Escapement")] == "3.872483"
    assert grid[1][grid[0].index("Spawners")] == "NA"


@pytest.fixture
def actual_staged(spec, actual_raw, tmp_path):
    return replayer.stage_original_sources(actual_raw, tmp_path / "aliases", spec=spec,
                                           out_dir=tmp_path / "build")


@pytest.fixture
def actual_build(spec, actual_staged, actual_vocab, tmp_path):
    return build_dataset(spec, build_date="2026-10-24", vocab=actual_vocab,
                         raw_dir=actual_staged, out_dir=tmp_path / "build")


def test_actual_current_build_preserves_every_cell_and_na_string(actual_build, actual_raw):
    expected = replayer.source_grid(actual_raw)
    with (actual_build.out_dir / "sdp/data/pws_data.csv").open(encoding="utf-8", newline="") as handle:
        assert list(csv.reader(handle, strict=True)) == expected
    frame = ms.read_salmon_datapackage(str(actual_build.out_dir / "sdp"))["resources"]["pws_data"]
    assert list(frame.columns) == expected[0] and frame.values.tolist() == expected[1:]
    assert all(isinstance(value, str) for row in frame.itertuples(index=False, name=None) for value in row)
    assert sum(value == "NA" for row in frame.itertuples(index=False, name=None) for value in row) == 197
    assert pq.ParquetFile(actual_build.out_dir / "observations.parquet").metadata.num_rows == 0


def test_current_loader_is_idempotent_and_no_interpretation_is_admitted(actual_build, spec):
    manifest = json.loads((actual_build.out_dir / "manifest.json").read_text())
    assert manifest["parser"] == {"kind": "csv", "source_sha256": None}
    assert {item["name"]: item["sha256"] for item in manifest["sources"]} == {
        item["name"]: item["sha256"] for item in spec.source["files"]}
    assert manifest["sdp_schema"]["source"] == "vendored"
    assert manifest["observations"] == 0 and manifest["review_counts"] == {}
    assert manifest["publication_ready"] is False
    assert manifest["validation"]["shacl"] == {"status": "passed", "conforms": True}
    store = ox.Store()
    loaded = combine.load_dataset_build(store, actual_build.out_dir)
    before = set(store)
    assert loaded == manifest
    assert combine.load_dataset_build(store, actual_build.out_dir) == loaded and set(store) == before
    forbidden_types = {config.STATIC_NS["qb"] + "Observation", config.SMN_NS + "Stock",
                       config.SMN_NS + "Population", config.STATIC_NS["rdf"] + "Statement"}
    assert not any(q.predicate.value == config.STATIC_NS["rdf"] + "type" and
        isinstance(q.object, ox.NamedNode) and q.object.value in forbidden_types for q in store)
    assert not any(q.predicate.value in {config.STATIC_NS["qb"] + "concept",
        config.STATIC_NS["qudt"] + "unit", config.SMN_NS + "broodYear", config.SMN_NS + "returnYear",
        config.STATIC_NS["skos"] + "exactMatch", config.STATIC_NS["owl"] + "sameAs",
        config.current().profile_base + "reviewStatus"} for q in store)
    # Real current-format hash refusal preserves caller state.
    with (actual_build.out_dir / "sdp/data/pws_data.csv").open("a") as handle:
        handle.write("unmanifested changed data\n")
    with pytest.raises(ValueError):
        combine.load_dataset_build(store, actual_build.out_dir)
    assert set(store) == before


@pytest.mark.parametrize("name", list(replayer.LOCAL_ALIASES.values()))
def test_mutated_source_fails_before_existing_output_changes(name, spec, actual_staged, actual_vocab, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for item in spec.source["files"]:
        shutil.copyfile(actual_staged / item["name"], raw / item["name"])
    with (raw / name).open("ab") as handle:
        handle.write(b"changed")
    output = tmp_path / "existing"
    output.mkdir()
    (output / "user-owned.txt").write_text("Preserve this output")
    before = file_hashes(output)
    with pytest.raises(SpecError, match="source SHA-256 mismatch"):
        build_dataset(spec, build_date="2026-10-24", vocab=actual_vocab, raw_dir=raw, out_dir=output)
    assert file_hashes(output) == before


def test_every_unchanged_output_has_external_attribution(actual_build, spec, tmp_path):
    before = file_hashes(actual_build.out_dir)
    sidecar = tmp_path / "accompanying-attribution.json"
    inventory = replayer.write_attribution_inventory(actual_build.out_dir, sidecar,
        spec=spec, build_date="2026-10-24")
    assert file_hashes(actual_build.out_dir) == before
    assert {item["path"]: item["sha256"] for item in inventory["files"]} == before
    assert "manifest.json" in before and "sdp/data/pws_data.csv" in before
    for item in inventory["files"]:
        assert item["source_citation"] == spec.source["attribution"]
        assert item["source_doi"] == "10.5281/zenodo.5780246"
        assert item["licence"] == "https://creativecommons.org/licenses/by/4.0/"
        assert item["source_urls"] == [entry["url"] for entry in spec.source["files"]]
        assert item["source_filename_mapping"] == replayer.LOCAL_ALIASES
        assert item["change_note"]
    assert json.loads(sidecar.read_text()) == inventory
    with pytest.raises(ValueError, match="already exists"):
        replayer.write_attribution_inventory(actual_build.out_dir, sidecar,
            spec=spec, build_date="2026-10-24")


def test_attribution_sidecar_cannot_pollute_genuine_build(tmp_path, spec):
    output = tmp_path / "build"
    output.mkdir()
    (output / "manifest.json").write_text("Unchanged fixture")
    before = file_hashes(output)
    with pytest.raises(ValueError, match="outside"):
        replayer.write_attribution_inventory(output, output / "attribution.json",
            spec=spec, build_date="2026-10-24")
    assert file_hashes(output) == before


def test_attribution_path_cannot_hide_build_overlap_with_parent_traversal(tmp_path, spec):
    output = tmp_path / "build"
    output.mkdir()
    with pytest.raises(ValueError, match="parent traversal"):
        replayer.write_attribution_inventory(output, tmp_path / "other/../build/attribution.json",
            spec=spec, build_date="2026-10-24")
    assert not list(output.iterdir())


def test_aliases_are_exact_regular_copies_and_can_be_reused_without_changes(spec, actual_raw, tmp_path):
    originals = file_hashes(actual_raw)
    staging = tmp_path / "aliases"
    replayer.stage_original_sources(actual_raw, staging, spec=spec, out_dir=tmp_path / "build")
    before = file_hashes(staging)
    for original, alias in replayer.LOCAL_ALIASES.items():
        assert not (staging / alias).is_symlink()
        assert (staging / alias).read_bytes() == (actual_raw / original).read_bytes()
    assert replayer.stage_original_sources(actual_raw, staging, spec=spec) == staging
    assert file_hashes(staging) == before and file_hashes(actual_raw) == originals


def test_different_alias_fails_without_overwrite_or_partial_copy(spec, actual_raw, tmp_path):
    staging = tmp_path / "aliases"
    staging.mkdir()
    alias = next(iter(replayer.LOCAL_ALIASES.values()))
    (staging / alias).write_bytes(b"Preserve existing different content")
    before = file_hashes(staging)
    with pytest.raises(ValueError, match="content differs; no overwrite"):
        replayer.stage_original_sources(actual_raw, staging, spec=spec)
    assert file_hashes(staging) == before


def test_alias_staging_rejects_symlinks_and_source_or_output_overlap(spec, actual_raw, tmp_path):
    staging = tmp_path / "aliases"
    staging.mkdir()
    alias = next(iter(replayer.LOCAL_ALIASES.values()))
    (staging / alias).symlink_to(actual_raw / replayer.CSV_NAME)
    with pytest.raises(ValueError, match="regular file"):
        replayer.stage_original_sources(actual_raw, staging, spec=spec)
    with pytest.raises(ValueError, match="must not overlap"):
        replayer.stage_original_sources(actual_raw, actual_raw / "nested", spec=spec)
    with pytest.raises(ValueError, match="must not overlap"):
        replayer.stage_original_sources(actual_raw, tmp_path / "build/raw", spec=spec,
                                         out_dir=tmp_path / "build")
