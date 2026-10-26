# V-1089 — DONE: reproduced excess SQLite work fixed; incident cause unproven

The source fix and 31 new behavioral regressions are ready for root acceptance.
This worker did **not** reproduce the original private 30-second incident. The
expanded final test command is **not green** in this partial copy: 363 passed,
3 failed because copied pipeline sources are missing. The standalone instruction
contract also fails because the supplied copy has no CLAUDE.md. Root must rerun
these checks in its complete checkout before accepting/merging/pushing.

## Evidence boundary

Fully read V-1078/REPORT.md, the supplied current db.search_logs, async route,
HTTPX _api/transport error handling and the registered MCP handler tests. No
production API, database, content, credentials, SSH, provider or service was used.

The incident input was query="14:30", agent="<project-orchestrator>",
date_from="2026-10-25", limit=8, with **no date_to**. Root separately reported a
30.065-second ReadTimeout in the original tool/result, but current direct search
returned 8 results/scanned 22 in 0.0031 seconds and HTTP returned 200 in 0.0328
seconds. Root's historical-ID-bounded check returned 7 results/scanned 1034 in
0.448 seconds; its separate exhaustive candidate pass was 1052 rows/0.46 seconds.
These are root's observations, not worker measurements. None establishes the
cause of the original timeout; neither a SCAN plan nor TG rate-slot warnings
establishes that cause. Later report echoes can change matches.

## Demonstrated defect and minimal fix

A synthetic database initialized by the actual db.init_db has the canonical
schema and **all runtime indexes**, including idx_logs_session and idx_logs_day.
Before the fix, the forced logs-outer CROSS JOIN walks other projects' and agents'
rows before applying scope/name visibility. The 10,001 eligible-ID limit does not
bound this physical SQLite work. With eight eligible rows, adding 16,384 irrelevant
rows changed candidate-only work from 150 to 163,976 VM instructions. Full search
regressions independently measure the same unwanted growth, including no-match
and nonexistent/case-mismatched-agent searches. Their oracles count actual SQLite
instructions and assert equal results; they never assert explanatory SQL prose,
plan names, or a wall-clock speed threshold.

For an exact scope/name pair, UNIQUE(name, scope) identifies at most one session.
Except for equal-day requests, the candidate query now resolves that ID once in a
scalar subquery and uses the existing ordered session index. Date expressions in
this path have unary +: SQLite leaves date() TEXT/NULL values unchanged, but cannot
choose the global expression index instead. Merely swapping CROSS JOIN order was
insufficient: ANALYZE caused some tested shapes to choose a global date-index walk
again. Both analyzed and fresh-schema variants are covered.

A single UTC day deliberately keeps V-1078's equality/day-index path. Forcing the
session index there can walk a large old history for a day containing only eight
rows. A separate 16,384-old-row regression and its mutant detect that regression.
Explicit all_projects and scope-only searches retain their existing path. This is
not a general guarantee that every query shape avoids global work; the retained
single-day and broad paths can still visit unrelated rows.

Only app/db.py production code changed. The route still uses Starlette's bounded
AnyIO worker pool; each worker owns its connection through success/error/cancel.
BEGIN still establishes one WAL snapshot across candidate resolution and payload
reads. Result matching still uses complete content and Python Unicode casefold,
with expanding-character snippet offsets unchanged. UTC conversion, date-before-
candidate filtering, newest IDs, result clamping, 10,000 eligible candidates plus
the coverage probe, and visible truncation flags are unchanged. No index, schema,
dependency, external contract, timeout, payload cap or history cutoff was added.

## Offline mechanisms and regression coverage

The full MCP regression calls the registered CallToolRequest handler, real _api,
HTTPX ASGI transport, async route and real SQLite on separate client/server loops.
It uses the reported parameter shape with no date_to and still verifies read=30.
A deterministic SQLite VM-work barrier stalls only after unnecessary work exceeds
2,000 instructions. A scaled 1-second client deadline turns that stall into a real
HTTPX ReadTimeout. Fixed search avoids the barrier; the supplied function fails.
A separate forced ReadTimeout control checks the canonical transport_timeout,
ReadTimeout, retryable GET envelope and recovery on the following successful call.
This is an **injected scaled timeout**, not a native 30-second incident reproduction;
the non-time-based VM-work oracle detects the defect without this deadline.

The new tests also check exact scope/name collisions in both directions, explicit
all_projects and scope-only controls, lower/upper/range/equal UTC date semantics,
offset timestamps, invalid stored dates, ID/timestamp disagreement, more than
10,000 excluded old rows before eligible candidates, full rare Unicode content
beyond a 10,000-character prefix, 9,999/10,000/10,001 coverage, MCP limit 1/50,
and concurrent rename/scope move/content replacement/deletion in a WAL reader.
V-1078's payload, loop responsiveness, connection ownership and recovery tests pass.
No supplied acceptance test was edited or weakened. No model review was performed.

Other possible sources of latency remain separate: full legitimate content reads
and casefold/snippet processing, host I/O/CPU contention, and waiting for a bounded
pool slot. The current route and MCP code were inspected and their existing
ownership/loop/timeout tests run; no private load, pool occupancy, historical
process state, or host contention was available to diagnose those alternatives.
Cancellation still lets an already running bounded worker finish/close normally.

## Checks actually run

