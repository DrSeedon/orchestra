# #312 — Did raising Codex context from 258,400 to 828,400 improve real work?

Research only. Frozen cutoff: `2026-08-24T06:54:34.857943Z`. No provider/model/load test, config change, service change or external write was made.

## Question

- **Context:** Orchestra's ChatGPT-auth Codex CLI/app-server runtime changed from 272,000 raw / 258,400 effective context to 872,000 raw / 828,400 effective context.
- **Change under test:** the configured effective context ceiling and its 784,800 auto-compact ceiling.
- **Baseline:** production turns immediately before the restart, at the old 258,400 ceiling.
- **Outcomes:** actual use above the old ceiling; compact/precompact frequency; terminal delivery proxy; TTFT/final wall; native reader/timeout/error outcomes; and observed account subscription-utilization slope.
- **Decision rule:** configuration is not credited with better work quality unless a human/acceptance outcome exists. It is credited with operational continuity only if real requests exceed the old ceiling and compact pressure falls. Subscription acceleration must appear in a same-plan, same-reset, equal-duration comparison before later workload is considered.

## Hypotheses and falsifiers

1. **H1 — the larger ceiling improves continuity because long threads compact less often.** Falsifier: no post request exceeds 258,400, or compact/precompact outcomes do not fall.
2. **H2 — the larger ceiling increases latency/failures because more history is sent.** Falsifier: post turns below the old request size are slower too, terminal failures rise immediately, and same-session comparisons share one direction after model/effort/role control.
3. **H3 — merely configuring 828,400 accelerates subscription consumption.** Falsifier: equal-duration windows in the same quota revision consume the same percentage, while later acceleration coincides with more work, diagnostics, images or uncovered account surfaces.
4. **H4 — raw pre/post differences are workload/environment confounding, not a clean ceiling effect.** Falsifier: the sign survives request-size, same-session/model/effort/role matching, scheduled/unscheduled reset separation, and removal of the 24.08 image incident and diagnostic tasks.

## Method and evidence boundary

The WAL-safe frozen backup was created with `sqlite3.Connection.backup()` from a read-only source. It is 485,879,808 bytes, SHA-256 `b938594cbb931e6505bc547e21ba6a76fb3f083a36f125c03c237841e823b821`, and passes `PRAGMA quick_check`. `backup-manifest.json` contains table counts and maxima. The full backup stays in ignored `private/` because it contains user content; all committed derivatives are sanitized. [4]

`analysis.py` joins 425 Codex `turn_usage` rows after the scheduled reset to native rollout records. Historical model comes from `turn_usage`; effort, effective ceiling, task start/end, TTFT, wall and maximum single-request context come from the same turn's `turn_context`, `task_started`, `task_complete` and `token_count`. Current `sessions.model` is never read. Historical `task_id` comes from `turn_usage`; role/pipeline are cutoff session metadata because Orchestra does not event-source their changes, so a later mutation would make the historical class `UNKNOWN`. The scan covers 1,321 rollout files / 2,279,614,107 bytes; 363/425 rows have complete native intervals. [4]

The primary windows are equal at 5,734.691 seconds:

- pre: `2026-08-23T07:28:43.476971Z → 09:04:18.168Z`;
- post: `2026-08-23T09:04:18.168Z → 10:39:52.859029Z`.

Both use `plan_type=pro`, quota revision `2026-08-30T07:28:42Z`, and precede #240's direct benchmark calls, later fleet-wide failures, the unscheduled 24.08 reset and the image-heavy incident. `turns.csv` is the requested row-level table; `measurements.md` defines every column and denominator. [4]

## Findings

### F1 — the production change point is exact

Commit `c3e66f162ce324877e245d4c75b298a229a68672` was recorded at `2026-08-23T08:25:01Z`. The last completed old-ceiling task started at `08:55:45.125Z` with native `model_context_window=258400`. Persisted logs record the restart action at `09:03:34.834Z` and restored-session marker at `09:04:11.936Z`. The first new-ceiling task began at `09:04:18.168Z` with `model_context_window=828400`; no observed task interleaves the two ceilings. [4][5]

OpenAI's current model card lists GPT-5.6 Sol's API context window as 1,050,000, while the configuration reference defines `model_context_window` as the context available to the active model and `model_auto_compact_token_limit` as the automatic compaction threshold. The 828,400 value is therefore the measured ChatGPT-auth CLI effective surface, not the API card's total. [1][2]

**CONFIRMED — tier 1 local native measurements plus tier 2 official configuration semantics.**

### F2 — real turns used the added context and compact pressure fell

In the equal-duration post window, 19/34 complete turns exceeded the old 258,400 effective limit in at least one native model request; 15/34 exceeded 272,000 and the maximum was 654,999. Pre had 0/31 above 258,400 and max 227,607. Turns with a compact outcome fall 4→1; precompact outcome falls 6→4. [4]

This proves the larger ceiling was not merely configured: it carried requests that could not fit under the old effective ceiling. It also proves an operational continuity gain—fewer immediate compactions—not better semantic output.

**CONFIRMED for use; LIKELY for continuity benefit — tier 1 measurements, but compact frequency has only one short pre/post interval.**

