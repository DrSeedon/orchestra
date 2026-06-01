**BLOCKING**
None found.

**SUGGESTION**
- [app/manager.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-p1/app/manager.py:891): waiting-state restore is only applied in the worker resume loop. Orchestrators can also own bg jobs via default `bg_create(target="you")`, so a waiting orchestrator resumes as idle even if `bg_manager.has_active_jobs(id)` is true. Not crash/data-loss, but it defeats #10 for orchestrators.
- [app/tg_bridge.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-p1/app/tg_bridge.py:872): `_poll_conn` should still get a `try/finally: close()` around the infinite loop. This is a real but small leak only if stream tasks are cancelled/restarted in-process; at ~10 users it is not blocking. The FastAPI SSE path already closes correctly.

**NIT**
None.

Checked the called-out items: #6 reset ordering is correct, #8 flags-after-send is correct, #13 persist remains single-flight per session despite the dedicated executor, and #19’s long-lived SQLite reads do not hold a read transaction between polls. I could not run pytest in this sandbox because there is no writable temp directory; `git diff --check` passed.
