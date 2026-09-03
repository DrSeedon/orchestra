# #228 — Enforcement surface inventory

Date: 2026-08-12. Scope: current branch, `pipelines/default/prompts/**`,
`CLAUDE.md`, `pipelines/default/pipeline.yaml`, spawn/admission/manager paths,
backend launch configuration, MCP registration, Claude settings, and the Claude
environment hook. All behavioral probes were local/unit-level; no live session,
service, or task state was touched.

## Executive result

The restrictions divide into three materially different classes:

1. **Hard runtime guards:** known-role spawn topology, new-worker weekly quota,
   Claude's exact blocked built-ins, root path admission, MCP
   `read-only` mode when explicitly selected, MCP `orchestra` name protection,
   overlapping `owned_dirs` at spawn, Codex native multi-agent disablement in
   the constructed CLI launch, and non-force kill guards.
2. **Prompt-only controls:** model choice (including `Terra`/`Fable` bans),
   per-file ownership after spawn, phase/approval gates, immutable-oracle/test
   rules, lifecycle classification, worker prohibition on orchestrator MCP
   tools, deploy authorization, review ceilings, git workflow, and most other
   procedure in roles/modules/skills/`CLAUDE.md`.
3. **Explicitly permissive surfaces:** every managed Orchestra MCP is configured
   `full`; Codex runs `danger-full-access` with approval `never`; Claude uses
   `permission_mode="default"` plus an allow-by-default callback; OpenCode
   explicitly allows edit/bash/external directories; user Claude settings allow
   Bash/Read/Write/Edit/WebSearch/WebFetch. There is no project
   `.claude/settings*.json`, and the proposed shell hook is not installed here.

The most important counter-evidence is concrete:

- a worker's prompt says never use `kill_worker`, while its managed MCP exposes
  that tool and the route has no caller-role/ownership check;
- `owned_dirs` is a hard prompt boundary, but a physical write outside the
  claimed directory succeeded;
- `Terra` is forbidden in the routing prompt, but the API schema accepted it;
- the default manifest is `validation: fail-open`, so `validate_spawn()` alone
  accepts unknown roles (the complete manager path currently fails earlier
  during role prompt resolution);
- the source itself records three observed prompt-enforcement failures at
  `CLAUDE.md:192-193`.

## Method and coverage

- Scanned 20 prompt files / 1,815 lines under `pipelines/default/prompts/**`.
  A broad restriction vocabulary found 380 candidate lines; the inventory below
  groups them by enforcement mechanism rather than restating every imperative.
- Read the exact consuming call paths. A definition or prompt was not counted as
  enforcement unless a local probe executed the path.
- Ran 35 focused existing tests: 30 in the primary restriction batch, 4 kill
  guard tests, and 1 unsafe-path route test. All 35 passed.
- Ran isolated Python probes for prompt-vs-runtime tool behavior, settings
  sources, actual manager spawn results, ownership, MCP registration, route
  model validation, Codex launch construction, quota refusal, safe roots, and
  Claude hook deployment state.

Two-sided prompt-safety terminology used below:

- **Safe:** both forgetting the prompt and applying it too broadly only degrade
  to an already-allowed operational state.
- **Unsafe:** either direction can perform a forbidden/destructive action, lose
  data, bypass approval/isolation, or deny an authorized essential action.

## Inventory by restriction family

### F1. Role prompts, workflow gates, immutable oracle, and acceptance-test rules

**Exact sources.** Base prohibitions and tool routing are at
`pipelines/default/prompts/base.md:4,30-43`; worker restrictions at
`pipelines/default/prompts/roles/worker.md:4,9-20`; full-cycle phase gates at
`pipelines/default/prompts/roles/full-cycle.md:4-8,45-46,109-137,175-200`;
report gates at `pipelines/default/prompts/modules/report-format.md:24-27`.
The prompt also prohibits editing tests and requires an immutable pre-existing
oracle at `pipelines/default/prompts/roles/worker.md:13-18` and
`pipelines/default/prompts/roles/full-cycle.md:117-137,195-200`.

**Runtime guard actually executes?** **No general guard.** The server does not
track current full-cycle phase, approval, RED commit, test identity, or oracle
bytes. The prompt tells the agent and reviewer to compare them. Ordinary
filesystem/runtime permissions remain able to edit any writable path.
Downstream merge/kill tools have their own unrelated guards, but do not enforce
these workflow states.

