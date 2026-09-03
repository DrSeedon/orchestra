# Исследовательский срез: работают ли правила

## Наблюдения

- **CONFIRMED.** Телеметрия покрывает 58 611 записей с `2026-07-27T16:20:40` по `2026-08-11T09:53:23` UTC. Артефакт: `python3 - <<'PY' ... select min(ts), max(ts), count(*) from logs ... PY` → `('2026-07-27T16:20:40.227730+00:00', '2026-08-11T09:53:23.715300+00:00', 58611)`.

- **CONFIRMED.** Правила менялись часто: 89 коммитов затрагивают `CLAUDE.md`/`pipelines/default/prompts` за 27.07–11.08; из их subject 45 содержат `rule`/`правил`. Артефакт: `git log --since='2026-07-27' --until='2026-08-12' --format='%h' -- CLAUDE.md pipelines/default/prompts | wc -l` → `89`; awk-подсчёт subject → `rule-word 45`.

- **CONFIRMED.** Текущий свод — 268 строк/62 362 байта, prompt-модули — 1 657 строк/113 097 байт. Артефакт: `wc -c -l < CLAUDE.md` → `268 62362`; `find pipelines/default/prompts -type f -name '*.md' -print0 | xargs -0 wc -c -l | tail -1` → `1657 113097 total`.

- **CONFIRMED.** Модуль требует порядок `pwd → search_memory → frame/restate → code scan` и делает `search_memory` обязательным для research/diagnosis/planning. Артефакт: `pipelines/default/prompts/modules/memory-search.md:4-8`, цитата: ``**Mandatory pre-work order:** `pwd` → this memory gate ... MUST call `search_memory(...)` ``.

- **CONFIRMED, но это только наблюдательный прокси.** После появления этого модуля (коммит `3f84a10`, 2026-08-01 06:22:54 UTC) в 1 913 неотфильтрованных эпизодах `user_message` с хотя бы пятью следующими tool-событиями лишь 230 содержали `pwd` раньше `search_memory` в первых пяти инструментах (12.0%); `search_memory` вообще встретился в 287/1 913 (15.0%). Артефакт (точная команда): `python3 - <<'PY'` с `rows=select session_id,id,ts,type,content from logs order by session_id,id`, разбиением по `user_message`, выбором первых пяти `type='tool'` и проверками `any('search_memory' in c)`/`any('pwd' in c)`, вывел `episodes 1913 search_memory_any_first5 287 pwd_any 318 pwd_before_memory 230`. Нельзя считать это чистой compliance-rate: неизвестны исключения правила и часть сообщений — служебные.

- **CONFIRMED.** Для правила worker «отчитываться через Orchestra `send_message`, не встроенный `SendMessage`» наблюдается 1 485 tool-событий с префиксом `mcp__orchestra__send_message:` и 0 событий с префиксом `SendMessage:`. Артефакт: `select count(*) from logs where type='tool' and content like 'mcp__orchestra__send_message:%'` → `1485`; тот же запрос с `content like 'SendMessage:%'` → `0`. Формулировка правила: `pipelines/default/prompts/roles/worker.md:12-13`.

- **CONFIRMED.** Правило SQLite-снимка появилось коммитом `a0c7d1d` в 2026-08-07 08:19 UTC и предписывает «только `sqlite3.Connection.backup`, никогда `cp`». Артефакт: `CLAUDE.md:177`, цитата: ``Снимаешь копию ЖИВОЙ SQLite ... только `sqlite3.Connection.backup`, никогда `cp`.``; `git show -s --format='%h|%ad' --date=iso a0c7d1d` → `a0c7d1d|2026-08-07 10:19:00 +0200`.

- **CONFIRMED.** Для tool-команд, одновременно содержащих `orchestra.db`, до правила было 33 `backup` против 59 `cp`; после — 31 `backup` против 9 `cp`. Доля `backup` среди `backup+cp` выросла с 35.9% (33/92) до 77.5% (31/40), то есть +41.6 п.п. Артефакт: выполнены точные запросы `select count(*) from logs where type='tool' and ts < '2026-08-07T08:19:00' and content like '%orchestra.db%' and content like '%backup%'` → `33`, тот же запрос с `content like '%cp %'` → `59`; и те же два запроса с `ts >= '2026-08-07T08:19:00'` → `31`, `9`. Это самый сильный найденный сигнал полезности правила; остаётся риск, что часть команд — не снимки живой БД.

- **CONFIRMED, отрицательный сигнал.** Правило после неудачного `merge_worker` сначала вызывать `worker_wip` находится в `CLAUDE.md:158`. В tool-result до его появления было 49 событий `Merge operation ... FAILED`, после — 25; `worker_wip` в следующих 20 лог-событиях был только в 4/49 (8.2%) до и 3/25 (12.0%) после. Артефакт (точная команда): `python3 - <<'PY'` с `rows=select id,ts,session_id,content from logs where type='tool_result' and content like '%Merge operation %FAILED%'`, для каждого failure запрос `select id,type,content from logs where session_id=? and id>? order by id limit 20`, затем `any('worker_wip' in content)`, cutoff `2026-08-06T11:48:00`, вывел `before failures 49 ... rate 4 / 49` и `after failures 25 ... rate 3 / 25`. Рост статистически неубедителен и не подтверждает причинного эффекта.

