# #386 — Whole-file merge tests versus vertical tickets

Date: 2026-08-24. Phase: research only. No application code, repository tests, provider calls, or
live merge was changed or invoked.

## Question

- **Context:** Orchestra runs an orchestrator-owned ticket acceptance command and then a
  file-mapped pytest subset before `merge_worker`. A Phase-2 branch can contain frozen RED tests
  for several future tickets while a child branch implements one vertical ticket.
- **Change under test:** make the regression gate reason about the actual merge target without
  choosing a final implementation mechanism in this phase.
- **Baseline:** the current gate diffs every worker against local `main`/`master`, selects entire
  test files, and fails on any non-zero pytest run.
- **Outcome:** a valid current ticket must be mergeable into a nested integration target while a
  new regression outside that ticket, an oracle mutation, an incomplete run, or a RED result bound
  for `main` must still block. Wall-clock and failure-set noise must be measured rather than
  assumed.

## Hypotheses considered and falsifiers

### H1 — the reproduced #380 rejection is primarily a wrong-base selection bug

**Hypothesis.** The gate selects #380's frozen multi-ticket file only because it compares the T1
candidate with `main`; comparing changed paths with the requested nested target removes that
unchanged file while retaining mapped regressions for the app files changed by T1.

**Falsifier.** `tests/test_message_delivery_receipts_380.py` remains selected when the exact target
commit `826e551b` is the diff base, or the candidate changed that file relative to the target.

### H2 — target-versus-candidate failure-set subtraction is a general safe answer

**Hypothesis.** Run the same mapped selection on target and candidate and allow the candidate when
its failure identities are a subset of the target's.

**Falsifier.** A candidate introduces a different failure or a timeout at a node that was already
RED on target, but a nodeid-only set still reports “no new failures”; alternatively, a strict
failure fingerprint rejects legitimate progress through the same future-ticket test. #380
produced both sides of this falsifier in one local run.

### H3 — per-ticket selectors/metadata are sufficient

**Hypothesis.** The orchestrator-owned `-k 'test_t380_r1_'` command proves the vertical slice and
can replace the whole-file gate.

**Falsifier.** A candidate makes R1 green and introduces a failure in a mapped non-R1 test. The R1
selector stays green, so selector-only admission hides the regression.

### H4 — merge only after the final ticket

**Hypothesis.** Keeping every ticket in one long-lived branch until the whole frozen file is green
avoids any gate change.

**Falsifier.** The workflow requires independently mergeable vertical tickets, target-branch
checkpoints, or per-ticket executor isolation; final-only integration removes all three even if the
last merge is safe.

## Current code and contracts

1. `changed_paths()` resolves only `main`, then `master`, and runs
   `git diff --name-only <base>...HEAD`; it receives no requested merge target [1].
2. `select_tests()` selects `tests/test_<app stem>.py`, the route surface test, and **every changed
   `tests/test_*.py` as a whole file**. It has no node selector or ticket metadata [1].
3. Pytest is deliberately invoked without `-x`; on ordinary completion any non-zero exit other
   than “nothing collected” is `FAILED`. On an outer timeout, any already-printed `FAILED`/`ERROR`
   node also makes the run `FAILED`; only a timeout with no printed failure is `INCONCLUSIVE` [1].
4. The ticket acceptance command runs first. It is read from the session's server-side task row,
   and the ordinary worker MCP role cannot set it; only orchestrator/sub-orchestrator roles may
   supply `acceptance_command` through that path [2][3]. However, “server-owned” does **not** mean
   “required or immutable”: an empty command returns `SKIPPED`, `merge_operations` blocks only
   `FAILED`/`INCONCLUSIVE`, and the command executes candidate-side tests/config without comparing
   them with the frozen target [2][3]. The source comments also correctly say this is not a security
   boundary against a worker with arbitrary shell/DB/code access [3].
5. Only after both gates pass does `merge_operations` forward
   `request.target or accepted_base_branch` to merge execution. The test gate call itself receives
   only the worker worktree path [2].
6. Merge execution resolves the target under `repo_mutation_lock`, but its public contract pins
   worker branch/head only; it has no expected target commit parameter [9]. Therefore any cached or
   freshly measured target baseline needs a target-head compare at the mutation boundary, or the
   tested target and merged target can differ.