### F3 — human-quality improvement is UNKNOWN

The available outcome proxy changes from 30/31 to 35/35 `end_turn`, but no row has a human score, acceptance-command result tied to that turn, or blinded quality judgment. Assistant text, tool rounds, `end_turn` and task status at the frozen cutoff prove delivery, not correctness. The post task/role mix also changes sharply: orchestrator/full-cycle/worker 24/5/2 → 15/20/0; output median rises 1,737→4,898 and tool rounds 4→6. [4]

**UNKNOWN — telemetry has no valid quality oracle.**

### F4 — raw latency rose, but the ceiling's causal contribution is unresolved

Raw TTFT median/p90 rises 12.371/32.044→16.525/94.146 seconds; final wall median/p90 rises 69.796/771.294→158.325/1,133.810 seconds. At the same time, aggregate turn-input median rises 3.98×, maximum single-request median 2.30×, output median 2.82×, and tool rounds 1.5×. [4]

The size stratum breaks a simple configuration-overhead story. For Sol/xhigh requests at or below 258,400, median TTFT is 13.480 seconds pre and 11.956 post. Post requests above the old ceiling have 17.710-second median TTFT and 210.127-second wall, versus 11.956/126.053 below it. Larger actual histories correlate with slower turns; the setting alone does not slow requests that remain small. [4]

The four same-session/model/effort/role controls have mixed TTFT signs: Orchestra 13.480→20.193, COG 18.442→66.079, identity-baseline 8.068→7.715, comfy-image 11.262→10.468 seconds. Post also has nine turns with reconnect/connect outcomes versus three pre. [4]

**UNCERTAIN for causal latency; CONFIRMED for the raw association — direct measurements, but task size/network/state change simultaneously.**

### F5 — immediate terminal failures did not increase; later failures are clustered incidents

The primary window improves from 30/31 to 35/35 terminal `end_turn`. In the longer post period before the unscheduled reset, 25/252 turns are interrupted. Of those, 12 occur in a fleet-wide `server_error` cluster at `11:21–11:24Z`, and 10 at the fleet-wide server/restart cluster at `16:42Z`; only three lie outside both clusters. These timestamps affect many sessions and are not specific to context size. [4]

**REFUTED for an immediate general failure increase; UNCERTAIN for rare near-ceiling histories.**

### F6 — the 24.08 image-heavy incident is real counter-evidence, not a clean ceiling estimate

After the unscheduled reset and outside both core windows, COG records four oversized-reader errors from `05:14:41Z`; comfy-image records native compact starts at `05:17:20Z` and `05:19:03Z`, a blank-detail compact failure at `05:21:04Z` consistent with the known 120-second budget, and a later successful compact at `05:30:54Z`. [4][6]

The incident shows a post-change risk: longer image-heavy histories can reach a state that stresses resume JSONL framing and compact. It does not isolate the context ceiling because inline image payload, 16 MiB reader framing, restart/resume, and compact timeout change together. The affected sessions are explicitly flagged and removed in sensitivity cohorts.

**CONFIRMED incident, UNCERTAIN ceiling causality — tier 1 logs/native timeline, multi-factor mechanism.**

### F7 — subscription consumption did not accelerate immediately; it did later, for non-isolated reasons

Both primary windows consume exactly +3 percentage points of the same Pro quota revision over 1.593 hours: 1.883 pp/h before and after. This refutes an immediate effect from merely raising the configured ceiling. [4]

The later post slope reaches +47 pp over 8.279 requested hours (5.677 pp/h), so overall consumption did accelerate later. It cannot be causally assigned to the ceiling:

- the post-before-reset ledger contains 252 turns (202 Sol, 50 Luna), 1.053B aggregate input and 2.434M output tokens;
- #240 adds 28 benchmark model turns and two reviewer calls outside `turn_usage`; known direct #240 use is 3,157,712 input, 1,965,824 cached and 26,228 output tokens, plus two warmups without token fields;
- the account counter covers laptop/desktop/other surfaces that the VPS row ledger does not;
- image generation shares the general Codex allowance; official OpenAI documentation says it uses included limits 3–5× faster on average than similar non-image turns; [3]
- a new quota revision is first observed at `2026-08-24T03:47:54Z`, resetting utilization from the prior 51% range to 4%. No redemption message survives, so the cause is `UNKNOWN`; post-reset rows are not joined to the old denominator. [4]

**REFUTED for immediate acceleration; CONFIRMED for later aggregate acceleration; UNKNOWN for causal apportionment to context.**

### F8 — API virtual dollars, ChatGPT credits and subscription percentage are different measures

OpenAI's API model page prices Sol at $4/M input, $0.40/M cached input and $20/M output, with a >272K API multiplier of 2× input and 1.5× output for the full request. The current ChatGPT/Codex rate card instead expresses Sol as 100/10/500 credits per million input/cached/output and Luna as 5/0.5/30; available credits extend work after included limits. [1][3]

