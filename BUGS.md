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
