# Handoff: адаптация Orchestra под Codex / Sol

Дата: 2026-07-16  
Статус: реализовано, применено рестартом, live E2E пройден. Изменения не закоммичены.

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