**Safe probe.** The ownership write probe under F3 is also a direct filesystem
falsifier: a prompt imperative did not restrict the write syscall. The focused
prompt tests included in the 30-test batch prove text assembly, not physical
enforcement.

**Physical violation outcome.** A disobedient agent can implement before an
approval gate, alter an oracle/test, skip the initial RED run, or send multiple
executor attempts. Nothing in the filesystem or session state rejects the
operation solely because it violates these prompt clauses.

**Visibility.** Usually only the git diff/log/report, and only after the fact.
There is no synchronous agent/orchestrator refusal naming the violated phase.

**Two-sided prompt-safety verdict.** **Unsafe.** Under-application can merge
unapproved or oracle-mutating work. Over-application can stop legitimate work
or falsely treat a local/self-authored check as immutable, but the under-side is
already sufficient for an unsafe verdict.

### F2. Claude built-in tools and background execution

**Exact sources.** Prompt statements:
`pipelines/default/prompts/base.md:30-43`. Runtime implementation:
`app/backend_claude.py:49-82` and its live SDK wiring at
`app/backend_claude.py:198-207`. Orchestrators receive `Task`/`Agent` in
`disallowed_tools`; all Claude roles receive scheduling tools in the disallowed
list. `AskUserQuestion`, `Monitor`, and any tool input carrying
`run_in_background=true` are denied by the permission callback.

**Runtime guard actually executes?** **Yes for exact `disallowed_tools`; not for
the background payload.** This inventory's original direct callback probe proved
only what the Python function returns when called manually. A later real-backend
counter-probe (`probes/local/runtime-probes.md` P4) observed
`Bash(run_in_background=true)` execute with `is_error=false` and recorded zero
callback invocations. The callback is also not cross-runtime.

**Exact safe probe and raw output (excerpt).** Command:

```bash
/home/kesha/orchestra/.venv/bin/python - <<'PY'
import asyncio
from app.backend_claude import _make_auto_approve, _disallowed_tools
async def main():
    for orch in (False, True):
        cb = _make_auto_approve(orch)
        print("role", orch, "disallowed", _disallowed_tools(orch))
        for name, args in [("AskUserQuestion", {}), ("Monitor", {}),
                           ("Agent", {}), ("Bash", {"command":"true"}),
                           ("Bash", {"command":"true", "run_in_background":True})]:
            r = await cb(name, args)
            print(name, type(r).__name__, getattr(r, "message", ""))
asyncio.run(main())
PY
```

```text
role False disallowed ['ScheduleWakeup', 'CronCreate', 'CronDelete', 'CronList', 'Workflow']
AskUserQuestion PermissionResultDeny AskUserQuestion is not available in Orchestra.
Monitor PermissionResultDeny Monitor is not available in Orchestra.
Agent PermissionResultAllow
Bash PermissionResultAllow
Bash PermissionResultDeny run_in_background is disabled in Orchestra ...
role True disallowed [..., 'Task', 'Agent']
Agent PermissionResultDeny Agent is not available for orchestrators. Use spawn_worker instead.
```

The focused regression command was
`python -m pytest tests/test_disallowed_tools.py -q`; it passed `2/2` as part of
the 30-test batch.

**Physical violation outcome.** Exact disallowed tools are absent from the CLI
tool set. `AskUserQuestion` produced a loud callback deny in a real control run,
but background Bash physically executed because the callback was not called.
Counter-evidence: a **worker** deliberately retains the native `Task` delegation
tool even though `base.md:39-40` states a universal ban.

**Visibility.** Callback denial returns explicit text to the agent and is
visible in its tool result. A disallowed tool is instead absent from the model's
tool catalog.

**Two-sided prompt-safety verdict.** The exact hard-denied subset is **safe from
prompt forgetting**. The background claim is **REFUTED** as enforcement and needs
`PreToolUse`; the universal built-in-Agent statement is **unsafe/inconsistent**
because Claude workers physically retain native `Task` delegation.

### F3. Worktree and `owned_dirs` territory

**Exact sources.** Prompt boundary:
`pipelines/default/prompts/modules/git-workflow.md:5-15` and
`pipelines/default/prompts/roles/worker.md:10`. Dynamic ownership overlay:
`app/manager.py:477-485,623-630`. Runtime overlap check:
`app/manager.py:583-609`; normalization and prefix comparison:
`app/workspace.py:2237-2265`.

