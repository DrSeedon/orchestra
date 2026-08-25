# Personal memory

- For the dashboard IndexedDB mirror, keep the database version stable and validate a content
  epoch in a raw `logs + meta` transaction before `_storeOpen()` resolves. Stamp the same epoch
  on each row too: an already-open old tab can reinsert old-format records after the meta reset,
  so an open-only marker does not make incompatible reads impossible.
