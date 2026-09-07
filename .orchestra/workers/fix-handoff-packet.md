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
- **Never undo a mutation with `git checkout -- <file>` while the file has uncommitted
  work.** It reverts to HEAD and takes the new code with it. In #509 that silently
  deleted a whole new route mid-mutation-run, and the "restored" pass stayed red until I
  re-typed it. Copy the file to `/tmp` first and restore with `cp`, as for every other
  mutated file.
- **Adding a `NOT NULL DEFAULT ''` column to `review_receipts` means FOUR writers.**
  `review_receipt_create`, `review_receipt_reserve`, `review_receipt_record_skip` and the
  task-run writer each build values from `_REVIEW_RECEIPT_COLUMNS` with `.get()`, so a
  missing key inserts NULL and the constraint fires. The table default does not save you.
- **`record_review_outcome` order: `accepted` first, `attested` second.** Calling
  `attested` on a receipt whose `author_outcome` is still `unknown` is refused with
  `attestation_outcome_not_attestable: unknown`; the tool description does not say so.
  The receipt id is not in the artifact — read it from `review_receipts` in
  `data/orchestra.db` (read-only) by `task_id` and `round`.
- **Before promising an attestation, run the gate's own parser.**
  `review_findings(Path(artifact).read_text(), worktree=...)` from
  `app/review_coverage.py` prints the anchors the gate will accept. Empty list → no
  `closed_findings` value can ever pass, take a resume round instead.
- **Runtime handoff packet has two copies with different rules.** Ledger
  (`runtime_handoffs.packet_json`, hash `packet_sha256`) keeps constraint bodies — the
  idempotent replay in `_prepare_runtime_handoff` and `/handoffs/{id}/events` both
  verify against it. The delivered candidate is a projection with its own recomputed
  hash. Change the projection and you must also touch `confirm_runtime_handoff`
  (`app/db.py`), which recomputes the expected candidate hash per attempt mode.
