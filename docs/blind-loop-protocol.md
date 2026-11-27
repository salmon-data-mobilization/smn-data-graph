# Blind loop protocol, v2 (draft, 2026-11-27)

This replaces the single-model loop used in the November 2026 intake rounds
under `data/intake/`. It responds to an outside review of those rounds by
GPT-6.2 Sol and Fable 5.2. The review confirmed the arithmetic. It found that
the rounds could not estimate an error rate or show that the added checks help
on new data, and that no domain scientist or data custodian checked any claim.

The aim is evidence a sceptical fisheries scientist would accept. A second AI
model is a robustness check. It is not scientific sign-off.

## 1. What changed from v1, and why

| v1 weakness (found in review) | v2 rule |
|---|---|
| Mapper and grader were the same model, so they shared blind spots. | Mapper and grader roles use at least two model families, and each grader comes from a family that did no mapping on that case. Disagreement between families sends a claim to a person. |
| The coordinator chose each case after a non-blind search to show a known contrast. | Cases are drawn at random from a sampling frame built and hashed before any agent analyses a case. The frame scout lists every eligible case and does not screen for interest. |
| The protocol named the expected structure of the answer ("at least one stream changes role"). | Mappers get one generic question, the same for every case. |
| The coordinator wrote checker code before the mapper sealed. | No case-specific checker code exists before the mapper seals. Mappers work source-led, without earlier tooling. |
| Repairs were graded on the same case and ended all-pass. | First-pass results are final for the round. A repair is only scored on new cases drawn from the frame. |
| The rubric rewarded bookkeeping: none of the material omissions the reviewers found could fail a check. | The rubric scores materiality, competing or superseded editions, uncertainty quality, preservation of source caveats, and omissions found by other roles. |
| Some loop agents read shared agent memory. | No role except the coordinator reads agent memory or earlier rounds. |
| No domain person or data provider took part. | Every case ends with a claim sheet for the data custodian or an assessment scientist. Critical claims are not published until a person has answered it. |
| Seals were local hashes in a gitignored folder. | Seals are recorded in `seals.md` with receipt times. Pushing hash-only seals to a public branch is optional and needs Brett's approval per round. |

## 2. Roles

- **Coordinator** (not blind): builds the protocol, seals it, runs the draw,
  hands out materials, assembles reports. Authors no answers and no reference
  keys.
- **Frame scout**: lists eligible cases from public sources against fixed
  inclusion criteria. Does not analyse them.
- **Mappers** (two or three, one per model family): answer the case question
  independently. They see only the brief and case sources.
- **Graders** (two, from different families): adjudicate every mapper's claims
  against the sources using the sealed rubric, then compare with each other.
- **Custodian or assessment scientist** (a person): answers the claim sheet.
  Their answers become the human-sealed key.

## 3. Procedure for one round

1. Write `protocol/design.md`, `protocol/mapper-brief.md` and
   `grading/rubric.md`. Seal all three before the frame exists.
2. The frame scout writes `frame/frame.json`. Seal it.
3. Draw cases with a seed taken from the frame hash, and record the draw.
4. Place each case's source list in `cases/<id>/case.md`, with the generic
   question.
5. Run the mappers in parallel. Seal each mapper's folder when it finishes.
6. Run both graders over all sealed mapper outputs. Seal each grade.
7. Compare the graders' results. Build one claim sheet per case.
8. Write `REPORT.md`: per-case results by model family, agreement between
   graders, omissions, cost and wall time. No aggregate accuracy claim until
   enough cases have accumulated (§5).
9. Send the claim sheets only with Brett's approval. Record the answers as
   keys.

## 4. Claim sheet

One page per case, written for someone who knows the stock:

- the figures in question, with locators;
- each critical claim, and which families agree or disagree with it;
- materiality: how much each open point would change the number a researcher
  uses;
- at most five yes/no or short-answer questions;
- a line for the respondent's name, role and date.

## 5. Measuring over time

Keep a running ledger across rounds with these entries per case and model:
- claims correct, wrong or unsupported;
- material omissions;
- false accepts (an unfit use called fit);
- false abstentions;
- agreement with the custodian key once it exists.

Report rates with intervals only after 20 or more cases drawn from the frame.
Run an ablation every few rounds that compares the lean source-led workflow
with the full checker stack on the same new cases. Keep a check only if it
catches material errors on cases it was not built for.
