# Research #98 — Grok runtime incident and multi-runtime audit

Date: 2026-07-28.

Scope: investigation only. No production code, live database writes, service
restarts, or external messages were performed. SQLite was opened with
`mode=ro`. Secret values are redacted; only environment variable names are
preserved.

## Verdict

1. **Grok workers are not production-usable yet: Orchestra MCP was absent from
   the started roster.** The historical `grok-test` session reported an empty
   MCP roster and zero MCP tools. Reconstructing current code with its
   persisted session fields produces an explicit `orchestra` record, while
   `grok inspect` reports the worktree as `projectTrusted=false` and discovers
   a second, same-name repository record. The available artifacts do not
   distinguish whether trust filtering, same-name precedence, or both removed
   the generated record before startup. `_verify_mcp_isolation()` then accepted
   `expected={"orchestra"}, started={}` because it checks only unexpected
   servers, not missing required servers. The observed `tasks` catalog is
   Grok's built-in scheduler surface, not the repository MCP server.
2. **The worker did not demonstrate a 500,000-token occupied context.** Its
   last model call had a prompt of **84,482 tokens (16.9% of the advertised
   window)**; the post-turn occupied context was not exposed separately.
   Orchestra stored the turn-wide aggregate `totalTokens=1,678,471` as current
   context, clamped it to 100%, and triggered three unnecessary compaction
   attempts. Those
   attempts added **262,236 input tokens, 6,446 output tokens, and $0.1270776**
   while producing three `empty summary` errors.
3. **Three active runtime adapters are normal; the fourth must not be a
   catch-all.**
   Claude, Codex, and Grok speak materially different lifecycle/event
   protocols. Exact repeated blocks are small except for the expected
   Codex↔Grok JSON-RPC transport: 181 lines, 14.8% of Codex and 21.3% of Grok
   nonblank lines. Do not force their event adapters into a base class.
   The local deployment has zero OpenCode sessions, turns, usage rows,
   registered models, plugin configuration, or running daemon, but the proxy
   model loader makes unconditional global deletion unproven. Inventory every
   deployment and migrate proxy models to an explicit runtime first; only then
   remove the unknown-model fallback and conditionally delete the adapter.
   Independently, unify three contracts: exhaustive model/runtime/provider
   validation, normalized turn usage/context, and identity-aware required MCP
   launch/conformance.

## Question and falsifiers

### Context

The first real Grok worker completed a small repository change but could not
call Orchestra MCP. Its dashboard then showed 100% of a 500K context window.
The repository now carries four `BackendLike` implementations: Claude, Codex,
Grok, and OpenCode.

### Hypotheses

#### H1 — the committed `.mcp.json` replaced or collided with Orchestra's MCP

Falsifier: capture the historical `session/new` wire payload; run a trusted/
untrusted × repository-file-present/absent matrix with distinguishable server
names; then run a separate same-name collision with distinguishable commands
and identities.

**Result: UNCERTAIN.** Current-code reconstruction includes Orchestra's
generated record before ACP translation, while Grok discovers a same-name
repository record and starts neither. There is no historical wire capture and
no controlled collision matrix, so replacement/precedence and trust cannot yet
be separated.

#### H2 — the isolation guard guarantees both purity and availability

Falsifier: supply an expected server, receive `mcpToolCount=0`, and see the
connection remain successful.

**Result: REFUTED.** Reproduced with current code and Grok 0.2.112:
`expected=["orchestra"]`, `started=[]`, `connected=true`.

#### H3 — one small task genuinely filled the 500K context window

Falsifier: inspect per-model-call prompt sizes and find that the last observed
prompt was materially below 500K.

**Result: REFUTED as a claim about measured utilization.** The last-call
prompt was 84,482 tokens. The 1.67M value is the sum of input over 25 calls;
post-turn occupied context was not separately reported.

#### H4 — most backend code is the same transport copied four times

Falsifier: exact clone analysis finds little common code outside the
Codex↔Grok JSON-RPC pair, while event mapping remains provider-specific.

**Result: REFUTED.** Claude and OpenCode each share under 3% exact block lines
with other backends. Event adapters alone occupy 247–547 lines per runtime.

#### H5 — OpenCode is active in this local deployment

Falsifier: the live DB or process table contains an OpenCode session, turn,
usage row, registered model, or running daemon.

**Result: REFUTED locally.** All five measurements are zero. This does not
prove that another deployment or dynamically loaded proxy model does not
select the adapter.

## 1. MCP incident

### 1.1 What Orchestra composed

The session row is:

```text
id                  2836896d-e1c0-4c0d-acc6-f7f4462a65eb
name                grok-test
scope               /mnt/data/Projects/Python/orchestra
cwd                 .../worktrees/mnt-data-projects-python-orchestra/grok-test
role                worker
parent_name         Orchestra-orchestrator
pipeline            default
model/runtime       grok-4.5 / grok
mcp_servers_custom  ""
```