7. The regression gate also treats an empty map and an all-`live_probe` deselection as `SKIPPED`,
   and `merge_operations` permits that status [1][2]. A safe intentionally-RED workflow therefore
   cannot infer oracle coverage merely from “neither gate failed”; it needs positive evidence that
   its required frozen ticket oracle actually ran and passed.

**Confidence: CONFIRMED.** These are direct current-source observations (evidence tier 2, primary
source) plus the local reproduction below (tier 1).

## Deterministic local reproduction from #380

### Frozen topology

- `main` and this research branch: `71374ea5`.
- Nested #380 target: `826e551b` (`task-380/fix-send-message-receipt`).
- Frozen RED oracle: `c42163d9`.
- T1 candidate: `4e5cb061`.
- The oracle blob is byte-identical in the RED commit, target, and candidate:

```text
$ git diff --quiet 826e551b 4e5cb061 -- tests/test_message_delivery_receipts_380.py
oracle_diff_rc=0
$ git rev-parse 826e551b:tests/test_message_delivery_receipts_380.py \
    4e5cb061:tests/test_message_delivery_receipts_380.py \
    c42163d9:tests/test_message_delivery_receipts_380.py
eb354ed60a5fd3bf3a2d024c4cd14f9a9c581b63
eb354ed60a5fd3bf3a2d024c4cd14f9a9c581b63
eb354ed60a5fd3bf3a2d024c4cd14f9a9c581b63
```

The commits were exported with `git archive` into isolated directories under `/tmp`; the exact
project runtime ran pytest 9.0.3 with `PYTHONDONTWRITEBYTECODE=1`. No provider or live merge path
was reachable.

### Why the current map selects the future RED file

The current `select_tests()` was called with the two measured Git path lists against the exported
candidate tree:

```text
main-to-candidate changed_count 9
changed ['app/db.py', 'app/manager.py', 'app/message_deliveries.py',
         'app/routes/sessions.py', 'docs/tasks/380/plan.md',
         'docs/tasks/380/research.md', 'docs/tasks/380/review-plan.md',
         'docs/workers/impl380-t1.md',
         'tests/test_message_delivery_receipts_380.py']
mapped ['tests/test_db.py', 'tests/test_manager.py',
        'tests/test_message_delivery_receipts_380.py',
        'tests/test_routes_surface.py']

target-to-candidate changed_count 5
changed ['app/db.py', 'app/manager.py', 'app/message_deliveries.py',
         'app/routes/sessions.py', 'docs/workers/impl380-t1.md']
mapped ['tests/test_db.py', 'tests/test_manager.py',
        'tests/test_routes_surface.py']
```

The whole frozen file is not a T1 change. It enters the current gate solely through
`main...candidate`; it disappears under `target...candidate`. H1 survives its falsifier.

### The slice is green under its frozen ticket oracle

Exact selector runs:

```text
target 826e551b:
exit 1; elapsed=15.56 s; maxrss_kb=151444
5 failed, 17 deselected in 11.39s

candidate 4e5cb061:
exit 0; elapsed=17.89 s; maxrss_kb=148628
.....                                                                    [100%]
5 passed, 17 deselected in 13.40s
```

This is the vertical-ticket fact: all five frozen R1 cases turn RED→green without changing the
oracle file [4].

### The whole file still rejects it

A 30-second cap was passed to the current `run_pytest()` helper to make the experiment bounded.
The target and candidate were alternated twice. The candidate result was identical in both runs:

```text
status=failed reason=timeout_with_failures
failed_count=13 passed_count=7
stopped_in=tests/test_message_delivery_receipts_380.py::test_t380_r7_claude_compact_completion_wakes_durable_receipt
```

The target failure set contained all 22 nodeids; the candidate's 13 printed failures were a strict
subset, and the exact candidate set repeated 2/2:

```text
candidate_failure_sets_equal True count 13 symmetric_diff []
candidate_minus_target []
target_minus_candidate_count 9
candidate_failed_subset_target True
target_count 22 candidate_count 13
target_failure_sets_equal True first 22 second 22 symmetric_diff []
```

