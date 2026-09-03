# #249 — preregistered Antigravity CLI experiment protocol

Recorded before the first usage-bearing run on the eligible Latvia-associated account. Read-only `/quota` and `models` calls already returned successfully and consumed zero tokens.

## Fixed environment

- Official Antigravity CLI 1.1.12, SHA-512 already checked against the official installer manifest.
- One saved consumer OAuth profile; no API key.
- Same VPS and FR IPv4 / DE IPv6 egress used for both rejected Russia-associated accounts.
- Scratch workspaces only under `data/research-249-antigravity/probes/`; production files are read-only when explicitly added.
- Usage-bearing commands have a 5-minute timeout and raw stdout/stderr are saved separately.

## Metrics

For every turn record:

- process exit code;
- ordered NDJSON event types;
- terminal status and root `conversation_id`;
- input, output, thinking, cache-read and total tokens;
- native/MCP tool name and result;
- quota `remaining_fraction` before and after.

Quota estimate for a repeat of task shape `t`: `tasks_remaining ~= remaining_fraction / observed_fraction_drop_t`. If the provider reports no drop at its output precision, report only a lower bound from the cumulative measured work; do not invent an absolute limit.

Stop usage tests when either weekly group drops by 5 percentage points, any credential/eligibility/rate error appears, or the planned tasks below finish. Do not increase load merely to force a visible percentage.

## E1 — streaming, native tool use, root ID and cwd-isolated resume

Model: `gemini-3.6-flash-low`, cheapest listed Gemini model.

1. In isolated cwd A, ask the agent to use a native terminal/write tool to create `native-marker.txt` with `AURORA-249-A-71C4`, reply `ACK-A`, and remember `MEMORY=AURORA-249-A-71C4`.
2. In isolated cwd B, repeat with `BOREAL-249-B-92F7` and `ACK-B`.
3. Inspect terminal results and `~/.gemini/antigravity-cli/cache/last_conversations.json`.
4. Run `agy -c` from A and B separately; demand the remembered value without tools/filesystem.

Pass requires incremental `init`/`step_update`/`result`, a real tool event plus matching file side effect, and correct distinct memory in each cwd. A non-empty root ID passes exact-ID capture. A blank root ID with correct A/B `-c` proves only the unique-cwd workaround; same-cwd parallel sessions remain unsupported.

## E2 — unique control cwd plus real repository via `--add-dir`

Model: `gemini-3.1-pro-low`.

From a third isolated control cwd, add this worktree with `--add-dir` and ask the agent to inspect the exact existing `app/backend_protocol.py`, reporting its six protocol methods with no edits.

Pass requires tool evidence that the named existing file was read and the exact six methods are returned. This checks whether a backend can give every no-worktree Orchestra session a private conversation cwd while mounting its real target directory.

## E3 — MCP invocation, not discovery

Model: `gemini-3.6-flash-low`.

Configure workspace-local `.agents/mcp_config.json` with one stdio server exposing only `record_probe(marker)`. Ask the agent to call that MCP tool with `MCP-249-5E8A`; forbid shell/native write tools.

Pass requires all three: stream `tool_info` names the MCP tool, MCP response says `RECORDED:MCP-249-5E8A`, and the server-side marker file contains the exact value. Discovery alone is a fail.

## E4 — third-party model pool

Models and real read-only tasks:

- `claude-sonnet-4-6`: inspect the current backend lifecycle seams named in `research.md` and identify the late-credential-validation path, with file:line evidence.
- `claude-opus-4-6-thinking`: adversarially evaluate the unique-cwd resume workaround against `SessionManager` support for worktree and non-worktree sessions, with file:line evidence.

Pass per model requires a successful usage-bearing turn, real file-read tool events, non-zero token usage and no fallback model in the stream. Quota is sampled after each task. These two tasks share the `3p-weekly` pool by provider contract.

## E5 — compact surface

Use quota-free read-only `/help`, `/context` or documented help output. Confirm automatic compaction from the 1.1.3 changelog. Do not manufacture a context-window-sized workload.

Pass for Orchestra requires either a native external compact command or compatibility with Orchestra's existing summarize-to-fresh-session fallback. Automatic internal compaction alone does not satisfy manual compact control.

## Execution deviation and stop

The quota stop was not sampled after every turn as preregistered. Thirteen short Gemini
results were run before the next `/quota` sample; that sample reported
`remaining_fraction=0.83995521068573` rather than the baseline `1.0`. The batch therefore
consumed approximately **16.0 percentage points**, exceeding the 5-point stop condition
before it could fire. All further inference probes were stopped immediately. E4 was not run;
the Claude/GPT group remained at `1.0`.

This is a protocol deviation, not a quota estimate to smooth away. It means the run establishes
only the measured cost of this particular mixed probe batch and a strong warning that even
Flash-low tool turns are not cheap on this tier. It does not establish an absolute weekly token
allowance or a per-task conversion factor.
