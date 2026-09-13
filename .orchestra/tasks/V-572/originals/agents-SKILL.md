---
name: laptop-access
description: Access the owner's laptop from the VPS through its reverse SSH tunnel for repository synchronization, commands, files, and diagnostics. Use when asked to work on the laptop or sync laptop and VPS copies.
---

# Laptop access

Adapted from `/home/kesha/.claude/skills/laptop-access/SKILL.md` for Codex. The connection below was verified on 2026-09-12.

The laptop establishes a reverse SSH tunnel to VPS loopback port 2222. Use laptop user `maxim`, not VPS user `kesha`, and the dedicated key:

```bash
ssh -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5 -p 2222 maxim@127.0.0.1 'hostname; pwd'
```

Verified laptop hostname: `maxim-911aird`. Tailscale and an SSH host alias are not required. A public-key rejection does not prove the tunnel is down: check the username and identity first. Use `ss -ltnp` to inspect the listener. Refusal or timeout alone does not establish whether the laptop is asleep, offline, or the tunnel has failed.

If `run_on_laptop` is available, it is an alternative with its own tool constraints. Direct SSH works in Codex without that connector. Do not bypass a connector's policy restrictions using another interpreter.

## Paths

- Laptop Python projects: `/mnt/data/Projects/Python/`.
- DnD laptop checkout: `/mnt/data/Projects/Python/Claude-Code-Game-Master`.
- DnD VPS checkout: `/home/kesha/projects/dnd-game-master`.
- Laptop Unity projects: `/mnt/data/Projects/Unity/`.
- Laptop vault: `/mnt/data/Рабочий стол/Cursor/COG-second-brain` (historical Claude skill evidence; verify existence before using).
- Orchestra runs on the VPS. Its laptop checkout is not the live service.

Verify the target path, remote, branch, and working changes on both machines before synchronizing. Preserve uncommitted work. When the user authorizes committing all project changes and syncing, inspect the changes, commit the intended files, fetch, integrate without discarding either side, and push. Verify both checkouts against the same remote commit. Git synchronization does not authorize service restart or deployment.

Use the current runtime's server-side background-job mechanism for long commands. Do not use obsolete `run_in_background` instructions from the Claude source. Do not launch another agent or change unrelated projects merely to obtain access.
