# #402 — durable Telegram file batches

## External contract verified

- Telegram Bot API `sendMediaGroup` requires 2–10 items. Documents and audio can only be
  grouped with the same media type: <https://core.telegram.org/bots/api#sendmediagroup>.
- aiogram's `MediaGroupBuilder` applies one shared caption to the first media object and defines
  `MAX_MEDIA_GROUP_SIZE = 10`: <https://docs.aiogram.dev/en/v3.28.2/utils/media_group.html>.
- The installed production dependency is aiogram `3.28.2`; `InputMediaPhoto` and
  `InputMediaDocument` are present in that interpreter.

## Delivery and grouping contract

`send_files(paths, caption="", as_document=False, event_id="")` uses one root UUID for the
ordered manifest. Index zero keeps that UUID; later files receive deterministic UUIDv5 child
IDs derived from the root and their original index. Every child remains a normal durable
`tg_file_deliveries` row with independent primary/mirror target states and message ID. The root
status aggregates those rows and exposes the per-file receipts in original order.

The root payload hash binds ordered content hashes, sizes, original names, caption, sender/scope,
`as_document`, target set, media kind, and planned group number. Repeating the same root and
manifest returns `ALREADY_ACCEPTED`; changed content or order returns `IDEMPOTENCY_CONFLICT`.
Provider-ambiguous failures are reconciled through the existing
`file_delivery_status(root_event_id)` path and are never blindly retried.

Grouping is a stable partition by effective type (`photo` or `document`) followed by chunks of
10. Type groups are emitted in first-seen type order; original order is preserved inside every
group. `as_document=True` forces every input into document groups. A singleton remainder uses the
existing single-file provider seam because Telegram albums require at least two items. The
caption is stored only on original index zero, which is the first item of the first group; every
other album item and later group has no caption.

The durable runner snapshots and validates every member before crossing a group provider
boundary, claims all ready members atomically, and calls `send_media_group` once. Success maps the
returned message IDs back to individual rows in order. Timeout/error after the boundary marks all
claimed members `UNKNOWN`; a later runner does not replay them. A pre-submit snapshot failure is
per-file and retryable with the same root event: already-sent siblings are not resent.

Primary and mirror targets are separate durable rows and separate per-chat runners, so the mirror
gets its own album. The legacy `_mirror_send_file` and `send_file` code paths are unchanged.

## Invalid path behavior

Admission is atomic and all-or-none. All paths are snapshotted before the DB acceptance
transaction. If any path is missing, empty, oversized, non-regular, or unreadable, temporary
snapshots for valid siblings are removed, no receipt/target row is committed, and nothing reaches
Telegram. The route returns HTTP 400 with `BATCH_FILE_INVALID`, `outcome_unknown=false`, and an
`invalid` list containing index, path, and exception class. This deliberately rejects the valid
siblings too, but never silently: the caller can correct the manifest and retry with a new event.

## Persistence migration

Four nullable columns were added to `tg_file_deliveries`: `batch_id`, `batch_index`,
`batch_group`, and `batch_kind`, plus a batch lookup index. The index must be created by
`_migrate_tg_file_deliveries` after the additive `ALTER TABLE` steps. Creating it in the initial
`executescript` broke existing DBs before migration with `no such column: batch_id`; the explicit
old-schema migration test reproduced and closed that ordering defect.

## Tests and mutations

Frozen RED commit: `d8c43a5c`.

```text
uv run pytest -q tests/test_tg_file_deliveries.py
6 failed in 11.93s, RC=1 (before production changes)
```

Final batch, route, timeout, retry, and migration tests:

```text
uv run pytest -q tests/test_tg_file_deliveries.py tests/test_tg_file_batch_route.py
12 passed in 13.44s, 12.56s, and 11.95s; RC=0 in three consecutive runs
```

Existing `send_file`/durable delivery behavior:

```text
uv run pytest -q tests/test_mcp_stdio.py -k send_file
3 passed, 106 deselected in 6.21s, RC=0

uv run pytest -q tests/test_tg_bridge.py::TestSendFileRouting \
  docs/tasks/333/acceptance/test_tg_file_delivery_333.py
16 passed in 14.75s, RC=0

uv run pytest -q tests/test_db.py
90 passed in 77.04s, RC=0
```

The task statement named `tests/test_tg_file_deliveries.py` as existing, but it did not exist on
fresh main. It is now the frozen acceptance file; the actual existing files were
`tests/test_tg_bridge.py`, `tests/test_mcp_stdio.py`, and the #333 durable suite under
`docs/tasks/333/acceptance/test_tg_file_delivery_333.py`.

Two isolated mutations used a committed test for each protection:

```text
limit 10 -> 100:
before=1 mutated=1 after=1 red_rc=1 green_rc=0
test_send_files_12_photos_use_10_plus_2_and_one_caption

document classification -> photo:
before=1 mutated=1 after=1 red_rc=1 green_rc=0
test_send_files_mixed_types_make_stable_homogeneous_groups

legacy single-file root collision guard:
before=1 mutated=1 after=1 red_rc=1 green_rc=0
test_batch_root_collision_with_single_delivery_returns_conflict
```

## Review

The changed surface is shared message delivery, an external provider boundary, a queue/lease,
and an additive persistence migration. The desired route is Sol, but no separate Sol run was
authorized. One automatically allowed fresh Luna pass supplied model independence from the
`gpt-5.6-sol` author (`gpt-5.6-luna` reviewer, both Codex runtime).

Round one found one blocking defect: a root event ID already occupied by a legacy single-file
receipt or another batch's child entered batch retry and raised HTTP 500. A committed pre-fix
oracle reproduced the `RuntimeError`; `_commit_batch_acceptance` now routes cross-kind IDs through
the existing principal/idempotency conflict check, returning 409. Its guard-only mutation returned
RC=1 and restored RC=0. The permitted resume classified the blocker `FIXED`, found no new issue,
and returned `APPROVED`. Evidence quote `return _same_batch_response(` appears in the reviewed
diff. Artifact: `docs/tasks/402/codex-review-impl.md`.
