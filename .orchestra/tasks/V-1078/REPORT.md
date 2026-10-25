# V-1078 — log search timeout and API responsiveness

Implemented in `app/db.py` and `app/routes/sessions.py`; manual changelog updated.
No MCP timeout, schema, visibility policy, provider, deployment or restart changes.
This is a source-only worker result; the broker owns its branch and commit.

## Findings and implementation

The supplied production ReadTimeout is the incident being addressed, not a newly
reproduced production observation. No live API, DB, logs, credentials or services
were accessed. The earlier root timeout was not counted as independent evidence.
The V-1001 report was not supplied in this copy; its six existing tests were run
before changes and passed (`baseline-v1001.txt`).

The public baseline function is preserved verbatim in `baseline_search.py`, SHA-256
`3122a1b78d7a20eea9fa9fe358eb8a1650bfef84d10fd651489aa0ad3b671a03`.
Real synthetic SQLite with the runtime schema reproduces the supplied plan shape:
two day-range predicates select the day index but require a temporary sort by ID.
The old SELECT carries complete `content` into that sort, before Python can stop
at eight matches. Thus the candidate/result bounds do not bound sorted payload
bytes or protect the event loop. This is a demonstrated mechanism and a plausible
explanation of the incident, not proof of the private host's particular latency.

Changes:

- Single-day requests use `date(l.ts) = date(?)`, retaining SQLite's UTC timezone
  conversion and inclusive calendar-day semantics. The existing day index supplies
  descending rowid order without the range query's sorter. No index was added.
- The candidate query carries only IDs. Content is fetched one candidate at a time
  and stops with the existing result bound. Range-query sorters contain only IDs;
  the extra coverage candidate never requires reading its payload. CROSS JOIN still
  keeps logs outer for bounded newest-first scans without date predicates.
- Explicit `BEGIN` holds one WAL read snapshot across candidate and payload reads.
  A regression commits a concurrent scope move, content replacement and deletion
  between those phases. Without `BEGIN`, the last candidate can disappear after
  the ID cursor finishes, producing a real None-row failure.
- The async route awaits Starlette's existing bounded AnyIO thread pool. The worker
  opens, uses and closes its own SQLite connection. Validation remains before
  offload. Errors propagate; cancellation never closes SQLite from another thread.
  Under raw asyncio task cancellation, the caller cancels while the bounded worker
  finishes and closes normally. There is no unsafe cross-thread interruption.
- Casefold offsets are mapped back to original character positions for snippets.
  Previously an expanding prefix (`ß`, `İ`) could move the snippet away from the
  actual match. Matching remains Python Unicode casefold, including partial matches
  inside an expansion; complete Russian voice content is searchable.

## Offline reproduction and profile

`profile_search.py` imports `tests/conftest.py` before app, creates only task-local
synthetic SQLite, and removes its database files. All runtime indexes are present.
Own rows have alternating dates and timestamps out of ID order. Every case has
twice as many foreign-project rows, with the same exact agent name. Own-row counts
N are 512 and 2,048; padding is 64 or 65,536 ASCII bytes per row. Eight recent
matches, one oldest rare match and zero matches are measured separately.

`profile.jsonl` retains actual output: SQLite 3.45.1, 20 shapes, two samples each
in before/after/after/before order. The table gives the median of two elapsed
measurements in milliseconds. These are scoped local results, not production SLA
or quota/savings estimates. Cache, scheduler and instrumentation noise remain;
the script's VM counts are approximate units of 100 SQLite instructions.

| N | padding/row | query shape | baseline ms | fixed ms | scanned |
|---:|---:|---|---:|---:|---:|
| 512 | 65,536 B | single day, 8 matches | 43.180 | 2.312 | 8 |
| 2,048 | 65,536 B | single day, 8 matches | 210.543 | 2.615 | 8 |
| 2,048 | 65,536 B | two days, 8 matches | 520.107 | 4.114 | 8 |
| 2,048 | 65,536 B | no date, 8 matches | 2.838 | 2.759 | 8 |
| 2,048 | 65,536 B | oldest rare match | 647.718 | 134.880 | 2,048 |
| 2,048 | 65,536 B | zero matches | 674.701 | 143.444 | 2,048 |
| 2,048 | 64 B | single day, 8 matches | 3.372 | 2.196 | 8 |
| 2,048 | 64 B | oldest rare match | 6.962 | 11.134 | 2,048 |
| 2,048 | 64 B | zero matches | 6.985 | 13.544 | 2,048 |

For the large single-day case, first SQL execute changed from 194.428 to 1.164 ms;
for the large two-day case, 489.120 to 2.572 ms. Results and scanned counts are
asserted equal in every profile trial. Small-content exhaustive scans are slower:
the extra primary-key SELECT per consumed row has a measured cost. This tradeoff
avoids unneeded blob materialization while preserving full rare/zero-match coverage.

An additional transparent SQLite view counts payload evaluations inside SQLite,
including its sorting work. With 256 older own rows, eight recent matches and
1,000 foreign/wrong-agent rows, baseline single-day search evaluates 136 payloads,
two-day search 264, and streaming/no-date variants nine (cursor read-ahead).
Fixed search evaluates exactly eight in all ten small/large/date variants. In the
32,768-byte fixture the single-day baseline touches 4,194,400 payload bytes versus
96 fixed bytes; the two-day baseline touches 8,388,704 versus 96. These are fixture
payload-evaluation counts/bytes, not OS disk-read or production estimates.

