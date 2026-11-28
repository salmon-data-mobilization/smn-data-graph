#!/usr/bin/env python3
"""Seeded, stratified draw of blind-loop cases from a sealed sampling frame.

The seed is the first 16 hex digits of SHA-256(frame bytes + round label), so
anyone holding the frame file and the label can repeat the draw. Strata with
the fewest previously drawn cases are chosen first, ties broken by the seeded
generator. One case is then drawn uniformly from each chosen stratum, among
cases that share no document URL with any earlier draw or with another pick
in this draw, so that each draw adds an independent document cluster.
Exit codes: 0 drawn, 2 missing or malformed input, 3 not enough cases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import sys


def stratum(case: dict) -> str:
    if case.get("stratum"):
        return case["stratum"]
    return case["case_id"].split("-", 1)[0].upper()


def urls(case: dict) -> set[str]:
    return {d["url"] for d in case.get("documents", []) if d.get("url")}


def draw(frame_bytes: bytes, label: str, drawn: list[str], k: int) -> dict:
    cases = json.loads(frame_bytes)["cases"]
    digest = hashlib.sha256(frame_bytes + label.encode()).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    used = set().union(*(urls(c) for c in cases if c["case_id"] in drawn))
    by_id = {c["case_id"]: c for c in cases}
    pools: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for c in cases:
        s = stratum(c)
        counts.setdefault(s, 0)
        if c["case_id"] in drawn:
            counts[s] += 1
        elif not urls(c) & used:
            pools.setdefault(s, []).append(c["case_id"])
    open_strata = sorted(pools)
    rng.shuffle(open_strata)
    picks, chosen = [], []
    for s in sorted(open_strata, key=lambda s: counts[s]):
        free = sorted(i for i in pools[s] if not urls(by_id[i]) & used)
        if free and len(picks) < k:
            pick = rng.choice(free)
            picks.append(pick)
            chosen.append(s)
            used |= urls(by_id[pick])
    if len(picks) < k:
        raise ValueError(f"only {len(picks)} strata have an independent undrawn case; need {k}")
    return {
        "frame_sha256": hashlib.sha256(frame_bytes).hexdigest(),
        "round_label": label,
        "seed_hex": digest[:16],
        "previously_drawn": sorted(drawn),
        "drawn_per_stratum_before": dict(sorted(counts.items())),
        "chosen_strata": chosen,
        "drawn": picks,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("frame", type=Path)
    p.add_argument("--label", required=True, help="round label, e.g. crossmodel-r2")
    p.add_argument("--drawn", default="", help="comma-separated case IDs drawn in earlier rounds")
    p.add_argument("-k", type=int, default=3)
    a = p.parse_args(argv)
    try:
        frame_bytes = a.frame.read_bytes()
        result = draw(frame_bytes, a.label, [d for d in a.drawn.split(",") if d], a.k)
    except (OSError, json.JSONDecodeError, KeyError) as e:
        print(f"input error: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 3
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
