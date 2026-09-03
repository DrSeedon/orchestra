# fix-task-timeout

- `bg_create(type="run")` starts in the main checkout, not this worktree. For worktree scripts,
  use an explicit worktree `cd`, `PYTHONPATH=<worktree>`, and the main project's existing
  `.venv/bin/python3`; `uv run` inside a fresh worktree creates an empty local `.venv`.

