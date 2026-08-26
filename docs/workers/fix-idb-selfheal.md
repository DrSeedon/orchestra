# Personal memory

- For the dashboard IndexedDB mirror, keep the database version stable and validate a content
  epoch in a raw `logs + meta` transaction before `_storeOpen()` resolves. Stamp the same epoch
  on each row too: an already-open old tab can reinsert old-format records after the meta reset,
  so an open-only marker does not make incompatible reads impossible.
- When adding nullable columns to an existing SQLite table, create indexes that reference them
  only after the additive migration. `CREATE TABLE IF NOT EXISTS` leaves the old table untouched,
  so an index in the initial schema script fails before `ALTER TABLE` can run.
