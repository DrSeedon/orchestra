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

## [2026-05-31 17:41 UTC] codex_review не видит diff под-репо/proxy — путь резолвится в главный репо
- **Reporter:** dev-lead
- **Scope:** /mnt/data/Projects/Python/seedon
При запуске codex_review для изменений в proxy/main.py (под-директория worktree) Codex анализирует diff ГЛАВНОГО репозитория (документация seedon), а не proxy-код.

Воспроизведение (воркер infra, ветка task-30/infra):
1. `codex_review(mode="review")` — Codex увидел diff главного репо (доки), не proxy/main.py. Ревью бесполезно.
2. `codex_review(target="/tmp/cache-opt-diff.patch", mode="exec")` — bg job завершился, но output-файл НЕ записан (path resolution ломается между главным репо и worktree/под-папкой).

ОБХОД (рабочий): 2-я попытка через exec на заранее собранный patch (`git diff main...HEAD -- proxy/main.py > /tmp/x.patch`, затем codex exec на этот файл) — СРАБОТАЛА и поймала реальный blocking-баг. То есть exec-режим на patch-файл работает, но нестабильно (с первого раза output не записался).

Ущерб: review кода в под-папках worktree ненадёжно. Для multi-repo проектов (seedon содержит proxy/ как часть кода) нужен корректный path resolution или явный параметр рабочей директории для codex_review.

Severity: medium (есть обход через patch-файл, но неинтуитивный и flaky).

## [2026-05-31 17:42 UTC] Ambiguous task linking: один номер таска в двух проектах ломает линковку коммитов при merge_worker
- **Reporter:** dev-lead
- **Scope:** /mnt/data/Projects/Python/seedon
merge_worker и worker_wip выдают warning "Ambiguous task #N — exists in projects: seedon, orchestra. Use project filter." при попытке слинковать коммиты к таску.

Воспроизведение:
- Таски #28 и #30 существуют ОДНОВРЕМЕННО в проектах seedon И orchestra (одинаковые номера в разных проектах).
- При merge_worker("infra") сам мерж проходит ("Merged N commits"), НО линковка коммитов к таску фейлится с warning про ambiguity.
- Результат: коммиты замержены, но не привязаны к таску (task.commits пустой).

Корневая причина: номера тасков (#N) не уникальны глобально — уникальны только в паре (project, number). Логика link_commits_to_task() не передаёт project-фильтр, поэтому при коллизии номеров не знает к какому таску линковать.

Фикс: link_commits_to_task должен использовать project воркера (или таска переданного в spawn_worker task_id) для дизамбигуации. Либо merge_worker должен принимать project-параметр.

Severity: low (мерж работает, страдает только метадата-линковка коммит↔таск).

## [2026-05-31 17:42 UTC] Воркер создаёт ветки от устаревшего origin/main вручную (checkout -b) → повторные конфликты мержа + рассинхрон metadata Orchestra
- **Reporter:** dev-lead
- **Scope:** /mnt/data/Projects/Python/seedon
Дважды подряд (#28 и #30) merge_worker зафейлился конфликтом в proxy/main.py. Корневая причина процессная + платформенная.

Что происходит:
1. switch_worker_branch иногда фейлится с "worker is running" (race: каждый send_message будит воркера → он в running → switch не проходит). Воркер не может переключиться штатно.
2. В обход воркер сам делает `git checkout -b task-30/infra origin/main` — от УСТАРЕВШЕГО origin/main (актуальный локальный main с уже замерженным #28 уехал вперёд).
3. Orchestra metadata об этой ветке не знает: get_worker_info.branch показывает старую (task-28), хотя фактически воркер на task-30. worker_wip при этом видит правильные коммиты — рассинхрон между двумя источниками правды.
4. При merge_worker — конфликт, т.к. ветка от старой базы, а несколько тасков трогают один файл.

Два бага платформы:
A) switch_worker_branch race — нельзя переключить ветку пока воркер "running", а сообщения сами его будят. Нужен способ переключить ветку без гонки (очередь, или switch прерывает turn).
B) get_worker_info.branch не синхронизируется когда воркер создаёт ветку сам. Должен быть единый источник правды (как worker_wip).

Обход: воркер делает git rebase main перед DONE; оркестратор НЕ помечает task done до подтверждённого вывода merge_worker.

Severity: medium — приводит к повторяющимся конфликтам и панике оркестратора по ложным данным.
