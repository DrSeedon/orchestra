# #312 measurements — 258,400 → 828,400 effective Codex context

All timestamps are UTC. No provider/model call was made for this task.

## Frozen evidence boundary

- Source: `/mnt/data/Projects/Python/orchestra/data/orchestra.db`.
- Snapshot method: Python `sqlite3.Connection.backup()` from a `mode=ro` connection; this includes WAL state without copying a live `.db` file.
- Start/end: `2026-08-24T06:54:13.548006Z` → `2026-08-24T06:54:34.857943Z`.
- Private backup: `private/orchestra-20260824.sqlite`, 485,879,808 bytes, SHA-256 `b938594cbb931e6505bc547e21ba6a76fb3f083a36f125c03c237841e823b821`, `PRAGMA quick_check=ok`.
- Public provenance: `backup-manifest.json`. The full backup is ignored because it contains user content and may contain credentials; all tracked derived rows are sanitized.
- Native timing/context scan: 1,321 rollout files, 2,279,614,107 bytes; 394 target turns found, 363/425 DB rows have complete native `task_started→task_complete` intervals. No conflicting native records.

## Exact change point

| Evidence | UTC | Value |
|---|---|---|
| implementation commit | 2026-08-23 08:25:01 | `c3e66f162ce324877e245d4c75b298a229a68672`, `#209: maximize managed Codex context` |
| last completed old-ceiling task start | 2026-08-23 08:55:45.125 | `task_started.model_context_window=258400` |
| user requests restart after broken frontend | 2026-08-23 09:02:34.711 | persisted `user_message` |
| orchestrator announces restart action | 2026-08-23 09:03:34.834 | persisted assistant text |
| restored-session marker | 2026-08-23 09:04:11.936 | `[system] Orchestra server restarted` |
| first new-ceiling task start | 2026-08-23 09:04:18.168 | `task_started.model_context_window=828400` |

The gap between the last old and first new native starts is 513.043 seconds. The current journal begins at the later boot `2026-08-23T11:25:42Z`, so the earlier systemd `Started` line has expired; the DB restoration marker plus native rollout fields bound the production change point. The setting is 272,000 raw / 258,400 effective before and 872,000 raw / 828,400 effective after; new auto-compact ceiling is 784,800.

## Row-level table contract

`turns.csv` has 425 Codex `turn_usage` rows from the clean scheduled reset through the frozen cutoff. Its columns satisfy the requested schema:

| Requested field | Row-level columns / source |
|---|---|
| session/turn ts | `session_id`, `event_id`, `usage_ts`, native `start_ts`, `end_ts` |
| project/worker | `project` from historical `turn_usage.scope`/project mapping; `worker` from immutable session identity |
| historical model/effort | `model` from `turn_usage`; `effort` and `rollout_model` from that turn's native `turn_context`; never `sessions.model` |
| task/pipeline class | `task_id` from `turn_usage`; `role`, `task_pipeline_class`, `task_status_at_cutoff` |
| configured ceiling | native `configured_effective_ceiling`; `configured_raw_ceiling` only when the effective value uniquely maps to the recorded config |
| actual tokens | `actual_input_tokens_total`, `actual_cached_input_tokens`, derived `actual_uncached_input_tokens`, `actual_output_tokens`; plus native maximum single request (`max_request_*`) |
| compact/connect/error outcomes | status-envelope `precompact_outcome`, `compact_outcome`, `resume_outcome`, `connect_outcome`, `reader_outcome`, `timeout_outcome`, `error_outcome` |
| work/outcome proxy | `tool_rounds`, `assistant_text_bytes`, `ok`, `stop_reason`, `final_outcome_proxy`; no quality judgment is inferred |
| latency | native `wall_seconds`, `ttft_seconds` when complete rollout telemetry exists |
| quota/revision/reset | nearest prior valid `quota_plan`, `quota_utilization`, `quota_revision`, `quota_reset_cause` |
| coverage | `machine_account_coverage`, `analysis_window`, `core_cohort`, `sensitivity_exclusion`, `image_incident_period` |

The per-turn status envelope is `(previous native turn end for the same session, current native turn end]`; it assigns between-turn compact/reconnect events to the next turn once. Only `status/error/warning` logs classify failures; free text and tool output cannot self-confirm a failure. `resume_outcome` additionally admits the exact server-restored system message.

