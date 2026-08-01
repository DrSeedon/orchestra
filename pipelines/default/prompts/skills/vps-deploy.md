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
ssh -o StrictHostKeyChecking=no root@orchestra.zahoron.ru "cd /opt/orchestra && git pull origin main"
```

### 3. Restart the service
```bash
ssh -o StrictHostKeyChecking=no root@orchestra.zahoron.ru "systemctl restart orchestra"
```
`uv sync` runs automatically via `ExecStartPre` — dependencies install themselves.

### 4. Verify it's running
```bash
ssh -o StrictHostKeyChecking=no root@orchestra.zahoron.ru "sleep 3 && systemctl status orchestra --no-pager | head -8"
curl -s --max-time 10 -o /dev/null -w '%{http_code}' https://orchestra.zahoron.ru
```
Expected: `active (running)` + HTTP 302 (redirect to login).

### 5. If it crashed — diagnose
```bash
ssh -o StrictHostKeyChecking=no root@orchestra.zahoron.ru "journalctl -u orchestra -n 30 --no-pager"
```

## Rules
- **Do NOT deploy** while a worker is actively fixing something — wait for DONE
- **Do NOT deploy** untested code — run tests locally first
- **Always verify** that the service started after restart
- On `ModuleNotFoundError` — `uv sync` should fix it (it's in ExecStartPre). If not — `ssh root@orchestra.zahoron.ru "cd /opt/orchestra && uv sync"`

## VPS parameters
- Host: `root@orchestra.zahoron.ru`
- Path: `/opt/orchestra`
- Service: `orchestra.service`
- URL: `https://orchestra.zahoron.ru`
- User: `orchestra` (systemd)
