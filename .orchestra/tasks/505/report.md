# #505 report — Astra vs Sol on long agentic Orchestra work

Date: 2026-09-05. Candidate: open replay of completed production task #474. Model-facing prompt:
the frozen 65-test oracle is red; diagnose and make it green.

## Outcome

**Preregistered verdict: `question_open`.** The experiment qualified as long for both models, but
each model produced only 2/3 accepted results. The rule required both to be 3/3 before comparing
their per-run USD ranges. No winner is inferred post hoc.

This is not a null dataset. It establishes three bounded results:

1. The open task crossed all frozen long thresholds for both models.
2. Across all three attempts, Sol's measured USD per accepted result was `$1.6816204`; Astra's was
   `$4.1905540`, a **2.49197×** ratio. This is descriptive evidence, not a routing verdict, because
   3/3 acceptance failed.
3. Both rejected attempts had a green 65-test oracle and were rejected only because each added the
   same one-line compatibility field to `app/mcp_stdio.py`, outside the frozen five-path scope.
   Therefore 2/3 must not be interpreted as either model failing to solve the defects.

## Frozen design and integrity

- Base: `bf59a7d38739af3c7652b9466b2590490d83b0b7`.
- Oracle bundle: `1c62094929224831801cf42bb314844159f8cd807e670a1457cdd348d3252002`.
- Open assignment: `de11c6f430de30e5d718dbeddf321e2dbe085ac25a15f84da0bf13c10161d93d`.
- Binary throughout: `/home/maxim/.local/bin/codex` → `codex-cli 0.153.4`, wrapper SHA-256
  `61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70`.
- Order: Astra/Sol/Astra/Sol/Astra/Sol, `medium`, `--ignore-user-config`, explicit
  `project_doc_max_bytes=262144`.
- Every run: provider RC 0, oracle RC 0 (`65 passed`), non-zero computed cost, unchanged source
  fixture, unchanged oracle bundle and scratch tests, unchanged binary.
- Isolation preflight: `SHELL_OK`, `PRODUCTION_WRITABLE=5/5`, baseline
  `10 failed, 49 passed, 6 errors`, `BLINDNESS_OK`; `.git` and the live repository were absent,
  and all 195,089 bytes of `AGENTS.md` reached the prompt.
- Source blindness is **CONFIRMED for named paths**; arbitrary undiscovered side channels remain
  possible.

The first harness attempt exposed a nested-sandbox defect: Codex tried to create its own bwrap
inside the outer source-blind bwrap, so neither command body started. The repair kept the outer
namespace and used `--dangerously-bypass-approvals-and-sandbox`, the CLI mode intended for an
already externally sandboxed process. The final preflight proved shell, test, write, and blindness
before the next paid call.

## Per-run measurements

`load` is the one-minute load average before→after. Full 1/5/15-minute vectors are in
`raw/benchmark.json`.

| model | run | accepted | reject reason | wall s | load | tools | input | cache read | fresh | output | reasoning | cost USD |
|---|---:|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| Astra | 0 | yes | — | 235.016 | 1.46→2.57 | 19 | 1,646,676 | 1,550,592 | 96,084 | 5,387 | 138 | 2.7807820 |
| Sol | 0 | no | extra `app/mcp_stdio.py` | 191.951 | 4.29→6.06 | 16 | 1,628,365 | 1,521,536 | 106,829 | 6,221 | 1,392 | 1.1603504 |
| Astra | 1 | no | extra `app/mcp_stdio.py` | 573.834 | 4.94→6.23 | 23 | 2,000,908 | 1,899,648 | 101,260 | 5,267 | 131 | 3.1755980 |
| Sol | 1 | yes | — | 181.965 | 7.60→4.81 | 15 | 1,584,666 | 1,480,704 | 103,962 | 5,915 | 1,118 | 1.1264296 |
| Astra | 2 | yes | — | 207.582 | 5.68→6.95 | 15 | 1,367,685 | 1,275,008 | 92,677 | 4,459 | 112 | 2.4247280 |
| Sol | 2 | yes | — | 500.695 | 12.63→11.19 | 16 | 1,674,801 | 1,600,512 | 74,289 | 6,955 | 1,662 | 1.0764608 |

Literal arithmetic is stored per row. Examples:

- Astra 0: `(96084*10 + 1550592*1 + 0*12.5 + 5387*50)/1e6 = $2.780782000`.
- Sol 0: `(106829*4 + 1521536*0.4 + 0*5 + 6221*20)/1e6 = $1.160350400`.

All costs are API-equivalent computed USD. Standalone `codex exec` does not create attributable
Orchestra `turn_usage` rows; no value is presented as recorded `turn_usage.cost_usd`. Pool
percentages were not sampled.

## Aggregates and frozen decision rule

| metric | Astra | Sol |
|---|---:|---:|
| attempts / accepted | 3 / 2 | 3 / 2 |
| total input | 5,015,269 | 4,887,832 |
| cache read | 4,725,248 | 4,602,752 |
| fresh input | 290,021 | 285,080 |
| output | 15,113 | 19,091 |
| reasoning (included in output) | 381 | 4,172 |
| total attempt cost | `$8.3811080` | `$3.3632408` |
| USD / accepted result | **`$4.1905540`** | **`$1.6816204`** |
| median wall | 235.016 s | 191.951 s |
| median tool items | 19 | 16 |
| median output | 5,267 | 6,221 |
| long thresholds | 3/3 pass | 3/3 pass |