Current policy rejects immediately because the candidate is non-zero. A nodeid-only differential
would instead say “no new failures” even though the candidate run is incomplete and stopped inside
one of those previously RED nodes. That is direct counter-evidence against H2's *safe* form.

The failure cause also changed under a stable nodeid. On target, R2 failed at
`app.message_deliveries does not exist`; on the candidate the same R2 nodeid reached the new module
and failed at `#380 keyed running steer never reached backend`. Ignoring the failure payload admits
an arbitrary new defect at the same node; including the payload makes legitimate progressive RED
tests appear new. This ambiguity is intrinsic to failure-set subtraction, not a terminal-output
parser bug.

**Confidence: CONFIRMED.** Git object identity, selector output, full-file nodeids, and repeated
bounded results are direct measurements (tier 1).

## Exact failure identity

Pytest's public protocol emits a report for setup, call, and teardown, and collection has a
separate `CollectReport`; `pytest_runtest_logstart` exposes the full nodeid before an item runs [5].
Nodeids are rooted at pytest's `rootdir` and include path, class/function, and parametrization [8].
The comparison contract therefore needs two levels:

| Event | Stable comparison key | Diagnostic fingerprint | Admission rule |
|---|---|---|---|
| Assertion/exception in test body | `("test", normalized_nodeid, "call")` | exception class, normalized crash location, normalized `longrepr` digest | New key blocks. Changed fingerprint at an existing key is **uncertain**, not automatically pre-existing. |
| Setup error | `("test", normalized_nodeid, "setup")` | same fields | Distinct from call failure; new/changed blocks or is uncertain. |
| Teardown error | `("test", normalized_nodeid, "teardown")` | same fields | Distinct because a call can pass and teardown can still error. |
| Collection error | `("collect", normalized_collector_nodeid)` | exception class/location/`longrepr` digest | Record for diagnosis, but do not allow a merge from a baseline or candidate with collection failure: pytest normally does not enter the run loop after collection failure [5]. |
| Outer timeout during an item | `("timeout", normalized_active_nodeid)` from logstart without logfinish | completed report set plus stopped node | Diagnostic only; candidate is incomplete and must be `INCONCLUSIVE` even if earlier RED nodeids are all baseline-known. |
| Outer timeout during collection/session startup | `("timeout", "collection" | "session")` | selected paths and last collector/event | Diagnostic only; never subtract as an allowed baseline failure. |
| Pytest internal/usage/interrupted/no-tests | no test failure identity | public exit status plus stderr | Exit 2/3/4 is inconclusive; exit 5 retains the current explicit “no tests after deselect” treatment; exit 0 is complete green; exit 1 is complete only when structured reports and session finish were captured [6]. |

`normalized_nodeid` means the same forced root/config on both trees, path separators normalized to
`/`, and no removal of parametrization. Target and candidate must use the same interpreter, plugin
set, marker expression, ordered selected paths, and environment contract. XFAIL/SKIP are not
failures; strict XPASS is represented by pytest as a failing report and follows the phase rule.

Terminal regex is adequate for today's timeout diagnostics but insufficient for a general
differential: ordinary `run_pytest()` truncates output to 4,000 characters and does not return
failure nodeids on completed exit 1 [1]. A future experiment would need structured pytest reports;
this is a requirement, not a prescription of where that collector lives.

**Confidence: CONFIRMED** for phases/nodeids/exit meanings (pytest primary documentation and
installed pytest 9.0.3); **LIKELY** for the proposed normalization boundary, because no production
implementation was built.

## Cost, noise, caching, and invalidation

### Measured wall-clock

All times are `/usr/bin/time` elapsed seconds; load is `/proc/loadavg` immediately before each run.

| Run | Load before | Target | Candidate | Pair cost | Result identity |
|---|---:|---:|---:|---:|---|
| target pilot | 2.05 | 26.30 | — | — | complete, 22 failed |
| bounded pair 1 | 1.60 / 1.89 | 28.84 | 30.22 | 59.06 | target complete 22; candidate timeout 13 failed/7 passed |
| bounded pair 2 | 2.20 / 2.26 | 30.24 | 30.25 | 60.49 | target timed out after printing the same 22; candidate repeated the same 13/7/stopped node |
| R1 selector pair | 1.31 / 1.60 | 15.56 | 17.89 | 33.45 | target 5 failed; candidate 5 passed |

