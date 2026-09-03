# #456 — design defects that escaped review

## Question

- **Context:** Orchestra's own implementation/review history, limited to the three candidates named in task #456: split task-number ownership, content-derived fact identity, and transcript lookup through a replaceable SDK `session_id`.[1]
- **Change under test:** one bounded review STOP rule for durable identity and state ownership.
- **Baseline:** the review artifacts and review/no-review decisions that actually accompanied the historical diffs.
- **Measured outcome:** for every candidate, whether the defective hunk entered implementation review and what the reviewer wrote; on a frozen replay, true STOPs across 3 positives, false STOPs across 6 controls, prompt-token increase, and review-turn increase.

## Hypotheses considered

1. **H1 — one structural class exists.** A durable-identity mismatch or multiple independent writers cause these failures because the chosen key/owner has a different lifecycle or uniqueness scope from the logical entity/state. **Falsifier:** the three candidates do not share either invariant, or a bounded classifier cannot distinguish them from controls.
2. **H2 — the current severity wording is the main problem.** Review misses the class because PROJECT CONTEXT names only crash/corrupt/security as blocking. **Falsifier:** review catches the design defect before code, or defective implementation never enters review.
3. **H3 — a prompt-only STOP rule catches the class without an open-ended review loop.** **Pre-registered falsifier:** fewer than 3/3 positive STOPs or more than 1/6 false STOPs in one turn.[2]
4. **H4 — more review rounds solve the miss.** **Falsifier:** a reviewed hunk survives the full existing round ceiling without the lifecycle defect being named.

## Method

The corpus, labels, order, exact STOP rule, and pass threshold were committed before the evaluator ran (`259bcff4`). The evaluator saw only nine fixed excerpts in `evaluation-packet.md`, not `evaluation-gold.json` or task history. The three positives were the card-named historical candidates. The six controls were two paired fixes at the same seams plus four ordinary reviewed/leaf changes that do not create durable identity or a second state writer.[2][3]

Historical classification uses this strict rule:

- **review saw and missed:** a model-review artifact exists, its input contains the exact defective hunk, and the artifact does not name that lifecycle/ownership failure;
- **did not reach implementation review:** no implementation-review artifact/input exists, even if an earlier plan review discussed the subject;
- **caught but not enforced:** the plan review names the exact defect, but implementation contradicts it and has no implementation review.

The read-only reproduction is `history_audit.py`; it queries the live SQLite log through `mode=ro`, checks exact git hunks/artifacts, and writes `history-audit.json`.[4]

## Historical findings

| Candidate | Defect proved in history | What review actually saw/wrote | Classification |
|---|---|---|---|
| Task number / two stores | `baf501c7` added canonical `store.task_create(...)` plus legacy `_legacy_api_create_task(...)` while the independent `create_task_for_scope`/`discard_unbound_task` legacy path already existed. #406 later measured **2 semantic collisions** and a counter disagreement that raises before write.[5] | The #341 worker session has **0** `codex_review` tool calls and **0** `codex exec` calls. Its DONE message says `Review: none — explicitly prohibited`.[4] | **Did not reach implementation review.** |
| Fact identity from mutable text | `e3f95f98` builds UUIDv5 from `source_file + source_lines + statement`. #429 later states that rephrasing makes a new UUID and turns an edit into another fact.[6] | Three Luna review rounds reviewed `/tmp/kb-409.diff`. Round 1 identifies `scripts/kb_promote_facts.py:95-101` and restates the exact formula as “same source path, lines, and statement,” proving that the reviewer saw the identity hunk; no round mentions rephrasing/content mutability. All three verdicts remained `Incorrect`; there was no `APPROVED` verdict.[7] | **Review saw the exact formula and missed this lifecycle defect**, but did **not** falsely approve the whole diff. The original `/tmp` input is no longer preserved. |
| Historical transcript keyed by current SDK session | `01a666ed` looks up both transcript lists and messages through `sess.get("session_id")`; an existing rollback lifecycle replaces that field while the logical Orchestra session persists. `38caf30b` later added the historical `sdk_session_id` lookup and a regression test.[8] | Plan review explicitly said old transcripts can be lost after `compact/current-session` change and required a separate `sdk_session_id`. The plan says this was fixed, but the implementation still used the current field. At delivery, the implementation report says Codex was unavailable and asks to review implementation later; the only review file committed with the implementation is `codex-review-plan.md`.[8] | **Caught in plan, not enforced; no implementation review is evidenced at delivery.** |

### Count

- Verified design defects among the three named candidates: **3/3**.
- Exact defective implementation hunks that entered model review: **1/3**.
- **Review saw and missed:** **1/3** (`stable_fact_id`).
- **Did not reach implementation review at delivery:** **2/3** (task counters; transcript route).
- Of those two, **1** had already been caught correctly in plan review and was lost between plan and code.
- Defective diffs that received a clean `APPROVED` verdict: **0/3**. Calling these “three approved design defects” would be false.[4]

