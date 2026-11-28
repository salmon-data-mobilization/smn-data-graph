# Blind loop protocol, v2.2 (2026-11-27)

This protocol tests whether AI agents can read published salmon figures and tell a researcher which figure is fit for which use, with evidence. Integrating those figures naively produces wrong numbers. They come in competing editions, and they differ in how they treat jacks, effective females, origin, gross and net, expansions and overlapping aggregates.

A second or third AI model is a robustness check. It is not scientific sign-off. Only data custodians and assessment scientists can confirm a critical claim.

Histories:
- v1 was a single-model loop run in Codex, recorded in `data/intake/*-202611{26,27}`.
- v2 round 1 is in `data/intake/crossmodel-blind-20261127/`.
- v2.1 round 2 is in `data/intake/crossmodel-r2-20261127/`.
- The reviews behind each version are in `data/intake/loop-reviews/`.

These folders are local and are not in git.

## 1. Why the design is what it is

| Weakness found | Rule |
|---|---|
| **v1:** mapper and grader were the same model and shared blind spots | Mappers and graders come from at least two families, and at least one grader comes from a family that did not map |
| **v1:** the coordinator picked each case to show a known contrast | Cases are drawn at random from a sealed sampling frame. The frame is stratified by jurisdiction and never reuses a document cluster |
| **v1:** the protocol hinted at the answer | Every case uses the same generic question, written by `draw.py --cases`. The scout's reported values are never shown |
| **v1:** checker code was written before the mapper sealed; repairs were graded on the same case | No case-specific checkers. First-pass results are final. A repair is scored only on new cases |
| **v2r1:** holistic R1–R8 grades agreed at chance (κ = 0.12) | Graders label atomic claims as true, false or unsupported, and check the basis tag |
| **v2r1:** graders could identify mappers | Claims from all mappers and planted items are pooled and shuffled, with identity and probabilities removed |
| **v2r1:** retrieval was mixed up with reading | Two librarians from different families build one frozen packet. Mappers read only the packet |
| **v2r1:** no ground truth | Planted items measure grader sensitivity and specificity. A known-answer bank comes next |
| **v2r1:** the coordinator's hand-written claim sheets anchored respondents | Sheets for people are generated, show no AI verdict, and any edit to them is recorded with who proposed it |
| **v2r1:** Indigenous data authorities were invisible | The packet records `collected_by` and `rights`. Questions about data collected by Indigenous organisations go only through an existing relationship |
| **v2r2:** the headline κ pooled planted with natural items | The scorer computes agreement on natural items only |
| **v2r2:** every planted false item could be refuted from its own page, and plants were shorter than real items | Plants are near misses that need page context or a second document. Their lengths follow the distribution of natural items. A verifier from another family checks every label |
| **v2r2:** graders split on whether an inference counts as true (specific agreement on "not true" 0.39) | Graders judge the whole item: false if the packet contradicts a substantive clause, otherwise unsupported if a substantive clause is not established. A warranted inference from packet evidence can be true |
| **v2r2:** stock_recruit was ambiguous, and fitness grades agreed at chance | stock_recruit judges the spawner value S, with the recruit status and any missing harvest, age allocation or cohort coverage stated. Grades are defensible or incorrect |
| **v2r2:** sheets asked custodians to endorse AI inferences, and routed by the first document's publisher | Custodian sheets come from the mappers' factual questions, at most five per sheet. They are routed through a hand-kept authority table, by case where the table says so, with a series-level answer option. A separate sheet, one case each, goes to an assessment scientist |

## 2. Roles

