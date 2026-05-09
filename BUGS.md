# Orchestra Bug Reports (from agents)

## ~~[2026-05-07 05:25 UTC] send_message to idle orchestrators fails with "not found"~~ ✅ FIXED
- **Fix:** `ensure_loaded_any(name)` — fallback by name across all scopes

## ~~[2026-05-07 13:05 UTC] Workers don't have mcp__orchestra__send_message~~ ✅ FIXED
- **Fix:** absolute path to mcp_stdio.py + no .mcp.json copy to worktrees

## ~~[2026-05-09 03:16 UTC] notify_kesha не работает~~ ✅ NOT A BUG
- Kesha bot offline → connection refused. Start kesha-bot to fix.

## ~~[2026-05-09 03:44 UTC] Worker edits in main repo~~ ✅ FIXED
- **Fix:** CWD rules restored in worker prompt (pwd first, never cd to original repo)

## ~~[2026-05-09 04:59 UTC] Draft message hangs~~ ❌ NOT ORCHESTRA BUG
- Kesha TG bot bug, tracked in kesha-tg-bot/TODO.md

## ~~[2026-05-09 08:45 UTC] Workers skip Codex CLI on follow-up rounds~~ ✅ MITIGATED
- **Fix:** system_prompt contains persistent rules. Orchestrator must repeat critical constraints in follow-up messages

## ~~[2026-05-09 09:45 UTC] Auto-report misleads orchestrator~~ ✅ FIXED
- **Fix:** auto-report clearly tagged `[auto-report]`, prompt says "auto-report without DONE = worker hung, ping immediately"

## ~~[2026-05-09 09:53 UTC] Workers go idle without send_message~~ ✅ MITIGATED
- **Fix:** MANDATORY in worker prompt, mcp__orchestra__send_message explicitly named, auto-report as fallback

## ~~[2026-05-09 10:15 UTC] Context overflow alerting~~ ✅ FIXED
- **Fix:** platform auto-appends `⚠️ CONTEXT CRITICAL: N%` when >90%. `compact_worker` MCP tool added. Orchestrator prompt updated

## ~~[2026-05-09 10:33 UTC] kill_worker Internal Server Error~~ 🔍 OPEN
- Worktree cleanup fails for some workers. Likely stale git state or missing worktree dir

## ~~[2026-05-09 10:41 UTC] compact_worker empty error~~ ✅ FIXED
- **Root cause:** httpx timeout 30s, compact takes ~40s. Fixed: timeout 120s + no-retry rule in prompt