**Runtime guard actually executes?** **Partly.** Spawn is rejected when declared
directories overlap an existing live worker. After spawn there is **no syscall,
path, patch, git, or commit guard** confining the worker to those directories.
The isolated manager probe executed the overlap rejection. A second probe wrote
outside the declared directory.

**Exact safe probes and raw output.** Manager overlap probe (temporary DB,
in-memory existing session):

```text
owned_dirs_overlap_outcome= ValueError owned_dirs overlap with 'existing': app/api/v1. Use different dirs or kill 'existing' first
```

Filesystem probe (temporary directory under this owned artifact directory):

```text
## Directory ownership | You OWN these directories — edit ONLY files under them: | - claimed/ | Do NOT touch files outside your owned directories. If the task requires it — STOP and ask the orchestrator.
outside_claimed_write= physical write succeeded exists= True
```

**Physical violation outcome.** Collision prevention works only if both workers
accurately declare `owned_dirs`. A worker can physically edit outside its list,
the main checkout, or another unclaimed directory. The write succeeds normally.

**Visibility.** Overlap is a synchronous `ValueError` surfaced as spawn failure.
An out-of-territory edit has no special event; it is visible only in filesystem
or git inspection.

**Two-sided prompt-safety verdict.** **Unsafe.** Forgetting permits cross-worker
overwrites or main-checkout edits; over-applying can block a necessary file not
included in an incomplete ownership list.

### F4. Spawn topology: `can_spawn`, role resolution, and root exemption

**Exact sources.** Manifest policy:
`pipelines/default/pipeline.yaml:3,35-45,52-77,84-100`. Schema and graph
validation: `app/pipeline.py:207-227,308-327`. Runtime decision:
`app/pipeline.py:612-658`. Manager calls it before worktree/start side effects at
`app/manager.py:643-653`; prompt assembly occurs earlier at
`app/manager.py:623-630`.

**Runtime guard actually executes?** **Yes for known roles.** Actual manager
probes reject `worker -> worker` before session publication/worktree creation.
The default manifest is `fail-open`, so `validate_spawn()` alone allows an
unknown parent/child. In the full manager path, an unknown child currently dies
earlier because its role prompt cannot be resolved. Root sessions (no parent)
are deliberately exempt.

**Exact safe probes and raw output.** Existing integration command:

```bash
/home/kesha/orchestra/.venv/bin/python -m pytest \
  tests/test_pipeline.py::TestValidateSpawn \
  tests/test_default_pipeline.py::TestDefaultValidateSpawn \
  tests/test_manager.py::TestValidateSpawnIntegration::test_forbidden_spawn_blocked_before_side_effect -q
```

The broader batch output was:

```text
.............................. [100%]
30 passed in 7.88s
```

Direct current-default counter/proof:

```text
validate_spawn: worker -> 'worker' DENY ValueError ... terminal
validate_spawn: worker -> 'ghost' ALLOW
manager: worker DENY ValueError role 'worker' cannot spawn 'worker'...
manager: ghost DENY ValueError role 'ghost' not resolvable in pipeline 'default'...
```

**Physical violation outcome.** Known prohibited topology produces a spawn
error and no worktree. Unknown role acceptance in the narrow validator does not
currently create a session because prompt resolution fails first. A root/UI
caller can create any resolvable role by design.

**Visibility.** Manager `ValueError` becomes HTTP 409 at
`app/routes/sessions.py:210-219`; MCP wraps it as a spawn failure.

**Two-sided prompt-safety verdict.** The known-role topology is **hard-enforced,
not prompt-dependent**. The fail-open unknown-role branch is unsafe as a sole
guard; present safety depends on an earlier independent failure, so callers of
`validate_spawn()` must not infer fail-closed behavior.

### F5. Model routing and model bans

**Exact sources.** Routing imperatives and the `Terra`/`Fable` bans are at
`pipelines/default/prompts/modules/model-routing.md:2-16` and duplicated as
policy narrative at `CLAUDE.md:84-92`. Manifest defaults are at
`pipelines/default/pipeline.yaml:5,40-41,56-57,72-73,88-96`. API validation only
checks registry membership at `app/routes/sessions.py:110-157`.
`spawn_worker` requires a nonempty model but delegates which model to the prompt
at `app/mcp_stdio.py:707-740`.

