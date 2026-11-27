"""Witness a private scientific design before mapping and verify the receipt in each submission."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify_manifest(path, expected):
    data = path.read_bytes()
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or digest(data) != expected:
        raise ValueError("Design manifest differs from the independently supplied SHA-256")
    names = set()
    base = path.parent.resolve()
    for line in data.decode().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            raise ValueError("Invalid SHA-256 manifest entry")
        checksum, name = match.groups()
        member = base / name
        if (Path(name).is_absolute() or name != Path(name).as_posix() or ".." in Path(name).parts
                or name in names or member.resolve() != member or member == path.resolve()):
            raise ValueError("Unsafe or repeated design member")
        if digest(member.read_bytes()) != checksum:
            raise ValueError(f"Design file changed: {name}")
        names.add(name)
    if not names:
        raise ValueError("The design manifest is empty")
    return len(names)


def create_receipt(path, receipt):
    # Publish the complete receipt once, even if two coordinators open the gate.
    with NamedTemporaryFile(dir=path.parent, delete=False) as saved:
        temp = Path(saved.name)
        try:
            saved.write((json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())
            saved.flush()
            os.fsync(saved.fileno())
            os.link(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["witness", "verify"])
    parser.add_argument("manifest", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--expected-sha256", required=True, help="digest received independently from the source reader")
    parser.add_argument("--context", action="append", nargs=2, default=[], metavar=("LABEL", "SHA256"), help="additional public pins frozen at registration")
    parser.add_argument("--submission", type=Path, action="append", default=[], help="copy of the original public receipt in a sealed submission")
    args = parser.parse_args()
    try:
        count = verify_manifest(args.manifest, args.expected_sha256)
        if args.mode == "witness":
            if args.submission:
                raise ValueError("Check mapper receipts in verify mode")
            pins = dict(args.context)
            if len(pins) != len(args.context) or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in pins.values()):
                raise ValueError("Context pins require distinct labels and SHA-256 digests")
            create_receipt(args.receipt, {
                "version": 1, "design_manifest_sha256": args.expected_sha256, "design_members": count,
                "witnessed_at_utc": datetime.now(timezone.utc).isoformat(), "context_sha256": pins,
            })
        else:
            data = args.receipt.read_bytes()
            receipt = json.loads(data)
            if receipt["version"] != 1 or receipt["design_manifest_sha256"] != args.expected_sha256 or receipt["design_members"] != count:
                raise ValueError("Receipt does not identify the frozen design")
            for label, value in args.context:
                if receipt["context_sha256"].get(label) != value:
                    raise ValueError(f"Different context pin: {label}")
            for submission in args.submission:
                if submission.read_bytes() != data:
                    raise ValueError(f"Submission carries a different study receipt: {submission}")
        print(f"{args.mode}: {count} verified design member(s), {len(args.submission)} submission receipt(s)")
    except (KeyError, OSError, ValueError, TypeError) as error:
        parser.exit(1, f"Study gate failed: {error}\n")


if __name__ == "__main__":
    main()
