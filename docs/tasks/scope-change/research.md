# Research: сменить корневую папку (scope/repo_path) оркестратора без потери сессии

**Дата:** 2026-05-31
**Статус:** RESEARCH ONLY (реализация не делалась)
**Вердикт:** ⚠️ **СРЕДНЕ** — выполнимо, но требует рестарта backend оркестратора (НЕ hot). Сессия/контекст НЕ теряются (resume по `session_id`). Главный нюанс — это не "переименование пути", а **смена identity-ключа**, на котором завязан весь проект.

---

## TL;DR

`scope` — это не просто поле, это **первичный ключ идентичности оркестратора** (вместе с `name`). На него завязаны: фильтрация всех агентов/задач/jobs, env MCP-подпроцесса, slug worktree-путей, CWD, вкладки дашборда. Сменить можно, но:

1. **Сессия Claude НЕ теряется** — она привязана к `session_id` (resume-токен Claude CLI), а не к scope. Меняем scope в БД → пересоздаём backend с тем же `session_id` → контекст цел.
2. **Backend оркестратора надо передёрнуть** (disconnect → reconnect) — потому что `ORCHESTRA_SCOPE` инжектится в env MCP-подпроцесса при старте backend и read-only внутри `mcp_stdio.py`. Без рестарта MCP старые tools будут фильтровать по старому scope.
3. **Воркеры остаются на старом scope** — у них свой scope = их `repo_path`. Менять их scope каскадно — отдельный кошмар (worktree уже физически в старом slug-каталоге). Рекомендация: смена scope разрешена **только когда у оркестратора нет живых воркеров** (или воркеры мигрируются вручную/отдельно).
4. **Worktree-каталоги воркеров НЕ переезжают** — они в `worktrees/<old-scope-slug>/`. Физически перемещать = ломать git worktree registration. Поэтому смена scope = операция "пустого" оркестратора.

---

## Что такое scope: полная карта зависимостей

### 1. DB — `sessions` таблица (app/db.py)
- `sessions.scope` — `NOT NULL`, входит в `UNIQUE(name, scope)` (db.py:58) и индекс `idx_sessions_scope` (db.py:68).
- Фильтрация: `get_session_by_name(name, scope)`, `get_all_sessions(scope)`, `get_stats(scope)` — всё по scope.
- **Edge-case UNIQUE:** если в новом scope уже есть агент с таким же `name` — `UPDATE sessions SET scope=?` упадёт на UNIQUE-конфликте. Надо проверять заранее.

### 2. DB — другие таблицы
- `jobs.scope` (db.py:84) — spawn/kill jobs, фильтр `get_jobs(scope)`.
- `bg_jobs.target_scope` (db.py:180) — background jobs, индекс `idx_bg_jobs_scope`, куча функций фильтрации (`bg_get_active_for_scope`, `bg_count_active`, ...).
- `test_lock.scope` (db.py:91) — PRIMARY KEY. Тест-лок привязан к scope.
- `tm_projects.scope` (db.py:103) — `UNIQUE`. Привязка проекта задач (Task Manager) к scope. `get_project_by_scope()` (tm.py:104) резолвит проект по scope в API задач/платежей.

**Вывод по DB:** scope разбросан по 5 таблицам. НО — `sessions` каскадит (`logs`, `inbox` через `ON DELETE CASCADE` по session_id, не scope). Реально менять scope надо в: `sessions` (только у самого оркестратора — у воркеров отдельный разговор), опционально `tm_projects`, `bg_jobs.target_scope`, `test_lock.scope`. `jobs` — эфемерны (только последние 20 для UI), можно не трогать.

### 3. MCP-подпроцесс (app/mcp_stdio.py)
- `SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")` (mcp_stdio.py:21) — читается **один раз при старте процесса**, дальше read-only.
- Используется как фильтр "свои агенты" во ВСЕХ tools: `list_agents`, `send_message`, `spawn_worker` (scope=repo_path по умолчанию), `task_*`, `bg_*`, `test_lock_*` и т.д.
- Env задаётся в `_make_mcp_config()` (manager.py:296-311): `"ORCHESTRA_SCOPE": scope`.
- MCP-подпроцесс спавнится Claude CLI при `backend.connect()` (через `ClaudeBackend(mcp_servers=self.mcp_servers)`).

**Критично:** изменить scope в env работающего MCP-процесса нельзя. Нужно:
1. Перестроить `session.mcp_servers` через `_make_mcp_config(name, NEW_scope, role)`.
2. `await session._disconnect_backend()` — убивает старый MCP-подпроцесс.
3. Следующий `send()` поднимет backend заново → новый MCP с новым `ORCHESTRA_SCOPE`.

### 4. CWD оркестратора
- У оркестратора `cwd == scope` (обычно). `session.cwd` передаётся в `ClaudeBackend(cwd=...)` — это рабочий каталог Claude CLI.
- При смене scope меняем и `session.cwd` (если хотим, чтобы агент работал в новой папке). Это тоже требует рестарта backend (cwd фиксируется при `connect()`).

### 5. Worktree (app/workspace.py)
- `create_worktree(repo_path, name, scope, ...)` (workspace.py:51) — `scope_slug = _slugify(scope)`, путь = `worktrees/<scope_slug>/<name>`.
- **Только воркеры имеют worktree.** У оркестратора `worktree_path == None` (он работает прямо в scope-папке).
- Поэтому для **оркестратора без воркеров** worktree вообще не при делах — менять нечего.
- Для воркеров: их worktree физически лежит в каталоге старого slug. Переименование scope → их `worktree_path` указывает на `worktrees/<old-slug>/...`. Это всё ещё валидный git worktree (привязка по абсолютному пути в `.git/worktrees/`), пока папку физически не двигают. Менять `worker.scope` в БД, не трогая физический путь — рассинхрон (slug в пути ≠ новый scope), но НЕ ломается, т.к. `worktree_path` хранится абсолютным и используется напрямую (manager.py:621, session.cwd=wt_path).

### 6. Дашборд (app/static/js/app.js)
- Вкладки оркестраторов идентифицируются по `o.scope` (app.js:614, 638, 684, 702, 914 — `selectOrchestrator(name, scope)`).
- `currentScope` шлётся во все API-запросы (логи, send, prompt). После смены scope фронт просто перечитает `/api/orchestrators` (там новый scope) и нарисует вкладку заново. SSE-стрим переподключится на новый scope. **Граница:** активный SSE на старый scope оборвётся — UI надо обновить (reload вкладок). Не блокер, косметика.

### 7. TG Bridge (app/tg_bridge.py)
- Топики keyed по **orchestrator name**, НЕ по scope (`config["topics"][name]`, tg_bridge.py:203, 596).
- ✅ **Смена scope НЕ ломает TG** — топик привязан к имени, имя не меняется.

### 8. REPO_TO_SCOPE (app/main.py:1444-1456)
- GitHub webhook mapping `repo_full → scope` из env `ORCHESTRA_REPO_SCOPE_MAP`. Статический, читается при старте сервера.
- Если scope меняется — webhook-маппинг устареет (будет слать в старый scope). Но это env-конфиг, не БД. Для большинства кейсов (dev, переезд папки) неактуально. Упомянуть в доке "не забудь обновить env, если используешь GitHub webhooks".

### 9. `_is_safe_path` (app/main.py:259)
- Новый путь должен пройти `_is_safe_path` (быть внутри `_get_allowed_roots()`). Валидация обязательна перед сменой.

---

## Ответы на вопросы из задачи

**1. Что минимально нужно обновить в DB?**
Для оркестратора без воркеров:
- `sessions.scope` (+ `cwd`) у строки оркестратора.
- `tm_projects.scope` — ЕСЛИ к проекту привязаны задачи и хотим сохранить связь (опционально).
- `bg_jobs.target_scope` — для активных bg-jobs оркестратора (обычно их нет/мало).
- `test_lock.scope` — если держит лок (редко).
Минимум-минимум: **только `sessions.scope` + `sessions.cwd`**. Остальное — по ситуации.

