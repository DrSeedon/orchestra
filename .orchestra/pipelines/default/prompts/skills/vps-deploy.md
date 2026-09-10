---
name: vps-deploy
description: Deploy Orchestra to its VPS via git pull and systemd restart. Use only when the active user request explicitly commands that exact VPS/production deploy or restart; merged fixes, production drift, or urgency do not trigger it.
---

# VPS Deploy

Update Orchestra on production VPS.

## Authorization gate
This skill provides a procedure, never permission. Before any SSH or external mutation, verify
that the active user request explicitly authorizes this exact VPS deploy/restart. Otherwise STOP
without SSH; merged fixes, stale production, urgency, or passing tests never authorize a deploy.

## Procedure

### 1. Check that main is clean
```bash
git status
git log --oneline -3
```
Make sure needed commits are in main and pushed to GitHub.

### 2. Update code on VPS
```bash
ssh root@<VPS_IP> \
  "sudo -u kesha git -C /home/kesha/orchestra pull --ff-only origin main"
```

### 3. Restart the service
```bash
ssh root@<VPS_IP> "systemctl restart orchestra"
```
`uv sync` runs automatically via `ExecStartPre` — dependencies install themselves.

### 4. Verify it's running
```bash
ssh root@<VPS_IP> "sleep 3 && systemctl status orchestra --no-pager | head -8"
curl -s --max-time 10 -o /dev/null -w '%{http_code}' https://orc.seedon.ru
```
Expected: `active (running)` + HTTP 302 (redirect to login).

### 5. If it crashed — diagnose
```bash
ssh root@<VPS_IP> "journalctl -u orchestra -n 30 --no-pager"
```

## Rules
- **Do NOT deploy** while a worker is actively fixing something — wait for DONE
- **Do NOT deploy** untested code — run tests locally first
- **Always verify** that the service started after restart
- Read `~/.claude/docs/vps-registry.md` before connecting; it is the source of truth for the host.
- Zahoron is an archived client contour. Never deploy, update, or restart it from this skill.
- On `ModuleNotFoundError`, diagnose the pinned interpreter from the effective unit; do not run an unpinned `uv sync` in production.

## VPS parameters
- Host: `root@<VPS_IP>` (Contabo) — the address itself is not published in this repository; take it from the registry above or ask the owner.
- Path: `/home/kesha/orchestra`
- Service: `orchestra.service`
- URL: `https://orc.seedon.ru`
- User: `kesha` (systemd)
