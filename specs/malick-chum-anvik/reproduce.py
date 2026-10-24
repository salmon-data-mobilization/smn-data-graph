"""Reproduce the private lexical Malick Anvik build from original local ZIP bytes.

Run from the project root using the genuine locked runtime. No fetch, model,
SDK patch, parser guard change, source mutation or publication occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import socket
import sys

PROJECT = Path(__file__).resolve().parents[2]
# Normal standalone CLI import bootstrap; parser resolution still uses the
# unchanged project-root specs/malick_anvik_parser.py source guard.
sys.path.insert(0, str(PROJECT))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw-dir", type=Path, required=True,
                   help="Directory containing the original pink-chum-database-1.1.zip")
    p.add_argument("--vocab-dir", type=Path, required=True,
                   help="Explicit existing offline smn.ttl/gcdfo.ttl/psc.ttl cache")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--build-date", required=True, help="Derived execution date YYYY-MM-DD")
    p.add_argument("--receipt", type=Path, required=True, help="New local JSON receipt; never overwritten")
    args = p.parse_args()
    if args.receipt.exists():
        p.error("receipt already exists; preserve earlier evidence")
    attempts = Counter()
    def blocked(name):
        def fail(*a, **kw):
            attempts[name] += 1
            raise RuntimeError("Malick reproduction must remain offline: " + name)
        return fail
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr",
                 "getnameinfo", "create_connection"):
        setattr(socket, name, blocked(name))
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            setattr(socket.socket, name, blocked("socket." + name))
    # Outer counters precede third-party/SDK imports and detect swallowed probes.
    import pandas as pd
    import pyarrow.parquet as pq
    import pyoxigraph as ox
    import metasalmonpy as ms
    from salmongraph import config, combine, iri
    from salmongraph.executor import build_dataset
    from salmongraph.spec import load_spec, validate_spec
    from salmongraph.vocab import VocabIndex, VocabSource, PSC_DOCUMENT_PATTERNS
    from specs.malick_anvik_parser import ARCHIVE_NAME, ARCHIVE_SHA256, parse

    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    spec_path = Path(__file__).with_name("malick-chum-anvik.yaml")
    parser_path = PROJECT / "specs/malick_anvik_parser.py"
    archive_path = args.raw_dir / ARCHIVE_NAME
    before = {str(path): sha(path) for path in (spec_path, parser_path, archive_path)}
    assert before[str(archive_path)] == ARCHIVE_SHA256
    cfg = config.current()
    sources = [
        VocabSource("smn", config.SMN_NS, "Explicit existing cached smn bytes",
                    args.vocab_dir / "smn.ttl"),
        VocabSource("gcdfo", config.GCDFO_NS, "Explicit existing cached gcdfo bytes",
                    args.vocab_dir / "gcdfo.ttl"),
        VocabSource("psc", config.PSC_VOCAB_NS, "Explicit existing cached PSC bytes",
                    args.vocab_dir / "psc.ttl", non_term=PSC_DOCUMENT_PATTERNS),
    ]
    vocab = VocabIndex(sources, cfg=cfg, offline=True)
    spec = load_spec(spec_path)
    problems = validate_spec(spec, vocab)
    if problems:
        raise ValueError("Lexical Spec validation failed: " + "\n".join(problems))
    expected = parse(spec=spec, raw_dir=args.raw_dir)
    result = build_dataset(spec, build_date=args.build_date, vocab=vocab,
                           raw_dir=args.raw_dir, out_dir=args.out_dir)
    manifest = json.loads((result.out_dir / "manifest.json").read_text())
    # Current loader is the actual unchanged entry point, without legacy adapter.
    store = ox.Store()
    loaded = combine.load_dataset_build(store, result.out_dir)
    first = set(store)
    assert combine.load_dataset_build(store, result.out_dir) == loaded and set(store) == first
    assert loaded == manifest and manifest["observations"] == 0
    assert manifest["publication_ready"] is False and manifest["review_counts"] == {}
    frames = ms.read_salmon_datapackage(str(result.out_dir / "sdp"))["resources"]
    import csv
    cells, blanks = 0, 0
    for table, frame in expected.items():
        with (result.out_dir / "sdp/data" / (table + ".csv")).open(newline="") as handle:
            grid = list(csv.reader(handle, strict=True))
        assert grid[0] == list(frame.columns)
        assert grid[1:] == frame.values.tolist()
        actual = frames[table]
        assert list(actual.columns) == list(frame.columns) and len(actual) == len(frame)
        for i, row in enumerate(frame.itertuples(index=False, name=None)):
            for j, value in enumerate(row):
                cells += 1
                found = actual.iloc[i, j]
                if value == "":
                    blanks += 1
                    assert found == "" or pd.isna(found)
                else:
                    assert isinstance(found, str) and found == value
    age_blanks = sum(value == "" for name in ("recruits.2", "recruits.7")
                     for value in expected["chum_data"][name])
    assert cells == 366 and blanks == 45 and age_blanks == 44
    assert pq.ParquetFile(result.out_dir / "observations.parquet").metadata.num_rows == 0
    assert not any(q.predicate.value == config.STATIC_NS["rdf"] + "type"
                   and q.object.value == config.STATIC_NS["qb"] + "Observation"
                   for q in store if isinstance(q.object, ox.NamedNode))
    assert {str(path): sha(path) for path in (spec_path, parser_path, archive_path)} == before
    assert not attempts
    receipt = {
        "schema": "malick-anvik-lexical-phase1-build/1",
        "source_release": {"doi": "10.5281/zenodo.6478751", "version": "v1.1",
                           "publication_date": "2022-04-22", "licence": "CC0-1.0",
                           "archive_sha256": ARCHIVE_SHA256},
        "derived_build_date": args.build_date, "source_version_is_build_date": False,
        "spec_sha256": before[str(spec_path)], "parser_sha256": before[str(parser_path)],
        "build_root": str(result.out_dir), "manifest_sha256": sha(result.out_dir / "manifest.json"),
        "tables": {name: {"rows": len(frame), "columns": len(frame.columns)}
                   for name, frame in expected.items()},
        "native_cells": cells, "blank_cells_total": blanks,
        "blank_age_count_cells": age_blanks,
        "all_native_csv_cells_and_nonblank_sdk_strings_match": True,
        "observations": 0, "identity_declarations": 0, "review_queue_rows": 0,
        "formal_age_notation": None, "semantic_mappings": 0,
        "measured_intake_complete": False,
        "measured_intake_blocker": "Formal age convention unresolved; native age is an assumption flag. Do not satisfy the current name screen with a generic or invented notation.",
        "source_rights_confirmed": spec.public,
        "publication_ready": False, "external_upload_or_contact": False,
        "current_loader_passed": True, "reload_idempotent": True,
        "quad_counts": manifest["quad_counts"], "validation": manifest["validation"],
        "vocabulary_pins": vocab.pins_dict(),
        "network_attempts": dict(attempts), "network_attempts_total": sum(attempts.values()),
        "network_scope": "Ten outer Python DNS/socket hooks before imports; not a kernel/native-process network measurement",
        "original_archive_spec_parser_unchanged": True,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x") as out:
        json.dump(receipt, out, indent=2, sort_keys=True)
        out.write("\n")
    print(json.dumps({"receipt": str(args.receipt), "sha256": sha(args.receipt),
                      "observations": 0, "cells": cells,
                      "quads": sum(manifest["quad_counts"].values()), "network_attempts": sum(attempts.values())}))


if __name__ == "__main__":
    main()