`SessionManager` always creates the generated `orchestra` config in
`_make_mcp_config()` [S1]. `_grok_factory()` starts from that config and then
loads scope/user extras [S2]. The loader reads
`/mnt/data/Projects/Python/orchestra/.mcp.json` because `scope` is the
repository root, but explicitly discards the key `orchestra`. Therefore the
committed test record does not overwrite the generated record inside
Orchestra's composition.

Reconstructing current production code with the persisted session fields
yields this sanitized `mcpServers` request shape:

```json
{
  "cwd": "/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-test",
  "mcpServers": [
    {
      "name": "orchestra",
      "type": "stdio",
      "command": "/usr/bin/python",
      "args": [
        "/mnt/data/Projects/Python/orchestra/app/mcp_stdio.py"
      ],
      "env": [
        {"name": "PYTHONPATH", "value": "/mnt/data/Projects/Python/orchestra"},
        {"name": "HTTPS_PROXY", "value": "<redacted>"},
        {"name": "HTTP_PROXY", "value": "<redacted>"},
        {"name": "NO_PROXY", "value": "localhost,127.0.0.1"},
        {"name": "ORCHESTRA_URL", "value": "http://127.0.0.1:8888"},
        {"name": "ORCHESTRA_SCOPE", "value": "/mnt/data/Projects/Python/orchestra"},
        {"name": "ORCHESTRA_ROLE", "value": "worker"},
        {"name": "ORCHESTRA_ACCESS_MODE", "value": "full"},
        {"name": "WORKER_NAME", "value": "grok-test"},
        {"name": "PARENT_NAME", "value": "Orchestra-orchestrator"}
      ]
    }
  ]
}
```

The current live Orchestra process does not expose an `INTERNAL_TOKEN`
environment key, so current reconstruction omits it. That is not a historical
wire fact: the incident may have used `session/load`, and the process
environment at 12:08 was not archived. If absent, later Orchestra HTTP calls
would be unauthenticated, but stdio tool registration/listing happens before a
tool invokes that callback and therefore does not explain an empty started
roster.

The translation to ACP happens at `backend_grok.py:891-914`; `connect()` sends
the result at `backend_grok.py:288-313` [S3].

**Confidence: CONFIRMED** for current composition code and the deterministic
reconstruction using persisted DB fields; **UNCERTAIN** for the exact
historical `session/new`/`session/load` payload because no raw request was
captured.

### 1.2 What Grok discovered and what it started

The managed home currently contains:

```toml
# Generated by Orchestra — do not edit.
# Managed workers get exactly the MCP servers Orchestra passes in session/new.
[compat.claude]
mcps = false

[compat.cursor]
mcps = false
```

`grok inspect --json`, run in the preserved `grok-test` worktree with that
managed home, returned this sanitized subset:

```json
{
  "cwd": ".../worktrees/mnt-data-projects-python-orchestra/grok-test",
  "projectTrusted": false,
  "externalCompat": {
    "claude.mcps": {"enabled": false, "source": "config"},
    "cursor.mcps": {"enabled": false, "source": "config"}
  },
  "mcpServers": [
    {
      "name": "websearch",
      "source": {"type": "claudeJson", "path": "~/.claude.json"}
    },
    {
      "name": "mcp-pandoc",
      "source": {"type": "claudeJson", "path": "~/.claude.json"}
    },
    {
      "name": "orchestra",
      "source": {
        "type": "mcpJson",
        "path": ".../grok-test/.mcp.json"
      }
    }
  ]
}
```

This list is discovery, not the started roster. The real startup event stored
by Orchestra was:

```text
2026-07-28T12:08:20.110731Z  status  grok mcp ready · 0 tools
```

A clean reproduction using current `GrokBackend`, the same generated
`orchestra` config, a temporary managed `GROK_HOME`, and the current worktree
produced:

```text
connected=true
expected=['orchestra']
started=[]
events=[
  {
    method:'_x.ai/mcp/servers_updated',
    serverNames:[]
  },
  {
    method:'_x.ai/mcp_initialized',
    mcpToolCount:0
  }
]
```

With Claude compatibility enabled, the same probe started only the two global
Claude servers:

```text
expected=['orchestra']
started=['mcp-pandoc', 'websearch']
mcpToolCount=3
result=GrokMcpIsolationError
```

It still did not start the explicit or repository `orchestra` record. Binary
0.2.112 contains the diagnostic:

```text
repo-local (project-scoped) server not started for an untrusted folder
re-run with --trust to allow repo-local servers
```

The repository has no project-level trust entry in the managed Grok home.
`grok agent --help` also documents `--plugin-dir` as “always trusted” for MCP
servers injected by SDKs.

The missing falsifier is a trust-enabled end-to-end run. It was attempted
after the cached OAuth credential had expired and stopped at:

