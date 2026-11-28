#!/usr/bin/env python3
"""Blind, pool and score blind-loop claims.

blind: merge every mapper's claims for one case with the coordinator's planted
items, strip identity and probabilities, shuffle with a seed taken from the
inputs, and write the grader-facing items.json and fitness.json plus a
coordinator-only key.json that maps neutral IDs back to their sources.

score: read the keys, the graders' labels and pre-keys, and write metrics.
Agreement (Fleiss kappa, raw agreement, Gwet's AC1 and specific agreement on
'not true') is computed on natural items only. Planted items give each
grader's sensitivity on negatives (false or unsupported), exact labels and
specificity, also by mutation type, and are never pooled with natural items.
Per mapper: precision, unsupported and overclaim rates, majority verdict by
basis tag, and a Brier score and AUC of p against grader flags (descriptive:
they compare p with AI votes, not with truth). Also each grader's leniency
toward its own family, on contested items only; fitness grades collapsed to
defensible or incorrect; each mapper's fitness choice against the graders'
sealed pre-key majority; and recall of each grader's pre-key facts. Two
queues for people: contested critical items plus a seeded audit sample of
unanimous accepts, for an assessment scientist; and the mappers' custodian
questions, grouped by cell and routed through a hand-kept authority table to
whoever holds the cell.

With --sheets, score also writes draft sheets: one per custodian route, capped
at five questions, each with an internal cover note, and one per case for an
assessment scientist. A route whose data involve an Indigenous organisation
with no named relationship is written under held/. --edits applies a reviewed
list of drops, replacements and priorities to custodian questions.
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


def route(case: str, doc: dict, authority: dict) -> str:
    """Who holds a cell: the case's estimators if the table names them, else the publisher's route, else its agency."""
    return (authority.get("route_by_case", {}).get(case)
            or authority.get("route_by_publisher", {}).get(doc.get("publisher"))
            or agency(doc.get("publisher")))


def qid(case: str, text: str) -> str:
    """A stable ID for a custodian question, so that reviewed edits survive re-scoring."""
    return "Q" + hashlib.sha256(f"{case}|{text}".encode()).hexdigest()[:6]


def auc_low_p(pairs: list[tuple[float, bool]]) -> float | None:
    """Chance that a flagged item has a lower p than an unflagged one; ties count half."""
    pos, neg = [p for p, f in pairs if f], [p for p, f in pairs if not f]
    if not pos or not neg:
        return None
    return round(sum((a < b) + 0.5 * (a == b) for a in pos for b in neg) / (len(pos) * len(neg)), 3)


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
    p_flags = defaultdict(list)
    by_basis = defaultdict(Counter)
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
        item = items_by_case[case][iid]
        mapper[m]["items"] += 1
        mapper[m][f"majority_{maj or 'none'}"] += 1
        by_basis[m][f"{maj or 'none'}|{item.get('basis')}"] += 1
        basis_votes = [by_g[g].get("basis_correct") for g in by_g if by_g[g].get("basis_correct") is not None]
        if basis_votes and majority([str(v) for v in basis_votes]) == "False":
            mapper[m]["overclaim"] += 1
        contested = len(set(verdicts)) > 1
        if isinstance(src.get("p"), (int, float)):
            # an item with no majority counts as not true
            brier[m].append((src["p"] - (1.0 if maj == "true" else 0.0)) ** 2)
            p_flags[m].append((src["p"], any(v != "true" for v in verdicts)))
        if contested:
            for g, lab in by_g.items():
                others = [by_g[o]["verdict"] == "true" for o in by_g if o != g]
                if others:
                    lean[g][family(m) == family(graders[g])].append((lab["verdict"] == "true") - sum(others) / len(others))
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
                           "majority_by_basis": dict(sorted(by_basis[m].items())),
                           "brier": round(sum(brier[m]) / len(brier[m]), 3) if brier[m] else None,
                           "p_vs_any_flag": {"flagged": sum(f for _, f in p_flags[m]), "of": len(p_flags[m]),
                                             "auc_low_p": auc_low_p(p_flags[m])}}
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
            text = q.get("question") or ""
            cell = cells[(case, q.get("doc_id"), q.get("page"))]
            cell["questions"].append({"id": qid(case, text), "question": text, "answer_type": q.get("answer_type"),
                                      "choices": q.get("choices") or [], "errata": bool(ERRATA.search(text))})
            cell["asked_by"].add(claims.parent.parent.name)
    by_route = defaultdict(list)
    for (case, doc_id, page), cell in cells.items():
        doc = manifests.get(case, {}).get(doc_id, {})
        orgs = doc.get("collected_by") or []
        by_route[route(case, doc, authority)].append({
            "case_id": case, "doc_id": doc_id, "page": page, "title": doc.get("title"), "url": doc.get("url"),
            "publisher": doc.get("publisher"), "collected_by": orgs, "hold": holds(orgs, authority),
            "asked_by": len(cell["asked_by"]), "questions": cell["questions"]})
    out["custodian_questions_by_route"] = {r: sorted(v, key=lambda c: (c["case_id"], str(c["doc_id"]), c["page"] or 0))
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


SENDER = "(sender: name, role and organisation)"
INTRO = ("We are {sender}. We are compiling published salmon figures so that researchers use each one as its "
         "producers intend. AI readers drafted these questions from the reports that publish these figures, and a "
         "person checked them before sending. Each question is about a specific table cell or passage, with its page. "
         "Answer only what you can: \"Can't say\" is a useful answer.\n\n"
         "We will keep your answers as dated notes beside each cell, attributed to your organisation. We will name "
         "you only if you tick the consent box. We will send you the notes we keep for these cells.")
DECISIONS = ["Who sends this, from which organisation, and by when a reply is wanted.",
             "Whether an answer given without consent may be kept under the organisation's name, as the sheet says.",
             "What the recipient gets back. The sheet promises the notes kept for these cells.",
             "Whether to offer payment or acknowledgement."]
CAP = 5


def answer_lines(q: dict) -> list[str]:
    if q.get("answer_type") == "yes_no":
        return ["   ☐ Yes  ☐ No  ☐ Can't say", "   If no: ______________________"]
    if q.get("answer_type") == "choice" and q.get("choices"):
        extra = [] if any(re.search(r"\b(neither|other)\b", c, re.I) for c in q["choices"]) else ["Neither"]
        return ["   " + "  ".join(f"☐ {c}" for c in [*q["choices"], *extra, "Can't say"])]
    return ["   Answer: ______________________"]


def slug(text: str) -> str:
    return re.sub(r"-+", "-", "".join(ch if ch.isalnum() else "-" for ch in text)).strip("-").lower()[:80]


def custodian_sheet(target: str, cells: list[dict], authority: dict, edits: dict) -> tuple[str, str, bool]:
    """One route's sheet and its internal cover note. Returns (sheet, cover, held)."""
    ranked, dropped = [], []
    for ci, c in enumerate(cells):
        for q in c["questions"]:
            e = edits.get(q["id"], {})
            if e.get("action") == "drop":
                dropped.append((q, e))
                continue
            if e.get("action") == "replace":
                q = {**q, **{k: e[k] for k in ("question", "answer_type", "choices", "errata") if k in e}}
            default = 0 if q["errata"] else 1 if c["asked_by"] > 1 else 3 if e.get("action") == "optional" else 2
            ranked.append((e.get("priority", default), ci, q, e))
    ranked.sort(key=lambda t: (t[0], t[1]))
    kept, later = ranked[:CAP], ranked[CAP:]
    lines = [f"# Questions for {target}", "", "**DRAFT, NOT SENT.**", "", INTRO.format(sender=SENDER), "",
             "## First, in your own words", "",
             "Is there anything a user of these figures should know about them? ______________________", ""]
    n = 0
    for title, errata in (("Possible errors we noticed", True), ("Questions", False)):
        part = [t for t in kept if t[2]["errata"] == errata]
        if part:
            lines += [f"## {title}", ""]
        for ci in dict.fromkeys(t[1] for t in part):
            c = cells[ci]
            n += 1
            lines += [f"### {n}. {c['title'] or c['doc_id']}, PDF page {c['page']}", "",
                      f"Source: {c['url']}#page={c['page']}" if c["url"] else "Source: (no URL)",
                      f"Data collected by: {', '.join(c['collected_by']) or 'not stated'}", ""]
            for j, (_, _, q, e) in enumerate((t for t in part if t[1] == ci), 1):
                lines += [f"{j}. {q['question']}{' (optional)' if e.get('action') == 'optional' else ''}",
                          *answer_lines(q)]
            lines += ["", "Does your answer apply to: ☐ this cell only  ☐ every year in this series  ☐ the method", ""]
    lines += ["## Consent", "", "☐ You may name me, with my role, beside these answers.", "",
              "Name, role, organisation, date: ______________________", ""]
    held_orgs = sorted({o for c in cells for o in c["hold"]})
    rel = {o: authority.get("relationship", {}).get(o) for o in held_orgs}
    held = any(not r for r in rel.values())
    cover = [f"# Cover note for {target}", "", "Internal. Not for the recipient. **Do not send** until Brett approves "
             "the recipient and the wording.", ""]
    if held_orgs:
        cover += ["## Hold", "", "These figures were collected by or with:", "",
                  *[f"- {o}: relationship {r or '**none named**'}" for o, r in rel.items()], "",
                  "Send only through an existing relationship with each organisation, and first ask whether and how "
                  "it wants its figures and caveats represented." + (" This sheet is held until a person names each "
                                                                      "relationship in the authority table." if held else ""), ""]
    cover += ["## Decisions for Brett", "", *[f"- {d}" for d in DECISIONS],
              f"- Confirm the route ({target}) in data/intake/authority.json.", "",
              f"## Questions: {len(kept)} on the sheet, {len(later)} held back for a follow-up, {len(dropped)} dropped", ""]
    cover += [f"- Held back: {q['id']} {q['question']}" for _, _, q, _ in later]
    cover += [f"- Dropped: {q['id']} {q['question']} ({e.get('reason')}; {e.get('by')})" for q, e in dropped]
    cover += [f"- Edited ({e['action']}): {q['id']} ({e.get('reason')}; {e.get('by')})" for _, _, q, e in ranked
              if e.get("action") in ("replace", "optional") or "priority" in e]
    return "\n".join(lines), "\n".join(cover + [""]), held