`input_tokens` in `turn_usage` is the aggregate over all model requests in one agent turn, not the configured context ceiling. `max_request_input_tokens` comes from native `token_count.last_token_usage.input_tokens` and is the comparable actual single-request context.

## Primary equal-duration comparison

The pre interval begins at the first persisted zero after the scheduled weekly reset. The post interval has the identical 5,734.691 seconds. Both are `plan_type=pro`, share reset revision `2026-08-30T07:28:42Z`, precede the #240 diagnostic burst, the unscheduled 24.08 reset and the image-heavy incident.

| Metric | pre 258,400 (`07:28:43.477→09:04:18.168`) | post 828,400 (`09:04:18.168→10:39:52.859`) | Observed delta |
|---|---:|---:|---:|
| DB turns / complete native rows | 31 / 30 | 35 / 34 | +4 / +4 |
| terminal `end_turn` | 30/31 (96.8%) | 35/35 (100%) | +3.2 pp; one pre interrupt |
| model mix | Sol 29, Luna 2 | Sol 34, Luna 1 | not identical |
| role mix | orchestrator 24, full-cycle 5, worker 2 | orchestrator 15, full-cycle 20 | strongly shifted |
| TTFT median / p90, seconds | 12.371 / 32.044 | 16.525 / 94.146 | +34% / +194% |
| final wall median / p90, seconds | 69.796 / 771.294 | 158.325 / 1,133.810 | +127% / +47% |
| tool rounds median | 4 | 6 | +50% |
| aggregate turn input median | 392,031 | 1,558,785 | 3.98× |
| max single-request input median / p90 | 115,213 / 212,222 | 265,431 / 510,943 | 2.30× / 2.41× |
| output median | 1,737 | 4,898 | 2.82× |
| turns with compact outcome | 4 | 1 | −3 |
| turns with precompact outcome | 6 | 4 | −2 |
| turns with connect/reconnect outcome | 3 | 9 | +6; post network/restart noise |
| status/log error outcome | 3 | 0 | −3 |
| tracked ChatGPT credit-equivalent sum | 745.963 | 1,767.122 | 2.37× |
| recorded API-virtual dollars | $38.295 | $70.685 | 1.85× |
| subscription utilization | 0→3% | 3→6% | **+3 pp in each**, 1.883 pp/h |

The workload changed at the same boundary. Post turns asked the model to do more: larger histories, 50% more tool rounds and 2.82× more output. Therefore the raw wall/TTFT difference is not a causal context-setting estimate.

## Did the larger window get used?

- 19/34 complete post turns had a maximum single request above the old 258,400 effective limit; 15/34 were above 272,000; max was 654,999. Pre had 0/31 above 258,400 and max 227,607.
- In the same Sol/xhigh stratum, all 29 pre turns were below the old ceiling. Post splits into 15 below/equal and 18 above:

| Sol/xhigh request-size stratum | n | max-request median | TTFT median / p90 | wall median | tools median | completion |
|---|---:|---:|---:|---:|---:|---:|
| pre ≤258,400 | 29 | 117,547 | 13.480 / 33.893 | 78.893 | 4 | 29/29 |
| post ≤258,400 | 15 | 149,024 | 11.956 / 66.072 | 126.053 | 6 | 15/15 |
| post >258,400 | 18 | 352,444 | 17.710 / 94.146 | 210.127 | 6 | 18/18 |

Post turns that stayed below the old ceiling did not have a higher median TTFT than pre (11.956 vs 13.480 seconds). The slower post group is the group that actually used larger requests; this is correlation with context/workload size, not proof that the configured ceiling itself adds latency.

## Within-session matched control

Four same-session/model/effort/role strata have turns on both sides:

| worker | pre/post n | max-request median pre→post | TTFT median pre→post | wall median pre→post | tools median pre→post |
|---|---:|---:|---:|---:|---:|
| Orchestra-orchestrator | 3/5 | 214,738→259,272 | 13.480→20.193 | 294.472→280.751 | 18→11 |
| COG-second-brain-orchestrator | 4/6 | 180,935→550,274 | 18.442→66.079 | 399.919→635.834 | 15→16 |
| identity-baseline | 5/18 | 193,564→268,722 | 8.068→7.715 | 399.633→129.738 | 13→6 |
| comfy-image-orchestrator | 17/4 | 99,509→148,246 | 11.262→10.468 | 45.771→18.955 | 3→1 |

