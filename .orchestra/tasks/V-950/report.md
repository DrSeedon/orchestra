# V-950 — bare checklist tool name misses for Claude agents

## Evidence (read-only, live DB `logs`, 2026-10-10 onward unless stated)
- `update_checklist` (bare) called 10 times, plus 1 placeholder; correct `mcp__orchestra__update_checklist` 335 times in the same window. Each bare call returned `No such tool available: update_checklist`. The same miss exists for `update_progress` (4) and `bg_create` (3), so it is not specific to the checklist; it is the most frequent only because it is the most used tool.
- The tool is registered normally: `mcp__orchestra__update_checklist` succeeds in the same sessions. So the cause is the name the model chooses, not registration.

## Cause
`task-management.md` (lines 12, 33), `base.md` and others name tools bare (`update_checklist(...)`, `update_progress(...)`, `bg_create`). Claude Code registers MCP tools as `mcp__<server>__<tool>`, and a model usually bridges the gap (≈97% here) but sometimes copies the bare name, typically on the first call after compaction or a new assignment.

## Runtime naming (checked in code, not guessed)
- Claude: `mcp__orchestra__<tool>` (prefix required).
- Codex: the model calls server `orchestra`, tool `<tool>`; the `mcp__` form exists only in our log naming (`app/backend_codex.py:1632,1738`).
- OpenRouter harness: tool schemas carry no prefix (`app/harness/mcp.py:233`); `display_name` adds `mcp__` only for the dashboard (`mcp.py:242`).
So the prefix is Claude-only; prefixing every mention would mislead Codex/harness.

## Fix
One sentence in `base.md` (delivered to every role and runtime): rules name tools without the server prefix; in Claude Code call `mcp__orchestra__<name>`, e.g. `mcp__orchestra__update_checklist`; other runtimes use the bare name. It covers all tools, not only the checklist, and costs about 50 tokens per prompt. Per-runtime substitution in the assembler was rejected: it would change nine module texts and need a runtime-aware renderer for a 2% slip that one line addresses.

## Not verified
No re-measurement yet: the effect is visible only as the rate of bare-name calls in `logs` after sessions rebuild their prompt (baseline ≈2% for the checklist). The lost-checklist case (a later session did not retry) is not covered by the text.

## Restart
Not required: prompt files are read when a session's prompt is built; running sessions pick it up on their next rebuild.
