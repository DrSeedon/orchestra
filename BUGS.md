# Orchestra Bug Reports

## Open

### 🔴 send_message 500 после рестарта
- **Reporter:** Parsing-orchestrator (2026-05-26)
- send_message к idle воркерам = 500 после restart Orchestra. Свежие воркеры работают
- Ошибка до HTTP слоя, global exception handler не помог
- **Workaround:** respawn воркера
- **Assignee:** backend

### 🟠 codex_review output path — пишет в main worktree
- **Reporter:** Orchestra-orchestrator (2026-05-31)
- `codex_review(output="docs/...")` пишет файл относительно CWD Orchestra-сервера, не worktree воркера
- Воркер не может прочитать результат
- **Workaround:** воркер ищет файл через find
- **Assignee:** backend | **Task:** #27

### 🟡 Worker DONE report уходит parent_name вместо task giver
- **Reporter:** seedon-orchestrator (2026-05-31)
- Воркер спавнен orchestrator-A, задачу дал orchestrator-B через send_message. DONE уходит к A (parent), B не знает что задача выполнена
- **Root cause:** send_message DONE идёт к `{orchestrator_name}` из промпта = parent при спавне
- **Assignee:** нет

## [2026-05-31 17:36 UTC] codex_review не видит diff суб-репо (git worktree с вложенным .git)
- **Reporter:** infra
- **Scope:** /mnt/data/Projects/Python/seedon
При запуске codex_review(mode="review") из воркера infra, Codex работает в основном репо /mnt/data/Projects/Python/seedon/ и видит diff основного git, а не суб-репо infra/ который имеет отдельный .git. Результат: Codex ревьюит не тот diff ("documentation describing agent hierarchy") вместо proxy/main.py изменений. Также не может записать output файл (путь docs/tasks/30/ не существует в основном репо). Воркараунд: self-review вместо Codex для суб-репо.
