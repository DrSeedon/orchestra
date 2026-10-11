---
name: vps-deploy
description: Deploy or restart the Orchestra service on its VPS, or update the owner's laptop checkout. Use only after the owner explicitly authorizes that exact deployment or restart.
---

# Orchestra deployment

owner decision, 2026-10-11: document the current origin-only update and controlled restart flow because the previous unversioned copy targeted an obsolete root SSH path and deployment procedure.

This skill describes operations; it does not grant permission. Before connecting or changing a checkout or service, the active user request must explicitly authorize the exact target and action. A merge, stale VPS, passing tests, urgency, or this skill alone is not authorization. Never restart, stop, or deploy Orchestra on your own. If Python changes need a restart and the owner did not authorize it, report that requirement and stop before the restart.

Use only the current project deployment inventory. The VPS loopback SSH target below is not a pattern for guessing or substituting a host. Do not put an IP, credential, or alternate remote in prompts or logs.

## VPS update

Confirm the authorized change is committed and pushed to the public `origin` main branch. On the VPS, inspect the working tree and remotes; preserve any local changes and do not touch other remotes. Update only by fast-forward from `origin`:

```sh
git -C /home/kesha/orchestra status --short --branch
git -C /home/kesha/orchestra remote -v
git -C /home/kesha/orchestra fetch origin
git -C /home/kesha/orchestra merge --ff-only origin/main
```

Run these commands as `kesha` through the local SSH route when operating from the VPS control environment:

```sh
ssh -o BatchMode=yes kesha@localhost 'git -C /home/kesha/orchestra fetch origin && git -C /home/kesha/orchestra merge --ff-only origin/main'
```

If the worktree is dirty, a remote differs from the authorized origin, or fast-forward fails, stop and report the observed state. Do not reset, stash, force, pull from another remote, or deploy untested code.

## VPS restart

Restart only when the active owner command explicitly authorizes this Orchestra VPS restart. The command below schedules the restart a few seconds after SSH exits so the connection can return:

Before submitting it, record the current `MainPID` for comparison.

```sh
ssh -o BatchMode=yes kesha@localhost 'nohup sh -c "sleep 5; sudo systemctl restart orchestra" >/tmp/orchestra-restart.log 2>&1 </dev/null &'
```

After starting it, create a durable timer with `bg_create(type="timer", delay_seconds=10, message="Verify the authorized Orchestra restart")` and end the turn; do not sleep or poll. When the timer wakes the task, verify the service rather than treating the command submission as success:

- `systemctl is-active orchestra` reports `active`; record `MainPID` and confirm it is a new process.
- `curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8888/` returns `302`.
- Inspect the service journal from the restart for startup errors.
- Verify effective `MemoryHigh=14G` and `MemoryMax=16G` through systemd, then read `memory.high` and `memory.max` in the service's actual cgroup (resolve its path from `ControlGroup`; do not assume a historical path).
- Inspect restart recovery: identify any `cut_names`, confirm the corresponding workers have been restored, and verify background jobs were restored.

If a check fails, report the concrete result. Do not issue another restart unless the owner explicitly authorizes that additional restart.

## Owner's laptop

Use this route only when the owner explicitly authorizes updating the laptop checkout. Identify the exact local Orchestra process and checkout from current state; do not use a broad `pkill` or a saved PID. Send `kill -TERM <verified-pid>` first. If that exact process remains, use the owner's polkit-authorized `kill -INT <verified-pid>` escalation. Do not use `sudo` or target another process. Update the intended checkout only from its configured `origin` with `git fetch origin` followed by `git merge --ff-only origin/main`; preserve dirty changes and stop if fast-forward is unavailable.