The bounded pair cost varied by 1.43 s (2.4% of the 59.78 s mean), but the 30-second decision
boundary changed the target classification from complete to timed out under higher load. Failure
sets were stable 2/2 on each tree. This is enough to show both facts: identities can be stable while
completion status is noisy at the budget edge.

The production budgets are larger: one mapped file gets 330 s, the correct target-relative #380
map of three files gets 630 s, and the current erroneous four-file map gets 780 s [1]. A naive
target+candidate double run therefore has a worst-case budget of 1,260 s or 1,560 s respectively,
before the separate ticket acceptance command. Baseline caching can amortize this, but it cannot be
the built-in `.pytest_cache`.

### Exact replay commands

The following is the recorded local protocol, with `TMP` standing for the path printed by
`mktemp`. It exports tracked objects only, captures load beside each measurement, and invokes the
same current helper used for the bounded full-file verdict:

```bash
TMP=$(mktemp -d /tmp/task386.XXXXXX)
mkdir -p "$TMP/target" "$TMP/candidate"
git archive 826e551b app tests pyproject.toml | tar -x -C "$TMP/target"
git archive 4e5cb061 app tests pyproject.toml | tar -x -C "$TMP/candidate"

R=/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python
for side in target candidate; do
  cd "$TMP/$side"
  printf '%s load_before=%s\n' "$side" "$(cat /proc/loadavg)"
  /usr/bin/time -f 'elapsed=%e user=%U sys=%S maxrss_kb=%M' \
    -o "$TMP/$side.time" \
    env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$TMP/$side" \
    "$R" -c "import json; from app.merge_test_gate import run_pytest; print(json.dumps(run_pytest('$TMP/$side',['tests/test_message_delivery_receipts_380.py'],timeout=30), sort_keys=True))" \
    > "$TMP/$side.out" 2>&1
  printf '%s load_after=%s\n' "$side" "$(cat /proc/loadavg)"
  cat "$TMP/$side.time"
done
```

The ticket-selector pair used the same exports/runtime and these exact pytest arguments:

```bash
env PYTHONDONTWRITEBYTECODE=1 "$R" -m pytest -q \
  tests/test_message_delivery_receipts_380.py -k 'test_t380_r1_'
```

The target/candidate path-map input was produced by:

```bash
git diff --name-only main...4e5cb061
git diff --name-only 826e551b...4e5cb061
```

### What pytest caching does and does not do

The current argv does not pass `--lf`, `--ff`, or `--nf`. Pytest's cache provider records
`lastfailed` and nodeids, but it only filters/reorders execution when those options activate the
corresponding plugins [7]. Repeated ordinary runs still executed every selected test. In the local
runs, warming `.pytest_cache` did not overcome load noise (target elapsed 26.30 → 28.84 → 30.24 s).

A reusable **baseline-result** cache would need the entire invocation as its unit; per-file caching
is unsafe in the presence of session fixtures, ordering, and shared process state. The minimum cache
key/invalidation contract is:

1. repository identity and exact target commit SHA (not branch name);
2. exact ordered selected paths/node selectors, pytest argv/marker expression, root/config,
   batching partition, total budget, and per-batch timeout allocation policy;
3. interpreter/runtime fingerprint and plugin/dependency lock identity;
4. relevant environment/config fingerprint, or no reuse across process/environment changes;
5. no dirty/untracked target inputs; target SHA change invalidates unconditionally;
6. cache only a completed structured run; collection/internal/usage/timeout results are never
   allowlists;
7. compare the pinned target SHA again inside the repository mutation lock before merge; mismatch
   discards the verdict and restarts the gate.

A red baseline also needs a stability policy. Requiring the same baseline identity/fingerprint on
two runs reduces flake risk but turns the first cache fill into two baseline runs plus one candidate
run. The #380 nodeid sets repeated 2/2, but that sample does not establish a general flake rate.

**Confidence: CONFIRMED** for measured cost and native pytest cache semantics; **LIKELY** for cache
key sufficiency because environment-dependent tests can always reveal another untracked input.

## Comparison of the approaches

