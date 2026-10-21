# V-999 — Claude Code local history usage

## Result

Added `app.claude_history_usage` to import assistant usage records from `~/.claude/projects/*/*.jsonl`. The collector uses the last record for each `message.id` (falling back to the record UUID as V-998 did), stores one row per message, and upserts on re-run. Rows are never deleted when a source file disappears. Stored dimensions are day, working directory, and model, with input, output, cache-read and cache-write token counts.

`SessionManager.start_background_tasks()` starts the existing periodic manager task. It scans once at startup and every six hours after that, off the event loop. Malformed JSONL line counts are returned and logged with a warning; unreadable files also produce a warning.

The existing `/api/usage/analytics` payload now includes `claude_history_comparison`, grouped by day and working directory. Each entry carries Orchestra, Claude history, and history-minus-Orchestra values for message count and each token category. The analytics overview displays those project rows in a compact table.

## First real history backfill dry run

Read-only scan of the current local history; it did not open or write either the live DB or a copy DB:

- 3,232 JSONL files inspected; 119,721 unique assistant message IDs retained.
- 39 days represented, from 2026-08-29 through 2026-10-21; 4,064 distinct project values (the recorded `cwd`, or encoded Claude project-directory fallback when absent) and 5,138 day × project × model groups.
- Totals: input 252,675; output 97,487,077; cache read 38,085,665,809; cache write 756,886,201 tokens.
- Two malformed JSONL lines were skipped and reported by the collector.

After adding the distinct-chunk-UUID regression fixture, the parser was run again with `message.id` as the dedup key. The recheck inspected 3,232 files, found 119,792 unique messages across 39 days (2026-08-29–2026-10-21), 4,067 project values, and 5,141 day × project × model groups. Totals: input 252,825; output 97,540,772; cache read 38,133,092,279; cache write 757,042,203 tokens; two malformed lines. Both scans were read-only. The counts increased between scans, consistent with local history files receiving new records while collection is running; the six-hour rerun will capture those records.

The scan is a dry run of the same parser used by the scheduled DB collector. Once the Python change is merged and the service is restarted by its owner, startup collection will import the messages into Orchestra's DB.

## Verification

- `uv run --frozen python -m pytest tests/test_claude_history_usage.py tests/test_usage_analytics.py tests/test_usage_analytics_frontend.py -q` — 49 passed.
- The test command imported `app` from `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-claude-history-usage/app/__init__.py`.
- Synthetic fixtures cover last-record deduplication, idempotent collection, deleted-file retention, malformed-line visibility, and API comparison values.
- Mutation check: changing the dedup expression to prefer the record UUID made the streamed-chunk test fail (`messages` was 2, expected 1); restoring the `message.id` key returned all 49 tests to green.
- No live database was used by tests. Real history numbers above came from a parser-only dry run.

## Deployment

Python files in `app/` changed; the collector and API changes take effect after a service restart. No restart was performed.
