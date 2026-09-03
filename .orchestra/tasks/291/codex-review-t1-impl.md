The acceptance oracle passes, but two enum constraints accept NULL under SQLite semantics. This permits invalid durable rows, including immutable outcomes that cannot subsequently be corrected.

Full review comments:

- [P2] Reject NULL outcome statuses — /home/kesha/orchestra/worktrees/home-kesha-orchestra/impl291-t1/app/db.py:74-76
  Because `status` lacks `NOT NULL`, SQLite treats the `CHECK` result for `NULL` as valid, allowing immutable outcome rows with no recognized terminal status. Such rows cannot be repaired due to the update/delete triggers, so the enum constraint must also prohibit NULL.

- [P2] Reject NULL reserve-intent states — /home/kesha/orchestra/worktrees/home-kesha-orchestra/impl291-t1/app/db.py:108-110
  The `state` enum is nullable, and SQLite permits NULL through this `CHECK`. Any caller can therefore create an intent outside the declared lifecycle states, defeating the schema-level enforcement expected from this migration; add `NOT NULL` to the column.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Round (2026-08-16T11:23:02Z)

## Re-review status

- FIXED — `quota_controller_outcomes.status` is now `NOT NULL` with the enum `CHECK`.
- FIXED — `quota_controller_reserve_intents.state` is now `NOT NULL` with the enum `CHECK`.

## New findings

None within T1 scope. The frozen oracle passes: `5 passed in 1.98s`.

## Verdict

APPROVED

Verbatim changed line:

`c.execute("BEGIN IMMEDIATE")`