**Runtime guard actually executes?** **Only syntactic/registry validation.** An
empty or unknown model is rejected. Task-class routing, Luna-first policy,
Spark criteria, and `Terra`/`Fable` prohibitions are not enforced by spawn or
manager code.

**Exact safe probe and raw output.** Command instantiated the actual request
schema for three registered models:

```text
spawn_request_model= gpt-5.6-luna ACCEPTED_AS gpt-5.6-luna
spawn_request_model= gpt-5.6-terra ACCEPTED_AS gpt-5.6-terra
spawn_request_model= claude-opus-5[1m] ACCEPTED_AS claude-opus-5[1m]
manager_created= terra-probe model= gpt-5.6-terra published= True
```

The manager line came from a temporary isolated database with a mocked backend
and `planned_initial_turn=False`; the created session was stopped before the
probe exited.

**Physical violation outcome.** A caller can request and create a registered
but prompt-forbidden model. The rejection, if any, comes from quota/readiness,
not from the Terra/Fable/task-class rule.

**Visibility.** No warning identifies a routing-policy violation; dashboard and
logs merely show the selected model after creation.

**Two-sided prompt-safety verdict.** **Unsafe.** Under-application starts a model
the user explicitly prohibited; over-application can deny the documented Opus
fallback or Sol complexity exception. `CLAUDE.md:192-193` independently records
a 1/1 Terra prompt-ban failure and says forbidden consequences require code.

### F6. Weekly worker admission / quota

**Exact sources.** Policy and error contract:
`app/quota_gate.py:15-20,24-54,95-135,201-249,272-355`. Spawn preflight:
`app/manager.py:650-653`. Every new idle worker turn:
`app/session.py:882-927`. HTTP mapping: `app/routes/sessions.py:210-219`.
Orchestrator, running-turn steering, and compact/reconnect paths are intentionally
exempt by the condition at `app/session.py:895-899`.

**Runtime guard actually executes?** **Yes.** It is fail-closed for stale/unknown
worker quota and blocks at `>=95%`. A planned initial worker turn is refused
before publishing the session. It does not stop a turn already running and does
not gate orchestrator turns.

**Exact safe probe and raw output.** Direct decision and refusal:

```text
decision= blocked 95.0 allowed= False
physical_outcome= QuotaGateError New worker turn blocked: Codex weekly quota is 95% (new worker turns stop at 95%). Wait for quota telemetry or reset.
```

Focused integration test included in the primary batch:
`tests/test_manager.py::TestCreateSession::test_planned_initial_turn_is_refused_before_session_publish`;
it passed.

**Physical violation outcome.** New worker session/turn is not started; HTTP is
429 with canonical non-retryable detail. Steering an already running worker and
orchestrators continue by design.

**Visibility.** Explicit `QuotaGateError`/HTTP error to caller; quota block
notices are also routed to the parent elsewhere in manager/session code.

**Two-sided prompt-safety verdict.** **Hard-enforced.** Fail-closed overreach can
temporarily deny work when telemetry is unavailable, but that is an explicit
server safety policy rather than agent interpretation.

### F7. MCP access mode, registration, and role exposure

**Exact sources.** MCP read-only catalog and filtering:
`app/mcp_stdio.py:51-66,267-289,2266-2269`. Managed server construction:
`app/manager.py:393-415`; it always sets `ORCHESTRA_ACCESS_MODE=full` at line 401.
Codex's enabled-tool list and config translation:
`app/backend_codex.py:276-286,1558-1594`. Scope/user MCP discovery:
`app/runtime_registry.py:117-156`. Custom MCP sanitization protects only the
reserved `orchestra` name at `app/manager.py:375-390`.

**Runtime guard actually executes?** **Read-only filtering works when selected,
but managed sessions do not select it.** All managed roles receive `full`, and
Codex explicitly receives `spawn_worker`, `kill_worker`, and the other full
tools. `ORCHESTRA_ROLE` filters how `list_agents` is displayed
(`app/mcp_stdio.py:1004-1016`), not mutating tool registration. Known-role spawn
is still stopped later by F4, but `kill_worker`, task/payment mutation, and
other tools have their own endpoint-specific checks rather than a worker-role
deny.

**Exact safe probes and raw output.** Filtering and merge probe:

```text
read-only= ['get_worker_logs', 'list_agents']
full= ['get_worker_logs', 'kill_worker', 'list_agents', 'send_message', 'spawn_worker']
readonly_catalog_size= 12
sanitized_custom= {'demo': {'command': 'demo'}}
orchestra_access_mode= full
mcp_keys= ['demo', 'orchestra']
```

Scope settings probe:

```text
loaded_scope_mcp= {'from_settings': {'command': 'settings-cmd'}, 'from_mcp_json': {'command': 'mcp-cmd'}}
```

The attempted `orchestra` overrides in both files were stripped; both other
servers loaded. Focused MCP tests passed in the 30-test batch:
`test_read_only_access_mode_hides_mutating_tools`,
`test_full_access_mode_preserves_all_tools`, and
`test_unknown_access_mode_is_rejected`.

A direct isolated/mocked worker-role call showed the absence of a caller-role
guard at the MCP function boundary:

```text
worker_role_kill_tool_outcome= Worker 'victim' stopped and archived.
worker_role_kill_api_call= [('DELETE', '/api/sessions/victim', {'params': {'scope': '/isolated', 'force': 'true'}})]
```

**Physical violation outcome.** Read-only mode removes mutating tools from MCP
registration. In normal managed mode a worker can invoke a prompt-forbidden
mutating MCP. Endpoint guards may reject the target state, but no general
caller-role gate rejects the invocation.

**Visibility.** Tool presence is visible to the agent. Endpoint rejection is
visible in the tool result. Successful cross-owner `send_message` gives only a
post-send warning (`app/mcp_stdio.py:900-903`); mutating calls do not have a
uniform ownership warning.

**Two-sided prompt-safety verdict.** **Unsafe for worker/orchestrator tool
separation.** Under-application can mutate/archive outside intended authority;
over-application via read-only would also remove necessary reporting and task
workflow tools. The reserved MCP name protection itself is hard and safe.

### F8. CLI permissions, sandbox, native delegation, and secret-bearing argv

**Exact sources.** Claude options:
`app/backend_claude.py:181-238`. Codex command and thread parameters:
`app/backend_codex.py:393-483`; unexpected client approval requests are rejected
at `app/backend_codex.py:800-827`. Codex MCP config is emitted through `-c`
arguments at `app/backend_codex.py:1558-1594`. MCP base env includes
`INTERNAL_TOKEN` at `app/runtime_env.py:15-20`. OpenCode explicitly allows
edit/bash/webfetch/external directories at `app/backend_opencode.py:169-175`.

**Runtime guard actually executes?** Mixed:

- Codex launch construction executes with `features.multi_agent=false` — a hard
  configuration request to disable native agents.
- Codex thread starts with `approvalPolicy=never` and
  `sandbox=danger-full-access`; these are permissive, not guards.
- Claude's callback denies the F2 subset and allows everything else.
- The unit probe proves the exact command/JSON-RPC request Orchestra sends; it
  does not independently certify the external CLI's implementation of every
  option.

**Exact safe probe and raw output (secret redacted before printing).** The probe
mocked `asyncio.create_subprocess_exec` and the JSON-RPC transport while executing
`CodexBackend.connect()`:

```text
argv_flags= ['features.multi_agent=false', 'web_search="live"', 'app-server', '--stdio']
mcp_env_arg= mcp_servers.orchestra.env={..., INTERNAL_TOKEN="<redacted>", ..., ORCHESTRA_ROLE="worker", ORCHESTRA_ACCESS_MODE="full", ...}
enabled_tools_has_spawn= True has_kill= True
thread_start= {'cwd': '/tmp', 'model': 'gpt-5.6-sol', 'approvalPolicy': 'never', 'sandbox': 'danger-full-access', 'developerInstructions': 'ROLE'}
```

`tests/test_backend_codex.py::test_connect_uses_scope_and_preserves_stdio` and
`::test_mcp_config_args_dotted_leaves` passed in the 30-test batch.

**Physical violation outcome.** Filesystem edits and commands execute without
interactive approval or Codex sandbox containment. Native Codex multi-agent is
requested off, but Orchestra full MCP delegation remains enabled. The internal
token is serialized in command-line config; local process-list readers can see
argv unless the launcher/runtime hides it. This is counter-evidence against
treating CLI config as a secrecy boundary (and is already tracked as #224 in
`CLAUDE.md:311`).

