# Task #179 — Codex review sandbox

## Result

`codex_review` now executes on this VPS without the unavailable user-namespace sandbox and rejects
blind reviews that nevertheless return exit 0. The live acceptance reviewer executed a real file
read and quoted an exact line that was absent from its prompt.

## Reproduction confirmed

All commands from the task were repeated unchanged:

```text
bwrap --dev-bind / / --unshare-net -- /bin/true
exit 1: bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted

bwrap --dev-bind / / -- /bin/true
exit 1: bwrap: setting up uid map: Permission denied

unshare --user --map-root-user /bin/true
exit 1: unshare: write failed /proc/self/uid_map: Operation not permitted
```

## Implementation

In `app/mcp_stdio.py`:

1. Every fresh, resumed, and stale-session fallback command now invokes Codex as
   `codex -s danger-full-access -a never exec ...`.
2. `--full-auto` was removed. It selected `workspace-write`, which starts vendor `bwrap` and fails
   before every generated shell command on this host.
3. `_CODEX_EXECUTION_FAILURE_PATTERN` detects the observed low-level errors and explicit reviewer
   admissions that the sandbox or all commands failed.
4. The background command checks the JSONL and final round before atomic persistence. A match emits
   `codex_review failed: Codex could not execute workspace commands` and exits 70.

Why this mode: `read-only` and `workspace-write` are unusable here because both require the kernel
facility that was reproduced as unavailable. `danger-full-access` is the remaining and therefore
minimal sufficient Codex sandbox mode. It does not grant permissions beyond the Unix account
already running Orchestra; it only stops Codex from wrapping commands in a sandbox this account
cannot create. `-a never` is required for unattended background execution and is expressed
separately instead of using the broader combined bypass flag.

## Behavioral tests

Command:

```text
uv run pytest -q tests/test_codex_review_sandbox.py tests/test_mcp_codex_review.py tests/test_codex_bin_resolution.py tests/test_codex_review_artifact.py
```

Result: `23 passed in 5.05s`.

The new test executes the complete generated shell command with a fake Codex process that writes a
plausible `## Verdict` and exits 0 after reporting `bwrap`. The command exits 70 and does not persist
the review artifact. Command-construction coverage checks fresh/resumed `exec` and `review` paths.

## Live acceptance and mutation

The first call through this worker's already-connected MCP reproduced the old defect and is kept as
`live-review-original.md`: it reported `bwrap`, wrote a verdict, and the job announced exit 0.

A fresh Python process then called the patched `app.mcp_stdio.codex_review()` against
`read-proof.txt`. The prompt named only the path and line number. Codex emitted a real
`command_execution` event with exit 0 and quoted:

```text
Line 2: ORCHESTRA-179-READ-PROOF-68427.
```

The mutation check ran backup, mutation, patched review, and restoration inside one server-side
shell command. The reviewer observed the changed value:

```text
Line 2: ORCHESTRA-179-MUTATED-93158.
```

After the job, the fixture again contains `ORCHESTRA-179-READ-PROOF-68427` and no backup remains.
Full outputs: `live-review-fixed.md` and `live-review-mutated.md`.

## Rollout behavior for existing agents

The Orchestra MCP command is an absolute path computed by the running server's
`app/runtime_env.py`: `/home/kesha/orchestra/app/mcp_stdio.py`. An agent's MCP subprocess starts
when its backend connects and keeps the imported code for that process lifetime. Editing a worker
worktree therefore never hot-reloads the connected MCP process; after merge, a new backend
connection reads the patched file from the main checkout.

Automatic/manual reconnect paths:

- Worker idle hibernation is scheduled after 300 seconds; orchestrator idle hibernation after 600
  seconds. Hibernation calls `_disconnect_backend()`. The next message constructs and connects a new
  backend, which starts a new MCP subprocess from main.
- A real model change while idle also calls `_disconnect_backend()` immediately; the next message
  starts a new backend/MCP process. Selecting the already active model is a no-op.
- A server restart recreates every backend/MCP process, but is not necessary and was not performed.
- A running or waiting session does not hibernate. Manual hibernation also refuses non-idle,
  pending-delivery, and compacting sessions.

Operational consequence: after merge, the four active workers remain on the old blind MCP until
their current turns/background jobs finish. To make their upcoming reviews safe without restarting
Orchestra, wait until each is idle, manually hibernate it, then send the continuation. Otherwise
allow five idle minutes and let the next message wake it. A model change is an unnecessary,
context-affecting alternative.

## Follow-up required: protect jobs created by old MCP processes

The MCP-side detector cannot protect commands already assembled by one of the nine old processes.
`app/bg_jobs.py::_run_exec` currently accepts exit 0 and then checks only that `success_file` is
nonempty and, for exec review, that it contains `## Verdict`. The reproduced blind artifact passes
both checks.

A separate shared-runtime change should reject known sandbox/command-execution failure markers in
`full_output` and the artifact before `_trigger()`, scoped to Codex review jobs. Changing only the
new MCP job config cannot protect old jobs because their config is already missing such a rule.
This requires editing `app/bg_jobs.py` outside #179's ownership and, unlike `mcp_stdio.py`, requires
an authorized Orchestra restart before the running server uses it. Until that follow-up is deployed,
manual hibernation after this merge is the safe route for currently connected workers.
