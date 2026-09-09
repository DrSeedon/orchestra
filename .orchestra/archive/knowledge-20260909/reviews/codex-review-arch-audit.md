**Verdict**
- `praise:` The report is broadly solid and not a rubber stamp: most Top-10 claims are real, line refs mostly check out, and Appendix A is directionally correct.
- `issue:` One Top-10 subclaim is materially overstated/wrong: the Codex loop “dies silently and never transitions to IDLE” claim.
- `issue:` The report misses a same-class async blocker in `routes/tm.py`, so its “real async blocker is `tm_yougile.py`” framing is incomplete.

**Top-10 Accuracy**
- `praise:` `get_by_name` union claim is correct. `app/manager.py:749` explicitly returns `AgentSession | dict | None`; in-memory returns `AgentSession` at `app/manager.py:751`, DB fallback returns row/dict at `app/manager.py:754`. Call-site branching is widespread, e.g. `app/main.py:685`, `app/main.py:822`, `app/routes/bg.py:29`.
- `praise:` Sync SQLite in `tm_yougile.py` is correct. `app/tm_yougile.py:104` is `async def`, opens sync SQLite at `app/tm_yougile.py:105`, does `BEGIN IMMEDIATE` at `app/tm_yougile.py:114`, `app/tm_yougile.py:133`, `app/tm_yougile.py:147`, `app/tm_yougile.py:163`; also sync DB in async helpers at `app/tm_yougile.py:204` and `app/tm_yougile.py:233`.
- `issue:` Codex missing callback is real but consequence is overstated in `docs/reviews/arch-audit.md:142`. The Codex loop is created without `add_done_callback` at `app/session.py:358`, but `_codex_turn_loop` catches `Exception` at `app/session.py:461` and sets `IDLE` in `finally` at `app/session.py:464`. So “crash dies silently and session never transitions to IDLE” is false for normal exceptions. Better wording: “unobserved task exceptions are still possible for `BaseException`/finally failures; add callback for symmetry and logging.”
- `praise:` `_auto_continue` unbounded chain concern is fair: max-turn handling spawns `_auto_continue()` without a cap at `app/session.py:555`.

**Appendix A**
- `praise:` Rejection is correct. `merge_worktree_to_main` is sync `def` at `app/workspace.py:354`; `switch_worktree_branch` is sync `def` at `app/workspace.py:593`; callers use `asyncio.to_thread`, e.g. `app/main.py:884`, `app/main.py:950`, `app/manager.py:601`, `app/manager.py:636`. The lock can serialize merges, but it blocks a worker thread, not the event loop.
- `nit:` Appendix says `main.py:909` as a workspace caller; that is a continued `switch_worktree_branch` call started at `app/main.py:908`, so the reference is imprecise but not substantively wrong.

**Refactoring Plan**
- `suggestion:` P0 mostly makes sense, but “P0 is zero structural risk” at `docs/reviews/arch-audit.md:247` is too confident. Wrapping `tm_yougile.py` DB blocks in `to_thread` is low-risk but can change transaction timing around YouGile HTTP calls.
- `issue:` P0 should include `routes/tm.py` sync DB/API wrappers alongside `tm_yougile.py`. Current handlers are `async def` but call sync DB/API directly at `app/routes/tm.py:53`, `app/routes/tm.py:64`, `app/routes/tm.py:78`, `app/routes/tm.py:92`, `app/routes/tm.py:110`, `app/routes/tm.py:119`, `app/routes/tm.py:128`, `app/routes/tm.py:148`, `app/routes/tm.py:158`.
- `suggestion:` P1 before route extraction is sound. The `dict | AgentSession` leak blocks clean route moves.
- `issue:` P3 callback registry before P4 is architecturally clean but may be too early for an MVP budget. I’d defer broad event-bus/general callback work until after targeted fixes unless cycles are actively blocking edits. A tiny explicit callback interface is OK; a generic event bus risks abstraction creep.

**Major Misses**
- `issue:` Same async-blocker class missed in `routes/tm.py`: sync SQLite and sync task-manager APIs run in async routes. Examples: `_tm.api_create_task` at `app/routes/tm.py:56`, `_tm._conn()` at `app/routes/tm.py:69`, `_tm.api_update_task` at `app/routes/tm.py:101`, sync payment/status calls at `app/routes/tm.py:113` and `app/routes/tm.py:122`, raw sync queries at `app/routes/tm.py:134`, `app/routes/tm.py:151`, `app/routes/tm.py:160`. This directly contradicts the success criterion in `docs/reviews/arch-audit.md:255`.
- `suggestion:` `main.py` has another blocking async handler: `subprocess.run(..., timeout=10)` in `restart_server` at `app/main.py:1427`. Less severe because it’s manual/admin, but it belongs in the same “sync work in async route” bucket.
- `issue:` `open_file` bypasses `_is_safe_path`: `app/main.py:367` accepts any existing path and launches `xdg-open` at `app/main.py:376` when `ALLOW_OPEN_FOLDER` is enabled. Auth/env-gated, but architecturally inconsistent with `get_file_content` at `app/main.py:336` and `list_files` at `app/main.py:380`.

**Over-Engineering Risks**
- `suggestion:` Splitting `AgentSession` into `SessionState`, `EventLoopSystem`, `CostSystem`, `CompactSystem`, `PersistenceSystem` is likely too much for a 10-user MVP if done literally. Prefer extracting one painful subsystem first, probably cost or compaction.
- `suggestion:` “No file over ~600 lines except `db.py`” at `docs/reviews/arch-audit.md:257` is an arbitrary size target. Good as a smell, bad as a success criterion; it can drive churn.
- `suggestion:` A generic event bus/callback registry may violate “simple/flat/minimal abstractions.” Use explicit startup-wired callbacks first, not a broad pub/sub system.
tokens used
127,321
**Verdict**
- `praise:` The report is broadly solid and not a rubber stamp: most Top-10 claims are real, line refs mostly check out, and Appendix A is directionally correct.
- `issue:` One Top-10 subclaim is materially overstated/wrong: the Codex loop “dies silently and never transitions to IDLE” claim.
- `issue:` The report misses a same-class async blocker in `routes/tm.py`, so its “real async blocker is `tm_yougile.py`” framing is incomplete.