**Visibility.** Tool calls appear in agent logs. Sandbox/approval settings are
not normally narrated to the agent. CLI argv is visible to local process
inspection, including its token value; this report retains only a redaction.

**Two-sided prompt-safety verdict.** **Unsafe as filesystem/command isolation.**
The native-agent disable is a hard defense for that narrow path; disabling too
broadly would break legitimate Orchestra delegation, which remains separately
enabled.

### F9. Claude settings and project settings

**Exact sources.** SDK settings selection:
`app/backend_claude.py:234-238`. Scope MCP parsing from
`.claude/settings.json`, `.claude/settings.local.json`, and `.mcp.json`:
`app/runtime_registry.py:117-139`. Current user file:
`/home/kesha/.claude/settings.json:2-10`.

**Runtime guard actually executes?** Settings are loaded (`setting_sources`
contains user/project/local), but current settings are **permission grants**,
not restrictions. The project/worktree has no `.claude/settings.json` or
`.claude/settings.local.json`. Claude's F2 callback remains the hard override
for its denied subset.

**Exact safe probe and raw output.** SDK options probe:

```text
permission_mode= default
setting_sources= ['user', 'project', 'local']
disallowed_tools= ['ScheduleWakeup', 'CronCreate', 'CronDelete', 'CronList', 'Workflow', 'Task', 'Agent']
```

Filesystem/state probe:

```text
user settings allow: Bash(*), Read(*), Write(*), Edit(*), WebSearch(*), WebFetch(*)
project_settings: absent
project_local_settings: absent
```

**Physical violation outcome.** User settings permit broad tools; they do not
stop writes or shell commands. A project settings file can add scope MCP servers
other than `orchestra`; the reserved name is stripped by runtime parsing.

**Visibility.** Permission prompts are suppressed for allowed operations.
Malformed MCP settings log a server warning, usually invisible to the agent.

**Two-sided prompt-safety verdict.** **Unsafe if relied on for policy.** There is
no deny policy here to forget; over-broad settings removal could break required
tools, while present grants leave physical safety to other guards.

### F10. Claude environment hook

**Exact sources.** Hook payload:
`deploy/orchestra-claude-env.sh:1` (exactly
`unset -f grep find 2>/dev/null || true`). Drop-in:
`deploy/orchestra-claude-env.conf:1-2`. Installer and rollback:
`deploy/manage-claude-env-hook.sh:17-42,187-207,230-261`.

**Runtime guard actually executes?** **Not on this deployment.** Current probe
found no `CLAUDE_ENV_FILE` in this process and no
`/etc/orchestra/claude-env.sh`. Even when installed, the hook restores real GNU
`grep`/`find` semantics; it does not authorize/deny commands, files, tools, or
models.

**Exact safe probe and raw output.** Existing isolated hook behavior test:

```bash
/home/kesha/orchestra/.venv/bin/python -m pytest \
  tests/test_claude_env_hook.py::test_hook_runs_after_vendor_functions_and_restores_gnu_semantics -q
```

It passed in the 30-test batch. Deployment-state probe:

```text
CLAUDE_ENV_FILE=<unset>
hook_present=no
```

The test's asserted physical behavior is: after sourcing, `type -P grep` is
`/usr/bin/grep`, `type -P find` is `/usr/bin/find`, non-recursive grep on a
directory exits 2, and recursive grep finds the fixture.

**Physical violation outcome.** Without installation, vendor function
substitution (if present) is not neutralized by this mechanism. With it, only
the two shell functions are unset. No prohibited action is blocked.

**Visibility.** Installation/rollback prints that restart is required and not
performed. Runtime sourcing is otherwise silent.

**Two-sided prompt-safety verdict.** Not a prompt control. Operationally
two-sided: failure to apply leaves misleading grep/find behavior; applying to an
environment that intentionally depends on vendor functions changes semantics.
The exact two-function payload bounds that risk.

### F11. Admission path roots and denied secret paths

**Exact sources.** Route gate:
`app/routes/sessions.py:175-180`. Root/secret policy:
`app/routes/system.py:160-211`. This restricts session `cwd`, not the subsequent
agent's filesystem syscalls.

**Runtime guard actually executes?** **Yes at HTTP session creation.** Resolved
paths must be under allowed roots and may not include denied dot-directories,
database/key extensions, or specific secret components.

