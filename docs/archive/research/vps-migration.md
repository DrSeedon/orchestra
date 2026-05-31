# VPS Migration Research — Orchestra to 24/7 Server

**Date**: 2026-05-18
**Status**: Research / Planning
**Author**: feat-vps-migration worker

---

## 1. Current State Audit

### 1.1 What's Running (Laptop)

| Component | Port | RAM | Disk | Notes |
|---|---|---|---|---|
| Orchestra (FastAPI + uvicorn) | 8888 | ~100MB | 68MB DB + 844MB uploads | systemd `orchestra` |
| Claude Code CLI (per session) | — | ~290MB each | — | 4 active = ~1.2GB |
| MCP servers (per CLI) | — | ~60MB each | — | websearch, yougile, serena etc. |
| TG Local Bot API | 8081 | ~20MB | 13MB data | systemd `telegram-bot-api` |
| Hiddify VPN proxy | 12334 | ~50MB | — | Required from Russia for Anthropic API |
| Codex CLI | — | ~100MB | — | On-demand, not persistent |

**Total peak RAM**: ~2.5GB (4 active Claude CLIs + MCP servers + Orchestra + TG bot)
**Total disk**: ~15GB (Orchestra repo + worktrees + data)

### 1.2 Hardcoded Paths in Codebase

Found in `app/`:
- `/home/maxim/.local/bin/claude` — fallback CLI path (backend_claude.py:85)
- `/home/maxim/.npm-global/bin/codex` — fallback Codex path (backend_codex.py:14)
- `/mnt/data/Projects/Python` — project roots (main.py:120-122)
- `/mnt/data/Projects/Python/Parsing` — GitHub webhook mapping (main.py:988-992)
- `http://127.0.0.1:12334` — Hiddify proxy (backend_claude.py:92, systemd service)

### 1.3 Authentication

- **Claude Code**: OAuth credentials in `~/.claude/.credentials.json` (471 bytes)
- **Codex CLI**: Auth in `~/.codex/auth.json` (4.5KB)
- **TG Bot**: Token in `.env` (hardcoded, portable)
- **Git**: SSH key for GitHub (`~/.ssh/`)

---

## 2. Claude Code on VPS — The Critical Question

### 2.1 Can It Run Headless?

**Yes, but with caveats.**

- CLI runs fine without display, uses `-p` flag or `--output-format stream-json` (which Orchestra already uses)
- No browser needed for operation, only for initial auth
- Minimum 4GB RAM recommended

### 2.2 Authentication Methods (Priority Order)

| # | Method | Headless? | Subscription? | Notes |
|---|---|---|---|---|
| 1 | `CLAUDE_CODE_USE_BEDROCK` | ✅ | No (API) | AWS Bedrock, separate billing |
| 2 | `ANTHROPIC_AUTH_TOKEN` | ✅ | No (API) | LLM gateway |
| 3 | `ANTHROPIC_API_KEY` | ✅ | No (API) | Console account, pay-per-use |
| 4 | `apiKeyHelper` script | ✅ | Depends | Custom script returns key |
| 5 | `CLAUDE_CODE_OAUTH_TOKEN` via `claude setup-token` | ✅ | **Yes (Max)** | **1-year token, no refresh needed** |
| 6 | OAuth `/login` flow | ❌ | Yes (Max) | Requires browser |

### 2.3 Recommended: `claude setup-token`

```bash
# On laptop (has browser):
claude setup-token
# → Outputs: sk-ant-oat01-...  (valid 1 year)

# On VPS:
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..."
```

Also create `~/.claude.json`:
```json
{"hasCompletedOnboarding": true}
```

### 2.4 CRITICAL BUGS to Watch