**Top-10 Accuracy**
- `praise:` `get_by_name` union claim is correct. `app/manager.py:749` explicitly returns `AgentSession | dict | None`; in-memory returns `AgentSession` at `app/manager.py:751`, DB fallback returns row/dict at `app/manager.py:754`. Call-site branching is widespread, e.g. `app/main.py:685`, `app/main.py:822`, `app/routes/bg.py:29`.
- `praise:` Sync SQLite in `tm_yougile.py` is correct. `app/tm_yougile.py:104` is `async def`, opens sync SQLite at `app/tm_yougile.py:105`, does `BEGIN IMMEDIATE` at `app/tm_yougile.py:114`, `app/tm_yougile.py:133`, `app/tm_yougile.py:147`, `app/tm_yougile.py:163`; also sync DB in async helpers at `app/tm_yougile.py:204` and `app/tm_yougile.py:233`.
- `issue:` Codex missing callback is real but consequence is overstated in `docs/reviews/arch-audit.md:142`. The Codex loop is created without `add_done_callback` at `app/session.py:358`, but `_codex_turn_loop` catches `Exception` at `app/session.py:461` and sets `IDLE` in `finally` at `app/session.py:464`. So “crash dies silently and session never transitions to IDLE” is false for normal exceptions. Better wording: “unobserved task exceptions are still possible for `BaseException`/finally failures; add callback for symmetry and logging.”
- `praise:` `_auto_continue` unbounded chain concern is fair: max-turn handling spawns `_auto_continue()` without a cap at `app/session.py:555`.

**Appendix A**
- `praise:` Rejection is correct. `merge_worktree_to_main` is sync `def` at `app/workspace.py:354`; `switch_worktree_branch` is sync `def` at `app/workspace.py:593`; callers use `asyncio.to_thread`, e.g. `app/main.py:884`, `app/main.py:950`, `app/manager.py:601`, `app/manager.py:636`. The lock can serialize merges, but it blocks a worker thread, not the event loop.
- `nit:` Appendix says `main.py:909` as a workspace caller; that is a continued `switch_worktree_branch` call started at `app/main.py:908`, so the reference is imprecise but not substantively wrong.

**Refactoring Plan**
- `suggestion:` P0 mostly makes sense, but “P0 is zero structural risk” at `docs/reviews/arch-audit.md:247` is too confident. Wrapping `tm_yougile.py` DB blocks in `to_thread` is low-risk but can change transaction timing around YouGile HTTP calls.
- `issue:` P0 should include `routes/tm.py` sync DB/API wrappers alongside `tm_yougile.py`. Current handlers are `async def` but call sync DB/API directly at `app/routes/tm.py:53`, `app/routes/tm.py:64`, `app/routes/tm.py:78`, `app/routes/tm.py:92`, `app/routes/tm.py:110`, `app/routes/tm.py:119`, `app/routes/tm.py:128`, `app/routes/tm.py:148`, `app/routes/tm.py:158`.
- `suggestion:` P1 before route extraction is sound. The `dict | AgentSession` leak blocks clean route moves.
- `issue:` P3 callback registry before P4 is architecturally clean but may be too early for an MVP budget. I’d defer broad event-bus/general callback work until after targeted fixes unless cycles are actively blocking edits. A tiny explicit callback interface is OK; a generic event bus risks abstraction creep.

**Major Misses**
- `issue:` Same async-blocker class missed in `routes/tm.py`: sync SQLite and sync task-manager APIs run in async routes. Examples: `_tm.api_create_task` at `app/routes/tm.py:56`, `_tm._conn()` at `app/routes/tm.py:69`, `_tm.api_update_task` at `app/routes/tm.py:101`, sync payment/status calls at `app/routes/tm.py:113` and `app/routes/tm.py:122`, raw sync queries at `app/routes/tm.py:134`, `app/routes/tm.py:151`, `app/routes/tm.py:160`. This directly contradicts the success criterion in `docs/reviews/arch-audit.md:255`.
- `suggestion:` `main.py` has another blocking async handler: `subprocess.run(..., timeout=10)` in `restart_server` at `app/main.py:1427`. Less severe because it’s manual/admin, but it belongs in the same “sync work in async route” bucket.
- `issue:` `open_file` bypasses `_is_safe_path`: `app/main.py:367` accepts any existing path and launches `xdg-open` at `app/main.py:376` when `ALLOW_OPEN_FOLDER` is enabled. Auth/env-gated, but architecturally inconsistent with `get_file_content` at `app/main.py:336` and `list_files` at `app/main.py:380`.

**Over-Engineering Risks**
- `suggestion:` Splitting `AgentSession` into `SessionState`, `EventLoopSystem`, `CostSystem`, `CompactSystem`, `PersistenceSystem` is likely too much for a 10-user MVP if done literally. Prefer extracting one painful subsystem first, probably cost or compaction.
- `suggestion:` “No file over ~600 lines except `db.py`” at `docs/reviews/arch-audit.md:257` is an arbitrary size target. Good as a smell, bad as a success criterion; it can drive churn.
- `suggestion:` A generic event bus/callback registry may violate “simple/flat/minimal abstractions.” Use explicit startup-wired callbacks first, not a broad pub/sub system.
