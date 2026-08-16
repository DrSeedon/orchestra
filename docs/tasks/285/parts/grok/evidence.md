# #285 Grok evidence slice

## Scope and cutoff

- Evidence cutoff: `2026-08-16T08:55:39.261861+00:00` (`usage_snapshots.id=10221`).
- Scope: Grok only. `local_laptop`, `vps_orchestra`, `vps_user_home`, `vps_managed_home`, and scratch controls remain separate contours.
- Database and journal timestamps below are UTC. Host timezone is `Europe/Berlin` (`UTC+02:00` at cutoff), `LocalRTC=no`, `NTPSynchronized=yes`.
- Credential values, tokens, message bodies, and full payment details were not selected or recorded.

## `login_probes`

| contour | ts | source | sanitized_result | classification | evidence |
|---|---|---|---|---|---|
| local_laptop | 2026-08-12 | `docs/tasks/232/research.md` | `grok 0.2.112`; auth file absent; `grok models` printed unauthenticated | `not_authenticated` | Recorded command output; last CLI-home activity was 2026-07-29 |
| local_laptop | 2026-08-13 | `docs/tasks/251/laptop-config-sanitized.md` | Version and config metadata only; no login/model-listing call | `login_not_probed` | Artifact's stated probe boundary |
| local_laptop | 2026-08-16T08:51:53.608473Z | one-shot reverse SSH | Key exchange reset by peer before a remote command ran | `access_transport_failure_current_state_unobserved` | Transport output; no laptop-side state observed |
| vps_orchestra | 2026-08-13T06:38:00.347326Z | `logs.id=94143` | Connect failed: Grok credentials not found; run login first | `credentials_missing` | Session `audit247-grok-probe`, error row |
| vps_orchestra | 2026-08-13 | `docs/tasks/251/research.md` | `grok 1.0.3`; model listing reported logged in and listed 4.6/4.5; auth mode 0600 | `authenticated_model_listing_success` | Sanitized command results; 18 headless rc=0 turns recorded |
| vps_user_home | 2026-08-14T09:24:49Z | `docs/tasks/267/report.md` | OAuth/OIDC metadata had a refresh field; later model listing reported logged in and 4.6 | `oauth_authenticated_model_listing_success` | Auth fields reduced to mode/presence/timestamps |
| vps_scratch_control | 2026-08-14 | `docs/tasks/267/report.md` | Intentionally invalid scratch auth: model listing unauthenticated; ACP required authentication | `invalid_auth_control` | Scratch HOME, separate from both live homes |
| vps_managed_home | 2026-08-14T15:19:49.454Z to 2026-08-16T02:49:51.505Z | managed `unified.jsonl` | Seven `auth.refresh.success` events | `oauth_refresh_success_events` | Full retained managed CLI log, event names/timestamps only |
| vps_user_home | 2026-08-16T08:52:13.719974Z | sanitized metadata probe | Regular 0600 file; OIDC; refresh field present; expiry metadata `2026-08-14T15:24:49.087867335Z` | `credential_metadata_expired_login_not_probed` | Model listing not invoked because it can refresh or mutate auth state |
| vps_managed_home | 2026-08-16T08:52:13.719974Z | sanitized metadata probe | Regular 0600 file; OIDC; refresh field present; expiry metadata `2026-08-16T08:49:51.497093720Z` | `credential_metadata_expired_login_not_probed` | Model listing not invoked because it can refresh or mutate auth state |

## `quota_signals`

The VPS rows compress consecutive identical snapshots while retaining the snapshot-ID range, row count, and endpoints. All successful VPS windows have `window_minutes=10080` and reset `2026-08-16T19:51:48.358179Z`.

