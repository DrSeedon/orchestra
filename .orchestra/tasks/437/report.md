# #437 — Fable 5.1 subscription canary report

## Result

**Do not introduce Fable 5.1 into the working pool. Live Fable calls in #437: `0`.**

The remaining empirical question was whether Max weights Fable output tokens at the same rate as Opus or at the 2× API-price ratio. The exact multiplier remains unmeasured. The question was closed because neither answer changes the routing decision:

- 2× → Fable consumes more subscription than Opus;
- 1× → Fable consumes the same subscription, while the advertised cache-read price reduction does not reduce subscription usage.

Buying a 593,467-output-token discriminator cannot change that decision and is therefore not justified.

## Question and evolution of the measurement

#434 showed that Fable 5.1 can reuse the Claude Code cache and that its cache reads are cheaper under token-billed API pricing. #437 was authorized to test whether this advantage transfers to Claude Max subscription accounting.

The intended live canary was stopped before its first Fable call after full-account evidence showed that the local sensitivity estimate was biased by missing consumers. Two decision rules and the 72,704-token harness remain in the task directory as explicitly superseded audit artifacts; `run_live_output_canary.py` now exits before any provider/model call.

## What was directly measured in this worktree

### Laptop-Orchestra-only regression

`reproduce_subscription_regression.py` used the frozen range `2026-07-29T05:17:21.890375Z..2026-09-01T18:45:10.186332Z`, 3,481 Claude rows, 3,307 quota-bearing rows, and 77 monotonic counter segments. `regression-results.json` preserves all windows.

Across four preregistered arms:

- output coefficient: `127.99..148.91 five-hour p.p./MTok`;
- cache-read coefficient: `−0.117..−0.155 p.p./MTok`;
- control R²: `0.323..0.371`;
- cache-write coefficient: `1.57..4.04`, but every 95% interval included zero;
- extended R² gain: `0.0029..0.0157`;
- VIF `3.29..6.14`, standardized condition number `5.00..5.32`.

These numbers are reproducible for the local source and **not estimates of the shared account**.

### Timestamp-filter defect

The reported “last 3 hours” count `142 turns / 458,176 output tokens` was reproduced from a broken SQLite predicate:

```sql
turn_usage.ts >= datetime('now', '-3 hours')
```

`turn_usage.ts` contains ISO timestamps with `T`; SQLite `datetime()` emits a space. On the same date, lexical comparison evaluates `T > space`, so the predicate selected the whole date. One turn later the same broken query returned `143 / 463,533`, first row `03:49:11`, whereas a Python-generated ISO cutoff returned `85 / 271,347` for the actual three hours.

The local current-window check after the visible `86%→1%` reset yielded `147,164 output tokens` and `1%→20%`, or `129.11 p.p./MTok`. That check was internally correct for the local source but was later withdrawn as an account-wide sensitivity estimate.

### Mechanical checks

- `python3 docs/tasks/437/reproduce_subscription_regression.py --self-test` → `SELF_TEST_OK`.
- Frozen regression run → `stable_control_gate=true`; arms A/B/C/D = `77/77/64/72` windows.
- `python3 docs/tasks/437/run_live_output_canary.py --self-test` → `SELF_TEST_OK`.
- Live harness without `--self-test` → exit 1 before telemetry/model access:
  `SUPERSEDED: 72,704-token harness used the incomplete 142.225996 coefficient; no live Fable call is permitted`.
- `docs/tasks/437/live-results.json` does not exist.

## Full-account evidence supplied by the user

The user combined four sources: VPS Claude Code, laptop Claude Code, VPS Orchestra, and laptop Orchestra. A 201-pair laptop/VPS quota check matched exactly 141 times and differed by mean 0.51 p.p., supporting one shared account counter.

Source shares:

| Source | Share of observed consumption |
|---|---:|
| VPS Claude Code | 36.7% |
| laptop Claude Code | 33.7% |
| VPS Orchestra | 15.7% |
| laptop Orchestra | 14.0% |

Full-coverage regression supplied by the user:

| Term | Five-hour p.p./MTok |
|---|---:|
| output | **15.68** |
| cache read | **−0.030** |
| cache write | **1.71** |
| intercept | **4.44** |

`R²=0.751`. This worker cannot reproduce the full regression: the local DB contains only laptop Orchestra and contains neither VPS telemetry nor interactive Claude Code turn telemetry from either machine. The full-coverage coefficients are caller-supplied measurement evidence, not independently rerun evidence.

## Independent manufacturer confirmation

Caller-supplied primary-source quote from `@ClaudeDevs`, 2026-09-01:

> “In Claude Code, cache reads count at a reduced rate toward subscription usage, which remains unchanged.”

The same post says long sessions billed at API rates can be 25–45% cheaper.

The statement separates unchanged subscription accounting from savings on token-billed/API surfaces. It independently supports the stable empirical result: cache-read is approximately free in the subscription counter, so Fable 5.1's 75% API cache-read discount does not create a Max-pool advantage.

