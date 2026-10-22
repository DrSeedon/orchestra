# V-1023 — AttributeError `_append_prompt_path` in disconnect()

V-1021 added `_remove_append_prompt()` to `ClaudeBackend.disconnect()`; tests/test_disconnect_dead_process.py builds the
backend via `__new__` (no `__init__`) and stubs only `_remove_mcp_config`, so `_append_prompt_path` was missing.

Fix: class-level `_append_prompt_path: Path | None = None` in `app/backend_claude.py`. Nothing else changed.

Tests (`/tmp/venv/bin/python -m pytest`, no `uv` on this hub): tests/test_disconnect_dead_process.py +
tests/test_claude_append_prompt_file_v1021.py → 8 passed (incl. the V-1021 file-removed-on-disconnect test).
