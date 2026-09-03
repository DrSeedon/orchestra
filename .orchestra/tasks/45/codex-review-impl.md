The security fixes are mostly in the right direction, but the rename change can drop recent in-memory prompt edits, and the new upload download header should not interpolate unsanitized filenames.

Full review comments:

- [P2] Preserve loaded prompts during rename — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-security/app/main.py:678-681
  For loaded sessions, this now derives `system_prompt` from the database row rather than the live `session`. If `/api/sessions/{name}/prompt` just called `_persist()`, that write is asynchronous; a rename in that window reads the stale DB prompt and then overwrites `session.system_prompt`, so the recent prompt edit is lost. Use the live session values for loaded sessions after the DB uniqueness update succeeds, or drain the pending persist before reading from DB.

- [P2] Escape filenames in the download header — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-security/app/main.py:1195-1195
  When an authenticated upload uses an original filename whose suffix contains quotes or control characters, `upload_file` preserves that suffix in the stored name. Interpolating `path.name` directly into `Content-Disposition` can create malformed or unsafe response headers when serving `/uploads/...`; use Starlette's `filename=` handling or quote/sanitize the value.