SCIENTIST_INTRO = ("We are {sender}. We are testing whether AI readers can tell a researcher which published salmon "
                   "figure is fit for which use. Your judgements become the reference that the AI readers are scored "
                   "against. This sheet covers one case. With the documents listed below, it should take about two to "
                   "four hours.")


def scientist_sheet(case: str, items: list[dict], round_dir: Path) -> str:
    entry_p, man_p = round_dir / "cases" / case / "frame-entry.json", round_dir / "packet" / case / "manifest.json"
    entry = json.loads(entry_p.read_text()) if entry_p.exists() else {}
    docs = json.loads(man_p.read_text())["documents"] if man_p.exists() else []
    lines = [f"# Key sheet for an assessment scientist: {entry.get('stock', case)}, {entry.get('return_year', '')}", "",
             "**DRAFT, NOT SENT.**", "", SCIENTIST_INTRO.format(sender=SENDER), "", "## The case", "",
             f"{entry.get('stock', case)} ({entry.get('species', '')}), return year {entry.get('return_year', '')}, "
             f"{entry.get('jurisdiction', '')}. A researcher wants to use published spawning abundance for this stock "
             "and year in a multi-stock analysis. The starting documents are:", "",
             *[f"- {d.get('title')} ({d.get('publisher')}, {d.get('year')}): {d.get('locator', '')}"
               for d in entry.get("documents", [])], "", "## The documents", "",
             "Work from these documents only. Part 2 refers to them by ID and PDF page.", "",
             *[f"- **{d['doc_id']}** {d.get('title')} ({d.get('publisher')}, {d.get('year') or 'n.d.'}). "
               f"{d.get('url') or ''}" for d in docs], "", "## Part 1: your own decisions, before you read Part 2", "",
             "For each use, give fit / fit with adjustment / unfit / abstain, the figure (document, PDF page, value) and "
             "the conditions:", "", "- **trend** across years;",
             "- **stock_recruit:** judge the figure as the spawner value S for its brood year. Say separately whether "
             "matching recruits can be assembled, and what is missing (harvest, age allocation, cohort coverage);",
             "- **regional_sum** with neighbouring stocks.", "",
             "Then list up to five things a researcher must know before using this figure.", "",
             "## Part 2: statements to judge", "",
             "AI readers wrote these statements, and some are wrong. You will not see how the AI graders judged them.", ""]
    for it in items:
        lines += [f"**{it['item_id']}.** {it['statement']}", "", f"Evidence cited: {'; '.join(it['evidence'])}", "",
                  "☐ True  ☐ False  ☐ Partly (which part?)  ☐ Not established by the documents  ☐ Can't say", "",
                  "Note, with document and page: ______________________", ""]
    return "\n".join(lines)


def sheets(scores: dict, round_dir: Path, out: Path, authority: dict | None = None,
           edits: dict | None = None) -> list[Path]:
    """Write the draft sheets for people. No AI verdict appears on any of them. A held route goes under held/."""
    authority, edits = authority or {}, {e["id"]: e for e in (edits or {}).get("edits", [])}
    written = []
    for target, cells in scores["custodian_questions_by_route"].items():
        sheet, cover, held = custodian_sheet(target, cells, authority, edits)
        folder = out / "held" if held else out
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in ((f"custodian-{slug(target)}.md", sheet), (f"custodian-{slug(target)}.cover.md", cover)):
            (folder / name).write_text(text)
            written.append(folder / name)
    items = scores["scientist_queue"] + scores["audit_sample"]
    cover = ["# Cover note for the assessment-scientist sheets", "",
             "Internal. Not for the recipient. **Do not send** until Brett approves the recipient.", "",
             "## Decisions for Brett", "", "- Who sends these, and to whom: one case per scientist, matched by region.",
             "- Whether to offer payment or acknowledgement for two to four hours of work.",
             "- How the scientist receives the documents (the frozen packet folder for the case).", "",
             "## Items per case (internal: the scientist must not see which are contested)", ""]
    out.mkdir(parents=True, exist_ok=True)
    for case in sorted({i["case_id"] for i in items}):
        mine = [i for i in items if i["case_id"] == case]
        random.Random(int(hashlib.sha256(f"sheet:{case}".encode()).hexdigest()[:16], 16)).shuffle(mine)
        path = out / f"assessment-scientist-{case}.md"
        path.write_text(scientist_sheet(case, mine, round_dir))
        written.append(path)
        flagged = {i["item_id"] for i in scores["scientist_queue"]}
        cover += [f"- {case}: {sum(i['item_id'] in flagged for i in mine)} flagged by a grader, "
                  f"{sum(i['item_id'] not in flagged for i in mine)} drawn from unanimous accepts"]
    (out / "assessment-scientist.cover.md").write_text("\n".join(cover + [""]))
    written.append(out / "assessment-scientist.cover.md")
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
    s.add_argument("--edits", type=Path, help="reviewed edits to custodian questions (drop, replace, optional, priority)")
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
                edits = json.loads(a.edits.read_text()) if a.edits else None
                sheets(scores, a.round_dir, a.sheets, authority, edits)
            print(json.dumps(scores, indent=1, ensure_ascii=False))
    except (OSError, json.JSONDecodeError, KeyError) as e:
        print(f"input error: {e!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
