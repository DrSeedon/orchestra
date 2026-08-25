# #364 — IndexedDB mirror self-healing

## Reproduction and exact incompatibility

The frozen Playwright oracle creates the real version-1 `orchestra` IndexedDB, writes 40
rows in the pre-24.08 mirror format, and then loads the current dashboard through routed
worktree `app.js` and `style.css`.

The stale format has two programmatically observable differences:

- `meta` has no `schema_epoch`;
- stored log rows have no `tool_use_id`, `tool_name`, or `tool_is_error`. Before commit
  `e7d521de`, `_SYNC_COLS` wrote only `id, session_id, ts, type, content, event_id`, while
  the current renderer and sync contract carry all nine fields.

Current main trusted `rows.length >= 40`, rendered that old page, and opened SSE at its old
maximum ID. The red run recorded `after_ids=[40]`; the newer server tail then grew the chat
row by row with DOM counts `39, 40, 46, ... 80`. This reproduces the owner's "staircase".
The paired click-expansion test was green before the fix, so expanding one tool message does
not change its neighbour: the observed staircase was SSE tail replay, not shared disclosure
state.

Frozen oracle commit: `28e20ff0` (`#364: freeze red oracle`). The oracle was not edited after
that commit.

## Fix

`app/static/js/app.js` now owns mirror epoch `2` in both places that matter:

- a same-version `logs + meta` read/write transaction checks `meta.schema_epoch` before
  `_storeOpen()` resolves; a missing or different epoch atomically clears the mirror and
  installs epoch `2`;
- every newly stored row carries `_mirror_epoch: 2`, and `_storeRead()` validates the epoch,
  required row types, and the three current tool metadata fields before returning any row.
  If an already-open old tab writes old rows after the initial repair, the reader clears them
  instead of rendering them.

Record validation is intentionally lazy and bounded to the rows selected for the requested
session/page. Incompatible rows outside that page may remain inert in IndexedDB, but no such row
is returned to the renderer: the first candidate-page mismatch clears the whole mirror.

After a reset `_storeRead()` returns an empty miss, so the existing `_fetchHistory()` path
downloads the current server page and `_storePut()` rebuilds the mirror. No user reload or
console action is involved.

This differs from both rejected #364 approaches:

- IndexedDB remains at database version `1`; there is no version bump, so a second open tab
  cannot block an upgrade transaction.
- the open-time reset uses its own raw transaction before `_storeReady` resolves. It does not
  call `_storeTx` from `rq.onsuccess`, so it cannot wait on the unresolved open path and
  deadlock.

It also does not call `indexedDB.deleteDatabase()`. IndexedDB is origin-scoped, and the same
open-time check runs independently on the domain and on `localhost`, so both origin-specific
databases self-heal.

## Verification

Baseline before production changes:

```text
uv run pytest -q tests/test_frontend.py::test_indexeddb_legacy_mirror_is_rebuilt_before_chat_render
1 failed in 19.13s, RC=1
after_ids=[40], steps=[39, 40, 46, ... 80], history_calls=[]
```

Focused fixed behavior:

```text
uv run pytest -q \
  tests/test_frontend.py::test_indexeddb_legacy_mirror_is_rebuilt_before_chat_render \
  tests/test_frontend.py::test_chat_expanding_one_message_keeps_neighbor_state \
  tests/test_frontend.py::test_indexeddb_record_epoch_rejects_old_tab_recontamination \
  tests/test_frontend.py::test_indexeddb_schema_repair_runs_for_each_origin
4 passed in 18.94s, 28.45s, and 26.56s; RC=0 in three consecutive runs
```

Required regression selection:

```text
uv run pytest -q tests/test_frontend.py -k "chat or mirror or indexeddb or timeline"
14 passed, 71 deselected in 30.40s, RC=0
```

Mutation disabled both detection paths (open-time epoch check and record-time epoch check) in
one command. The frozen oracle failed with the same `after_ids=[40]` staircase, then passed
after the same command restored and touched `app.js`:

```text
before_open=1 before_read=1 mutated_open=1 mutated_read=1
after_open=1 after_read=1 red_rc=1 green_rc=0
```

## Review

The changed surface is persistence schema/data recovery, so the desired route is Sol. A separate
Sol call was not authorized; one automatically permitted fresh Luna pass reviewed the bounded
implementation diff instead. Author/reviewer independence: `gpt-5.6-sol` author versus
`gpt-5.6-luna` reviewer, both on the Codex runtime.

The reviewer found no blocker and returned two suggestions. The bounded-validation behavior is
documented above. The former single-page contamination probe was replaced with a real two-page,
shared-browser-context interleaving: the old page keeps its version-1 connection open, the current
page repairs without an upgrade, then the old page writes an epoch-1 row and the current reader
clears it. No second review round is allowed for suggestions alone.

Review artifact: `docs/tasks/364/codex-review-impl.md`. The raw completed-job evidence included
`sed -n '118,142p' .review-364.diff` and the exact reviewed line
`await _storeReset('строки сохранены другой схемой');`; this satisfies the review-work evidence
check even though the compact final artifact contains only findings and verdict.
