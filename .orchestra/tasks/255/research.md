# #255 — почему Codex тормозит при десятках живых процессов

## Вердикт

История **не подтверждает резкий provider/model slowdown от высокой одновременности**. Она
подтверждает другое: пользовательский счёт «~30 процессов/сессий» смешивает три разных величины —
active model turns, app-server roots и их Node/code-mode/MCP helpers.

В 1 280 точных rollout-интервалах максимум был **12 одновременно active Codex turns**, не 20 или
30. При 10–12 active turns TTFT median/p90 = **11.684/18.372 с** против **9.273/35.575 с** при
одном: медиана выше на 2.411 с, но tail вдвое ниже. В сопоставимых `xhigh` и full-cycle strata
медиана TTFT не выросла: `xhigh` **9.827→9.691 с**, full-cycle **9.403→9.708 с**. Model output
throughput не упал, а вырос **28.296→32.107 output tokens/s**. [M1][M2]

Почему high-concurrency turn в целом длился 415 с против 109 с: он делал больше работы — median
tool rounds **22 против 4**, output **13 740 против 2 928**, aggregate input **1.95M против
1.01M**. Final wall вырос 3.83× при output 4.69× и tool rounds 5.5×. Это workload composition,
не признак замедлившегося token stream. [M2]

**Подтверждённый резкий эффект десятков процессов — локальное давление на ноутбук.** До #111
idle Codex не hibernate: на границе постановки было 109 sessions / 62 Codex-related processes,
3.4 GiB RSS, 10 GiB swap и load до 13, но точных active turns в этот момент было только **4**.
Через семь минут: 16 native roots + 16 Node + 17 helpers = 49 процессов, 3.324 GiB RSS, 11 GiB
swap, load 3.53/2.75/4.22, active turns **8**. Значит большинство процессов не равно отдельным
provider calls; они всё равно создают memory/swap pressure и правдоподобно тормозят весь desktop.
[H1][M2]

**Exact cause сегодняшнего “резко” остаётся UNCERTAIN:** нет синхронного исторического ряда
CPU/RAM/swap/process/proxy для каждого turn и нет ни одного 20+ active-turn интервала. По имеющимся
данным наиболее вероятна смесь local memory/swap pressure и более тяжёлых одновременно запущенных
workloads, а не proxy capacity, account throttling или Orchestra stdio.

Confidence:

- **CONFIRMED** — process/session count не равен active turns; max exact active=12; bucket metrics.
- **LIKELY** — local process memory/swap объясняет system-wide/UI slowness.
- **REFUTED для observed 10–12 cohort** — резкая provider queue/account throttle и большой stdio
  penalty.
- **UNCERTAIN** — историческая proxy saturation и поведение при 20+ active turns.

## Вопрос и гипотезы

- **Context:** standalone/одиночный Codex нормален; при ~30 живых Codex processes/sessions всё
  ощущается резко медленнее.
- **Change under test:** active Codex turn concurrency, отдельно от process/session population.
- **Baseline:** те же historical Codex turns при одном active turn.
- **Outcome:** TTFT/final/tool rounds/tokens, dispatch→app-server start, provider errors/quota,
  process/RSS/swap/load и proxy counters на совпадающей временной границе.

| Hypothesis | Falsifier | Verdict |
|---|---|---|
| H1 local CPU/RAM/process contention | host pressure absent, dispatch/output stream slows only with provider concurrency | LIKELY for desktop; seconds/turn UNCERTAIN |
| H2 proxy saturation/queue | active/rejected/failed stay far below cap or failures occur at low/zero active turns | not supported now; historical UNCERTAIN |
| H3 OpenAI account throttling | high-concurrency turns succeed at non-limit quota, errors cluster elsewhere | REFUTED for 10–12 cohort |
| H4 provider model queue | TTFT/tokens-per-second degrade consistently within role/effort | REFUTED for 10–12 cohort |
| H5 Orchestra stdio/process contention | dispatch→task_started or local JSON-RPC grows to seconds | REFUTED as large contributor |
| H6 workload composition | final wall grows without more tools/output/input | SUPPORTED: high cohort did 4–5.5× more work |

## Method

### Frozen retrospective boundary

Cutoff is task #255's `updated_at`: `2026-08-23T13:54:29.852026+00:00`. No model/provider call,
load test, proxy switch, config mutation or service mutation was run.