TTFT/wall direction is mixed: two sessions speed up and two slow down. Counts and tasks per session remain badly imbalanced, so this falsifies a common-sign latency claim but does not estimate quality.

## Failures beyond the immediate window

- Before the unscheduled 24.08 reset, the entire post period has 227/252 `end_turn` (90.1%). Of 25 interruptions, 12 fall in the fleet-wide `server_error` cluster `11:21–11:24Z`, and 10 fall at the fleet-wide server/restart cluster `16:42Z`; only 3 are outside those two timestamps. These are not context-window-specific failures.
- The immediate equal-duration window has no failure increase (30/31 → 35/35).
- Compaction pressure decreased immediately (compact outcome 4→1), while 19 post turns used requests impossible under the old effective ceiling. This is the clearest operational continuity gain.
- A human/acceptance-scored work-quality outcome does not exist in telemetry. `end_turn`, assistant bytes and eventual task status are delivery proxies, not proof that work improved.

## Subscription consumption and coverage

The immediate matched window does **not** show acceleration: both sides consume exactly 3 percentage points of the same Pro quota revision in 1.593 hours. Later post consumption does accelerate: the last valid old-revision anchor is 50% at `17:10:36Z`, a +47 pp rise from the 3% pre-restart anchor over 8.279 requested hours (5.677 pp/h). That later slope is not attributable to the ceiling:

- the post-before-reset ledger contains 252 turns, 202 Sol + 50 Luna, 1.053B aggregate input tokens and 2.434M output tokens;
- #240 alone adds 28 benchmark model turns (26 token-bearing raw rows + two unmeasured reconnect warmups) and two later reviewer calls outside `turn_usage`; known #240 direct usage is 3,157,712 input, 1,965,824 cached (nine raw cache fields missing), and 26,228 output tokens;
- subscription utilization is account-wide, while `turn_usage` is VPS/Orchestra-only; standalone laptop/desktop and other account surfaces are not recorded here;
- image generation counts toward the same general usage limit and the official docs say it uses included limits 3–5× faster on average than similar turns without image generation; the post period contains image-heavy work;
- the 24.08 counter jumps to a new reset revision (`2026-08-31T00:51:01Z`) between retained samples. No redemption message is retained, so its cause is `UNKNOWN`; rows after it are a separate stratum.

`api_virtual_usd` is the Orchestra/API-equivalent display and not a subscription debit. `credit_equivalent` applies the current official ChatGPT token rate card (Sol 100/10/500 credits per million uncached/cached/output; Luna 5/0.5/30). Neither is substituted for observed subscription percentage.

## Required 24.08 image-heavy incident stratum

The incident is outside both core windows and after the unscheduled reset. It is retained as counter-evidence, not blended into the pre/post estimate:

- COG: four `oversized_reader_failure` error rows from `05:14:41Z` through `05:20:30Z` on `thread/resume` history.
- comfy-image-orchestrator: compact starts `05:17:20Z` and `05:19:03Z`; `native Codex compact failed:` at `05:21:04Z` after the known 120-second budget; a later retry starts `05:30:31Z` and completes `05:30:54Z`.
- These failures show a real post-change risk at large image-heavy histories. They do not isolate the ceiling: persisted inline image payload, 16 MiB JSONL reader framing, a restart, and compact timeout all change simultaneously.

Machine-readable event rows are in `summary.json:image_incident`; affected sessions are flagged in every row and excluded in the sensitivity cohorts.

## Boundaries

- Historical model comes from `turn_usage` and native `turn_context`, never current `sessions.model`.
- `task_id` is historical from `turn_usage`; `role`/`pipeline` are persisted session metadata at cutoff because those fields are not event-sourced. Any later role/pipeline mutation is unobservable and the class must then be treated as `UNKNOWN`.
- Effort is unavailable for 62/425 rows without a parsed native context; those rows remain `unobserved` and do not enter effort-matched strata.
- TTFT/wall are unavailable for 62/425 rows without a complete native interval.
- Current task status at cutoff is not a historical turn outcome and is labeled as such.
- Quota snapshots are rounded integers and sometimes missing (`provider_usage.codex.windows=[]`); start/end anchors and revision equality are recorded in `summary.json`.
- The tariff change `prolite→pro` on 16.08 predates both core windows; both compared windows are `pro`.
- The full post window crosses an unscheduled reset and cannot be treated as one denominator.
