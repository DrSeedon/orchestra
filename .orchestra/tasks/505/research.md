# #505 — Astra vs Sol on long agentic Orchestra work: preregistration

Date: 2026-09-05. Phase 1 only. **Paid model calls made in this phase: 0.**

## Question

- **Context.** Orchestra uses the Codex CLI with a large fixed role/project prompt. #498 measured
  a 28–32 second closed ticket: Astra used 46% fewer output tokens but cost 2.23× Sol in subscription
  credits because output was only 9.8% of Astra's bill.
- **Change under test.** Route genuinely long, multi-step Codex work to `gpt-6-astra` instead of
  `gpt-5.6-sol`.
- **Baseline.** Sol on the identical source, prompt, oracle, effort, isolation, and run order.
- **Measurable outcome.** API-equivalent **USD per independently accepted result**, using the
  owner's 2026-09-05 metric correction. Pool percentages and subscription credits are not used.

## Hypotheses and falsifiers

| hypothesis | what would prove it wrong |
|---|---|
| H1: Astra's token efficiency on long work more than pays for its 2.5× token rates | all six runs are accepted and Sol's per-run USD range lies strictly below Astra's |
| H2: fixed/repeated input remains large enough that Sol is still cheaper | all six runs are accepted and Astra's per-run USD range lies strictly below Sol's |
| H3: the answer depends on run variance rather than model identity | both models are 3/3 accepted but their per-run USD ranges overlap |
| H4: the candidate is not actually long enough to answer #505 | either model misses any preregistered long-work threshold: median wall time 180 s, median 8 completed tool items, or median 5,000 output tokens |

The 5,000-output-token threshold is not arbitrary. With the #498 measured short-run input mix,
Astra's input portion was `$0.171694` and Sol's was `$0.0685824`; 5,000 output tokens cost `$0.25`
and `$0.10` respectively. Passing the threshold therefore makes generated output cost exceed the
fixed short-ticket input overhead on both cards. Reasoning tokens are already included in
`output_tokens`; they are reported separately but never added a second time.

## Candidate task

**Selected: source-blind replay of completed production task #474, on base commit
`bf59a7d38739af3c7652b9466b2590490d83b0b7`.** The model must repair five connected merge-path
defects across these five production files:

- `app/db.py`
- `app/merge_operations.py`
- `app/merge_test_gate.py`
- `app/review_coverage.py`
- `scripts/migrate_review_receipts.py`

The behaviors are: a named per-node pytest timeout that does not kill the batch; review identity
that survives unrelated target movement but not changed production; structured fail-closed git-ref
errors; no receipt inheritance by untracked production files; and no accidental bypass of a legacy
registered acceptance command. The exact assignment is `candidate_task.md`.

This is genuinely ours and long by evidence, not by prompt length:

- Task Manager records #474 from `2026-09-04T10:49:45.299653Z` to
  `2026-09-04T12:07:19.376242Z`: **4,654.076589 seconds (1:17:34)** [2].
- Its completed commit changed 15 files by +1,648/−43; the production slice replayed here is five
  files and **+222/−33** (`git diff --numstat bf59a7d3 cb052ed -- <five paths>`) [3].
- The pre-fix `CLAUDE.md` is 447 lines / 195,089 bytes; its prompt tree is 23 files / 174,638 bytes.
  `AGENTS.md` is reproduced byte-for-byte from that `CLAUDE.md`, as Orchestra does at Codex connect.
- The accepted oracle is 65 tests across four files, not one assertion. The pre-fix source gives
  **10 failed, 49 passed, 6 errors in 7.96 s**; the completed five-file production diff gives
  **65 passed in 9.00 s** [4]. The setup `KeyError`s are the missing diff-identity behavior, not
  collection/import failures.

### Alternatives rejected

- Reusing #498's `humanize_ranges` ticket is refuted by #498 itself: 28–32 seconds, 2–4 shell
  commands, hundreds of output tokens. It would remeasure fixed prompt overhead.
- The 276-row #501 rules audit looked long, but its Task Manager state is still `new` and its result
  exists only on an unmerged branch. Treating that subjective classification as ground truth would
  benchmark agreement with an unaccepted model output, not correctness. It was removed from the
  harness after this check.
- Completed #433 is real but changed 76 files over roughly 12 hours. Six replays would risk measuring
  timeout/context exhaustion rather than a practical long ticket. #474 is the bounded middle.

