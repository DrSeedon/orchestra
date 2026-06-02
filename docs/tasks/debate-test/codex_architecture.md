---
slug: architecture
topic: Orchestra architecture — optimal or needs refactoring?
created: 2026-06-02T12:00:00Z
model: gpt-5.5
---

## Round 1 — 2026-06-02

### My Position (Codex/GPT-5.5)

Моя позиция: для текущего масштаба Orchestra текущая архитектура скорее адекватна, чем проблемна. Это MVP для небольшой команды и порядка 10 пользователей, а не распределенная платформа с десятками backend-реализаций и отдельными командами на подсистему. Здесь важнее, чтобы инварианты состояния были видны рядом с местами, где они меняются.

`blocking:` я не вижу в исследованных файлах доказательства, что крупность `AgentSession`, `SessionManager` или `main.py` уже создает crash/corrupt/security проблему. Есть maintainability cost, но это не то же самое, что срочный архитектурный долг.

`thought:` `AgentSession` выглядит большим не потому, что туда случайно свалили unrelated business logic, а потому что runtime-сессия агента является настоящим агрегатом состояния: backend process/client, listener task, heartbeat, hibernate, compact, pending message queue, turn generation, cost/context accounting и persistence snapshot должны двигаться согласованно. Разрезание такого агрегата на `SessionLifecycle`, `EventProcessor`, `MessageQueue`, `PersistenceManager` может улучшить форму файлов, но ухудшить локальность инвариантов.

`thought:` текущий стиль ближе к простому "transaction script + stateful aggregate": плоские функции, dataclass, явные side effects, минимум DI/ABC. Это хорошо совпадает с заявленной философией проекта: simple, flat, minimal abstractions; "3 lines > premature abstraction".

`suggestion:` вместо moderate refactoring я бы выбрал conservative hardening: не резать lifecycle/session сейчас, а точечно улучшать тестируемость вокруг уже найденных опасных мест. Например, добавить regression tests на queued messages + compact, scope change + drained persistence, prompt refresh, backend mismatch on load. Это даст больше безопасности, чем перенос кода по новым классам.

### Counter-Arguments

`thought:` **1. "God Object: AgentSession"**

Контраргумент: `AgentSession` большой, но его поля не независимы. Они образуют один runtime-state machine. В `send()` одновременно проверяются `_compacting`, `status`, `backend_type`, `_pending_messages`, `_hibernate_task`, `_hibernated`, `_turn_gen`, `_turn_logs`, `_turn_start`, `_last_msg_time`, `_prompt_injected`, `_template_hash`, `_backend` и `_listen_task` (`app/session.py:196-285`). Это не четыре чистые ответственности, а одна критическая секция запуска хода.

`blocking:` вынос `MessageQueue` отдельно от lifecycle создаст риск race/regression. Сейчас `send()` умеет делать mid-turn inject для Claude, но принудительно queue для Codex (`app/session.py:203-218`), а `_flush_pending()` под тем же `_lifecycle_lock` повторно проверяет compact и requeue'ит сообщения, если compact успел первым (`app/session.py:544-579`). Если очередь станет отдельным объектом, ей все равно придется знать `backend_type`, `status`, `_compacting`, `_turn_gen` и уметь стартовать backend. Это будет не decoupling, а friend-class с доступом к приватному состоянию.

`blocking:` вынос `EventProcessor` отдельно от session также опасен. `_handle_turn_end()` не просто парсит событие: он обновляет session id, cost deltas, context, total tokens, bg-job waiting state, compact ack event, scope idle notification, auto-compact, auto-report, pending flush и hibernate (`app/session.py:467-542`). Любой отдельный `EventProcessor` получит толстый callback API обратно в `AgentSession`, иначе потеряет порядок side effects.

`blocking:` `PersistenceManager` как отдельный компонент может сломать уже задокументированный ordering invariant. В `SessionManager.change_orchestrator_scope()` код специально disconnect'ит backend и вызывает `session._drain_persist()` перед транзакцией `change_scope()`, потому что иначе stale queued persist может перезаписать cwd и получить `scope=/new + cwd=/old` (`app/manager.py:612-630`). Это конкретный пример, где persistence не является нейтральной инфраструктурой; она участвует в lifecycle ordering. Вынести можно, но только если новый контракт явно сохраняет "drain before external DB transaction".

`thought:` **2. "Manager antipattern: SessionManager"**

Контраргумент: `SessionManager` действительно крупный, но основная сложность в `create_session()` является orchestration boundary, а не случайным мусором. Создание сессии связывает в один атомарный поток: normalize scope/cwd/model, уникальность имени, role resolution, owned_dirs conflicts, prompt composition, parent resolution, `can_spawn`, TG topic default, MCP config, backend type, initial DB save, task status update, optional dirty auto-commit, worktree creation, skill injection, branch-aware prompt formatting, idle callback, second DB save, session start, registry insert и rollback worktree/DB on failure (`app/manager.py:419-536`).

`blocking:` отдельный `SpawnService` с большой вероятностью либо начнет напрямую трогать `SessionManager.sessions`, prompt helpers, workspace, DB и task manager, либо вернет огромный "spawn plan" с side effects вокруг него. В обоих вариантах появится новая граница, но не исчезнет реальная транзакционная сложность. Особенно рискованно отделять worktree rollback от создания `AgentSession`: сейчас `except BaseException` удаляет worktree и DB row рядом с местом, где они были созданы (`app/manager.py:529-536`).

`suggestion:` `PromptBuilder` звучит разумнее, но ROI ниже, чем кажется. Prompt composition не статичен: `_workers_block()` и `_other_orchestrators_block()` читают текущие sessions из DB (`app/manager.py:54-93`), orchestrator prompt получает dynamic catalog/current workers (`app/manager.py:232-247`), а worker prompt форматируется второй раз после создания worktree, когда уже известна branch (`app/manager.py:516-523`). Это не чистый builder из template files; это runtime prompt assembler, завязанный на registry/DB/worktree.

`thought:` **3. "main.py mixes routes, SSE, auth, business logic"**

Контраргумент: да, `main.py` большой, но FastAPI-монолит с route handlers в одном файле для MVP не является архитектурной аварией. Большинство endpoints являются тонкими адаптерами над `manager`, `db`, `workspace`, `tm`, `bg_jobs`. Разнос по routers даст навигационную пользу, но не изменит runtime behavior.

`suggestion:` здесь я скорее соглашусь на поздний косметический split по bounded areas: `sessions_routes.py`, `tm_routes.py`, `bg_routes.py`, `files_routes.py`, `usage_routes.py`. Но это стоит делать после стабилизации tests, потому что часть endpoints содержит embedded policy: path safety (`app/main.py:246-300`), SSE polling (`app/main.py:477-508`), merge/switch per-session locks (`app/main.py:734-808`), GitHub webhook routing (`app/main.py:1505-1620`). Механический перенос без тестов легко потеряет middleware/import/lifespan coupling.

`thought:` **4. "Circular dependency"**

Контраргумент: заявленный circular dependency преувеличен. На верхнем уровне `manager.py` импортирует `AgentSession`, `AgentStatus`, `is_orchestrator_role` из `session.py` (`app/manager.py:14`). В `session.py` нет верхнеуровневого импорта `manager`; есть ленивый импорт `_prompt_template_hash` внутри `send()` (`app/session.py:251`). Это запах, но не import-time cycle.

`suggestion:` если трогать prompt code, можно вынести `_prompt_template_hash` и prompt helpers в `app/prompting.py`. Но это микрорефакторинг, не основание резать `AgentSession`.

`thought:` **5. "No backend protocol"**

Контраргумент: два backend'а уже используют достаточно ясный structural contract: `connect`, `send`, `events`, `interrupt`, `disconnect`, optional `reconnect`, optional `context_usage`, `session_id` (`app/backend_claude.py:137-192`, `app/backend_codex.py:52-238`). Жесткий ABC сейчас может навредить, потому что Claude и Codex реально асимметричны: Claude persistent client supports reconnect/context_usage/mid-turn query; Codex CLI is per-turn subprocess, `connect()` is intentionally no-op, reconnect отсутствует, context usage считается из JSON events.

`suggestion:` легкий `typing.Protocol` может быть полезен как документация для type checkers, но не как runtime abstraction layer. Если добавлять, то без factory hierarchy и без попытки привести Claude/Codex к одинаковому lifecycle там, где backend semantics разные.

### Concessions

`suggestion:` Claude прав, что крупные файлы увеличивают cognitive load. `AgentSession` на 975 LOC и `SessionManager` на 963 LOC уже требуют аккуратного чтения, а onboarding нового разработчика будет медленнее.

`suggestion:` Claude прав, что `main.py` стоит разнести позже. Это самый безопасный кандидат на file-level cleanup, потому что route grouping даст навигацию без изменения core state machine.

`suggestion:` Claude прав, что prompt composition можно сделать более явной областью. Но я бы начинал не с класса `PromptBuilder`, а с маленького `app/prompting.py`, куда переехали бы pure-ish helpers: frontmatter parsing, module loading, role prompt lookup, template hash. Dynamic blocks, завязанные на sessions/DB, нужно переносить осторожно.

`suggestion:` Claude прав, что backend contract стоит зафиксировать. Но достаточно Protocol/type hints/tests на contract, а не ABC с inheritance.

`nit:` `_backend: Optional[object]` в `AgentSession` снижает читаемость. Это можно заменить на `BackendLike | None` после введения Protocol, без изменения runtime.

### Verdict

`blocking:` не делать сейчас moderate refactoring `AgentSession -> SessionLifecycle/EventProcessor/MessageQueue/PersistenceManager`. Риск регрессий в ordering, async locks, compact/queue/reconnect/hibernate выше ожидаемой пользы.

`blocking:` не выделять `SpawnService` до появления тестов на create-session rollback, worktree creation, prompt formatting after branch assignment, parent/can_spawn и owned_dirs warnings.

`suggestion:` разрешенный минимальный план:

1. Добавить focused regression tests вокруг текущих инвариантов.
2. Вынести только prompt pure helpers в `app/prompting.py`, если это реально уменьшит lazy import из `session.py`.
3. Добавить `BackendLike` Protocol для документации и type checking, не меняя поведение backend'ов.
4. Позже разнести `main.py` по routers механически, маленькими PR, без изменения business logic.

Итог: текущая архитектура не "красивая", но прагматически правильная для стадии проекта. Главная ценность сейчас в сохранении локальности сложного runtime state. Рефакторинг должен следовать за тестами и конкретными болями, а не за метрикой LOC.

## Round 2 — 2026-06-02

### Re-review

`PARTIAL:` **1. Вынести prompt helpers в `app/prompting.py`**

Согласен с Claude в главном: это не тот же класс риска, что разрезание `AgentSession` или `create_session()`. `_parse_role_frontmatter()`, `_load_modules()`, `_role_prompt_file()`, `_skills_catalog()`, `_roles_catalog()`, `_prompt_template_hash()` в основном читают prompt files и возвращают строки (`app/manager.py:96-267`). Это можно делать раньше, не дожидаясь большого test harness.

Но "zero runtime risk" я бы не писал. Есть два конкретных риска:

`suggestion:` перенос должен избегать нового цикла `session -> prompting -> session`. Сейчас `session.py` лениво импортирует `_prompt_template_hash` из `manager.py` (`app/session.py:251`). Если новый `app/prompting.py` импортирует `is_orchestrator_role` из `app.session`, а `session.py` начнет импортировать `_prompt_template_hash` из `app.prompting`, получится ровно тот цикл, который мы хотим убрать. Значит, role predicate/constants нужно либо держать в `prompting.py`, либо вынести в маленький независимый `roles.py`.

`suggestion:` не надо притворяться, что весь prompt layer чистый. `ROLE_SYSTEM_PROMPT()` добавляет dynamic blocks `_other_orchestrators_block()` и `_workers_block()`, которые читают sessions из DB (`app/manager.py:54-93`, `app/manager.py:232-247`). Эти части можно оставить в `manager.py` или передавать как зависимости. Без этого `PromptBuilder` снова станет manager-with-another-name.

Вердикт по пункту: да, маленький `app/prompting.py` допустим сейчас, если переносить только file/template helpers и явно проверить imports.

`PARTIAL:` **2. Extract-method внутри `_handle_turn_end`**

Согласен: это не dangerous decomposition, если методы остаются private methods того же `AgentSession`. `_handle_turn_end()` делает слишком много за один экран: session id/cost accounting, token/context accounting, error logging, max-turns auto-continue, bg-job waiting, compact ack, scope idle, auto-compact, auto-report, pending flush, hibernate (`app/session.py:467-542`). Разбивка внутри класса может улучшить читаемость без friend-classes.

Риск не нулевой из-за порядка side effects:

`blocking:` ранний `return` при `sr in ("error_max_turns", "max_turns") and ok` сейчас предотвращает обычное завершение: не ставит IDLE/WAITING, не делает auto-report, не flush'ит pending, не hibernate'ит, а запускает `_auto_continue()` (`app/session.py:509-512`). Любой `_schedule_next_action()` должен сохранить этот early-exit.

`blocking:` `self.status` выставляется в `WAITING` или `IDLE`, затем сразу вызывается `_persist()` (`app/session.py:519-525`), и только после этого идут compact ack, scope idle notification, auto-compact, auto-report, pending flush, hibernate (`app/session.py:527-542`). Если helper-методы начнут сами вызывать `_persist()` или поменяют порядок, можно получить stale status или лишний auto-report.

`suggestion:` безопасный вариант: extract-methods без async и без новых объектов, например `_apply_turn_usage(meta)`, `_update_context_from_turn(meta)`, `_finish_turn_status() -> live_pct`, `_maybe_start_auto_compact(live_pct)`, `_finish_idle_actions()`. Но основной метод должен оставаться orchestration outline, где порядок виден.

Вердикт по пункту: да, но это должен быть маленький readability PR с line-by-line diff review, не "нулевой риск".

`PARTIAL:` **3. Split `main.py` по FastAPI routers**

Согласен, что `main.py` на 1655 LOC стоит резать. Не согласен, что это полностью механический low-risk split. В файле есть глобальный `manager = SessionManager()` (`app/main.py:29`), lifespan с порядком старта DB/manager/bg_jobs/tg/ssh/snapshot (`app/main.py:33-53`), middleware/auth на уровне app (`app/main.py:60-89`), shared Pydantic-модели, shared caches (`_git_status_cache`, `app/main.py:1198-1249`), глобальный `_tm` (`app/main.py:1285`) и даже переназначение `logger` для webhook (`app/main.py:1501`).

`blocking:` если routers будут импортировать `manager` из `app.main`, появится плохая зависимость `router -> main app`, а при include_router можно легко получить import-time side effects. Нужен маленький dependency module или router factory: например `app/deps.py` с `manager`, либо `create_sessions_router(manager)`.

`suggestion:` я бы резал не "все сразу", а от наименее связанного к наиболее связанному:

1. `tm_routes.py`: уже в основном делегирует в `app.tm`, но учесть, что `_tm` используется также в session merge/switch (`app/main.py:759`, `app/main.py:803`).
2. `bg_routes.py`, `proxy_routes.py`, `files_routes.py`: ограниченный surface.
3. `sessions_routes.py`: самый рискованный, потому что дергает private session methods (`_disconnect_backend`, `_persist`), session locks, SSE polling, workspace operations и manager internals (`app/main.py:477-808`).
4. `webhook_routes.py`: отдельно, но аккуратно с `logger = logging.getLogger("orchestra.webhook")`, чтобы не менять logger для остального файла.

Вердикт по пункту: да, split нужен, но как серия маленьких переносов с smoke test импорта app и пары endpoint checks. Не как один "mechanical" PR.

`AGREE:` **4. Добавить `BackendLike` Protocol**

Согласен. Это low-risk documentation/type-checking improvement, если не превращать его в runtime hierarchy. Базовый Protocol должен описывать только реально общий контракт: `session_id`, `connect()`, `send()`, `events()`, `interrupt()`, `disconnect()`. `reconnect()` и `context_usage()` лучше оставить optional через `hasattr`, потому что ClaudeBackend и CodexBackend действительно имеют разные lifecycle semantics (`app/backend_claude.py:137-192`, `app/backend_codex.py:52-238`).

`suggestion:` положить Protocol в независимый модуль вроде `app/backend_protocol.py`, который импортирует только `AsyncIterator` и `AgentEvent`. Не класть его в `backend_claude.py`/`backend_codex.py`, чтобы не создавать backend-to-backend coupling.

### Verdict раунда

Мы сошлись по главным архитектурным рискам: не резать `AgentSession` на сервисы, не создавать `SpawnService`, не вводить ABC/factory hierarchy для backend'ов.

Моя обновленная позиция:

`AGREE:` `app/prompting.py` можно делать сейчас, если scope ограничен file/template helpers и перенос не создает новый import cycle.

`AGREE:` `_handle_turn_end()` можно разбить private helper-методами внутри `AgentSession`, если сохранить видимый порядок side effects и early return для max_turns.

`PARTIAL:` `main.py` надо split'ить, но не одним большим "mechanical" переносом. Начинать с менее связанных routers, а session routes оставить на отдельный аккуратный шаг.

`AGREE:` `BackendLike` Protocol полезен как typing/documentation-only слой, без runtime enforcement.

Итоговый компромисс: допустимы малые локальные рефакторинги, которые не меняют state ownership. Все, что пересекает lifecycle/queue/persistence/worktree transaction boundary, остается под запретом без regression tests.

## Round 3 (Final) — 2026-06-02

### Consensus

Финальный консенсус:

1. `AGREE:` не резать `AgentSession` на `SessionLifecycle/EventProcessor/MessageQueue/PersistenceManager`. Runtime state должен оставаться в одном агрегате.
2. `AGREE:` не создавать `SpawnService`. `SessionManager.create_session()` остается транзакционным orchestration boundary с rollback рядом с worktree/DB side effects.
3. `AGREE:` вынести `app/prompting.py`, но только file/template helpers и с проверкой imports.
4. `AGREE:` разбить `_handle_turn_end()` private helper-методами внутри `AgentSession`, сохранив видимый порядок side effects и early return для `max_turns`.
5. `AGREE:` добавить `BackendLike` Protocol как typing/documentation-only контракт, без ABC, factory hierarchy и runtime enforcement.
6. `PARTIAL:` `main.py` split нужен, но безопасная стратегия — поэтапная. Первый шаг: `deps.py` + самые слабосвязанные routers.

### deps.py Design

`app/deps.py` должен быть маленьким shared-dependencies module, а не новой свалкой глобалов.

Конкретное содержимое:

```python
from app.manager import SessionManager
from app import tm as tm

manager = SessionManager()

def get_manager() -> SessionManager:
    return manager

def get_tm():
    return tm

def get_bg_manager():
    from app.bg_jobs import bg_manager
    return bg_manager
```

`manager` можно держать как singleton в `deps.py`, потому что он уже singleton в текущем `main.py` (`app/main.py:29`), и весь runtime завязан на один registry sessions.

`tm` стоит экспортировать из `deps.py` сразу, потому что task-manager API использует `_tm` напрямую (`app/main.py:1285-1449`), но session endpoints тоже вызывают `_tm.link_commits_to_task()` и `_tm.api_update_task()` в merge/switch flows (`app/main.py:759`, `app/main.py:803`). Если `tm_routes.py` уедет первым, session routes/main все равно должны брать тот же модуль из общего места.

`bg_manager` лучше отдавать через `get_bg_manager()` с lazy import. Он нужен lifespan'у (`app/main.py:40-42`, `app/main.py:52`) и bg endpoints (`app/main.py:1463-1496`). Lazy import снижает шанс import-time coupling между `deps.py`, `bg_jobs.py` и будущими routers.

Что должно остаться в `main.py`:

`app = FastAPI(...)`, lifespan wiring, `app.mount("/static", ...)`, auth middleware registration, global exception handler, root/login pages until отдельный `web_routes.py`, and `include_router(...)`. `main.py` должен стать composition root, а не provider всех зависимостей.

Что НЕ класть в `deps.py`:

`templates`, route request models, `_git_status_cache`, usage cache, path safety helpers, webhook logger, OAuth helpers, file upload constants. Эти вещи должны жить рядом со своими routers/modules. Иначе `deps.py` быстро станет вторым `main.py`.

Первый router PR:

1. Создать `app/deps.py`.
2. В `app/main.py` заменить `manager = SessionManager()` на `from app.deps import manager`.
3. Создать `app/routes/tm.py` и перенести `TmTaskCreate`, `TmTaskUpdate`, `TmPaymentReceive`, `_resolve_client_id`, `/api/tm/*`.
4. Создать `app/routes/bg.py` и перенести `BgJobCreateRequest`, `/api/bg/jobs`.
5. В `main.py` подключить `app.include_router(tm_router)` и `app.include_router(bg_router)`.
6. Smoke checks: `python -m py_compile app/*.py app/routes/*.py`, `python -c "import app.main"`, ручная проверка `/api/tm/tasks` и `/api/bg/jobs` на dev server.

### Top 3 Changes for 1 Day

`1.` **Dependency cleanup: `app/prompting.py` + `BackendLike` Protocol**

Файлы:

- создать `app/prompting.py`;
- создать `app/backend_protocol.py`;
- обновить `app/manager.py`;
- обновить `app/session.py`;
- обновить `app/main.py` import для prompt endpoint (`app/main.py:435-462`).

Что именно:

- перенести `_parse_role_frontmatter()`, `_load_modules()`, `_role_prompt_file()`, `_skills_catalog()`, `_roles_catalog()`, `_prompt_template_hash()` из `manager.py` в `prompting.py`;
- не переносить dynamic `_workers_block()` / `_other_orchestrators_block()` без dependency injection;
- убрать ленивый импорт `_prompt_template_hash` из `session.py:251`, заменить на импорт из `app.prompting`;
- добавить `BackendLike` Protocol с общим контрактом `session_id`, `connect`, `send`, `events`, `interrupt`, `disconnect`;
- типизировать `_backend: BackendLike | None` в `AgentSession`, optional `reconnect/context_usage` оставить через `hasattr`.

Почему первое: это уменьшает связность `manager.py`, документирует backend contract и почти не трогает runtime behavior.

`2.` **Readability refactor `_handle_turn_end()` внутри `AgentSession`**

Файл: `app/session.py`.

Что именно:

- выделить `_apply_turn_result(meta)`: session id, cost deltas, totals;
- выделить `_update_context_from_turn(meta)`;
- выделить `_finish_turn_status()`: bg job check, `IDLE/WAITING`, `_persist()`;
- выделить `_after_turn_idle_actions(live_pct)`: compact ack, notify scope idle, auto-compact, auto-report, pending flush/hibernate;
- оставить в `_handle_turn_end()` главный порядок: parse meta -> apply usage -> handle errors -> early return max_turns -> log status -> finish status -> after-turn actions.

Обязательное условие: early return для `max_turns` (`app/session.py:509-512`) должен остаться до обычного `IDLE/WAITING` завершения. `_persist()` после status update (`app/session.py:519-525`) должен остаться до post-turn actions.

Почему второе: это улучшает самый плотный участок core state machine без изменения ownership и без новых классов.

`3.` **First `main.py` split: `deps.py`, `tm_routes.py`, `bg_routes.py`**

Файлы:

- создать `app/deps.py`;
- создать `app/routes/__init__.py`;
- создать `app/routes/tm.py`;
- создать `app/routes/bg.py`;
- обновить `app/main.py`.

Что именно:

- перенести `/api/tm/*` endpoints (`app/main.py:1316-1449`) в `app/routes/tm.py`;
- перенести `/api/bg/jobs` endpoints (`app/main.py:1463-1496`) в `app/routes/bg.py`;
- `main.py` оставить composition root и подключить routers;
- session merge/switch пока оставить в `main.py`, но заменить прямой `_tm` на dependency из `app.deps`, чтобы следующий split не создавал дублирующих imports.

Почему третье: это дает реальное уменьшение `main.py` без захода в самые рискованные session/SSE/workspace endpoints.

### Final Verdict

Текущая архитектура Orchestra адекватна стадии MVP: она плоская, state ownership в ключевых местах виден, а самые опасные операции держат side effects рядом с rollback/locking. Это не "чистая архитектура", но это рабочая архитектура для одного разработчика и малого числа пользователей.

Рефакторинг нужен, но не вокруг абстрактных паттернов. Правильное направление: уменьшать import coupling и размер файлов там, где это не меняет владельца состояния. Неправильное направление: дробить core lifecycle на сервисы ради LOC.

Финальная оценка: architecture acceptable; targeted cleanup recommended; broad decomposition rejected.
