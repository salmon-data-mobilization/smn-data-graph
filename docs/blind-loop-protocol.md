# Blind loop protocol, v2.1 (2026-11-27)

This protocol tests whether AI agents can read published salmon figures and tell a researcher which figure is fit for which use, with evidence. Integrating those figures naively produces wrong numbers. They come in competing editions, and they differ in how they treat jacks, effective females, origin, gross and net, expansions and overlapping aggregates.

A second or third AI model is a robustness check. It is not scientific sign-off. Only data custodians and assessment scientists can confirm a critical claim.

Histories:
- v1 was a single-model loop run in Codex, recorded in `data/intake/*-202611{26,27}`.
- v2 round 1 is in `data/intake/crossmodel-blind-20261127/`.
- The reviews behind this version are in `data/intake/loop-reviews/`. These folders are local and are not in git.

## 1. Why the design is what it is

| Weakness found | Rule |
|---|---|
| **v1:** mapper and grader were the same model and shared blind spots | Mappers and graders come from at least two families, and at least one grader comes from a family that did not map |
| **v1:** the coordinator picked each case to show a known contrast | Cases are drawn at random from a sealed sampling frame. The frame is stratified by jurisdiction and never reuses a document cluster |
| **v1:** the protocol hinted at the answer | Every case uses the same generic question |
| **v1:** checker code was written before the mapper sealed; repairs were graded on the same case | No case-specific checkers. First-pass results are final. A repair is scored only on new cases |
| **v2r1:** holistic R1–R8 grades agreed at chance (κ = 0.12) | Graders label atomic claims as true, false or unsupported, and check the basis tag. Fitness decisions are graded as anonymous sets |
| **v2r1:** graders could identify mappers. The Anthropic grader gave the Anthropic mapper 0.98, against 0.69 from the OpenAI grader | Claims from all mappers and planted items are pooled and shuffled, with identity and probabilities removed |
| **v2r1:** retrieval was mixed up with reading. Mappers shared only a third of their documents, and one used 9 times the tokens of the other | Two librarians from different families build one frozen packet. Mappers read only the packet |
| **v2r1:** no ground truth, and graders were only compared with each other | Planted items (true, and false of known mutation types) measure grader sensitivity and specificity. A known-answer bank comes next |
| **v2r1:** confidence labels were degenerate, and overclaiming went unscored | Each claim carries a probability p (scored by Brier) and a basis tag: printed, computed or inferred |
| **v2r1:** the coordinator's hand-written claim sheets anchored respondents and introduced errors | Person-queue items are generated from stable IDs and routed by the publisher of the cell. Questions are factual and forced-choice. Fitness questions go to an assessment scientist, not the custodian |
| **v2r1:** Indigenous data authorities were invisible | The packet records `collected_by` and `rights`. Questions about data collected by Indigenous organisations go through an existing relationship, never a cold sheet |

## 2. Roles

- **Coordinator** (not blind): seals the protocol, runs the draw, freezes the packets, writes the planted items, pools and scores. Writes no answers and no keys.
- **Frame scout:** lists every eligible case against fixed criteria, without screening for interest, and records reported values.
- **Librarians** (two, from different families): find and download documents. They don't interpret them.
- **Mappers** (two or more families): write atomic claims and three fitness decisions per case from the packet alone.
- **Graders** (three, one per family): first a sealed pre-key, then blind labels on the pooled items.
- **Person** (custodian or assessment scientist): answers routed questions. Their answers become human keys, which are what judge mappers and graders.

## 3. Procedure for one round

1. Seal the design, briefs and tools.
2. Seal the frame. Draw with `scripts/blind_loop/draw.py`.
3. Run the librarians. Freeze each packet with `scripts/blind_loop/packet.py`, then seal.
4. Run the mappers and the graders' pre-keys in parallel. Seal each when it finishes.
5. Write and seal the planted items. Pool with `scripts/blind_loop/pool.py blind`, then seal.
6. Run grader phase 2 and seal the labels.
7. Run `pool.py score` and `scripts/blind_loop/check_citations.py`. Write the report and the person queue.
8. Retrospective (§5).

## 4. Measures

**Graders**
- Fleiss κ on item verdicts, overall and by case. AI labels count as a provisional reference only when κ ≥ 0.75.
- Sensitivity and specificity on planted items.
- Leniency toward their own family: true-rate relative to the other graders, same family against other family.

**Mappers**
- Precision against the graders' majority.
- False, unsupported and overclaim rates.
- Brier score of p.
- Recall of the graders' pre-key facts.
- Fitness grades.
- Scripted quote and value checks.

**Other**
- Discovery by each librarian.
- Tokens and wall time per role.
- Once human keys exist: agreement of mappers and graders with those keys. Only that agreement counts as accuracy.

Report rates as counts with denominators. Report intervals only once enough independent document clusters have accumulated (at least 20). Planted and known-answer rates are never pooled with natural rates.

## 5. Retrospective procedure (from round 3)

1. One page, written within a day, from the scored outputs only.
2. Check the preregistered predictions.
3. Propose at most two changes. Each must name its evidence (a human key, a known-answer result or a planted-item result, never grader preference), the metric it should move and in which direction, and its cost.
4. One in, one out: each new field, tool or criterion replaces an existing one. Keep at most five generic tools and no stock-specific checkers.
5. Delete anything that has not contributed to a confirmed finding in two rounds.
6. A reviewer from a family that did not coordinate the round signs the page.
7. Keep the mapper brief to about one page.

Round 2 (v2.1) is a declared exception. It is a redesign, because the v2r1 measures could not detect change.

## 6. Tools

`scripts/blind_loop/`:
- `draw.py`
- `packet.py`
- `pool.py` (`blind` and `score`)
- `check_citations.py`

Tests are in `tests/test_blind_loop.py`.