The interval source is native rollout JSONL:

1. Load Codex `turn_usage` rows at/before cutoff for per-turn model/tokens/errors/quota.
2. Scan the existing rollout corpus (≈1.93 GB; exact file/byte count frozen in [M2]) for matching native
   `task_started`, `turn_context`, `task_complete`.
3. Use rollout timestamps and `task_complete.duration_ms/time_to_first_token_ms`; sort and overlap
   strictly by `ts`.
4. Count active interval at each start as `start <= instant < end`; bucket 1, 2–4, 5–9, 10–19,
   20+.
5. Count DB tool events and latest user-message→native-start dispatch on the same session/interval.

Why DB `codex turn=... started` was not used as the interval start: for 1 122 matched markers,
lag from rollout start is median 0.006 s, p90 0.043 s, but max **13 507.561 s**. Restarts can replay
a delayed `turn/started`; two initially impossible rows (DB duration below TTFT) exposed this.
The native rollout start/end differs from its own duration field by at most 0.431 s. [M2]

Coverage: 1 333 Codex usage rows, 1 280 exact complete rollout intervals, 53 usage rows without a
complete local rollout interval. All bucket conclusions are for the 1 280 exact intervals.

### Required table

The full mandatory table — UTC range, active turns, process snapshot boundary, model/effort/tier/
task class, TTFT/final/tools/tokens, host pressure, proxy counters, provider evidence, controls and
source — is [M1]. Machine-readable per-turn rows are [M3].

| Active turns | n | TTFT med/p90, s | final med/p90, s | dispatch med/p90, s | tools med | input med | output med | output tok/s med | errors |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 329 | 9.273 / 35.575 | 108.517 / 798.140 | 0.024 / 1.924 | 4 | 1 008 292 | 2 928 | 28.296 | 58 |
| 2–4 | 609 | 10.917 / 39.187 | 123.528 / 1 053.817 | 0.027 / 0.778 | 4 | 941 680 | 3 009 | 27.904 | 35 |
| 5–9 | 320 | 10.697 / 27.802 | 164.660 / 1 110.835 | 0.038 / 0.541 | 6 | 1 172 374 | 4 767 | 29.516 | 2 |
| 10–19 (observed 10–12) | 22 | 11.684 / 18.372 | 415.173 / 1 532.883 | 0.133 / 0.623 | 22 | 1 949 378 | 13 740 | 32.107 | 0 |
| 20+ | 0 | — | — | — | — | — | — | — | — |

Historical `tier` is not persisted by `turn_usage` or `turn_context`, so the required table marks
it unobserved. Current managed config is Standard, but that is not projected backward. Task class
is the stable Orchestra role plus task-id presence; prompt semantics are not reconstructed.

## Findings

### F1 — “30 processes” was never “30 active model turns”

The exact maximum is 12 active turns. The 20+ bucket is empty. Process snapshots prove the
denominators diverge:

- at #111 task creation (`2026-08-01T06:49:12Z`), exact active turns=4 while the supplied snapshot
  says 109 live sessions / 62 Codex-related processes, 3.4 GiB RSS, 10 GiB swap, load up to 13;
- at the second `06:56Z` snapshot, exact active turns=8 while process tree=16 native +16 Node +17
  helpers=49, RSS 3.324 GiB, swap 11 GiB, load 3.53/2.75/4.22;
- the first Aug-01 active=10 start is 13 minutes later, without a synchronous process snapshot.

#111 traces the mechanism: persistent Codex had inherited `hibernate=False`; idle roots and MCP
descendants accumulated until the task implemented process-scope hibernation. [H1]

**CONFIRMED, tier 1 saved snapshot + exact rollout overlap.** The process population caused real
memory/swap pressure, but the absence of per-process CPU samples prevents attributing load=13 to
Codex CPU specifically.

### F2 — high active-turn final wall is heavier work, not slower streaming

High cohort vs one active turn:

- final median 415.173/108.517 = 3.83×;
- tools 22/4 = 5.5×;
- output 13 740/2 928 = 4.69×;
- aggregate input 1.95M/1.01M = 1.93×;
- output rate 32.107/28.296 = 1.14×, not a slowdown.

Within the same Aug-01 06:00–09:00 UTC window, TTFT medians were 19.807 (n=1), 13.156 (n=8),
11.051 (n=123), 11.669 (n=19) across the four observed buckets — not monotonic. In full-cycle,
TTFT 1→10–19 was 9.403→9.708 s; in xhigh, 9.827→9.691 s. [M2]

