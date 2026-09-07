# Reusable workflow notes

- CI tests that inspect managed CLI argv must pin executable constants to installed stable paths (for example `/bin/true`), not depend on Codex/Grok being installed in the runner.
- Tests around runtime capabilities should patch the capability seam when neighboring tests can mutate the global registry; otherwise CI ordering can change the branch under test.
- When adding a NOT NULL review_receipts column, update every receipt producer, including `scripts/migrate_review_receipts.py`, and mutation-check the migration apply test.