| contour | ts | raw_signal | utilization_or_limit | classification | evidence |
|---|---|---|---|---|---|
| local_laptop | 2026-07-28 | Monthly billing: `used=474`, `monthlyLimit=20000`, `usageUnit=modelCalls` | `474/20000 modelCalls` | `provider_monthly_usage_and_limit` | `docs/tasks/95/quota-source.md` |
| local_laptop | 2026-07-27T13:42:49.738Z | Weekly `creditUsagePercent=2` | `2% / 7d` | `provider_weekly_utilization` | `docs/tasks/96-grok-quota/research.md` |
| local_laptop | 2026-07-27T13:44:48.068Z | Weekly `creditUsagePercent=3` | `3% / 7d` | `provider_weekly_utilization` | same |
| local_laptop | 2026-07-27T13:51:10.959Z | Weekly `creditUsagePercent=5` | `5% / 7d` | `provider_weekly_utilization` | same |
| local_laptop | 2026-07-27T14:16:58.952Z | Weekly `creditUsagePercent=6` | `6% / 7d` | `provider_weekly_utilization` | same |
| local_laptop | 2026-07-27T14:35:38.601Z | Weekly `creditUsagePercent=7` | `7% / 7d` | `provider_weekly_utilization` | same |
| local_laptop | 2026-07-27T14:45:24.561Z | Weekly `creditUsagePercent=8` | `8% / 7d` | `provider_weekly_utilization` | same |
| local_laptop | 2026-07-27T14:53:02.852Z | Weekly `creditUsagePercent=9` | `9% / 7d` | `provider_weekly_utilization` | same |
| local_laptop | 2026-07-27T15:41:39.311Z | Weekly `creditUsagePercent=10` | `10% / 7d` | `provider_weekly_utilization` | same |
| local_laptop | 2026-07-27T16:01:25.088Z | Weekly `creditUsagePercent=11` | `11% / 7d` | `provider_weekly_utilization` | same |
| local_laptop | 2026-07-27T16:09:22.940Z | Weekly `creditUsagePercent=12` | `12% / 7d` | `provider_weekly_utilization` | same |
| local_laptop | 2026-07-28T09:45:08.533Z | Weekly `creditUsagePercent=10`; period `2026-07-25T18:49:05.891405Z/2026-08-01T18:49:05.891405Z` | `10% / 7d` | `provider_weekly_utilization` | same |
| vps_orchestra | 2026-08-13T06:53:24.745767Z | 8%; 5 rows through 07:13:35Z | `8% / 7d` | `provider_weekly_utilization` | snapshots 9338–9342 |
| vps_orchestra | 2026-08-13T07:18:38Z | 9% | `9% / 7d` | `provider_weekly_utilization` | snapshot 9343 |
| vps_orchestra | 2026-08-13T07:23:40Z | 11% | `11% / 7d` | `provider_weekly_utilization` | snapshot 9344 |
| vps_orchestra | 2026-08-13T07:28:43Z | 12%; 7 rows through 07:58:55Z | `12% / 7d` | `provider_weekly_utilization` | snapshots 9345–9351 |
| vps_orchestra | 2026-08-13T08:03:58Z | 13%; 58 rows through 12:52:14Z | `13% / 7d` | `provider_weekly_utilization` | snapshots 9352–9409 |
| vps_orchestra | 2026-08-13T12:57:17Z | `PermissionError: token_expired`; 4 rows through 13:11:32Z | unavailable | `telemetry_unavailable_token_expired` | snapshots 9410–9413 |
| vps_orchestra | 2026-08-13T14:11:57Z | 13%; 25 rows through 16:13:43Z | `13% / 7d` | `provider_weekly_utilization` | snapshots 9425–9449 |
| vps_orchestra | 2026-08-13T16:18:46Z | 14%; 46 rows through 20:05:44Z | `14% / 7d` | `provider_weekly_utilization` | snapshots 9450–9495 |
| vps_orchestra | 2026-08-13T20:10:46Z | `PermissionError: token_expired`; 140 rows through 2026-08-14T07:52:41Z | unavailable | `telemetry_unavailable_token_expired` | snapshots 9496–9635 |
| vps_orchestra | 2026-08-14T09:25:57Z | 14%; 3 rows through 09:36:00Z | `14% / 7d` | `provider_weekly_utilization` | snapshots 9654–9656 |
| vps_orchestra | 2026-08-14T09:41:02Z | 15%; 2 rows through 09:46:04Z | `15% / 7d` | `provider_weekly_utilization` | snapshots 9657–9658 |
| vps_orchestra | 2026-08-14T09:51:06Z | 17% | `17% / 7d` | `provider_weekly_utilization` | snapshot 9659 |
| vps_orchestra | 2026-08-14T09:56:08Z | 18% | `18% / 7d` | `provider_weekly_utilization` | snapshot 9660 |
| vps_orchestra | 2026-08-14T10:01:10Z | 19% | `19% / 7d` | `provider_weekly_utilization` | snapshot 9661 |
| vps_orchestra | 2026-08-14T10:06:12Z | 21% | `21% / 7d` | `provider_weekly_utilization` | snapshot 9662 |
| vps_orchestra | 2026-08-14T10:11:15Z | 23% | `23% / 7d` | `provider_weekly_utilization` | snapshot 9663 |
| vps_orchestra | 2026-08-14T10:16:17Z | 27% | `27% / 7d` | `provider_weekly_utilization` | snapshot 9664 |
| vps_orchestra | 2026-08-14T10:21:22Z | 31% | `31% / 7d` | `provider_weekly_utilization` | snapshot 9665 |
| vps_orchestra | 2026-08-14T10:26:24Z | 36% | `36% / 7d` | `provider_weekly_utilization` | snapshot 9666 |
| vps_orchestra | 2026-08-14T10:31:26Z | 41% | `41% / 7d` | `provider_weekly_utilization` | snapshot 9667 |
| vps_orchestra | 2026-08-14T10:36:29Z | 48% | `48% / 7d` | `provider_weekly_utilization` | snapshot 9668 |
| vps_orchestra | 2026-08-14T10:41:31Z | 54% | `54% / 7d` | `provider_weekly_utilization` | snapshot 9669 |
| vps_orchestra | 2026-08-14T10:46:32Z | 61% | `61% / 7d` | `provider_weekly_utilization` | snapshot 9670 |
| vps_orchestra | 2026-08-14T10:51:35Z | 67% | `67% / 7d` | `provider_weekly_utilization` | snapshot 9671 |
| vps_orchestra | 2026-08-14T10:56:37Z | 71% | `71% / 7d` | `provider_weekly_utilization` | snapshot 9672 |
| vps_orchestra | 2026-08-14T11:01:39Z | 73% | `73% / 7d` | `provider_weekly_utilization` | snapshot 9673 |
| vps_orchestra | 2026-08-14T11:06:40Z | 77%; 2 rows through 11:11:42Z | `77% / 7d` | `provider_weekly_utilization` | snapshots 9674–9675 |
| vps_orchestra | 2026-08-14T11:16:44Z | 78% | `78% / 7d` | `provider_weekly_utilization` | snapshot 9676 |
| vps_orchestra | 2026-08-14T11:21:46Z | 79%; 49 rows through 15:23:53Z | `79% / 7d` | `provider_weekly_utilization` | snapshots 9677–9725 |
| vps_orchestra | 2026-08-14T15:28:55Z | `PermissionError: token_expired`; 496 rows through cutoff | unavailable | `telemetry_unavailable_token_expired` | snapshots 9726–10221 |

