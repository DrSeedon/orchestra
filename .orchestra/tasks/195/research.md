# Task #195 evidence

- Before the change, `uv run pytest -q tests/test_migrate_agent.py::test_encoding_matches_real_cli_directories` failed on 17 live `/tmp/tmp.*` pairs; the first was `/tmp/tmp.2YpeKWs1py` → `-tmp-tmp-2YpeKWs1py`.
- The live probe found 149 `cwd → directory` pairs. `cwd.replace('/', '-')` matched 132/149; mapping dots to dashes matched 149/149.
- No directory under `~/.claude/projects` contains a dot, so the observed migrated/live state has no legacy dot-encoded directory to invalidate.
- After `enc_cli_dir()` changed to map both `/` and `.`, the focused test and the deterministic dot test passed. The old one-line implementation was restored for the mutation run and made the live test fail; the restore marker occurred once.
- Full file: `23 passed`.