```text
GrokProtocolError
{"code":-32000,"message":"Authentication required"}
```

This does not weaken the measured facts—real worktree untrusted and started
roster empty—but it leaves two viable explanations: trust filtering and
same-name collision/precedence between the generated and discovered
`orchestra` records. The activation path (`trusted_folders.toml` versus an
always-trusted plugin) and collision behavior must be tested after login
before implementation.

**Confidence: CONFIRMED** that the worktree was untrusted and no Orchestra
server started. **UNCERTAIN** about why the explicit ACP record did not start:
the binary diagnostic supports the trust hypothesis, but the positive
transition and a distinguishable same-name collision test were both missing.

### 1.3 Why the old T2 verification missed it

The original successful MCP probe did not represent a worker:

```text
old F4 probe cwd paths: /tmp/grok-acp-test, /tmp/grok_acp_mcp_tool.py
old T2 probes:          /tmp/grok-iso-clean, /tmp/grok-iso-dirty
real worker cwd:        .../worktrees/.../grok-test
```

The temporary probe directory was not a Git worktree and therefore did not
exercise the repo trust gate. Unit tests manually populate
`_started_servers`; none launches an untrusted Git worktree and requires the
generated Orchestra server to become ready.

The production guard then performs only:

```python
unexpected = started_servers - expected_servers
if unexpected:
    raise GrokMcpIsolationError(...)
```

For the incident:

```text
expected = {"orchestra"}
started  = {}
unexpected = {}
missing    = {"orchestra"}  # never calculated
```

`_x.ai/mcp_initialized` sets the ready event regardless of
`mcpToolCount=0` [S3]. Thus the check did run; it passed the wrong predicate.
It guarantees “no extra server” but not “all required servers started.”

**Confidence: CONFIRMED.** Reproduced against the exact guard.

### 1.4 `tasks` did not come from `.mcp.json`

The raw Grok tool-catalog responses were:

```text
search_tool {"query":"orchestra send_message","limit":10}
→ {"results":[],"total_hidden_tools":6,"status":"ready","note":null}

search_tool {"query":"send_message list_agents","limit":20}
→ {
    "results":[{
      "server":"tasks",
      "tools":[{
        "tool_name":"tasks__list",
        "description":"List the user's active scheduled tasks ..."
      }]
    }],
    "total_hidden_tools":6,
    "status":"ready"
  }

use_tool {"tool_name":"orchestra__send_message", ...}
→ Tool `orchestra__send_message` failed via `use_tool`:
  Tool not found: orchestra__send_message
```

Grok's bundled scheduler implements `scheduler_create`, `scheduler_list`, and
`scheduler_delete`; its user guide describes the same scheduled-task surface
and `/tasks` pane [S4]. The binary contains the scheduler implementation and
tool descriptions. It is part of Grok's built-in/deferred tool catalog and is
not included in the `_x.ai/mcp/servers_updated` roster.

The worker's statement that it “saw `orchestra`” was an inference from reading
the physical `.mcp.json`, not a tool-catalog observation.

**Confidence: CONFIRMED.** Raw search/use responses plus the bundled primary
implementation/docs.

### 1.5 Proposal for the MCP topic

Phase 2 should not choose a transport until a renewed-auth experiment closes
both trust and name-collision questions. Run two experiments:

1. a 2×2 matrix (trusted/untrusted × repository `.mcp.json` present/absent)
   with different server names and distinguishable commands, isolating trust
   and autodiscovery;
2. a same-name collision case in which generated and repository servers are
   both named `orchestra` but run distinguishable commands and expose
   verifiable identities, isolating precedence/substitution.

The acceptance gate is end-to-end, not a roster fixture:

1. real Git worktree;
2. managed Grok home;
3. exactly the generated `orchestra` server starts;
4. `mcpToolCount > 0`;
5. `search_tool` finds `orchestra__list_agents`;
6. `use_tool` successfully calls it;
7. a committed foreign `.mcp.json` remains inactive.

Two candidates must be tested:

- persist the real worktree as trusted inside Orchestra's isolated Grok home;
- inject a per-process MCP plugin via `--plugin-dir`, which Grok describes as
  always trusted.

Whichever is chosen, name-only set comparison is insufficient: a foreign
same-name repository server could otherwise satisfy availability. The launch
plan must either suppress repository autodiscovery or bind every required
server to a verifiable identity (source/config fingerprint or an
Orchestra-specific handshake canary), then compare both set differences:

```text
unexpected = started - allowed
missing    = required - started
```

`mcpToolCount=0` with a required server must fail connection. A physical
`.mcp.json` or a matching server name must never count as availability
evidence.

## 2. Context and token economics

### 2.1 The raw turn usage is cumulative across model calls

The first task produced this exact `turn_completed.usage`:

```json
{
  "inputTokens": 1665949,
  "outputTokens": 12522,
  "cachedReadTokens": 1581056,
  "reasoningTokens": 9886,
  "totalTokens": 1678471,
  "modelCalls": 25,
  "costUsdTicks": 7192348000
}
```

The 25 exact `prompt_tokens` values from the unified inference log were:

```text
38,710  39,825  42,119  45,084  48,806
53,140  55,894  59,230  62,110  65,761
67,592  69,056  69,606  70,092  72,013
73,149  78,200  79,859  80,368  80,773
80,997  81,943  83,171  83,969  84,482
```

Their sum is exactly **1,665,949**, the reported `inputTokens`. Therefore:

```text
aggregate input over 25 calls  = 1,665,949
last-call prompt tokens        =    84,482
last prompt / 500K window      =     16.9%
```

`backend_grok._turn_end_event()` instead sets current context from
`usage.totalTokens` [S3]:

```python
context_tokens = totals["totalTokens"]  # 1,678,471
context_pct = min(100, context_tokens * 100 / 500_000)
```

That is the root cause of the false 100%. The last-call prompt is direct
evidence against the displayed 100%, but it is not automatically identical to
post-turn occupied context; Grok did not expose the latter as a separate
field.

**Confidence: CONFIRMED.** Exact sum of all 25 model-call prompts equals the
turn usage field.

### 2.2 Initial prompt composition

Grok does not expose per-section token counts. The section allocation below
uses `cl100k_base` counts scaled to Grok's exact first-message prompt. Only
the 38,710 total is exact; both partitions and individual rows are calibrated
estimates rounded to the nearest token.

```text
Exact first prompt                                38,710
  estimated conversation/context subtotal         32,047
  estimated residual tool-schema catalog           6,663
```

Estimated composition of the 32,047 context subtotal:

| Initial component | Characters | Estimated tokens |
|---|---:|---:|
| Native Grok system prefix | 4,144 | 810 |
| Orchestra role/platform system prompt | 16,471 | 3,800 |
| Runtime/git user-info injection | 478 | 116 |
| Project/global instruction bundle | 57,599 | 22,061 |
| Skills index/system reminder | 16,244 | 4,384 |
| Actual task prompt | 2,173 | 876 |
| **Subtotal** | **97,109** | **32,047** |

The instruction bundle contains:

| Instruction source | Relationship | Estimated tokens |
|---|---|---:|
| Global `~/.claude/CLAUDE.md` | distinct | 6,431 |
| Project `CLAUDE.md` | hash `a4673e...` | 7,741 |
| Project `AGENTS.md` | byte-identical to project `CLAUDE.md` | 7,741 |
| Wrappers/labels | — | 148 |

The duplicated project file therefore occupies approximately **7,741 initial
prompt tokens before the task begins**. The Orchestra platform role itself is
only about 3,800 tokens; it is not the dominant initial cost.

The character subtotal is intentionally not summed in the table because
wrapper/serialization characters are counted at the message boundary, while
the displayed component lengths are raw content lengths.

**Confidence: CONFIRMED** for byte identity, character sizes, and aggregate
prompt tokens; **LIKELY** for per-component token allocation because Grok's
tokenizer is not exposed.

### 2.3 What grew the per-call prompt during the task

The per-call prompt grew by exactly:

```text
84,482 - 38,710 = 45,772 tokens
```

Stored chat content was counted with `cl100k_base` and proportionally scaled
to that exact delta:

| Incremental category | Estimated retained prompt tokens | Share |
|---|---:|---:|
| Tool results | 35,621 | 77.8% |
| Tool-call arguments | 8,259 | 18.0% |
| Retained reasoning summaries | 1,637 | 3.6% |
| Assistant prose | 183 | 0.4% |
| One synthetic system reminder | 72 | 0.2% |
| **Exact calibrated total** | **45,772** | **100%** |

Tool-result decomposition:

| Tool | Calls/results | Result chars | Estimated retained prompt tokens |
|---|---:|---:|---:|
| `read_file` | 13 | 45,174 | 15,484 |
| `grep` | 16 | 36,850 | 11,513 |
| `run_terminal_command` | 20 | 25,131 | 8,088 |
| `search_tool` | 4 | 1,003 | 313 |
| edits/write/use_tool | 6 | 795 | 223 |

Read/search outputs alone account for approximately **32,540 retained prompt
tokens**:
`read_file` + `grep` + terminal discovery commands. This is the concrete main
consumer after the duplicated initial instructions.

This was not caused by reading whole files blindly. All 13 `read_file` calls
specified offsets and limits (20–180 lines). The largest single result was
2,817 estimated tokens; the largest grep result was 2,172; the largest
terminal result was 1,264. No stored result carried a truncation marker.
Instead, the model made **59 tool calls**, including 29 direct
`read_file`/`grep` calls and several overlapping shell searches.

