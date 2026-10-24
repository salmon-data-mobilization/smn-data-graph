"""Offline observation-writer contracts using fictional, tiny source records."""

from __future__ import annotations

import copy
from dataclasses import replace
from decimal import Decimal
import socket

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from salmongraph import config, iri
from salmongraph.executor import _source_code_iri, write_observations
from salmongraph.spec import DatasetSpec, SpecError


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("observation tests must be offline")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture
def spec():
    # Unusual names ensure the writer follows explicit bindings, not lexical
    # guesses such as choosing a column named 'year' or 'spawners'.
    return DatasetSpec(
        spec_version=1, slug="fictional-salmon", version="v 1/2",
        title="Fictional source", description="A software fixture, not biological evidence.",
        source={"publisher": "Fixture", "redistribution": "unconfirmed"}, parser="csv",
        tables=({"id": "source.A", "file": "source.csv", "keys": ["source id", "period"],
                 "columns": [
                     {"name": "source id", "role": "identifier", "datatype": "string"},
                     {"name": "period", "role": "dimension", "datatype": "integer"},
                     {"name": "run/code", "role": "dimension", "datatype": "string",
                      "codes": {"A": "gcdfo:FixtureTarget", "gap": None}},
                     {"name": "source count", "role": "measure", "datatype": "number",
                      "concept": "psc:PSC-CV-000035", "unit": "unit:NUM",
                      "year_basis": "smn:broodYear", "method": "gcdfo:FixtureMethod",
                      "estimate_type": "gcdfo:FixtureEstimate",
                      "uncertainty": {"standard_error": "se", "cv": "cv", "lower": "lo", "upper": "hi"}},
                     {"name": "other count", "role": "measure", "datatype": "number",
                      "concept": "psc:PSC-CV-000036", "unit": "unit:NUM", "year_basis": "smn:returnYear"},
                     *({"name": name, "role": "attribute", "datatype": "number"}
                       for name in ("se", "cv", "lo", "hi", "year")),
                 ]},),
        identity=({"table": "source.A", "column": "source id", "kind": "stock", "authority": "fixture"},),
        observations=({"table": "source.A", "key": ["source id", "period"],
                       "dimensions": ["source id", "period", "run/code"],
                       "year_column": "period", "measures": ["source count", "other count"]},),
    )


@pytest.fixture
def frame():
    return pd.DataFrame({
        "source id": ["002", "001/α"], "period": [2001, 2000], "run/code": ["gap", "A"],
        "source count": [-99.0, 0.0], "other count": [-4.125, None],
        "se": [0.25, None], "cv": [0.0, None], "lo": [-120.0, None], "hi": [-100.0, None],
        "year": [1900, 1901],
    })


def column(spec, name):
    return next(c for c in spec.tables[0]["columns"] if c["name"] == name)


def write(tmp_path, spec, frame, name="observations.parquet"):
    path = tmp_path / name
    count = write_observations(spec, {"source.A": frame}, path)
    return count, pq.read_table(path), path


def mark(aspect, confidence="high"):
    return {"aspect": aspect, "confidence": confidence, "evidence": ["Explicit fixture source or mapping evidence."]}


