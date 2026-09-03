# Deploy Notes — Amsterdam VPS

## Git pull — NEVER as root
`git pull` must be done as the `orchestra` user, not root.
Root-owned `.git/` breaks all worktree operations for agent sessions.

```bash
# CORRECT:
sudo -u orchestra git pull

# WRONG (breaks everything):
sudo git pull
```

If already broken:
```bash
sudo chown -R orchestra:orchestra /opt/orchestra/.git
```

## Systemd service
Consider adding to `orchestra.service`:
```ini
[Service]
ExecStartPre=/usr/bin/chown -R orchestra:orchestra /opt/orchestra/.git
```
