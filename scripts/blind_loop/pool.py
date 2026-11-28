#!/usr/bin/env python3
"""Blind, pool and score blind-loop claims.

blind: merge every mapper's claims for one case with the coordinator's planted
items, strip identity and probabilities, shuffle with a seed taken from the
inputs, and write the grader-facing items.json and fitness.json plus a
coordinator-only key.json that maps neutral IDs back to their sources.

score: read the keys, the graders' labels and pre-keys, and write metrics:
Fleiss kappa on item verdicts; each grader's sensitivity and specificity on
planted items; per-mapper precision, unsupported and overclaim rates and a
Brier score against the graders' majority; leniency of each grader toward
mappers of its own family; fitness grades; recall of each grader's pre-key
facts; and the queue of items that need a person, grouped by the publisher of
the cited document. Planted-item rates are reported apart from natural ones.
With --sheets, score also writes one short draft claim sheet per publisher,
holding any sheet that concerns data collected by an Indigenous organisation.
Exit codes: 0 written, 2 missing or malformed input.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import sys

VERDICTS = ("true", "false", "unsupported")
ITEM_FIELDS = ("statement", "kind", "evidence", "basis", "critical", "materiality")


def family(model: str) -> str:
    return model.split("/", 1)[0].replace("antigravity", "google")


def blind(case: str, mappers: dict[str, Path], planted: Path | None, out: Path, keydir: Path) -> None:
    raw = b"".join(p.read_bytes() for p in mappers.values()) + (planted.read_bytes() if planted else b"")
    rng = random.Random(int(hashlib.sha256(raw + case.encode()).hexdigest()[:16], 16))
    items, sets, key = [], [], {"case_id": case, "items": {}, "sets": {}}
    for model, path in mappers.items():
        sub = json.loads(path.read_text())
        figures = {f["figure_id"]: f for f in sub.get("figures", [])}
        for c in sub.get("claims", []):
            items.append(({f: c.get(f) for f in ITEM_FIELDS},
                          {"source": "mapper", "model": model, "claim_id": c.get("claim_id"), "p": c.get("p")}))
        fit = {}
        for use, v in sub.get("fitness", {}).items():
            v = dict(v)
            v["figures"] = [{k: figures[f].get(k) for k in ("doc_id", "page", "value", "unit", "quantity")}
                            for f in v.pop("figure_ids", []) if f in figures]
            v.pop("claim_ids", None)
            fit[use] = v
        sets.append((fit, model))
    for pl in json.loads(planted.read_text()) if planted else []:
        items.append(({f: pl.get(f) for f in ITEM_FIELDS},
                      {"source": "planted", "truth": pl["truth"], "mutation": pl.get("mutation")}))
    rng.shuffle(items)
    rng.shuffle(sets)
    ids = rng.sample(range(1000, 10000), len(items))
    pooled = []
    for n, (item, src) in zip(ids, items):
        iid = f"I{n}"
        pooled.append({"item_id": iid, **item})
        key["items"][iid] = src
    letters = "ABCDEFGH"
    anon = []
    for i, (fit, model) in enumerate(sets):
        anon.append({"set_id": f"V{letters[i]}", **fit})
        key["sets"][f"V{letters[i]}"] = model
    out.mkdir(parents=True, exist_ok=True)
    keydir.mkdir(parents=True, exist_ok=True)
    (out / "items.json").write_text(json.dumps({"case_id": case, "items": pooled}, indent=1, ensure_ascii=False))
    (out / "fitness.json").write_text(json.dumps({"case_id": case, "sets": anon}, indent=1, ensure_ascii=False))
    (keydir / f"{case}.key.json").write_text(json.dumps(key, indent=1))


def fleiss(rows: list[list[str]], cats=VERDICTS) -> float | None:
    rows = [r for r in rows if len(r) >= 2 and len(r) == len(rows[0])]
    if not rows:
        return None
    n = len(rows[0])
    p_j = Counter()
    P = 0.0
    for r in rows:
        c = Counter(r)
        p_j.update(c)
        P += (sum(v * v for v in c.values()) - n) / (n * (n - 1))
    P /= len(rows)
    total = len(rows) * n
    Pe = sum((p_j[k] / total) ** 2 for k in cats)
    return None if Pe == 1 else round((P - Pe) / (1 - Pe), 3)


def majority(labels: list[str]) -> str | None:
    top, n = Counter(labels).most_common(1)[0]
    return top if n * 2 > len(labels) else None


def rate(num: int, den: int) -> dict:
    return {"n": num, "of": den, "rate": round(num / den, 3) if den else None}


def score(round_dir: Path, graders: dict[str, str]) -> dict:
    keys = {json.loads(p.read_text())["case_id"]: json.loads(p.read_text())
            for p in sorted((round_dir / "coordinator/keys").glob("*.key.json"))}
    labels = defaultdict(dict)  # (case, item) -> grader -> label dict
    fit_grades = defaultdict(dict)
    for g in graders:
        for case in keys:
            p = round_dir / "grading" / g / f"{case}.labels.json"
            if not p.exists():
                continue
            lab = json.loads(p.read_text())
            for it in lab.get("items", []):
                labels[(case, it["item_id"])][g] = it
            for fg in lab.get("fitness", []):
                fit_grades[(case, fg["set_id"], fg["use"])][g] = fg["grade"]
    rows, per_case_rows = [], defaultdict(list)
    planted = {g: Counter() for g in graders}
    mapper = defaultdict(Counter)
    brier = defaultdict(list)
    lean = defaultdict(lambda: defaultdict(list))
    queue = []
    manifests = {c: {d["doc_id"]: d for d in json.loads((round_dir / "packet" / c / "manifest.json").read_text())["documents"]}
                 for c in keys if (round_dir / "packet" / c / "manifest.json").exists()}
    items_by_case = {c: {i["item_id"]: i for i in json.loads((round_dir / "pool" / c / "items.json").read_text())["items"]}
                     for c in keys}
    for (case, iid), by_g in sorted(labels.items()):
        src = keys[case]["items"][iid]
        verdicts = [by_g[g]["verdict"] for g in graders if g in by_g]
        if len(verdicts) == len(graders):
            rows.append(verdicts)
            per_case_rows[case].append(verdicts)
        maj = majority(verdicts)
        if src["source"] == "planted":
            for g, lab in by_g.items():
                caught = lab["verdict"] != "true"
                planted[g]["false_items" if src["truth"] == "false" else "true_items"] += 1
                if src["truth"] == "false" and caught:
                    planted[g]["false_caught"] += 1
                if src["truth"] == "true" and not caught:
                    planted[g]["true_accepted"] += 1
            continue
        m = src["model"]
        mapper[m]["items"] += 1
        mapper[m][f"majority_{maj or 'none'}"] += 1
        basis_votes = [by_g[g].get("basis_correct") for g in by_g if by_g[g].get("basis_correct") is not None]
        if basis_votes and majority([str(v) for v in basis_votes]) == "False":
            mapper[m]["overclaim"] += 1
        if isinstance(src.get("p"), (int, float)) and maj:
            brier[m].append((src["p"] - (1.0 if maj == "true" else 0.0)) ** 2)
        for g, lab in by_g.items():
            others = [by_g[o]["verdict"] == "true" for o in by_g if o != g]
            if others:
                lean[g][family(m) == family(graders[g])].append((lab["verdict"] == "true") - sum(others) / len(others))
        crit = bool(items_by_case[case][iid].get("critical")) or any(by_g[g].get("critical") for g in by_g)
        if crit and (len(set(verdicts)) > 1 or maj != "true"):
            ev = (items_by_case[case][iid].get("evidence") or [{}])[0]
            doc = manifests.get(case, {}).get(ev.get("doc_id"), {})
            queue.append({"case_id": case, "item_id": iid, "statement": items_by_case[case][iid]["statement"],
                          "doc_id": ev.get("doc_id"), "page": ev.get("page"), "publisher": doc.get("publisher"),
                          "collected_by": doc.get("collected_by"),
                          "verdicts": {g: by_g[g]["verdict"] for g in by_g},
                          "notes": {g: by_g[g].get("note") for g in by_g}})
    out = {"graders": graders,
           "fleiss_kappa_all": fleiss(rows),
           "fleiss_kappa_by_case": {c: fleiss(r) for c, r in per_case_rows.items()},
           "items_labelled_by_all": len(rows),
           "planted": {g: {"sensitivity": rate(c["false_caught"], c["false_items"]),
                           "specificity": rate(c["true_accepted"], c["true_items"])}
                       for g, c in planted.items()},
           "mappers": {m: {"items": c["items"],
                           "precision_majority_true": rate(c["majority_true"], c["items"]),
                           "majority_false": rate(c["majority_false"], c["items"]),
                           "majority_unsupported": rate(c["majority_unsupported"], c["items"]),
                           "no_majority": rate(c["majority_none"], c["items"]),
                           "overclaim": rate(c["overclaim"], c["items"]),
                           "brier": round(sum(brier[m]) / len(brier[m]), 3) if brier[m] else None}
                       for m, c in mapper.items()},
           "leniency_true_rate_minus_other_graders": {
               g: {"same_family": round(sum(v[True]) / len(v[True]), 3) if v[True] else None,
                   "other_family": round(sum(v[False]) / len(v[False]), 3) if v[False] else None}
               for g, v in lean.items()},
           "fitness": defaultdict(dict),
           "person_queue_by_publisher": defaultdict(list)}
    for (case, sid, use), by_g in sorted(fit_grades.items()):
        out["fitness"][f"{case}:{keys[case]['sets'][sid]}"][use] = {"grades": by_g, "majority": majority(list(by_g.values()))}
    for q in queue:
        out["person_queue_by_publisher"][q["publisher"] or "unknown"].append(q)
    recall = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for g in graders:
        for case in keys:
            p = round_dir / "grading" / g / f"{case}.labels.json"
            if not p.exists():
                continue
            for fact in json.loads(p.read_text()).get("prekey_matches", []):
                hit_models = {keys[case]["items"][i]["model"] for i in fact.get("item_ids", [])
                              if keys[case]["items"].get(i, {}).get("source") == "mapper"}
                for m in {s["model"] for s in keys[case]["items"].values() if s["source"] == "mapper"}:
                    recall[g][m][1] += 1
                    recall[g][m][0] += m in hit_models
    out["prekey_recall"] = {g: {m: rate(*v) for m, v in ms.items()} for g, ms in recall.items()}
    return out


INDIGENOUS = ("tribe", "tribal", "nation", "first nation", "indian", "band", "inter-tribal", "intertribal",
              "critfc", "nwifc", "lisims", "gitanyow", "gitksan", "confederated", "native")


def sheets(scores: dict, round_dir: Path, out: Path, per_sheet: int = 5) -> list[Path]:
    """Write one short draft claim sheet per publisher from the scored person queue."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    manifests = {}
    for publisher, queue in sorted(scores["person_queue_by_publisher"].items()):
        rows = sorted(queue, key=lambda q: (len(set(q["verdicts"].values())) == 1, q["case_id"]))[:per_sheet]
        lines = [f"# Draft questions for {publisher}", "",
                 "**DRAFT, NOT SENT.** Sender: (named person). Reply by: (date). "
                 "Your answers will be recorded as a dated, citable key next to the source cell; "
                 "tick the consent line if we may cite your name and role.", ""]
        relationship = False
        for n, q in enumerate(rows, 1):
            m = manifests.setdefault(q["case_id"], {d["doc_id"]: d for d in json.loads(
                (round_dir / "packet" / q["case_id"] / "manifest.json").read_text())["documents"]})
            doc = m.get(q["doc_id"], {})
            collected = ", ".join(doc.get("collected_by") or []) or "not stated"
            if any(k in collected.lower() for k in INDIGENOUS):
                relationship = True
            url = doc.get("url", "")
            lines += [f"## {n}. {doc.get('title', q['doc_id'])}, PDF page {q['page']}", "",
                      f"Source: {url}#page={q['page']}" if url else "Source: (no URL)",
                      f"Data collected by: {collected}", "",
                      f"> {q['statement']}", "",
                      "Is this statement correct as written?  ☐ Yes  ☐ No  ☐ Partly  ☐ Can't say", "",
                      "If no or partly, what is correct? ______________________", ""]
        if relationship:
            lines.insert(4, "**Hold:** at least one item concerns data collected by an Indigenous organisation. "
                            "Route through an existing relationship with that organisation, not as a cold request.\n")
        lines += ["☐ You may cite my name and role with these answers.", "",
                  "Name, role, date: ______________________", ""]
        path = out / f"{''.join(c if c.isalnum() else '-' for c in publisher).strip('-').lower()}.md"
        path.write_text("\n".join(lines))
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("blind")
    b.add_argument("round_dir", type=Path)
    b.add_argument("case")
    b.add_argument("--mapper", action="append", required=True, metavar="MODEL=PATH")
    b.add_argument("--planted", type=Path)
    s = sub.add_parser("score")
    s.add_argument("round_dir", type=Path)
    s.add_argument("--grader", action="append", required=True, metavar="LABEL=MODEL")
    s.add_argument("--sheets", type=Path, help="also write draft claim sheets, one per publisher, here")
    a = p.parse_args(argv)
    try:
        if a.cmd == "blind":
            mappers = {m.split("=", 1)[0]: Path(m.split("=", 1)[1]) for m in a.mapper}
            blind(a.case, mappers, a.planted, a.round_dir / "pool" / a.case, a.round_dir / "coordinator/keys")
        else:
            graders = dict(g.split("=", 1) for g in a.grader)
            scores = json.loads(json.dumps(score(a.round_dir, graders), default=dict))
            if a.sheets:
                sheets(scores, a.round_dir, a.sheets)
            print(json.dumps(scores, indent=1))
    except (OSError, json.JSONDecodeError, KeyError) as e:
        print(f"input error: {e!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