def test_source_semantics_values_origin_keys_and_uncertainty(tmp_path, spec, frame):
    count, table, path = write(tmp_path, spec, frame)
    rows = table.to_pylist()
    assert count == 3
    assert [r["obs_iri"] for r in rows] == sorted(r["obs_iri"] for r in rows)
    first = next(r for r in rows if r["year"] == 2000)
    assert first["value"] == 0.0
    assert first["source id_iri"] == iri.ident("stock", "fixture", "001/α")
    assert first["year_basis_iri"] == config.SMN_NS + "broodYear"
    assert first["obs_iri"] == iri.obs(spec.slug, spec.version, "001/α", 2000,
                                       config.PSC_CONCEPT_NS + "PSC-CV-000035")
    assert first["run/code_iri"] == _source_code_iri(spec.slug, "source.A", "run/code", "A")
    assert first["run/code_iri"] != config.GCDFO_NS + "FixtureTarget"
    count_row = next(r for r in rows if r["year"] == 2001 and r["measure_iri"].endswith("000035"))
    assert count_row["value"] == -99.0  # No silent source-sentinel or sign policy.
    assert count_row["lower"] == -120.0 and count_row["upper"] == -100.0
    assert count_row["standard_error"] == 0.25 and count_row["cv"] == 0.0
    assert count_row["run/code_iri"] == _source_code_iri(spec.slug, "source.A", "run/code", "gap")
    assert count_row["method_iri"] == config.GCDFO_NS + "FixtureMethod"
    assert count_row["estimate_type_iri"] == config.GCDFO_NS + "FixtureEstimate"
    other = next(r for r in rows if r["measure_iri"].endswith("000036"))
    assert other["value"] == -4.125 and other["year_basis_iri"] == config.SMN_NS + "returnYear"
    assert other["method_iri"] is None and other["estimate_type_iri"] is None
    assert other["standard_error"] is None
    assert {r["dataset_iri"] for r in rows} == {iri.dataset(spec.slug, spec.version)}
    assert all(r["review_status"] is None for r in rows)
    assert table.schema.field("value").type == pa.float64()
    assert table.schema.field("year").type == pa.int32()
    assert "period_iri" not in table.column_names and "year_iri" not in table.column_names
    metadata = pq.ParquetFile(path).metadata
    assert metadata.row_group(0).column(0).compression == "ZSTD"


def test_empty_and_all_missing_have_same_explicit_schema(tmp_path, spec, frame):
    _, full, _ = write(tmp_path, spec, frame)
    count, empty, _ = write(tmp_path, spec, frame.iloc[:0], "empty.parquet")
    assert count == 0 and empty.schema == full.schema
    frame["source count"] = pd.Series([pd.NA, None], dtype="object")
    frame["other count"] = np.nan
    count, missing, _ = write(tmp_path, spec, frame, "missing.parquet")
    assert count == 0 and missing.schema == full.schema


def test_missing_non_key_dimensions_are_null_not_invented(tmp_path, spec, frame):
    frame["run/code"] = [None, pd.NA]
    _, table, _ = write(tmp_path, spec, frame)
    assert table["run/code_iri"].null_count == 3


def test_repeat_is_byte_identical_with_row_column_and_measure_order_changes(tmp_path, spec, frame):
    _, _, first = write(tmp_path, spec, frame)
    changed = copy.deepcopy(spec)
    changed.observations[0]["measures"].reverse()
    frame = frame.iloc[::-1, ::-1].reset_index(drop=True)
    _, _, second = write(tmp_path, changed, frame, "second.parquet")
    assert first.read_bytes() == second.read_bytes()


def test_config_override_applies_to_all_minted_nodes_and_explicit_profile_concepts(tmp_path, spec, frame):
    column(spec, "source count")["concept"] = "corp:variables/source-count"
    with config.override(base="https://example.test/data/", profile_base="https://example.test/profile/"):
        _, table, _ = write(tmp_path, spec, frame)
        for row in table.to_pylist():
            assert row["obs_iri"].startswith("https://example.test/data/obs/")
            assert row["dataset_iri"].startswith("https://example.test/data/dataset/")
            assert row["source id_iri"].startswith("https://example.test/data/id/")
            assert row["run/code_iri"].startswith("https://example.test/data/code/")
        assert "https://example.test/profile/variables/source-count" in table["measure_iri"].to_pylist()


def test_code_identity_keeps_table_and_field_scope_without_slug_collisions():
    assert _source_code_iri("fixture", "a.b", "a b", "001/A") != _source_code_iri("fixture", "a.b", "a-b", "001/A")
    assert _source_code_iri("fixture", "a.b", "code", "A") != _source_code_iri("fixture", "a_b", "code", "A")
    assert _source_code_iri("fixture", "a.b", "code", "001") != _source_code_iri("fixture", "a.b", "code", "1")


@pytest.mark.parametrize("aspect,confidence,expected", [
    ("measure-counts", "high", "awaitingReview"),
    ("year-basis", "high", "awaitingReview"),
    ("description", "high", "agentAccepted"),
    ("label", "medium", "awaitingReview"),
])
def test_explicit_dependency_marks_follow_provenance_policy(tmp_path, spec, frame, aspect, confidence, expected):
    # A label on a source identifier can be non-critical. Measure semantics
    # marks remain critical, with no high-confidence critical auto-acceptance.
    target = "source count" if aspect == "measure-counts" else "period" if aspect == "year-basis" else "source id"
    column(spec, target)["mark"] = mark(aspect, confidence)
    _, table, _ = write(tmp_path, spec, frame)
    rows = table.to_pylist()
    if target == "source count":
        assert all(r["review_status"] == expected for r in rows if r["measure_iri"].endswith("000035"))
        assert next(r for r in rows if r["measure_iri"].endswith("000036"))["review_status"] is None
    else:
        assert {r["review_status"] for r in rows} == {expected}


def test_weakest_mark_and_uncertainty_dependency_not_unselected_attributes(tmp_path, spec, frame):
    column(spec, "source id")["mark"] = mark("label")
    column(spec, "se")["mark"] = mark("unit-scale")
    column(spec, "year")["mark"] = mark("year-basis")  # Explicitly not the year/dimension.
    _, table, _ = write(tmp_path, spec, frame)
    rows = table.to_pylist()
    assert next(r for r in rows if r["standard_error"] is not None)["review_status"] == "awaitingReview"
    assert all(r["review_status"] == "agentAccepted" for r in rows if r["standard_error"] is None)


def test_dimension_mapping_mark_remains_pending_including_null_target_gap(tmp_path, spec, frame):
    column(spec, "run/code")["mark"] = mark("identity-equivalence")
    _, table, _ = write(tmp_path, spec, frame)
    assert set(table["review_status"].to_pylist()) == {"awaitingReview"}


@pytest.mark.parametrize("name,semantic_field", [
    ("source count", None), ("period", None), ("run/code", None),
    ("se", "unit"), ("source id", "concept"),
])
def test_direct_writer_refuses_descriptive_evidence_for_semantics_before_output(
        tmp_path, spec, frame, name, semantic_field):
    target = column(spec, name)
    if semantic_field:
        target[semantic_field] = "unit:NUM" if semantic_field == "unit" else "gcdfo:FixtureTarget"
    target["mark"] = mark("label", "high")
    path = tmp_path / "existing.parquet"
    path.write_bytes(b"existing output must be preserved")
    with pytest.raises(SpecError, match="must be critical"):
        write_observations(spec, {"source.A": frame}, path)
    assert path.read_bytes() == b"existing output must be preserved"


@pytest.mark.parametrize("bad", [None, pd.NA, np.nan, True, 2000.5, np.inf, -np.inf, "2000", 2**31, -(2**31)-1])
def test_invalid_years_fail_without_replacing_existing_output(tmp_path, spec, frame, bad):
    frame["period"] = frame["period"].astype(object)
    frame.loc[0, "period"] = bad
    path = tmp_path / "observations.parquet"
    path.write_bytes(b"existing artifact")
    with pytest.raises(ValueError):
        write_observations(spec, {"source.A": frame}, path)
    assert path.read_bytes() == b"existing artifact"


def test_exact_integral_year_values_have_no_invented_calendar_window(tmp_path, spec, frame):
    frame["period"] = [0.0, -2000.0]
    _, table, _ = write(tmp_path, spec, frame)
    assert set(table["year"].to_pylist()) == {0, -2000}


@pytest.mark.parametrize("bad", [np.inf, -np.inf, True, "123", [1], 2**53 + 1,
                               Decimal("0.123456789123456789"), Decimal("1e-400")])
def test_invalid_or_lossy_numeric_values_fail(tmp_path, spec, frame, bad):
    frame["source count"] = frame["source count"].astype(object)
    frame.at[0, "source count"] = bad
    with pytest.raises(ValueError):
        write(tmp_path, spec, frame)


def test_decimal_and_numpy_scalars_are_written_without_scientific_transform(tmp_path, spec, frame):
    frame["source count"] = pd.Series([Decimal("3.125"), np.int64(42)], dtype=object)
    _, table, _ = write(tmp_path, spec, frame)
    assert sorted(r["value"] for r in table.to_pylist() if r["measure_iri"].endswith("000035")) == [3.125, 42.0]


def test_declared_integer_measures_reject_fractional_source_values(tmp_path, spec, frame):
    column(spec, "source count")["datatype"] = "integer"
    frame.loc[0, "source count"] = 1.25
    with pytest.raises(SpecError, match="exact integral"):
        write(tmp_path, spec, frame)


