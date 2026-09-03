---
slug: guards-impl-review
topic: 5 deterministic guards review
model: gpt-5.5
---

## Tests
`UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q` не запускал: перед full-suite я попытался взять проектный test-lock, но MCP-вызов `acquire_test_lock` был отменён. По правилам проекта полный прогон без лока стартовать нельзя.

## Round 1
### Summary
Guard'ы в целом идут в правильную сторону, но два из пяти не являются детерминированными в текущем виде. Kill guard может уничтожить worktree running worker'а после clean-check, потому что проверка выполняется до остановки backend'а и без session lock. owned_dirs block проверяет только загруженные in-memory сессии и пропускает unloaded/waiting workers из SQLite, хотя они остаются live workers и продолжают владеть директориями. Остальные изменения в основном рабочие, но dirty file details режут имена файлов через `split()`, поэтому сообщения будут неточными для путей с пробелами/rename-строк.

### Замечания
blocking: app/main.py:745 — kill guard проверяет `git status`/`rev-list` до `manager.remove()` и без `manager.get_session_lock(session_id)` или lifecycle lock; если worker сейчас `running`, он может записать uncommitted файл сразу после clean-check, а затем `remove_worktree(... --force)` удалит worktree → фикс: при `not force` блокировать kill running worker'а либо сначала остановить/дождаться idle под lock, затем делать git-check и remove в одной критической секции.

blocking: app/main.py:748 — `_run_git()` возвращает пустую строку при timeout/ошибке git и stderr отбрасывается, поэтому broken worktree, отсутствующий `main`, зависший git или любая ошибка `git status`/`git rev-list` трактуется как clean/0 ahead → фикс: для kill guard использовать helper, который возвращает returncode/stdout/stderr, и fail-closed: `git status` error/timeout => 400 с диагностикой; `rev-list` error/timeout => 400, а не `n=0`.

blocking: app/manager.py:271 — owned_dirs block смотрит только `self.sessions.values()` и только статусы `idle/running`; unloaded-but-active rows из SQLite и `waiting` workers не проверяются, хотя `_live_workers_in_scope()` уже считает `idle/running/waiting` из памяти и DB live workers → фикс: проверять и `get_all_sessions(scope)` с `parse_owned_dirs(row["owned_dirs"])`, дедуплицировать по id, включить статус `waiting`.

suggestion: app/workspace.py:310, app/workspace.py:522, app/main.py:750 — `l.split()[-1]` некорректно отображает dirty paths с пробелами и rename/copy porcelain-строки; guard всё равно блокирует, но подсказка может увести не к тому файлу → фикс: для обычного porcelain брать `line[3:]`, а лучше `git status --porcelain=v1 -z` и парсить NUL-delimited paths.

suggestion: app/main.py:534 — send_message hint собирает `get_all_sessions()` без `req.scope`, поэтому typo в одном scope показывает имена агентов из других проектов; для маленькой команды это не критично, но это лишняя утечка project topology и шум → фикс: сначала показывать похожие имена из `req.scope`, а cross-scope hints добавлять только явно или отдельной строкой.

### Вердикт
требует доработки
