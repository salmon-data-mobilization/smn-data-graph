#!/usr/bin/env python3
"""Blind, pool and score blind-loop claims.

blind: merge every mapper's claims for one case with the coordinator's planted
items, strip identity and probabilities, shuffle with a seed taken from the
inputs, and write the grader-facing items.json and fitness.json plus a
coordinator-only key.json that maps neutral IDs back to their sources.

score: read the keys, the graders' labels and pre-keys, and write metrics.
Agreement (Fleiss kappa, raw agreement, Gwet's AC1 and specific agreement on
'not true') is computed on natural items only. Planted items give each
grader's sensitivity and specificity and are never pooled with natural items.
Also: per-mapper precision, unsupported and overclaim rates and a Brier score
against the graders' majority; each grader's leniency toward its own family,
on contested items only; fitness grades collapsed to defensible or incorrect,
and each mapper's fitness choice against the graders' sealed pre-key
majority; and recall of each grader's pre-key facts. Two queues for people:
contested critical items plus a seeded audit sample of unanimous accepts, for
an assessment scientist; and the mappers' custodian questions, grouped by cell
and routed through a hand-kept authority table to the organisation that holds
the cell. With --sheets, score also writes the draft sheets.
Exit codes: 0 written, 2 missing or malformed input.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import re
import sys

VERDICTS = ("true", "false", "unsupported")
ITEM_FIELDS = ("statement", "kind", "evidence", "basis", "critical", "materiality")
USES = ("trend", "stock_recruit", "regional_sum")
DEFENSIBLE = {"correct": "defensible", "acceptable": "defensible", "defensible": "defensible", "incorrect": "incorrect"}
USABLE = {"fit": "usable", "fit_with_adjustment": "usable", "unfit": "unfit", "abstain": "abstain"}
AUDIT_PER_CASE = 3
# Candidates only: a person confirms each organisation in the authority table. Word boundaries keep
# "National Marine Fisheries Service" out.
INDIGENOUS = re.compile(r"\b(tribes?|tribal|nations?|indian|band|inter-?tribal|confederated|native|critfc|nwifc)\b", re.I)
ERRATA = re.compile(r"transpos|as printed|misprint|typo", re.I)


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


def agreement(rows: list[list[str]], cats=VERDICTS) -> dict:
    """Agreement on items every grader labelled: Fleiss kappa, raw pairwise agreement, Gwet's AC1 (stable when
    nearly every vote is 'true'), and specific agreement on 'not true': when one grader flags an item, how often
    another does too."""
    rows = [r for r in rows if len(r) >= 2 and len(r) == len(rows[0])]
    if not rows:
        return {"items": 0}
    n = len(rows[0])
    pairs = [(a, b) for a in range(n) for b in range(a + 1, n)]
    raw = sum(r[a] == r[b] for r in rows for a, b in pairs) / (len(rows) * len(pairs))
    share = Counter(x for r in rows for x in r)
    pe = sum(share[c] / (len(rows) * n) * (1 - share[c] / (len(rows) * n)) for c in cats) / (len(cats) - 1)
    both = sum(r[a] != "true" and r[b] != "true" for r in rows for a, b in pairs)
    one = sum((r[a] != "true") != (r[b] != "true") for r in rows for a, b in pairs)
    flags = [sum(v != "true" for v in r) for r in rows]
    return {"items": len(rows), "fleiss_kappa": fleiss(rows, cats), "raw_agreement": round(raw, 3),
            "ac1": round((raw - pe) / (1 - pe), 3) if pe < 1 else None,
            "specific_agreement_not_true": round(2 * both / (2 * both + one), 3) if both + one else None,
            "flagged_by_at_least": {str(k): sum(f >= k for f in flags) for k in range(1, n + 1)}}


def agency(publisher: str | None) -> str:
    """Fallback route when the authority table has no entry: the agency, without division or programme."""
    return (publisher or "").split(" (")[0].split(",")[0].strip() or "unknown"


def route(doc: dict, authority: dict) -> str:
    return authority.get("route_by_publisher", {}).get(doc.get("publisher")) or agency(doc.get("publisher"))


def holds(orgs, authority: dict) -> list[str]:
    """Organisations that put an item on hold: listed in the authority table, or a keyword candidate."""
    known = set(authority.get("indigenous_organisations", [])) | set(authority.get("includes_indigenous_members", []))
    return sorted({o for o in orgs if o in known or INDIGENOUS.search(o)})


def majority(labels: list[str]) -> str | None:
    top, n = Counter(labels).most_common(1)[0]
    return top if n * 2 > len(labels) else None


def rate(num: int, den: int) -> dict:
    return {"n": num, "of": den, "rate": round(num / den, 3) if den else None}


def mean(xs: list[float]) -> dict:
    return {"items": len(xs), "mean": round(sum(xs) / len(xs), 3) if xs else None}


def score(round_dir: Path, graders: dict[str, str], authority: dict | None = None) -> dict:
    authority = authority or {}
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
    rows, case_rows = [], defaultdict(list)
    planted = {g: Counter() for g in graders}
    by_mutation = defaultdict(Counter)
    mapper = defaultdict(Counter)
    brier = defaultdict(list)
    lean = defaultdict(lambda: defaultdict(list))
    queue, unanimous = [], defaultdict(list)
    manifests = {c: {d["doc_id"]: d for d in json.loads((round_dir / "packet" / c / "manifest.json").read_text())["documents"]}
                 for c in keys if (round_dir / "packet" / c / "manifest.json").exists()}
    items_by_case = {c: {i["item_id"]: i for i in json.loads((round_dir / "pool" / c / "items.json").read_text())["items"]}
                     for c in keys}
    for (case, iid), by_g in sorted(labels.items()):
        src = keys[case]["items"][iid]
        verdicts = [by_g[g]["verdict"] for g in graders if g in by_g]
        maj = majority(verdicts)
        if src["source"] == "planted":
            negative = src["truth"] != "true"  # false or unsupported
            for g, lab in by_g.items():
                caught = lab["verdict"] != "true"
                planted[g]["negative_items" if negative else "true_items"] += 1
                if negative:
                    planted[g]["negative_caught"] += caught
                    planted[g]["negative_exact"] += lab["verdict"] == src["truth"]
                    by_mutation[src.get("mutation") or "unstated"]["labels"] += 1
                    by_mutation[src.get("mutation") or "unstated"]["caught"] += caught
                else:
                    planted[g]["true_accepted"] += not caught
            continue
        if len(verdicts) == len(graders):
            rows.append(verdicts)
            case_rows[case].append(verdicts)
        m = src["model"]
        mapper[m]["items"] += 1
        mapper[m][f"majority_{maj or 'none'}"] += 1
        basis_votes = [by_g[g].get("basis_correct") for g in by_g if by_g[g].get("basis_correct") is not None]
        if basis_votes and majority([str(v) for v in basis_votes]) == "False":
            mapper[m]["overclaim"] += 1
        if isinstance(src.get("p"), (int, float)) and maj:
            brier[m].append((src["p"] - (1.0 if maj == "true" else 0.0)) ** 2)
        contested = len(set(verdicts)) > 1
        if contested:
            for g, lab in by_g.items():
                others = [by_g[o]["verdict"] == "true" for o in by_g if o != g]
                if others:
                    lean[g][family(m) == family(graders[g])].append((lab["verdict"] == "true") - sum(others) / len(others))
        item = items_by_case[case][iid]
        if not (item.get("critical") or any(by_g[g].get("critical") for g in by_g)):
            continue
        docs = [manifests.get(case, {}).get(e.get("doc_id"), {}) for e in item.get("evidence") or []]
        orgs = sorted({o for d in docs for o in d.get("collected_by") or []})
        entry = {"case_id": case, "item_id": iid, "statement": item["statement"],
                 "evidence": list(dict.fromkeys(f"{e.get('doc_id')} p.{e.get('page')}" for e in item.get("evidence") or [])),
                 "collected_by": orgs, "hold": holds(orgs, authority)}
        if contested or maj != "true":
            queue.append({**entry, "verdicts": {g: by_g[g]["verdict"] for g in by_g},
                          "notes": {g: by_g[g].get("note") for g in by_g}})
        else:
            unanimous[case].append(entry)
    audit = []
    for case, pool_ in sorted(unanimous.items()):
        rng = random.Random(int(hashlib.sha256(f"audit:{case}".encode()).hexdigest()[:16], 16))
        audit += rng.sample(pool_, min(AUDIT_PER_CASE, len(pool_)))
    out = {"graders": graders,
           "agreement_natural": agreement(rows),
           "agreement_natural_by_case": {c: agreement(r) for c, r in sorted(case_rows.items())},
           "planted": {g: {"sensitivity": rate(c["negative_caught"], c["negative_items"]),
                           "exact_on_negatives": rate(c["negative_exact"], c["negative_items"]),
                           "specificity": rate(c["true_accepted"], c["true_items"])}
                       for g, c in planted.items()},
           "planted_by_mutation": {m: rate(c["caught"], c["labels"]) for m, c in sorted(by_mutation.items())},
           "mappers": {m: {"items": c["items"],
                           "precision_majority_true": rate(c["majority_true"], c["items"]),
                           "majority_false": rate(c["majority_false"], c["items"]),
                           "majority_unsupported": rate(c["majority_unsupported"], c["items"]),
                           "no_majority": rate(c["majority_none"], c["items"]),
                           "overclaim": rate(c["overclaim"], c["items"]),
                           "brier": round(sum(brier[m]) / len(brier[m]), 3) if brier[m] else None}
                       for m, c in mapper.items()},
           "leniency_on_contested_items": {g: {"same_family": mean(v[True]), "other_family": mean(v[False])}
                                           for g, v in ((g, lean[g]) for g in graders)},
           "fitness": defaultdict(dict),
           "scientist_queue": queue,
           "audit_sample": audit}
    collapsed = []
    for (case, sid, use), by_g in sorted(fit_grades.items()):
        c = [DEFENSIBLE.get(v, v) for v in by_g.values()]
        collapsed.append(c)
        out["fitness"][f"{case}:{keys[case]['sets'][sid]}"][use] = {"grades": by_g, "majority": majority(c)}
    out["fitness_summary"] = {"decisions": len(collapsed),
                              "unanimous_defensible": sum(set(c) == {"defensible"} for c in collapsed),
                              "any_incorrect": sum("incorrect" in c for c in collapsed)}
    choice, splits = defaultdict(Counter), []
    for case in keys:
        pk = {g: json.loads(p.read_text())["fitness"] for g in graders
              if (p := round_dir / "grading" / g / f"{case}.prekey.json").exists()}
        fp = round_dir / "pool" / case / "fitness.json"
        sets = json.loads(fp.read_text())["sets"] if fp.exists() else []
        for use in USES:
            pks = {g: pk[g][use]["choice"] for g in pk if use in pk[g]}
            if not pks:
                continue
            exact, usable = majority(list(pks.values())), majority([USABLE.get(c, c) for c in pks.values()])
            if len(set(pks.values())) > 1:
                splits.append({"case_id": case, "use": use, "prekey_choices": pks})
            for s in sets:
                if use in s:
                    m, c = keys[case]["sets"][s["set_id"]], s[use].get("choice")
                    choice[m]["decisions"] += 1
                    choice[m]["exact"] += c == exact
                    choice[m]["usable"] += USABLE.get(c, c) == usable
    out["fitness_choice_vs_prekey_majority"] = {m: {"exact": rate(c["exact"], c["decisions"]),
                                                    "usable_or_unfit": rate(c["usable"], c["decisions"])}
                                                for m, c in choice.items()}
    out["prekey_fitness_splits"] = splits
    cells = defaultdict(lambda: {"questions": [], "asked_by": set()})
    for claims in sorted(round_dir.glob("mappers/*/*/claims.json")):
        case = claims.parent.name
        if case not in keys:
            continue
        for q in json.loads(claims.read_text()).get("custodian_questions", []):
            cell = cells[(case, q.get("doc_id"), q.get("page"))]
            cell["questions"].append({k: q.get(k) for k in ("question", "answer_type", "choices")})
            cell["asked_by"].add(claims.parent.parent.name)
    by_route = defaultdict(list)
    for (case, doc_id, page), cell in cells.items():
        doc = manifests.get(case, {}).get(doc_id, {})
        orgs = doc.get("collected_by") or []
        by_route[route(doc, authority)].append({
            "case_id": case, "doc_id": doc_id, "page": page, "title": doc.get("title"), "url": doc.get("url"),
            "collected_by": orgs, "hold": holds(orgs, authority), "asked_by": len(cell["asked_by"]),
            "errata": any(ERRATA.search(q["question"] or "") for q in cell["questions"]),
            "questions": cell["questions"]})
    out["custodian_questions_by_route"] = {r: sorted(v, key=lambda c: (not c["errata"], -c["asked_by"], c["case_id"],
                                                                       str(c["doc_id"]), c["page"] or 0))
                                           for r, v in sorted(by_route.items())}
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


def answer_lines(q: dict) -> list[str]:
    if q.get("answer_type") == "yes_no":
        return ["   ☐ Yes  ☐ No  ☐ Can't say"]
    if q.get("answer_type") == "choice" and q.get("choices"):
        return ["   " + "  ".join(f"☐ {c}" for c in q["choices"]) + "  ☐ Neither  ☐ Can't say"]
    return ["   Answer: ______________________"]


def sheets(scores: dict, round_dir: Path, out: Path, authority: dict | None = None, per_sheet: int = 8) -> list[Path]:
    """Write draft sheets: one per custodian route, from the mappers' custodian questions, and one for an
    assessment scientist, from the contested items and the audit sample. No AI verdict appears on any sheet."""
    authority = authority or {}
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for target, cells in scores["custodian_questions_by_route"].items():
        lines = [f"# Draft questions for {target}", "",
                 "**DRAFT, NOT SENT.** Sender: (named person). Reply by: (date).", "",
                 "We are compiling published salmon figures so that researchers use each one as its producers "
                 "intend. These questions are about cells in your published reports. Your answers will be recorded "
                 "as a dated note beside each cell, cited to you only if you tick the consent line.", ""]
        held = sorted({o for c in cells for o in c["hold"]})
        if held:
            rel = {o: authority.get("relationship", {}).get(o) or "none named" for o in held}
            lines += ["**Hold:** these figures were collected by or with "
                      + "; ".join(f"{o} (relationship: {r})" for o, r in rel.items())
                      + ". Send only through that relationship, and first ask whether and how the organisation "
                        "wants its figures and caveats represented.", ""]
        if not authority.get("route_by_publisher"):
            lines += ["**Route not confirmed:** no authority table was given, so this sheet is addressed to the "
                      "publisher's agency. A person must confirm who holds these cells.", ""]
        n = 0
        for i, c in enumerate(cells):
            if i == 0 and c["errata"]:
                lines += ["## Possible errors we noticed", ""]
            if not c["errata"] and (i == 0 or cells[i - 1]["errata"]):
                lines += ["## Questions", ""]
            if i == per_sheet:
                lines += ["## If you have time", ""]
            n += 1
            lines += [f"### {n}. {c['title'] or c['doc_id']}, PDF page {c['page']}", "",
                      f"Source: {c['url']}#page={c['page']}" if c["url"] else "Source: (no URL)",
                      f"Data collected by: {', '.join(c['collected_by']) or 'not stated'}", ""]
            for j, q in enumerate(c["questions"], 1):
                lines += [f"{j}. {q['question']}", *answer_lines(q)]
            lines += ["", "Does your answer apply to: ☐ this cell only  ☐ every year in this series  ☐ the method", ""]
        lines += ["## Anything else", "", "Is there anything else a user of these figures should know? "
                  "______________________", "", "☐ You may cite my name and role with these answers.", "",
                  "Name, role, date: ______________________", ""]
        path = out / f"custodian-{''.join(ch if ch.isalnum() else '-' for ch in target).strip('-').lower()}.md"
        path.write_text("\n".join(lines))
        written.append(path)
    items = scores["scientist_queue"] + scores["audit_sample"]
    random.Random(int(hashlib.sha256(json.dumps(sorted(i["item_id"] for i in items)).encode()).hexdigest()[:16],
                      16)).shuffle(items)
    lines = ["# Draft key sheet for an assessment scientist", "",
             "**DRAFT, NOT SENT.** Reviewer: (named person). Packet: (location).", "",
             "Work from the documents in the packet. Do Part 1 for a case before you read its Part 2. The statements "
             "in Part 2 come from AI readers, and some are wrong. You will not see how the AI graders judged them.", "",
             "## Part 1: your own decisions", "",
             "For each case, from the packet alone:", "",
             "- **trend, stock_recruit, regional_sum:** fit / fit with adjustment / unfit / abstain, the figure "
             "(document, PDF page, value) and the conditions. For stock_recruit, judge the figure as the spawner "
             "value S for its brood year, and note separately whether matching recruits can be assembled.",
             "- **Must-know facts:** up to five things a researcher must know before using this figure.", ""]
    lines += [f"- {case}" for case in sorted({i["case_id"] for i in items} | {s["case_id"] for s in scores.get(
        "prekey_fitness_splits", [])})]
    lines += ["", "## Part 2: statements to judge", ""]
    for case in sorted({i["case_id"] for i in items}):
        lines += [f"### {case}", ""]
        for it in (i for i in items if i["case_id"] == case):
            lines += [f"**{it['item_id']}.** {it['statement']}", "", f"Evidence cited: {'; '.join(it['evidence'])}", "",
                      "☐ True  ☐ False  ☐ Not established by the documents  ☐ Can't say", "",
                      "Note (document and page): ______________________", ""]
    path = out / "assessment-scientist.md"
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
    s.add_argument("--authority", type=Path, help="hand-kept authority table (routes, Indigenous organisations)")
    s.add_argument("--sheets", type=Path, help="also write the draft sheets here")
    a = p.parse_args(argv)
    try:
        if a.cmd == "blind":
            mappers = {m.split("=", 1)[0]: Path(m.split("=", 1)[1]) for m in a.mapper}
            blind(a.case, mappers, a.planted, a.round_dir / "pool" / a.case, a.round_dir / "coordinator/keys")
        else:
            graders = dict(g.split("=", 1) for g in a.grader)
            authority = json.loads(a.authority.read_text()) if a.authority else {}
            scores = json.loads(json.dumps(score(a.round_dir, graders, authority), default=dict))
            if a.sheets:
                sheets(scores, a.round_dir, a.sheets, authority)
            print(json.dumps(scores, indent=1, ensure_ascii=False))
    except (OSError, json.JSONDecodeError, KeyError) as e:
        print(f"input error: {e!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