**Exact safe probe and raw output.** Command called `_is_safe_path` directly:

```text
/tmp True
/home/kesha/orchestra True
/home/kesha/.ssh False
/home/kesha/.claude/settings.json False
/home/kesha/orchestra/data/orchestra.db False
/etc False
```

The actual session-create route was then called with the existing denied
directory:

```text
status= 403 body= {"error":"cwd not in allowed paths: /home/kesha/.ssh"}
```

`tests/test_api.py::TestChangeScopeEndpoint::test_403_unsafe_path` also passed
(`1 passed in 5.78s`), exercising the same root policy on the scope-change
route.

**Physical violation outcome.** Unsafe `cwd` receives HTTP 403 and manager is
not invoked. Once a permitted cwd is admitted, broad backend permissions can
still address paths outside cwd; F3/F8 show there is no general filesystem
confinement.

**Visibility.** Explicit HTTP 403: `cwd not in allowed paths`.

**Two-sided prompt-safety verdict.** Hard-enforced for cwd. It must not be
misrepresented as a sandbox: overgeneralizing it would create a false security
claim.

### F12. Kill/lifecycle restrictions and force bypass

**Exact sources.** Prompt lifecycle classification:
`pipelines/default/prompts/modules/worker-lifecycle.md:4-17`. MCP interface:
`app/mcp_stdio.py:1091-1106`. Hard route guards:
`app/routes/sessions.py:724-792` — running worker, live children, dirty tree,
content not merged, and detector error. All are skipped by `force=true` except a
subsequent physical remove failure.

**Runtime guard actually executes?** **Partly.** Dirty/unmerged/live-child/running
checks execute for non-force calls. The semantic rules “one-shot vs persistent”,
“final DONE”, “awaiting approval”, and “user explicitly requested cleanup” are
prompt-only; the route does not parse lifecycle description or reports. Any
caller with the full MCP can request force.

**Exact safe probe and raw output.** Command:

```bash
/home/kesha/orchestra/.venv/bin/python -m pytest \
  tests/test_api.py::test_kill_blocks_real_unmerged_content \
  tests/test_api.py::TestDeleteOrphanGuard::test_blocks_kill_with_live_child \
  tests/test_api.py::TestDeleteOrphanGuard::test_force_overrides \
  tests/test_mcp_stdio.py::test_kill_worker_force_param -q
```

```text
.... [100%]
4 passed in 8.53s
```

**Physical violation outcome.** Non-force archive is rejected with HTTP 400 and
the worker remains. `force=true` archives despite live children/dirty/unmerged
state by design. A prompt-disobedient worker with full MCP can therefore request
the physical bypass; only actual removal failure stops it.

**Visibility.** Non-force refusals explain the exact state and mention force.
Successful force returns only “stopped and archived”; it does not warn that a
prompt lifecycle rule was bypassed.

**Two-sided prompt-safety verdict.** **Unsafe for semantic lifecycle.** Forgetting
can permanently archive a full-cycle/persistent worker or discard work;
over-applying merely keeps an idle worker, but the destructive under-side is
decisive. The non-force git/child guards are hard and useful defense-in-depth.

### F13. Procedural modules/skills and `CLAUDE.md` operational restrictions

**Exact sources.** Representative owners (all are injected text, not policy
state): deployment authorization at
`pipelines/default/prompts/skills/vps-deploy.md:3,11-13,48-49` and
`CLAUDE.md:60-64`; Codex review process at
`pipelines/default/prompts/skills/codex-debate.md:29,81,95-100,120,145,159`;
research safety at
`pipelines/default/prompts/modules/research-method.md:20-27,76-87`; git at
`pipelines/default/prompts/modules/git-workflow.md:5-31`; memory search at
`pipelines/default/prompts/modules/memory-search.md:2-18`; agent management at
`pipelines/default/prompts/modules/orchestration.md:10-18,63-83,139-181,231-269`;
and the explicit
prompt-vs-code safety test at `CLAUDE.md:192-193`.

**Runtime guard actually executes?** **Generally no.** Skills/modules shape the
system prompt. Individual commands may later hit specific guards (quota, spawn,
kill, auth), but the platform does not maintain “skill loaded”, “review round”,
“research phase”, “deploy authorized”, “memory searched”, or “correct source
tier” state. The `systemctl`/deploy prohibition is authorization text, not a
shell deny.

