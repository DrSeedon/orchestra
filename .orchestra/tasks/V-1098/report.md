# V-1098 — Terra vs Luna on reconnaissance of Orchestra code: STOP at the isolation fork

Status: offline preparation complete, **no model was run**. The provider run cannot start on this host without an owner decision about
process isolation (below). Baseline: `62896b9884aacf82219ab672dbfe1f4d50dcd0fe`. Date: 2026-10-27.

## Reading order
1. This section and "Decision needed". 2. `scripts/local_bench/recon_oracle.py` (scorer) and `tests/local_bench/test_recon_oracle.py`.
3. `runner.py`/`config.py` diff (response-based controls). Private, not in git: `.orchestra/private/V-1098/` — tasks, golden answers,
configs, `verify_golden.py`, offline dress-rehearsal runs (the golden answers must not reach the models' input).

## Why the run is stopped
`python -m scripts.local_bench doctor` → RC 2, `bwrap: setting up uid map: Permission denied`; `kernel.apparmor_restrict_unprivileged_userns=1`
(Ubuntu 24.04.4, kernel 6.8.0-147). The harness runs the provider CLI with `-s danger-full-access` *inside* bwrap; without bwrap the model
shell would see the whole host (`/home/kesha/orchestra/.env` 0600 but running as the same uid, the 5.7 GB `data/orchestra.db` mode 0644, ssh keys,
KB and task reports that contain the answers). I looked for an already-supported, equally protected native path and found none:
- `codex sandbox -- true` (0.163.0): `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`, same wall; the legacy-Landlock override
  panics (`filesystem-restricted execution requires bubblewrap`). Codex's native sandbox *is* bwrap.
- `unshare -Ur`: `write failed /proc/self/uid_map: Operation not permitted`. `sudo` is blocked inside the agent process (NoNewPrivileges).
- Landlock exists (ABI 4: filesystem + TCP connect), Yama `ptrace_scope=1`. ABI 4 has no signal scoping (needs ABI 6) and no `/proc`/PID
  namespace, so a Landlock-only sandbox still lets the model signal or inspect other processes of the same uid (e.g. the Orchestra service) — weaker
  than the bwrap boundary the harness promises, hence not "equally protected".
I did not weaken the AppArmor setting, skip the preflight, or use a `danger-full-access` fallback.

## Decision needed (architectural / system-protection fork — owner)
| Option | What changes | Protection compared to the harness contract | Cost |
|---|---|---|---|
| **A. Narrow AppArmor exception for the one vendor `bwrap` binary** (Ubuntu's documented per-binary `userns` profile; global sysctl stays 1) | One profile file for `/usr/lib/node_modules/@openai/codex/.../codex-resources/bwrap`, loaded by root via `ssh kesha@localhost`; reversible | Full: unchanged harness (mount/PID/IPC namespaces, private `/tmp`/HOME, relay-only network) | Smallest; touches system protection, which the owner left "as is" in V-560 — his call. Any process that runs that exact binary gains unprivileged userns. |
| B. New Landlock+seccomp mode in `isolation.py` (no system change) | New isolation code | Weaker: same-uid signals/ptrace-inspection and `/proc` visible; model shell could disturb production | New security design, needs its own verification |
| C. Dedicated unix user + wrapper | New account, sudoers rule, file modes (`data/orchestra.db` is world-readable and must be re-checked) | Process isolation by uid, but no mount/network namespace; Landlock still needed | System change plus new code |
| D. Another host | — | — | Out of scope (VPS only); laptop excluded |
Recommendation: **A**. It is the only option that keeps the already-tested harness boundary unchanged; if refused, run only the offline part (already done) and treat the model question as unmeasured here.
Everything else (tasks, oracle, controls, configs, schedule) is ready, so a single "yes" starts the pilot.

## What is ready (verified offline)
- **Harness changes** (reuse of `scripts/local_bench`): `recon_oracle.py` — deterministic scorer, no model judge; `controls.reference_response` /
  `controls.negative_responses` — the run refuses to start any arm unless the oracle passes a recorded correct answer and fails every recorded wrong one
  (wrong answer, fabricated citation, no JSON) and the empty baseline. README and CHANGELOG updated.
- **Tests** (`uv run --frozen python -m pytest tests/local_bench --confcutdir=tests/local_bench -q -p no:randomly`): 56 passed (18 new). Mutations reddened
  committed tests: dropping the invalid-citation clause (5 failures), dropping the anchor-coverage clause (1), disabling the reference-response control (2).
  The tests do not import `app`, the live DB, tokens or provider CLIs.
- **Task set** (6 real questions on `app/` at the baseline, pinned `git archive` of `app/` without `app/static`; 147 files, 4.0 MB; no `.orchestra`, KB,
  reports, `.env`, DB, AGENTS/CLAUDE/TODO/CHANGELOG, no MCP, web search disabled, same prompt text and answer format for every arm):
  one real call chain across 4 modules; two registry/decorator questions (route table by decorators with a client-call distractor; where an owner-only
  model set is read and where its gate is called, with a comment/definition distractor); two configuration-failure questions (a malformed value read
  live from `.env`: raising function, exception, fragment, import-time vs call-time; a stale persisted override at start: propagation, deletion, log
  level, horizon); one negative control (a Redis pool that does not exist — correct answer is "not found" plus the real storage module).
- **Golden answers** were derived by reading and re-derived independently by `verify_golden.py` (AST call-edge check, AST route/usage scan, execution of the real
  parser and of `initialize_gate_override` against a stub store, `rg` over all of `app/` for the negative): 20/20 checks agree.
- **Offline dress rehearsal** with fixture actors on all six tasks through the real runner: controls gave baseline FAIL, reference PASS and all three negative
  responses FAIL; actors good/wrong/fabricated/no-JSON gave PASS/FAIL/FAIL/FAIL. This proves the scoring, not any model.

## Pre-registered design (fixed before any run)
- Arms: Terra 6.1 `high`, Terra 6.1 `xhigh`, Luna 6 `high` (Luna `xhigh` and Fast tier only if the pilot shows Luna high below ceiling or timing is the open question).
  Exact model ids `gpt-6.1-terra` / `gpt-6-luna` (visible in `codex debug models`, CLI 0.163.0; Terra default effort is `low`, so efforts are always set explicitly).
- Per-task pass = every golden check exact, zero invalid citations, every anchor line covered, no out-of-scope file change, process exited 0.
  Secondary: graded `check_score`, citations validity rate, `false_completion` (non-empty reply without parseable JSON), tool calls, wall seconds, input/cached/output tokens,
  API-equivalent USD at standard short-context prices (Terra 1.00/0.05/5.00, Luna 0.10/0.01/0.50 per 1M; reported separately from subscription use and from other agents' consumption).
  Failures from quota/provider/launch are recorded as invalid runs, not as wrong answers; budget stops are reported, not bypassed.
- Pilot: 1 repeat of task 1 + task 6 with all arms (checks end-to-end accounting and the side-effect check). Main: 6 tasks × 3 repeats × 3 arms = 54 runs, task order and arm order rotated
  per repeat. Decision rules before data: if every arm passes every run (ceiling) the report says the set cannot separate them and compares only time/tokens/cost; no sweep to harder tasks without a new decision.
  With 18 runs per arm, a pass-rate difference under roughly 25 percentage points is not distinguishable from noise; the report will give intervals, not rankings of overlapping arms.
- Cost cap in the configs: 0.8 / 1.2 / 0.3 USD per arm-run API-equivalent (sum 41.4 USD for 18 task-repeats worst case). The binding limit is the Plus Codex subscription pool, shared with other agents; the pilot measures real use before the main set.

## Limits and risks
Different CLI features for the same model are not isolated (this measures model + Codex runtime). Six questions, one code base and one author's golden answers are a narrow sample; a pass means the answer
matches the golden facts and the cited lines exist and cover the anchors, not that the explanation is complete. Terra/Luna equal-effort labels may not mean equal compute. No result on model quality exists yet.

Restart: not needed (no `app/**` change).

## Update 27.10: isolation decision applied, pilot blocked by provider quota

Owner decision (27.10 15:21 KRS): no sandbox, plain Codex `-s danger-full-access`. Implemented as `"sandbox": "none"` in the run config (`scripts/local_bench/runner.py`, `config.py`): each arm runs in a throw-away `mkdtemp` copy of the pinned source with its own HOME/CODEX_HOME, bwrap preflight and relay are skipped, the full JSONL is kept, and `audit_transcript` marks a run invalid when any shell command names a path outside the copy, `..`, `~`, `.orchestra`, `.env`, `.ssh` or the DB. AppArmor/sysctl untouched. Tests: `tests/local_bench` 58 passed (commit bffb70719).

Pilot (t1 and t6, three arms each, 6 runs): every run ended in 2-58 s with 0 commands and the provider event `You've hit your usage limit ... try again at 12:00 PM` (`turn.failed`). All 6 are INVALID by quota, not model answers; no tokens were billed (accounting missing). Raw JSONL in `.orchestra/private/V-1098/runs/pilot-*`. No comparison data exist yet. The pilot must be repeated after the limit resets; the weekly-percentage check before the main set is still pending.

## Result (27.10): Terra 6.1 high / xhigh vs Luna 6 high on Orchestra code reconnaissance

Setup as pre-registered: baseline `62896b988`, six tasks (t1 call chain, t2 route registry, t3 owner-only models, t4 config failure, t5 stored override, t6 negative control), 3 repeats, task order rotated per repeat, three arms in parallel per run = **54 runs**, plus a 6-run pilot (t1, t6). Codex CLI 0.163.0, `-s danger-full-access` in a throw-away copy per run (owner decision 27.10 15:21 KRS: no sandbox), no web search. Raw JSONL, stderr, oracle output, effective configs: private `runs/main-*` (not in git); per-run table `main-summary.json`, scorer `aggregate.py` in this folder. Quota: weekly Codex window 56% before the pilot, 58% after the main set (shared pool, other agents included), no run hit a provider limit (one earlier pilot attempt did, 6 runs, invalid and rerun; see above). API-equivalent cost only, not a subscription charge.

### Strict result (oracle exactly as frozen before the runs)

| Arm | Valid runs | Pass | 95% Wilson | Median s | Mean API-equiv USD/run | Median tool calls | Invalid citations | False completions |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| terra-high | 18 | 15 | 83% (61-94) | 13.9 | 0.0236 | 5 | 0 | 0 |
| terra-xhigh | 17 | 14 | 82% (59-94) | 15.3 | 0.0231 | 5 | 0 | 0 |
| luna-high | 18 | 15 | 83% (61-94) | 17.9 | 0.0034 | 3 | 3 | 0 |

Per task (pass/valid): t1 Terra 3/3 + 3/3, Luna 0/3; **t2 Terra 0/3 + 0/3, Luna 3/3**; t3, t4, t5 all arms 3/3; t6 Terra-high 3/3, Terra-xhigh 2/2, Luna 3/3. Totals of arm cost: terra-high 0.425, terra-xhigh 0.416, luna-high 0.060 USD (54 runs ≈ 0.90 USD API-equivalent).

### Two measurement defects found after the runs (disclosed, not hidden)

1. **t2 is a task-specification flaw, not a model difference.** The prompt asked for the handler "function name", while the shared answer-format footer says names are `path::Name`. Both Terra arms followed the footer (`app/routes/system.py::get_usage`), Luna wrote the bare name. After stripping `path::` from the handler, all 9 Terra and 9 Luna answers are the identical, correct 10-route set (checked against the golden set). The strict table above keeps the frozen oracle; the corrected view (post-hoc, labeled as such) is: **Terra-high 18/18, Terra-xhigh 17/17 (+1 flagged run below), Luna 15/18**.
2. **One run flagged invalid by the path audit is a false positive:** t6 repeat 3 terra-xhigh ran `rg --files -g '*.env*' ...` inside the copy (a glob, no read outside). It scored 1.0 on all checks. Kept as invalid in the strict table (rule applied mechanically), counted as valid-in-fact in the corrected view: Terra-xhigh 18/18. No run read outside its working copy or wrote outside it (0 out-of-scope changes in 54 runs).

### Reading

- **Quality on reconnaissance of this size:** Terra (either effort) answered every task correctly once the t2 format flaw is removed; Luna failed only t1 (3/3 repeats): wrong class name `AgentManager` for `SessionManager`, an extra intermediate step in the chain, and one invalid line citation per run (the only invalid citations in the whole set). Because the three Luna failures are three repeats of one task, the real independent N is 6 tasks, not 18: the difference (Terra 18/18 vs Luna 15/18, Fisher two-sided p = 0.23 on runs, weaker on tasks) is **not distinguishable from noise and from this one task's difficulty**. A difference below roughly 25 percentage points is not measurable with this design; the sign (Terra at least as accurate) is suggestive only.
- **xhigh did not help:** no pass-rate gain over high, +10% time, ~+20% output tokens, same cost. No evidence for xhigh on reconnaissance.
- **Cost and time:** Luna-high is ~7x cheaper in API-equivalent dollars (0.0034 vs ~0.0235 per run), but slower (median 17.9 s vs 13.9 s; it emits ~2x more output tokens, 1202 vs 549 mean) and makes fewer tool calls (3 vs 5). Ceiling: 5 of 6 tasks were passed by every arm, so the set mostly measures cost and time, not capability; no harder tasks were added (pre-registered).
- **Practical conclusion for Orchestra:** for bounded questions of this kind both models are sufficient; use Luna where a cheap answer with line citations is checked afterwards (watch invalid citations and exact class names on multi-hop call chains), Terra high where a multi-hop chain must be exactly right. No evidence supports xhigh. Not measured: tasks longer than ~2 min, edit tasks, Fast mode, Luna xhigh, other repositories, subscription-quota burn per run (the shared window moved 56 -> 58% weekly over 54 runs, which includes other agents).
- **Limits:** one repository snapshot, six tasks, three repeats, oracle written by one author (answers verified by AST and by running code, 20/20); t2 flaw above; Codex CLI version and model snapshots as of 27.10.
