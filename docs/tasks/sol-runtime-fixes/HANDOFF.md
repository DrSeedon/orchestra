# Handoff: адаптация Orchestra под Codex / Sol

Дата: 2026-07-16  
Статус: runtime-фиксы применялись ранее; новые фиксы ложных Codex/Claude timeout и Claude interrupt реализованы и протестированы, но сервис после них не перезапускался. Изменения не закоммичены.

## Дополнение: ложная смерть Codex turn на 600-й секунде

- `research-grok-build` не завис: с `16:37:00` до `16:46:58` от него продолжали приходить tool events. Orchestra убила backend ровно в `16:47:00` собственным `asyncio.timeout(600)`.
- Прокси действительно оборвался в `16:43:53`, но Codex восстановил HTTPS transport к `16:44:10` и продолжил работу. Это сопутствующий сбой, не причина убийства.
- Удалён абсолютный timeout всего Codex turn. Завершение теперь определяется потоком Codex (`turn.completed`/exit) или явным interrupt.
- Heartbeat после 10 минут тишины не убивает живой Codex: recovery происходит только если исчез backend, завершился subprocess или умер listener. Тишина живого процесса только логируется.
- `thread_id` сохраняется сразу по `thread.started`, поэтому restart/обрыв до `turn.completed` больше не лишает Orchestra возможности `codex exec resume`.
- Исправлен self-cancel: `_disconnect_backend()` больше не отменяет и не `await`-ит heartbeat, если вызван из самого heartbeat.
- Регрессионные тесты: `6 passed` для новых контрактов; расширенный набор — `72 passed, 1` известный несвязанный flaky `test_auto_report_fires_after_idle_timeout`. `compileall` и `git diff --check` прошли.
- Для применения нужен явный рестарт `orchestra.service`; по правилам проекта в этой сессии он не выполнялся.

## Дополнение: Claude SDK turn timeout и interrupt

- В БД найдено `76` ложных `Turn timeout (600s)` у `32` Claude-сессий за 2026-07-09—16.
- Старый код проверял возраст turn только при получении очередного события. После 600 секунд он выбрасывал именно это событие через `continue` и инжектил `[system] Turn timed out...` в живой SDK-stream; это могло разорвать пару `tool_use/tool_result` и породить `stop_reason=tool_use`.
- Удалён абсолютный Claude turn timeout. Реальные stream failures по-прежнему проходят через существующий reconnect с лимитом пяти последовательных ошибок; heartbeat следит за listener отдельно.
- SDK `interrupt()` внутри ждёт control response до `60s`. Orchestra теперь ждёт acknowledgement максимум `5s`; при timeout/error закрывает backend, чтобы модель не продолжала работать после отображения `idle`.
- Состояние `idle` публикуется до ожидания control response под lifecycle lock. Новое сообщение ждёт завершения interrupt и начинает чистый turn вместо mid-turn injection.
- Явный interrupt подавляет stale auto-report оборванного turn; следующий новый/queued/compact turn сбрасывает этот флаг.
- `claude-agent-sdk` обновлён с `0.2.87` до `0.2.114`; минимальная версия `0.2.111`, где Anthropic исправил zombie CLI subprocess при asyncio cancellation.
- Проверка затронутого набора: `64 passed, 1 deselected`; расширенный lifecycle/API/manager набор: `203 passed, 4 deselected` (известный flaky auto-report и три несвязанных manager-теста). `compileall` и `git diff --check` прошли.

## Что сделано

- Исправлен расчёт контекста Sol: Orchestra читает последнее `last_token_usage` и `model_context_window` из Codex rollout вместо cumulative usage и неверного hardcode `997500`. Runtime fallback для GPT-5.6 — `258400`.
- Исправлена стоимость: после resume учитывается только delta текущего запуска, cached input тарифицируется отдельно. Новый Sol smoke стоил `$0.12` вместо повторного начисления `$30.82`.
- Исправлены retry лимитов: monthly/weekly subscription limit считается terminal; transient retry counter сбрасывается только новым сообщением пользователя.
- Исправлен `codex_review`: stale temp-файлы очищаются, результат сначала пишется в `.round`, затем валидируется и атомарно сохраняется; resume атомарно добавляет новый раунд и обновляет `codex_sessions.json`.
- Background `run` job теперь различает success/failure по exit code, проверяет обязательный artifact/verdict и отправляет воркеру явный `FAILED`.
- Устранено зависание, когда дочерний Codex MCP держит stdout открытым после завершения команды: Orchestra ждёт exit процесса-лидера отдельно и завершает только оставшуюся job process group.
- Codex наследует proxy env Orchestra. Источник истины не менялся: `/mnt/data/Projects/Python/orchestra/.env`; активный маршрут — Contabo DE `127.0.0.1:12343`.

## Основные файлы

- Runtime и accounting: `app/backend_codex.py`, `app/models.py`, `app/session_cost.py`.
- Retry/state machine: `app/session.py`, `app/session_turns.py`.
- Review/background jobs: `app/mcp_stdio.py`, `app/bg_jobs.py`, `app/codex_review_artifact.py`.
- Тесты: `tests/test_backend_codex.py`, `tests/test_bg_jobs.py`, `tests/test_p4_cost.py`, `tests/test_session.py`, `tests/test_codex_review_artifact.py`, `tests/test_mcp_codex_review.py`.
- Полный технический отчёт: `docs/tasks/sol-runtime-fixes/report.md`.

## Проверено

- Targeted suite: `103 passed, 1 deselected`; исключён известный flaky `test_auto_report_fires_after_idle_timeout`.
- `py_compile` и `git diff --check` прошли.
- Live Sol smoke: корректный процент контекста и delta-cost.
- Live `codex_review`: job `bg-96e61cfa1a` завершён как `triggered`, artifact содержит `Summary / Findings / Verdict`.
- Live orphan-pipe smoke: job `bg-da7d69b933` завершён как `triggered` до timeout.
- `orchestra.service` — `active`; `scripts/check-proxies.sh` подтверждает Contabo `:12343`.

## Что осталось

- Не переписывать исторические `$30+` автоматически: эти значения уже сохранены ошибочно, а надёжного per-turn baseline для миграции нет. Новые turns считаются правильно.
- Внутренний формат Codex rollout не является стабильным API. Парсер работает fail-soft: при изменении формата контекст станет unknown, а не ложными `100%`.
- Полный pytest suite не подтверждён; targeted suite затронутых контрактов зелёный.
- Перед коммитом проверить общий dirty worktree и не откатить чужие изменения. В `app/backend_codex.py` до этой задачи уже была правка 16 MB stream/readline — она сохранена и интегрирована.