- **Coordinator** (not blind): seals, draws, freezes packets, pools and scores. Writes no answers, keys or plants.
- **Frame scout:** lists every eligible case against fixed criteria, without screening for interest, and records reported values. Those values are never shown to any role.
- **Librarians** (two, from different families): find and download documents. They don't interpret them.
- **Mappers** (two or more families): write atomic claims and three fitness decisions per case from the packet alone.
- **Plant author** (neither a mapper nor a grader): writes the planted items from the packet, without seeing any mapper output.
- **Plant verifier** (a family other than the author's; neither a mapper nor a grader): tries to overturn every plant's label before pooling.
- **Graders** (three, one per family): first a sealed pre-key, then blind labels on the pooled items.
- **People:**
  - *custodians* answer factual questions about their cells;
  - an *assessment scientist* records their own decisions on one case, then judges the flagged items and a random sample of unanimous accepts.

  Their answers become the human keys, which are what judge mappers and graders.

## 3. Procedure for one round

1. Seal the design, briefs, predictions and tools.
2. Draw with `draw.py --cases`, then seal the draw and the case files.
3. Run the librarians. Freeze each packet with `packet.py`, then seal.
4. Run the mappers, the graders' pre-keys and the plant author in parallel. Seal each when it finishes.
5. Run the plant verifier. The coordinator drops any plant whose label the verifier overturns, fixes quotes that are not exact, and records each change. Then seal the plants.
6. Pool with `pool.py blind`, then seal.
7. Run grader phase 2 and seal the labels.
8. Run `pool.py score --authority … --edits … --sheets …` and `check_citations.py`. Write the report.
9. Reviewers from at least two families, one of which did not coordinate, review the round. The coordinator writes the retrospective (§5).

## 4. Measures

All rates are counts with denominators.

**Graders**, on natural items only:
- Fleiss κ, raw agreement, Gwet's AC1, and specific agreement on "not true". AI labels count as a provisional reference only when κ ≥ 0.75.
- Leniency toward their own family, on contested items only. It is "not estimable" when there are none.

**Graders, on planted items** (reported apart):
- caught negatives (false or unsupported, not labelled true), exact labels on negatives, and true items accepted, by grader and by mutation type;
- falling below the ceiling is an expected diagnostic, not evidence of better grading.

**Mappers:**
- precision against the graders' majority;
- false and unsupported counts, and overclaims (basis tag judged wrong);
- majority verdict by basis tag. Descriptive only: *hypotheses* are unsupported items tagged inferred; *overreach* is unsupported or false items tagged printed or computed;
- the Brier score of p and the AUC of p against grader flags, with the flag count. Descriptive only, because they compare p with AI votes, not with the truth;
- recall of the graders' pre-key facts;
- fitness choice against the sealed pre-key majority, exact and as usable or unfit;
- fitness grades. When a scale or definition changes, report the old and new versions on the same sealed cases. Report decisions under a new definition separately, never by collapsing the old grades. Unanimity is a reliability diagnostic only;
- scripted quote and value checks.

**Other:**
- discovery by each librarian;
- tokens and wall time per role, including the coordinator's;
- once human keys exist, agreement of mappers and graders with those keys. Only that agreement counts as accuracy.

Report intervals only once there are 20 or more independent document clusters. Planted and known-answer rates are never pooled with natural rates.

## 5. Retrospective procedure

1. One page, written within a day, from the scored outputs only. The coordinator seals a draft before reading any review.
2. Check the preregistered predictions.
3. Propose at most two changes. Each must name:
   - its evidence: a human key, a known-answer result, a planted-item result, or a reliability failure under rule 8. Grader preference never counts;
   - the metric it should move, and in which direction;
   - its cost.
4. One in, one out: each new field, tool or criterion replaces an existing one. Keep at most five generic tools and no stock-specific checkers.
5. Delete anything that has not contributed to a confirmed finding in two rounds. Until human keys exist, "contributed" means changed a reported number, a routing decision or a person-queue item.
6. A reviewer from a family that did not coordinate the round signs the page.
7. Keep the mapper brief to about one page.
8. A reliability failure on sealed outputs may justify repairing a measurement: clarifying a definition, or removing a measure. A reliability failure means κ below 0.40, specific agreement on "not true" below 0.50, or a measure at its ceiling or floor. The repair needs a bridge: the old and new versions reported on the same sealed cases. It never justifies:
   - adding a measure;
   - relaxing a threshold;
   - choosing a preferred figure;
   - dropping a strict grader;
   - claiming an accuracy or biological-correctness gain.
9. No change may be justified by a rise in majority precision or κ alone. Precision is always reported with recall and the hypothesis count. Model recall is not completeness.
10. Sheets for people are judged by the people who answer them: response, time taken and objections to wording. Rule 3's evidence types do not apply to them. This exemption covers sheet wording, routing and answer format only. It does not exempt changes to evaluation sampling, key eligibility or scoring from rules 3 and 4. No sheet reaches anyone until Brett approves the recipient.

Rules 8–10 were accepted, with the amendments above, by the round 2 signer (openai/gpt-6.2-sol).

## 6. Tools

`scripts/blind_loop/`:
- `draw.py`: the draw and the case files;
- `packet.py`;
- `pool.py`: `blind`, and `score` with `--authority`, `--edits` and `--sheets`;
- `check_citations.py`.

Tests are in `tests/test_blind_loop.py`. The authority table, `data/intake/authority.json`, is kept by a person. Each round's edits to custodian questions are in its `coordinator/sheet-edits.json`.

## 7. Graduation gate for the IYS High Seas Expeditions graph (proposed; Brett decides)

The project intends to apply this method to a data graph for the International Year of the Salmon High Seas Expeditions (2019, 2020 and 2022), aimed at the program's main hypotheses. It moves there when, against human keys on at least 20 independent document clusters:

- **Mappers:**
  - precision on critical claims is at least 0.95, with a one-sided 95% lower bound of at least 0.90;
  - recall of the assessment scientist's must-know facts is at least 0.85;
  - no decision-changing error goes unflagged. This is tested on blinded, analyst-keyed outputs (an assembled trend series, a brood pairing and a regional subtotal), not inferred from item accuracy.
- **Graders:**
  - the majority agrees with the keys on at least 0.85 of items;
  - sensitivity on realistic plants is at least 0.80;
  - at least 0.90 of the items the humans judged false or unfit were flagged or queued.
- **Providers:**
  - custodians from at least three organisations have answered;
  - median time per sheet is 15 minutes or less;
  - no objection to wording is unresolved.

  Indigenous organisations take part only through their own processes, and the gate sets no response quota for them.

Then a keyed IYS pilot, across all three expedition years and the main data types, must reproduce at least two hypothesis-facing results within tolerances set by an analyst.

**What transfers:**
- frozen packets and seals;
- atomic claims with exact locators;
- scripted quote and value checks;
- edition handling;
- holds;
- the split between custodian and scientist routing.

**What does not transfer:** stock-year framing and the three escapement uses. Expedition data turn on:
- cruise, station, event and specimen keys;
- standardising gear, effort and catchability;
- subsampling expansions;
- genetic stock identification baselines and probabilistic assignments;
- oceanographic and plankton joins.

The CARE principles still apply, because genetic stock identification assigns fish to the rivers of Indigenous nations.
