# #437 full-coverage sensitivity and revised feasibility

Status: **FABLE BLOCKED.** This arithmetic supersedes `decision-rule.md`, `decision-rule-scoped.md`, and live harness commit `18d0efdc`. No live Fable observation exists under any prior rule.

## Evidence boundary

The user supplied a four-source account-wide regression over VPS Claude Code, laptop Claude Code, VPS Orchestra, and laptop Orchestra:

| Predictor | Full-coverage coefficient, five-hour p.p./MTok |
|---|---:|
| output | 15.68 |
| cache read | −0.030 |
| cache write | 1.71 |
| intercept | 4.44 |

`R²=0.751`. Source shares: VPS Claude Code 36.7%, laptop Claude Code 33.7%, VPS Orchestra 15.7%, laptop Orchestra 14.0%. A 201-pair laptop/VPS quota check matched exactly 141 times and differed by mean 0.51 p.p.; the account counter is shared.

This worker **cannot reproduce the full regression**: the local DB contains laptop Orchestra only and has neither VPS turn telemetry nor interactive Claude Code turn telemetry from either machine. The local `127.99–148.91` output range and cache-write confidence interval remain valid only for the 14% source and are withdrawn as estimates of account-wide sensitivity.

The account-wide coefficients are caller-supplied measurement evidence, not independently reproduced here. All revised calculations below are deterministic arithmetic on that input.

## Stable and withdrawn conclusions

- Stable: cache-read weight remains approximately zero (`−0.030` vs output `15.68`). The API cache-read discount does not materially affect the subscription counter.
- Withdrawn: local output sensitivity `~142 p.p./MTok`, `6.7–7.8k tokens/p.p.`, live-window `129.11`, and target `72,704`.
- Withdrawn: “cache write is indistinguishable from zero” as an account-wide claim. Full coverage reports `1.71 p.p./MTok`, write/output ratio `0.109`; local non-detection was missing-source bias.

## Revised five-hour volume

For `B_full=15.68 five-hour p.p./MTok`, one five-hour p.p. corresponds to:

```text
1,000,000 / 15.68 = 63,775.51 output tokens
```

Raw-vs-2× price predictions differ by the raw prediction. A ≥3 p.p. five-hour separation requires:

```text
T_5h = 3,000,000 / 15.68 = 191,326.53 → 191,327 tokens
raw prediction   = 3.00001 five-hour p.p.
price prediction = 6.00001 five-hour p.p.
```

The shared five-hour counter is not a valid live outcome because unrelated Opus and interactive traffic moves it.

## Revised Fable-scoped volume

Frozen 72-hour conversion from shared snapshots: `r=54/335=0.16119402985074627 weekly p.p. per five-hour p.p.`. Fable allowance is 50% of shared weekly, so:

```text
S_raw = 15.68 × r / 0.5 = 5.055044776119403 scoped p.p./MTok
S_price = 10.110089552238806 scoped p.p./MTok
```

A ≥3 p.p. scoped separation requires:

```text
T_scoped = 3,000,000 / S_raw
         = 593,466.55 → 593,467 output tokens
```

At `593,467` actual uncontaminated Fable output:

| Scenario | Fable-scoped movement | Shared weekly movement | Shared five-hour movement |
|---|---:|---:|---:|
| raw 1× | 3.00000 p.p. | 1.50000 p.p. | 9.30556 p.p. |
| price 2× | 6.00000 p.p. | 3.00000 p.p. | 18.61113 p.p. |

## Does it fit the authorized budget?

**Mathematically yes, operationally narrowly.** The price-weighted prediction is 6 scoped p.p. under the authorized 7 p.p. ceiling, leaving 1 p.p. for integer rounding. The shared weekly prediction is 3 p.p.; from a 3% baseline it remains below the 15% absolute stop if unrelated traffic does not consume the 9 p.p. margin during the long run.

The current Claude Code result metadata reports a 64k output ceiling for Fable. `593,467` therefore requires at least `ceil(593,467/64,000)=10` near-maximum output calls. This is roughly 8.2× the withdrawn 72,704-token plan. Any fallback, short generation, fresh-telemetry failure, shared-weekly growth, or early scoped rounding can stop the run below power; topping up beyond either hard stop is forbidden.

## Decision zones if a new live harness is later authorized

For actual uncontaminated output `T` and observed Fable-scoped delta `D`:

- `P_raw = 5.055044776119403 × T / 1,000,000`;
- `P_price = 2 × P_raw`;
- `I_raw=[P_raw−1,P_raw+1]`;
- `I_price=[P_price−1,P_price+1]`.

Verdicts remain explicit: raw only → `RAW_TOKEN_WEIGHT`; price only → `API_PRICE_WEIGHT`; both → `INCONCLUSIVE_OVERLAP`; neither → `INCONCLUSIVE_NOISE`; separation <3 → `INCONCLUSIVE_UNDERPOWERED`; fallback/reset/telemetry stop → matching inconclusive label. A fallback interval is excluded whole from `D` and `T` but retained in the budget ledger.

No live run may use this rule until the orchestrator explicitly reauthorizes the revised 593,467-token target after seeing this feasibility result.
