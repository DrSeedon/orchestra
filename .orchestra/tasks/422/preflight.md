# #422 activation/replay preflight

Date: 2026-08-31. No model inference was made. No catalog/flag state was changed.

## Live RED baseline

Both production-reading checks printed the invariant before failing on their own seams:

```text
T1: PRODUCTION_SESSIONS_BEFORE=572 PRODUCTION_SESSIONS_AFTER=572
AssertionError: T1 catalog cache is empty

T2: PRODUCTION_SESSIONS_BEFORE=572 PRODUCTION_SESSIONS_AFTER=572
AssertionError: T2 live harness canary session is missing
```

T3 and T4 fail independently:

```text
AssertionError: T3 replay summary is missing
AssertionError: T4 report.md is missing
```

## Isolation arms

### Rejected: user `systemd-run`

The local probe entered a transient user unit but the requested isolation properties did not
protect the process:

```text
local-ok
NETWORK_ESCAPE
MAIN_ENV_READABLE
```

The orchestrator independently ran the production-shaped control and got the stronger failure:

```text
Failed to connect to user scope bus — $DBUS_SESSION_BUS_ADDRESS and $XDG_RUNTIME_DIR not defined
```

Therefore `systemd-run --user` is not an eligible sandbox in this environment. A worktree-local
process inheriting `.env` can read the production OpenRouter key and every other live credential;
this is the same failure class as the 16–18.08 duplicate Telegram clients started from worktrees.

### Accepted: bubblewrap

Command shape:

```text
bwrap --unshare-net --ro-bind / / --dev /dev --proc /proc /bin/sh -lc '<network probe>'
```

Observed:

```text
NETWORK_DENIED
bwrap_rc=0
```

The replay runner must additionally avoid `--ro-bind / /`: it will expose only the scratch clone,
runtime libraries and a read-only venv, hide the production repository/database/home, clear the
environment, set `MCP={}`, and pass `OPENROUTER_API_KEY` directly to the controller object only.

## Real-money boundary

The key belongs to a historically paid OpenRouter account. The runner may read exactly
`OPENROUTER_API_KEY` into controller memory; it must not source or forward the rest of `.env`.
Every metadata row and every request model must end in exact `:free`. Any observed paid or
unsuffixed route is a hard stop, not a scored run. `app.harness.llm.MAX_RETRIES=1` means one HTTP
attempt and zero retries.