| Approach | #380 nested target | New-regression protection | Main target | Cost / complexity | Verdict |
|---|---|---|---|---|---|
| Target-vs-candidate failure-set diff | Nodeid-only would accept 13 ⊂ 22, but would also ignore the observed timeout and changed R2 failure cause. A strict identity would reject this candidate. | Safe only with structured complete runs, changed-fingerprint handling, target pinning, and a trusted baseline. Same-node masking is otherwise real. | Candidate-added future RED tests have no target identity and must remain new/blocking. Existing RED main would become policy debt if allowlisted. | Usually ~2×; cache/TOCTOU/flake handling is substantial. | Not the smallest safe first move. Preserve as a later extension if red target-mapped files remain a demonstrated need. |
| Per-ticket selectors / metadata | Existing orchestrator-owned R1 selector proves the slice (`5 passed`). Combined with target-relative regression mapping, it removes the reproduced false rejection. | Selector alone is insufficient. Current acceptance may be empty/`SKIPPED`, and candidate-side test/config inputs are not frozen. Candidate/worker-selected `-k`, markers, or file lists must never define the regression set. | A selector must not authorize landing other RED tests into main. | Command storage already exists; positive-presence and frozen-input enforcement do not. | Keep as ticket oracle only after it is required, pinned, and its inputs are verified. |
| Final-only merge workaround | Avoids the intermediate rejection by waiting until R1–R7 are all green. | Strong at the final boundary, but regressions are discovered late. | Naturally keeps main green. | No gate code; loses vertical checkpoints, independent ticket executors, small diffs, and per-ticket merge evidence. | Safe emergency workaround, not the desired workflow. |
| Exact-target changed-path selection + required frozen ticket oracle | Removes the unchanged frozen #380 file from the nested candidate map while still running db/manager/route regressions and R1 acceptance. | Candidate-only mapped regressions still fail on any new red; positive oracle presence/pass plus byte-identical test/fixture/config/selection inputs prevent a candidate-side skip or weakening. Needs target-head pin/CAS. | `main...candidate` remains unchanged for main; candidate-added RED stays blocking. | No baseline double run; adds fail-closed oracle verification because current acceptance alone is insufficient. | Smallest safe approach supported by current evidence. |

## Protection against hidden regressions and worker-selected subsets

Any later plan should preserve these invariants:

1. Resolve the operation's effective target (`request.target` or accepted base), then pin its commit
   before selection. `main` is merely one possible target, not the default truth for nested merges.
2. The platform, not worker branch content, owns both the ticket acceptance argv and regression
   selection. A branch marker such as `future_ticket` or a worker-supplied `-k` is advisory at best.
3. For a behavioral ticket using the intentionally-RED nested-target workflow, a non-empty
   server-owned acceptance command is required and must be pinned with the accepted operation
   snapshot. `SKIPPED/no_command`, an empty selection, or a command changed after the snapshot is
   not admission evidence.
4. Freeze every ticket oracle before implementation. For #380 the target/candidate/RED blob equality
   above is the model. Before execution, verify byte identity for every named test, fixture/helper,
   `conftest.py`, pytest config, marker, and selection input against the frozen target/RED manifest.
   Any mismatch blocks unless the task giver explicitly re-freezes and starts a new operation.
5. Run the exact pinned ticket selector and the target-relative mapped regression set. Require a
   positive `PASSED` ticket result; a green selector cannot waive a new mapped failure outside it.
   A `SKIPPED` mapped result cannot authorize this special workflow without separate positive
   regression evidence; fall back to final-only/operator disposition rather than infer safety.
6. Candidate collection error, internal/usage error, timeout, or unreached selected file is
   inconclusive even when every printed failure existed on target.
7. Re-check target SHA under the same repository mutation lock used by merge. A moved target means
   the evidence is stale, not “close enough”.
8. `main` must not acquire intentionally RED future-ticket tests. Use a nested integration target
   for the frozen multi-ticket oracle, or use the final-only workaround.

## Smallest safe recommendation

Do **not** begin with a general failure allowlist. The reproduced defect can be removed more narrowly:

1. make the merge test gate consume the operation's exact effective target rather than discover
   `main`/`master` itself;