**Confidence: CONFIRMED** for this three-case corpus — direct git/artifact/SQLite measurements agree. The corpus is deliberately not a prevalence estimate for all Orchestra defects.

## The checkable class

The common class is **logical identity / ownership invariant mismatch**:

1. **Identity subtype:** code uses a value to identify, deduplicate, join, or address one logical entity across time/accounts/processes/components/stores, but the value can change while the entity persists, or two entities can share it in the required scope.
2. **Ownership subtype:** one logical state has multiple independent allocators/writers without one authoritative owner or atomic coordination.

The tested STOP rule requires a reviewer to name, from the supplied hunk and consumer context:

- entity/state;
- key or authoritative owner;
- uniqueness scope;
- every visible lifecycle mutation/writer;
- behavior under rename, rotation, reset, retry, and partial failure.

`STOP` is justified only by a concrete contradiction: same entity → another key, one key → two entities, or writers → divergent state. Ephemeral IDs, labels, content classifiers, constants, tests/docs, and read-only validation paths are explicit non-triggers.[2]

## One-turn replay and negative control

One fresh Luna pass applied the frozen rule to the blinded nine-case packet; no retry or coaching was allowed.[9]

```text
true_positive: 2/3
false_negative: 1/3 (case D, replaceable session_id)
false_positive: 0/6
true_negative: 6/6
pre_registered_threshold_met: false
```

The reviewer caught the content-derived fact UUID and dual task writers. It missed the session lifecycle even though the packet supplied both `sdk_id = sess.get("session_id")` and the pre-existing assignment `session.session_id = entry["session_id"]`.[3][9]

**Finding: the class exists, but the tested prompt-only formulation is insufficient.** It is quiet on this negative control (**0/6** observed false STOPs), yet recall is only **2/3**. Re-running after revealing the miss would be an exploratory, overfit result, so it was not done.

**Confidence: CONFIRMED** for the fixed corpus; **UNCERTAIN** outside it because six controls are too few for a population false-positive rate.

## Cost and the finite boundary

- Frozen STOP text by itself: **1,135 characters / 177 whitespace-delimited words / 234 `o200k_base` tokens**. This is a standalone tokenizer size, not a measured before/after insertion delta for a production prompt.[10]
- Nine-case packet: **7,080 `o200k_base` tokens**. The actual Luna evaluator turn recorded **386,569 input tokens, 314,880 cached input tokens, and 17,831 output tokens**; those totals include the reviewer runtime/system context and are not the marginal cost of the 234-token rule.[9][10]
- The replay used exactly **one** evaluator turn because the protocol prohibited retries. It does not measure how many production follow-ups a future gate would cause.
- False STOPs in that one-turn replay: **0/6**; production follow-up cost remains unmeasured.
- A real STOP can still open the existing evidence-backed follow-up after the artifact changes; it does not justify raising the current ceiling. #409 already spent **3 review rounds**, **4,298,927 input tokens** (4,011,008 cached), and **50,849 output tokens** while the content-lifecycle defect remained unnamed.[4]

**H4 is REFUTED for the observed #409 case only:** three changing-artifact rounds did not surface this design defect. This is not a controlled comparison of round counts and does not prove that extra rounds never help. There is no evidence here for raising the existing ceiling.

The stronger hypothesis is not another model round but a mechanically required **identity/ownership receipt** for triggered diffs: the five fields above plus a reproducible writer/mutation inventory (`rg`/AST) and an oracle for rename/reset/retry. Missing receipt or a contradictory inventory would stop admission before review. It could plausibly surface the session mutation even when the reviewer ignored supplied context, but its recall, false-positive rate, preparation cost, and delivery mechanism have **not** been measured; it is a Phase-2 design option, not a Phase-1 conclusion.

## Answer

There are **three verified design defects in the named sample**, but only **one** is a demonstrated reviewer miss. **Two never reached implementation review**, and one of those was actually caught in plan review and then ignored by implementation. The current evidence therefore diagnoses three different seams: reviewer calibration/attention, review coverage, and finding-to-code enforcement.

The narrow class can be detected partly without making review infinite: one bounded pass produced **2/3 detections and 0/6 false STOPs**; the standalone rule is **234 `o200k_base` tokens**, and the replay was capped at one turn. It cannot be called reliable or assigned a production turn cost: the pre-registered threshold failed and integration was not measured. Do **not** add generic “think about design” prose or raise the round ceiling from this evidence. If this proceeds, the evidence-aligned next experiment is a targeted admission receipt with a mechanical writer/lifecycle inventory and a fresh holdout; implementation is not justified yet.

## Counter-evidence and limits

