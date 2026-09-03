# Research: preventive compact before the 1-hour cache TTL

**Task:** `precompact-timer` · **Phase:** 1 (Research + Experiment) · **Snapshot:** 2026-07-18 05:51:53 UTC

## Question

- **Context:** Orchestra runs persistent orchestrators and workers on Claude Max. A cache miss after an idle hour reprocesses a much larger prefix than a post-compact restart.
- **Change under test:** fire one preventive compact during an idle episode, shortly before the 60-minute TTL.
- **Baseline:** do nothing and let the next turn restart from the full context.
- **Outcome:** observed idle-gap distribution, `P(gap > 60 | gap > T)`, false-trigger rate, and expected net benefit under the supplied cost model.

## Hypotheses and falsifiers (fixed before the final run)

1. **H1:** preventive compact has positive EV for both agent classes because gaps that survive to late `T` usually cross 60 minutes.
   - **Falsifier:** at the practical timer threshold, false-trigger cost makes EV non-positive at the context levels actually seen in Orchestra.
2. **H2:** orchestrators and workers need different timer thresholds because their idle-tail shapes differ.
   - **Falsifier:** their late-tail conditional probabilities and operational optimum are materially the same.
3. **H3 (counter-hypothesis):** lifecycle and restart logs create the apparent long-idle tail rather than agent behavior.
   - **Falsifier:** a sensitivity run that removes lifecycle-only status records preserves the conclusion.

## Pre-registered definitions and pass/fail

- Join `logs.session_id -> sessions.id`; use the stable session ID as the grouping key and retain `sessions.name` as the label. This avoids merging two same-named agents from different scopes.
- Analyze `sessions.backend_type = 'claude'` only. Codex/Sol sessions do not use the Anthropic Max cache model and are reported as exclusions.
- Primary sample: every non-negative gap between consecutive log rows inside a session, ordered by `(ts, id)`.
- Binary class: `sessions.is_orchestrator = 1` → **orchestrator**; every other role (`worker`, `full-cycle`, and legacy worker roles) → **worker**.
- `trigger(T)`: `gap > T`, for integer `T = 1..59` minutes.
- `correct`: `gap > 60` minutes. `false`: `T < gap <= 60` minutes.
- `P_correct(T) = correct / trigger(T)`; `false_rate(T) = 1 - P_correct(T)`.
- Primary operational choice must remain at least **5 minutes below TTL**, so the latest eligible threshold is `T=55`. `T=59` is reported as the mathematical edge, not the production recommendation.
- Supplied cost model, with `x = ctx_pct / 100`: `cold(x) = $3.50x`, `compact(x) = $0.20x`, `cold_after = $0.14`; `EV = P_correct * (cold(x) - cold_after - compact(x)) - P_false * compact(x)`.
- Policy passes at a given `T,x` iff `EV > 0`. Breakeven is the smallest `x` satisfying that inequality.
- Hour-of-day uses `Asia/Krasnoyarsk` and the hour when the gap starts. Counts and conditional rates are both shown to avoid confusing activity volume with idle propensity.
- Right-censored last gaps have no next log and are excluded from the primary estimator, as requested; their count and bias are reported.

## Findings

### Verdict

**Preventive compact should be enabled for idle Claude agents. Use `T=55 min` for both orchestrators and workers, and skip contexts below 5%.** In the deployable policy sample — cache-relevant gaps armed specifically after `turn ended` — the observed correct-trigger probability is 98.91% for orchestrators (91/92) and 98.68% for workers (75/76); each class has one false trigger. The broader consecutive-log estimator gives 99.22% (127/128) and 99.28% (138/139). The supplied cost model breaks even at ~4.25% context for either class, while policy-sample median contexts are 33% and 37%.

**Confidence: CONFIRMED for the direction and common `T=55`; LIKELY for exact rates.** The conclusion survives both lifecycle-log filtering and restriction to gaps that begin at `turn ended`, but the snapshot spans only 9.74 days and gaps cluster within agents.

### 1. Dataset and integrity

