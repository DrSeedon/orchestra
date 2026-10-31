# V-1159 — runtime usage, read-only accounting

Windows are half-open UTC: today `[2026-10-30T17:00:00Z, 2026-10-31T14:22:00Z)`, month `[2026-09-30T17:00:00Z, 2026-10-31T14:22:00Z)`, rolling 30d `[2026-10-01T14:22:00Z, 2026-10-31T14:22:00Z)`. Detailed source tables and identity/scope mapping remain local under `.orchestra/private/V-1159/`.

## Today — Orchestra VPS

| Unique accounting rows | Real-usage rows | Zero-token rows | Failed rows | Missing terminal events | Fresh input known | Input raw | Cache read | Cache write | Output | Reasoning subset | Known accounting-token sum | Native Codex Standard proxy |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 338 | 232 | 106 | 10 | 0 | 24,608,289 | 1,708,277,983 | 1,688,575,488 | 0 | 5,285,326 | 10,685 | 1,713,300,321 | 3,628.556 |

Codex input includes cached reads and writes; Claude cache counters are separate. Reasoning is included in output and was not added again. Fresh input is known for 24,608,289 tokens; 107 hub/harness rows lack proven freshness/combined-sum semantics (106 hub rows contain only zero counters). Hub `free` records are separate from subscription; OpenRouter-credit rows are also not folded into Codex Standard credits. API-equivalent USD totals are retained only in local private evidence. The daily native Codex proxy applies verified Sol and Luna Standard rates only; month/rolling credit values below remain the earlier Sol-priced subset because only today was re-rated for Luna.

The full daily top-actor table is private. Six current-role orchestrator aggregates on native Codex `gpt-6.1-sol` account for 174 real-usage turns and 3,356.778 credits; 57 `gpt-6-luna` subscription records add 271.778 credits.


### Same-token Terra counterfactual

Native Codex baseline Sol+Luna proxy 3,628.556 credits; pricing the same Sol tokens at Terra rates while holding Luna fixed gives 1,950.167. Difference 1,678.389 credits, 46.255% of the conditional baseline. Sol share of baseline proxy 92.510%. This is not a quota percentage-point estimate or a model-quality result. Calculation uses official Standard rates verified 2026-10-31; no speed multiplier or cache-write cost was added. Derivation script and input/output SHA-256 receipt remain local.

### Stored quota snapshot before the fixed end

The stored primary weekly counter moved from 47% pre-window to 77% by the last sample before END, across 255 VPS snapshots. This is account-wide telemetry, not attribution to the rows above; it is not converted through credits. No provider refresh was used.

## Month and rolling 30d — Orchestra VPS

| Window | Unique rows | Real usage | Failed | Zero-token | Missing terminal events | Rows lacking linked session | Fresh input known | Input raw | Cache read | Cache write | Output | Reasoning subset | Known accounting-token sum | Prior Sol-priced subset |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| month | 16,946 | 15,734 | 591 | 1,212 | 0 | 3,639 | 234,962,785 | 11,370,540,760 | 41,750,833,025 | 514,852,505 | 103,403,254 | 64,282 | 42,518,578,422 | 12,645.174 |
| rolling30d | 16,675 | 15,465 | 586 | 1,210 | 0 | 3,639 | 231,949,607 | 11,253,457,367 | 41,119,538,957 | 504,742,312 | 101,602,415 | 64,282 | 41,890,360,490 | 12,645.174 |

Fresh-input semantics are unresolved for 935 monthly rows and 896 rolling-30d rows; provider/model detail and cache-field completeness are in local evidence. API-equivalent USD totals remain local.


## Laptop Orchestra, Kesha VPS, Hermes coverage

Live laptop Orchestra DB had no `turn_usage` rows in today’s interval; the month known accounting sum is 1,359,668,255 tokens. Direct/manual Codex use outside that DB was not scanned.
Kesha VPS `response_usage` is a separate source: 20 today responses sum to input+output 3,832,596 tokens. Billing mode, cache-write split, Codex cost and failure status are unavailable, so this source is not added to the subscription proxy. Laptop Hermes has a live process but no usage rows in the requested window; its stored usage/session activity is stale.

## Checks and limits

Codex-only cache-read share is 1,683,429,760 / 1,713,300,321 known Codex input+output tokens = 98.257%; the 5,145,728 OpenRouter/harness cache-read tokens are excluded. `turn_usage.event_id` is UNIQUE; today’s 338 usage rows matched 338 terminal logs, with no missing/empty event IDs. All selected VPS timestamps use the UTC `+00:00` form. Today has zero session-join gaps; month/rolling have 3,639 retained usage rows whose session rows are absent, so historical names/roles are unknown. `turn_usage` has no origin; all terminal-log origin labels were `unknown`.

Initial collector drafts returned `ambiguous column name: scope`, `incomplete input`, and a Hermes-probe `SyntaxError: expected 'except' or 'finally' block`; those defects were corrected. A broad log query was terminated after 45 seconds with no result; the final indexed bounded read succeeded. The first Hermes window comparison used ISO strings against epoch timestamps; corrected UTC-epoch bounds found no today usage row. Exact RC/error details are local in `collection-attempts.md`.

Only database accounting rows and already stored limit snapshots were read. Native Codex JSONL, conversation bodies, provider endpoints, and account identity were not read. The actual snapshot has no five-hour percentage field. No weekly denominator was assumed; Standard credits are a priced subset, not a percentage of allowance.

Local raw datasets, SQL scripts, full provider/model/role tables, actor/scope tables, Hermes/Kesha evidence, snapshot timestamps and query-attempt errors: `.orchestra/private/V-1159/`. No tests were run (read-only task).
