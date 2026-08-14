# grok-263

- Live Orchestra DB is `/home/kesha/orchestra/data/orchestra.db`. Worktree
  `app.db._DEFAULT_DB_PATH` is worktree-local and is **not** production.
- Copy a live SQLite+WAL only with `sqlite3.Connection.backup`, never `cp`.
- Received pytest already green → do not author a new check; mutate existing
  protection if the ticket asks for a red/green mutation.
- Do not put `set -e` around an expected-red pytest before the file restore:
  the red exit skips the rollback.