@pytest.mark.parametrize("name,bad", [("se", -1), ("cv", -0.01), ("lo", np.inf), ("hi", "bad")])
def test_invalid_uncertainty_is_not_silently_dropped(tmp_path, spec, frame, name, bad):
    frame[name] = frame[name].astype(object)
    frame.at[0, name] = bad
    with pytest.raises(ValueError):
        write(tmp_path, spec, frame)


def test_reversed_interval_is_rejected_but_no_containment_rule_is_invented(tmp_path, spec, frame):
    # The standard fixture interval does not contain -99 and is valid. Only
    # reversed interval order is a generic writer error.
    frame.loc[0, "lo"], frame.loc[0, "hi"] = -100, -120
    with pytest.raises(SpecError, match="lower bound"):
        write(tmp_path, spec, frame)


def test_duplicate_keys_fail_even_when_one_row_has_no_measures(tmp_path, spec, frame):
    frame.loc[1, ["source id", "period"]] = frame.loc[0, ["source id", "period"]]
    frame.loc[1, ["source count", "other count"]] = None
    with pytest.raises(SpecError, match="duplicate source key"):
        write(tmp_path, spec, frame)


@pytest.mark.parametrize("bad", [None, "", np.nan, True])
def test_missing_or_invalid_source_keys_fail(tmp_path, spec, frame, bad):
    frame["source id"] = frame["source id"].astype(object)
    frame.at[0, "source id"] = bad
    with pytest.raises(ValueError):
        write(tmp_path, spec, frame)


def test_measure_concept_collision_is_rejected_at_the_same_source_key(tmp_path, spec, frame):
    column(spec, "other count")["concept"] = column(spec, "source count")["concept"]
    with pytest.raises(SpecError, match="IRI collision"):
        write(tmp_path, spec, frame)


def test_collision_across_two_blocks_is_rejected(tmp_path, spec, frame):
    spec = replace(spec, observations=spec.observations + copy.deepcopy(spec.observations))
    with pytest.raises(SpecError, match="IRI collision"):
        write(tmp_path, spec, frame)


@pytest.mark.parametrize("change", ["year-binding", "missing-frame", "missing-column", "unknown-code",
                                    "unbound-dimension", "ambiguous-dimension", "output-name-collision",
                                    "missing-unit", "missing-concept", "missing-basis", "bad-iri",
                                    "uncertainty-pointer", "duplicate-frame-column", "measure-datatype",
                                    "uncertainty-datatype"])
def test_broken_explicit_bindings_fail_before_writing(tmp_path, spec, frame, change):
    frames = {"source.A": frame}
    if change == "year-binding":
        del spec.observations[0]["year_column"]
    elif change == "missing-frame":
        frames = {}
    elif change == "missing-column":
        frames["source.A"] = frame.drop(columns="source count")
    elif change == "unknown-code":
        frame.loc[0, "run/code"] = "undeclared"
    elif change == "unbound-dimension":
        column(spec, "run/code")["codes"] = {}
    elif change == "ambiguous-dimension":
        spec = replace(spec, identity=spec.identity + ({"table": "source.A", "column": "run/code", "kind": "stock", "authority": "fixture"},))
    elif change == "output-name-collision":
        frame["measure"] = "A"
        spec.tables[0]["columns"].append({"name": "measure", "role": "dimension", "datatype": "string", "codes": {"A": None}})
        spec.observations[0]["dimensions"].append("measure")
    elif change.startswith("missing-"):
        field = {"missing-unit": "unit", "missing-concept": "concept", "missing-basis": "year_basis"}[change]
        column(spec, "source count")[field] = None
    elif change == "bad-iri":
        column(spec, "source count")["unit"] = "unknown:invented"
    elif change == "uncertainty-pointer":
        column(spec, "source count")["uncertainty"]["standard_error"] = "not a source column"
    elif change == "duplicate-frame-column":
        frames["source.A"] = pd.concat([frame, frame[["period"]]], axis=1)
    elif change == "measure-datatype":
        column(spec, "source count")["datatype"] = "string"
    elif change == "uncertainty-datatype":
        column(spec, "se")["datatype"] = "string"
    path = tmp_path / "broken.parquet"
    with pytest.raises(ValueError):
        write_observations(spec, frames, path)
    assert not path.exists()