**Exact safe probe.** Static assembly was covered by the selected default
pipeline tests in the 30-test batch. The physical falsifiers are the permissive
backend launch (F8) and successful out-of-territory write (F3): injection does
not change OS permissions.

**Physical violation outcome.** A disobedient agent can skip skill loading,
exceed a prose/review ceiling, run a deployment command, use the wrong source,
or omit memory search unless a separate endpoint/OS policy happens to stop the
specific operation.

**Visibility.** Mostly retrospective in transcript, shell history, git diff,
external state, or review artifacts. No standard synchronous policy event.

**Two-sided prompt-safety verdict.** Mixed by consequence, but **unsafe for any
procedure whose under-application can mutate production, lose data, bypass an
approval/review, or expose secrets**. Pure style/source-order guidance is safer:
over/under-application usually affects quality/cost rather than authority.

## Consolidated enforcement map

| Family | Hard guard on physical action? | Counter-evidence / bypass | Agent-visible refusal? |
|---|---|---|---|
| Phase/oracle/test workflow | No | Writable files and no phase state | No |
| Claude blocked built-ins/background | Exact names yes; background no | Worker `Task` retained; background Bash executed with callback=0 | Name absent / hook gap |
| `owned_dirs` | Spawn overlap only | Out-of-list write succeeded | Only overlap |
| `can_spawn` | Yes for actual known-role manager path | narrow validator fail-open for unknown; root exempt | Yes, 409/tool error |
| Model routing/Terra ban | Registry validation only | Terra schema accepted | No policy warning |
| Weekly worker quota | Yes for new idle worker turns | running steering/orchestrators exempt by design | Yes, 429/tool error |
| MCP role separation | Read-only capability exists, unused by managed sessions | all managed roles get `full` | Tool catalog only |
| CLI sandbox/approval | Native Codex delegation requested off | danger-full-access, approval never, broad Claude/OpenCode allow | Usually no |
| Settings | Claude deny subset supersedes settings | user settings broadly allow; project settings absent | Usually no |
| Env hook | Only grep/find semantic repair, currently absent | not an action authorization guard | Installer output only |
| cwd safe roots | Yes at session-create route | not a post-create filesystem sandbox | Yes, 403 |
| Kill lifecycle | Git/children/running guards unless force | force bypass; lifecycle semantics prompt-only | Yes only for non-force |
| Skills/modules/CLAUDE procedures | Generally no | OS/backend permissions unchanged | No standard event |

## Raw test record

Primary command:

```bash
/home/kesha/orchestra/.venv/bin/python -m pytest \
  tests/test_pipeline.py::TestValidateSpawn \
  tests/test_default_pipeline.py::TestDefaultValidateSpawn \
  tests/test_manager.py::TestValidateSpawnIntegration::test_forbidden_spawn_blocked_before_side_effect \
  tests/test_disallowed_tools.py \
  tests/test_mcp_stdio.py::test_read_only_access_mode_hides_mutating_tools \
  tests/test_mcp_stdio.py::test_full_access_mode_preserves_all_tools \
  tests/test_mcp_stdio.py::test_unknown_access_mode_is_rejected \
  tests/test_backend_codex.py::test_mcp_config_args_dotted_leaves \
  tests/test_backend_codex.py::test_connect_uses_scope_and_preserves_stdio \
  tests/test_claude_env_hook.py::test_hook_runs_after_vendor_functions_and_restores_gnu_semantics \
  tests/test_manager.py::TestCreateSession::test_planned_initial_turn_is_refused_before_session_publish -q
```

Raw result:

```text
..............................                                           [100%]
30 passed in 7.88s
```

Kill command/result are recorded under F12; the additional unsafe-path route
test is recorded under F11. Total focused existing tests:
**35 passed, 0 failed**.

## Bottom line for the parent audit

The source already contains the correct design principle at
`CLAUDE.md:192-193`: prompts are acceptable only when both failure directions
are harmless. Applying that principle to this inventory leaves a short hard
core (quota, known-role topology, selected Claude tool denies, cwd admission,
MCP reserved-name/read-only implementation, spawn overlap, and non-force kill
guards) surrounded by a much larger advisory surface. Any desired guarantee
about model bans, per-file territory, worker authority, phase/oracle integrity,
semantic lifecycle, deployment authorization, or review ceilings is not an
enforcement guarantee in the current runtime.
