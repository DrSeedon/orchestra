# Codex / Sol runtime fixes — 2026-07-16

## Результат

Orchestra адаптирована к фактической телеметрии Codex CLI. Исправлены ложные 100% контекста, повторная тарификация всей истории после resume/restart, неверная цена cached input, бесконечные retry terminal-лимитов и ложный успех `codex_review` без итогового артефакта.

Изменения применены рестартом `orchestra.service` и проверены живыми Sol/Codex-запусками.

## Что было сломано

1. Dashboard делил cumulative usage на hardcode `997500`. Реальный effective window текущей Sol-сессии, записанный Codex rollout, равен `258400`; поэтому значения `761k/998k`, `6035k/998k` и `100%` не описывали занятое окно.
2. `turn.completed.usage` у Codex на resume накопительный. После рестарта Orchestra принимала весь thread usage за новый ход и повторно начисляла десятки долларов.
3. Cached input считался по цене fresh input. Для Sol используется эквивалент API-цен: `$5/M` fresh input, `$0.50/M` cached input, `$30/M` output.
4. `monthly spend limit` не классифицировался как terminal limit, а retry counter обнулялся после каждого неуспешного turn. Получался бесконечный цикл `(1/3)`.
5. `codex_review` мог повторно использовать stale `.rc=0` после рестарта, объявить успех без output/verdict, перезаписать содержательный файл коротким final message или зависнуть на stdout, удерживаемом дочерним MCP-процессом.

## Реализация

- Контекст читается из последнего rollout `token_count.last_token_usage` вместе с runtime `model_context_window`. При отсутствии корректной телеметрии состояние помечается unknown, а cumulative usage больше не показывается как заполнение окна.
- Перед resume сохраняется baseline cumulative totals; в событие turn передаётся только delta текущего запуска. Cached tokens тарифицируются отдельно.
- Terminal subscription limits не ретраятся. Бюджет transient retry сбрасывает только новое внешнее сообщение пользователя.
- `run` background job теперь различает success и failure по exit code, умеет требовать непустой artifact и regex-инвариант, а при ошибке явно будит воркера сообщением `FAILED`.
- `codex_review` пишет сначала во временный `.round`, проверяет структуру, атомарно сохраняет/добавляет раунд и атомарно обновляет `codex_sessions.json`. Stale temp-файлы удаляются перед каждым запуском.
- После завершения job stdout дренируется ограниченное время. Если job-specific потомок оставил pipe открытым, завершается только выделенная process group, поэтому завершённый review больше не висит до общего timeout.
- Proxy env наследуется процессом Codex и остаётся привязанным к единому источнику `/mnt/data/Projects/Python/orchestra/.env`.

## Проверка

- Узкий regression suite: `103 passed, 1 deselected`. Исключён известный flaky `test_auto_report_fires_after_idle_timeout`.
- `python -m py_compile` для изменённых runtime-модулей: успешно.
- `git diff --check`: успешно.
- Sol smoke после первого рестарта ответил `SOL_RUNTIME_FIX_OK`; dashboard показал `58%`, а новый ход стоил `$0.12` вместо повторных `$30.82`.
- Финальный live `codex_review` после второго рестарта: job `bg-96e61cfa1a`, статус `triggered`, error отсутствует; output непустой и содержит `## Summary`, `## Findings`, `## Verdict`.
- Отдельный runtime smoke оставил дочерний процесс с открытым stdout: Orchestra распознала завершение лидера, закрыла его process group и перевела job `bg-da7d69b933` в `triggered`, не дожидаясь 15-секундного timeout.
- После рестарта `orchestra.service` active. `scripts/check-proxies.sh` подтвердил Contabo DE `127.0.0.1:12343`; Orchestra, Codex launchers и Cursor используют этот маршрут из `.env`.

## Оставшийся риск

- Уже накопленные исторические суммы в БД не переписаны: новые turns считаются правильно, но старые `$30+` остаются в истории. Автоматическая миграция без надёжного per-turn baseline могла бы заменить одну ложную цифру другой.
- Формат внутренних rollout events не является публичным стабильным API. Парсер работает fail-soft; при изменении формата dashboard покажет unknown вместо ложного процента.
- Полный pytest suite не подтверждён: ранний общий прогон был прерван, а расширенный targeted suite ранее показал четыре известные несвязанные ошибки (flaky timer и manager persistence/MagicMock tests). Для затронутых контрактов regression suite зелёный.