**2. Воркеры — их scope меняется?**
По умолчанию НЕТ. У воркера scope = его repo_path, worktree физически в старом slug-каталоге. Каскадная смена scope воркеров = перемещение worktree (git worktree move) + UNIQUE-проверки + рестарт каждого MCP. Рекомендация: **запретить смену scope при наличии живых воркеров**, либо требовать их предварительного merge+kill.

**3. Worktree переезжают?**
Оркестратор — нет worktree (N/A). Воркеры — физически НЕ переезжают (см. п.5). Это аргумент за "смена scope только для пустого оркестратора".

**4. MCP SCOPE — рестарт нужен?**
ДА. `ORCHESTRA_SCOPE` фиксируется в env MCP-подпроцесса при старте. Нужен `_disconnect_backend()` + пересборка `mcp_servers`. Сам **Orchestra-сервер рестартить НЕ надо** — только backend конкретного оркестратора (disconnect, дальше lazy reconnect на следующем `send`).

**5. Hot (без рестарта Orchestra)?**
ЧАСТИЧНО. Orchestra-сервер — да, hot. Backend оркестратора — нет, его надо передёрнуть (disconnect). Но это дёшево: сессия Claude resume-ится по `session_id`, контекст не теряется, агент даже не заметит (как hibernate→wake). С точки зрения юзера — "hot", с точки зрения процессов — мини-рестарт одного backend.

**6. Edge-cases:**
- **UNIQUE(name, scope):** в целевом scope уже есть агент с тем же именем → конфликт. Проверять.
- **`tm_projects.scope` UNIQUE:** если в новом scope уже привязан другой проект — конфликт.
- **Живые воркеры:** ломается модель "scope = repo воркеров". Блокировать.
- **Активный turn:** менять scope пока оркестратор RUNNING — гонка. Требовать idle (как `change_model`, session.py:697).
- **Активные bg_jobs:** осиротеют (target_scope старый) — обновить или отменить.
- **Новый путь не git-репо / не существует / вне allowed roots:** валидировать (`_is_safe_path`, `Path.is_dir()`).
- **SSE/дашборд:** старый стрим оборвётся, фронт перерисует вкладку — косметика.
- **GitHub webhook map (REPO_TO_SCOPE):** устареет, env-конфиг — упомянуть.

**7. API endpoint / MCP tool / CLI?**
Рекомендация: **API endpoint + кнопка в дашборде** (это операция уровня оркестратора/юзера, не воркера). НЕ MCP tool — воркерам это не нужно, оркестратору менять собственный scope через tool странно (он работает в этом scope). Юзер-операция через дашборд = правильный уровень. Можно продублировать тонким MCP-tool для оркестратора, если захотим, но не обязательно.

---

## Рекомендация

**Делать. Сложность — средняя.** Это НЕ "невозможно" и НЕ тривиально.

Безопасный MVP-скоуп (без боли с воркерами):
- Endpoint `POST /api/orchestrators/{name}/change-scope` с телом `{old_scope, new_scope, new_cwd?}`.
- Гард-рейлы: idle-only, нет живых воркеров в старом scope, новый путь валиден (`_is_safe_path` + `is_dir`), нет конфликта `UNIQUE(name, new_scope)`.
- Транзакция в БД: UPDATE `sessions.scope`+`cwd`, опционально `tm_projects.scope`, `bg_jobs.target_scope`, `test_lock.scope`.
- В рантайме: пересобрать `session.mcp_servers` (`_make_mcp_config`), `session.scope`/`session.cwd`, `_disconnect_backend()` (lazy reconnect на следующем send, `session_id` сохранён → контекст цел).
- Фронт: после успеха перечитать `/api/orchestrators`, переключиться на новую вкладку.

См. `plan.md` для пошагового плана.
