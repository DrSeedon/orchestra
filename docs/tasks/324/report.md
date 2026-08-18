# #324 — the TG bridge may only start in the instance systemd runs

Live incident, 18.08.2026: an app started by an agent inside its worktree polled Telegram with
the production token and swallowed the user's incoming messages.

## Why code and not a prompt rule

The project's own criterion for where a rule may live: a prompt is admissible only when BOTH
directions of failure degrade into today's behaviour. Here the "agent forgot the rule" direction
produces the incident itself — a second getUpdates consumer, and the user's Telegram stops
working. That is a forbidden action, not a degradation, so the rule has to be enforced by code.

Measured 18.08.2026 before this change: `.env` is copied into every worktree at spawn, 22 of 42
copies carry the production `TG_BRIDGE_TOKEN` (sha256 `ee7326271483`, identical to the main
checkout), two orphans (`ppid=1`, cwd `worktrees/home-kesha-orchestra/feat-runtime-switch`) held
`127.0.0.1:8081` and produced 383 `TelegramConflictError` in one hour. Killing them took the
count to 0.

## The discriminator, chosen by measurement rather than by plausibility

The obvious candidates fail. An agent's shell **inherits** the systemd markers from the service
that spawned it. Measured in this worktree, from a worker's own Bash:

```
$ env | grep -E '^(INVOCATION_ID|LISTEN_FDS|LISTEN_PID|NOTIFY_SOCKET|SYSTEMD_EXEC_PID)='
LISTEN_FDS=59
SYSTEMD_EXEC_PID=2577299
INVOCATION_ID=04fd72909f134e93ab9726ccebc88331
NOTIFY_SOCKET=/run/systemd/notify
LISTEN_PID=2577299
```

So *presence* of any of these proves nothing — a test instance has all five. Testing for
`INVOCATION_ID`, `NOTIFY_SOCKET` or `LISTEN_FDS` would have been a check that returns the same
answer whether or not the process is canonical.

What is not inheritable is the **pid identity**. `sd_listen_fds` sets `LISTEN_PID` to the pid of
the very process systemd exec'd, and the unit runs `uvicorn app.main:app --fd 3` under
`Requires=orchestra.socket`, so it is always set there. Measured on the live service:

```
MainPID=2577299   cwd=/home/kesha/orchestra
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m uvicorn app.main:app --fd 3
LISTEN_PID=2577299
```

`LISTEN_PID == str(os.getpid())` holds in that process and in no descendant of it. Uvicorn
without `--workers`/`--reload` runs the app in the process systemd exec'd, so the identity is
available to application code — confirmed by `ps -p 2577299` showing the python process itself,
not a supervisor.

Rejected: comparing the running code's directory against the canonical checkout (via
`git rev-parse --git-common-dir`). It adds a subprocess at startup and covers nothing extra —
the unit pins `WorkingDirectory=/home/kesha/orchestra`, so a systemd-launched instance can never
run from a worktree, and a worktree-launched instance is already refused by the pid check. It
would also miss an app started from the main checkout, which the pid check catches.

## The change

`app/tg_bridge.py`, two additions and one call:

- `UnmanagedInstanceError(RuntimeError)`;
- `_unmanaged_instance_reason() -> str | None`, fail-closed in both directions — an unset
  `LISTEN_PID` refuses just as an inherited one does, so the guard is not green in an empty room;
- the call as the **first statement** of `start_bridge`, before `load_dotenv()` and before the
  token is read.

`start_bridge` is the only seam: `grep -rn "TG_BRIDGE_TOKEN" app/` returns exactly one read
(`app/tg_bridge.py:3747`), both `Bot(token=…)` constructions are inside it, and both call sites
(`app/main.py:46` and the `__main__` block at the bottom of `tg_bridge.py`) go through it.

Fail loud: the guard raises rather than returning. `_start_bridge_background` already logs
`TG bridge FAILED to start: <class>: <message>` with a traceback, and the message names the
failing check, both pids and the cwd:

```
TG bridge refused to start: LISTEN_PID=2577299 does not match this process (2707527) — the
value was inherited from the canonical instance, not assigned to this one. Only
orchestra.service (`uvicorn app.main:app --fd 3`, socket-activated) may hold TG_BRIDGE_TOKEN;
a second poller silently swallows the user's Telegram messages (#324). Nothing else about this
instance is affected. cwd=/home/kesha/orchestra/worktrees/home-kesha-orchestra/some-worker
```

