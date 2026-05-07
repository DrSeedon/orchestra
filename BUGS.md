# Orchestra Bug Reports (from agents)

## ~~[2026-05-07 05:25 UTC] send_message to idle orchestrators fails with "not found"~~ ✅ FIXED
- **Fix:** `ensure_loaded_any(name)` — fallback поиск по имени across all scopes (commit c379385)

## ~~[2026-05-07 13:05 UTC] Workers don't have mcp__orchestra__send_message~~ ✅ FIXED
- **Root cause 1:** `.mcp.json` из source repo копировался в worktree → CLI подхватывал проектный конфиг и не грузил Orchestra MCP из `--mcp-config`
- **Root cause 2:** `python -m app.mcp_stdio` не работал из worktree CWD (модуль не найден)
- **Fix:** убрали `.mcp.json` из PROJECT_FILES + абсолютный путь к mcp_stdio.py (commits 06e0b58, 9bf8054)
- **Verified:** test-final воркер → `mcp__orchestra__send_message(to="Parsing-orchestrator", message="PONG")` → доставлено ✅
