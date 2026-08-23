# #250 — What prompt makes coding agents write behavioral tests?

## Question

- **Context:** coding agents write regression tests after reading a small incident and current implementation.
- **Change under test:** add a compact six-question behavioral-test checklist before the agent writes the test.
- **Baseline:** the same task plus a 32-word instruction to write the smallest focused regression test, edit only the test file, and run focused pytest.
- **Outcome:** intended mutant caught, valid alternate implementation accepted, production path exercised, non-vacuity/positive control, and no scope/test weakening; test size, tool calls, and hangs are guard metrics.

The operational question is not whether the checklist sounds sensible. It is whether it improves those observable outcomes on the same frozen tasks without creating verification whales.

## Hypotheses considered

### H1 — checklist improves behavioral discrimination

The checklist causes better tests because it makes the agent name both sides of the oracle before coding: a regression that must be red and a valid future change that must remain green.

**Falsifier:** no score gain over baseline, or a gain bought by a preregistered whale condition.

### H0 — task statement already supplies the useful signal

The checklist adds process text without improving correctness because a competent coding agent already extracts the incident, public path, and valid alternative from a well-scoped task.

**Falsifier:** candidate gains at least three criterion-points overall and wins on at least two tasks without a whale.

### H2 — a prompt can improve one oracle dimension while damaging another

The checklist can make positive controls more explicit yet still induce representation assertions when the agent turns a valid-alternative example into exact whole-object equality.

**Falsifier:** every candidate-only gain occurs without a candidate-only regression, especially on the valid-alternate criterion.

## Sources and prior evidence

OpenAI's current model guidance recommends lean prompts, one instruction group changed at a time, and rerunning the same representative evals; its reported internal token/score ranges are explicitly directional and must be validated on the application's workload [1]. OpenAI's eval guidance separately recommends task-specific datasets, automated scoring where possible, explicit objective/dataset/metrics, and comparison or classification rather than open-ended vibe grading [2]. These are primary external sources current on 2026-08-23.

The local corpus contains 13 real cases, including all cases named in the task and a counterexample where exact cardinality is the business contract [3]. The cases are independent failure shapes, not 13 repetitions of the AI Proxy Manager incident.

## Evidence table

The required table with the exact columns is in [`corpus.md`](corpus.md) [3]. It includes:

1. AI Proxy Manager `article.route.count() == 7`;
2. exact-one fan wake, where cardinality is the contract;
3. literal `AbortSignal.timeout(30000)` / argv-source matching (#154);
4. direct primitive instead of `SessionManager.remove()` (#219);
5. empty `all()`/`any()` source collection (#203);
6. unconstrained `MagicMock` truthiness and wrong async double (#220);
7. executor-authored test under its own implementation (#210);
8. fallback/symmetric fixtures masking a mutation (#151/#186);
9. a negative test made vacuous by trigger inversion (#241);
10. absence assertion over live `#chat` (#270);
11. a short wall-clock timeout doubling as a performance assertion;
12. live quota/network/load state in automatic tests; and
13. Playwright receiving main assets instead of worktree JS/CSS.

The focused current-source proof command recorded in [`proof-tests.txt`](proof-tests.txt) produced `8 passed in 19.27s`, `EXIT=0` [3]. Historical mutant outputs and counterexamples remain cited per row rather than being replaced by the green current run.

## Frozen A/B method

The corpus, 32-word baseline, 175-word candidate, six fixtures, task texts, expected outcomes, controls, runner, grader, thresholds, and SHA-256 manifest were committed at `ce600426` before the first model call [4]. `sha256sum -c` returned `OK` for all 38 frozen entries. Candidate SHA-256 is `cdcc1a99308601eb3d68b8a78455db281492949809034625532604bfaf6969b9` [5].

The grader pilot scored strong hand-written controls `30/30` and deliberately brittle controls `14/30`; a collection/import error was not counted as red [5]. Six task pairs ran on fresh ephemeral `gpt-5.6-luna` sessions in the preregistered interleaved order. T05 (ledger idempotency) and T06 (deployment manifest parsing) are the two distant-domain transfer cases [4].

The grader did not score prose. It ran each produced test against current code, valid alternatives, intended mutants, a production-path mutation, and a positive-control mutation, with a 10-second per-command ceiling [4][6].

## A/B results

### Headline

| arm | behavioral score | paired W/L/T | intended mutants | valid alternates | production path | positive control | scope integrity |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | **28/30** | — | 6/6 | **6/6** | 6/6 | 4/6 | 6/6 |
| candidate | **28/30** | **1/1/4** | 6/6 | 5/6 | 6/6 | **5/6** | 6/6 |

The paired two-sided exact sign test is `p=1.0`; it is descriptive here because only two pairs were non-ties [6]. The preregistered H1 success condition was not met: score gain `0`, one win, one loss.

### Per-task scores

| task | baseline | candidate | observed difference |
|---|---:|---:|---|
| T01 route switch/cards | 4 | 4 | both missed the frozen empty-card positive control |
| T02 lifecycle kill path | 5 | 5 | tie |
| T03 explicit classifier + fallback | 4 | 5 | candidate added a normal visible event, so `return []` turned red |
| T04 prompt collection | 5 | 5 | tie |
| T05 exactly-once ledger | 5 | 4 | candidate compared the complete debit dict and rejected a valid added metadata field |
| T06 manifest parser | 5 | 5 | tie |

The T05 failure is the load-bearing counterexample. Before editing, the candidate agent explicitly answered that non-debit audit entries were a valid future change, and its seeded audit entry correctly stayed green. It then asserted the complete shape of the debit record:

```python
assert debits == [{"kind": "debit", "invoice_id": "inv-1", "amount_cents": 1250}]
```

The separate frozen valid alternative added `"recorded_by": "billing"`; this metadata dimension was not named in the agent's answer. The test failed even though the contract fields and exactly-one debit behavior remained correct [7]. The baseline asserted filtered cardinality and the amount field separately, so it stayed green [7].

### Prompt adherence and cost guards

All `6/6` candidate subjects emitted numbered answers 1–6 before the first `file_change` event [6]. Thus the prompt did force the requested planning output; the equal correctness score is not explained by simple instruction noncompliance.

| guard metric | baseline | candidate |
|---|---:|---:|
| nonblank test LOC, total | 63 | 64 |
| maximum test LOC in one cell | 13 | 14 |
| tool calls, total | 35 | 32 |
| median tool calls | 6 | 5 |
| grader timeouts | 0 | 0 |
| maximum focused grader command | 0.242 s | 0.371 s |
| model wall time, total | 272.040 s | 388.128 s |
| maximum model wall time | 56.528 s | 117.014 s |

No preregistered verification-whale condition fired [6]. Candidate wall time was 42.7% higher, but one sample per cell and changing host load do not identify the prompt as the cause; tool calls moved in the opposite direction. Tokens/cost were not emitted by this isolated runner, so no token-efficiency claim is made.

## Findings and confidence

### F1 — “assert behavior, never counts” is false

**CONFIRMED — primary code and direct mutant corpus.** Incidental card count breaks on a valid added card, while exactly one reducer wake and exactly one debit per invoice are business contracts after filtering to the contract event [3][7]. The operational distinction is not count versus no count; it is contract cardinality versus today's unscoped representation cardinality.

### F2 — the six questions force explicit pre-test design output

**CONFIRMED on this runtime/corpus — direct measurement.** All 6 candidate sessions answered all six numbered questions before their first file edit [6].

### F3 — explicit pre-test answers did not improve behavioral correctness

**REFUTED for the leading hypothesis on the frozen corpus — direct paired measurement.** Candidate and baseline both scored 28/30; candidate won one task, lost one, and tied four (`p=1.0`) [6]. This meets H1's preregistered falsifier.

### F4 — prompt compliance is not oracle enforcement

**CONFIRMED — direct counterexample.** The candidate handled the one future change it named (a non-debit audit entry) but still rejected a different valid representation extension through exact whole-record equality [7]. Naming one valid extension did not prevent over-specification along an adjacent, unmentioned metadata dimension.

### F5 — the checklist did not create verification whales

**CONFIRMED on the frozen runs — direct measurement.** Candidate tests were 64 versus 63 nonblank LOC, used 32 versus 35 tool calls, and had zero grader timeouts [6]. This removes one possible objection but does not turn a zero correctness gain into an improvement.

### F6 — prompt-only reliability is not established; independent oracles remain the stronger mechanism

**LIKELY — direct A/B plus prior independent evidence.** #210 measured an executor's own `13 passed` while an independently hidden frozen oracle produced 17/42 failures, six against explicit AC [8]. #250 shows the analogous smaller failure: a six-answer checklist can be obeyed while a valid alternate still turns red. The strongest operational mechanism is therefore a lean prompt plus an independently frozen behavioral grader/mutant set, not a longer checklist alone [2][6][8]. Generality beyond this model/corpus remains unproven.

## Counter-evidence and limitations

- Candidate improved T03 by adding a normal visible event; `visible_subagents(...) -> []` then failed. The checklist can help a specific non-vacuity gap [7].
- Candidate caught all intended mutants and exercised every frozen production path; it was not generally poor [6].
- T01's empty-card control is debatable if the task contract is read as switch-only rather than UI-card rendering. Treating that criterion as pass for both arms changes 28/30 to 29/30 for both and leaves the zero differential unchanged.
- N=6, one repetition, one model/runtime, and small Python fixtures do not establish model-wide reliability. The exact sign test has only two non-ties.
- The two distant-domain cases broaden topic coverage but do not establish semantic independence from the corpus author.
- No token/cost metric was available; only tool calls, LOC, focused grader duration, and model wall time were recorded.
- A revised prompt that explicitly says “assert only named contract fields, never whole records when metadata may grow” was not tested. Claiming it fixes T05 would be speculation.

## Answer / operational recommendation

There is no evidence-backed short prompt that **reliably** produces high-signal behavioral tests by itself in this experiment. The tested standalone candidate is [`candidate-prompt.md`](candidate-prompt.md); it reliably elicited the six requested answers (6/6), but it did **not** improve correctness over a precise baseline (28/30 versus 28/30) and traded one positive-control gain for one valid-alternative regression.

Do not promote this candidate as a mandatory production rule on the strength of #250. If used, treat it as a compact design checklist. The reliability boundary must remain mechanical: freeze the incident/contract and valid alternative before implementation, run the produced test against an intended mutant plus relevant fallback/compound case, and reject tests that fail a valid alternate, bypass the production path, pass vacuously, hang, or expand scope.

## Affected files, risks, and edge cases

No production prompt, skill, test, deployment, or service was changed. Phase 1 touched only:

- `docs/tasks/250/` — corpus, preregistration, standalone candidate, fixtures, runner/grader, sanitized raw outputs, and analysis;
- `docs/kb/test-oracles.md` — new measured conclusion and open gap.

If a later approved phase changes production prompts, the likely consumer is the test-writing/code-quality instruction owner, but #250 does not authorize or recommend that edit. Risks for a future eval are repeated-sample cost, cross-language transfer, graders that mistake harmless metadata for contract breakage, and positive controls attached to a collection outside the actual contract.

## Task-observer outcome

The observation log is in [`observations.md`](observations.md). No new skill is justified: the reusable finding belongs to `test-oracles`, and the existing task-observer/table and context-economy methods already covered the only workflow issue encountered.

## Adversarial review outcome

One targeted Sol review recomputed the `28/30` totals, `1/1/4` split, `p=1.0`, criterion counts, cost guards, expected variants, and distinguishing T03/T05 outcomes and returned **APPROVE WITH SUGGESTIONS**, with no blocking findings [10]. Its two suggestions were accepted above: the unregistered two-win threshold was removed from H1, and T05 was narrowed from “the named alternative did not constrain the assertion” to “one named alternative did not prevent over-specification on another dimension.” No second review round is allowed for suggestion-only prose changes.

## Sources

1. **[Tier 2 — official primary documentation]** OpenAI, [Model guidance: Favor leaner prompts / compare on representative evals](https://developers.openai.com/api/docs/guides/latest-model), fetched 2026-08-23.
2. **[Tier 2 — official primary documentation]** OpenAI, [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices), fetched 2026-08-23.
3. **[Tier 1/2 — direct rerun + primary repository artifacts]** `docs/tasks/250/corpus.md`; `docs/tasks/250/proof-tests.txt`; cited current tests and historical task reports per row.
4. **[Tier 1 — preregistered experiment]** `docs/tasks/250/prereg.md`; freeze commit `ce600426`; `docs/tasks/250/freeze-manifest.sha256`.
5. **[Tier 1 — mechanical pilot]** `docs/tasks/250/grader-self-test.txt`; `docs/tasks/250/expected-outcomes.json`.
6. **[Tier 1 — direct measurement]** `docs/tasks/250/analysis-summary.json`; `docs/tasks/250/grade-results.json`.
7. **[Tier 1 — raw direct outputs]** `docs/tasks/250/raw/*/{events.jsonl,test_target.py,diff.patch,metadata.json}`.
8. **[Tier 1 — prior controlled local measurement]** `docs/tasks/210/research.md`, hidden frozen oracle versus executor-authored tests.
9. **[Tier 1 — prior local measurement]** `docs/kb/token-efficiency.md`, prompt/tool-call cost and verification-whale evidence.
10. **[Independent reviewer artifact]** `docs/tasks/250/review-research.md`, one targeted `gpt-5.6-sol` adversarial pass with evidence-bearing suggestions and completed verdict.

## Review gate inputs

- **Changed files / consumers:** prose and research harness only under `docs/tasks/250/`, plus appended evidence in `docs/kb/test-oracles.md`; consumers are the task owner and future agents reading the test-oracles memory gate. No production runtime consumer changed.
- **Author model/runtime:** `gpt-5.6-sol` on Codex runtime, verified by `list_agents` for `research-test-prompt-sol` on 2026-08-23.
- **Exact AC:** 13-row evidence table with the eight required columns and all named cases; standalone concise candidate containing the six pre-test questions and conditional deterministic/mutation guidance; frozen interleaved baseline/candidate eval with 1–2 distant domains; behavioral grader for the five named criteria plus LOC/tool/hang guards; sanitized raw artifacts; new measured KB findings only; no production/deploy change.
- **Named checks:** `python3 docs/tasks/250/eval/verify_artifacts.py` → all checks `PASS`, including 13 rows, 12 raw cells, 6/6 pre-edit answer blocks, 38 frozen hashes, and zero secret-form hits; `python3 docs/tasks/250/eval/grader.py --self-test` → strong `30/30`, weak `14/30`; focused current-source proof → `8 passed in 19.27s`, `EXIT=0`.