- **CONFIRMED.** В срезе 1 799 turn-usage, из них 1 740 успешных: 1 395 успешных Claude и 345 успешных Codex; распределение рантаймов резко меняется по дням (например, 08.08: 51 Codex, 09.08: 150 Codex). Артефакт: `select runtime,sum(ok),count(*) from turn_usage group by runtime` → `claude 1395/1450`, `codex 345/349`; дневной запрос `select substr(ts,1,10),runtime,count(*) ...` дал указанные значения. Это сильный конфаундер для любых before/after сравнений поведения.

- **LIKELY.** Долгоживущие prompt cohorts переживают появление новых правил: `template_hash='ac5b3688'` представлен 26 сессиями с 2026-08-03 по 2026-08-11, а `31c6a922` — 25 сессиями с 03.08 по 06.08. Артефакт: `select template_hash,count(*),min(created_at),max(created_at) from sessions group by template_hash` → строки `ac5b3688|26|2026-08-03T08:25:36...|2026-08-11T08:18:53...` и `31c6a922|25|2026-08-03T08:29:17...|2026-08-06T04:43:25...`. В БД нет таблицы, связывающей hash с версией `CLAUDE.md`, поэтому это не доказывает, какие именно правила видел агент.

- **CONFIRMED.** В корневом своде минимум две ссылки на артефакты мёртвые: `docs/tasks/728/` и `docs/tasks/727/research.md` отсутствуют. Артефакт: `for p in docs/tasks/728 docs/tasks/727/research.md; do test -e "$p"; echo "$p exit=$?"; done` → оба `exit=1`; ссылки находятся в `CLAUDE.md:158`.

- **LIKELY.** Описание старого конфликта про `research-method.md` «велел Run in /tmp» больше не является текущей инструкцией: в своде это историческая фраза `CLAUDE.md:225`, а действующий модуль прямо говорит `Do not put large files in /tmp`. Артефакт: `rg -n 'Run in /tmp|Do not put large files in /tmp' CLAUDE.md pipelines/default/prompts` → `CLAUDE.md:225` и `pipelines/default/prompts/modules/research-method.md:81` соответственно. Это не активная команда, но текст легко принять за текущий конфликт.

- **CONFIRMED.** Свод содержит 15 пунктов в секции «Проверь перед работой» и 81 bullet-строку в диапазоне «Грабли», при этом телеметрия не маркирует ни один лог идентификатором правила. Артефакт: `awk 'NR>=142&&NR<160&&/^-/ {n++} END{print n}' CLAUDE.md` → `15`; `awk 'NR>=160&&NR<265&&/^-/ {n++} END{print n}' CLAUDE.md` → `81`; схема `logs` не имеет `rule_id`/`prompt_version`.

## Что говорит ПРОТИВ моих выводов

- **UNCERTAIN.** Все поведенческие прокси имеют ограничения: `backup`/`cp` считаются по tool-текстам (включая цитаты и другие репозитории), `merge_worker` использует окно следующих 20 логов, а `pwd → search_memory` не учитывает исключения правила. Артефакт: ограничения следуют из SQL-фильтров `type/content` выше; в схеме `logs` нет поля, связывающего событие с правилом или задачей.

- **UNCERTAIN.** `template_hash` — косвенный признак версии prompt; содержимое hash/cohort в SQLite не сохранено, поэтому нельзя утверждать, что 26 сессий получили один и тот же свод. Артефакт: `select template_hash,count(*),min(created_at),max(created_at) from sessions group by template_hash` → cohort `ac5b3688|26|...`.

## Чего я проверить не смог

- **UNCERTAIN.** Нельзя построить честный causal before/after или compliance по каждому правилу: первая пользовательская запись в `logs` — 03.08, а многие правила добавлены 27.07–02.08; `logs` не содержит `rule_id`, prompt-version, expected task class или снимок собранного prompt по `template_hash`. Артефакт: `select min(ts) from logs where type='user_message'` → `2026-08-03...`; схема `logs` содержит только `type/content` и служебные поля.

## Итог

- **CONFIRMED.** В этом срезе есть один заметный положительный поведенческий эффект — переход от `cp` к `backup` для команд с `orchestra.db` (35.9% → 77.5%), и один отрицательный/неубедительный — `worker_wip` после failed merge (8.2% → 12.0%).

- **CONFIRMED.** Объективный общий вывод «правила в среднем работают лучше после появления» по этой телеметрии сделать нельзя: нет rule-version в логах, нет сопоставимого pre-периода, и рантайм меняется с Claude на Codex.

- **LIKELY.** В своде есть мёртвые/дезориентирующие элементы: две битые ссылки в доказательстве правила и историческое упоминание уже устранённого `/tmp`-конфликта. Их стоит удалить или явно пометить как архивные; остальные 81 пункт «Граблей» нельзя объявить лишними без rule-level маркировки и отдельной выборки задач.