## Frozen independent oracle

The oracle is copied verbatim from completed commit
`cb052ede731d0a0846a340b02b1992da549cf095`, while production starts from the earlier base. Its
bundle SHA-256 is:

`1c62094929224831801cf42bb314844159f8cd807e670a1457cdd348d3252002`

| immutable file | bytes | SHA-256 |
|---|---:|---|
| `tests/test_review_coverage_target_drift_474.py` | 22,002 | `f695776391570622324d096d4dc172ec4b19182db77f2edf393a8f24fe61d0fc` |
| `tests/test_merge_test_gate.py` | 42,122 | `34898df33f0fcdc956d12932610be6d2739ea1809ce2e59bfeb6e63fe6efedcd` |
| `tests/test_acceptance.py` | 25,070 | `40401ec8d20e40648e0d5f267ae426aa65b9db4a8bb6be1ac8b5734530a61416` |
| `tests/test_review_receipt_migration_436.py` | 4,160 | `442e87f027aadb38633361265d27c421765508f3a9dcdeb5a8be8a0cb372e0b9` |

Acceptance command, run by the harness after the model exits:

```bash
/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q \
  tests/test_review_coverage_target_drift_474.py \
  tests/test_merge_test_gate.py \
  tests/test_acceptance.py \
  tests/test_review_receipt_migration_436.py
```

A run is accepted only when the CLI returns 0, the command returns 0, the four scratch oracle hashes
match before/after, the frozen oracle bundle and source fixture hashes match before/after, the
computed USD cost is non-zero, and every changed non-cache path is one of the five production paths.
The model may read the tests but cannot replace them. The known completed production diff is a
positive control: exactly the five allowed files change and the command reports `65 passed`.

## Source-blind isolation

Each run gets a fresh `/tmp/astra505/run-<n>-<model>` export and a separate ephemeral Codex home
containing only a copied `auth.json` (no config, logs, memories, history, or sessions). The export is
not a git repository. `bwrap` mounts the scratch tree writable, mounts the test venv read-only, and
masks the entire live `/mnt/data/Projects/Python/orchestra` tree. A no-model preflight inside the
same namespace proved:

- the live repository, prior #474 report, and #505 oracle are unreachable;
- `.git` is absent;
- `CLAUDE.md` and generated `AGENTS.md` are byte-identical;
- the base `CLAUDE.md` contains zero literal `#474` matches;
- pytest 9.0.3 and Codex CLI 0.153.4 start successfully, and `codex login status` reports
  `Logged in using ChatGPT` from the minimal home;
- `codex debug prompt-input -c project_doc_max_bytes=262144` contains the complete 195,089-byte
  `AGENTS.md`, including its final 1,000 bytes;
- the frozen base archive hash is
  `ba17525a5475c46719e041e302e2a7f8fc58238088727d0a729adad7c022368c` before/after.

Every Codex command contains `--skip-git-repo-check --ignore-user-config --ephemeral`, fixed
`model_reasoning_effort=medium`, `project_doc_max_bytes=262144`, `approval_policy=never`, and
`workspace-write`. The explicit document cap reproduces Orchestra's full project instructions even
though the rest of user config is ignored. The `--ignore-user-config` flag prevents the machine's
`service_tier="fast"` from applying Astra's 2.5× Fast multiplier.

## Run order and captured fields

The fixed order is Astra/Sol/Astra/Sol/Astra/Sol, three runs per model. No model blocks. The harness
prints 1/5/15-minute `loadavg` at START and END of every run and stores both values. Each result row
contains:

- `cost_usd` plus the literal arithmetic;
- `input_tokens`, `cache_read_tokens`, `cache_create_tokens`, derived fresh input, `output_tokens`,
  and `reasoning_tokens`;
- CLI return, wall time, completed item counts, oracle output, changed paths, all hashes, and the
  final accepted boolean.

No quota or pool percentage is sampled anywhere.

## USD accounting

Standalone `codex exec` does **not** create an attributable Orchestra `turn_usage` row. The write is
inside `SessionTurns.handle_turn_end` → `turn_usage_add`, after an Orchestra session emits a terminal
event (`app/session_turns.py:332-375`, `app/db.py:3680-3750`). This harness invokes the CLI directly
outside SessionManager, so claiming a recorded row would be false. The harness therefore uses the
owner-authorized fallback and marks every row `cost_source="computed_vendor_card"`.

For every run:

```text
fresh = input_tokens - cache_read_tokens - cache_create_tokens
cost_usd = (fresh*input_rate + cache_read*cached_rate
            + cache_create*write_rate + output_tokens*output_rate) / 1,000,000
```

Rates in USD per 1M tokens are Astra `10 / 1 / 12.5 / 50` and Sol `4 / 0.4 / 5 / 20` for
fresh / cache-read / cache-create / output [1]. A regression check on #498 run 0 yields:

- Astra: `(9771*10 + 73984*1 + 0*12.5 + 325*50)/1e6 = $0.187944000`.
- Sol: `(10080*4 + 70656*0.4 + 0*5 + 567*20)/1e6 = $0.079922400`.

Before paid execution the harness also requires the exact Astra price row from #503 to exist in a
fresh process importing current main. The dependency changed during Phase 1: the first probe returned
`observed=None` and refused; after #503 landed, the same fresh-process probe returned
`{"cached":1.0,"input":10.0,"output":50.0,"write":12.5}` and passed. The refusal remains in the
harness, so a regression spends zero calls. A missing usage event or zero first-Astra cost is a void
run and aborts the experiment, never a cheap observation.

## Preregistered decision rule

Primary metric for each model:

```text
dollars_per_accepted_result = sum(cost_usd of all three attempts) / accepted_count
```

Failed attempts remain in the numerator. They are not made free by filtering them out.

The experiment answers the long-work question only if both models satisfy all three long thresholds
and both are 3/3 accepted. Then:

- **Astra better:** `max(Astra run USD) < min(Sol run USD)`.
- **Sol better:** `max(Sol run USD) < min(Astra run USD)`.
- **Depends / ranges overlap:** neither strict inequality holds. This is a closed, publishable
  outcome, not rounded into a winner.

If either model is below 3/3, any long threshold fails, a hash changes, a run is void, or the price
preflight fails, the harness publishes costs and failures but leaves #505 **open** rather than
changing the rule after seeing data.

If all accepted Astra runs again report `reasoning_tokens=0`, the harness runs the same high-effort
four-squares control that produced 2,588 reasoning tokens in #498. It reports that control and its
cost separately and excludes it from A/B economics. A zero is treated as real only if the channel
control is non-zero; otherwise the reasoning split is `UNCERTAIN` while total output/cost remains
the primary metric.

## Findings and confidence

| finding | confidence | basis |
|---|---|---|
| #474 is a real long Orchestra task, not a fabricated benchmark | **CONFIRMED** | Task Manager duration plus completed git diff (tier 1 measurements) |
| Frozen tests distinguish the pre-fix and completed implementations | **CONFIRMED** | 10 failed + 6 errors before; 65 passed after (tier 1) |
| The model cannot read the completed implementation or task report in the run namespace | **CONFIRMED for named paths** | bwrap positive/negative preflight (tier 1); arbitrary undiscovered side channels remain possible |
| Standalone runs cannot honestly use `turn_usage.cost_usd` | **CONFIRMED** | current writer path requires Orchestra terminal event; CLI is invoked directly (tier 2 source code) |
| The candidate will cross the preregistered long thresholds | **LIKELY, not measured** | historical task took 77.6 min and changed five production owners; the replay prompt is more closed and may finish faster |
| Astra will be cheaper | **UNCERTAIN** | the entire purpose of Phase 2; no paid result exists yet |

## Counter-evidence and risks

- The final #474 scope includes three defects discovered during the original work. The replay names
  all five up front, so it is more closed than history and may be faster. The thresholds prevent a
  fast replay from masquerading as long-work evidence.
- Visible acceptance tests expose intended behavior. That is the normal frozen-oracle contract and
  prevents subjective judging, but it reduces open-ended diagnosis. Both models receive identical
  exposure.
- The source snapshot predates current main. That is deliberate source blindness; it measures a real
  historical unit rather than today's unrelated concurrent edits.
- Exact 3/3 acceptance is conservative. A capability difference would be interesting, but with only
  three attempts it is not converted into a cost winner post hoc.
- Standalone USD is computed rather than written by `turn_usage`. The formula is byte-for-byte the
  same shape as `_codex_cost` (`app/backend_codex.py:204-217`) and each row publishes its arithmetic,
  but the result must be labelled computed.

## Affected files and phase boundary