2. derive changed paths and mapped regression files from that pinned target commit to candidate;
3. for this behavioral workflow, require a non-empty server-owned acceptance command pinned in the
   operation snapshot, plus a frozen manifest whose test/fixture/helper/`conftest.py`/pytest-config/
   selection inputs must match the candidate byte-for-byte before execution;
4. require positive `PASSED` evidence from that exact ticket oracle; `SKIPPED`, empty selection, or
   an input mismatch blocks rather than falling through to merge;
5. require the target commit to remain unchanged through the merge mutation boundary;
6. preserve current fail-closed behavior for any candidate RED/incomplete mapped run and for main,
   and do not treat a skipped mapped run as sufficient evidence for this special workflow.

This recommendation does not choose the eventual parameter/storage/API shape. It states the
smallest **admission contract** that explains and fixes the measured #380 false rejection without
trusting the candidate's oracle copy. Add failure-set differencing only after a real target-relative
mapped file remains pre-RED and cannot be separated by frozen server-owned ticket metadata.

### Recommendation falsifiers

- With the exact nested target pinned, the unchanged shared oracle is still selected.
- A changed app module maps to the same pre-RED whole file on the target; target-relative selection
  alone still rejects a valid ticket. This would justify researching structured differential or
  server-owned expected-RED metadata next.
- A candidate changes a non-ticket mapped behavior and the combined acceptance+regression gates
  pass.
- A candidate mutates the frozen oracle and passes.
- A behavioral ticket has no acceptance command, produces `SKIPPED`, or changes a frozen
  test/fixture/config/selection input and still passes.
- The target advances after test completion and merge still commits without re-running.
- A timeout, collection error, or empty worker-selected subset produces an allowed merge.
- A main-target candidate can land intentionally RED future tests.

## RED oracle design for Phase 2

No RED test is written in Phase 1. The Phase-2 oracle should use a real temporary Git repository,
not mocks of `git diff`, with this graph:

```text
main M ── target I (adds frozen T1+T2 RED file) ── candidate C (implements T1 only)
```

Required assertions:

1. current behavior is demonstrably RED: when target `I` is requested, the gate selects as if from
   `M` and reaches the untouched T1+T2 file;
2. desired nested behavior: target-relative changed paths exclude that unchanged oracle, the exact
   server-owned T1 command is green, and a mapped non-ticket regression still blocks;
3. main control: the same candidate shape targeting `M` still selects/rejects candidate-added RED;
4. target-move control: advance `I` after the verdict and before the mutation boundary; merge must
   stop and require a fresh verdict;
5. oracle-mutation control: change a frozen test/fixture/config in `C`; admission must stop;
6. incomplete controls: call failure, setup error, teardown error, collection error, and an active
   timeout must remain distinct; timeout/collection cannot be subtracted into success;
7. subset attack control: a candidate marker or `-k` that omits a new mapped regression must not
   affect the platform-selected regression set.

Mutation checks should at minimum hardcode `main`, remove the target-head compare, trust a
candidate selector, and ignore a mapped regression. Each mutation must make the named RED oracle
fail for the missing behavior, then the unmodified implementation must return green.

## Counter-evidence, risks, and gaps

- The T1 selector is green, but the partially implemented candidate makes later future tests reach
  deeper behavior and eventually times out. Therefore “all whole-file reds are harmless
  pre-existing failures” is **REFUTED**. Only the narrower statement “the R1 slice satisfies its
  frozen R1 oracle” is confirmed.
- The current server-side task row owns the acceptance string but does not require it and does not
  freeze its candidate-side inputs. Therefore the earlier draft's “existing two gates” wording as a
  complete safety contract was **REFUTED** by direct code inspection and adversarial review.
- Target-relative selection happens to remove the shared #380 file because its name is not the
  stem-map for `app/message_deliveries.py`. A future suite may put multiple tickets in a mapped
  `tests/test_<stem>.py`; that is the explicit falsifier for the narrow recommendation.
- The full four-file mapped command was not run: its production budget is 780 s and it includes
  heavyweight `tests/test_manager.py`. The reproduction isolates the disputed file and uses the
  exact selector/mapping code; the remaining mapped files are a Phase-2 regression concern.
