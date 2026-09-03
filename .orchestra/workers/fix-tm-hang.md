# fix-tm-hang

- `sqlite3.Connection.backup` warms the copied database's page cache and can hide a cold-start
  latency failure. For a cold arm on a disposable copy, record a warm control and use
  `os.posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED)` on that copy only; #395 changed startup
  16.123→213.691 s and exposed a 108.216-second create without touching live state.
- A constant-size receipt proves that a transaction completed, not that every stored byte stayed
  uncorrupted. Keep readiness O(1) by treating it as a commit marker, then validate selected rows
  before serving them and run the full integrity scan on an owned background/recovery path.
- Across non-atomic canonical+projection writes, never delete a PENDING request merely because the
  writer raised: first resolve its deterministic canonical identity. Existing identity means
  recover; proven absence means the reservation can be released for a real retry.
- When merging contours that reused task numbers, inspect both task directories by filename even
  if the handoff says artifacts do not conflict; preserve one side under descriptive names and
  repair every KB evidence link so a fact cannot silently point at the other task's document.
