# #263 — synthetic `turn_usage` rows

## What was deleted

Live recount at delete time (same `BEGIN IMMEDIATE` as the `DELETE`, not the
assignment snapshot):

| | before | after |
|---|---:|---:|
| matching `scope='/test' OR session_id LIKE 'test-%'` | **26** | **0** |
| `turn_usage` total | 3411 | 3385 |
| sessions | `test-001` × 26 | — |
| scopes | `/test` × 26 | — |
| runtimes | claude 25, codex 1 | — |
| sum `cost_usd` | $1.0041406 | — |

IDs: 121–126 (2026-08-03T10:08:52Z–10:09:11Z) and 1152–1171
(2026-08-07T02:45:55Z–02:48:40Z). Set matched the expected 26 / `test-001` /
`/test` / 25+1, so deletion ran. Codex `MIN(ts)` after: `2026-08-05T10:41:09.904925+00:00`
(was the 03.08 synthetic row).

## Backup

`sqlite3.Connection.backup` (not `cp`) of `/home/kesha/orchestra/data/orchestra.db`:

`/home/kesha/orchestra-backups/orchestra-pre-263-20260814T093551Z.db`
(293261312 bytes; backup itself contained 26 matching / 3411 total).

Service was not restarted. Production DB was mutated once, by this delete.

## Source

All 26 rows predate `#235` (`823de42a`, 2026-08-13 07:44 +0200). Newest
synthetic ts is 2026-08-07; `rows_on_or_after_235 = 0`.

They come from pytest against the main-checkout default path
(`/home/kesha/orchestra/data/orchestra.db`) before the autouse guard:

- `tests/test_session.py` fixture `session` hard-codes `id="test-001"`,
  `scope="/test"`, `model="claude-sonnet-5[1m]"` — matches all 26 models.
- The one Codex row (`id=126`, `event_id='task-turn'`, `cost_usd=0`) is the
  Codex backend fixture using the same session id (`task-turn` in
  `tests/test_session.py` / `tests/test_backend_codex.py`).

`#235` already wraps `sqlite3.connect` and redirects `DB_PATH` in
`tests/conftest.py`. No new rows after that commit. Item 2 (stop new ones)
is closed by this check, not by new production code. `ORCHESTRA_DB_PATH` is
unset in `.env`.

## Named test command

Run first, before any change, as received:

```text
uv run python -m pytest -q tests/ -k "turn_usage or usage_guard or db_guard"
.............                                                            [100%]
13 passed, 2906 deselected in 26.87s
```

Already green. No new test written (received command was not red).

## Mutation (existing guard, not the test)

Broke `_isolate_production_db` `autouse=True` → `False` in `tests/conftest.py`.
Mutated marker count 0 / `autouse=False` marker 1.

```text
FAILED tests/test_production_db_isolation.py::test_production_db_guard_is_autouse
AttributeError: 'builtin_function_or_method' object has no attribute
'_orchestra_production_db_guard'
1 failed, 12 passed, 2906 deselected in 8.44s
```

Rollback `mv` + `touch`: marker 1 / false-marker 0. Green repeat:

```text
.............                                                            [100%]
13 passed, 2906 deselected in 9.78s
```

`git diff tests/conftest.py` empty after restore. Mutated run did not create
worktree `data/orchestra.db`. Live matching stayed 0.

## Grok-runtime notes (first worker on this runtime)

Worked: live recount-in-transaction, WAL backup, one-shot delete, source
dating vs `#235`, mutation of existing guard.

Did not invent a new write-path filter in `turn_usage_add`: tests legitimately
persist `scope='/test'` into isolated tmp DBs; blocking that would break them.
Prevention is “tests must not open the production file”, which `#235` already
does.

Near-miss: wrapping the expected-red pytest in `set -e` aborted before
rollback. Restored from `.bak` in the next command; tree clean.