## Named retractions

The following statements are **withdrawn for account-wide decisions**:

1. `129.11 five-hour p.p./MTok` as the account sensitivity. It measured one incomplete source.
2. `6,715–7,813 output tokens per five-hour p.p.`. Full coverage gives about `63,776`.
3. “Cache write is approximately zero.” Full coverage reports `1.71 p.p./MTok`, write/output ratio `0.109`; local non-detection was missing-source bias.
4. `72,704 Fable output tokens` as a powered scoped discriminator. Under full sensitivity it predicts only `0.368` scoped p.p. raw or `0.735` price-weighted.
5. The #434 `0.888×` Fable/Opus historical comparison as a subscription conclusion. It remains only an API-price counterfactual.

The finding that survived both local and full coverage is **cache-read weight ≈0**.

## Unclosed exact multiplier and price of returning

Exact Fable-vs-Opus output weighting in Max remains **UNMEASURED**.

Using the full-coverage output coefficient `15.68`:

- one five-hour p.p. ≈ `63,775.5` output tokens;
- a 3-p.p. separation on the noisy five-hour counter requires `191,327` Fable output tokens, but that counter is contaminated by unrelated Opus/interactive traffic;
- using `r=54/335` and the 50% Fable allowance gives raw scoped slope `5.0550448 p.p./MTok`;
- a 3-p.p. Fable-scoped separation requires **593,467 actual uncontaminated output tokens**;
- predictions at that target: raw `3.000 scoped p.p.`, API-price-weighted `6.000 scoped p.p.`;
- this fits under the authorized 7-p.p. ceiling mathematically, with 1 p.p. rounding margin;
- the current CLI reports 64k maximum Fable output per call, so at least **10 near-maximum calls** are required.

Any safeguard fallback, short output, telemetry failure, or early hard stop can leave the experiment underpowered. A future return must reauthorize this explicit cost; no old 72.7k harness may be reused.

## Quality and speed

No closed-ticket quality run and no matched speed run were purchased. Both were lower priority than subscription accounting. After the manufacturer confirmation and full-coverage result made the routing decision invariant to the remaining output multiplier, further model spending had no decision value.

## Review

A Luna review was started against the now-superseded 72,704-token harness. The server restarted/subject was withdrawn before any completed verdict artifact appeared. No review result is claimed. Final closure rests on frozen scripts, synthetic self-tests, fail-closed live guard, exact arithmetic, and the user's full-coverage evidence.

## Candidate KB promotion

### Установлено

- `fact:claude-subscription-token-weights-full-coverage` · искать: `Fable 5.1`, `subscription`, `cache read`, `cache write`, `output` · Full four-source account regression reports output `15.68`, cache-read `−0.030`, cache-write `1.71`, intercept `4.44` p.p./MTok and `R²=.751`; `@ClaudeDevs` says subscription usage remains unchanged while API-billed long sessions can be 25–45% cheaper · evidence: `docs/tasks/437/report.md` full-account section + caller-supplied `@ClaudeDevs` 2026-09-01 quote · 2026-09-02 #437.
- `fact:sqlite-iso-timestamp-separator-filter` · искать: `datetime('now','-3 hours')`, `turn_usage.ts`, `SQLite`, `T` · Comparing ISO text containing `T` with SQLite `datetime()` text containing a space selected the whole same date: broken `143/463,533` from `03:49`, correct ISO cutoff `85/271,347` · evidence: `docs/tasks/437/report.md` timestamp-filter section · 2026-09-02 #437.
- `fact:fable-output-weight-discriminator-cost` · искать: `593467`, `Fable-scoped`, `7 p.p.`, `output multiplier` · Exact Fable output weighting is unmeasured; a 3-p.p. scoped discriminator at full sensitivity requires 593,467 uncontaminated output tokens, predicts raw3/price6 scoped p.p., and needs at least ten 64k calls · evidence: `docs/tasks/437/decision-rule-full-coverage.md` + arithmetic check in report · 2026-09-02 #437.

### Отвергнуто

- `fact:laptop-orchestra-quota-sensitivity-withdrawn` · искать: `129.11`, `6715`, `7813`, `cache write zero`, `14%` · Laptop-Orchestra-only sensitivity and cache-write non-detection cannot represent the shared account; full coverage changed output ~142→15.68 and write locally-unidentified→1.71 · evidence: `docs/tasks/437/regression-results.json` vs caller-supplied four-source regression in `docs/tasks/437/report.md` · 2026-09-02 #437.

### Пробелы

- Exact Fable/Opus output multiplier in Claude Max remains unmeasured · next valid measurement costs 593,467 uncontaminated Fable output tokens and explicit reauthorization · 2026-09-02 #437.

## Files and production impact

- Added task-local preregistration, regression harness/results, superseded decision records, preflight evidence, fail-closed live harness, and this report under `docs/tasks/437/`.
- `app/`, `tests/`, `app/models.py`, provider configuration, and production data were not modified.
- Breaking changes: none.
