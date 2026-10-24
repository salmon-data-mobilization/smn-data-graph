"""Reproduce the lexical Ohlberger PWS build from original, pinned local files.

No fetch, install, source modification, publication or scientific acceptance
occurs. The accompanying attribution inventory is outside the genuine build.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import socket
import sys

PROJECT = Path(__file__).resolve().parents[2]
# Ordinary standalone CLI imports; no parser, config ROOT or SDK guard changes.
sys.path.insert(0, str(PROJECT))
HERE = Path(__file__).resolve().parent
SPEC_PATH = HERE / "ohlberger-pws-2021.yaml"
EVIDENCE_PATH = HERE / "source-evidence.json"
CSV_NAME = "GCB-21-1726 Data.csv"
README_NAME = "GCB-21-1726 README.rtf"
LOCAL_ALIASES = {CSV_NAME: "GCB-21-1726-Data.csv", README_NAME: "GCB-21-1726-README.rtf"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_grid(raw_dir):
    """Read source text, consuming only the BOM as an encoding marker."""
    with (Path(raw_dir) / CSV_NAME).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle, strict=True))


def _external_new_path(path, build_dir):
    """Refuse unmanifested files inside a current-format build or overwrites."""
    path, build_dir = Path(path).absolute(), Path(build_dir).absolute()
    if ".." in path.parts or ".." in build_dir.parts:
        raise ValueError("receipt paths cannot use parent traversal")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("receipt paths cannot use symlinks")
    if path.exists():
        raise ValueError("receipt already exists; preserve earlier evidence")
    if path == build_dir or path.is_relative_to(build_dir) or build_dir.is_relative_to(path):
        raise ValueError("accompanying receipts must be outside the genuine build directory")
    return path


def _write_new_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def stage_original_sources(raw_dir, staging_dir, *, spec, out_dir=None):
    """Copy exact original bytes to declared filename aliases, without overwrite.

    Existing matching regular files can be reused. Different content, symlinks,
    traversal and overlap with originals/build/source code fail before copying.
    """
    raw_dir, staging_dir = Path(raw_dir).absolute(), Path(staging_dir).absolute()
    candidates = [raw_dir, staging_dir]
    if out_dir is not None:
        candidates.append(Path(out_dir).absolute())
    for path in candidates:
        if ".." in path.parts or any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("source staging cannot use symlinks or parent traversal")
    pairs = [(raw_dir, staging_dir), (staging_dir, HERE)]
    if out_dir is not None:
        pairs += [(staging_dir, candidates[-1]), (raw_dir, candidates[-1])]
    if any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for a, b in pairs):
        raise ValueError("source staging, original source, code and build directories must not overlap")
    expected = {item["name"]: item for item in spec.source["files"]}
    if set(expected) != set(LOCAL_ALIASES.values()):
        raise ValueError("source staging requires the exact documented alias declarations")
    payloads = []
    for original, alias in LOCAL_ALIASES.items():
        source, destination = raw_dir / original, staging_dir / alias
        if source.is_symlink() or not source.is_file():
            raise ValueError("original source must be a regular file: " + original)
        payload = source.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected[alias]["sha256"]:
            raise ValueError("original source SHA256 mismatch: " + original)
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise ValueError("local alias must be a regular file: " + alias)
        if destination.exists() and destination.read_bytes() != payload:
            raise ValueError("local alias content differs; no overwrite: " + alias)
        payloads.append((destination, payload))
    # All existing inputs/aliases are checked before any new directory or file.
    staging_dir.mkdir(parents=True, exist_ok=True)
    for destination, payload in payloads:
        if not destination.exists():
            with destination.open("xb") as handle:
                handle.write(payload)
        if destination.is_symlink() or destination.read_bytes() != payload:
            raise ValueError("local alias changed during staging: " + destination.name)
    return staging_dir


def attribution_inventory(build_dir, *, spec, build_date):
    """Describe source attribution for every unchanged generated file.

    This accompanies CC-BY source material. It does not relicense the executor
    software, imply a publisher release, or confer scientific approval.
    """
    build_dir = Path(build_dir)
    paths = sorted(path for path in build_dir.rglob("*") if path.is_file())
    records = []
    for path in paths:
        relative = path.relative_to(build_dir).as_posix()
        if relative == "sdp/data/pws_data.csv":
            change = ("Derived CSV serialization of the entire original table. UTF-8 BOM consumed "
                      "as encoding; all headers, 60-row order, 1560 lexical cells and 197 NA tokens retained. "
                      "No filtering, numeric conversion, imputation or scientific interpretation.")
        else:
            change = ("Generated structural/provenance, dictionary, report or current-build metadata "
                      "accompanying the original source table; not an original publisher file. "
                      "Zero measured observations, identity bridges or review acceptance.")
        records.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path),
                        "source_citation": spec.source["attribution"],
                        "source_doi": spec.source["doi"], "licence": spec.source["licence"],
                        "source_urls": [item["url"] for item in spec.source["files"]],
                        "source_filename_mapping": LOCAL_ALIASES,
                        "change_note": change})
    return {"schema": "ohlberger-pws-accompanying-attribution/1", "files": records,
            "derived_build_date": build_date, "publisher_version": None,
            "derived_spec_version": spec.version, "publication_ready": False,
            "licence_scope": "CC BY 4.0 applies to the deposited source material; this inventory does not relicense executor software or other datasets.",
            "placement": "Accompanying sidecar outside the genuine current-format build; no output bytes changed."}


def write_attribution_inventory(build_dir, path, *, spec, build_date):
    path = _external_new_path(path, build_dir)
    inventory = attribution_inventory(build_dir, spec=spec, build_date=build_date)
    _write_new_json(path, inventory)
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True,
                        help="Original CSV and README.rtf directory; no downloads occur")
    parser.add_argument("--vocab-dir", type=Path, required=True,
                        help="Explicit existing offline smn.ttl/gcdfo.ttl/psc.ttl directory")
    parser.add_argument("--staging-dir", type=Path, required=True,
                        help="Separate local directory for byte-identical safe-filename aliases")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--build-date", required=True, help="Explicit derived execution date YYYY-MM-DD")
    parser.add_argument("--receipt", type=Path, required=True, help="New build verification JSON outside build")
    parser.add_argument("--attribution-receipt", type=Path, required=True,
                        help="New per-file accompanying attribution JSON outside build")
    args = parser.parse_args()
    receipt_path = _external_new_path(args.receipt, args.out_dir)
    attribution_path = _external_new_path(args.attribution_receipt, args.out_dir)
    if receipt_path == attribution_path:
        parser.error("verification and attribution receipts must be different files")
    for path in (receipt_path, attribution_path):
        if any(path == folder or path.is_relative_to(folder) for folder in
               (args.raw_dir.absolute(), args.staging_dir.absolute(), HERE)):
            parser.error("receipts cannot be inside source, staging or code directories")
    attempts = Counter()

    def blocked(name):
        def fail(*unused_args, **unused_kwargs):
            attempts[name] += 1
            raise RuntimeError("Ohlberger reproduction must remain offline: " + name)
        return fail

    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr",
                 "getnameinfo", "create_connection"):
        setattr(socket, name, blocked(name))
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            setattr(socket.socket, name, blocked("socket." + name))
    # Ten outer counters precede third-party imports and catch swallowed probes.
    import metasalmonpy as ms
    import pyarrow.parquet as pq
    import pyoxigraph as ox
    from salmongraph import combine, config
    from salmongraph.executor import build_dataset
    from salmongraph.spec import load_spec, validate_spec
    from salmongraph.vocab import PSC_DOCUMENT_PATTERNS, VocabIndex, VocabSource

    spec = load_spec(SPEC_PATH)
    inputs = [SPEC_PATH, EVIDENCE_PATH, Path(__file__),
              *(args.raw_dir / original for original in LOCAL_ALIASES)]
    before = {str(path): sha256(path) for path in inputs}
    staged = stage_original_sources(args.raw_dir, args.staging_dir, spec=spec, out_dir=args.out_dir)
    staged_before = {alias: sha256(staged / alias) for alias in LOCAL_ALIASES.values()}
    cfg = config.current()
    vocab = VocabIndex([
        VocabSource("smn", config.SMN_NS, "Explicit existing cached smn bytes", args.vocab_dir / "smn.ttl"),
        VocabSource("gcdfo", config.GCDFO_NS, "Explicit existing cached gcdfo bytes", args.vocab_dir / "gcdfo.ttl"),
        VocabSource("psc", config.PSC_VOCAB_NS, "Explicit existing cached PSC bytes", args.vocab_dir / "psc.ttl",
                    non_term=PSC_DOCUMENT_PATTERNS)], cfg=cfg, offline=True)
    errors = validate_spec(spec, vocab)
    if errors:
        raise ValueError("Lexical Spec validation failed: " + "\n".join(errors))
    expected = source_grid(args.raw_dir)
    assert len(expected) == 61 and all(len(row) == 26 for row in expected)
    assert len({row[0] for row in expected[1:]}) == 60
    assert sum(value == "NA" for row in expected[1:] for value in row) == 197
    assert not any(value == "" for row in expected[1:] for value in row)
    result = build_dataset(spec, build_date=args.build_date, vocab=vocab,
                           raw_dir=staged, out_dir=args.out_dir)
    manifest = json.loads((result.out_dir / "manifest.json").read_text())
    output_csv = result.out_dir / "sdp/data/pws_data.csv"
    with output_csv.open(encoding="utf-8", newline="") as handle:
        assert list(csv.reader(handle, strict=True)) == expected
    frame = ms.read_salmon_datapackage(str(result.out_dir / "sdp"))["resources"]["pws_data"]
    assert list(frame.columns) == expected[0] and frame.values.tolist() == expected[1:]
    assert all(isinstance(value, str) for row in frame.itertuples(index=False, name=None) for value in row)
    assert pq.ParquetFile(result.out_dir / "observations.parquet").metadata.num_rows == 0
    assert manifest["observations"] == 0 and manifest["review_counts"] == {}
    assert manifest["publication_ready"] is False and spec.public is True
    assert manifest["validation"]["shacl"]["conforms"] is True
    store = ox.Store()
    loaded = combine.load_dataset_build(store, result.out_dir)
    first = set(store)
    assert loaded == manifest
    assert combine.load_dataset_build(store, result.out_dir) == loaded and set(store) == first
    forbidden_types = {config.STATIC_NS["qb"] + "Observation", config.SMN_NS + "Stock",
                       config.SMN_NS + "Population", config.STATIC_NS["rdf"] + "Statement"}
    assert not any(q.predicate.value == config.STATIC_NS["rdf"] + "type" and
                   isinstance(q.object, ox.NamedNode) and q.object.value in forbidden_types for q in store)
    forbidden_predicates = {config.STATIC_NS["qb"] + "concept", config.STATIC_NS["qudt"] + "unit",
                            config.STATIC_NS["skos"] + "exactMatch", config.STATIC_NS["owl"] + "sameAs",
                            cfg.profile_base + "reviewStatus", config.SMN_NS + "broodYear",
                            config.SMN_NS + "returnYear"}
    assert not any(q.predicate.value in forbidden_predicates for q in store)
    assert {str(path): sha256(path) for path in inputs} == before
    assert {alias: sha256(staged / alias) for alias in LOCAL_ALIASES.values()} == staged_before
    assert not attempts
    inventory = write_attribution_inventory(result.out_dir, attribution_path,
                                            spec=spec, build_date=args.build_date)
    # Sidecar generation is read-only with respect to every build file.
    assert inventory == attribution_inventory(result.out_dir, spec=spec, build_date=args.build_date)
    receipt = {
        "schema": "ohlberger-pws-lexical-build-verification/1",
        "source_record": "https://zenodo.org/records/5780246", "source_doi": spec.source["doi"],
        "source_publication_date": "2021-12-14", "publisher_version": None,
        "source_resource_type": {"type": "publication", "subtype": "article"},
        "derived_spec_version": spec.version, "derived_build_date": args.build_date,
        "source_version_is_build_date": False, "build_root": str(result.out_dir),
        "input_sha256": before, "manifest_sha256": sha256(result.out_dir / "manifest.json"),
        "source_filename_mapping": LOCAL_ALIASES, "staged_source_sha256": staged_before,
        "originals_and_aliases_byte_identical": True,
        "rows": 60, "columns": 26, "cells": 1560, "literal_NA_cells": 197, "blank_cells": 0,
        "all_source_derived_csv_and_sdk_strings_match": True, "row_order_preserved": True,
        "observations": 0, "identity_declarations": 0, "semantic_mappings": 0,
        "review_decisions": 0, "review_queue_rows": 0, "measured_intake_complete": False,
        "rights_confirmed": spec.public, "source_licence": spec.source["licence"],
        "publication_ready": False, "current_loader_passed": True, "reload_idempotent": True,
        "quad_counts": manifest["quad_counts"], "validation": manifest["validation"],
        "configuration": manifest["configuration"], "vocabulary_pins": vocab.pins_dict(),
        "source_originals_and_owned_files_unchanged": True,
        "attribution_receipt": str(attribution_path), "attribution_sha256": sha256(attribution_path),
        "attribution_files": len(inventory["files"]), "build_files_unchanged_by_attribution": True,
        "network_attempts": dict(attempts), "network_attempts_total": sum(attempts.values()),
        "network_scope": "Ten outer Python DNS/socket hooks before imports; not a kernel/native-process network measurement",
        "limitations": ["Lexical source discovery only; no measured observations or accepted interpretations.",
                        "README Year is return year and Spawners refers to two years prior; neither is transformed.",
                        "README mean_pH is described as pCO2; ambiguity remains unresolved.",
                        "No Malick overlap identity, brood-year shift, numerical comparison or scientific approval.",
                        "Actual source creator/contact/date contract gaps remain in generated publication report."],
        "external_upload_or_contact": False,
    }
    assert not attempts
    _write_new_json(receipt_path, receipt)
    print(json.dumps({"receipt": str(receipt_path), "sha256": sha256(receipt_path),
                      "attribution_receipt": str(attribution_path), "attribution_sha256": sha256(attribution_path),
                      "observations": 0, "cells": 1560, "quads": len(store), "network_attempts": sum(attempts.values())}))


if __name__ == "__main__":
    main()
