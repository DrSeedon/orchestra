## Tests

Команда из задания `uv run python -m pytest -q` не дошла до pytest: `uv` упал на инициализации кэша `/home/maxim/.cache/uv` из-за read-only FS (`os error 30`). Повтор с `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q` не завершился и не вывел результатов за несколько минут; pass/fail count получить не удалось.

## Summary

#24 в целом готов: схема “хранить только custom, на старте пересобирать orchestra+custom” соответствует текущему коду.

#25 требует правки семантики frontmatter и ясного ответа, является ли это guardrail или security policy.

#26 требует доработки до реализации: миграция `bg_jobs` сейчас самый рискованный кусок, плюс cron-fire должен проверять актуальный статус job перед отправкой.

## #24 Findings

1. `app/manager.py:466`, `app/manager.py:505`, `app/session.py:777` — план парсит `mcp_servers_custom` из БД, но не требует, чтобы результат был dict. Если в колонке окажется JSON не-объект (`[]`, `"x"`), `_make_mcp_config(..., extra=custom)` упадет на `extra.items()` при восстановлении сессии, то есть сломает restart-survival для этой сессии. Fix: после `json.loads` делать `if not isinstance(custom, dict): log warning; custom = {}`; тот же sanitizer использовать на create-path перед сохранением.

## #25 Findings

1. `app/manager.py:92` — предложенный `val = meta.get("can_spawn", None)` не различает “поля нет” и “поле есть, но YAML null”: `can_spawn:` через `yaml.safe_load` даст `{"can_spawn": None}`. Это прямо ломает заявленную absent-vs-empty/present семантику на краю формата. Fix: проверять наличие ключа отдельно: `if "can_spawn" not in meta: return None`; затем читать `val = meta["can_spawn"]`; `None`/не-list трактовать как malformed fail-open с warning.

2. `app/main.py:365`, `app/manager.py:305`, `app/mcp_stdio.py:67` — план валидирует parent role через `parent_name`, который приходит от клиента. Если это должно быть ограничение безопасности, а не подсказка для честного `spawn_worker`, API caller может указать permissive parent и обойти `can_spawn`. Fix: либо явно документировать как advisory guardrail, либо выводить parent identity server-side из доверенного контекста. Минимально: не считать `parent_name` из произвольного `/api/sessions` security boundary; для MCP-path можно передавать caller role/name из stdio env, но тогда это тоже доверие к локальному MCP процессу.

## #26 Findings

1. `app/db.py:234`, `app/db.py:171` — rebuild `bg_jobs` через `executescript` в `_migrate` опасен для data integrity. В Python `sqlite3.executescript()` делает implicit commit перед скриптом; “существующий transaction” из `with _conn()` не гарантирует атомарный rename/create/copy/drop. Ошибка посередине может оставить `bg_jobs_old`, неполную новую таблицу или потерянные индексы. Fix: делать rebuild в явном `SAVEPOINT`/`ROLLBACK TO` или отдельными `execute` внутри контролируемой транзакции; тест должен падать искусственно между rename и drop и проверять, что старая таблица восстановлена.

2. `app/db.py:171`, `app/db.py:633` — миграционный `CREATE TABLE bg_jobs` в плане описан как `... no type CHECK ...`. Здесь нельзя оставлять псевдокод: `bg_save_job` пишет конкретный набор колонок (`id,type,config,message,target_session_id,target_name,target_scope,created_by_name,status,expires_at,trigger_at,created_at,last_output`), а restore/list читают `triggered_at`, `error`. Fix: в плане зафиксировать полный DDL и `INSERT INTO bg_jobs (<explicit columns>) SELECT <same columns> FROM bg_jobs_old`; не использовать `SELECT *`.

3. `app/bg_jobs.py:203`, `app/bg_jobs.py:227` — план одновременно говорит “для no-expiry передать `timeout=None`” и “на restore far-future remaining acceptable”. После рестарта `restore_from_db` знает только `expires_at`, поэтому `None` уже не восстановить без отдельного маркера. Это не обязательно ломает работу, но делает поведение зависимым от 100-летнего sentinel и расходится с моделью runner. Fix: либо хранить `no_expiry: true` в `config` и восстанавливать `timeout=None`, либо явно принять sentinel-модель и убрать инструкцию про `None`.

4. `app/bg_jobs.py:71` планового runner — если finite cron timeout истекает раньше следующего cron fire, код делает `break` и сразу вызывает `_expire(job_id)`. Job истечет немедленно при старте, а не в `expires_at`. Fix: если `next_fire > deadline`, спать до deadline и только потом expire, либо завести отдельный deadline wait.

5. `app/bg_jobs.py:249`, `app/db.py:678`, `app/db.py:687` — `_fire_cron` в плане отправляет сообщение без DB-guard, что job все еще `active` и не `expires_at < now`. При cancel/expire между пробуждением cron task и `session.send()` возможен лишний fire уже отмененной/истекшей job. Fix: добавить DB helper вроде `bg_cron_should_fire(job_id)`, который атомарно проверяет `status='active' AND expires_at>=now` прямо перед send; после send `bg_cron_record_fire` обновляет только `WHERE status='active'`.

6. `app/db.py:1`, `docs/tasks/26/plan.md` helper `bg_cron_record_fire` — `db.py` сейчас не импортирует `json`, а helper использует `json.loads/json.dumps`. В плане это помечено как “verify”, но для реализации это must-have, иначе первый успешный cron-fire упадет и счетчик не запишется. Fix: добавить `import json` в `app/db.py` рядом с текущими импортами.

7. `app/db.py:110` планового `bg_cron_record_fire` — read-modify-write `SELECT config` → mutate → `UPDATE ... WHERE status='active'` не защищает от lost update, если по багу запустятся два cron task на один job id. В текущем single-process это низкий риск, но именно restart-survival код уже опирается на `_tasks` как runtime guard. Fix: внутри helper брать write lock (`BEGIN IMMEDIATE`/transaction), перечитывать status+config и обновлять в той же транзакции; если status уже не active, не писать `last_output`.

## Verdict

#24: ready после type-check parsed custom JSON.

#25: needs work.

#26: needs work.
