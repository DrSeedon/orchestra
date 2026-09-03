# Handoff: provider runtimes и lifecycle сабагентов

Дата: 2026-07-17
Репозиторий: `/mnt/data/Projects/Python/orchestra`

## Задание следующей сессии

Не повторяй завершённый runtime-рефакторинг. Исправь оставшуюся гонку сохранения
`started_at` / `ended_at` у Claude SDK sub-agents и background tasks, добавь
регрессионный тест, выполни проверки и закоммить исправление напрямую через Git.

Перед работой прочитай корневой `AGENTS.md`, затем проверь `git status` и текущий
`HEAD`: после создания этого handoff история могла измениться.

## Уже сделано

Основные завершённые коммиты:

- `cd3dce1` — `refactor: make agent runtimes provider-agnostic`
- `41c7dc4` — `fix: correlate subagent lifecycle events`
- `4365d06` — `fix: close late SSE subscribers during restart`

Между ними есть чужой несвязанный коммит `ebd8cd7 document RAG VPS deployment`.
Не откатывай и не переписывай его.

Реализовано:

- `app/runtime_registry.py` отделяет Orchestra от конкретного backend: runtime
  регистрирует capabilities, factory и reconnect/liveness-контракты;
- модели маршрутизируются через registry, а плагины подключаются через
  `ORCHESTRA_RUNTIME_PLUGINS`;
- Claude, Codex и OpenCode используют общий lifecycle-контракт;
- idle-переключение Claude ↔ Codex сохраняет DB/UI-историю Orchestra и передаёт
  ограниченный provider-neutral handoff. Provider-native session, скрытый
  reasoning/cache и незавершённые tool calls между провайдерами не переносятся;
- абсолютные 600-секундные timeout для живых Claude/Codex turns удалены;
- restart корректно закрывает SSE, включая поздних подписчиков;
- Claude SDK `Task*` events связываются по `parent_tool_use_id → task_id`;
- UI отдельно показывает настоящих SDK-агентов и `local_bash` background tasks,
  не предлагает фиктивный transcript для bash-задач и буферизует
  stream-before-start race.

## Что уже проверено

- Полный suite после lifecycle-фиксов: `647 passed, 21 skipped, 4 deselected`.
- После late-SSE фикса: `30 passed` targeted.
- `compileall`, `node --check app/static/js/app.js`, `git diff --check` — зелёные.
- Live restart завершался штатно, без `SIGKILL` и timeout.
- SQLite `PRAGMA integrity_check` возвращал `ok`.
- Headless Chrome:
  - `seedon-orchestrator`: `0` SDK agents, `39` background tasks, без фиктивных
    transcript-кнопок;
  - `mass-job-hunter`: `14` SDK agents, рабочие JSONL transcripts.

Четыре deselected-теста были несвязаны с этой задачей:

- `tests/test_pipeline.py::TestSchemaValidation::test_invalid_model_in_defaults_rejected`
- `tests/test_pipeline.py::TestSchemaValidation::test_invalid_model_in_role_rejected`
- `tests/test_tg_bridge.py::TestResultImagesEnabled::test_default_false_without_env`
- `tests/test_workspace.py::TestCreateWorktree::test_rollback_on_copy_failure`

## Подтверждённый оставшийся баг

В production-данных `seedon-orchestrator` найдена историческая строка:

```text
description: Commit and push email update to site
status:      completed
started_at:  2026-07-16T09:40:36.722213+00:00
ended_at:    2026-07-16T09:40:36.722100+00:00
```

`ended_at` оказался на 113 микросекунд раньше `started_at`.

Причина:

1. `AgentSession._persist_subagent()` в `app/session.py` отправляет start,
   progress и end как независимые fire-and-forget jobs.
2. Общий `_db_executor()` имеет четыре worker thread.
3. `subagent_upsert()` в `app/db.py` назначает `started_at` в момент фактического
   INSERT.
4. Если end-job исполнился первым, он создаёт строку со своим поздним
   `started_at`; пришедший затем start-job его не исправляет.

Обычный concurrent upsert тест проверяет сохранность полей, но не инверсию
порядка lifecycle-событий.

## Ожидаемое исправление

Сохрани текущую fire-and-forget архитектуру, но сделай timestamps устойчивыми к
любому порядку выполнения:

1. В `AgentSession._persist_subagent()` фиксируй timestamp в event-loop до
   отправки job в executor.
2. Для lifecycle `phase == "start"` передавай явный `started_at`; для end —
   явный `ended_at`.
3. В `subagent_upsert()` используй переданный `started_at` при INSERT и при
   конфликте сохраняй самое раннее известное начало.
4. Убедись, что end-before-start после второго upsert даёт
   `started_at <= ended_at`, а API вычисляет неотрицательную длительность.
5. Не сериализуй весь DB executor и не добавляй отдельную очередь ради одной
   строки: явные timestamps + идемпотентный upsert закрывают гонку проще.

Если точная форма SDK start metadata отличается, сначала посмотри места вызова
`_persist_subagent()` в `AgentSession._handle_event()`. Не угадывай `phase`.

## Обязательные тесты

Минимум:

1. Регрессия в `tests/test_subagents.py`: сначала выполнить end-upsert с
   фиксированным `ended_at`, затем start-upsert с более ранним фиксированным
   `started_at`.
2. Проверить, что описание/type от start сохранились, статус end не затёрся,
   `started_at <= ended_at`, а duration не отрицательный.
3. Если меняется `_persist_subagent()`, добавить узкий тест передачи timestamp
   start-события, а не полагаться только на DB unit test.

Команды приёмки:

```bash
pytest -q tests/test_subagents.py tests/test_subagent_routes.py tests/test_backend_stream.py
python -m compileall -q app tests
node --check app/static/js/app.js
git diff --check
pytest -q
```

После тестов разрешён restart `orchestra.service` для live-проверки. Сначала
сообщи пользователю, что перезапускаешь сервис. После рестарта проверь:

- сервис снова `active`;
- `/api/subagents/{session_id}` отдаёт раздельные `kind=agent|background`;
- длительности не отрицательные;
- transcript доступен только настоящим SDK agents.

## Ограничения

- Git выполняй напрямую в этой сессии. Не запускай Orchestra-агента ради
  `git add`, `commit`, `push` или проверки статуса.
- Не используй subagents, если пользователь отдельно их не попросил.
- Не делай push, VPS-операции и миграцию исторических строк без отдельной
  просьбы.
- Не раскрывай содержимое `.env`, токены и credentials. Proxy берётся только из
  `/mnt/data/Projects/Python/orchestra/.env`.
- Не смешивай сюда несвязанные 404 `/api/tm/payments/status`: они относятся к
  проектам без настроенного клиента и не являются частью subagent lifecycle.
- Background `local_bash` не имеет transcript по дизайну; не пытайся его
  «восстановить».

## Критерий готовности

Готово, когда end-before-start regression зелёный, targeted и полный suite
прошли либо точно задокументированы только известные несвязанные падения, live
restart не оставляет зависших turns/SSE, а исправление закоммичено отдельным
локальным коммитом без чужих файлов.
