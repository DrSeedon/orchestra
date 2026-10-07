# V-745: isolate quota policy history writes

## Источник записи

В production `data/orchestra.db` строка `quota_policy_history.id=1` до исправления имела `effective_from=1791366137.5606716` (`2026-10-07T09:42:17.560672Z`), `source=observed` и policy с `claude_night_quota_share=0.057`.

Источник нашёлся в журнале инструментов сессии `feat-ratelimit`, scope `/home/kesha/orchestra`. В `2026-10-07T09:42:17.454456Z` Bash выполнил Python-probe таблицы значений. Его код импортировал `line_limit, quota_policy` и вызвал `policy = quota_policy()`; строка появилась через 106 мс. На тот момент `quota_policy()` по умолчанию вызывал `_persist_quota_policy()`, а импортированный `app.db.DB_PATH` разрешился в production DB. Это был отдельный процесс агента из worktree, не PID сервиса `378413`.

Журнал фиксирует следующий инструментальный вызов в той же сессии в `09:42:55Z`: `python -m pytest` по четырём точечным тестам. Он не создал эту строку: `tests/conftest.py::_isolate_production_db` удаляет `ORCHESTRA_DB_PATH` до импорта приложения, затем подменяет `db.DB_PATH` на `tmp_path/orchestra.db` и запрещает SQLite открывать production-файл. Проба была исполнена вне pytest и обошла эти защиты.

## Исправление

`quota_policy()` теперь только читает текущую конфигурацию. Запись истории выполняет отдельный observer и startup initializer, оба допускают запись только если `LISTEN_PID` совпадает с PID процесса и `LISTEN_FDS > 0`. Эти значения есть у socket-activated сервиса; унаследованные дочерним CLI значения не пройдут PID-сверку. Маршрут quota map наблюдает изменения `.env` через observer; обычные импорты, расчёты гейта и вызовы `quota_policy()` не создают историю.

На startup добавлена миграция, которая действует только на `id=1`, ожидаемый старый timestamp, `source=observed` и поля именно V-744 policy (`shift=8`, `day_start=8`, `night_share=0.057`). Уже исправленная строка даёт no-op; несовпадающая строка не меняется и оставляет warning в журнале.

Перед коррекцией production DB сделан online backup через `sqlite3.Connection.backup()` в `/home/kesha/orchestra/data/orchestra.db.v745-backup-20261007.sqlite`: 3,304,108,032 байта, `PRAGMA integrity_check` вернул `ok`.

Точное время сверено по `systemctl show orchestra.service -p ActiveEnterTimestamp`: `Wed 2026-10-07 12:42:41 CEST`. Это `2026-10-07 10:42:41 UTC`, epoch `1791369761` (`date -u -d @1791369761`); CEST здесь UTC+02:00. В миграции `id=1.effective_from` изменён с `1791366137.5606716` на `1791369761.0`. Лог: `V-745 quota history correction applied: id=1 effective_from 1791366137.560672 -> 1791369761`. Проверка после миграции подтвердила `(id=1, effective_from=1791369761.0, source=observed)`. Policy строки не менялась; реконструированные строки `id=2` (2026-09-29T00:00:00Z) и `id=3` (2026-10-06T04:43:00Z) остались без изменений. Поскольку API истории сортирует по effective time, day/night policy теперь начинается на графике с фактического рестарта.

## Проверки

Команда `uv run --frozen python -m pytest tests/test_quota_gate.py tests/test_quota_admission_e2e.py tests/test_quota_wait_queue.py tests/test_quota_map_api.py tests/test_quota_headroom_447.py tests/test_usage_readiness.py tests/test_mcp_quota_gate.py tests/test_codex_quota_103.py tests/test_turn_ended_no_quota_suffix.py tests/test_t344_quota_lines_browser.py tests/test_audit0901_sysquota.py tests/test_model_gates.py -q` завершилась: `204 passed in 75.19s`. Набор включает browser-тест исторической/текущей линии. Новые проверки подтверждают, что вызов `quota_policy()` и initializer из не-сервисного процесса не создают БД, initializer socket-activated процесса сохраняет стартовую историю, а миграция исправляет только известную строку и становится no-op при повторе.

Импортированный `app.quota_gate`: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-ratelimit/app/quota_gate.py`. `git diff --check` прошёл; после browser-тестов `.orchestra/tasks/V-652/quota-timeline.png` восстановлен.

Python-изменения требуют рестарта Orchestra, чтобы новый запрет случайной записи начал действовать в сервисе; рестарт не выполнялся. Исправление строки истории уже применено к production DB и само по себе рестарта не требует.
