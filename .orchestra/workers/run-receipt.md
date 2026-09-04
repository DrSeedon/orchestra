# run-receipt

- When a new contract intentionally supersedes an older regression with the same semantic input, stop instead of making production distinguish by incidental metadata; get the old fixture updated to express the new prerequisite and retain the formerly allowed state as an explicit negative case.
- A temporary worktree proves a baseline only after the command actually `cd`s into it; creating the worktree while running pytest from the current checkout measures the wrong branch.
- An `init_db` reconciliation may query only columns whose additive migrations have already run in that same function; table existence alone does not prove the required legacy columns exist.
- Keep the shared task CAS identity shape stable. Carry task-run input provenance in a separate `task_snapshot_ref`; adding `canonical_head` to the identity leaks into exact consumers and rereading it after a status write makes an idempotent assignment look like provenance drift.
