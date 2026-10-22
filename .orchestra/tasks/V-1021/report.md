# V-1021 — "Argument list too long" starting Claude (Orchestra-orchestrator, 22.10 07:46 UTC)

## Cause
`app/backend_claude.py` passed the system prompt as SDK preset `append`; the SDK
(`subprocess_cli.py:586`) emits it as one argv value `--append-system-prompt <text>`. Linux
MAX_ARG_STRLEN is 131072 bytes per argument (Cyrillic = 2 bytes/char), so a post-compaction
connect with memory + handoff summary overflowed it (`[Errno 7]`).

## Change
- `ClaudeBackend._set_appended_system_prompt` (plain branch and `_history_import` branch with
  `HISTORICAL_TOOL_INSTRUCTION`): writes the text to `~/.orchestra/system-prompts/<instance key>.md`
  (dir 0700, file 0600, atomic replace, same pattern and location family as the MCP config, outside
  any worktree), sets `options.system_prompt = {"type":"preset","preset":"claude_code"}` (no `append`) and
  `options.extra_args["append-system-prompt-file"] = path`. The SDK emits `--append-system-prompt-file <path>`.
- Rewritten on every `_make_client()` (every connect); removed in `disconnect()` next to the MCP config.
- Resume branch (no system prompt) is unchanged. `system_prompt_sha256` still hashes `self.system_prompt`.
- Checked the installed CLI 2.1.293 actually honours the flag: a file saying "Reply only with PINEAPPLE" made `claude -p go --append-system-prompt-file f` answer PINEAPPLE.
- `tests/test_backend_claude.py`: the history-import test now reads the file instead of `["append"]`.
- New `tests/test_claude_append_prompt_file_v1021.py` (6 tests): >131072-byte Cyrillic prompt → no argv arg
  reaches the limit and the file holds the exact text; small prompt also goes only through the file (no inline
  flag, one path); history-import branch; 0600/0700, outside cwd, overwritten on re-connect; removed on
  disconnect; sha256 is of the text. Mutation back to inline `append`: 5 of 6 fail (the sha test is
  independent of transport by design).

## Verification — what I could and could not run
The task copy contained only `app/backend_claude.py` (no other `app/*`, no `uv`), so the project
suite could not run here and `import app` has no `__file__` (namespace package; imported
`app.backend_claude` = `<task copy>/app/backend_claude.py`). I ran the new test file against the
real SDK (claude-agent-sdk 0.2.164, `/tmp/venv`) with throwaway stubs for the four missing sibling
modules (errtext, events, runtime_history, usage_contract; plus models and claude_history): 6 passed;
mutation: 5 failed. NOT run: `tests/test_backend_claude.py` and `tests/test_mcp_config_isolation.py`
against the real app. Please run
`uv run --frozen python -m pytest tests/test_claude_append_prompt_file_v1021.py tests/test_backend_claude.py tests/test_mcp_config_isolation.py -q`
in the full checkout before merging.

## Risks
- Workers started with `ORCHESTRA_AGENT_UID` run the CLI as another uid; the 0600 prompt file (like the existing MCP config) must be readable by that uid. If the MCP config already works for them, so does this; I did not verify the uid-drop path.
- Python change → needs a restart after merge; I did not restart anything.