Failed attempts remain in each model's numerator. Both accepted counts are 2, so the USD/accepted
ratio equals the total-cost ratio: **2.4919738× Astra/Sol**.

The raw attempt-cost ranges are Astra `$2.424728–$3.175598` and Sol
`$1.076461–$1.160350`. They do not activate the winner rule: the preregistration allowed range
comparison only after 3/3 acceptance for both models. `raw/benchmark.json` correctly stores both
accepted-run ranges as `null` and the verdict as `question_open`.

## Why acceptance was 2/3

All six runs made the oracle green. The rejected Sol 0 and Astra 1 runs changed the five expected
production files **plus** `app/mcp_stdio.py`. Their extra diff is byte-identical:

```diff
@@ async def codex_review(...)
         "production_snapshot_sha256": "",
+        "production_diff_sha256": "",
         "production_paths_json": "[]",
```

The open assignment intentionally did not name the five allowed files, while the harness retained
the preregistered five-path scope. Two independent runs inferred that the new non-null receipt field
also belongs in the MCP receipt payload. The historical implementation and the oracle did not
require that line, but it is a plausible compatibility completion rather than weakened testing:
both runs kept all four oracle files byte-identical and passed all 65 tests.

This is counter-evidence against reading the acceptance count as model reliability. It is also why
the result cannot be upgraded post hoc: broadening the scope after seeing the identical alternative
would change the oracle contract. The correct registered outcome remains `question_open`.

## Token-efficiency finding

The external long-work hypothesis did not reproduce directionally on this task:

- Astra used **2.607% more total input** than Sol (5,015,269 vs 4,887,832), not materially less.
- Astra used **20.837% fewer output tokens** (15,113 vs 19,091), far short of the external 5.3×
  reduction that motivated #505.
- Astra used far fewer reported reasoning tokens (381 vs 4,172); all three Astra rows were non-zero,
  so the reasoning-channel control was not triggered.
- The 2.5× card dominated: total computed cost was **2.49197×**.

More importantly, crossing the frozen long-work thresholds did not make output dominate the bill.
Across the three long attempts, input was **90.984%** of Astra's cost and **88.647%** of Sol's;
output was only 9.016% and 11.353%. Tool use repeatedly reintroduced large cached context, so a
long agent loop preserved essentially the same input-dominated mix seen in #498.

This observation is CONFIRMED for these six runs. It does not override the preregistered routing
verdict, which remains open because acceptance was 2/3.

## Experiment overhead outside the open A/B

Two Astra calls are permanently preserved but excluded from the open A/B numerator and ranges by
the owner-approved re-preregistration:

| variant | accepted | wall | tools | output | cost | classification |
|---|---:|---:|---:|---:|---:|---|
| nested-sandbox attempt | no | 33.656 s | 2 | 339 | `$0.716476` | harness defect; command bodies never started |
| fully specified assignment | yes | 154.955 s | 10 | 3,785 | `$1.659628` | valid closed-work result; below long floor |
| **overhead total** |  |  |  |  | **`$2.376104`** | excluded, not deleted |

The closed-assignment row is a real capability data point: Astra repaired five connected merge-gate
defects across exactly five production files, kept the oracle untouched, and produced `65 passed in
8.52s` for `$1.659628`.

The sandbox-failure row independently measured Astra's fixed toll before work: fresh input 51,367
cost `$0.513670`, cache-read 185,856 cost `$0.185856`, and output 339 cost `$0.016950`. Input was
`$0.699526` or **97.634%** of its `$0.716476` total. A 195,089-byte `AGENTS.md` plus the surrounding
fixed prompt/context therefore cost about **$0.70 before useful work began** in that turn.

Open A/B cost was `$11.7443488`; adding preserved experiment overhead gives `$14.1204528` total
computed USD for #505.

## Verification

Independent recomputation over `raw/benchmark.json` printed:

```text
VERIFICATION_OK: 6 ordered runs; costs recomputed; 65 tests green each; all hashes/binary fixed;
accepted A=2/3 S=2/3; long=true; verdict=question_open; overhead=$2.376104
```

Review: none — the orchestrator recorded the Phase 1 no-review decision, and no additional model
review was authorized or needed for the mechanically verified result.

## Files and next decision

- Frozen design and runner: `research.md`, `candidate_task.md`, `run_ab.py`.
- Canonical measurement: `raw/benchmark.json`.
- Raw model events: eight `raw/events-*.jsonl` files (two excluded Astra variants plus six open
  A/B attempts).
- No `app/**`, production database, user config, or live service was changed.

Open decision for the owner: keep the strict preregistered `question_open`, or authorize a new
experiment whose acceptance contract admits the independently repeated `app/mcp_stdio.py` field.
No rerun or threshold/scope change was made in this task.

## Sources

1. `.orchestra/tasks/505/raw/benchmark.json` — canonical per-run usage, costs, hashes, load,
   acceptance, preflight, overhead ledger, and verdict.
2. `.orchestra/tasks/505/raw/events-*.jsonl` — model commands/messages and file-change events.
3. OpenAI Docs, `https://developers.openai.com/api/docs/pricing.md` — Standard short-context USD
   rates: Astra 10/1/12.5/50 and Sol 4/0.4/5/20 per 1M tokens.
4. OpenAI Docs, `https://developers.openai.com/codex/pricing.md` — credit ratios and Astra Fast-mode
   2.5× multiplier; Fast was disabled here.