| Issue | Severity | Impact | Status |
|---|---|---|---|
| [#47754](https://github.com/anthropics/claude-code/issues/47754) | 🔴 CRITICAL | **Cloudflare WAF blocks OAuth refresh from VPS IPs** (datacenter ranges). Token refresh → 403. Users locked out for 26+ days | Open, unresolved |
| [#28827](https://github.com/anthropics/claude-code/issues/28827) | 🟡 HIGH | OAuth token refresh fails in `-p` mode (non-interactive). Access token lives ~10-15 min | Closed as dup |
| [#21765](https://github.com/anthropics/claude-code/issues/21765) | 🟡 HIGH | Copying credentials.json to another machine → refresh fails | Closed as "not planned" |

**Mitigation**: `setup-token` generates a 1-year token that doesn't need refreshing. This bypasses ALL three bugs above. But if the token expires or gets revoked, you need laptop access to regenerate.

### 2.5 SDK Billing Change (June 15, 2026)

Starting June 15, Agent SDK and `claude -p` get **separate monthly credit**:
- Max 20x ($200/mo): $200 SDK credit
- Credit doesn't roll over. After exhaustion: extra usage billing at API prices (if enabled)

**Impact**: Orchestra uses SDK exclusively. The $200/mo credit should be sufficient (currently using ~$50-80/mo equivalent), but needs monitoring.

### 2.6 Rate Limits

- **Per-account, NOT per-IP** — VPS won't change limits
- Max 20x: ~220k tokens per 5-hour window
- Same whether from Russia via proxy or from NL VPS directly

---

## 3. VPS Requirements

### 3.1 RAM Calculation

| Scenario | RAM Needed |
|---|---|
| Orchestra server | 100MB |
| 1 orchestrator session (Claude CLI + MCP) | ~350MB |
| 1 worker session (Claude CLI + MCP) | ~350MB |
| Idle sessions (hibernated) | ~0 (no process) |
| TG Local Bot API | 20MB |
| OS + systemd | 300MB |
| **Minimum** (1 orch + 1 worker) | **~1.1GB** |
| **Comfortable** (1 orch + 3 workers) | **~2.0GB** |
| **Peak** (2 orch + 5 workers) | **~3.5GB** |

**Recommendation**: **4GB RAM minimum, 8GB preferred**

Orchestra hibernates idle sessions (kills process, preserves context). At steady state, usually 2-4 active sessions. Swap helps absorb peaks.

### 3.2 CPU

- Claude CLI is **I/O bound** (waiting for API responses)
- Minimal CPU usage during operation
- **2 vCPU sufficient**, 4 vCPU comfortable

### 3.3 Disk

| Component | Size | Notes |
|---|---|---|
| Orchestra repo + .venv | ~500MB | `git clone` from GitHub |
| Worktrees (active) | ~500MB each × 15 | But can be recreated on demand |
| SQLite DB | 68MB | Copy from laptop |
| Uploads | 844MB | Copy from laptop |
| Claude CLI + .claude/ | ~500MB | npm install |
| Codex CLI + .codex/ | ~200MB | npm install |
| MCP servers | ~300MB | websearch, yougile, pandoc |
| Other project repos | varies | Clone from GitHub as needed |
| OS + packages | ~3GB | Ubuntu 24.04 |
| **Total minimum** | **~10GB** |
| **Comfortable** | **~40GB** (room for worktrees, logs, growth) |

### 3.4 Network

- **Latency to Anthropic API**: VPS in NL gets 47ms (vs 460ms from laptop via proxy). **10x faster!**
- **No proxy needed** from NL VPS — direct access to api.anthropic.com
- Low bandwidth (~10-50KB/s per session, text only)

---

## 4. VPS Options

### 4.1 Existing VPS (VPS_IP)

| Spec | Value | Verdict |
|---|---|---|
| CPU | 2 vCPU AMD EPYC | ✅ Sufficient |
| RAM | 3.8GB total, 2.7GB available | ⚠️ Tight (peak needs 3.5GB, only 2.7GB free) |
| Disk | 38GB total, 18GB free | ⚠️ Tight (need 10-40GB) |
| Location | NL | ✅ Great for Anthropic API |
| OS | Ubuntu 24.04 | ✅ Perfect |
| Running services | 32 (parsing-hub, seo-platform, victor, zahoron, etc.) | ⚠️ Already loaded |
| Provider | Unknown (QEMU/KVM, likely Hetzner or local provider) | — |

**Verdict**: ❌ **Too tight**. RAM barely fits, disk is marginal. Adding Orchestra + 5 Claude CLIs would compete with existing services. Risk of OOM kills.

### 4.2 Upgrade Existing VPS

If provider allows: bump to 8GB RAM + 80GB disk. Cost likely €15-25/mo instead of current plan.

**Pros**: No new server, existing services stay, familiar setup
**Cons**: All eggs in one basket, migration still needed

### 4.3 New Dedicated VPS — Hetzner Cloud

| Plan | vCPU | RAM | Disk | Price | Notes |
|---|---|---|---|---|---|
| CX22 | 2 | 4GB | 40GB | €4.35/mo | Minimum viable |
| CX32 | 4 | 8GB | 80GB | €7.49/mo | **Recommended** |
| CX42 | 8 | 16GB | 160GB | €15.49/mo | Overkill (for now) |

Location: `nbg1` (Nuremberg) or `fsn1` (Falkenstein) — both in DE/EU, low latency to Anthropic.

**Recommendation**: **Hetzner CX32** (4 vCPU, 8GB RAM, 80GB SSD) at **€7.49/mo** (~600₽/mo).

### 4.4 DigitalOcean

| Plan | vCPU | RAM | Disk | Price |
|---|---|---|---|---|
| Basic 4GB | 2 | 4GB | 80GB | $24/mo |
| Basic 8GB | 4 | 8GB | 160GB | $48/mo |

Much more expensive than Hetzner for same specs. No advantage.

---

## 5. Migration Plan

### Phase 0: Preparation (laptop, 30 min)

1. Generate `claude setup-token` → save token securely
2. Export Codex auth: copy `~/.codex/auth.json`
3. Backup Orchestra DB: `sqlite3 data/orchestra.db ".backup data/orchestra.db.migration"`
4. Push all branches to GitHub: `git push --all origin`
5. Document all .env variables

### Phase 1: VPS Setup (VPS, 1 hour)

```bash
# 1. Create Hetzner CX32
# 2. SSH in, initial setup
apt update && apt upgrade -y
adduser maxim
usermod -aG sudo maxim

# 3. Install dependencies
apt install -y git python3.12 python3.12-venv nodejs npm sqlite3 nginx certbot

# 4. Install Claude Code CLI
npm install -g @anthropic-ai/claude-code

# 5. Configure Claude auth
mkdir -p ~/.claude
echo '{"hasCompletedOnboarding": true}' > ~/.claude.json
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..."

# 6. Install Codex CLI
npm install -g @openai/codex
mkdir -p ~/.codex
# Copy auth.json from laptop

# 7. Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 8. Clone Orchestra repo
git clone git@github.com:DrSeedon/orchestra.git /opt/orchestra
cd /opt/orchestra && uv sync

# 9. SSH key for GitHub
ssh-keygen -t ed25519
# Add to GitHub deploy keys
```

### Phase 2: Data Migration (30 min)

```bash
# From laptop:
rsync -avz data/orchestra.db maxim@vps:/opt/orchestra/data/
rsync -avz data/uploads/ maxim@vps:/opt/orchestra/data/uploads/
rsync -avz .env maxim@vps:/opt/orchestra/.env

# Recreate worktrees on VPS (they clone from same repo, don't need transfer)
# Orchestra auto-creates worktrees on spawn
```

### Phase 3: Code Adjustments

**Paths to update** (make configurable via env vars or detect automatically):

1. `backend_claude.py:85` — CLI path (use `shutil.which("claude")` only, remove hardcoded fallback)
2. `backend_codex.py:14` — Codex path (same)
3. `backend_claude.py:92` — Proxy env vars (make conditional: only set if `HTTPS_PROXY` is defined in env)
4. `main.py:120-122` — Project scan roots (move to config/env)
5. `main.py:988-992` — GitHub webhook repo mapping (move to config)

**New approach**: Use `ORCHESTRA_HOME=/opt/orchestra` as base, derive paths from it.

### Phase 4: Services Setup (VPS, 30 min)

```ini
# /etc/systemd/system/orchestra.service
[Unit]
Description=Orchestra — AI Agent Orchestrator
After=network.target

[Service]
Type=simple
User=maxim
WorkingDirectory=/opt/orchestra
ExecStart=/opt/orchestra/.venv/bin/python3 -u -m uvicorn app.main:app --host 127.0.0.1 --port 8888
Restart=always
RestartSec=5
Environment=PATH=/home/maxim/.local/bin:/home/maxim/.npm-global/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/maxim
Environment=CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
# NO proxy needed from NL VPS!

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/telegram-bot-api.service
[Unit]
Description=Telegram Bot API Server
After=network.target

[Service]
ExecStart=/usr/local/bin/telegram-bot-api --api-id=25265946 --api-hash=d8d278257ef11f9e1f4595d78f1e6f3a --local --http-port=8081 --dir=/opt/orchestra/data/tg-bot-api
Restart=always
User=maxim

[Install]
WantedBy=multi-user.target
```

### Phase 5: Nginx + SSL (30 min)

```nginx
server {
    server_name orchestra.yourdomain.com;
    
    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;  # Important for SSE
        proxy_cache off;
        
        # Basic auth for security
        auth_basic "Orchestra";
        auth_basic_user_file /etc/nginx/.htpasswd;
    }
    
    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/orchestra.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/orchestra.yourdomain.com/privkey.pem;
}
```

### Phase 6: MCP Servers (30 min)

| MCP Server | Migration | Notes |
|---|---|---|
| orchestra | Comes with repo | Just set env vars |
| websearch | Clone + npm install | `~/.claude/mcp-servers/websearch/` |
| pandoc | Install pandoc binary | `apt install pandoc` |
| yougile | Clone + pip install | Project management API |
| serena | pip install serena | LSP server |
| kwin | ❌ Skip | Desktop-only, irrelevant on VPS |

### Phase 7: Smoke Test (30 min)

1. Start Orchestra: `sudo systemctl start orchestra`
2. Open dashboard via nginx
3. Send message to orchestrator via TG
4. Spawn a test worker
5. Verify worker can:
   - Run Claude CLI (auth works)
   - Access GitHub (SSH)
   - Create worktrees
   - Run MCP servers
6. Verify Codex review works

### Phase 8: Cutover (15 min)

1. Stop Orchestra on laptop
2. Final DB sync: `rsync data/orchestra.db` (get latest sessions)
3. Start Orchestra on VPS
4. Update TG bot webhook (if needed — aiogram polls, so just restart)
5. Verify all sessions resume

---

## 6. Proxy Situation

### Current (Laptop in Russia)
- **Must use** Hiddify VPN proxy (127.0.0.1:12334) for Anthropic API
- Adds ~400ms latency per request
- Proxy can be flaky

### On VPS (NL/DE)
- **No proxy needed!** Direct access to api.anthropic.com
- Latency: ~47ms (vs 460ms via proxy from Russia)
- More reliable, simpler setup
- **Remove all proxy env vars** from systemd services and .env

### Telegram Bot API
- On existing VPS (NL), TG API works directly
- May need VPN proxy only if VPS IP gets blocked by Telegram (unlikely in NL)
- Local Bot API server works same way anywhere

---

## 7. Risks & Mitigations

### 7.1 Auth Token Expiry

**Risk**: `setup-token` expires after 1 year. If something revokes it earlier, no way to refresh from VPS.
**Mitigation**: 
- Set calendar reminder for token renewal (May 2027)
- Keep laptop ready for `claude setup-token` regeneration
- Monitor for 401 errors in logs
- Consider `ANTHROPIC_API_KEY` as backup (but costs real money, not subscription)

### 7.2 Cloudflare WAF Blocking

**Risk**: [#47754] — Cloudflare may block even `setup-token` requests from datacenter IPs.
**Mitigation**: 
- `setup-token` doesn't need refresh (1-year validity), so WAF refresh-blocking is irrelevant
- If initial auth fails from VPS, authenticate from laptop, transfer token
- Test auth from VPS IP BEFORE committing to migration

### 7.3 Session Loss During Migration

**Risk**: Active sessions can't be transferred between machines.
**Mitigation**:
- Schedule migration during low-activity period (night/weekend)
- Kill all active sessions before migration
- Sessions will auto-recreate on first message (new conversation)
- Historical logs are in SQLite DB (transferred)

### 7.4 Disk Space Exhaustion

**Risk**: Worktrees + uploads + logs grow over time.
**Mitigation**:
- 80GB on Hetzner CX32 is 8x current usage
- Orchestra already auto-cleans worktrees on session kill
- Set up log rotation
- Monitor disk usage (cron job)

### 7.5 Can Run Both Temporarily?

**Yes!** During testing:
- Laptop Orchestra stays on, handles production
- VPS Orchestra runs on different port, test-only
- Once verified, cutover: stop laptop, switch TG bot to VPS
- **Rollback**: just restart laptop Orchestra, 2 minutes

### 7.6 Other Projects

**Risk**: Orchestra manages workers for multiple projects (Parsing, seedon-site, etc.). Those repos need to exist on VPS.
**Mitigation**:
- Clone all needed repos on VPS: `git clone` from GitHub
- Update path mappings in Orchestra config
- Some projects may need their own dependencies installed

---

## 8. Alternative: Keep Laptop, Expose via Tunnel

### Option A: SSH Reverse Tunnel

```bash
# From laptop, expose dashboard to internet:
ssh -R 8888:localhost:8888 user@vps
```

**Pros**: No migration, keep everything as-is
**Cons**: Tunnel breaks on laptop sleep/reboot, not 24/7, adds latency

### Option B: Cloudflare Tunnel

```bash
cloudflared tunnel --url http://localhost:8888
```

**Pros**: Zero-config HTTPS, survives IP changes
**Cons**: Still depends on laptop being on, not 24/7, Claude CLI latency through proxy

### Option C: WireGuard VPN between laptop and VPS

**Pros**: Secure, fast, can access laptop services from VPS
**Cons**: Still depends on laptop, complex setup, not solving the core problem

### Verdict on Alternatives

**All alternatives fail the core requirement**: 24/7 availability. Laptop sleeps, reboots, travels. VPS is the only path to actual 24/7.

---

## 9. Recommended Approach

### Short Version

1. **Buy Hetzner CX32** (8GB RAM, 80GB SSD, €7.49/mo)
2. **Use `claude setup-token`** for auth (1-year token, no refresh headaches)
3. **Remove proxy** (VPS in EU = direct Anthropic API access, 10x faster)
4. **Migrate Orchestra + DB + uploads** via rsync
5. **Clone project repos** from GitHub (don't rsync 188GB of local files)
6. **Recreate worktrees** on demand (auto-created by Orchestra)
7. **Run parallel** for 1-2 days (laptop + VPS), then cutover

### Estimated Timeline

| Phase | Duration | Notes |
|---|---|---|
| VPS purchase + OS setup | 1 hour | Hetzner instant provisioning |
| Dependencies + auth | 1 hour | Node, Python, Claude, Codex |
| Code adjustments (paths, proxy) | 2 hours | Make paths configurable |
| Data migration | 30 min | rsync DB + uploads |
| Services + nginx | 1 hour | systemd + SSL |
| MCP servers | 30 min | websearch, yougile, pandoc |
| Testing | 2 hours | Full smoke test |
| Parallel run | 1-2 days | Verify stability |
| Cutover | 15 min | Stop laptop, final sync |
| **Total** | **~1-2 days** | Including parallel run |

### Monthly Cost

- Hetzner CX32: **€7.49/mo** (~600₽)
- Domain (optional): free subdomain or existing domain
- SSL: free (Let's Encrypt)
- **Total: ~€8/mo**

---

## 10. Pre-Migration Checklist

- [ ] Test `claude setup-token` — generate and verify token works
- [ ] Test auth from a non-Russian IP (e.g., existing VPS) — verify no Cloudflare blocking
- [ ] Verify all repos are pushed to GitHub (no local-only branches)
- [ ] Document all .env variables and secrets
- [ ] List all MCP servers and their dependencies
- [ ] Create VPS with Hetzner
- [ ] Set up SSH keys
- [ ] Make Orchestra paths configurable (code changes)
- [ ] Remove hardcoded proxy (make conditional)
- [ ] Write deployment script / ansible playbook

---

## 11. Open Questions

1. **Domain**: What domain to use for dashboard? `orchestra.seedon.ru`? New domain?
2. **Backup strategy**: Automated DB backups on VPS? To where?
3. **Monitoring**: Zabbix agent on new VPS? Or simpler (uptime kuma)?
4. **SSH to other VPS**: Workers SSH to VPS_IP for deploys — keys need to be on new VPS
5. **Existing VPS consolidation**: Eventually move other services too? Or keep separate?
6. **June 15 SDK billing split**: Monitor SDK credit usage closely after cutover
