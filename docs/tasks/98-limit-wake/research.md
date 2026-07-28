# Task 98 — monthly limit wake: investigation

## Revision after the first approval

The first version incorrectly inferred that
`extra_usage.spend_limit_reached=true` blocked Anthropic after the 5h reset.
That inference used provider flags without checking whether real turns executed.
A second read-only database measurement found 13 successful post-reset Claude
turns while the flag remained true. The conclusions and recommendation below
supersede both the original "manual-only until the human raises monthly" model
and the unsafe idea of treating the extra flag as an absolute provider gate.

## Question

### Context

`app/limit_wake.py` lets the dashboard schedule messages to agents whose latest
turn ended on a subscription limit. Timed provider windows have a future reset;
Anthropic's monthly extra-usage gate does not.

### Change under test

Choose the product contract for a click after Claude reported
`monthly spend limit` while its base timed window was also exhausted:

1. treat the terminal text as a permanent manual-only classification; or
2. derive provider readiness from current capacity: base timed capacity is
   sufficient on its own; the extra alternative remains disabled until its
   clear state is measured.

### Baseline

The current code puts monthly agents in `manual_agents`, creates no job for
them, and removes every Anthropic timed agent from provider scheduling whenever
`manual_agents` is non-empty [S1].

### Measurable outcome

A correct design must:

- account for every candidate as scheduled, waiting, or unscheduled with a
  reason;
- send only when complete base timed capacity is open; set
  `extra_available = false` until a live clear state is measured;
- after one click, show who will receive a message, under which condition, and
  when that condition is checked;
- survive restart and avoid waking an agent whose limit turn is no longer its
  latest turn.

## Hypotheses and falsifiers

### H1 — today's missed wake was caused by the mixed monthly/timed exclusion

**Claim.** At least one real Anthropic agent stopped on a timed limit and was
discarded only because another real agent stopped on monthly.

**Falsifier.** Reconstructing candidates with the production classifier on the
live database finds no timed Anthropic candidate during the incident.

**Result: REFUTED for today's incident.** The database contained three relevant
Claude stops and all three had the explicit text `You've hit your monthly spend
limit`. The complete scan described in M2 found 38 monthly limit-stop intervals
and zero timed intervals.

### H2 — the 5h reset restores execution even while extra spend remains reached

**Claim.** Once the base 5h window resets, an Anthropic agent is executable even
if its previous terminal text said monthly and
`extra_usage.spend_limit_reached` remains `true`.

**Falsifier.** Agents sent messages after the reset produce another monthly
terminal instead of a successful `end_turn`.

**Result: CONFIRMED.** While `spend_limit_reached=true` and `is_enabled=false`,
the reset changed 5h from 100% to 0%. The three monthly-classified agents then
accepted new messages and completed successful turns; the copied database
contains 13 successful post-reset Claude `end_turn` rows across four agents
(M1).

### H3 — the button provides observable confirmation even when its plan is empty

**Claim.** A click changes the state rendered by the panel or explicitly says
that no job was created.

**Falsifier.** Running the production scheduling function against a read-only
copy produces the same fields consumed by the UI before and after the click.

**Result: REFUTED.** The UI inputs were byte-for-byte equivalent for
`candidate_count`, `monthly_agents`, `manual_action_url`, and `scheduled` (M3).
The panel therefore redraws the same pre-click warning and does not acknowledge
that the request completed with zero jobs.

### H4 — `spend_limit_reached` is an absolute Anthropic provider gate

**Claim.** `extra_usage.spend_limit_reached=true` means no Anthropic agent can
execute, regardless of base timed utilization.

**Falsifier.** Successful Claude turns occur while that flag remains true and
base timed capacity is below 100%.

**Result: REFUTED.** Thirteen successful post-reset turns occurred with
`spend_limit_reached=true` (M1). The field gates supplemental extra usage, not
the provider. Its `true → false` transition is still unmeasured, so the current
contract fixes `extra_available = false`; no response-field guess may authorize
that branch.

## Measurements

All database work used a SQLite backup created through a `mode=ro` connection:

```text
source: /mnt/data/Projects/Python/orchestra/data/orchestra.db
copy:   /tmp/orchestra-limit-wake.db
copy taken: 2026-07-28 19:10 +07:00

second copy: /tmp/orchestra-limit-wake-clear.db
copy taken:  2026-07-28 19:32 +07:00
```

No live database rows were changed. No wake endpoint was posted to and no agent
was messaged.

### M1 — timed reset restored base capacity while extra usage stayed blocked

Persisted snapshots around the incident:

| UTC timestamp | Local | Anthropic 5h | 5h reset | 7d |
|---|---:|---:|---|---:|
| 2026-07-28 11:01:55 | 18:01:55 | 100% | ~12:00 UTC | 8% |
| 2026-07-28 11:57:39 | 18:57:39 | 100% | 12:00:00 UTC | 8% |
| 2026-07-28 12:02:42 | 19:02:42 | 0% | `null` | 8% |

The live read-only `GET /api/usage` at approximately 12:10 UTC returned:

```text
anthropic.five_hour.utilization = 0.0
anthropic.extra_usage.spend_limit_reached = true
anthropic.extra_usage.is_enabled = false
anthropic.extra_usage.disabled_reason = "org_level_disabled_until"
anthropic.extra_usage.utilization = 0.0
anthropic.spend.percent = 0
```

At 12:31 UTC the same extra-usage fields were unchanged, while base usage had
advanced:

```text
anthropic.five_hour.utilization = 18.0
anthropic.seven_day.utilization = 9.0
anthropic.extra_usage.spend_limit_reached = true
anthropic.extra_usage.is_enabled = false
anthropic.extra_usage.disabled_reason = "org_level_disabled_until"
```

The read-only database copy then established actual execution:

| Monthly-classified agent | Post-reset user message | Successful turn end |
|---|---|---|
| `seedon-orchestrator` | 12:08:34 UTC | 12:09:56 UTC |
| `COG-second-brain-orchestrator` | 12:08:59 UTC | 12:11:09 UTC |
| `polus-orchestrator` | 12:11:04 UTC | 12:12:42 UTC |

Across all Claude sessions there were 13 successful `end_turn` rows for four
agents after 12:00 UTC.

Therefore `spend_limit_reached` directly expresses only the supplemental
extra-usage block. It must not override open base capacity. The zero-valued
extra `utilization`/`spend.percent` fields are likewise not a provider
availability signal.

**Confidence: CONFIRMED** — two live API measurements, persisted before/after
snapshots, and successful production turns on the same account.

### M2 — real limit events and reconstructed candidates

The three Claude terminal sequences during the 100% 5h window were:

| Agent | Limit text timestamp (UTC) | Turn end | Classification |
|---|---|---|---|
| `seedon-orchestrator` | 11:14:37.286 | `stop_sequence` at 11:14:37.293 | monthly |
| `polus-orchestrator` | 11:43:56.835 | `stop_sequence` at 11:43:56.837 | monthly |
| `COG-second-brain-orchestrator` | 11:58:47.726 | `stop_sequence` at 11:58:47.730 | monthly |

Each turn contains the exact provider text:

```text
You've hit your monthly spend limit · raise it at claude.ai/settings/usage
```

The full Claude-log scan used the real `_latest_limit_turn()` function for each
terminal block and closed a candidate interval on the next non-wake
`user_message`. Result:

```text
LIMIT_INTERVALS 38
MONTHLY 38
TIMED 0
MIXED_SNAPSHOTS 0
```

At 12:11 UTC the production `_load_limit_stopped_agents()` on the copied
database returned only:

```text
polus-orchestrator, monthly, anthropic, idle, limit turn log id 329192
```

`seedon-orchestrator` and `COG-second-brain-orchestrator` had received later
user messages at 12:08 UTC, so the classifier correctly stopped considering
their old limit turns current.

**Confidence: CONFIRMED** — actual production classifier over the read-only
copy. The live dataset does not substantiate a mixed monthly/timed incident.

### M3 — empty click has no visible acknowledgement

`wake_status()` and `schedule_wake_after_reset()` were executed against the
copied database with a no-mutation fake background manager. No `create()` or
`cancel()` call occurred.

```text
before:
  candidate_count = 1
  monthly_agents = ["polus-orchestrator"]
  scheduled = []

POST result:
  scheduled_count = 0
  schedules = []
  manual_agents = ["polus-orchestrator"]
  unavailable_agents = []

after, for every field read by the UI:
  candidate_count = 1
  monthly_agents = ["polus-orchestrator"]
  scheduled = []

UI_INPUT_IDENTICAL True
```

The copied `bg_jobs` table contained zero rows whose action was
`wake_subscription_limited`.

**Confidence: CONFIRMED** — production scheduling/status functions and the
exact UI input contract, with no writes to the live service.

### M4 — mixed candidates disappear from the response contract

The exact `build_wake_plan()` function was run with the real 18:57 provider
snapshot and a deliberately synthetic mixed cohort, because M2 proves that no
real mixed cohort exists in the database:

```text
input: one monthly Anthropic candidate + one timed Anthropic candidate
snapshot: 5h=100%, reset=12:00 UTC; 7d=8%

output:
  schedules = []
  manual_agents = ["monthly-real-shape"]
  unavailable_agents = []
  unaccounted = ["timed-real-shape"]
```

This confirms the code-path defect but is **not** evidence that the defect
caused today's incident.

**Confidence: CONFIRMED for function behavior; REFUTED as today's root cause.**

## Findings

### F1 — monthly is an extra-capacity gate, not a provider gate

The observed monthly terminal occurred while the 5h base window was 100% and
extra usage was unavailable. After the base reset, agents executed successfully
without any change to the extra-usage flags (M1). Readiness is therefore:

```text
current task: base timed capacity open
future only after measurement: base open OR extra available
```

The base condition comes first and is sufficient by itself. A monthly terminal
describes why the previous request could not fall back beyond exhausted base
capacity; it does not make that agent permanently manual-only.

**Confidence: CONFIRMED** — live provider state plus 13 successful post-reset
turns (M1).

### F2 — log classification incorrectly overrides future provider capacity

Monthly classification comes from the candidate's latest terminal logs, not
from current or future provider availability. `build_wake_plan()` sends every
monthly-classified agent straight to `manual_agents`, even when a simultaneously
exhausted 5h window has a known reset [S1]. Today's three monthly-classified
agents all became executable at that reset (M1), but the button created no job
for them (M3).

The plan must classify the *provider state*, not use the terminal text as the
schedule policy:

- base already open → wake now;
- base exhausted with a future reset →
  schedule every provider candidate at the latest exhausted reset;
- neither base capacity nor a future timed reset →
  manual-only with names and reason.

**Confidence: CONFIRMED** — `_latest_limit_turn()` and
`build_wake_plan()` contracts [S1], reproduced on the copied database (M3), and
successful post-reset turns (M1).

### F3 — feedback is lossy in both empty and mixed plans

For monthly-only input, the post-click state is visually identical to the
pre-click state (M3). For a mixed response, `_analyticsWakePanel()` uses an
exclusive `if monthly ... else if scheduled` chain, so any monthly agent hides
valid schedules for other providers or cohorts [S2]. Persisted schedule rows
already contain full agent records, including names; `wake_status()` projects
them down to `agent_count` [S1]. The storage has the answer to "кому", but the
status/UI contract discards it.

**Confidence: CONFIRMED** — direct reproduction plus primary frontend/backend
code.

### F4 — one readiness helper must authorize only the measured base path

The public `GET /api/usage` can be privacy-suppressed when dashboard auth is
enabled, and `current_provider_usage()` currently drops `extra_usage` [S3].
Scheduling and every pre-send guard should call one internal readiness helper,
not loop HTTP back into the public route and not maintain two sibling checks.

For Anthropic, that helper must:

- require a fresh response for execution decisions;
- require both base windows (`five_hour` and `seven_day`) with numeric
  utilization; partial base data is not "open";
- declare `available` immediately when both base windows are below 100%,
  regardless of `spend_limit_reached`;
- otherwise report base capacity unavailable; `extra_available` is hard-coded
  false until a future live measurement establishes its clear-state contract;
- expose the latest future reset among exhausted base windows;
- return a visible unavailable/manual reason when neither capacity path can be
  established.

The live extra clear-state remains unmeasured. Therefore this implementation
uses only the proven base-capacity path. No combination of unmeasured extra
fields authorizes a send.

**Confidence: CONFIRMED for base capacity; UNCERTAIN for extra clear-state** —
the first has successful production turns, while the second transition has not
been observed.

## Product options

### Option A — keep monthly terminal agents manual-only

**Rejected.** This is current behavior. It dropped all three agents even though
the known 5h reset restored their ability to execute (M1–M3).

### Option B — provider-capacity one-shot (recommended)

One click obtains fresh provider readiness and places every candidate into an
exhaustive category:

- **available now:** run the existing guarded, staggered wake immediately;
- **base exhausted with future reset:** create the existing replaceable
  one-shot timer at the latest exhausted reset, regardless of whether the
  candidate's terminal kind was `monthly` or `timed`;
- **manual-only:** no base capacity and no future timed reset; extra capacity is
  deliberately disabled, so show names, reason, and the Claude Usage link;
- **unavailable data:** missing/stale required fields; show names and a
  fail-closed reason.

At timer fire and immediately before every `session.send()`, the same fresh
readiness helper must authorize complete base windows as open.
The existing turn-id guard, delivery ledger, restart replay, and stagger remain
applicable.