The MCP regression calls the real registered MCP request handler, real `_api`,
HTTPX in-process ASGI transport, route and SQLite. Client and server have separate
loops. A deterministic content-access gate stalls only on an unnecessary ninth
payload. A synthetic 1-second transport deadline raises HTTPX ReadTimeout, while
the MCP request's real timeout remains 30 seconds. Baseline yields the canonical
`transport_timeout` envelope; fixed search finishes with eight results without
entering the gate. This is an injected, scaled reproduction of the mechanism,
not a claim of reproducing the actual 30.2-second host trace.

## Checks actually run

Every Python shell used the provisioned uv 0.11.28:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
mkdir -p .orchestra/tasks/V-1078/tmp
export TMPDIR="$PWD/.orchestra/tasks/V-1078/tmp"
uv run --frozen python -m pytest tests/test_log_search_v1078.py tests/test_log_search_v1001.py tests/test_db.py tests/test_db_connection_ownership.py tests/test_mcp_stdio.py tests/test_session_logs_conditional.py tests/test_instruction_contract.py -q --tb=short --basetemp=.orchestra/tasks/V-1078/tmp/final
```

Final result: **283 passed in 27.16 s**, exit 0 (`final-tests.txt`). New regressions
cover allowed and rejected parameter combinations, own scope, explicit all-projects,
exact agent/name collisions, UTC date boundaries, invalid stored dates, newest ID,
9,999/10,000/10,001 coverage, simultaneous cap flags, 1/50 result clamping, full
large rare-match content, zero-match coverage, casefold expansion positions,
concurrent writes, another API response during a blocked search, normal/error/cancel
connection closure on its owning thread, recovery and the complete offline MCP chain.

Mutation commands, run with the same uv/TMPDIR setup:

```sh
uv run --frozen python .orchestra/tasks/V-1078/run_mutation.py baseline
uv run --frozen python .orchestra/tasks/V-1078/run_mutation.py inline
uv run --frozen python .orchestra/tasks/V-1078/run_mutation.py snapshot
nice -n 15 uv run --frozen python .orchestra/tasks/V-1078/profile_search.py
```

- Original database function: **14 failed, 1 passed, 21 deselected**, exit 1.
  Failures are 10 payload-work regressions, three displaced Unicode snippets and
  the MCP transport timeout. The partial-expansion control passes.
- Returning search to the loop: **1 failed, 35 deselected**, exit 1; the blocked
  request occupies the loop until its fixture guard releases, so it cannot remain
  pending while another API responds.
- Removing the explicit read transaction: **1 failed, 35 deselected**, exit 1;
  concurrent deletion makes a selected candidate disappear during content lookup.
- Mutation runners emit a pytest assertion-rewrite warning because the script
  intentionally imports isolation/app before starting pytest. It is not a test failure.

Instruction-contract script was also executed after conftest isolation:

```sh
uv run --frozen python -c 'import runpy; runpy.run_path("tests/conftest.py"); runpy.run_path("scripts/check_instruction_contract.py", run_name="__main__")'
```

It exits **1**: `CLAUDE.md must be a symlink to AGENTS.md`. The supplied copy has
no CLAUDE.md entry; it was already absent before edits. Root must run this check
in the original worktree with its symlink. The nine fixture-based instruction
contract tests pass within the 283-test run. No instruction was changed or weakened.

Intermediate failures were in newly authored fixtures: first `origin=None` violated
NOT NULL, then `origin=''` violated the existing origin CHECK; corrected to the
valid `unknown` provenance. The initial closure assertion ran from the wrong thread;
the final assertion checks closure from the owning worker. The first concurrent
scope move collided with an existing `(name, scope)` uniqueness constraint inside
a trace callback; the final fixture uses a distinct scope and propagates injection
errors directly. The full intermediate run had 282 passes and that one fixture
failure (`neighbours.txt`); final runs pass. No existing acceptance test was edited.

The exact resolved absolute app import was verified to belong to this checkout.
To avoid publishing raw hub-host paths, its absolute-path alias is
`/<hub-copy>/app/__init__.py`; SHA-256 of the actual absolute import path is
`eafa038475844c45e366238b770ab67451a337dcab25405e4320f239fbdf7649`.
Database module alias: `/<hub-copy>/app/db.py`. `profile.jsonl` includes the import
ownership check and baseline hash. Captured stdout is retained with host paths
normalized to these aliases; original-byte hashes are recorded separately.

## Remaining limits and handoff

Full suite was not needed after the targeted 283-test gate; no production latency,
actual host I/O, real transport authentication deployment, or service activation was
tested. A legitimate 10,000-row scan of large contents can still be costly; the
fix removes avoidable sorting/materialization and frees the loop, without hiding
errors, shortening useful data or increasing timeouts. Cancelled callers do not
forcibly stop their bounded workers; the standard AnyIO pool bounds concurrency.
Long legitimate readers retain a WAL snapshot until completion.

Unrelated observation for root only: `app/secret_mask.py`'s module docstring still
describes masking in add_log/live_broker, contrary to the current AGENTS policy.
It was not changed in this task.

Root owns review, source-worktree instruction check, merge, push and worker closure.
Actual Python activation belongs to the existing idle watcher. No Git commit,
push, live access, deployment, service restart, extra paid call or child agent was
performed by this worker.
