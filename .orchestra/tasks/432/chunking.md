# #432 generation g2 — cost and restart-bounded chunks

Generation parameters: `docs/tasks/432/generation-2.json`, SHA-256
`e5e0d355f14b311d3def92fd8a60a1553c4b8713b057a074d40b7ef2cc32852c`.

## Exact role-job count

| phase | role jobs |
|---|---:|
| structural canary | 1 |
| full positive A/B pair | 3 |
| A0/A0 noise, 6×2 | 12 |
| main 12×2: A + scout + B-main | 72 |
| cold-history controls, 3 pairs | 9 |
| zero-retrieval control | 3 |
| **total** | **100** |

The statistical main denominator remains 24 A/B pairs. Canary/positive/noise/controls are reported
separately; none is silently folded into the 24.

## Price estimate before g2 starts

Observed valid role samples from the excluded calibration generation:

- A main: `n=8`, mean `$0.12988514`, median `$0.11559464`, min/max
  `$0.04600944 / $0.23470120`;
- scout: `n=3`, mean `$0.0404772133`, median `$0.04015096`;
- B main: `n=3`, mean `$0.0493404933`, median `$0.05178240`;
- structural canary: `$0.00539916`.

Applied to 41 A-main, 29 scouts, 29 B-main and one canary:

- median-role projection: **`$7.41084684`** API-equivalent;
- mean-role projection: **`$7.93540339`**;
- projection using each role's observed min/max endpoints: **`$4.31255308 .. $12.35545452`**.

This is a planning range, not confidence interval. Actual generation cost is the sum of all terminal
role usage, including failed model answers; provider-started usage is never rewritten to zero.

## 15–20 minute construction

Measured completed role durations (`n=20`): median `5.21 min`, p90 `16.29 min`, maximum
`19.81 min`. Therefore one server-side job executes exactly **one Luna role session plus its
deterministic judge**. A B arm is two durable chunks: scout checkpoint → main+judge checkpoint.

`scripts/recon429/generation_432.py` pre-registers 100 slot IDs and atomically writes
`generation-state.json`:

1. `NOT_STARTED → STARTED` before provider launch;
2. terminal usage + judge artifact are written under the pair directory;
3. `STARTED → COMPLETED` only after both are durable.

The command for one chunk is:

```bash
/home/kesha/orchestra/.venv/bin/python scripts/recon429/generation_432.py run-next \
  --run-root scripts/recon429/run-g2-clean
```

It must itself be launched via `bg_create(type="run")`; after completion the next job starts from
the next `NOT_STARTED` slot. No job contains the remaining series.

### What chunking does and does not survive

Completed slots survive a service restart as immutable audit evidence; an interrupted job can waste
at most one role (observed p90 16.29 min), not every later role. A slot left `STARTED` is
`AMBIGUOUS` and is never auto-retried. Chunking therefore bounds wasted work but cannot make an
in-flight provider call attributable; a clean statistical generation still requires no ambiguous
slot. True adoption/resume of the child process remains the separate `app/bg_jobs.py` platform fix.

## Excluded generation

`docs/tasks/432/excluded-generations.json` permanently excludes `bg-54ff5827bb`,
`bg-74ba2c50f7`, `bg-0cb8101697` and ambiguous `task-416-a02` as `platform_restart`. The five
completed A/A rows (`$0.70058448`) do not seed g2 noise or any g2 denominator.