Refusal is confined to the bridge: HTTP keeps serving, because `_start_bridge_background` runs
as a background task and catches the exception.

## systemd

**RETRACTED — the first version of this report said "No unit change required" and that was
wrong.** Corrected after independent review (H1, `docs/tasks/324/opus-review.md`), reproduced
here before accepting it.

The live service passes the guard because of an **untracked drop-in**,
`/etc/systemd/system/orchestra.service.d/60-runtime-isolation.conf` (#303, dated 16.08), which
does `ExecStart=` (reset) and then pins a direct interpreter path. The base `ExecStart` — in
`/etc/systemd/system/orchestra.service` *and* in the tracked `deploy/orchestra.service:38` — was
`uv run uvicorn app.main:app --fd 3`, and **`uv run` does not exec, it forks**. Measured by me,
independently of the reviewer:

```
$ sh -c 'LISTEN_PID=$$ exec /home/kesha/.local/bin/uv run --no-project python /tmp/324-pidcheck.py'
LISTEN_PID=2751595 app_pid=2751601 MATCH=False      <- the guard would have refused
$ sh -c 'LISTEN_PID=$$ exec /home/kesha/orchestra/.venv/bin/python /tmp/324-pidcheck.py'
LISTEN_PID=2751602 app_pid=2751602 MATCH=True       <- the live drop-in's form
```

So on the tracked configuration this change would have taken the production bridge down, and
`--fd 3` was never what satisfied the check — the **direct exec of the interpreter** is. HTTP
would have kept working (fd 3 is inherited by the forked child either way), which is exactly what
makes the failure quiet: one line in the journal, and the user discovers it as silence in
Telegram.

**How I missed it:** `ps` showed the live process as
`/opt/orchestra/runtimes/…/bin/python -m uvicorn app.main:app --fd 3` while the unit I had just
read said `uv run uvicorn …`. I had both facts and never asked why they differed. The
measurement was right; the attribution of *why* it passed was not.

### Changed here (repo files only — nothing applied to /etc)

- `deploy/orchestra.service:38` → `ExecStart=/home/kesha/orchestra/.venv/bin/python -m uvicorn
  app.main:app --fd 3`, with the constraint and the measurement in a comment above it. The
  dated `/opt/orchestra/runtimes/...` path is deliberately *not* copied here: it rots on every
  runtime rebuild, and which runtime to use is #303's drop-in decision. This line only has to be
  safe when that drop-in is absent. `systemd-analyze verify` → rc=0.
- `app/tg_bridge.py` guard docstring — now names the direct exec as the mechanism instead of
  citing the `uv run … --fd 3` line, which does *not* satisfy the guard.

**Still an operator action.** Nothing in /etc was touched by me.

## Tests — `tests/test_tg_bridge_instance_guard.py`

Four cases: worktree-like instance refuses (inherited `LISTEN_PID`, worktree cwd), bare process
refuses (no systemd vars), socket-activated process is let through, and the recorded live
service environment passes the guard.

Two things stop them from passing vacuously. The `bridge_body_tripwire` fixture replaces
`_reset_tg_delivery_state` — the first real step of `start_bridge` — with a raiser, so a guard
that stopped firing surfaces as `_ReachedBridgeBody` instead of a quiet `return`. And the
permitting arm asserts that the body IS reached, so a guard wired to reject everything (which
would take the production bridge down) cannot pass either.

`start_bridge` is bound by name at module scope because conftest's autouse `_no_tg_bridge`
fixture replaces the module attribute with an `AsyncMock`; the module-scope binding keeps
pointing at the real coroutine.

### Mutation runs (protocol: `cp` → mutate → run → `mv` back → `touch` → marker count both sides → green repeat)

| # | Mutation | Marker before / after revert | Result |
|---|---|---|---|
| A | `reason = _unmanaged_instance_reason()` → `reason = None` (guard not wired) | 1 / 1 | **2 failed**, both raising `_ReachedBridgeBody` — the bridge body was really entered |
| B | `if listen_pid != str(os.getpid()):` → `if False:` (inherited pid accepted) | 1 / 1 | **1 failed** (`test_worktree_instance_refuses_to_start`), `_ReachedBridgeBody` |
| C | `if not listen_pid:` → `if False:` (missing `LISTEN_PID` accepted) | 1 / 1 | **1 failed** (`test_bare_process_refuses_to_start`) — falls through to the wrong branch and the message assertion catches it |

Each mutation targeted a string with `grep -c == 1` in the file (asserted inside the patch
script, so a non-applying mutation aborts instead of reading as "survived"). Green repeat after
every revert: `4 passed`. Final: `4 passed`.

### Regression runs

- `tests/test_tg_bridge.py tests/test_startup_bridge.py tests/test_tg_bridge_instance_guard.py` → **199 passed**
- `tests/test_api.py tests/test_restart_inbox.py tests/test_routes_surface.py tests/test_undelivered.py tests/test_voice_input.py tests/test_bug_report_notify.py` → **157 passed** (every test file that drives the lifespan through `TestClient(app)`)

## Pre-mortem

| Scenario | Check |
|---|---|
| Production bridge dies after this merge | `test_live_service_environment_passes_the_guard` replays the measured live env (`LISTEN_PID=2577299`, pid 2577299) and asserts the guard returns `None`; the permitting arm asserts `start_bridge` reaches its body. **This row was insufficient as first written** — the tests pin the live *process* environment, and nothing in them would have caught the tracked unit's `uv run` form producing that environment differently (H1). Config the tests cannot see is the residual hole; the comments in `deploy/orchestra.service` and the guard docstring are what carries it |
| `POST /api/restart` leaves a stale `LISTEN_PID` and the bridge never comes back | Restart goes through `systemctl restart`, so systemd re-exec's and re-assigns `LISTEN_PID`. `grep -rn "execv\|execl" app/ --include=*.py` finds self-exec only in `app/pidfd_exec.py`, a child-spawn helper — the app never re-execs itself |
| Existing suite starts failing because something calls the real `start_bridge` | 356 tests across the bridge, startup and lifespan files, all green; the only unmocked caller is the new test file |
| Refusal takes HTTP down with it | The raise happens inside a background task caught by `_start_bridge_background`; `test_startup_bridge.py` (already covering a raising `start_bridge`) is green |
| A test instance reaches Telegram by some other door | `TG_BRIDGE_TOKEN` has exactly one reader and both `Bot(token=…)` calls are inside `start_bridge`, downstream of the guard; with `bot` left `None` every outgoing path no-ops |

## Review route

**`review route unavailable`.** The gate selects a mandatory Sol pass — the risk floor fires
twice (shared message-delivery path; a lifecycle/admission gate whose bypass disables the
control), and size does not lower that floor. The oracle is explicitly weak: I wrote the test
after the implementation, so it is not an independent deterministic oracle.

The call was refused before reaching the reviewer:
`weekly_quota_blocked: Codex weekly quota is 98% (threshold 95%). Available provider: Claude,
Codex Spark.` Luna shares the Codex runtime and is blocked identically; Spark is forbidden for
review by policy. **Rounds spent: 0** (no reviewer output — a route refusal, not an attempt).

Author is Claude/Opus, so a Sol pass would also have been the cross-family review. An Opus
reviewer needs a fresh session from a spawn-capable parent, which a terminal worker cannot
start — the handoff goes to the orchestrator. Until then: **cross-family verdict unavailable.**

### Adversarial self-review (substitute for the review, not equivalent to it)

Every claim below was checked by command, not by reading the diff.

- **Is `start_bridge` the only seam?** `grep -rn "TG_BRIDGE_TOKEN" app/` → one functional read
  (`app/tg_bridge.py:3786`), the rest are the comment, a log string and the `__main__` argv
  assignment. `grep -rn "Bot(token=" app/` → `3817` and `3820`, both inside `start_bridge`
  downstream of the guard. With `bot` left `None`, every outgoing path no-ops.
- **Does raising early strand the wired callbacks?** It skips the assignment of
  `session.on_scope_idle`, `session.on_scope_running` and `manager.tg_topics_remover`. All three
  consumers already guard against the unassigned state: `app/session.py:2728`
  (`if on_scope_idle is None: return`), `:2736` (same for `on_scope_running`),
  `app/manager.py:1419` (`if delete_tg_topics and orch_names and self.tg_topics_remover`), and
  the module-level defaults at `app/session.py:3529-3530` are `None`. Leaving them unwired in a
  refused instance is also the correct behaviour — those callbacks push to Telegram.
- **Can `POST /api/restart` strand a stale `LISTEN_PID`?** No. `_do_restart_service` ends with
  `os.kill(os.getpid(), signal.SIGINT)` (`app/routes/system.py:2113`); the process exits and
  systemd's `Restart=always` starts a new one, so `LISTEN_PID` is re-assigned by systemd.
  `grep -rn "execv\|execl" app/ --include=*.py` finds self-exec only in `app/pidfd_exec.py`, a
  child-spawn helper — the app never re-execs itself.

**Open question I could not close alone, and the reason the handoff matters:** the guard makes
the production bridge depend on socket activation. If the unit is ever changed away from
`--fd 3` / `Requires=orchestra.socket`, the bridge stops — loudly in the log, but the user finds
out by his Telegram going quiet. That trade was taken deliberately (it is the only measured
non-inheritable signal), but it is exactly the kind of call a second opinion exists for.

### Outcome of the handoff

The orchestrator ran an independent Opus reviewer (`review324`,
`docs/tasks/324/opus-review.md`, `db36cfb1`). Verdict **APPROVED WITH SUGGESTIONS**. Still not
cross-family — author and reviewer are both Claude/Opus, Codex was at 98%; the family confound
is named, not removed.

And the open question above was the right one to hand over: it is exactly where the review found
something. Not the runtime behaviour — that direction came back confirmed — but the configuration
the guard silently depends on (H1 above). Confirmed by the reviewer, not by me:

- **Direction 1 (can a non-canonical instance still reach Telegram?)** — confirmed by count, and
  extended past what I checked: no raw HTTP client to the Bot API anywhere, 8 `bot is None` guards
  on the send paths, and the worktree instance writes to its own SQLite (`ORCHESTRA_DB_PATH`
  unset, default path is relative to the code) so it cannot corrupt production delivery state.
- **Direction 2 (false refusal of the live process)** — no path found; `LISTEN_PID` survives to
  `start_bridge` (nothing in the runtime's site-packages or `app/` mutates it), and
  `app/fdstore.py:92-94` already ships the identical predicate and works in production.
- **Oracle not vacuous** — the reviewer added the mutation I had not: `return None` →
  `return "MUTANT: always refuse"`, i.e. a guard nailed shut, the defect that kills the
  production bridge. 2 failed, caught by the permitting arm.

Findings taken: H1 and S2 (both applied above). S3 (a positive "token set but `TG bridge: ready`
never arrived" signal surfaced where the user actually looks, since the journal is not his
channel) is deliberately **not** in this commit — the orchestrator is filing it separately; it is
about the failure being observable, not about the gate. N1 (the same predicate now lives in
`app/fdstore.py:92-94` and here) left as a nit: if the signal ever changes, both must change.

## Behaviour change worth naming

`python -m app.tg_bridge <token> <group>` — the standalone runner at the bottom of the module —
could not succeed under any invocation once the guard existed: it always went through
`start_bridge`, and a hand-started process never has `LISTEN_PID == os.getpid()`. I had first
left it in place as "documentation of the refusal"; on review (S2) that is a door guaranteed to
return a traceback, and the project rule is to delete what your own change orphaned. **Removed**
(`app/tg_bridge.py`, 14 lines). Checked first that nothing invokes it: `import sys` and all four
`sys.` uses were local to the block, and no script, unit or doc calls `python -m app.tg_bridge`.

## Deployment installs (`deploy/install.sh`)

Second edge of H1: `install.sh:86` installs `orchestra.service.template`, whose ExecStart is
`--host 127.0.0.1 --port 8888` with no socket activation at all, while `install.sh:128` invited
the operator to set `TG_BRIDGE_TOKEN`. On such an installation the bridge can never start.

**Decision: stop advertising it, rather than give the template socket activation** — the tracked
`deploy/orchestra.socket` is `ListenStream=0.0.0.0:8888`, and shipping it onto a client VPS whose
nginx proxies `127.0.0.1:8888` would expose the dashboard port on every interface, a security
regression I cannot test from here. The step now states plainly that this template cannot run the
bridge and what it would take (socket unit + direct-exec `--fd 3`), so nobody sets a token and
waits for a bridge that will not come. `bash -n` clean.

**For the owner of the client VPS, after rollout:** check whether a TG bridge is configured
there (`grep TG_BRIDGE_TOKEN /opt/orchestra/.env`) and whether its unit exec's the interpreter
directly. If a token is set on an `install.sh`-style unit, this change turns a working bridge
into a refusing one — for that host it is blocking, not a suggestion. The reviewer had no access
to that host and neither do I; it is unverified either way.

## Found, not fixed

The token is still sitting in 22 worktree `.env` copies (`.env` is out of scope here by
instruction). This change removes the way that token gets used by accident, not the copies. If
the copies themselves should stop carrying it, that is a separate task against the spawn-time
`.env` copy.