**Pros:** restores the originally promised one-click wake at the known base
reset; uses the behavior directly proven by production turns; no recurring
watcher.

**Cons:** even genuinely available extra usage will not authorize a wake until
its clear state is observed in a later investigation. That does not block the
proven base-reset path.

### Option C — background watcher for extra usage

**Rejected for this fix.** It adds recurring state even though today's cohort
had a known base reset. It may be reconsidered only for a truly manual-only
cohort after the extra clear transition is measured.

## Recommendation

Implement **Option B: provider-capacity one-shot**.

The terminal kind remains useful evidence for explaining the previous stop, but
provider readiness decides what happens next. Today's monthly-classified agents
should have been scheduled for 18:59 because the 5h reset was known; the
successful turns at 19:08–19:12 prove that path.

The single readiness helper is the invariant for this implementation:

```text
extra_available = false
available = complete_base_windows_open
```

It is used both for the click decision and immediately before every staggered
send. Missing data fails closed with a visible reason, not silent omission. A
future measured extra clear-state may widen this invariant to
`base_open OR extra_available`; this task must not guess it.

The response/UI contract should be non-exclusive and exhaustive:

- **scheduled:** provider, reset time, exact agent names;
- **manual-only:** exact agent names, missing capacity path, required human
  action, and the Claude Usage link;
- **unavailable data:** exact agent names and missing/stale field reason;
- **not scheduled:** exact agent names and per-agent/provider reason;
- **click result:** an explicit sentence even when zero jobs were created;
- **persisted timed status:** scheduled, triggering, completed, or failed,
  including the latest error.

No recurring watcher is required.

## Counter-evidence and negative results

- The live database contains no timed Anthropic limit-stop interval, so the
  mixed filter is not the cause of today's three-agent incident.
- `spend_limit_reached` is not an account-wide provider gate: successful turns
  occurred while it remained true.
- The extra-usage clear transition is still unmeasured; this task explicitly
  fixes `extra_available = false`.
- The active five-minute usage snapshot loop persists the raw monthly gate in
  `usage_cache.json`, but the SQLite history drops it and neither path drives
  wake evaluation; cadence is not a watcher.
- No live POST was issued, so this investigation proves the empty scheduling
  result through the production function on a copy, not through an access-log
  record of the user's particular click.
- No wake job rows existed in the copied database at 19:10 local.

## Affected files and risks for a later plan

- `app/limit_wake.py`
  - replace terminal-kind scheduling with provider-capacity readiness;
  - use one helper on click, timer fire, and before each send;
  - return exhaustive status categories.
- `app/routes/system.py`
  - only if needed to obtain a fresh normalized base-window snapshot without
    weakening public `/api/usage` privacy; extra fields are not an authorization
    input in this task.
- `app/static/js/analytics.js`
  - render waiting, scheduled, and unscheduled groups together;
  - acknowledge empty results and show exact names/times.
- `tests/test_limit_wake.py`
  - monthly-classified candidate scheduled at an exhausted 5h reset;
  - monthly-classified candidate wakes immediately when base is open even while
    extra spend remains reached;
  - manual-only with no future base reset;
  - permissive-looking extra fields do not authorize a wake while base is
    exhausted;
  - mixed monthly/timed cohort, missing base window, stale usage, per-send
    reclose, restart, and manual-message skip.
- `tests/test_usage_analytics_frontend.py`
  - empty click acknowledgement and simultaneous manual/scheduled rendering.

Main risks:

- treating `spend_limit_reached` as an absolute provider block;
- treating an absent/stale extra field as extra capacity;
- authorizing from a partial Anthropic response;
- hiding one category because another is present;
- waking a stale candidate after a newer user message.

## Sources

1. **[S1, primary source]** `app/limit_wake.py`, especially
   `_latest_limit_turn`, `build_wake_plan`, `wake_status`,
   `schedule_wake_after_reset`, `provider_is_available`, and `run_wake_job`.
2. **[S2, primary source]** `app/static/js/analytics.js`,
   `_analyticsWakePanel()` and `_analyticsScheduleWake()`.
3. **[S3, primary source]** `app/routes/system.py`,
   `_provider_usage_snapshot()`, `_get_usage_data()`,
   `current_provider_usage()`, `_collect_usage_snapshot()`,
   `_usage_snapshot_loop()`, and `GET /api/usage`.
4. **[M1–M4, direct measurements]** live read-only HTTP GETs plus
   `/tmp/orchestra-limit-wake.db` and
   `/tmp/orchestra-limit-wake-clear.db`, created from the live SQLite database
   through read-only connections on 2026-07-28.