## Last 20 `real_turns`

Selection: for each `backend_type=grok` session, pair the nth `user_message` with the nth `status` row matching `turn ended (`; exclude identifiable probe sessions `audit247-grok-probe` and `grok-pilot`; take the latest 20 by end timestamp and display chronologically. Source is `logs`; all models are `grok-4.5`, all stop reasons are `end_turn`.

| # | session | user log / UTC | end log / UTC | source_kind | turn $ | session $ | ctx % | Grok 7d % |
|---:|---|---|---|---|---:|---:|---:|---:|
| 1 | grok-impl | 113419 / 10:22:34.712603 | 113644 / 10:25:40.437605 | orchestrator_assignment | 4.82 | 25.08 | 62 | 31 |
| 2 | grok-impl | 113720 / 10:27:05.055787 | 113761 / 10:27:36.851031 | orchestrator_assignment | 1.92 | 27.00 | 63 | 36 |
| 3 | grok-200 | 113469 / 10:23:26.824170 | 113865 / 10:29:25.960153 | orchestrator_assignment | 6.92 | 15.90 | 56 | 36 |
| 4 | grok-200 | 113924 / 10:30:22.839107 | 114078 / 10:33:07.753623 | orchestrator_assignment | 2.63 | 18.53 | 57 | 41 |
| 5 | grok-impl | 113818 / 10:28:59.410586 | 114281 / 10:37:03.033383 | orchestrator_assignment | 14.79 | 41.79 | 75 | 48 |
| 6 | grok-36 | 113940 / 10:30:40.755784 | 114296 / 10:37:27.880343 | orchestrator_assignment | 6.10 | 14.03 | 53 | 48 |
| 7 | grok-200 | 114176 / 10:34:52.878965 | 114341 / 10:38:59.460919 | orchestrator_assignment | 4.92 | 23.44 | 64 | 48 |
| 8 | grok-200 | 114262 / 10:36:24.319015 | 114362 / 10:39:34.365667 | worker_coordination | 1.00 | 24.44 | 65 | 48 |
| 9 | grok-impl | 114090 / 10:33:25.501941 | 114364 / 10:39:34.756418 | orchestrator_assignment | 2.41 | 44.20 | 77 | 48 |
| 10 | grok-impl | 114386 / 10:40:41.026196 | 114847 / 10:46:44.547462 | orchestrator_assignment | 5.30 | 49.50 | 21 | 61 |
| 11 | grok-36 | 114369 / 10:40:22.689579 | 114971 / 10:48:53.957854 | orchestrator_assignment | 11.41 | 25.44 | 63 | 61 |
| 12 | grok-36 | 114960 / 10:48:32.275571 | 115010 / 10:49:25.710755 | worker_coordination | 1.63 | 27.07 | 64 | 61 |
| 13 | grok-200 | 114415 / 10:40:55.990792 | 115224 / 10:54:09.334515 | orchestrator_assignment | 13.01 | 37.45 | 75 | 67 |
| 14 | grok-impl | 114897 / 10:47:39.843635 | 115333 / 10:57:01.750168 | orchestrator_assignment | 2.39 | 51.89 | 34 | 71 |
| 15 | grok-impl | 115006 / 10:49:20.407300 | 115356 / 10:57:42.606987 | worker_coordination | 0.36 | 52.25 | 34 | 71 |
| 16 | grok-36 | 115354 / 10:57:38.873330 | 115367 / 10:58:10.605286 | worker_coordination | 0.34 | 27.41 | 64 | 71 |
| 17 | grok-200 | 115275 / 10:56:04.715346 | 115489 / 11:02:07.290942 | orchestrator_assignment | 4.81 | 42.26 | 79 | 73 |
| 18 | grok-impl | 115377 / 10:58:34.194560 | 115637 / 11:06:26.909799 | orchestrator_assignment | 6.80 | 59.05 | 47 | 73 |
| 19 | grok-200 | 115534 / 11:03:44.570134 | 115727 / 11:10:56.002120 | orchestrator_assignment | 2.80 | 45.06 | 28 | 77 |
| 20 | grok-200 | 115750 / 11:12:08.071386 | 115923 / 11:19:26.115560 | orchestrator_assignment | 3.51 | 48.57 | 41 | 78 |

