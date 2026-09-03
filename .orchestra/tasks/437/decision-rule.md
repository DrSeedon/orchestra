# #437 preregistration — superseded five-hour Fable decision

Status: **SUPERSEDED BEFORE ANY LIVE FABLE OBSERVATION.** The shared five-hour outcome was withdrawn because unrelated Opus orchestrators move it. The replacement is `decision-rule-scoped.md`. This file remains unchanged below as the audit record of the rejected design.

## Frozen quantities from the zero-cost control

- Primary output coefficient `B = 142.225996 five-hour percentage points / MTok` from arm A in `regression-results.json`.
- Sensitivity range across A–D: `127.990740..148.908543 %/MTok`.
- Current 72-hour five-hour→weekly exchange rate: `r = 54 / 335 = 0.16119402985074627 weekly pp per five-hour pp`, measured by `app.db.usage_exchange_rate()` against the live DB after explicitly binding `DB_PATH` to `/mnt/data/Projects/Python/orchestra/data/orchestra.db`.
- Fable allowance is 50% of the shared weekly plan limit. Planning estimate: `Fable-scoped pp = five-hour pp × r / 0.5 = five-hour pp × 2r`. This is a nesting conversion for budget planning, not the live outcome oracle.

## Hypotheses

For actual non-fallback Fable output `T` tokens:

- `H_raw`: the subscription counts raw output tokens, so predicted five-hour movement is `P_raw = B × T / 1,000,000`.
- `H_price`: the subscription weights output by the model's API price; Fable output is 2× Opus, so `P_price = 2 × P_raw`.

The decision uses the five-hour counter. Fable-scoped weekly is used only for the hard budget stop.

## Required output for ≥3 p.p. hypothesis separation

`P_price - P_raw = P_raw`, so a 3 p.p. separation requires:

- primary estimate: `T >= 3,000,000 / 142.225996 = 21,093` Fable output tokens;
- conservative across the frozen sensitivity range: `T >= 3,000,000 / 127.990740 = 23,439` tokens.

Proposed target pending authorization: **23,500 total non-fallback Fable output tokens**, split across two matched calls in `O/F/O/F` order.

At 23,500 tokens:

| Scenario | Five-hour, primary | Five-hour, A–D range | Fable-scoped weekly estimate, primary | Fable-scoped range |
|---|---:|---:|---:|---:|
| raw 1× | 3.342 p.p. | 3.008–3.499 | 1.077 p.p. | 0.970–1.128 |
| price 2× | 6.684 p.p. | 6.016–6.999 | 2.155 p.p. | 1.939–2.256 |

The current 1 p.p. Fable-scoped ceiling cannot safely carry this discriminator: even `H_raw` is near/above it and `H_price` needs about 2.26 p.p. before integer rounding. Required hard ceiling for a safe run: **3 Fable-scoped weekly p.p.** A lower authorized ceiling means no run or an explicitly underpowered run whose expected result is `INCONCLUSIVE`.

## Matched protocol once authorized

- Order: Opus/Fable/Opus/Fable, one process at a time, no parallelism.
- Same cwd, effort, prompt shape, tool configuration, and requested output per pair; only exact model id changes.
- Record fresh upstream quota immediately before the first call and after every call. `/api/usage` is forbidden.
- Record `loadavg` and monotonic wall-clock around every call.
- Record every assistant message's actual `message.model`, plus every `modelUsage` key and token count.
- Aggregate actual output tokens, not requested output length.
- Stop immediately when Fable-scoped weekly movement from baseline reaches the authorized ceiling. Never start another Fable call at the ceiling.
- Abort/inconclusive if the five-hour or Fable-scoped reset timestamp changes during the sequence, fresh upstream returns an error/429, or the matched Opus output cannot be produced.

## Safeguard fallback rule

A Fable interval is uncontaminated only when every assistant message in that CLI call reports Fable 5.1 and `modelUsage` contains no Opus output tokens. If any assistant message or model-usage entry reports Opus for a requested-Fable call:

- exclude the entire interval's five-hour movement and all its output tokens from the Fable numerator/denominator;
- retain it only in the budget ledger because the subscription was still consumed;
- do not assign or prorate its counter movement between models;
- if uncontaminated Fable output falls below the authorized target, report `INCONCLUSIVE_FALLBACK`; do not exceed the ceiling to replace it.

## Decision zones fixed before observation

Let `D_F` be the sum of five-hour counter increments only across uncontaminated Fable intervals, and let `T_F` be their actual output. Recompute `P_raw` and `P_price` from `T_F`.

Use conservative ±1 p.p. observation bands for integer counter resolution:

- `I_raw = [P_raw - 1, P_raw + 1]`;
- `I_price = [P_price - 1, P_price + 1]`.

Verdict mapping:

- `RAW_TOKEN_WEIGHT`: `D_F` lies in `I_raw` and outside `I_price`.
- `API_PRICE_WEIGHT`: `D_F` lies in `I_price` and outside `I_raw`.
- `INCONCLUSIVE_OVERLAP`: `D_F` lies in both intervals. This label is mandatory; do not choose the nearer hypothesis.
- `INCONCLUSIVE_NOISE`: `D_F` lies in neither interval.
- `INCONCLUSIVE_UNDERPOWERED`: actual `P_price - P_raw < 3` p.p., including an early budget stop.
- `INCONCLUSIVE_FALLBACK`: fallback leaves less than the authorized non-fallback target.

Matched Opus is a validity control, not a correction knob. Let `D_O/T_O` be its aggregate. Expected Opus movement is `P_O = B × T_O / 1,000,000`. If `abs(D_O - P_O) > 1 p.p.`, external movement/noise exceeds the counter resolution and the entire experiment is `INCONCLUSIVE_NOISE`. Do not subtract an estimated background from Fable or tune the bands after observation.

If several inconclusive conditions apply, report all of them. No nearest-distance tie-break is allowed.

## Speed output

For uncontaminated calls report wall seconds, actual output tokens, output tokens/second, and start/end load average. Speed is descriptive at `n=2` per model; no significance claim is permitted.

## Quality

Closed-ticket quality is not part of this live output-weight canary. It is attempted only if an explicit later budget remains after the subscription-weight result.
