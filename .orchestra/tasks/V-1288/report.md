# V-1288 — Antigravity tool calls

**GREEN: 69 passed, 0 failed, 0 skipped; 10/10 intentional regressions detected.**

Work is limited to the broker-provided worker copy. No git operations, deployment,
service restart or live provider calls are performed here; the platform imports and
commits the result on `task-V-1288/agy-tools-ui`.

## Findings and decisions

- `_consume` emitted a bare tool name, losing arguments in persisted log content.
  Claude, Codex and the harness serialize even empty arguments as `{}`; follow that contract.
- The configured server map is `self.mcp_servers` in this checkout (no `_mcp_servers`).
  Eager MCP matching must prefer longer server names to resolve underscore prefixes.
- Terminal steps may omit parameters; retain the emitted metadata for both event types.
- Baseline required runner: provisioned uv 0.11.28, default `.venv`:
  `uv run --frozen python -m pytest tests/test_antigravity_runtime.py -q`:
  **5 passed**, 3.98 s; `baseline.log`. Frozen tests are unchanged.

## Changes

- `app/backend_antigravity.py:324`: emit `name: <JSON>` including empty `{}`;
  unwrap lazy MCP envelopes and eager calls matching configured servers; attach
  canonical name, short name and redacted input to use/result events. Conversation
  identity prevents compacted-step collisions. Repeated ACTIVE/terminal updates are
  emitted once, terminal-only DONE/ERROR gets a preceding call, and terminal rows
  without parameters retain the original call metadata.
- `app/static/js/tool-renderers.js:19`: shared built-in aliases/argument normalization,
  historical MCP labels/icons, lazy-envelope defense, and normalized read/diff views.
- `app/static/js/chat.js:1463`: full/compact cards consume the same normalized calls;
  Bash LF/CRLF preambles become exit badges plus real five-line output; read stats
  replace skeletons without fake code, numbered read bodies lose provider metadata;
  explicit errors override successful edit/special-card completion. Compact expansion
  retains original output and the error flag, including empty results.
- `app/static/js/live-activity.js:129`: clocks recognize normalized timeout/daemon args.
- `CHANGELOG.md:9`: hand-written Unreleased entry referencing V-1288.
- Added `tests/test_antigravity_tools_v1288.py` and
  `tests/antigravity_tools_v1288_node.cjs`. Existing frozen runtime tests were untouched.

## Verification

All Python runs used provisioned uv **0.11.28** on PATH and the default `.venv`.
Only locked dependency setup accessed PyPI; tests used synthetic local streams,
mocked providers/quotas and an offline Node DOM double. No provider inference.

Final command (with broker uv PATH and task-local TMPDIR):

```sh
nice -n 10 uv run --frozen python -m pytest tests/test_antigravity_runtime.py tests/test_antigravity_tools_v1288.py tests/test_live_tool_activity_831.py tests/test_antigravity_usage.py -q
```

**69 passed in 4.99 s** (`focused-r2.log`). Covers Unicode/empty/malformed args,
lazy/eager/unknown MCP names, overlapping server prefixes, actual parent-report
tracking, retained result metadata, terminal-only errors, repeated updates,
conversation/resume/fallback IDs, redaction, all requested aliases, full/compact
rendering, read offsets/ranges/diffs, timeout/daemon handling, CRLF/LF zero/nonzero
exit statuses and previews, silent commands, Markdown/code/image read summaries,
numbered reads, explicit/wrapped errors and compact error expansion. Existing live
activity and Antigravity usage contracts also pass.

Mutation controls execute production source in memory without editing files:
4 backend mutations (serialization, conversation ID, deduplication, lazy MCP) and
6 frontend mutations (tool alias, lazy MCP, exit-code extraction, read stat rendering,
explicit edit error handling, live timeout normalization). Every mutation is rejected
by an assertion; a parser/runtime exception alone is not accepted as detection.

Imported `app` path (also `import-path.log`):

`<hub-workspace>/app/__init__.py`

- R1 focused run: **39 passed, 2 failed** (3.91 s), `focused-r1.log`.
  Both failures were new mutation-harness defects: the read negative control raised a
  TypeError before its assertion, and the edit mutation replaced an earlier unrelated
  compact dispatcher expression. Fixed with optional access in the read assertion and
  a unique full-result mutation anchor. Product scenarios and frozen tests passed.
- Browser resource inspection found two already-running headless browser roots owned by
  other jobs. No third browser was launched. Frontend checks use an offline Node DOM
  double executing the production JS; actual browser layout/integration is unverified here.
- `scripts/check_instruction_contract.py` is not supplied in this worker copy.

## Handoff and limits

- Full browser layout/SSE integration and a live agy 1.5.8 invocation remain unverified;
  the suite exercises captured wire shapes, stream consumption and production JS offline.
- The full-suite runner `scripts/run_tests.py` is also absent; no full-suite result claimed.
- Source inspection completed; focused Python imports and JS execution passed. Task-local
  synthetic runtime/temp state was removed; no owned test processes remain.
- No production state, credentials, provider settings, git branches, services or remote
  infrastructure were modified. Activation/restart and post-import acceptance belong to
  the orchestrator. No browser screenshot or final visual verdict is claimed.
- Platform commit requested: **`#V-1288: Preserve Antigravity tool arguments and render native cards`**.
  Worker instructions forbid direct commits; platform imports/commits the changed files.
- Complete completion report is queued in root `.orchestra-outbox.jsonl` using the
  supported `send_message` envelope; delivery happens after this turn ends.

## Public evidence sanitization

Per orchestrator follow-up, replaced the Hub workspace prefix and all listed
personal/host fragments with `<hub-workspace>` in task evidence, including
truncated traceback paths. Raw evidence is archived by the orchestrator at
`.orchestra/private/V-1288/`. Protected source/test/changelog hashes are unchanged.
A recursive `rg` check of this task directory found zero remaining matches.