- The session plan review caught the exact identity-lifecycle problem, so missing PROJECT CONTEXT words are **not** the sole cause.[8]
- The #409 review noticed a nearby stable-ID collision, so the reviewer was not globally blind to identity; it missed the mutable-content lifecycle specifically.[7]
- The #409 review never approved the overall diff. The evidence supports “missed this defect,” not “approved a correct-looking defective change.”[7]
- Two of three defective implementation diffs have no implementation review evidenced at delivery. A better prompt cannot inspect input it never receives.[4][8]
- The six negative controls establish an observed count only; they do not prove that production false-positive rate is zero.[2][3]
- The three candidates were supplied by the task and are not a random sample. No claim about total historical prevalence follows.[1]

## Affected files, risks, and edge cases for a possible later plan

- Potential owners: `.orchestra/pipelines/default/prompts/modules/orchestration.md` (PROJECT CONTEXT), `.orchestra/pipelines/default/prompts/skills/codex-debate.md` / `.codex/skills/codex-debate/SKILL.md` (review contract), and a task-local or repository script for the receipt/inventory check. **None was changed in Phase 1.**
- The PROJECT CONTEXT block must not be expanded blindly: the session case proves review can already find the issue at plan time, and the replay proves prose alone can still miss it.
- Lexical triggers such as `_id`, `key`, or `email` will hit secret scanners, UI identifiers, and correct fixes. The negative controls deliberately include those nearby shapes; a trigger must distinguish persistent logical identity from content classification and presentation.
- A receipt authored after implementation can self-certify the same mistake. A future plan needs a frozen pre-implementation receipt or an independently generated writer inventory.
- Cross-file lifecycle mutation is the hard edge: case D was missed even with the relevant second excerpt. A test limited to the changed hunk will overstate recall.
- An `oracle: none` design decision cannot be delegated to a cheap executor under the existing pipeline.

## Adversarial review outcome

One fresh Luna pass reviewed the draft (`review-research-luna.md`). It returned **0 blocking findings**, confirmed the replay arithmetic, and challenged six scope/causality phrasings. The final text now (a) time-scopes absent implementation review to delivery, (b) records that the original #409 `/tmp` diff is gone while the artifact itself restates the exact formula, (c) labels 234 tokens as standalone size rather than a measured insertion delta, (d) does not infer production turns from the one-turn protocol, (e) limits the three-round result to #409, and (f) labels the receipt as an untested hypothesis. No second round was opened because the first pass had no blocker.[11]

## Sources

1. **Tier 2, primary task specification:** Task Manager #456, retrieved with `task_get("456")` on 2026-09-03; anchor quote also in `.orchestra/tasks/439/claims.md:33`.
2. **Tier 1, pre-registered measurement:** `.orchestra/tasks/456/evaluation-protocol.md`; frozen in commit `259bcff4` before the evaluator ran.
3. **Tier 1, frozen corpus and labels:** `.orchestra/tasks/456/evaluation-packet.md`; `.orchestra/tasks/456/evaluation-gold.json`; generator `.orchestra/tasks/456/build_evaluation_packet.py`.
4. **Tier 1, direct reproduction:** `.orchestra/tasks/456/history_audit.py`; `.orchestra/tasks/456/history-audit.json`; read-only SQLite `logs`/`turn_usage` plus exact git/artifact checks.
5. **Tier 2, primary repo artifacts:** commits `6f874ace`, `baf501c7`, `a10f1451`; `.orchestra/tasks/406/report.md`; `.orchestra/tasks/audit-0901/report.md:139-147`.
6. **Tier 2, primary repo artifacts:** commit `e3f95f98`; `git show 3cfa301b:docs/tasks/429/plan.md:107-112`; current `scripts/kb_promote_facts.py:96-102`.
7. **Tier 2, primary review artifact:** `.orchestra/tasks/409/codex-review-impl.md`; three matching `codex_review` calls and Luna usage rows in `history-audit.json`.
8. **Tier 2, primary repo artifacts:** commit `01a666ed`; `.orchestra/tasks/subagent-telemetry/codex-review-plan.md:20-33`; `.orchestra/tasks/subagent-telemetry/plan.md`; `.orchestra/tasks/subagent-telemetry/report.md`; commit `38caf30b` and `tests/test_subagent_routes.py::test_transcript_uses_historical_sdk_session_from_telemetry`.
9. **Tier 1, direct evaluator measurement:** `.orchestra/tasks/456/evaluation-luna.md`; `.orchestra/tasks/456/score_evaluation.py`; `.orchestra/tasks/456/evaluation-score.json`; `turn_usage.id=7314`.
10. **Tier 1, deterministic token proxy:** `.orchestra/tasks/456/measure_review_cost.py`; `.orchestra/tasks/456/review-cost.json`; command `uv run --no-project --with 'tiktoken==0.13.0' --python /mnt/data/Projects/Python/orchestra/.venv/bin/python python .orchestra/tasks/456/measure_review_cost.py`.
11. **Tier 2, independent model review:** `.orchestra/tasks/456/review-research-luna.md`; metadata names `gpt-5.6-luna`, verdict states “No blocking findings,” and cites an exact sentence from the reviewed artifact.
