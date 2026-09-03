## Tests

`uv run python -m pytest tests/ -q` не дошел до pytest: `uv` не смог открыть cache в `/home/maxim/.cache/uv` из-за read-only FS.

Повтор с `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/ -q` не дал результата за >2 минут и не вывел прогресс.

## Summary

Рефактор в целом двигает data access к `SessionManager`, но текущий `archived` не является надежным зеркалом DB. Самый опасный класс багов: stopped/error сессии могут быть потеряны из memory-only выдачи или храниться в разных схемах в зависимости от того, были они остановлены в текущем процессе или загружены при startup. Lifecycle операции не атомарны: `send`, `stop`, `remove` могут пересекаться на одной сессии без manager-level блокировки. Вердикт: требует фиксов перед ACK.

## Замечания

blocking: app/manager.py:136 - `stop()` кладет в `archived` `session.to_dict()`, а `load_archived()` кладет DB-row. В одном процессе `/api/sessions/{name}` для archived возвращает урезанную схему без `cwd/session_id/finished_at/worktree_path`, после restart - полную DB-схему; плюс `archive_by_id()` на такой записи упадет в `save_session(entry)` из-за отсутствующих ключей. Фикс: хранить в `archived` один канонический формат, лучше `session._to_db_dict()` или свежий `get_session(session_id)` после persist.

blocking: app/manager.py:275 - `load_archived()` вызывается до `mark_stale_sessions()` на app/manager.py:310. Worker rows, которые startup помечает `error`, не попадают в `archived`, а `list_sessions()` больше не делает DB merge, поэтому они исчезают из API/tools до следующего рестарта. Фикс: вызывать `load_archived()` после `mark_stale_sessions()` или архивировать stale rows в том же проходе.

blocking: app/session.py:116 - task error переводит `AgentSession` в `ERROR` и persist'ит DB, но `SessionManager` не переносит такую сессию из `sessions` в `archived`. Это ломает заявленный инвариант "archived хранит stopped/error": errored session остается active in-memory, `find_worker()` ее находит, а `send()` потом падает. Фикс: callback/observer в manager на terminal status или manager-owned wrapper вокруг turn task, который архивирует и удаляет из `sessions`.

blocking: app/manager.py:132 - `stop()` держит сессию в `sessions` весь `await session.stop()`. Параллельный `send()` на app/manager.py:121 может взять тот же объект и принять сообщение, пока stop уже чистит client/pending; результат - "ok" с потерянным message или гонка с cleanup/query. Фикс: per-session lifecycle lock или manager lock, плюс перевод в stopping/удаление из active index до await.

blocking: app/manager.py:139 - `remove()` вызывает `session.stop()` только для `RUNNING/STARTING`; `IDLE` active session удаляется из `sessions` и DB без `_cleanup_client()`. Это оставляет SDK client/таски живыми без DB row. Фикс: всегда cleanup/stop active session перед delete; если архив при remove не нужен, после stop удалить из `archived`.

suggestion: app/manager.py:258 - `archive_by_id()` мутирует `entry` до `save_session()`. Если `save_session()` упадет, например на `UNIQUE(name, scope)`, memory cache уже изменен и расходится с DB; метод также не защищен от active `session_id`. Фикс: работать с копией, проверять `session_id not in self.sessions`, обновлять `self.archived` только после успешного save.

suggestion: app/manager.py:229 - `list_sessions()` возвращает ссылки на dict'и из `self.archived`. Любой внутренний caller может случайно изменить cache через response object. Фикс: `result.append(a.copy())` или единый DTO builder.

question: app/tools.py:64 - `send_to_worker()` теперь пробует `ensure_loaded()` только по scopes активных sessions. DB-only idle worker в scope без активного агента стал недостижим через tool, хотя раньше DB scan его находил. Это намеренное сужение поведения? Если нет, нужен manager-level индекс/loadable lookup или scope в tool schema.

thought: app/manager.py:249 - `find_session_id_by_name()` не учитывает `scope`, а `get_worker_logs()`/`kill_worker()` используют его для active + archived. При одинаковых worker names в разных repos tool может взять чужую сессию. Фикс: либо сделать имена workers глобально уникальными явно, либо добавить `scope` в tools.

## Вердикт

требует фиксов

## Round 2

### Tests

`env UV_CACHE_DIR=/tmp/uv-cache timeout 90s uv run python -m pytest tests/ -q` завершился с code `124` без вывода. То есть suite все еще не дает подтверждения: либо hang, либо очень долгий setup/teardown без progress.

### Fix verification

1. FIXED: app/manager.py:141 и app/manager.py:329 теперь кладут в `archived` `session._to_db_dict()`, не `to_dict()`. Формат archived entries стал DB-shaped для stop/shutdown paths.

2. FIXED: app/manager.py:315-318 теперь вызывает `load_archived()` после `mark_stale_sessions()`. Stale workers, помеченные `error` при startup, должны попасть в memory archive.

3. STILL BROKEN: app/session.py:190-194 уже выставляет `self.status = AgentStatus.ERROR` внутри `_run_turn()`, а app/session.py:118-123 вызывает `on_error` только если `self.status != AgentStatus.ERROR`. Для основного error path callback не сработает, manager не получит событие и session останется вне `archived`. Фикс: вызывать `on_error` прямо в `_run_turn()` после persist или убрать status guard вокруг callback в `_on_task_done()`.

4. STILL BROKEN: app/manager.py:138-142 теперь удаляет session из active index до await, но это не сериализует уже полученные references. `manager.send()` может взять объект на app/manager.py:128 до `pop()`, а tools вообще делают `find_worker()` и потом напрямую `await session.send()` на app/tools.py:62-77. Нужен lifecycle lock/stopping flag на самом `AgentSession` или единый manager-owned send path.

5. FIXED: app/manager.py:144-152 теперь всегда вызывает `_cleanup_client()` для active session перед delete. Конкретный leak для idle sessions закрыт.

6. FIXED: app/manager.py:262-273 теперь не мутирует исходный archived dict до `save_session()` и отказывает active ids. Это закрывает cache/DB divergence из предыдущего замечания.

7. FIXED: app/manager.py:233-235 теперь возвращает `a.copy()`. Прямая мутация `self.archived` через `list_sessions()` больше не протекает.

### New bugs

blocking: app/manager.py:139 - `stop()` теперь делает `sessions.pop()` до `await session.stop()`, но не возвращает session обратно при exception. Если `session.stop()` или `_persist()` упадет, session исчезнет из active index и не попадет в `archived`; API начнет отдавать 404/неполные данные при живом объекте. Фикс: try/except с rollback в `self.sessions` или отдельное `stopping` registry до успешного archive.

blocking: app/manager.py:40 - `_on_session_error()` архивирует errored session, но не делает async cleanup client/turn resources. Если callback начнет реально срабатывать, manager удалит session из active index, оставив SDK client lifecycle вне управления. Фикс: error archival должен быть async manager task: cleanup, persist, archive, remove from active in one lifecycle path.

suggestion: app/manager.py:139 - из-за `pop()` до await stopping session временно невидима для `get_by_name()`, `get_session_id()` и logs lookup до завершения `session.stop()`. На медленном disconnect это дает transient 404. Если это intentional, нужен явный `stopping` state/index; иначе archive entry надо создавать до долгого await или lookup должен учитывать stopping sessions.
