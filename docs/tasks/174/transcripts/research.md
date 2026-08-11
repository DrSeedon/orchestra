# #174 transcript portability — Claude, Codex, Grok

Date: 2026-08-11

Worker: `r174-transcripts`

Scope: research only. All writes and CLI resumes used this worker's own sessions or copies beneath the freshly created `/tmp/r174-transcripts.v9rnWv`; no live session, production database, or production config was mutated.

Conversation text, OAuth material, signatures, request IDs, and UUIDs below are replaced by angle-bracket placeholders. Commands and protocol payload shapes are otherwise reproduced exactly.

## Verdict

1. **Claude direct JSONL:** a target-native, one-row `user` transcript is enough for Claude CLI 2.1.197 to resume and semantically recall an imported marker. This is a successful forgery of an internal format, not a stable public schema.
2. **Claude SDK `SessionStore`:** SDK 0.2.114 is a cleaner supported injection seam. A custom store returning the same one-row synthetic entry was loaded once, materialized to a temporary Claude project JSONL, resumed, and semantically recalled. The SDK explicitly declares each entry's concrete shape opaque/internal, so the seam removes filesystem placement work but not the native-schema dependency.
3. **Codex forged rollout:** codex-cli 0.146.0 accepts a two-row synthetic rollout (`session_meta`, then user `response_item`) from disk and semantically recalls the marker. Raw Claude JSONL is not accepted as a Codex rollout.
4. **Codex in-memory history:** the installed 0.146.0 app-server both advertises and accepts `thread/resume.history: Vec<ResponseItem>`. It requires initialize capability `experimentalApi=true`; without it the exact error is code `-32600`. With the capability, a two-item provider-neutral user+assistant history is accepted, a fresh thread ID is returned, and the next model turn recalls the marker. This is the cleanest measured Codex import seam, but the generated schema marks it `UNSTABLE` and `FOR CODEX CLOUD - DO NOT USE`.
5. **Codex path:** the installed app-server also accepts `thread/resume.path`, again only with `experimentalApi=true`. It resumed the forged rollout from an arbitrary absolute temp path and recalled the marker.
6. **Grok:** no Grok executable, user Grok home, credentials, or managed `data/grok-home` exists on this VPS/worktree now. Therefore no current Grok acceptance experiment was possible. Current source says the store is under stable `GROK_HOME`, keyed by `(cwd, sessionId)`, and historical task #95 measured its file layout, but those are source/historical evidence rather than a current on-disk sample.

## Evidence tiers

- **A — current direct measurement:** command executed on this VPS on 2026-08-11 against installed binaries, with an isolated temp home/session.
- **B — current primary local source:** installed SDK source, generated installed-binary protocol schema, or current repository source.
- **C — prior project measurement:** committed task #95 evidence from a different machine/date; useful, but explicitly not current system ground truth.

## Environment and safety boundary

```text
$ pwd
/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts

$ claude --version
2.1.197 (Claude Code)

$ codex --version
codex-cli 0.146.0

$ mktemp -d /tmp/r174-transcripts.XXXXXX
/tmp/r174-transcripts.v9rnWv
```

For isolated auth, only the relevant credential file was copied into each disposable CLI home, with mode 0600. Values were never printed:

```bash
install -m 600 /home/kesha/.claude/.credentials.json "$TEMP_CLAUDE_HOME/.credentials.json"
install -m 600 /home/kesha/.codex/auth.json "$TEMP_CODEX_HOME/auth.json"
```

All resume tests either operated on synthetic files or copies. Codex CLI tests used `--ephemeral`; app-server and SDK tests wrote only below temp homes.

## Claude CLI JSONL

### Current actual file and observed shape [A]

A new owned Claude session was created in an isolated `CLAUDE_CONFIG_DIR`:

```bash
env CLAUDE_CONFIG_DIR=/tmp/r174-transcripts.v9rnWv/claude-own \
  DISABLE_NON_ESSENTIAL_MODEL_CALLS=1 DISABLE_TELEMETRY=1 \
  claude -p '<baseline prompt>' \
  --session-id <OWN_SYNTH_UUID> --output-format stream-json --verbose \
  --model claude-haiku-4-5 --safe-mode --tools=
```

Sanitized result and file:

```text
result.subtype=success result=<MARKER> session_id=<OWN_SYNTH_UUID>
/tmp/r174-transcripts.v9rnWv/claude-own/projects/-home-kesha-orchestra-worktrees-home-kesha-orchestra-r174-transcripts/<OWN_SYNTH_UUID>.jsonl 4027 bytes
```

Structural inspection:

```text
rows 7 bytes 4027
types {'queue-operation': 2, 'user': 1, 'ai-title': 1, 'assistant': 2, 'last-prompt': 1}
user top ['cwd','entrypoint','gitBranch','isSidechain','message','parentUuid',
          'permissionMode','promptId','promptSource','sessionId','timestamp','type',
          'userType','uuid','version']
assistant.message keys ['content','id','model','role','stop_details','stop_reason',
                        'stop_sequence','type','usage']
assistant content types ['thinking'] then ['text']
```

The project directory encoding agrees with current Orchestra migration logic: strip the leading `/` and replace `/` with `-`. Current `ClaudeBackend._resume_transcript_exists()` recursively looks for `projects/**/<session-id>.jsonl` (`app/backend_claude.py:265-280`) [B].

### Exact-copy control [A]

```bash
env CLAUDE_CONFIG_DIR=/tmp/r174-transcripts.v9rnWv/claude-own \
  DISABLE_NON_ESSENTIAL_MODEL_CALLS=1 DISABLE_TELEMETRY=1 \
  claude -p '<control prompt>' --resume <OWN_SYNTH_UUID> \
  --output-format json --model claude-haiku-4-5 --safe-mode --tools=
```

```json
{"type":"result","subtype":"success","is_error":false,"result":"<MARKER>","session_id":"<OWN_SYNTH_UUID>","num_turns":1}
```

This establishes that isolated auth and ordinary native resume work before testing forgery.

### Minimal rewritten transcript [A]

The complete pre-resume file had one line:

```json
{"parentUuid":null,"isSidechain":false,"userType":"external","cwd":"<OWN_WORKTREE>","sessionId":"<SYNTH_SESSION_UUID>","version":"2.1.197","gitBranch":"task-174/r174-transcripts","type":"user","message":{"role":"user","content":"The portability marker imported from another runtime is <MARKER>."},"uuid":"<MESSAGE_UUID>","timestamp":"2026-08-11T07:35:00.000Z"}
```

Placement and command:

```text
$CLAUDE_CONFIG_DIR/projects/-home-kesha-orchestra-worktrees-home-kesha-orchestra-r174-transcripts/<SYNTH_SESSION_UUID>.jsonl
```

```bash
env CLAUDE_CONFIG_DIR=/tmp/r174-transcripts.v9rnWv/claude-min \
  DISABLE_NON_ESSENTIAL_MODEL_CALLS=1 DISABLE_TELEMETRY=1 \
  claude -p '<ask for prior marker>' --resume <SYNTH_SESSION_UUID> \
  --output-format json --model claude-haiku-4-5 --safe-mode --tools=
```

```json
{"type":"result","subtype":"success","is_error":false,"result":"<MARKER>","session_id":"<SYNTH_SESSION_UUID>","num_turns":1}
```

After resume, the CLI had appended ordinary native records:

```text
after_resume_rows 9
types ['user','queue-operation','queue-operation','assistant','user','assistant',
       'assistant','last-prompt','mode']
session_ids_unique 1
```

This proves separately:

- the forged file was accepted;
- the marker became model-visible history;
- the CLI continued persisting under the supplied session ID.

It does **not** make the row schema public or stable.

### Negative controls [A]

Missing transcript:

```bash
env CLAUDE_CONFIG_DIR=/tmp/r174-transcripts.v9rnWv/claude-missing \
  claude -p '<not run>' --resume <ABSENT_UUID> \
  --output-format json --model claude-haiku-4-5 --safe-mode --tools=
```

```text
No conversation found with session ID: <ABSENT_UUID>
```

Raw Codex rollout copied unchanged into Claude's project path:

```bash
env CLAUDE_CONFIG_DIR=/tmp/r174-transcripts.v9rnWv/raw-codex-to-claude \
  claude -p '<not run>' --resume <CODEX_UUID> \
  --output-format json --model claude-haiku-4-5 --safe-mode --tools=
```

```text
No conversation found with session ID: <CODEX_UUID>
codex_raw_as_claude_exit=1
```

Therefore raw files are not cross-runtime portable; target-schema rewriting is necessary.

## Claude SDK 0.2.114 `SessionStore`

### What the installed SDK promises [B]

Installed package/version:

```text
sdk_version 0.2.114
package /home/kesha/orchestra/.venv/lib/python3.12/site-packages/claude_agent_sdk
```

Primary local source says:

- `SessionStoreEntry` is one CLI JSONL line, but the concrete discriminated union is internal and adapters must pass entries through as opaque JSON (`types.py:1354-1367`).
- `SessionStore.load()` returns a full session for resume; the SDK materializes it to a temporary JSONL and invokes existing CLI resume (`types.py:1426-1445`, and the `load` doc immediately below).
- `ClaudeAgentOptions.session_store` is public and explicitly supports materializing resume when local JSONL is absent (`types.py:2058-2064`).
- `ClaudeSDKClient.connect()` validates the store and calls `materialize_resume_session()` before subprocess spawn (`client.py:100-145`).
- materialization creates `claude-resume-*`, writes `projects/<project-key>/<session-id>.jsonl`, copies auth, and points the subprocess at that temp `CLAUDE_CONFIG_DIR` (`_internal/session_resume.py:1-12,70-87,123-190`).

So `SessionStore` is a supported transport/storage seam, while the entries it carries remain intentionally opaque.

### Custom-store semantic test [A]

The test store returned the same one-row synthetic `user` entry shown above. Essential executable code:

```python
class Store:
    async def load(self, key):
        self.loads.append(dict(key))
        return [ENTRY]

    async def append(self, key, entries):
        self.appends.append((dict(key), len(entries)))

opts = ClaudeAgentOptions(
    model="claude-haiku-4-5",
    cwd="<OWN_WORKTREE>",
    resume=SID,
    session_store=store,
    cli_path="/usr/bin/claude",
    max_turns=2,
    tools=[],
    setting_sources=[],
    env={
        "CLAUDE_CONFIG_DIR": "/tmp/r174-transcripts.v9rnWv/claude-own",
        "DISABLE_NON_ESSENTIAL_MODEL_CALLS": "1",
        "DISABLE_TELEMETRY": "1",
    },
)
client = ClaudeSDKClient(options=opts)
await client.connect()
await client.query("<ask for prior marker>")
# Collect until ResultMessage, then disconnect.
```

Exact sanitized output:

```text
store_load_calls 1
load_key {'project_key': '<ENCODED_CWD>', 'session_id': '<SYNTH_SESSION_UUID>'}
semantic_recall True
assistant_text <MARKER>
result_session_id_matches True
store_append_calls 1 appended_entries 6
```

This distinguishes three facts:

1. the public SDK called the custom store;
2. the SDK/CLI accepted its synthetic native entry;
3. the next model turn semantically recalled the marker.

The successful output was not produced by copying into `~/.claude`; the SDK created and later cleaned its own temporary materialization. One earlier diagnostic harness intentionally waited for the persistent client's iterator to end instead of breaking on `ResultMessage`; it timed out after the turn had already completed. Its orphaned temp directory was identified for cleanup. That harness behavior is not a resume failure.

## Codex rollout JSONL

### Current actual own rollout and schema [A]

The current worker's thread ID matched exactly one on-disk file:

```text
/home/kesha/.codex/sessions/2026/08/11/rollout-2026-08-11T09-21-22-<OWN_THREAD_UUID>.jsonl
rows 60 bytes 433819
top_types {'session_meta':1,'event_msg':15,'response_item':42,'world_state':1,'turn_context':1}
```

Observed top-level/payload shapes:

```text
session_meta top ['payload','timestamp','type']
  payload ['base_instructions','cli_version','context_window','cwd','git',
           'history_mode','id','model_provider','originator','session_id',
           'source','timestamp']
event_msg payload ['collaboration_mode_kind','model_context_window','started_at',
                   'turn_id','type']
response_item payload ['content','id','internal_chat_message_metadata_passthrough',
                       'role','type']
world_state payload ['full','state']
turn_context payload ['approval_policy','approvals_reviewer','collaboration_mode',
                      'comp_hash','current_date','cwd','effort','model',
                      'multi_agent_version','permission_profile','personality',
                      'realtime_active','sandbox_policy','summary','timezone',
                      'turn_id','workspace_roots']
```

`response_item` payload types were `message`, `reasoning`, `custom_tool_call`, and `custom_tool_call_output`; message content uses `input_text` / `output_text`. Current Orchestra independently locates a rollout by `$CODEX_HOME/sessions/**/*<thread-id>.jsonl` for usage extraction (`app/backend_codex.py:1454-1467`) [B].

### Exact-copy control [A]

The current own rollout was copied while the current turn was active, hence it contained one dangling tool call. Resume still succeeded:

```bash
env CODEX_HOME=/tmp/r174-transcripts.v9rnWv/codex-control \
  codex exec resume <OWN_THREAD_UUID> '<control prompt>' \
  --json --ignore-user-config --ephemeral
```

```text
copied_lines=76 copied_bytes=458228
WARNING: ... Refusing to create helper binaries under temporary dir "/tmp" ...
{"type":"thread.started","thread_id":"<OWN_THREAD_UUID>"}
{"type":"turn.started"}
ERROR codex_core::util: Custom tool call output is missing for call id: <CALL_ID>
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"<MARKER>"}}
{"type":"turn.completed",...}
```

This is counter-evidence to any assumption that a dangling call makes the whole rollout non-resumable; 0.146.0 logs the defect and continues.

### Minimal two-row forged rollout [A]

Accepted complete fixture:

```json
{"timestamp":"2026-08-11T07:31:00.000Z","type":"session_meta","payload":{"session_id":"<SYNTH_UUID>","id":"<SYNTH_UUID>","timestamp":"2026-08-11T07:31:00.000Z","cwd":"<OWN_WORKTREE>","originator":"r174-portability-test","cli_version":"0.146.0","source":"exec","model_provider":"openai","history_mode":"legacy"}}
{"timestamp":"2026-08-11T07:31:01.000Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"The portability marker is <MARKER>."}]}}
```

Placement and command:

```text
$CODEX_HOME/sessions/2026/08/11/rollout-2026-08-11T09-31-00-<SYNTH_UUID>.jsonl
```

```bash
env CODEX_HOME=/tmp/r174-transcripts.v9rnWv/codex-two \
  codex exec resume <SYNTH_UUID> '<ask for prior marker>' \
  --json --ignore-user-config --ephemeral
```

```text
{"type":"thread.started","thread_id":"<SYNTH_UUID>"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"<MARKER>"}}
{"type":"turn.completed",...}
```

An optional third assistant `response_item` was also accepted, but it is not necessary. Thus the measured minimum for a useful import was two rows: metadata plus one user message.

### Metadata negative control [A]

Before adding `payload.session_id`, `payload.timestamp`, and `history_mode`, the same two-row file was rejected:

```text
Error: thread/resume: thread/resume failed: failed to read thread: thread-store internal error:
failed to read session metadata <TEMP_PATH>: rollout at <TEMP_PATH> does not start with
session metadata (code -32603)
```

This experiment changed the three fields together, so it establishes the accepted complete metadata set above, **not** which individual field is mandatory.

Missing rollout:

```text
Error: thread/resume: thread/resume failed: no rollout found for thread id <ABSENT_UUID> (code -32600)
codex_missing_exit=1
```

Raw Claude JSONL renamed as a Codex rollout:

```text
Error: thread/resume: ... rollout at <TEMP_PATH> is empty (code -32603)
claude_raw_as_codex_exit=1
```

The CLI parser skipped/no longer recognized the Claude rows; raw rename is not portability.

## Codex app-server `thread/resume.history` and `.path`

### Installed protocol advertisement [B]

Generated directly from installed 0.146.0:

```bash
codex app-server generate-json-schema --experimental \
  --out /tmp/r174-transcripts.v9rnWv/codex-schema
```

`codex_app_server_protocol.v2.schemas.json` contains `ThreadResumeParams` with this installed description:

```text
There are three ways to resume a thread:
1. By thread_id: load ... from disk by thread_id.
2. By history: instantiate ... from memory.
3. By path: load ... from disk by path.

For non-running threads, precedence is: history > non-empty path > thread_id.
```

The installed schema types `history` as `array|null` of `ResponseItem`; the message variant requires only `type`, `role`, and `content`, where content supports `input_text` and `output_text`. `path` is `string|null`. Both fields are marked unstable; `history` additionally says `FOR CODEX CLOUD - DO NOT USE`.

### Capability gate [A]

Without experimental capability, exact requests returned:

```json
{"method":"initialize","id":1,"params":{"clientInfo":{"name":"r174-history-test","title":"r174-history-test","version":"1"}}}
{"method":"thread/resume","id":2,"params":{"threadId":"<SYNTH_UUID>","history":["<two ResponseItems>"],"cwd":"<OWN_WORKTREE>","model":"gpt-5.6-sol","approvalPolicy":"never","sandbox":"danger-full-access"}}
```

```json
{"code":-32600,"message":"thread/resume.history requires experimentalApi capability"}
```

For path:

```json
{"code":-32600,"message":"thread/resume.path requires experimentalApi capability"}
```

Current Orchestra initializes Codex with only `clientInfo` (`app/backend_codex.py:390-399`), so these fields are not usable through the existing backend without opting in.

### In-memory two-item history and semantic recall [A]

The isolated app-server was launched with:

```bash
env CODEX_HOME=/tmp/r174-transcripts.v9rnWv/codex-history-exp \
  codex app-server --stdio --disable apps
```

Essential exact requests:

```json
{"method":"initialize","id":1,"params":{"clientInfo":{"name":"r174-history-test","title":"r174-history-test","version":"1"},"capabilities":{"experimentalApi":true}}}
{"method":"initialized","params":{}}
{"method":"thread/resume","id":2,"params":{"threadId":"<IGNORED_SYNTH_UUID>","history":[{"type":"message","role":"user","content":[{"type":"input_text","text":"The prior portability marker is <MARKER>."}]},{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Marker stored."}]}],"cwd":"<OWN_WORKTREE>","model":"gpt-5.6-sol","approvalPolicy":"never","sandbox":"danger-full-access"}}
{"method":"turn/start","id":3,"params":{"threadId":"<RETURNED_THREAD_UUID>","input":[{"type":"text","text":"<ask for prior marker>"}],"model":"gpt-5.6-sol","effort":"low"}}
```

Sanitized harness output:

```text
initialize True experimentalApi_requested True
resume_ok True returned_thread_id <NEW_THREAD_UUID> requested_id_reused False history_param_items 2 notifs_before_response 4
resume_thread_path <TEMP_ROLLOUT_PATH> turns 0
turn_start_ok True turn_id_present True
turn_completed_seen True
semantic_recall True
agent_text <MARKER><MARKER>
```

`agent_text` appears twice because the harness concatenated both the delta and completed-item forms. It is one model answer, not duplicate semantic output.

After resume/turn, the isolated home contained one generated native rollout:

```text
rollouts_created 1
path /tmp/r174-transcripts.v9rnWv/codex-history-exp/sessions/2026/08/11/rollout-<timestamp>-<NEW_THREAD_UUID>.jsonl
rows 16
first types ['session_meta','response_item','response_item','event_msg','event_msg','event_msg','response_item','response_item']
message_roles ['user','assistant','developer','user','user','assistant']
history_marker_persisted True
```

Thus “in-memory” describes the import API and precedence: it did not require a preexisting rollout, but app-server immediately established normal native persistence in the disposable home.

Important current-backend incompatibility: history import deliberately ignored the supplied `threadId` and returned a fresh ID. Current `CodexBackend.connect()` rejects any returned ID different from the requested ID (`app/backend_codex.py:408-421`). A product integration must treat history import as a new native identity rather than pass it through the ordinary resume-ID equality guard.

### Path resume and semantic recall [A]

The accepted two-row forged rollout was copied to the arbitrary absolute path `/tmp/r174-transcripts.v9rnWv/codex-path-fixture/forged.jsonl`, outside `$CODEX_HOME/sessions`. Request:

```json
{"method":"thread/resume","id":2,"params":{"threadId":"<IGNORED_SYNTH_UUID>","path":"/tmp/r174-transcripts.v9rnWv/codex-path-fixture/forged.jsonl","cwd":"<OWN_WORKTREE>","model":"gpt-5.6-sol","approvalPolicy":"never","sandbox":"danger-full-access"}}
```

Output:

```text
path_resume_ok True returned_thread_id <FORGED_METADATA_UUID> requested_id_ignored True path_matches True notifs_before_response 4
turn_start_ok True
turn_completed_seen True
semantic_recall True
agent_text <MARKER><MARKER>
```

This separately establishes:

1. forged rollout accepted from disk via explicit path;
2. `path` precedence over the supplied request ID;
3. next-turn semantic recall.

## Grok current system and historical store

### Current system check [A]

Current backend resolution and filesystem checks:

```bash
GROK_RESOLVED=$(PYTHONPATH=. python3 -c 'import app.backend_grok as b; print(b.GROK_BIN)')
printf 'resolved_GROK_BIN=%s\n' "$GROK_RESOLVED"
test -x "$GROK_RESOLVED"; printf 'binary_executable_exit=%s\n' "$?"
test -d /home/kesha/.grok; printf 'user_grok_home_exists_exit=%s\n' "$?"
test -d /home/kesha/orchestra/data/grok-home; printf 'managed_grok_home_exists_exit=%s\n' "$?"
env GROK_HOME=/tmp/r174-transcripts.v9rnWv/grok-home "$GROK_RESOLVED" --version
```

```text
resolved_GROK_BIN=/home/kesha/.grok/bin/grok
binary_executable_exit=1
user_grok_home_exists_exit=1
managed_grok_home_exists_exit=1
env: ‘/home/kesha/.grok/bin/grok’: No such file or directory
grok_version_exit=127
```

The running Orchestra process also had `GROK_BIN` unset, `HOME=/home/kesha`, and a PATH with no `grok`. Therefore there was no relevant current CLI to test and no live Grok store to copy. Creating `data/grok-home` via `ensure_grok_home()` would have been an unauthorized production/worktree mutation and was intentionally not done.

### Current source contract [B]

Current code establishes:

- resolution order: `$GROK_BIN`, PATH, then `~/.grok/bin/grok` (`app/backend_grok.py:19-25`);
- managed stable home: `<repo>/data/grok-home` (`:27-35`);
- generated config disables Claude/Cursor MCP discovery (`:37-44`);
- `auth.json` is a symlink to `~/.grok/auth.json` (`:100-123`);
- resume is ACP `session/load` with both `cwd` and `sessionId`; failure falls back loudly to `session/new` (`:309-346`);
- the subprocess receives managed `GROK_HOME` last, overriding inherited values (`:1009-1020`).

### Historical measured layout, not current ground truth [C]

Committed `docs/tasks/95/research.md:83-96` records a live Grok 0.2.112 measurement from 2026-07-27:

```text
$GROK_HOME/sessions/<url-encoded-cwd>/<sessionId>/
  events.jsonl
  updates.jsonl
  chat_history.jsonl
  system_prompt.txt
  summary.json
  rewind_points.jsonl
```

That experiment killed the process, started a new `grok agent stdio`, called `session/load {sessionId,cwd}`, and recalled a prior marker. It also established the store key as `(cwd, sessionId)`. This is credible prior evidence, but the current VPS has neither the binary nor those files, so this task does not upgrade it to tier A or claim cross-runtime rewriting works for Grok.

## Portability matrix

| Target seam | Current acceptance | Semantic recall | Stability / blocker |
|---|---:|---:|---|
| Claude raw native JSONL in isolated project dir | yes | yes | internal opaque CLI schema |
| Claude SDK 0.2.114 `SessionStore.load()` | yes | yes | public seam, entries still opaque native blobs |
| Claude given raw Codex rollout | no | n/a | `No conversation found` |
| Codex forged two-row rollout by thread ID | yes | yes | internal rollout schema and date/path convention |
| Codex forged rollout by `thread/resume.path` | yes | yes | experimental capability; unstable API |
| Codex `thread/resume.history` with two `ResponseItem`s | yes | yes | experimental capability; schema says cloud-only/do not use; returns fresh ID |
| Codex history/path without capability | no | n/a | exact `-32600` capability errors |
| Codex given raw Claude JSONL | no | n/a | rollout parsed as empty |
| Grok `session/load` on current VPS | not runnable | not tested | binary/auth/store absent |

## Implications for #174

- A provider-neutral transcript should **not** be copied verbatim between native stores. Both raw-direction controls fail.
- If implementation risk is acceptable, map only role-bearing text into the target runtime's smallest measured import representation; omit reasoning signatures, tool calls, usage, and provider-specific metadata.
- For Codex 0.146.0, `thread/resume.history` is materially cleaner than forged files and was semantically verified. It requires two explicit product changes: negotiate `experimentalApi`, and accept/store the fresh returned thread ID. Its unstable/cloud-only warning is substantial counter-evidence against treating it as a durable contract.
- `thread/resume.path` is useful for migration/diagnostics, but still consumes native rollout schema and is also experimental.
- For Claude SDK 0.2.114, `SessionStore` is the clean supported transport seam. However a converter still has to synthesize opaque Claude CLI entries, so retain the direct one-row CLI acceptance test as a compatibility canary.
- Grok needs a new live probe on a host where the CLI and auth exist before any design can claim transcript rewriting support. The only defensible current behavior is a loud “runtime unavailable / no tested import seam,” not guessed storage mutation.

## Literal acceptance appendix

This appendix is the load-bearing transcript from a second fresh temp root, `/tmp/r174-final.jYS3rD`. The UUIDs and marker strings in this section are disposable test values, not production IDs or user text, so they are preserved literally. Credential contents never appeared in stdout.

### Exact isolated homes and live-store non-mutation [A]

- Codex app-server home: `/tmp/r174-final.jYS3rD/codex-home`
- Explicit path fixture: `/tmp/r174-final.jYS3rD/fixtures/forged.jsonl`
- Claude auth source used by the SDK materializer: `/tmp/r174-final.jYS3rD/claude-auth`
- SDK-created resume home: `/tmp/claude-resume-7n3z36qu`
- SDK-created JSONL: `/tmp/claude-resume-7n3z36qu/projects/-home-kesha-orchestra-worktrees-home-kesha-orchestra-r174-transcripts/bbbbbbbb-cccc-4ddd-8eee-ffffffffffff.jsonl`

After all three acceptance turns, the exact verification output was:

```text
live_codex_import_matches=0
live_claude_import_matches=0
live_grok_user_home_exists=1
live_grok_managed_home_exists=1
isolated_codex_home=0
isolated_claude_auth_home=0
```

Here `test` exit `1` means absent and `0` means present. The two live-import counts searched `~/.codex/sessions` for the returned history thread ID / forged path ID and `~/.claude/projects` for the SessionStore ID. Both were zero. The isolated homes existed. Grok homes remained absent. Therefore the probes did not create or append a target transcript in any live store.

### SDK 0.2.114: exact minimal `SessionStoreEntry` and result [A]

The custom store returned exactly this one-element list; this is the complete entry, not a schema sketch:

```json
{"parentUuid":null,"isSidechain":false,"userType":"external","cwd":"/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts","sessionId":"bbbbbbbb-cccc-4ddd-8eee-ffffffffffff","version":"2.1.197","gitBranch":"task-174/r174-transcripts","type":"user","message":{"role":"user","content":"The SessionStore portability marker is R174_SESSION_STORE_LITERAL."},"uuid":"dddddddd-eeee-4fff-8000-111111111111","timestamp":"2026-08-11T08:15:00.000Z"}
```

Exact output from `ClaudeSDKClient.connect()` → `query()` → consume through `ResultMessage` → `disconnect()`:

```text
ENTRY_JSON {"parentUuid":null,"isSidechain":false,"userType":"external","cwd":"/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts","sessionId":"bbbbbbbb-cccc-4ddd-8eee-ffffffffffff","version":"2.1.197","gitBranch":"task-174/r174-transcripts","type":"user","message":{"role":"user","content":"The SessionStore portability marker is R174_SESSION_STORE_LITERAL."},"uuid":"dddddddd-eeee-4fff-8000-111111111111","timestamp":"2026-08-11T08:15:00.000Z"}
MATERIALIZED_HOME /tmp/claude-resume-7n3z36qu
MATERIALIZED_JSONL /tmp/claude-resume-7n3z36qu/projects/-home-kesha-orchestra-worktrees-home-kesha-orchestra-r174-transcripts/bbbbbbbb-cccc-4ddd-8eee-ffffffffffff.jsonl
SEMANTIC_RECALL True AGENT_TEXT ["R174_SESSION_STORE_LITERAL"]
LOAD_CALLS 1 RESULT_SESSION_ID_MATCH True
MATERIALIZED_EXISTS_AFTER_DISCONNECT False
```

There was no SDK/CLI error: the exact minimal one-row entry was accepted and recalled. `MATERIALIZED_EXISTS_AFTER_DISCONNECT False` confirms the SDK removed its injected temp home after the result.

### Codex 0.146.0: literal `thread/resume.history` request/response [A]

The process was exactly `CODEX_HOME=/tmp/r174-final.jYS3rD/codex-home codex app-server --stdio --disable apps`. Initialization opted into the required capability:

```json
{"method":"initialize","id":1,"params":{"clientInfo":{"name":"r174-literal-history","version":"1"},"capabilities":{"experimentalApi":true}}}
```

Literal history request:

```json
{"method":"thread/resume","id":2,"params":{"threadId":"77777777-8888-4999-8aaa-bbbbbbbbbbbb","history":[{"type":"message","role":"user","content":[{"type":"input_text","text":"The history portability marker is R174_HISTORY_LITERAL."}]},{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Marker stored."}]}],"cwd":"/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts","model":"gpt-5.6-sol","approvalPolicy":"never","sandbox":"danger-full-access"}}
```

Literal response:

```json
{"id":2,"result":{"thread":{"id":"019fefc6-1a9c-7c90-bab8-6e957feed641","extra":null,"sessionId":"019fefc6-1a9c-7c90-bab8-6e957feed641","forkedFromId":null,"parentThreadId":null,"preview":"The history portability marker is R174_HISTORY_LITERAL.","ephemeral":false,"isPinned":false,"historyMode":"legacy","modelProvider":"openai","createdAt":1786434165,"updatedAt":1786434165,"recencyAt":1786434165,"status":{"type":"idle"},"path":"/tmp/r174-final.jYS3rD/codex-home/sessions/2026/08/11/rollout-2026-08-11T09-42-45-019fefc6-1a9c-7c90-bab8-6e957feed641.jsonl","cwd":"/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts","cliVersion":"0.146.0","source":"vscode","canAcceptDirectInput":true,"threadSource":null,"agentNickname":null,"agentRole":null,"gitInfo":null,"name":null,"turns":[]},"model":"gpt-5.6-sol","modelProvider":"openai","serviceTier":null,"cwd":"/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts","runtimeWorkspaceRoots":["/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts"],"instructionSources":["/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts/AGENTS.md"],"approvalPolicy":"never","approvalsReviewer":"user","sandbox":{"type":"dangerFullAccess"},"activePermissionProfile":null,"reasoningEffort":null,"multiAgentMode":"explicitRequestOnly","initialTurnsPage":null,"turnsBackwardsCursor":null,"itemsBackwardsCursor":null}}
```

The literal next-turn request and semantic result were:

```json
{"method":"turn/start","id":3,"params":{"threadId":"019fefc6-1a9c-7c90-bab8-6e957feed641","input":[{"type":"text","text":"What is the history portability marker from the prior conversation? Reply with only the marker."}],"model":"gpt-5.6-sol","effort":"low"}}
```

```text
SEMANTIC_RECALL True AGENT_COMPLETED_TEXT ["R174_HISTORY_LITERAL"]
```

The response proves that `history` took precedence: the requested `7777…` ID was ignored, a new `019f…` thread was created under the isolated home, and its `preview` contains the injected user item.

### Codex 0.146.0: literal `thread/resume.path` request/response [A]

The path fixture was exactly the two-line forged rollout documented above, with session ID `22222222-3333-4444-8555-666666666666` and marker `R174_PATH_LITERAL`.

Literal request:

```json
{"method":"thread/resume","id":2,"params":{"threadId":"88888888-9999-4aaa-8bbb-cccccccccccc","path":"/tmp/r174-final.jYS3rD/fixtures/forged.jsonl","cwd":"/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts","model":"gpt-5.6-sol","approvalPolicy":"never","sandbox":"danger-full-access"}}
```

Literal response:

```json
{"id":2,"result":{"thread":{"id":"22222222-3333-4444-8555-666666666666","extra":null,"sessionId":"22222222-3333-4444-8555-666666666666","forkedFromId":null,"parentThreadId":null,"preview":"","ephemeral":false,"isPinned":false,"historyMode":"legacy","modelProvider":"openai","createdAt":1786435800,"updatedAt":1786434142,"recencyAt":1786434142,"status":{"type":"idle"},"path":"/tmp/r174-final.jYS3rD/fixtures/forged.jsonl","cwd":"/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts","cliVersion":"0.146.0","source":"exec","canAcceptDirectInput":true,"threadSource":null,"agentNickname":null,"agentRole":null,"gitInfo":null,"name":null,"turns":[]},"model":"gpt-5.6-sol","modelProvider":"openai","serviceTier":null,"cwd":"/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts","runtimeWorkspaceRoots":["/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts"],"instructionSources":["/home/kesha/orchestra/worktrees/home-kesha-orchestra/r174-transcripts/AGENTS.md"],"approvalPolicy":"never","approvalsReviewer":"user","sandbox":{"type":"dangerFullAccess"},"activePermissionProfile":null,"reasoningEffort":null,"multiAgentMode":"explicitRequestOnly","initialTurnsPage":null,"turnsBackwardsCursor":null,"itemsBackwardsCursor":null}}
```

Literal next-turn request and semantic result:

```json
{"method":"turn/start","id":3,"params":{"threadId":"22222222-3333-4444-8555-666666666666","input":[{"type":"text","text":"What is the path portability marker from the prior conversation? Reply with only the marker."}],"model":"gpt-5.6-sol","effort":"low"}}
```

```text
SEMANTIC_RECALL True AGENT_COMPLETED_TEXT ["R174_PATH_LITERAL"]
```

The response proves that `path` took precedence over the requested `8888…` ID and that app-server used the ID embedded in the forged rollout.

## Counter-evidence and limits

- Successful marker recall proves text history reached the next model call; it does not prove tool-call state, images, reasoning, compaction summaries, subagents, or long histories are portable.
- Claude accepted a one-row user history, but the SDK explicitly refuses to define that row union publicly.
- Codex accepted a deliberately complete minimal `session_meta`; the experiment did not isolate every required field.
- Codex exact-copy control tolerated a dangling tool call, but that does not establish arbitrary corrupt rollout tolerance.
- App-server history/path were generated and tested from the installed binary itself, but both are opt-in experimental APIs and can change independently of the CLI's disk format.
- No Grok claim in this report is based on a current executable or current on-disk session sample.
