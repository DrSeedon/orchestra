# Plan: смена scope/repo_path оркестратора без потери сессии

**Основано на:** research.md (этот же каталог)
**Сложность:** средняя · **Hot:** да для Orchestra-сервера, мини-рестарт одного backend
**Ключевая гарантия:** `session_id` (resume-токен Claude) сохраняется → контекст не теряется.

---

## Scope MVP (что делаем)
Смена scope **только для оркестратора без живых воркеров**, в состоянии idle. Каскадная миграция воркеров — НЕ в этом MVP (см. research §2, §5).

## Что НЕ делаем
- Не двигаем worktree-каталоги воркеров.
- Не меняем scope воркеров каскадно.
- Не трогаем Orchestra-сервер (никакого systemctl restart).
- Не обновляем `REPO_TO_SCOPE` (env-конфиг GitHub webhook) — только упоминание в ответе юзеру.

---

## Шаги реализации

### 1. DB-слой (app/db.py)
Добавить одну транзакционную функцию:
```python
def change_scope(session_id, old_scope, new_scope, new_cwd,
                 migrate_tm_project=True) -> dict:
    # один _conn(), всё в одной транзакции
    # 1. проверить UNIQUE(name, new_scope) — нет ли коллизии имени в целевом scope
    # 2. UPDATE sessions SET scope=?, cwd=? WHERE id=?
    # 3. опц. UPDATE tm_projects SET scope=? WHERE scope=old_scope (если migrate_tm_project и нет коллизии UNIQUE)
    # 4. UPDATE bg_jobs SET target_scope=? WHERE target_scope=old_scope AND status IN ('active','triggering')
    # 5. UPDATE test_lock SET scope=? WHERE scope=old_scope  (PK — проверить отсутствие коллизии)
    # вернуть что реально обновили
```
Гард: ловить `sqlite3.IntegrityError` (UNIQUE) и возвращать `{"error": ...}`, не падать.

### 2. Manager (app/manager.py)
Метод `SessionManager.change_orchestrator_scope(name, old_scope, new_scope, new_cwd)`:
```
- session = self.get_by_name(name, old_scope); требовать AgentSession (загружен в память)
- guard: session.is_orchestrator (иначе error)
- guard: session.status == IDLE (иначе "cannot change scope while running")
- guard: нет живых воркеров в old_scope:
    [s for s in self.sessions.values() if s.scope==old_scope and not s.is_orchestrator
     and s.status.value in ("idle","running","waiting")] → если есть, error со списком имён
- guard: new_cwd валиден — Path(new_cwd).is_dir()  (валидацию _is_safe_path делаем на уровне API, см. шаг 3)
- db.change_scope(...) → если error, вернуть как есть
- runtime-апдейт:
    await session._disconnect_backend()      # убить старый MCP-подпроцесс
    session.scope = new_scope
    session.cwd = new_cwd
    session.mcp_servers = _make_mcp_config(name, new_scope, session.role,
                                           extra=session.mcp_servers_custom)
    session._persist()
- НЕ зовём session.start() принудительно — backend поднимется lazy на следующем send()
  (session_id цел → resume → контекст сохранён)
- вернуть {"ok": True, "scope": new_scope, "cwd": new_cwd, "updated": {...}}
```
**Важно:** ключ `self.sessions` — это `session.id` (UUID), НЕ `(name, scope)`. Поэтому менять ключ в словаре НЕ надо — id не меняется. Это упрощает всё.

### 3. API (app/main.py)
```python
@app.post("/api/orchestrators/{name}/change-scope")
async def change_scope(name: str, req: ChangeScopeRequest):
    # req: old_scope, new_scope, new_cwd (optional, default=new_scope)
    new_cwd = req.new_cwd or req.new_scope
    if not _is_safe_path(req.new_scope) or not _is_safe_path(new_cwd):
        return JSONResponse({"error": "path not in allowed roots"}, 403)
    try:
        result = await manager.change_orchestrator_scope(
            name, req.old_scope.rstrip("/"), req.new_scope.rstrip("/"), new_cwd.rstrip("/"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, 409)
    if result.get("error"):
        return JSONResponse(result, 409)
    return result
```
Pydantic `ChangeScopeRequest(old_scope: str, new_scope: str, new_cwd: Optional[str] = None)`.

### 4. Фронт (app/static/js/app.js + templates)
- Кнопка "Сменить папку" в меню вкладки оркестратора (рядом с delete, app.js:801 `openDeleteOrchModal`).
- Модалка: input нового пути (default — текущий scope), submit → POST endpoint.
- На успехе: `await loadOrchestrators()` (перечитать вкладки) + `selectOrchestrator(name, new_scope)`.
- На ошибке: показать `result.error`.
- Это чисто статика — рестарт сервера НЕ нужен (CLAUDE.md: фронт подтягивается сам).

### 5. Тесты (tests/)
TDD-кандидаты (data layer — максимальная отдача, см. CLAUDE.md TDD):
- `db.change_scope`: happy path обновляет sessions.scope+cwd.
- UNIQUE-конфликт: в new_scope есть агент с тем же name → error, БД не тронута (транзакция откатилась).
- tm_projects миграция + коллизия UNIQUE.
- bg_jobs.target_scope обновляется только для active/triggering.
- manager guard: смена при RUNNING → error.
- manager guard: живые воркеры в old_scope → error со списком.
- session_id сохраняется после смены (контекст не теряется) — проверить что `session.session_id` не изменился.

---

## Порядок коммитов
1. `#<id>: db.change_scope + tests (data layer)`
2. `#<id>: manager.change_orchestrator_scope + guards + tests`
3. `#<id>: API endpoint /api/orchestrators/{name}/change-scope`
4. `#<id>: dashboard — change-scope button + modal`

## Риски / на что смотреть при ревью
- **Транзакционность DB:** все UPDATE в одном `_conn()`/одной транзакции, иначе частичная миграция при сбое.
- **Lazy reconnect:** убедиться, что после `_disconnect_backend()` следующий `send()` поднимает backend с НОВЫМ mcp_servers (а не закешированным). `_make_backend()` читает `self.mcp_servers` каждый раз — ок.
- **Гонка с hibernate:** менять только в idle; `_disconnect_backend()` сам гасит hibernate_task.
- **`_find_orchestrator_name` и прочие scope-lookup'ы** — после смены резолвятся по новому scope автоматически (читают из session.scope/БД), спец-обработки не требуют.

## Оценка
~150-200 строк (db + manager + api + фронт), 7 тестов. 1 воркер (sonnet для имплементации от этого спека), 2-3 итерации.
