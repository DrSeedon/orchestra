# Orchestra Bug Reports (from agents)

## ~~[2026-05-07 05:25 UTC] send_message to idle orchestrators fails with "not found"~~ ✅ FIXED
- **Fix:** `ensure_loaded_any(name)` — fallback поиск по имени across all scopes (commit c379385)

## ~~[2026-05-07 13:05 UTC] Workers don't have mcp__orchestra__send_message~~ ✅ FIXED
- **Root cause 1:** `.mcp.json` из source repo копировался в worktree → CLI подхватывал проектный конфиг и не грузил Orchestra MCP из `--mcp-config`
- **Root cause 2:** `python -m app.mcp_stdio` не работал из worktree CWD (модуль не найден)
- **Fix:** убрали `.mcp.json` из PROJECT_FILES + абсолютный путь к mcp_stdio.py (commits 06e0b58, 9bf8054)
- **Verified:** test-final воркер → `mcp__orchestra__send_message(to="Parsing-orchestrator", message="PONG")` → доставлено ✅

## ~~[2026-05-09 03:16 UTC] notify_kesha не работает~~ ✅ NOT A BUG
- **Cause:** Kesha bot (inbox server :18081) was offline. Orchestra works fine — notify_kesha sends HTTP to Kesha, if Kesha is down → connection refused. Start kesha-bot to fix.

## ~~[2026-05-09 03:44 UTC] Worker edits land in main repo instead of worktree~~ ✅ FIXED
- **Reporter:** seedon-site-orchestrator
- **Scope:** /mnt/data/Projects/Python/seedon-site
## Что произошло

Спавнил воркера `admin-geo` через `spawn_worker` с `repo_path=/mnt/data/Projects/Python/seedon-site`. Orchestra создал git worktree по адресу `/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-seedon-site/admin-geo` на ветке `feat/mnt-data-projects-python-seedon-site/admin-geo`.

**Ожидание**: воркер пишет код в worktree, потом оркестратор мержит в main.

**Реальность**: все изменения (145 insertions, 13 deletions в `backend/main.py`) оказались в **основном репо** (`/mnt/data/Projects/Python/seedon-site/`), а worktree остался **чистым** (без изменений, оригинальная версия файла).

## Доказательство

```
$ git worktree list
/mnt/data/Projects/Python/seedon-site                                                         ad8217d [main]
/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-seedon-site/admin-geo  ad8217d [feat/...]

$ git status  # в основном репо
modified:   backend/main.py

$ diff main/backend/main.py worktree/backend/main.py
# worktree = старая версия, main = новая с изменениями
```

## Вероятная причина

Воркер (Claude Code агент) получает `repo_path` и игнорирует worktree path — редактирует файлы по оригинальному `repo_path` вместо worktree директории. Либо CWD воркера устанавливается на оригинальный repo вместо worktree.

## Импакт

- Worktree-изоляция не работает — воркер пишет прямо в main
- Оркестратор не может проверить и одобрить изменения перед мержем
- Race condition: если два воркера спавнятся на один repo — оба пишут в main, конфликты

## ~~[2026-05-09 04:59 UTC] Draft message hangs~~ ❌ NOT ORCHESTRA BUG
- Kesha TG bot bug, not Orchestra. Already tracked in kesha-tg-bot/TODO.md as "Draft ghost".

## [2026-05-09 08:45 UTC] Workers skip Codex CLI on follow-up rounds unless explicitly reminded each time
- **Reporter:** Parsing-orchestrator
- **Scope:** /mnt/data/Projects/Python/Parsing
codex-reviewer worker correctly used `codex exec` for Round 1 (as explicitly stated in the initial task). But for Rounds 2-3, the orchestrator sent follow-up messages like "check the updated plan, append Round N" without repeating "use codex exec". The worker optimized by doing the review itself (Sonnet reviewing Sonnet's own plan = no adversarial value).

Root cause: workers treat the initial task prompt as one-time instructions. Follow-up messages via send_message don't carry the "use codex exec" constraint forward.

Fix options:
1. system_prompt should contain persistent rules like "ALWAYS use codex exec for reviews" (not just in the task message)
2. Orchestrator must repeat critical tool requirements in EVERY follow-up message
3. Worker should have a rule: "if Round 1 used tool X, all subsequent rounds use tool X unless told otherwise"

Impact: Rounds 2-3 review was still high quality (found real bugs in routes/web.php:96 and AuthenticatedSessionController), but lost the adversarial cross-LLM benefit. The whole point of Codex review is GPT-5.5 checking Claude's work — not Claude checking Claude's work.

## [2026-05-09 09:45 UTC] Auto-report misleads orchestrator — no way to distinguish "still working" from "hung/crashed"
- **Reporter:** Parsing-orchestrator
- **Scope:** /mnt/data/Projects/Python/Parsing
When a worker goes idle mid-task, Orchestra sends an auto-report with the last output. The orchestrator has no way to tell if:
- Worker finished successfully (should have sent explicit send_message but didn't)
- Worker hung/crashed mid-task (partial output looks like it's still analyzing)

Current behavior: orchestrator waits forever for a "DONE:" message that never comes because the worker already went idle.

Suggested fix for orchestrator system_prompt — add rule:
"When you receive an auto-report (prefixed with [auto-report]), check the message content. If it does NOT contain a clear completion signal (DONE, finished, committed, etc.), the worker likely hung mid-task. Either:
1. Ping the worker via send_message asking to continue
2. Check worker logs via get_worker_logs for debugging
Do NOT just wait — auto-report means the worker's turn ended."

Also consider: worker system_prompt should emphasize "NEVER go idle mid-task. If you need more turns — send_message asking for guidance, don't just stop."

## [2026-05-09 09:53 UTC] Workers go idle mid-task without sending explicit report — need stronger system_prompt enforcement
- **Reporter:** Parsing-orchestrator
- **Scope:** /mnt/data/Projects/Python/Parsing
seo-worker went idle twice during S7 task:
1. First idle: mid-analysis of DB migrations — auto-report with partial output, had to ping to continue
2. Second idle: after completing work and committing — auto-report instead of explicit send_message

Root cause: worker's system_prompt says "send_message to report" but doesn't emphasize it strongly enough. Workers treat it as optional.

Observed pattern across ALL workers in this session:
- test-worker, worker-parsing, worker-seo, worker-zahoron — all used auto-report
- codex-reviewer — sometimes used send_message, sometimes not
- Only test-final consistently used send_message (after being told explicitly in task)

Suggested fixes:
1. Worker system_prompt should have MANDATORY section: "BEFORE going idle, you MUST call mcp__orchestra__send_message. Auto-report is a FALLBACK, not the primary channel."
2. Consider platform-level enforcement: if worker goes idle without send_message AND task is not marked complete — auto-ping with "you went idle without reporting, continue or send DONE"
3. Orchestrator system_prompt should say: "auto-report without DONE/finished/committed = worker hung. Ping immediately."