Platform injections were not appended again on each model call. The task has
one initial instruction/skills injection and only one later 277-character
synthetic reminder. The large aggregate input comes from replaying the
growing conversation on every model call; **94.9%** of it was cache-read.

**Confidence: CONFIRMED** for calls, chars, exact total delta, and cache ratio;
**LIKELY** for category token allocation because it is calibrated from a
different tokenizer.

### 2.4 False compaction cost

The bad context field produced:

```text
12:11:55  turn ended ... ctx:100%
12:11:55  auto-compact triggered (100%)
12:11:57  compact started
12:12:29  compact attempt 1/3: empty summary
12:13:33  compact attempt 2/3: empty summary
12:14:54  compact attempt 3/3: empty summary
```

Raw usage for those three extra calls:

| Attempt | Input | Cached | Output | Cost |
|---|---:|---:|---:|---:|
| 1 | 84,802 | 84,480 | 2,333 | $0.0399860 |
| 2 | 87,419 | 84,736 | 2,375 | $0.0450368 |
| 3 | 90,015 | 87,296 | 1,738 | $0.0420548 |
| **Total waste** | **262,236** | **256,512** | **6,446** | **$0.1270776** |

No summary was applied, so the retries only inflated stored session totals.

**Confidence: CONFIRMED.** Raw `turn_completed` payloads and DB status/error
sequence.

### 2.5 Comparison with Sol

The nearest small real Sol task found in the DB is `fix-preview-sandbox`:
three files, +56/-3. The Grok task touched four files, +89/-2. This is an
observational comparison, not a controlled A/B.

| Metric | Grok `grok-test` | Sol `fix-preview-sandbox` | Grok/Sol |
|---|---:|---:|---:|
| Changed lines | 91 | 59 | 1.54× |
| Tool calls | 59 | 16 | 3.69× |
| Aggregate input | 1,665,949 | 955,711 | 1.74× |
| Output | 12,522 | 5,893 | 2.12× |
| Cache-read share | 94.9% | 92.3% | — |
| Recorded cost | $0.7192 | $0.9844 | 0.73× |
| Input per changed line | 18,307 | 16,198 | 1.13× |
| Tool calls per changed line | 0.65 | 0.27 | 2.39× |

Grok's 84,482 last-call prompt and Sol's 61,940 stored context metric are not
listed as a ratio because their semantics are not proven comparable.

A second, larger Sol task (`fix-tg-topic-lock`, +175/-41) used 37 tools,
1.829M aggregate input, and a stored context metric of 89,231. That
counterexample shows that million-token aggregate input is normal for
iterative cached agent loops; it is not evidence of a filled context window.

**Finding:** Grok was more tool-chatty on this task, but not economically
disqualified: it used 13% more aggregate input per changed line and cost less
under the recorded runtime rates. The decisive bug is false context
accounting/compaction, not an intrinsic 500K burn.

**Confidence: LIKELY.** Direct real measurements, but tasks differ.

### 2.6 Proposal for the context topic

The shared turn contract must distinguish:

```text
turn_input_tokens      cumulative billed input across model calls
current_context_tokens occupied prompt/window on the final call
context_known         whether the backend proved that field's semantics
model_calls            number of calls contributing to turn_input_tokens
```

Backends should not hand-write a loose metadata dict and reuse an ambiguous
`totalTokens`. A normalized constructor/validator should require field
semantics. An impossible value (`current > max`) must be fail-soft for the
turn: persist billed usage and cost, mark context unknown, emit a visible
diagnostic, and suppress context-driven compaction. It must not throw away the
`turn_end` or silently clamp the value to 100%.

For Grok, `turn_completed.usage.totalTokens` cannot be the current-context
source. Before implementation, verify whether `inference_done.prompt_tokens`
is exposed through ACP and whether it represents retained context or only the
serialized prompt; otherwise the current context must remain unknown rather
than being inferred from an aggregate.

Independently, Grok startup should inject one of project `CLAUDE.md` or
`AGENTS.md`, not both when their bytes are identical.

## 3. Multi-runtime architecture audit

### 3.1 Size and exact duplication

Current production files:

| File | Physical LOC | Backend class LOC | Methods |
|---|---:|---:|---:|
| `backend_claude.py` | 591 | 501 | 17 |
| `backend_codex.py` | 1,331 | 1,148 | 32 |
| `backend_grok.py` | 959 | 788 | 32 |
| `backend_opencode.py` | 632 | 526 | 24 |
| `runtime_registry.py` | 337 | — | — |
| `backend_protocol.py` | 16 | — | — |

Exact clone measurement normalized whitespace and counted consecutive matching
blocks of at least three physical code lines. Comments/blank lines were
excluded from matching:

| Pair | Exact blocks | Exact block lines |
|---|---:|---:|
| Claude ↔ Codex | 2 | 8 |
| Claude ↔ Grok | 3 | 9 |
| Claude ↔ OpenCode | 3 | 10 |
| Codex ↔ Grok | 38 | 181 |
| Codex ↔ OpenCode | 1 | 4 |
| Grok ↔ OpenCode | 2 | 7 |

Union of exact cloned lines per backend:

| Backend | Cloned lines / nonblank lines | Share |
|---|---:|---:|
| Claude | 15 / 544 | 2.8% |
| Codex | 183 / 1,233 | 14.8% |
| Grok | 184 / 864 | 21.3% |
| OpenCode | 11 / 574 | 1.9% |

Codex↔Grok clone lines are concentrated in JSON-RPC/process plumbing:

```text
_read_stdout       33
__init__           25
connect            23
disconnect         19
events             15
module helpers     11
conversion bridge  11
_request            9
_drain_stderr       9
error classify      7
other              10
```

Only four two-line methods are AST-identical across pairs (`session_id` and
`is_alive` properties). Even shared lifecycle method names have substantially
different bodies: pairwise token similarity for `connect()` peaks at 0.568
for Codex↔Grok and is 0.149–0.253 for most other pairs.

**Confidence: CONFIRMED.** Deterministic analysis over current source.

### 3.2 Provider-specific code is the majority that matters

Measured event/lifecycle translation buckets:

| Backend | Event/turn mapping LOC |
|---|---:|
| Claude | 247 |
| Codex | 547 |
| Grok | 263 |
| OpenCode | 255 |

Their vocabularies and completion semantics differ:

- Claude SDK yields typed messages and persistent mid-turn input.
- Codex app-server yields `item/*`, `turn/*`, collaboration events, and
  cumulative thread accounting.
- Grok ACP yields `session/update`, xAI MCP notifications, permission
  reverse-requests, queued turns, and per-turn aggregate usage.
- OpenCode uses HTTP + SSE + polling and owns a daemon lifecycle.

`BackendLike` correctly stays tiny: six lifecycle methods plus `session_id`
[S5]. The mistake is not lack of a large base class. It is that the normalized
`AgentEvent("turn_end", metadata=dict)` contract has no typed semantics or
validation.

**Decision:** keep Claude, Codex, and Grok protocol/event adapters separate.
Do not abstract the 181 Codex↔Grok transport lines yet; a shared transport
base would save less code than the provider-specific event mappings and would
couple two protocols that already differ in steering, completion, usage, and
MCP behavior.

### 3.3 Where runtime exhaustiveness is still duplicated

Adding Grok across T1–T6 touched six production surfaces:

```text
app/backend_grok.py
app/models.py
app/runtime_registry.py
app/static/css/style.css
app/static/js/analytics.js
app/usage_analytics.py
```

The current tree is better than the old hand-written ternaries, but runtime
knowledge remains split:

1. **Model/runtime selection:** `models.py` infers runtime; unknown models fall
   to OpenCode. `runtime_registry.py` separately registers runtime
   capabilities/factories.
2. **Accounting bucket/cache policy:** `usage_analytics.py` has
   `_PROVIDER_RULES=(grok,codex)` plus `ELSE claude`. OpenCode would therefore
   be charged to the Claude bucket even though its provider may be DeepSeek,
   Mistral, OpenRouter, etc.
3. **UI capacity/display metadata:** `static/js/utils.js::_PROVIDER_META`
   knows only Claude, Codex, and Grok. `usage.js` still has separate render
   blocks for those three.
4. **Weak turn contract:** all four backends independently construct
   `turn_end.metadata`, including `context_tokens`, cache fields, cost, and
   error flags.
5. **MCP composition/conformance:** manager builds the default, registry
   merges scope/user config, and each backend translates/starts/verifies it.
   The current contract cannot express `required` versus `allowed`.

Legacy `"claude"` defaults in DB/session restoration are compatibility
defaults and should remain explicit. The dangerous pattern is using Claude as
the exhaustive fallback for a runtime/provider that exists but was omitted.

### 3.4 Shared-contract blast radius is already measured

The Grok merge made factories call `get_role(pipeline, role)`. Legacy sessions
could have `pipeline=""`; `load_pipeline("")` raised `ValueError`, while the
factory caught only `FileNotFoundError`. The result was failed `send` for 34
live sessions [M5].

Current live read-only DB shape remains hostile to fixture-only assumptions:

```text
sessions total         337
pipeline empty          27
profile empty          323
base_branch empty      324
cwd missing on disk    247
```

This proves the right architectural boundary: centralize input contracts and
compatibility validation, not provider event machinery. A new runtime must be
tested against real persisted field combinations before registration.

### 3.5 OpenCode is dormant locally and dangerous as a catch-all

Live measurements:

```text
sessions.backend_type='opencode'       0
logs for OpenCode sessions             0
turn_usage.runtime='opencode'          0
registered ModelSpec runtime=opencode  0 of 12
running `opencode` processes           0
installed binary                       1.17.6
ORCHESTRA_RUNTIME_PLUGINS configured   no
```