All 20 dates are `2026-08-14`. Across the six Grok-backend sessions, `logs` contains 36 `turn ended` rows; 36/36 carry a `Grok 7d:` suffix. `turn_usage` contains 0 rows with `runtime='grok'`, and the six sessions' `total_turns` fields sum to 0.

## `error_counts`

| contour | source/window | category | count | classification/evidence |
|---|---|---|---:|---|
| vps_orchestra | `logs`, through cutoff | Grok-session error rows | 2 | One missing-credentials row (`94143`); one missing-required-MCP row (`104357`) |
| vps_managed_home | CLI log, full retained file | error-level rows | 0 | `cli_log_error_level` |
| vps_managed_home | CLI log, full retained file | warning rows | 12 | 10 inference retries; 2 catalog-refresh failures |
| vps_managed_home | CLI log, full retained file | inference retry: request-send error | 5 | transport error |
| vps_managed_home | CLI log, full retained file | inference retry: response-body decode error | 5 | transport error |
| vps_managed_home | CLI log, full retained file | model catalog refresh failed | 2 | `had_real_catalog=false` |
| vps_orchestra | snapshots, first Grok key through cutoff | provider available | 215 | weekly utilization recorded |
| vps_orchestra | same | provider unavailable: `token_expired` | 640 | telemetry unavailable |
| vps_orchestra | same | snapshot lacks Grok provider key | 29 | provider signal absent |
| vps_orchestra | journal, 2026-08-13T00:00Z through cutoff | Grok usage: no OAuth credentials | 191 | telemetry unavailable |
| vps_orchestra | same | Grok usage: OAuth token expired | 767 | telemetry unavailable |
| vps_orchestra | same | billing `?format=credits` HTTP 401 | 189 | billing auth failure |
| vps_orchestra | same | `Grok raw error payload` | 0 | backend terminal-error marker |
| vps_orchestra | same | explicit Grok quota/rate exhaustion signal | 0 | no explicit usage/rate/quota exhaustion marker observed |
| vps_orchestra | journal + sessions | HTTP 429 with “grok” only in session name | 3 | Excluded: `bench-grok` is `backend_type=codex`, model `gpt-5.6-sol` |
| vps_orchestra | Grok journal lines | datacenter/country/region/IP fault marker | 0 | no matching marker observed |

