---
name: laptop-access
description: Check the owner's laptop or its projects from the VPS through the reverse SSH tunnel.
---

# Laptop access

The only route for platform agents is SSH through the reverse tunnel. The laptop maintains the
connection to the VPS; its system-level `ssh-tunnel-vps.service` was checked active/running on
2026-09-13. The `run_on_laptop` tool is unavailable to platform agents.

## Check the connection

On the VPS, check the local listener:

```bash
ss -ltnH 'sport = :2222'
```

Working command (2026-09-13, host `maxim-911aird`, user `maxim`):

```bash
ssh -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5 -p 2222 maxim@127.0.0.1 'hostname; pwd'
```

For authorized work, replace only the remote command; quote paths containing spaces. The laptop
user is `maxim`, not the VPS user `kesha`. Empty successful `ss` output means no listener; an
error from the check does not prove that none exists. Refused/timeout means the connection is
unavailable: report the observed failure to the owner. Sleep, shutdown, and network loss are
possible, but one error does not establish the cause. Permission denied means an authentication
problem, not proven sleep: check the user and specified key. The tunnel is raised from the
laptop; do not reconfigure or restart it from the VPS.

## Actual boundaries

This is a remote shell with the `maxim` account's rights, not a command whitelist or metacharacter
filter. SSH maintains authentication and protects transport; the laptop OS limits object access.
The assignment and project rules determine what is allowed, not the existence of a working
connection. Installation, restart, and configuration changes are allowed only when explicitly
included in the agreed assignment. Handle the laptop carefully — see [AGENTS.md Orchestra,
"Authority boundaries"](/home/kesha/orchestra/AGENTS.md). Do not copy those rules into this skill.
Access alone does not authorize spawning agents or continuing other sessions. Long authorized
commands follow the platform's background-jobs rules.

## Directory map

Snapshot of the laptop: 2026-09-13T14:00:29.258676+00:00. These are directory names, not a
claim that each is an independent project. The `.git` marker was checked without reading history
or remotes; a file may represent a worktree or submodule. Before work, verify the chosen path
exists; the snapshot does not promise it is unchanged.

### /mnt/data/Projects/Python/

| Directory | `.git` marker |
|---|---|
| `ai-proxy-manager` | directory |
| `Alexey-Projects` | not found |
| `Aperant` | directory |
| `BallisticSim` | not found |
| `civsim` | not found |
| `Claude-Code-Game-Master` | directory |
| `claude-plugins-official` | directory |
| `claude-server` | directory |
| `CursorUsageAnalyzer` | directory |
| `DnD-Music-MCP` | directory |
| `E-CommerceBench` | directory |
| `games` | directory |
| `inscryption-ai` | directory |
| `inscryption-ai-public` | directory |
| `kesha-tg-bot` | directory |
| `LLM` | not found |
| `OF-Parser` | not found |
| `orchestra` | directory |
| `orchestra-architecture-audit` | file |
| `orchestra-astra-usage` | file |
| `orchestra-backups` | not found |
| `orchestra-bash-latency-20260905` | file |
| `orchestra-codex-state-compat` | file |
| `orchestra-day-20260907` | file |
| `orchestra-db-research` | file |
| `orchestra-design-gallery` | file |
| `orchestra-enterprise` | directory |
| `orchestra-handoff-context-window` | file |
| `orchestra-html-skill` | file |
| `orchestra-instruction-guard` | file |
| `orchestra-knowledge-delivery` | file |
| `orchestra-local-workflow` | file |
| `orchestra-model-text-control-flow` | file |
| `orchestra-receipt-audit` | file |
| `orchestra-remove-dead-compat` | file |
| `orchestra-retire-legacy-review` | file |
| `orchestra-service-lifecycle` | file |
| `orchestra-service-lifecycle-baseline` | file |
| `orchestra-simplify-review` | file |
| `orchestra-stability-recovery` | file |
| `orchestra-storage` | file |
| `orchestra-storage-baseline` | file |
| `orchestra-sync-20260912` | file |
| `orchestra-worker-autonomy` | file |
| `Parsing` | directory |
| `PhotoServer` | directory |
| `seedon` | directory |
| `slay-the-spire-analysis` | not found |
| `space-sim` | directory |
| `stargate-tactics` | directory |
| `test-project` | directory |
| `TradingCryptoBot` | directory |
| `TTS` | not found |
| `Vitaliy-Projects` | not found |
| `VoiceType` | directory |
| `VPN-Service` | directory |
| `web_portfolio` | directory |
| `WebView` | directory |
| `wmod` | directory |
| `world-state` | not found |

### /mnt/data/Projects/Unity/

| Directory | `.git` marker |
|---|---|
| `AIMedical` | directory |
| `AISwapFace` | directory |
| `Bashilov Story` | not found |
| `Birusa2026` | directory |
| `DefaultProjectUnity` | directory |
| `POLUS` | not found |
| `Test` | not found |
| `WinterGame` | directory |

Vault: `/mnt/data/Рабочий стол/Cursor/COG-second-brain` — existence checked in the same snapshot.
The laptop's Orchestra folder is a checkout; this platform's running Orchestra instance is on
the VPS. Access to the checkout does not authorize deployment or restart.
