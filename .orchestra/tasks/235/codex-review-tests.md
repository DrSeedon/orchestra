The guard can be bypassed by a valid SQLite file URI, allowing a test to open the live production database despite the isolation requirement.

Review comment:

- [P1] Block SQLite URIs with a localhost authority — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-test-prod-db/tests/conftest.py:26-27
  blocking: When a test connects with `sqlite3.connect("file://localhost<absolute-production-path>", uri=True)`, SQLite accepts the URI and opens the production database, but stripping only `file:` leaves `//localhost/...`, which resolves to a different filesystem path and bypasses the guard. Normalize SQLite's permitted `localhost` authority before comparing, and add this form to the rejection test.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Round (2026-08-13T05:41:35Z)

Re-review status: Prior P1 FIXED. `file://localhost<absolute-path>` is normalized and rejected; targeted tests pass (2/2).

New findings: None.

Verdict: APPROVED.

Verbatim reviewed line: `assert calls == []`
