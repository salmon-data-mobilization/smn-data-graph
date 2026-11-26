"""Build and verify the selected source intake, then admit each package to a local store."""

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
BATCHES = {
    1: ("dfo-rs-productivity", "nwfsc-columbia-chum-2020", "sasap-sockeye-brood"),
    2: ("dfo-smu-cu-du-lookup", "nwfsc-snake-chinook-pit-model", "sasap-alaska-harvest-sectors"),
    3: (
        "dfo-atlantic-salmon-watch-bc",
        "dfo-bc-lake-acoustic-targets",
        "dfo-cwt-release",
        "dfo-fraser-river-flows",
        "dfo-pacific-estuary-habitat",
        "dfo-pacific-postseason-catch",
        "dfo-ricker-beam-trawl",
        "dfo-salish-sea-juvenile-trawl",
        "dfo-sep-postseason-production",
        "dfo-south-coast-chinook-reference-fishery",
        "california-chinook-ecosystem-indicators",
        "cedar-river-off-channel-fish",
        "coleman-chinook-metabolism",
        "ctuir-chinook-radio-tracking",
        "elwha-chinook-outmigration",
        "hood-canal-steelhead-monitoring",
        "idaho-juvenile-steelhead-snorkel",
        "lower-granite-adult-steelhead",
        "methow-river-fish-production",
        "puget-sound-edge-habitat-fish",
        "adfg-copper-chinook-escapement",
        "koyukuk-chum-en-route-mortality",
        "pws-hatchery-origin-salmon",
        "pws-pink-salmon-parentage",
        "sasap-alaska-fish-passage",
        "sasap-alaska-fishery-disasters",
        "sasap-alaska-regional-abundance",
        "sasap-alaska-salmon-permit-earnings",
        "sasap-ne-pacific-coho-broods",
        "sasap-regional-salmon-weights",
    ),
}


# Sources sharing a published format can share a verifier. Each verifier reads
# the pinned source independently and takes the actual saved Spec as input.
SHARED_VERIFIERS = {
    "specs.dfo_pacific_tables_parser:parse": "verify_dfo_pacific_tables.py",
    "specs.knb_lexical_csv:parse": "verify_knb_lexical_csv.py",
    "specs.west_coast_csv:parse": "verify_west_coast_csv.py",
}


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
    parser.add_argument("--batch", type=int, choices=BATCHES, default=1, help="Source batch to replay (default: 1)")
    parser.add_argument("--intake-dir", type=Path, required=True, help="Directory with <source>/raw inputs and <source>/build outputs")
    parser.add_argument("--store", type=Path, required=True, help="Local Oxigraph database directory")
    parser.add_argument("--build-date", required=True, help="Explicit ISO date for the derived graph")
    args = parser.parse_args()

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
    for slug in BATCHES[args.batch]:
        source_dir = intake_dir / slug
        raw, build = source_dir / "raw", source_dir / "build"
        spec_dir = SPECS / slug
        spec_path = spec_dir / f"{slug}.yaml"
        spec = load_spec(spec_path)
        # The executor resolves custom parser modules inside its own source tree.
        # Compare the actual staged module before the executor fingerprints and runs it.
        verifier = spec_dir / "verify_source.py"
        verifier_args = []
        if spec.parser in SHARED_VERIFIERS:
            verifier = Path(__file__).with_name(SHARED_VERIFIERS[spec.parser])
            verifier_args = ["--spec", str(spec_path)]
        if ":" in spec.parser:
            module, _ = spec.parser.split(":", 1)
            parser_file = Path(*module.split(".")).with_suffix(".py")
            if (config.ROOT / parser_file).read_bytes() != (SPECS.parent / parser_file).read_bytes():
                raise ValueError(f"Stage the current {parser_file} in the isolated executor")
        if spec.parser != "csv" and not verifier.is_file():
            raise ValueError(f"{slug}: this parser requires an independent source comparison")
        # Rebuild in isolation. A changed source, date, SDK or parser must never
        # replace a previously verified package before the store checks its graph.
        with tempfile.TemporaryDirectory(dir=source_dir) as temporary:
            staged = Path(temporary) / "build"
            build_dataset(spec, raw_dir=raw, out_dir=staged, vocab=vocab, build_date=args.build_date)
            if verifier.is_file():
                subprocess.run(
                    [sys.executable, str(verifier), *verifier_args, "--raw-dir", str(raw), "--build-dir", str(staged)],
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

    # All selected packages passed their source checks. The loader checks each manifest
    # and commits its graphs in one transaction. Replaying identical builds is safe.
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = ox.Store(str(store_path))
    for build in builds:
        manifest = load_dataset_build(store, build)
        print(f"{manifest['dataset_iri']}  {sum(manifest['quad_counts'].values())} quads", flush=True)
    store.flush()


if __name__ == "__main__":
    main()
