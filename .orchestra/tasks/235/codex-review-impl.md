The guarded call paths fail open only for missing fan-barrier tables while re-raising unrelated OperationalError instances. Evidence from the reviewed diff: `import sqlite3`.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens
