# fix-handoff-packet — personal notes

- **Tests need the project venv, not `python`.** `python -m pytest` in a worktree dies
  at `tests/conftest.py:153` with `ModuleNotFoundError: No module named 'dotenv'`. Use
  `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest`; it still imports
  `app` from the worktree (verified via `app.__file__`), which is what the reporting
  rule asks for.
- **Get a baseline before blaming yourself for a red test.** `git worktree add --detach
  /tmp/<name> HEAD` gives a pristine copy of the branch tip with zero risk to the shared
  stash; run the same suite there, then `git worktree remove --force`. In #507 one of
  four failures was already red at HEAD.
- **Runtime handoff packet has two copies with different rules.** Ledger
  (`runtime_handoffs.packet_json`, hash `packet_sha256`) keeps constraint bodies — the
  idempotent replay in `_prepare_runtime_handoff` and `/handoffs/{id}/events` both
  verify against it. The delivered candidate is a projection with its own recomputed
  hash. Change the projection and you must also touch `confirm_runtime_handoff`
  (`app/db.py`), which recomputes the expected candidate hash per attempt mode.
