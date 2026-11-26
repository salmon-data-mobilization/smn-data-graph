"""Build and verify the three pinned source packages, then admit each to a local store."""

import argparse
import csv
import itertools
from pathlib import Path
import tempfile
import subprocess
import sys

import pyoxigraph as ox
from salmongraph import config
from salmongraph.combine import load_dataset_build
from salmongraph.executor import build_dataset
from salmongraph.spec import load_spec
from salmongraph.vocab import VocabIndex


SPECS = Path(__file__).resolve().parents[1]
SOURCES = ("dfo-rs-productivity", "nwfsc-columbia-chum-2020", "sasap-sockeye-brood")


def check_csv(spec, raw, build):
    for table in spec.tables:
        source = raw / table["file"]
        resource = build / "sdp" / "data" / (table["id"] + ".csv")
        with source.open(encoding="utf-8-sig", newline="") as left, resource.open(encoding="utf-8", newline="") as right:
            rows = itertools.zip_longest(csv.reader(left, strict=True), csv.reader(right, strict=True))
            for record, (original, packaged) in enumerate(rows, start=1):
                if original != packaged:
                    raise ValueError(f"{source.name}: packaged CSV differs at record {record}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake-dir", type=Path, required=True, help="Directory with <source>/raw inputs and <source>/build outputs")
    parser.add_argument("--store", type=Path, required=True, help="Local Oxigraph database directory")
    parser.add_argument("--build-date", required=True, help="Explicit ISO date for the derived graph")
    args = parser.parse_args()

    # The executor resolves custom parsers inside its checkout and hashes the code it ran.
    custom = "dfo_rs_productivity_parser.py"
    if (config.ROOT / "specs" / custom).read_bytes() != (SPECS / custom).read_bytes():
        raise ValueError(f"Stage this intake's {custom} in the isolated executor's specs directory")
    intake_dir = args.intake_dir.resolve()
    store_path = args.store.resolve()
    if store_path.is_relative_to(intake_dir) or intake_dir.is_relative_to(store_path):
        raise ValueError("Keep the database separate from inputs and package builds")
    if store_path.exists() and any(store_path.iterdir()) and not (store_path / "CURRENT").is_file():
        raise ValueError("Store path contains other files and has no RocksDB CURRENT file")
    vocab = VocabIndex(offline=True)
    pins = Path(__file__).with_name("vocabularies.tsv")
    with pins.open(encoding="utf-8", newline="") as stream:
        expected = {row["key"]: row["sha256"] for row in csv.DictReader(stream, delimiter="\t")}
    if {key: pin.sha256 for key, pin in vocab.pins.items()} != expected:
        raise ValueError("Local vocabulary files differ from this intake's pins")
    builds = []
    for slug in SOURCES:
        source_dir = intake_dir / slug
        raw, build = source_dir / "raw", source_dir / "build"
        spec_dir = SPECS / slug
        spec = load_spec(spec_dir / f"{slug}.yaml")
        # Rebuild in isolation. A changed source, date, SDK or parser must never
        # replace a previously verified package before the store checks its graph.
        with tempfile.TemporaryDirectory(dir=source_dir) as temporary:
            staged = Path(temporary) / "build"
            build_dataset(spec, raw_dir=raw, out_dir=staged, vocab=vocab, build_date=args.build_date)
            if slug == "dfo-rs-productivity":
                subprocess.run(
                    [sys.executable, str(spec_dir / "verify_source.py"), "--raw-dir", str(raw), "--build-dir", str(staged)],
                    check=True,
                )
            else:
                check_csv(spec, raw, staged)
            if build.exists():
                load_dataset_build(ox.Store(), build)
                if (build / "manifest.json").read_bytes() != (staged / "manifest.json").read_bytes():
                    raise ValueError(f"{slug}: saved build differs. Use a fresh intake directory for changed inputs.")
            else:
                staged.rename(build)
        builds.append(build)

    # All three packages passed their source checks. The loader checks each manifest
    # and commits its graphs in one transaction. Replaying identical builds is safe.
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = ox.Store(str(store_path))
    for build in builds:
        manifest = load_dataset_build(store, build)
        print(f"{manifest['dataset_iri']}  {sum(manifest['quad_counts'].values())} quads", flush=True)
    store.flush()


if __name__ == "__main__":
    main()
