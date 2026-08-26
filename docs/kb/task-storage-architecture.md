# task-storage-architecture

## Установлено

- Generation 3 inherited two independent task-number allocators: a 2026-08-26 full join of 693 legacy and 684 canonical tasks found 684 paired identities, zero unresolved mappings, and two semantic collisions in `orchestra` (#398 and #399); both newer canonical records had different older legacy tasks under the same number · `docs/tasks/406/report.md` § Pre-fix inventory; sqlite backup + 684 `state.json` records · 2026-08-26 #406
- Under canonical ownership, task creation must read `next_display_number` from canonical, compare it with legacy `_next_par` before either write, and pass that exact number to legacy; a mismatch is an `IdentityConflictError`, not projection debt returned after two successful but different writes · `app/ia/task_store.py:task_list`; `app/tm.py:api_create_task`; `tests/test_task_par_collision_406.py` · 2026-08-26 #406
- Collision repair is content-bound to one fresh snapshot: dry-run emits a token, `--apply` rereads both stores inside `BEGIN IMMEDIATE`, and any new/changed task refuses the pass before mutation; a copy probe inserted #410 between calls and got `REFUSED`, RC=2, with #404/#405 unchanged · `scripts/repair_task_par_collisions.py`; `docs/tasks/406/report.md` § Repair script · 2026-08-26 #406
- Current task storage is six SQLite tables: projects, tasks, clients, payments, payment_allocations, sync_log; schema owner is app/db.py:279-352 and current business writers are app/tm.py:220-1201 · local source [L1][L3], 2026-08-23 #299
- A Phase-1 safe snapshot watermark on 2026-08-23 contained 19 projects, 601 tasks, 2 payments, 3 allocations, 488 sync rows and 486 linked commit hashes; it used sqlite3.Connection.backup into :memory: and retained aggregate-only output. This is historical baseline evidence, not a timeless migration invariant · measurement [L6], 2026-08-23 #299
- A later live recheck watermark on 2026-08-23 still had 19/601/2/3/488 for projects/tasks/payments/allocations/sync but had 489 linked hashes; one continued write changed the observed aggregate, proving migration must freeze a fresh backup plus canonical cutoff/head and derive all expected counts/hashes from its immutable manifest · measurement [L6], 2026-08-23 #299
- Current #N is monotone/non-reuse only within project_id: migration drops historical global tm_par_sequence and app/tm.py:_next_par uses MAX(par_number)+1 plus docs/tasks directory guard · app/db.py:692-699, app/tm.py:63-78, 2026-08-23 #299
- Git clones preserve repository history/recovery and git merge stops on conflicting hunks until explicit resolution · Git primary docs [W1][W2], 2026-08-23 #299
- git-issue stores editable text issue directories with Git push/pull and SHA identity; git-bug stores distributed issues as Git objects; TicGit stores git-meta ticket fields plus local git-meta.sqlite; git-issues stores Markdown/YAML issue files with numeric id examples · [W3][W4][W5][W6], 2026-08-23 #299
- A Git-canonical task store with SQLite query projection is feasible without changing task/payment tool names if SQLite is projection-only and canonical_head is distinct from projection_head · synthesis backed by [W5][W7][W8] and current facade [L4], 2026-08-23 #299
- Recommended identity is stable UUID/ULID plus preserved display #N, allocated from disjoint per-contour leases; at 601 tasks a 4-hex hash has 93.6146% birthday probability of at least one collision · measurement/math in docs/tasks/299/research.md §4, 2026-08-23 #299

## Отвергнуто

- Pinning repair replacements from an earlier maximum (#409/#410) · live #409 was allocated to `kb-promote-facts` between inventory and implementation; replacements must be chosen from the apply-time occupied set and guarded by the dry-run snapshot token · `docs/tasks/406/report.md` § Pre-fix inventory · 2026-08-26 #406
- Global sequential #N as the sole cross-contour identity · two offline contours can both choose MAX+1 and current code is project-scoped; stable ID + lease is required · 2026-08-23 #299
- Four-hex content-hash prefix as canonical ID · birthday collision probability is 93.6146% at n=601 and ≈99.9510% at n=1000 · 2026-08-23 #299
- SQLite canonical plus Git export as the final portability architecture · stale/empty export requires an explicit side choice; beads_rust documents stale-export refusal and rebuild modes, while an independent SQLite+JSONL implementation documents a stable export interface · [W7][W8], 2026-08-23 #299
- One shared append-only JSONL as the primary write shape · every contour touches one merge-hotspot path; per-task records/events are needed for concurrent writers · historical Phase-1 snapshot had 1,281 revisions and 486 links, while later recheck observed 489 links, so neither count is a timeless AC · 2026-08-23 #299

## Пробелы

- Legal policy for storing payment/client notes in private Git and the required history-rewrite/remote-retention procedure is not supplied · technical tombstone is not GDPR erasure · 2026-08-23, task #299
- User acceptance of lease gaps versus requirement for one contiguous global #N sequence is not measured · central allocator is required if gaps/offline creates are unacceptable · 2026-08-23, task #299
- Performance baseline for current task_list/task_get and 10k-record replay is not measured · thresholds are defined in research §10 for implementation phase · 2026-08-23, task #299

## Источники

- docs/tasks/299/research.md — current model, safe aggregates, external comparison, identity, sync state machine and migration gates.
