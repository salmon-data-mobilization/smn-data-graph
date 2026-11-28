# Blind loop protocol, v2.3 (2026-11-27)

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
| **v2r3:** planted sensitivity and the fitness choice were at their ceiling for a second round | Plants become an operational check with positive controls. Fitness becomes a stated estimate (estimand, value, units, cited inputs, a scriptable adjustment, or a bound), which graders compute on their own in the pre-key |
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

  Their answers are attached to graph nodes as context. No step waits for them, and they are not an answer key (v2.3).

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
- the outside-reference tests of section 7. Agreement between models is never reported as accuracy.

Report intervals only once there are 20 or more independent document clusters. Planted and known-answer rates are never pooled with natural rates.

## 5. Retrospective procedure

1. One page, written within a day, from the scored outputs only. The coordinator seals a draft before reading any review.
2. Check the preregistered predictions.
3. Propose at most two changes. Each must name:
   - its evidence: an outside-reference result (section 7), a known-answer result, a planted-item result, or a reliability failure under rule 8. Grader preference never counts;
   - the metric it should move, and in which direction;
   - its cost.
4. One in, one out: each new field, tool or criterion replaces an existing one. Keep at most five generic tools and no stock-specific checkers.
5. Delete anything that has not contributed to a confirmed finding in two rounds. "Contributed" means changed a reported number, a routing decision or a person-queue item.
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

## 7. Graduation gate: outside references, no human key (v2.3)

Brett set the design principle on 2026-11-27: no human in the loop and no human answer key. People are fallible too, and the loop exists to gather evidence that sits outside anyone's memory. This gate replaces the human-key gate of v2.2. It was reviewed in round 3 by openai/gpt-6.2-sol (signed with amendments) and google-gemini-4-carbon, and their amendments are applied.

### Principle

Agreement between models cannot find an error that every model shares, for example a wrong figure that every source repeats. So each test below uses a reference that comes from outside the models but needs no person in the loop: planted mutations, published results, later revisions, raw data and arithmetic.

### Tests

| ID | Test | Reference | Pass |
|---|---|---|---|
| G1 | Plant check (operational, not a graduation criterion) | Verified negative plants and verified true plants (positive controls) | Any miss marks the grader broken; specificity is reported with sensitivity |
| G2 | Reproduce published results | Derived results that the sources publish (totals, trends, CPUE, stock proportions). The targets and their duplicates are sealed away from the mappers, and scripts recompute them from versioned raw records | ≥ 0.80 reproduced within a tolerance based on rounding or on the effect on decisions, or the difference explained with a citation. Cited discrepancies are counted separately. 0 silent mismatches. Matching a publication can reproduce its error |
| G3 | Hidden revisions | Documents from before a known erratum, revision or supersession, with the later document withheld, plus matched controls that were never revised. Revisions with no earlier warning sign are excluded | ≥ 0.70 of the later-corrected issues flagged as contested, superseded or unfit, with the false-flag rate on controls reported |
| G4 | Citation integrity | Scripted check against the packet's own text, plus a visual check of table cells and rendered image pages | 100% of quotes resolved at the cited page. Unresolved and fabricated are reported separately. 0 fabricated documents |
| G5 | Stability | A second independent run (other librarian and mapper families, another packet build, another seed) | ≥ 0.85 same estimand and value per cell, within tolerance; every difference flagged. This test detects instability, never a stable error |
| G7 | Scripted invariants | Rules that hold whatever any model says: no join fan-out on cruise, station, event and specimen keys; every zero-catch haul kept; specimen counts no greater than catch; stock probabilities summing to 1; effort and swept area positive; positions, depths, temperatures and salinities inside physical bounds | 0 violations, or each one explained with a citation |
| G6 | Defect escape | A fixed, independent audit of critical outputs, omissions and unanimous accepts, with its search effort sealed in advance | 0 errors that change a headline result. Zero finds without stated search effort means nothing |

Before the gate certifies any graph output, it seals the denominators, the minimum coverage by independent cluster, the tolerances, and hard stops for any silent critical failure. Thresholds are never met by abstaining or by flagging everything.

### What the gate cannot show

- Errors that all sources share and that no published result, revision or raw data exposes.
- Facts that exist only in a person's memory. The graph records these as "not established by the documents" and attaches the open question to the node. Nobody waits for an answer.

### What stays

- CARE and Indigenous data holds. These concern rights, not accuracy, so the hold rule stays unchanged.
- Custodian questions as an output attached to graph nodes, not as a gate.

### What goes

- The assessment-scientist sheets and the human-key thresholds in v2.2 §7.

### Route to the IYS High Seas Expeditions graph

Round 3 (spawner abundance) is the last escapement round. Round 4 is an IYS pilot that uses the same machinery on the 2019, 2020 and 2022 expeditions. G2 uses the published expedition results as the outside reference. The hypotheses come from the expedition plans and reports, not from model memory.