The live schema differs from the task's historical data dictionary: `logs` contains `(session_id, ts, type, content)` and must join `sessions` for name, role, backend, and scope. The analysis used a SQLite backup so concurrent production logs could not move the result mid-run.

| Item | Value |
|---|---:|
| Raw logs | 35,163 |
| Excluded non-Claude logs | 947 (6 Codex sessions) |
| Claude logs analyzed | **34,216** |
| Claude sessions with logs | **119** (16 orchestrators, 103 workers) |
| Observed interval | 2026-07-08 12:04 → 2026-07-18 05:51 UTC |
| Span | **9.741 days** |
| Consecutive gaps | 12,383 orchestrator + 21,714 worker |
| Negative/out-of-order gaps | 0 |
| Snapshot SHA-256 | `2cf00b36d0d8df8942b9106c2ae4df5dc73e3de02032dc5275765b9c53fc15f0` |

`sessions.id` is the grouping key because `sessions.name` is not globally unique (`nir-writer` exists in two scopes). This is the current-schema equivalent of grouping by the requested `session_name` without merging independent conversations.

**Confidence: CONFIRMED — direct database measurement and integrity checks.**

### 2. Idle-gap distribution

| Gap bucket | Orchestrators | Workers |
|---|---:|---:|
| ≤1m | 11,465 (92.59%) | 20,962 (96.54%) |
| 1–5m | 468 (3.78%) | 324 (1.49%) |
| 5–15m | 226 (1.83%) | 215 (0.99%) |
| 15–30m | 61 (0.49%) | 60 (0.28%) |
| 30–45m | 25 (0.20%) | 10 (0.05%) |
| 45–55m | 10 (0.08%) | 4 (0.02%) |
| **55–60m** | **1 (0.008%)** | **1 (0.005%)** |
| 1–2h | 33 (0.27%) | 16 (0.07%) |
| 2–6h | 44 (0.36%) | 65 (0.30%) |
| 6–12h | 12 (0.10%) | 8 (0.04%) |
| 12–24h | 22 (0.18%) | 27 (0.12%) |
| >24h | 16 (0.13%) | 22 (0.10%) |

Most rows are within-turn bursts, not idle episodes. In the interpretable tail (`gap > 1m`), 127/918 orchestrator gaps (13.83%) and 138/752 worker gaps (18.35%) cross the TTL. Tail medians are 4.9m and 7.1m. The distribution has a conspicuous valley at 55–60m and then a long tail: exactly the shape a late preventive timer needs.

**Confidence: CONFIRMED — direct measurement.**

### 3. Timer sweep: `P(gap > 60 | gap > T)`

| T | Orch triggers | Orch Pcorrect | Worker triggers | Worker Pcorrect |
|---:|---:|---:|---:|---:|
| 1 | 918 | 13.83% | 752 | 18.35% |
| 5 | 450 | 28.22% | 428 | 32.24% |
| 10 | 302 | 42.05% | 306 | 45.10% |
| 15 | 224 | 56.70% | 213 | 64.79% |
| 20 | 202 | 62.87% | 200 | 69.00% |
| 25 | 171 | 74.27% | 156 | 88.46% |
| 30 | 163 | 77.91% | 153 | 90.20% |
| 40 | 147 | 86.39% | 145 | 95.17% |
| 45 | 138 | 92.03% | 143 | 96.50% |
| 50 | 134 | 94.78% | 141 | 97.87% |
| **55** | **128** | **99.22%** | **139** | **99.28%** |
| 59 | 127 | 100.00% | 139 | 99.28% |

Workers become predictable earlier than orchestrators, but both converge at 55 minutes. Pure cost EV is monotonically highest at the latest possible `T`; operationally, `T=59` leaves only one minute for scheduler jitter and summary generation. The pre-registered five-minute reserve makes **55 minutes the production optimum for both**.

H2 is **REFUTED**: the mid-tail differs, but there is no evidence for role-specific production timers at the safe boundary.

**Confidence: CONFIRMED for this sample; Wilson event-level 95% CI at T=55 is 95.71–99.86% (orchestrators) and 96.04–99.87% (workers).**