**CONFIRMED descriptively; causal task-mix adjustment remains incomplete.** Worker strata do get
slower (6.241→12.696 s), but their output/tools simultaneously rise 862→15 677 and 0→29, so they
do not isolate concurrency.

### F3 — account/provider throttling is absent at the high-concurrency boundary

All 22 turns at active 10–12 completed successfully; recorded Codex primary utilization ranged
18–56%. Error rate falls from 58/329 at concurrency 1 to 0/22 at 10–12. Among low-concurrency
errors, 30/58 at concurrency 1 and 11/35 at 2–4 have quota≥99%; rate-limit episodes are a separate
quota-bound state, not a high-concurrency state. [M2][M3]

Retained Orchestra journal begins only at `2026-08-23T11:14:41Z`. Its 29 distinct seconds with
`Codex usage fetch failed` occurred at exact active-turn counts `{0:21, 1:1, 2:6, 3:1}`. These are
WHAM usage-endpoint failures around restart/recovery, not model-response failures, and they do not
rise with active turns. [M2]

**REFUTED for observed 10–12 cohort, tier 1.** This does not prove an undocumented account limit
cannot start above 12; history has no 20+ cell.

### F4 — no observed provider queue signature

A provider queue should inflate model-start TTFT and/or reduce token throughput across comparable
roles/efforts. Instead:

- xhigh TTFT: 9.827 / 11.221 / 10.139 / 9.691 s;
- full-cycle TTFT: 9.403 / 10.264 / 10.093 / 9.708 s;
- overall p90 TTFT at 10–12 is 18.372 s, below p90 35.575/39.187 at 1/2–4;
- high-concurrency output throughput is highest.

**REFUTED as the sharp slowdown mechanism for observed 10–12, LIKELY not absent universally.**
Provider noise remains visible inside every bucket; the data cannot locate that noise within the
provider stack.

### F5 — Orchestra stdio/dispatch does not supply the missing hundreds of seconds

Latest user-message→native `task_started` at 10–12 active turns is median 0.133 s, p90 0.623 s.
Lower buckets are also subsecond in median; high p90 is not inflated. #240 independently measured
local Python JSON-RPC median 0.058 ms and real `turn/start` ack 6–21 ms. [M1][H2]

**REFUTED as a large contributor.** Dispatch includes quota admission/backend wake as well as stdio,
so it is an upper bound on pure stdio for covered rows, not a microbenchmark of every code path.

### F6 — proxy saturation is not demonstrated; current counters give only a bounded control

The historical high-concurrency windows predate the current proxy manager and have no accepted/
failed/rejected/queue time series. Therefore historical proxy saturation is **UNCERTAIN**.

The read-only current snapshot at `2026-08-23T14:15:52Z` is a negative control, not a historical
join: endpoint `127.0.0.1:12339`, Contabo, 22 active / 512 max connections, 4 206 accepted, 0 failed,
0 rejected, semantic backend response 401 in 1 780 ms. The gateway has a hard capacity/reject
counter, not a historical queue counter (`gateway.py:124-137,284-286`). [M1][H3]

**REFUTED for that snapshot; UNCERTAIN for July/Aug-01.** The same snapshot's host load changed
rapidly while proxy failure counters stayed zero, which argues against treating loadavg as proxy
queue depth.

### F7 — local resource pressure best explains “everything” slowing, not model TTFT

3.3–3.4 GiB RSS plus 10–11 GiB swap from Codex-related process trees is sufficient evidence of
real host pressure. The process tree multiplied each root into Node/native/helper/MCP children.
This matches a slow desktop, context switches and swap stalls. At the same time, subsecond dispatch
and non-degrading provider output throughput show that the saved high-turn cohort did not translate
that pressure into a sharp Codex network/model slowdown.

**LIKELY for system-wide responsiveness; UNCERTAIN for exact seconds added to an individual Codex
turn.** No synchronous per-turn CPU, MemAvailable, PSI or swap-in series survives.

## Counter-evidence and limits

- High concurrency n=22 occurs only in two early windows (20 of 22 on Aug-01); date/provider/task
  composition is confounded.
- 53 Codex usage rows lack a complete local rollout interval and are excluded. Error-rate results
  apply to the exact cohort, not every attempted turn.
