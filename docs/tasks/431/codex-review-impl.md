<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The attachment formatting and normal error paths pass the targeted tests and the full mcp_stdio test file. However, oversized inputs are read into memory before rejection, creating a shared-process availability risk.

Review comment:

- [P1] Enforce the attachment limit before unbounded reads — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-attach/app/mcp_stdio.py:1157-1158
  When `file_path` points to a multi-megabyte or gigabyte file, `read_bytes()` loads the entire file before the 64 KiB check. This can exhaust or stall the shared MCP process instead of returning the required explicit size error; check the regular-file size or perform a bounded `MAX+1` read first.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Round (2026-09-01T17:19:18Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently the 64 KiB envelope no longer requires swallowing the warehouse first. 😏

Re-review status: APPROVED

- Prior P1: FIXED. Oversized files are rejected via `stat()` before delivery; the bounded `MAX+1` read handles races.
- New findings: None.
- Verification:
  - `uv run pytest -q tests/test_mcp_stdio.py -k 'send_message' --timeout=30` — `8 passed, 109 deselected`
  - `uv run pytest -q tests/test_message_delivery_receipts_380.py --timeout=30` — `25 passed`
  - `uv run pytest -q tests/test_mcp_stdio.py --timeout=30` — `117 passed`
- Changed line: `with path.open("rb") as attachment_file:`

The old code mailed a warehouse in a 64 KiB envelope; this one finally checks the envelope first.