### 4. False compact rate

False rate is exactly `1 - Pcorrect`. It falls from 86.17%/81.65% at `T=1` to **0.78%/0.72% at `T=55`**. The two late false cases are real returns:

- orchestrator `COG-second-brain-orchestrator`: 58.149m, then a user message;
- worker `seo-cro`: 59.152m, then a new task.

The worker false case remains eligible even at `T=59`, so moving from 55 to 59 improves only the orchestrator point estimate and sacrifices the safety buffer.

**Confidence: CONFIRMED for observed completed gaps.**

### 5. EV and breakeven context

The supplied values are interpreted as full-window coefficients scaled by current context fraction `x`:

```text
cold(x)       = 3.50x
compact(x)    = 0.20x
cold_after    = 0.14
EV            = Pc × (3.50x - 0.14 - 0.20x) - Pf × 0.20x
```

At `T=55`, solving `EV=0` gives **4.244% ctx for orchestrators and 4.244% for workers**. At 40% ctx, EV is **+$1.170 and +$1.171 virtual dollars per trigger**. The observed context distributions at trigger time are:

| Class | Known ctx coverage | P25 | Median | P75 |
|---|---:|---:|---:|---:|
| Orchestrator | 119/128 (92.97%) | 21% | **37%** | 52% |
| Worker | 111/139 (79.86%) | 17.5% | **35%** | 47.5% |

At the medians, a correct orchestrator compact saves about `$1.08` (`$1.30 cold` vs `$0.21 compact+cold-small`); a worker saves about `$1.02` (`$1.23` vs `$0.21`). Even a stricter interpretation in which compact costs a fixed `$0.20` rather than `$0.20x` breaks even near 9.7%, still below both medians and P25s.

**Confidence: CONFIRMED under the task's cost model; LIKELY for absolute virtual dollars because the model is an approximation, not per-event token accounting.**

### 6. Hour-of-day segmentation (Asia/Krasnoyarsk)

| Gap-start period | Orch long gaps / P(>60\|>1) | Worker long gaps / P(>60\|>1) |
|---|---:|---:|
| Night 23–08 | 9 / **32.1%** | 5 / **20.8%** |
| Morning 08–12 | 7 / 4.1% | 18 / 11.9% |
| Day 12–18 | **71** / 13.9% | **88** / 20.0% |
| Evening 18–23 | 40 / 19.2% | 27 / 19.7% |

Absolute timer volume peaks during the day because activity also peaks there. Conditional idle propensity is highest at night, but the night denominator is small (28 orchestrator and 24 worker gaps over one minute). A 17:00 worker spike is partly fleet lifecycle behavior around a mass manual-stop, so hour-of-day should be telemetry, not a scheduling rule.

**Confidence: LIKELY for broad periods; UNCERTAIN for individual hours due sparse denominators and lifecycle clustering.**

### 7. Counter-evidence: lifecycle-only logs

Manual stop, interrupt, and `waiting for bg jobs` are log entries but not prompt-cache hits. A sensitivity run removed lifecycle-only `status` rows, reconstructed consecutive gaps, and obtained:

| Class | Primary T55 | Cache-relevant-only T55 |
|---|---:|---:|
| Orchestrator | 127/128 = 99.22% | 102/103 = **99.03%** |
| Worker | 138/139 = 99.28% | 84/85 = **98.82%** |

Filtering reduces apparent trigger volume by 19.5% and 38.8%, so the raw snapshot must **not** be linearly extrapolated into monthly trigger counts or savings. It barely changes conditional accuracy, so H3 is **REFUTED for the decision**: lifecycle logs inflate volume, not the late-tail conclusion.

The actual feature would not arm after every cache-relevant row; it would arm only after a completed turn. Restricting the filtered stream to gaps whose start is `status: turn ended` gives the most policy-aligned estimator:

| Class | Turn-ended triggers at T55 | Correct | False | Pcorrect | Median ctx |
|---|---:|---:|---:|---:|---:|
| Orchestrator | 92 | 91 | 1 | **98.91%** | 33% (91 known) |
| Worker | 76 | 75 | 1 | **98.68%** | 37% (73 known) |

Its event-level Wilson 95% intervals are 94.10–99.81% and 92.92–99.77%. EV at 40% context remains strongly positive: **+$1.166** and **+$1.163** per trigger, with breakeven at 4.25%. This restriction removes the population mismatch between the exploratory all-log sweep and the recommended `turn ended` implementation without changing the decision.

### 8. Censoring and other limitations

- The final gap of each session has no next row and is right-censored, so it is excluded as requested. At snapshot time, 115 non-running Claude sessions had already been silent for over 60m. Exclusion likely makes the long-tail estimate conservative, but their eventual return is unknown.
- Gaps are clustered within sessions. The Wilson intervals above treat events as independent and are optimistic for fleet generalization.
- Two orchestrators contribute 55/127 primary long gaps; rates describe observed fleet traffic, not an equal-weighted average agent.
- The 9.74-day window is adequate for a direction but short for weekday/seasonal conclusions.
- Timing false-rate prices token burn only. It does not quantify semantic loss from summarizing unfinished work.
- Claude Code documents that compact invalidates the conversation-layer cache but its summarization request reads the existing warm prefix [1]. The feature must fire before TTL and only at a natural break.
- Claude subscription sessions automatically request the one-hour TTL and hits refresh it [1]. If the account falls back to usage credits/forced 5m TTL, this policy is invalid.

## Concrete recommendation

1. Enable preventive compact for `backend_type='claude'` only.
2. Use the same **`T=55 minutes`** for orchestrators and workers.
3. Fire only when `status == idle`, the preceding turn has ended, there is no active background job, and `context_pct >= 5`.
4. Fire at most once per idle episode. Lifecycle-only status rows must not re-arm the timer; only new user/agent activity does.
5. Preserve the existing orchestrator pre-save workflow before compact. For workers, persist gate/task state first; semantic loss is the main non-monetary risk.
6. Log `scheduled_at`, `fired_at`, role/backend/context, next real activity, and whether the next gap crossed 60m. Re-estimate after 30 days of feature telemetry.

## Affected code / risks for a future implementation

- `app/session.py::compact` already rejects running sessions and performs orchestrator pre-save; reuse it rather than adding a second compact path.
- `app/session_turns.py::after_turn_idle_actions` is the natural place to arm an idle-only timer after `turn ended`; its current auto-compact is context-pressure-only (`>90%`) and worker-only.
- `app/manager.py::list_sessions` and `app/db.py::get_last_turn_map` already expose `last_turn_ts` and `cache_ttl_seconds`; timer state may need persistence to enforce once-per-idle-episode across restart.
- `app/bg_jobs.py` state must guard against compact while waiting/running.
- Tests belong beside `tests/test_session.py` compact re-entry/running guards, plus timer cancellation/re-arm/restart cases.
- Do not touch Codex backend behavior; its cache economics are outside this research.

## Reproducibility

```bash
python docs/tasks/precompact-timer/analyze.py /path/to/orchestra-snapshot.db --pretty
uv run python docs/tasks/precompact-timer/artifact_smoke.py
```

Browser smoke result: **PASS — 7 charts, timer/context controls, desktop/mobile overflow, zero JavaScript errors.**

## Sources

1. Claude Code Docs, “How Claude Code uses prompt caching” — 1h TTL on subscription, hit refresh, compact cache behavior. Fetched 2026-07-18. https://code.claude.com/docs/en/prompt-caching
2. Orchestra prior research — documented 1h TTL and measured 17.5× cold/hot cost ratio. `docs/tasks/cache-optimization/research.md`.
3. Kesha reference methodology and artifact. `/mnt/data/Projects/Python/kesha-tg-bot/artifacts/cache-compact-analysis.html`; `docs/tasks/cache-compact/calc-v2.py`; `timing_sweep.py`.
4. Direct measurement — snapshot of `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, hash and interval above; reproducible script in this task directory.