- The current target branch can move between gate and merge. Any baseline cache or target-aware
  selection without target-head compare is a TOCTOU regression.
- A candidate with arbitrary shell access can rewrite platform code or DB state. This research
  preserves the current trust model; it does not claim a security boundary against a malicious
  local Unix user.
- No docs/kb topic was changed because this worker's ownership is limited to
  `docs/tasks/386/` and its personal-memory path. The orchestrator was notified before completion.

## Affected files for a possible later plan

- `app/merge_test_gate.py` — target-aware changed paths, selection/evidence contract.
- `app/merge_operations.py` — pass/pin the effective target into the gate.
- `app/workspace.py` and/or merge execution boundary — compare the expected target head under the
  mutation lock.
- `tests/test_merge_test_gate.py` — real nested-target, main, target-move, timeout/collection, and
  subset-attack oracles.
- `app/acceptance.py`, task/operation metadata, and `app/mcp_stdio.py` are current contract
  dependencies. The evidence requires fail-closed oracle presence/pinning/immutability somewhere
  in this boundary, but Phase 1 does not choose which file or storage shape owns it.

## Findings and confidence summary

1. **CONFIRMED:** #380's whole-file rejection is caused by `main...candidate` selecting an oracle
   file unchanged from the requested nested target. Direct Git/map measurement.
2. **CONFIRMED:** T1 is green under its frozen server-owned selector (`5 passed`) while the full
   file remains non-zero. Direct pytest measurement.
3. **REFUTED:** nodeid-subset comparison alone safely distinguishes regressions. It would accept
   the measured 13⊂22 set despite an incomplete timeout and changed same-node failure cause.
4. **CONFIRMED:** per-ticket selector alone cannot protect mapped behavior outside the selector.
   Contract inspection; its falsifier is mechanically constructible in Phase 2.
5. **LIKELY:** exact-target changed-path selection plus a required, operation-pinned, frozen-input
   ticket oracle and the mapped regression gate is the smallest safe first change. Current
   acceptance by itself is insufficient; the mapped-pre-RED same-file case remains deliberately
   open.
6. **CONFIRMED:** naive baseline+candidate execution doubles bounded wall time to about one minute
   for this one file and can consume up to 1,560 s under the current four-file budget. Direct timing
   and current budget formula.
7. **LIKELY:** a complete target-result cache can amortize baseline cost only with commit/runtime/
   selection/environment keys and target-head CAS. No cache implementation was tested.

## Sources

1. `app/merge_test_gate.py:1-303,407-423` — current changed-path mapping, pytest argv, timeout
   parsing, budgets, and gate verdicts (primary source, opened 2026-08-24).
2. `app/merge_operations.py:976-1088` — acceptance/gate ordering and late target forwarding
   (primary source, opened 2026-08-24).
3. `app/acceptance.py:140-230`; `app/mcp_stdio.py:1149-1166` — server task command, empty-command
   skip, and caller role ownership (primary source, opened 2026-08-24).
4. `docs/tasks/380/plan.md` at commit `826e551b`; oracle commit `c42163d9`; T1 commit `4e5cb061`
   — #380 ticket selectors, frozen RED evidence, and implementation topology (primary source,
   opened from Git objects 2026-08-24).
5. [pytest API reference: collection and runtest hooks](https://docs.pytest.org/en/latest/reference/reference.html#test-running-hooks)
   — setup/call/teardown protocol, collection reports, node start/finish hooks (primary upstream
   documentation, opened 2026-08-24).
6. [pytest exit codes](https://docs.pytest.org/en/stable/reference/exit-codes.html) — public exit
   meanings (primary upstream documentation, opened 2026-08-24).
7. [pytest cache provider source](https://docs.pytest.org/en/stable/_modules/_pytest/cacheprovider.html)
   — `lastfailed` recording and option-gated filtering/reordering (primary upstream source, opened
   2026-08-24).
8. [pytest configuration/rootdir reference](https://docs.pytest.org/en/stable/reference/customize.html#initialization-determining-rootdir-and-configfile)
   — nodeid root and cache directory semantics (primary upstream documentation, opened
   2026-08-24).
9. `app/workspace.py:1118-1148` — merge mutation lock and worker-only expected-head contract
   (primary source, opened 2026-08-24).
