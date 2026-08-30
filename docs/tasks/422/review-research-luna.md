<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently, 34/51 “promotions” is already effectiveness—provided we leave the denominator and outcome metric elsewhere 🙃

## Summary

Phase 1 is not ready for acceptance: two safety boundaries are overstated, and the replay protocol lacks a fully preregistered estimand, budget, and decision rule. The C2 catalog itself matches the current OpenRouter response: 18 exact `:free` routes, 17 eligible.[OpenRouter models endpoint](https://openrouter.ai/api/v1/models)

## Findings (blocking/suggestion/question)

### blocking — [docs/tasks/422/research.md:43-47](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-auto-work/docs/tasks/422/research.md:43)

The report says `CLAUDE.md` changes require separate approval, but the cited current prompt explicitly allows orchestrators to write project `CLAUDE.md` on their own decision. The scheduler sends normal messages with normal agent rights, so this is an autonomous write path. Narrow the claim to canonical KB links or reconcile the role-specific exception; the current “candidate/evidence ceiling” is false.

### suggestion — [docs/tasks/422/research.md:77-83](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-auto-work/docs/tasks/422/research.md:77)

The inventory is not fully exact for `timer`: `app/bg_jobs.py:419-420` has a separate `wake_subscription_limited` execution path, and `delay_seconds` is not capped even though the timer lifetime is capped at eight days. State whether A1 covers only the agent-facing `bg_create` API or all `bg_jobs.py` behavior, then document these cases.

### suggestion — [docs/tasks/422/research.md:81](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-auto-work/docs/tasks/422/research.md:81)

`run` does not wake the target on every failure. Its generic exception path at `app/bg_jobs.py:1027-1028` only marks the job failed; notification exists for nonzero exit, timeout, and validation failures. Qualify the table as “known exit/timeout failures” or record the silent exception path.

### suggestion — [docs/tasks/422/research.md:85-88](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-auto-work/docs/tasks/422/research.md:85)

“Maximum 50 active jobs” is not a hard invariant: `create()` checks the count before saving, and concurrent calls can pass the check independently. `replace_key` also deliberately bypasses the count gate. Describe this as an admission check unless atomic enforcement is demonstrated.

### suggestion — [docs/tasks/422/research.md:143-167](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-auto-work/docs/tasks/422/research.md:143)

The `53→51→34` and `8/9/2/4` chains are not reproducible from the artifact: only two normalization examples are shown, and there is no complete proposal-to-triage mapping. The totals cover different cohorts—51 proposals, 47 triage records, and 23 post-trigger records, of which only 19 have verdicts. Add the full frozen ledger and denominator definitions; otherwise this measures traceable throughput, not self-improvement effectiveness.

### suggestion — [docs/tasks/422/research.md:218-223](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-auto-work/docs/tasks/422/research.md:218)

The three #417 branches are priced only qualitatively (“minimal blast radius”, “more storage”, “maximum blast radius”). Add comparable units such as LLM rounds, wall time, storage/worktree cost, human approval time, and rollback exposure, or explicitly mark the prices as unmeasured.

### blocking — [docs/tasks/422/research.md:327-343](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-auto-work/docs/tasks/422/research.md:327)

“Ordinary tools” plus an external model is not an isolation protocol. `HarnessBackend` merges MCP and built-in tools, while the replay specifies no isolated SQLite, credential scrub, MCP denylist, network policy, or output redaction. “No production/external side effect” is only a post-run success condition; a failed run could already mutate production or expose private data.

### suggestion — [docs/tasks/422/research.md:327-332](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-auto-work/docs/tasks/422/research.md:327)

`git cat-file -e <solution_sha>` proves only that the solution is absent at startup. With ordinary Git/network access, the agent can fetch the remote or otherwise retrieve the solution later. Remove remotes, disable network fetches, or add a post-run object/reachability audit.

### suggestion — [docs/tasks/422/research.md:320-323](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-auto-work/docs/tasks/422/research.md:320)

The `720 + 108` budget counts logical rounds, not provider attempts. `app/harness/llm.py:206-254` retries each request up to three times and records every attempt, so the theoretical maximum is 2,484 attempts before controls. The live account tier is also unknown; OpenRouter documents free-model caps as account/model-dependent rate limits.[Limits documentation](https://openrouter.ai/docs/api_reference/limits)

### suggestion — [docs/tasks/422/research.md:309-317](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-auto-work/docs/tasks/422/research.md:309)

The protocol does not define a lane-level pass/fail threshold or confidence rule, yet claims `N=30` can reject “everything/nothing”. Selecting three routes after the pilot also makes the estimate conditional on an unspecified selected subset. Freeze the route-selection algorithm, estimand, uncertainty method, and falsification threshold before any model response.

## Verdict

**Overall correctness:** ❌ Incorrect for acceptance
**Confidence:** 0.98

The research is directionally useful and correctly identifies several unknowns, but the approval claim and replay safety boundary require correction before this can serve as an architecture-decision artifact. No implementation was proposed or authorized, and no files were edited.

The replay currently looks like a “free” buffet where the bill, bouncer, and exit door are all still theoretical.

## Wrapper recovery note

The wrapper returned `review artifact is blind: execution never happened`, but the reviewer produced the
substantive findings and verdict above. Full text was recovered from
`/tmp/codex_review_research-auto-work_review-research-luna.jsonl`; this counts as Round 1.
Both blocking findings were verified against current code/prompts and accepted for correction.

## Round (2026-08-30T12:28:04Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently, the replay now has a budget, isolation, and thresholds—one control is still hiding in the footnotes 🙃

## Summary

Round 1 findings are fixed or correctly narrowed; no blocking issue remains. I found five non-blocking prose/methodology follow-ups.

Prior status: candidate boundary, replay isolation, scheduler semantics, 53→51→34 ledger, branch pricing, retry budget, blindness checks, and route estimand/thresholds — **FIXED**.

## Findings (blocking/suggestion/question)

### STILL BROKEN — suggestion — docs/tasks/422/research.md:50-57

`LIKELY for quality of filter` is still too strong. The evidence shows a changed verdict mix, not improved correctness: no ground-truth outcome exists, cohorts are not joined, and the same section says causality is unproven. Label the distribution shift as `CONFIRMED` and filter quality as `UNCERTAIN`.

### NEW — suggestion — docs/tasks/422/research.md:315-327

The weighted estimand still lacks an operational population definition: scope is unspecified, and the five strata have no mutually exclusive classifier or precedence rule. A task can fit both “closed leaf code fix” and “high-risk boundary”, changing both sampling and weights. Freeze scope and classification rules.

### NEW — question — docs/tasks/422/research.md:344-348,400-408

The budget says the listed controls require no model calls, but the false-premise control requires model behavior producing `WIP/STOP`. Clarify that those two tasks are included in the 30-ticket matrix and count both route attempts, or add their calls to the budget.

### NEW — suggestion — docs/kb/auto-work.md:15

The KB says retro had “0 consumers”, while the research evidence establishes only “0 working reads” in the measured channel. Narrow the claim to the observed project/agent channels; otherwise it overstates what the measurement proves.

### NEW — suggestion — docs/tasks/422/research.md:279-307

The exact route list is present, but the evidence is only a dated live query with an ellipsized `jq` command. Without a raw-response snapshot, timestamp, or hash, the mutable endpoint cannot substantiate the historical 18/17 catalog claim. Preserve a frozen response digest or equivalent evidence.

> “N=30 — screening, не точная оценка: шесть наблюдений на stratum дают широкие интервалы.”

## Verdict

**Overall correctness:** ✅ Correct, no blocking findings.
The requested Round 1 corrections are reflected in the prose and ledger; remaining issues affect calibration and reproducibility, not safety or implementation authorization.

Эксперимент уже пристёгнут ремнём безопасности — осталось перестать называть показания спидометра доказательством качества.

## Author close-out after Round 2

Applied all five non-blocking follow-ups: filter quality is `UNCERTAIN`; population scope and
mutually-exclusive stratum precedence are frozen; false-premise cases are inside N=30/budget;
retro claims are narrowed to measured project-agent channels; the live catalog has a timestamped,
hashed normalized snapshot in `docs/tasks/422/openrouter-free-catalog.tsv`.
No Round 3 was requested: the prose ceiling is two rounds.