Code carried solely for that path:

```text
app/backend_opencode.py          632 lines
tests/test_backend_opencode.py   723 lines
tests/test_backend_routing.py    198 lines
total dedicated/near-dedicated  1,553 lines
```

OpenCode is locally dormant, but `_infer_backend()` routes every unknown
non-`gpt-*`, non-`claude-*`, non-`grok-*` model to it [S6], while analytics
and UI have no OpenCode bucket/card. A newly discovered proxy model could
therefore activate an unexercised daemon and land its cost in Claude through
the fallback.

The current code also fetches dynamic proxy models and can assign inference
models to OpenCode, including aliases for Gemini, Llama, and Mistral [S7].
Thus zero local rows and processes do not prove that no other deployment or
future proxy response relies on the adapter.

**Decision:** first inventory every deployment, current proxy model response,
and runtime plugin configuration. Migrate every model that currently depends
on inference to an explicit runtime. Only after that migration may backend
selection fail loud for an unregistered model and the unknown-model catch-all
be removed. On this local deployment, mark OpenCode dormant/unsupported. If
the inventory finds no explicit OpenCode model, delete the adapter; otherwise
retain it only behind explicit `ModelSpec` entries.

Counter-evidence: OpenCode is the existing path to arbitrary provider/model
IDs, and dynamic proxy loading makes that a product path rather than a purely
hypothetical one. The local deployment does not exercise it, but this audit
cannot inspect every external deployment; unconditional deletion is therefore
not supported yet.

### 3.6 Concrete architecture decision

Keep the three active provider adapters separate. Inventory and explicitly
migrate inferred proxy models before disabling OpenCode's implicit selection;
make later adapter deletion conditional on that inventory. Unify exactly these
three places:

1. **Exhaustive model/runtime/provider validation**
   - preserve `ModelSpec(model → runtime, provider, context)` separately from
     `RuntimeDefinition(runtime → harness, capabilities)`; OpenCode itself
     proves that runtime and provider are not one-to-one;
   - maintain quota/accounting/display metadata as an explicit provider
     mapping rather than folding it into either runtime record;
   - backend selection fails on an unknown model instead of falling through;
   - startup validates that every model's runtime and provider mappings exist,
     and frontend/provider metadata is generated or checked exhaustively.
2. **Normalized turn-usage contract**
   - typed fields distinguish billed aggregate input from current occupied
     context;
   - one constructor validates cost/cache/context invariants;
   - each provider adapter only translates its raw payload into this type.
3. **MCP launch/conformance contract**
   - manager/registry produce `{allowed, required, translated configs,
     expected identities}`;
   - backend startup proves required identities started and no unallowed
     identity started, not merely `required_names ⊆ started_names ⊆
     allowed_names`;
   - tests include a real runtime smoke in a real Git worktree, not only
     fabricated notifications.

Keep separate:

- process lifecycle and transport;
- provider event dictionaries/mappers;
- permission/reverse-request handling;
- error/quota classification;
- provider-specific compact/resume/steering behavior.

This is not “four providers are bad.” The measured problem is one locally
dormant implicit runtime plus three underspecified shared contracts.

## Counter-evidence and limitations

1. **MCP root cause is not isolated.** The OAuth credential expired before a
   trusted-worktree probe. The empty real/reproduced roster is confirmed, but
   the positive trust transition and same-name collision/precedence matrix are
   both still Phase-2 gates.
2. **Per-category Grok tokens are estimates.** Grok reports exact call totals,
   not section totals. Category counts use `cl100k_base` scaled to exact
   boundaries. Do not present a row as vendor-billed exactness.
3. **Sol comparison is not an A/B test.** The tasks are similar in size but
   differ in code and requirements. It establishes order of magnitude, not a
   model quality ranking.
4. **Clone count is conservative.** Exact blocks ≥3 lines miss semantic clones
   written differently. The same-name method similarity check still found
   only Codex↔Grok lifecycle code notably close.
5. **OpenCode has a dynamic product path.** It can reach proxy-loaded models
   unavailable via the three subscriptions. There is no local model, session,
   usage, process, or plugin configuration, but external deployments were not
   inventoried, so global deletion is not yet justified.
6. **Last-call prompt is not proven occupied context.** The 84,482-token
   measurement disproves the aggregate-as-context calculation, but Grok did
   not expose a separate post-turn retained-context field.

## Adversarial review

The first Codex review returned **Changes required** and challenged five
load-bearing claims [R1]:

- historical request reconstruction was incorrectly presented as a wire fact;
- trust and same-name MCP collision had not been separated;
- name-only MCP conformance permitted substitution;
- last-call prompt was mislabeled as post-turn occupied context;
- local OpenCode inactivity did not justify unconditional global deletion or
  a model/provider/runtime mega-registry.