Every Python command used the provisioned uv **0.11.28**, the frozen lock and the
default .venv; no fallback runner/interpreter or lock replacement was used.
Tests themselves stayed offline. Long output was captured completely. Temporary
files, synthetic databases and test subprocess fixtures stayed under this task's
tmp directory (TMPDIR); dependency cache provisioning was the permitted exception.
Heavy runs were sequential and used nice -n 15.

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
mkdir -p .orchestra/tasks/V-1089/tmp
export TMPDIR="$PWD/.orchestra/tasks/V-1089/tmp"
nice -n 15 uv run --frozen python .orchestra/tasks/V-1089/run_checks.py
nice -n 15 uv run --frozen python .orchestra/tasks/V-1089/profile_search.py
```

The final pytest command executed by run_checks.py was:

```sh
uv run --frozen python -m pytest tests/test_log_search_v1001.py tests/test_log_search_v1078.py tests/test_log_search_v1089.py tests/test_db.py tests/test_db_connection_ownership.py tests/test_mcp_stdio.py tests/test_session_logs_conditional.py tests/test_instruction_contract.py tests/test_mcp_proof.py tests/test_mcp_config_isolation.py tests/test_mcp_resolve_operation_423.py -q --tb=short --basetemp=.orchestra/tasks/V-1089/tmp/final
```

Final: **363 passed, 3 failed in 38.29 seconds**, exit 1. All 31 V-1089 and 36
V-1078 cases passed. The three failures are:

- test_search_rule_module_is_delivered_to_every_role: missing
  .orchestra/pipelines/default/prompts/modules/knowledge.md (also failed baseline).
- test_rebuilding_live_session_config_keeps_running_mcp_proof and
  test_make_mcp_config_issues_proof_not_in_base_env: missing
  .orchestra/pipelines/default/pipeline.yaml.

Standalone scripts/check_instruction_contract.py, run after conftest isolation,
exits 1 because CLAUDE.md is absent; none was fabricated. Its fixture-based tests
pass. Required source-backed prompt/proof/instruction checks therefore remain
unverified here. Full-suite testing was not performed.

All eight in-memory mutation checks exit 1 for actual behavioral failures:

| Mutant | Observed failure result |
|---|---|
| Supplied search function (V-1078 current baseline) | 22 failed, 9 deselected |
| Allow global day index in exact-session path | 2 failed, 14 passed, 15 deselected |
| Force session path for a single day too | 1 failed, 30 deselected |
| Remove explicit read transaction | 1 failed, 30 deselected |
| Remove scope from exact session lookup | 1 failed, 30 deselected |
| Search only first 10,000 content characters | 1 failed, 30 deselected |
| Reduce eligible candidate cap to 100 | 3 failed, 1 passed, 27 deselected |
| Execute search inline on the event loop | 1 failed, 35 deselected |

The mutation runner compiles only in memory and points the real route at that
function; production files are never mutated on disk. Its single assertion-rewrite
warning comes from deliberately loading conftest/app before pytest. Earlier runs,
including the initial 26-failure red run before added control cases, are retained
in stdout/ and stdout/iteration-1/ with their original raw-byte hashes.

## Profile, artifacts and handoff

profile_search.py runs the actual supplied and fixed functions against 18 synthetic
shapes: 1,052 own rows; 0/16,384/65,536 newer foreign rows; 64/32,768 own-content
padding; eight recent matches, seven rare old matches, and zero matches. Half the
foreign rows are below the lower date. Every before/after/after/before timing sample
asserts the complete result dictionary is equal. VM work is measured in separate
passes at intervals of 100 instructions; EXPLAIN describes those actual queries.
Raw sample values and plans are in stdout/profile.jsonl; these are scoped synthetic
measurements with cache/scheduler noise, not a production SLA or proof of incident
causality. Full required content processing remains costly.

Selected final samples (median of two elapsed measurements; VM rounded down to
100 instructions; no production latency inference):

| Padding | Foreign rows | Matches | Before ms | After ms | VM before / after |
|---:|---:|---|---:|---:|---:|
| 64 | 0 | recent-eight | 1.503 | 1.552 | 200 / 200 |
| 64 | 0 | rare-seven | 7.918 | 7.939 | 36700 / 31500 |
| 64 | 0 | zero | 9.837 | 9.376 | 36700 / 31500 |
| 64 | 65536 | recent-eight | 39.260 | 1.827 | 491700 / 200 |
| 64 | 65536 | rare-seven | 27.931 | 8.357 | 528300 / 31500 |
| 64 | 65536 | zero | 27.278 | 8.812 | 528300 / 31500 |
| 32768 | 65536 | recent-eight | 30.869 | 3.981 | 491700 / 200 |
| 32768 | 65536 | zero | 95.795 | 89.354 | 528300 / 31500 |

The absolute imported app path is recorded verbatim in ignored
private/raw/profile.jsonl; its public absolute-path alias is
/<hub-copy>/app/__init__.py. The probe asserts that actual path belongs to this
checkout, and stdout/probe.txt records its SHA-256. Host identity is intentionally
not put into a public report. stdout-manifest.json hashes both every original raw
byte stream and its complete normalized derivative; artifact-manifest.json hashes
the published source/artifacts. Original stdout stays in ignored private/raw;
stdout/ replaces host paths and applies the publication secret-form filter. The
task-local .gitignore overrides the root .orchestra negations for private/ and tmp/;
finalize_evidence.py checks that behavior in an isolated Git sandbox, without commits.

implementation.diff contains the exact supplied-to-fixed function diff. CHANGELOG
is updated. No neighboring source, supplied test, root instruction, running process,
repository remote, deployment or restart was changed. Offline test fixtures may
create their own temporary Git repositories; this worker did no project Git
commit/push/clone. Root owns independent diff review, own mutation/complete-checkout
checks, acceptance, merge and push. This source change is not evidence of Python
activation in a live process; activation follows the existing idle-watcher policy.