- Historical service tier is unobserved.
- Process snapshots and active turns are aligned at two boundaries, but no process snapshot exists
  during the exact 10–12 peak.
- Proxy manager counters reset on restart and do not retain time series; current success cannot
  clear historical proxy behavior.
- Claude/non-Codex concurrent turns are not reconstructed, so cross-provider host/network traffic is
  an unmeasured control. Output volume/rounds/throughput serve only as within-Codex workload controls.
- Current sessions rows are mutable state and were not used to infer historical runtime/model or
  concurrency.

## Smallest future experiment — not authorized or run

History cannot isolate idle process pressure or populate 20+. Two staged experiments minimize Sol
calls and stop as soon as one cause is reproduced:

### Stage A — idle process/local contention, 4 Sol calls

ABAB, one provider call at a time, identical full-role Standard/xhigh PONG/read-only task:

- A: ordinary process population;
- B: ten scratch app-server trees initialized but idle (≈30 Node/native/helper processes), no
  concurrent model turns.

Four calls at #240 D cost ≈`4 × $0.167 = $0.668` API-equivalent (subscription pool use, not cash).
If B repeatedly exceeds A beyond A/A noise while proxy counters remain flat, local contention is
reproduced; stop without Stage B.

### Stage B — provider/proxy active concurrency, 22 Sol calls only if A is negative

One baseline call → ten simultaneous identical isolated calls → one baseline → second ten-call
wave. Exact total 22; estimated `22 × $0.167 = $3.674` API-equivalent. Capture proxy counters and
host counters before/during/after each wave. This populates active=10, the level corresponding to
roughly 30 OS processes in the saved trees. A 20+ arm would require a separate, more expensive
approval.

Stop immediately on any: MemAvailable <4 GiB; swap growth >1 GiB; load1 >12 for two consecutive
10-second samples; proxy rejected/failed increments; any rate-limit/model error; any call >180 s;
or incomplete process cleanup. Never switch proxy/config or restart services inside the experiment.

Both stages require a new explicit user approval. Combined maximum if both run: 26 Sol calls,
≈$4.342 API-equivalent.

## Review gate

- Changed artifacts/consumers: `docs/tasks/255/*` read by the user/orchestrator;
  `docs/kb/codex-runtime.md` read at future memory gates.
- Author metadata: Codex runtime, `gpt-5.6-sol`, from the current session/turn metadata.
- AC: required concurrency table and buckets from exact `ts` intervals; all five hypotheses
  separated; no new provider/model/mutation; future experiment exact calls/price/stops.
- Mechanical check: `python docs/tasks/255/analysis.py`; validate 1 280 CSV rows, max active=12,
  no 20+ rows, table numbers equal JSON, secret-form scan clean.
- **Review: none — explicit #255 instruction forbids all new model/provider calls.** Although Luna
  can otherwise be auto-approved, it is still a new model call and was not run. Sol is forbidden.

## Sources

- [M1] `docs/tasks/255/measurements.md` — mandatory table and source boundaries.
- [M2] `docs/tasks/255/bucket-summary.json` — bucket/strata/journal/proxy aggregates.
- [M3] `docs/tasks/255/turns.csv` — 1 280 exact native intervals and per-turn fields.
- [M4] `docs/tasks/255/analysis.py` — full reproduction from SQLite/rollouts/journal/counters.
- [M5] `docs/tasks/255/verification.md`, `verify.py` — exact mechanical gate and output.
- [H1] `docs/tasks/111/research.md`, `report.md` — saved process/RSS/swap/load snapshots,
  hibernation cause and implementation.
- [H2] `docs/tasks/240/research.md`, `analysis.json`, `measurements.md` — isolated transport/
  app-server/wrapper measurements.
- [H3] existing AI Proxy Manager source/status/journal: `gateway.py:124-137,284-286`, status
  counter snapshot recorded in [M1]/[M2].
- Live SQLite primary source, read-only: `/mnt/data/Projects/Python/orchestra/data/orchestra.db`,
  cutoff above; tables `logs`, `turn_usage`, `sessions`, `tm_tasks`, `tm_projects`.
- Native primary history, read-only: `~/.codex/sessions/**/*.jsonl`, bytes/files recorded in [M2].
- Retained primary journal, read-only: `journalctl -u orchestra`, actual retained range recorded in
  [M2].