## Retention and gaps

| source | retained/measured range | rows or size | gap measurement |
|---|---|---:|---|
| `logs`, all sessions | 2026-07-27T16:20:40.227730Z to cutoff | 117,014 rows | none asserted outside retained range |
| `logs`, Grok backend | 2026-08-13T06:37:59.972434Z to 2026-08-14T11:19:26.115560Z | 2,705 rows | no Grok rows after last completed Grok turn |
| `turn_usage`, all runtimes | 2026-08-03T06:33:39Z to 2026-08-16T08:53:42Z | 3,452 rows | 0 `runtime='grok'` rows |
| `usage_snapshots` | first overall 2026-07-05; first Grok key 2026-08-13T06:53:24.745767Z | 884 rows in Grok-era span; 855 with Grok key | 29 rows without Grok key |
| Grok-key gap 1 | missing-key snapshots 9414–9424, 2026-08-13T13:16:34.493170Z to 14:06:56.029536Z | 11 rows | 60.4 min between adjacent snapshots that contain a Grok key |
| Grok-key gap 2 | missing-key snapshots 9636–9653, 2026-08-14T07:57:42.744429Z to 09:20:55.419847Z | 18 rows | 93.3 min between adjacent snapshots that contain a Grok key |
| managed CLI unified log | 2026-08-13T07:28:43.147Z to 2026-08-16T02:49:51.666Z | 5,265 rows; 1,484,426 bytes | file coverage only |
| user CLI unified log | retained file at probe | 656 rows; 181,488 bytes | file coverage only |
| system journal | 3 retained boots; oldest boot start 2026-07-03T08:14:57+02:00 | query bounded to Aug 13/cutoff | boot list is the retention boundary |

## Commands and source mapping

```text
pwd
git status --short
git check-ignore -v docs/tasks/285/parts/grok/evidence.md
sqlite3 -readonly /home/kesha/orchestra/data/orchestra.db
  schema inspection and cutoff-bounded SELECT/CTE queries over sessions, logs,
  turn_usage, and usage_snapshots
jq
  auth mode, refresh-field presence, expiry timestamp, event names, levels,
  and timestamps only; credential values never selected
journalctl -u orchestra --since 2026-08-13T00:00:00Z
  --until 2026-08-16T08:55:39.261861Z --output=short-iso-precise
journalctl --list-boots
timedatectl show --property=Timezone --property=LocalRTC
  --property=NTPSynchronized
ssh -i ~/.ssh/tunnel_laptop -p 2222 maxim@127.0.0.1
  one-shot transport probe; no remote command executed
rg/read-only inspection:
  app/db.py, app/manager.py, app/routes/system.py, app/backend_grok.py,
  docs/tasks/95/quota-source.md, docs/tasks/96-grok-quota/research.md,
  docs/tasks/232/research.md, docs/tasks/251/research.md,
  docs/tasks/251/laptop-config-sanitized.md, docs/tasks/267/report.md,
  docs/grok-field-guide.md
```

The machine-readable source rows and measurements are in `evidence.json`.
