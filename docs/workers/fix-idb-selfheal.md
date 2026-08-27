# Personal memory

- For the dashboard IndexedDB mirror, keep the database version stable and validate a content
  epoch in a raw `logs + meta` transaction before `_storeOpen()` resolves. Stamp the same epoch
  on each row too: an already-open old tab can reinsert old-format records after the meta reset,
  so an open-only marker does not make incompatible reads impossible.
- When adding nullable columns to an existing SQLite table, create indexes that reference them
  only after the additive migration. `CREATE TABLE IF NOT EXISTS` leaves the old table untouched,
  so an index in the initial schema script fails before `ALTER TABLE` can run.
- For dashboard Playwright tests that clear chat state, let the initial async context fetches settle
  first; otherwise a late response can erase the injected fixture and produce intermittent false failures.
- For dashboard tests asserting a manually applied agent status, isolate `renderAgentList` while
  awaiting a real `refreshSessions()`; otherwise the refresh can overwrite the badge during the assertion.
- When isolating a renderer in a shared dashboard fixture, wait for the target DOM node before
  replacing it; otherwise the stub can prevent the production path from creating the node at all.
- For IndexedDB chat mirrors, compare the stored page top to a locally cached server watermark before
  painting; an epoch/schema check alone cannot detect compatible but stale content.
- For multi-session mirrors, the freshness watermark must be keyed by session id; a global log max
  turns unrelated activity into false stale-page fetches.