This revision adopts all five corrections: the MCP root cause remains
uncertain pending both the 2×2 trust/autodiscovery matrix and a separate
same-name identity experiment; context is unknown when its semantics are
unproved; invalid telemetry is fail-soft; OpenCode inventory and explicit
model migration precede both catch-all removal and conditional adapter
deletion; and `ModelSpec`, runtime definition, and provider/quota metadata
remain separate, cross-validated entities.

The resumed review then found that the initial 2×2 design removed the
same-name collision it claimed to test, and that fallback removal could break
uninventoried dynamic proxy models [R1]. Both findings are incorporated above.
It also identified two nonblocking presentation errors: an estimated
32,047/6,663 prompt split labeled exact and a ratio between semantically
different Grok/Sol context fields. Both were removed.

The third round returned **Approved** with no blocking, suggestion, or question
findings. It confirmed that the four second-round corrections were preserved,
the arithmetic remained consistent, and no credential values, secrets, or PII
were present [R1].

## Affected files and risks for a later plan

No production file was changed in this phase.

Likely plan surfaces:

- `app/backend_grok.py`
  - identity-aware symmetric MCP conformance;
  - trust/plugin activation route;
  - context from a semantically verified per-call field or unknown.
- `app/runtime_registry.py`, `app/manager.py`
  - typed MCP launch plan;
  - exhaustive model/runtime/provider consistency;
  - legacy DB-shape conformance.
- `app/events.py` or a new small usage-contract module
  - typed normalized turn usage.
- `app/models.py`, `app/usage_analytics.py`,
  `app/static/js/utils.js`, `app/static/js/usage.js`
  - separate exhaustive model/runtime and provider metadata sources.
- inventory deployments/proxy/plugin consumers, migrate inferred models to
  explicit runtimes, then remove the OpenCode inference catch-all; remove
  `app/backend_opencode.py` and dedicated tests only if the same inventory
  confirms no explicit consumers.
- `tests/test_backend_grok.py`
  - real Git-worktree MCP smoke, required-server-missing failure, context
    aggregate/current regression.
- runtime-wide tests
  - every persisted DB-shape combination builds or fails with an explicit
    compatibility error.

Primary risks:

- trusting the worktree may accidentally re-enable its committed `.mcp.json`;
- checking MCP only by server name permits same-name substitution;
- plugin injection may have a different MCP schema or session-resume behavior;
- using chunk `_meta.totalTokens` as current context without checking its
  semantics could replace one ambiguous field with another;
- generating frontend metadata must not make the dashboard depend on a
  runtime process being available;
- deleting OpenCode requires cross-deployment proxy/plugin/import inventory,
  not only checking this DB or backend file.

## Sources and evidence

1. **[S1, primary code]** `app/manager.py:271-289`,
   `_make_mcp_config`.
2. **[S2, primary code]** `app/runtime_registry.py:124-163,235-286`,
   MCP loaders and Grok/OpenCode factories.
3. **[S3, primary code]** `app/backend_grok.py:280-348,544-561,821-856,
   891-914`, ACP startup, guard, roster tracking, usage, MCP translation.
4. **[S4, primary bundled runtime]**
   `data/grok-home/docs/user-guide/20-background-tasks.md`,
   `~/.grok/README.md`, Grok 0.2.112 binary strings, and
   `grok agent --help` / `grok inspect --json`.
5. **[S5, primary code]** `app/backend_protocol.py`,
   `app/events.py`, all four `app/backend_*.py` implementations.
6. **[S6, primary code]** `app/models.py:166-177`,
   `app/usage_analytics.py:13-29`, `app/static/js/utils.js::_PROVIDER_META`.
7. **[M1, direct measurement]** live SQLite opened via
   `file:/mnt/data/Projects/Python/orchestra/data/orchestra.db?mode=ro`;
   session/log/usage counts and comparable Sol sessions.
8. **[M2, direct measurement]** Grok native session
   `019fa8a0-36dc-7a52-8798-17cecd0e9ab0`: sanitized
   `chat_history.jsonl`, `updates.jsonl`, `events.jsonl`, and unified numeric
   inference records.
9. **[M3, direct measurement]** controlled current-backend MCP probes with
   temporary Grok homes; only server names/status/counts retained.
10. **[M4, direct measurement]** deterministic AST/token/exact-block analysis
    over the four current backend source files.
11. **[S7, primary code]** `app/models.py:254-350,357-370`, dynamic proxy
    model registration, runtime inference, and semantic aliases.
12. **[M5, persisted incident evidence]** project memory/field guide and
    incident messages for the 34-session `pipeline=""` failure; current live DB
    shape remeasured read-only.
13. **[R1, adversarial second opinion]**
    `docs/tasks/98-grok-runtime-audit/codex-review-research.md`, first review
    and resumed verdict.
