# V-1001 — Past log search

## Result

Added the project-scoped `search_logs` MCP tool and `/api/logs/search` endpoint. Text matching uses Unicode casefolding, including Russian; filters accept inclusive `YYYY-MM-DD` bounds and an optional exact agent name. The tool sends the caller's configured project scope by default. Searching every project requires `all_projects=true`. Results carry timestamp, agent, project, normalized message type, a snippet of at most 502 characters, and the log id. A 10,000-candidate scan cap and 50-result cap bound broad searches; `scan_truncated` and `result_limit_reached` make each cap visible.

Voice transcripts remain searchable in the stored user-message content. `get_log_context` and `/api/logs/{log_id}/context` retrieve up to ten preceding and ten following rows plus the match; each returned content is capped at 4,000 characters.

The shared `knowledge.md` module instructs all roles to search their own project first, then all projects as needed, and cite the date and relevant log finding. A mechanics test checks that the module is included once in every role prompt.

## Read-only check against the live DB

Read `/home/kesha/orchestra/data/orchestra.db` through SQLite `mode=ro`; no data was changed. At check time the DB file was 5.4 GB, `logs` held 808,384 rows, and 277 sessions belonged to `/home/kesha/projects/seedon`.

The query equivalent to `search_logs("Сбер", scope="/home/kesha/projects/seedon", date_from="2026-08-27", date_to="2026-08-27")` returned 1,113 candidate rows for that scope and day. Casefold matching found 39 rows, including two `user_message` voice entries from `seedon-orchestrator`: log 226670 at 09:29:02 UTC and log 226723 at 09:32:47 UTC. The latter transcript contains the Sberbank paid-subscription message that prompted the search; the same result set also contains the account-opening conversation. No transcript contents or account details are copied into this report.

Measured SQLite execution took 0.565 s on the first run and 2.029 s on a repeat that also casefolded all candidate content. `EXPLAIN QUERY PLAN` before the change reported `SCAN l` and a primary-key lookup of each session; the date-bounded query scanned the log table. Added `idx_logs_day` on `date(ts)` to bound historical date queries. The isolated test DB confirms SQLite uses that index. No FTS index was added: this one-day query examined 1,113 scoped rows and the scan limit bounds returned candidates. The live DB has not been changed or benchmarked with the new index.

## Checks

- `uv run --frozen python -m pytest tests/test_log_search_v1001.py tests/test_default_pipeline.py -q` — 62 passed.
- `uv run --frozen python scripts/check_instruction_contract.py` — passed.
- The tests cover case-insensitive Russian matching, date bounds, default project isolation, explicit all-project search, voice transcript matching, result limits, caller scope in the MCP tool, context lookup, and shared-module delivery.
- Imported application path in the test run: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-history-search/app`.

Python changed in `app/`; the new API/tool and production date index require an owner-authorized Orchestra restart after merge. No restart was performed.