Accordingly, `turn_usage.cost_usd` remains an API-equivalent display. `credit_equivalent` is a transparent rate-card calculation. Neither replaces the observed subscription percentage. In the core windows, tracked credit-equivalent sums rise 745.963→1,767.122 and virtual dollars $38.295→$70.685 even though subscription utilization rises +3 pp in each. Rounding, reporting lag and uncovered account surfaces prevent converting one series into the other here. [4]

**CONFIRMED distinction — tier 2 official semantics plus tier 1 divergent local series.**

## Counter-evidence

- The raw latency increase is large enough that "no downside" would be false: post TTFT median is +34% and p90 nearly 3×. It is also concentrated in larger actual requests and reconnect-heavy turns, so "the setting itself caused it" is unsupported.
- The post image-heavy failure family is a meaningful warning. Excluding it is necessary for the primary estimate, but it must not be erased: it may be an edge exposed by allowing history to grow farther before compact.
- Compact outcomes fall in only a 95.6-minute paired window; one different work period could change 4→1.
- The sensitivity cohort excluding diagnostic and incident sessions is badly unbalanced (n=9 pre, n=24 post) and still changes task mix. It cannot rescue a causal quality claim.
- The later 5.677 pp/h quota slope argues against declaring consumption harmless. It proves fleet/account burn was high, just not why.

## Verdict

The 3.21× effective-context increase produced a **real operational gain**: 19/34 immediate post turns used requests above the old ceiling and compact outcomes fell 4→1. Whether the resulting work was semantically better is **UNKNOWN** because no quality oracle exists.

Terminal failures did **not** increase in the matched immediate window (30/31→35/35). Raw TTFT and wall did increase, but the post workload was materially larger and same-session signs are mixed; the ceiling's independent latency effect remains **UNRESOLVED**. A distinct image-heavy resume/compact failure family is confirmed after the later reset and remains the main counter-risk.

Subscription utilization did **not** accelerate immediately: both same-plan/same-revision windows burn +3 pp in equal time. It accelerated later to 5.677 pp/h, but that period combines much more work, #240's off-ledger diagnostics/reviews, image activity, fleet incidents, other account surfaces and an unscheduled reset. The saved telemetry cannot apportion that later burn causally to the context ceiling.

## Gaps and smallest next evidence

- **Quality:** require an acceptance/human score tied to each turn or task; current task status is not enough.
- **Causal latency:** passive future telemetry should retain `max_request_input_tokens`, model/effort/task class, TTFT and provider reconnect state for at least one full quota revision. Compare within the same session/task class below/above 258,400 before considering a paid active experiment.
- **Account coverage:** capture machine/surface identity with every subscription sample; without it, account-wide percentage cannot be reconciled to VPS rows.
- **Reset cause:** the new `2026-08-31T00:51:01Z` revision is observationally an unscheduled provider-side reset; the trigger is unknown.
- **Image edge:** preserve payload-size and compact-stage telemetry separately from token context. A context ceiling and a JSONL byte ceiling are different resources.

No implementation plan or recommendation is authorized in this phase.

## Affected files, risks and edge cases

- Evidence owners only: `docs/tasks/312/*`, `docs/kb/codex-runtime.md`.
- Runtime seams relevant to any future work: managed config carry/refresh in `app/backend_codex.py`; compact policy/status in `app/session.py`; historical `turn_usage`/`usage_snapshots` recording.
- Risks: cumulative per-turn token totals mistaken for context; current session model mistaken for historical model; rounded quota points treated as exact credits; reset revisions joined; direct CLI/laptop use omitted; image bytes conflated with tokens; `end_turn` called quality.

## Review gate

No Luna/Sol/model review was run: the #312 assignment explicitly forbids auxiliary model calls. Under the `codex-debate` fact-extraction route, mechanical completeness is the final gate here. Exact command/output:

```text
$ python3 docs/tasks/312/verify.py
PASS #312: backup=b938594cbb931e6505bc547e21ba6a76fb3f083a36f125c03c237841e823b821 rows=425 unique=425 rollout_complete=363 old/new=31/363 core=31/35 quota_delta=3/3 incident_rows=9 secret_scan_files=11
```

## Sources

1. **Primary official, opened 2026-08-24.** OpenAI Developers, GPT-5.6 Sol model card — https://developers.openai.com/api/docs/models/gpt-5.6-sol
2. **Primary official, opened 2026-08-24.** OpenAI / ChatGPT Learn, Codex Configuration Reference — https://learn.chatgpt.com/docs/config-file/config-reference
3. **Primary official, opened 2026-08-24.** OpenAI / ChatGPT Learn, Codex Pricing and credits — https://learn.chatgpt.com/docs/pricing
4. **Tier 1 local measurement.** `docs/tasks/312/backup-manifest.json`, `change-point.json`, `turns.csv`, `matched-sessions.csv`, `summary.json`, `measurements.md`; generated by `analysis.py` and checked by `verify.py`.
5. **Tier 1 local implementation/change evidence.** Commit `c3e66f162ce324877e245d4c75b298a229a68672`; `docs/tasks/209/research.md`.
6. **Tier 1 local incident evidence.** Frozen `logs` rows summarized in `summary.json:image_incident`; exact native timeline preserved in #306/#307 agent handoff and task logs.