Only `.orchestra/tasks/505/**` is changed. No `app/**`, production database, user config, quota
counter, or external service was mutated. The next approved experiment is the already-prepared paid
3+3 run; it does not start until the owner approves this exact #474 candidate.

## Review decision

- Changed artifact/consumers: this research design, frozen oracle, and harness; consumer is the
  owner's model-routing/spend decision.
- Author runtime: current Astra full-cycle session.
- AC: deterministic red/green controls, isolation preflight, frozen hashes, and the preregistered
  result rule above.
- Checks: pre-fix `10 failed, 49 passed, 6 errors`; completed control `65 passed`; bwrap preflight
  RC 0; harness dry-run says `paid_calls: 0`.

`codex-debate` would normally route a spend-affecting research conclusion to one Luna completeness
pass. The owner explicitly prohibited **any paid run** before approving the candidate, so no model
review was launched. This is recorded as `Review: none — paid-review prohibited before candidate
approval`; the mechanical controls above are the Phase 1 gate. No Sol reviewer was authorized.

The required KB promotion is also not written: the owner limited territory to
`.orchestra/tasks/505/` only. The finding remains in this task artifact until an owner with KB
territory promotes it.

## Sources

1. `.orchestra/tasks/498/research.md` — #498 measured token mix, rates, Fast-mode trap, and reasoning
   channel control; merged source read in full (tier 1 measurements + vendor primary sources).
2. Orchestra Task Manager `task_get(474)` — created/completed timestamps, done status, and completed
   commit statistics (tier 1 project state).
3. Git objects `bf59a7d3`, `cb052ede`; `git diff --numstat` and `git show` — source and accepted fix
   identity (tier 1 repository state).
4. `.orchestra/tasks/505/run_ab.py` dry-run and scratch controls — red/green oracle, bwrap isolation,
   hashes, and cost arithmetic (tier 1 direct measurements).
5. `app/backend_codex.py:204-217`, `app/session_turns.py:332-375`, `app/db.py:3680-3750` — cost formula
   and the only `turn_usage` persistence path relevant here (tier 2 primary source code).

## Re-preregistration: open assignment after the closed variant was too short

The approved first assignment named all five defects and all five production files. Astra completed
it correctly, but in **154.955 seconds / 10 tool items / 3,785 output tokens**. The oracle was
untouched and reported `65 passed in 8.52s`; exactly the five expected production files changed.
Cost was `$1.659628`. This is a valid closed-work capability result, but it failed the frozen wall
and output-token thresholds and therefore did not enter the long-work A/B.

The owner approved one re-preregistration on 2026-09-05. The only model-facing change is
`candidate_task.md`: it now says only that the same frozen 65-test suite is red and must be made
green. It does not name defects, target production files, behavior changes, or an implementation
outline. The new assignment SHA-256 is
`de11c6f430de30e5d718dbeddf321e2dbe085ac25a15f84da0bf13c10161d93d` and is checked before every
continued run.

Everything else remains frozen: base commit `bf59a7d3`, oracle bundle
`1c62094929224831801cf42bb314844159f8cd807e670a1457cdd348d3252002`, outer source-blind bwrap,
`--ignore-user-config`, `medium`, 262,144-byte project-doc cap, Astra/Sol interleaving, dollar
formula, 3+3 target, winner/overlap rule, and thresholds 180 s / 8 tool items / 5,000 output tokens.
If the open Astra run 1 misses any threshold, the batch stops again.

Two earlier Astra calls stay permanently in the ledger but are excluded from the newly
preregistered A/B numerator and ranges:

| excluded variant | accepted | wall | output | cost | reason |
|---|---:|---:|---:|---:|---|
| nested-sandbox attempt | no | 33.656 s | 339 | `$0.716476` | harness prevented both commands from starting |
| fully specified assignment | yes | 154.955 s | 3,785 | `$1.659628` | valid closed-work result; not long |
| **experiment overhead** |  |  |  | **`$2.376104`** | reported separately from open A/B |

The harness defect is closed by retaining the outer bwrap and passing Codex
`--dangerously-bypass-approvals-and-sandbox`, the CLI's mode for already externally sandboxed
automation. A no-model final-namespace preflight produced `SHELL_OK`, actual read/rewrite/cmp on all
five production files (`PRODUCTION_WRITABLE=5/5`), the exact baseline oracle result
`10 failed, 49 passed, 6 errors in 8.17s`, and `BLINDNESS_OK`; the live repository and `.git`
remained unreachable.
