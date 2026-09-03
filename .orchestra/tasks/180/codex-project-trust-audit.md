# #180 — Codex project trust / context audit

Date: 2026-08-16. Scope: local Orchestra-managed Codex sessions and registered project roots.
Secret values were not copied into this report.

## Trigger and root causes

VPN-orchestrator started Codex with:

> Project-local config, hooks, and exec policies are disabled ... until the project is trusted.

The warning was accurate. Its private
`~/.orchestra/codex-home/<session-id>/config.toml` had the Orchestra MCP server but no
`[projects.<cwd>].trust_level`. `CodexBackend._prepare_codex_home()` deliberately did not clone
the base config's `[projects]` table, but it also failed to add the current managed checkout.

Two adjacent delivery gaps were measured:

1. `AgentSession._ensure_backend()` mirrored `CLAUDE.md -> AGENTS.md` only for sessions with a
   worktree. Root orchestrators have no worktree, so VPN-orchestrator had a 29,895-byte
   `CLAUDE.md` and no `AGENTS.md`; native Codex did not receive those repository instructions.
2. `_codex_factory()` did not merge the repository `.mcp.json`. Claude and Grok already use
   `_load_scope_mcp_servers()`. VPN Codex therefore received only Orchestra MCP and silently
   missed its project `aperant` MCP server.

## Implemented fix

- Each private Codex home now trusts only `Path(cwd).resolve()` for that backend. Foreign
  `[projects]` entries and foreign global MCP servers remain excluded.
- Codex backend setup mirrors `CLAUDE.md -> AGENTS.md` for `worktree_path or cwd`. Existing
  tracked `AGENTS.md` remains owned by the repository and is not overwritten.
- Codex now merges scope `.mcp.json` servers with the manager-owned MCP set. A project entry
  named `orchestra` cannot override the trusted manager server.
- Local CLI was aligned with the repository pin: `codex-cli 0.145.0 -> 0.146.0`.

Verification:

```text
126 passed in 2.59s
python -m py_compile: pass
git diff --check: pass
```

Covered invariants include canonical/quoted cwd TOML round-trip, no cloning of foreign trust or
MCP secrets, manager `orchestra` precedence, scope MCP delivery, and orchestrator cwd AGENTS
preflight ordering.

## Project and Git inventory

- `/mnt/data/Projects/Python`: 33 top-level directories; 23 are Git repositories and 10 are not.
- Active orchestrator projects: 18; 17 resolve to a Git repository. `media-orchestrator`
  currently points at a non-Git directory.
- This is not one Git repository. Remotes also vary:
  - Orchestra: `enterprise`, `origin`, `vadim`.
  - Aperant and COG: `origin`, `upstream`.
  - VPN-Service: `origin`, `origin-https`.
  - Mods, WebView, and stargate-tactics: no configured remote.
  - Most remaining registered repositories have one `origin`.
- VPN-Service is a PRIVATE GitHub repository. Its local `master` was one commit behind
  `origin/master` during the audit. It was not pulled because VPN-orchestrator had an active turn.

## Rules, skills, MCP, and secrets boundary

Across the 18 active orchestrator roots:

- No project had `.codex/hooks.json` or project `.codex/rules/*` files.
- One project (Claude-Code-Game-Master) had `.codex/config.toml` with project MCP settings.
- Project Codex skills were present in COG (11), VPN-Service (5), and Orchestra (5). Skills load
  even while a project is untrusted; the warning concerned config/hooks/rules.
- Durable Orchestra role/modules are passed as developer instructions independently of Git.
  Repository `CLAUDE.md` requires the AGENTS mirror fixed above for native Codex discovery.

VPN-Service specifics:

- `.env`, `.auto-claude/.env`, and `keys/server1.pem` exist locally and are ignored by Git.
  No filename-classified credential file was tracked. Both env files were mode 0664 at
  measurement time and were tightened to 0600; the PEM was already 0600.
- The tracked `CLAUDE.md` contains live-looking infrastructure endpoints and proxy secret
  material. The GitHub repository is private, but these values are still present in tracked
  history and available to every repository collaborator.
- `.mcp.json` is tracked and defines the `aperant` server with an `APERANT_PROJECT` environment
  key; it contains no credential value under that key.
- Managed Codex starts with `sandbox="danger-full-access"` and `approvalPolicy="never"`.
  Therefore it can read same-user local `.env`, PEM, SSH, and other accessible files if a task
  directs it to. Those secrets are not automatically inserted into the model prompt; they are
  available through filesystem access.
- The per-agent Codex home is mode 0700 and `config.toml` is 0600. Auth and session-store links
  are shared intentionally; MCP env stays in the private config rather than process argv.

## Activation boundary

Source and tests are fixed locally, but the running Orchestra process still has the old Python
code. Existing Codex processes also do not reload trust, AGENTS, or MCP config mid-process.
Activation therefore requires an Orchestra restart and a fresh/restarted Codex CLI at a turn
boundary. No service or active VPN turn was interrupted during this audit.
