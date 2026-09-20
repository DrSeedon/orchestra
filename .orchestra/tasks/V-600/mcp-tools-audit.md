# V-600 — аудит MCP-тулов

Срез: `app/mcp_stdio.py` в этом worktree; боевая SQLite открыта только через `mode=ro`; период SQL: `ts > '2026-09-13'`. В таблице задержки — пары `logs.type=tool`/`tool_result` по `tool_use_id`, медиана — средние два центральных значения, p95 — nearest-rank (`ceil(0.95*n)`). Отказы взяты из `tool_errors` за тот же период по `tool_name`. «Строк кода в теле» — непустые строки без комментариев между первой и последней AST-операцией тела. HTTP-счёт — статический типичный успешный путь по `_api`; ветвления указаны текстом в той же ячейке.

## Таблица

| тул | строк кода в теле | число параметров | сколько HTTP-вызовов к серверу делает один вызов в типичном пути | ждёт ли исход внутри вызова (да / нет — отвечает «потом разбужу») | есть ли свой потолок ожидания и какой | вызовов за 7 дней | медиана задержки, с | p95 задержки, с | отказов за 7 дней |
|---|---:|---:|---|---|---|---:|---:|---:|---:|
| spawn_worker | 129 | 14 | 2 | нет | 30 с (параметр timeout _api) | 78 | 3.454 | 30.107 | 41 |
| delivery_status | 19 | 1 | 1 | нет | 30 с (параметр timeout _api) | 0 | — | — | 0 |
| retry_initial_delivery | 9 | 3 | 1 | нет | 30 с (параметр timeout _api) | 0 | — | — | 0 |
| acquire_test_lock | 14 | 1 | 1 | нет | 30 с (параметр timeout _api) | 1 | 0.080 | 0.080 | 0 |
| release_test_lock | 9 | 0 | 1 | нет | 30 с (параметр timeout _api) | 1 | 0.048 | 0.048 | 0 |
| test_lock_status | 8 | 0 | 1 | нет | 30 с (параметр timeout _api) | 0 | — | — | 0 |
| send_message | 54 | 4 | 1 (+1 при проверке неоднозначной доставки) | нет | 30 с (параметр timeout _api) | 1075 | 0.450 | 1.291 | 21 |
| message_delivery_status | 25 | 1 | 1 | нет | 30 с (параметр timeout _api) | 9 | 0.095 | 0.591 | 0 |
| open_fan | 20 | 3 | 1 | нет | 30 с HTTP; deadline барьера по умолчанию 1800 с | 0 | — | — | 0 |
| list_agents | 117 | 0 | 3 (оркестратор; 2 у worker) | нет | 30 с (параметр timeout _api) | 98 | 0.539 | 18.620 | 0 |
| list_orchestrators | 20 | 0 | 1 | нет | 30 с (параметр timeout _api) | 4 | 0.208 | 0.322 | 0 |
| get_worker_logs | 12 | 2 | 1 | нет | 30 с (параметр timeout _api) | 5 | 0.307 | 0.799 | 0 |
| compact_worker | 9 | 1 | 1 | нет | 120 с | 2 | 45.172 | 90.289 | 1 |
| kill_worker | 5 | 2 | 1 | нет | 30 с (параметр timeout _api) | 27 | 1.131 | 3.047 | 0 |
| stop_worker | 5 | 1 | 1 | нет | 30 с (параметр timeout _api) | 16 | 0.106 | 0.620 | 0 |
| rename_worker | 5 | 2 | 1 | нет | 30 с (параметр timeout _api) | 0 | — | — | 0 |
| file_delivery_status | 25 | 1 | 1 | нет | 30 с (параметр timeout _api) | 13 | 0.066 | 0.116 | 0 |
| send_file | 69 | 4 | 1 (+1 fallback status) | нет | 180 с | 54 | 0.150 | 0.452 | 1 |
| send_files | 75 | 4 | 1 (+1 fallback status) | нет | 180 с | 38 | 0.161 | 0.924 | 0 |
| publish_artifact | 17 | 3 | 1 | нет | 30 с (параметр timeout _api) | 0 | — | — | 0 |
| send_chart | 40 | 4 | 1 через send_file | нет | 180 с через send_file | 7 | 0.454 | 1.407 | 0 |
| notify_user | 37 | 3 | 1 | нет | 30 с (параметр timeout _api) | 1 | 0.075 | 0.075 | 0 |
| update_progress | 7 | 2 | 1 | нет | 30 с (параметр timeout _api) | 1 | 0.106 | 0.106 | 0 |
| change_worker_model | 7 | 2 | 1 | нет | 30 с (параметр timeout _api) | 17 | 0.142 | 0.532 | 0 |
| merge_worker | 168 | 8 | 2 с lifecycle-v2; +GET статуса при PENDING | да | 10 с для completion job; 90 с обычное ожидание; каждый HTTP _api 30 с | 191 | 0.419 | 1.338 | 19 |
| resolve_merge_operation | 68 | 2 | 1 | нет | 30 с (параметр timeout _api) | 0 | — | — | 0 |
| switch_worker_branch | 51 | 6 | 1 | нет | 30 с (параметр timeout _api) | 48 | 0.930 | 16.063 | 5 |
| check_conflict | 12 | 2 | 1 | нет | 30 с (параметр timeout _api) | 1 | 0.116 | 0.116 | 0 |
| worker_wip | 58 | 2 | 1 | нет | 30 с (параметр timeout _api) | 107 | 0.376 | 1.490 | 0 |
| report_bug | 15 | 2 | 1 | нет | 30 с (параметр timeout _api) | 4 | 0.310 | 5.881 | 0 |
| update_worker_description | 5 | 2 | 1 | нет | 30 с (параметр timeout _api) | 2 | 0.071 | 0.087 | 0 |
| set_worker_owned_dirs | 33 | 2 | 1 | нет | 30 с (параметр timeout _api) | 0 | — | — | 0 |
| update_worker_prompt | 5 | 2 | 1 | нет | 30 с (параметр timeout _api) | 0 | — | — | 0 |
| get_worker_info | 7 | 1 | 1 | нет | 30 с (параметр timeout _api) | 6 | 0.177 | 0.434 | 0 |
| project_goal | 64 | 7 | 1 для get/set; 2 для progress/policy | нет | 30 с (параметр timeout _api) | 1 | 0.326 | 0.326 | 1 |
| project_wait | 38 | 5 | 1 | нет | 30 с (параметр timeout _api) | 0 | — | — | 0 |
| task_create | 35 | 11 | 1 | нет | 30 с (параметр timeout _api) | 130 | 0.543 | 3.007 | 0 |
| task_create_status | 10 | 2 | 1 | нет | 30 с (параметр timeout _api) | 0 | — | — | 0 |
| task_update | 63 | 14 | 1; 2 с portfolio_project | нет | 30 с (параметр timeout _api) | 19 | 0.680 | 1.699 | 0 |
| task_list | 14 | 3 | 1 | нет | 30 с (параметр timeout _api) | 2 | 0.279 | 0.518 | 0 |
| task_get | 6 | 2 | 1 | нет | 30 с (параметр timeout _api) | 15 | 0.160 | 2.185 | 0 |
| bg_create | 47 | 11 | 1 | нет | 30 с HTTP; timeout_seconds относится к фоновому заданию | 411 | 0.207 | 0.765 | 0 |
| bg_list | 64 | 0 | 1 | нет | 30 с (параметр timeout _api) | 31 | 0.107 | 1.532 | 0 |
| bg_cancel | 5 | 1 | 1 | нет | 30 с (параметр timeout _api) | 49 | 0.107 | 1.241 | 8 |
| search_memory | 37 | 3 | 1 | нет | 5 с | 13 | 5.064 | 5.549 | 0 |

## Непарные ответы

Из зарегистрированных тулов: 1 вызов `list_agents` за период не имеет строки `tool_result`; он не включён в медиану/p95. Остальные 2476 из 2477 вызовов спарены. Техническая выборка сохранена в `stats.tsv`, `registered-all-stats.txt`, `pair-counts.txt`.

## Асинхронные тулы

К асинхронным отнесены вызовы, возвращающие queued/durable receipt, идентификатор фоновой работы или нетерминальный PENDING вместо окончательного результата. Доля ниже — именно доля длительности вызова ≤10 с по спаренным логам; это не доля завершённых фоновых операций.
- `spawn_worker` — Возвращает создание worker и initial-delivery receipt со state=QUEUED; агент ждёт доставки начального задания. Страховка: `delivery_status`/`retry_initial_delivery`; отдельного bg job в теле нет. По задержке ≤10 с: 66/78 = 84.6%.
- `send_message` — Возвращает durable message-delivery receipt (часто state=QUEUED); агент ждёт следующего хода/доставки адресату. Страховка: `message_delivery_status`; отдельного bg job в теле нет. По задержке ≤10 с: 1072/1075 = 99.7%.
- `send_file` — Возвращает file-delivery receipt state=QUEUED; агент ждёт доставки файла. Страховка: `file_delivery_status`; отдельного bg job в теле нет. По задержке ≤10 с: 54/54 = 100.0%.
- `send_files` — То же для album/batch: receipt state=QUEUED, затем доставка. Страховка: `file_delivery_status`; отдельного bg job в теле нет. По задержке ≤10 с: 38/38 = 100.0%.
- `send_chart` — Рисует локальный chart, затем возвращает результат вложенного `send_file`, обычно QUEUED. Страховка: `file_delivery_status`; отдельного bg job в теле нет. По задержке ≤10 с: 7/7 = 100.0%.
- `open_fan` — Возвращает barrier и текст END YOUR TURN NOW; агент ждёт последний report ребёнка и wake. Страховка — fan barrier на сервере; вызовов за период нет. По задержке ≤10 с: нет измерений.
- `bg_create` — Возвращает id созданного фонового задания, не результат command/timer/file/ssh/run; агент ждёт trigger/wake. Страховка — само server-side bg job (timeout_seconds задаётся параметром). По задержке ≤10 с: 411/411 = 100.0%.
- `merge_worker` — При PENDING/RUNNING не возвращает итог merge: source формирует STILL PENDING и передаёт job_id, который будит агента. Страховка — completion job; при обычном пути внутренний polling статуса до 90 с. По задержке ≤10 с: 191/191 = 100.0%.

## Многошаговые танцы

Цепочки ниже — соседние вызовы одного session/agent в `logs`, не предположение по документации. Число — количество таких соседних пар за период; после — фактические даты и имена агентов из сохранённой выборки `chain-samples.tsv`.
- `worker_wip → merge_worker`: 42 пары. Примеры: 2026-09-13 04:36 Claude-Code-Game-Master-orchestrator; 2026-09-13 05:07 Claude-Code-Game-Master-orchestrator; 2026-09-20 07:24 cog-second-brain-orchestrator.
- `merge_worker → merge_worker`: 39 пар (повтор того же operation после нетерминального результата). Примеры: 2026-09-13 03:09 и 03:29 comfy-image-orchestrator-vps; 2026-09-20 06:10 Orchestra-orchestrator.
- `merge_worker → worker_wip`: 24 пары (проверка фактически landed состояния). Примеры: 2026-09-13 05:45 comfy-image-orchestrator-vps; 2026-09-13 13:51 Orchestra-orchestrator; 2026-09-13 15:57 Claude-Code-Game-Master-orchestrator.
- `send_file → file_delivery_status`: 8 пар. Примеры: 2026-09-14 04:55 seedon-orchestrator; 2026-09-14 04:55 comfy-image-orchestrator-vps; 2026-09-20 06:15 University-orchestrator.
- `send_files → file_delivery_status`: 2 пары: 2026-09-14 04:39 и 2026-09-18 06:44, оба `seedon-orchestrator`.
- `bg_create → bg_list`: 10 пар. Примеры: 2026-09-13 11:36 balatro-vps; 2026-09-13 14:16 balatro-strategy; 2026-09-14 03:32 comfy-image-orchestrator-vps.
- `switch_worker_branch → worker_wip`: 2 пары: 2026-09-13 05:07 Claude-Code-Game-Master-orchestrator и 2026-09-19 10:42 seedon-orchestrator.
За этот период соседних пар `spawn_worker → delivery_status`, `send_message → message_delivery_status` и `task_create → task_create_status` в логах нет; наличие follow-up описано исходным кодом, но фактической цепочки в срезе нет.

## Самые медленные

| место | тул | p95, с | что занимает время по коду |
|---:|---|---:|---|
| 1 | compact_worker | 90.289 | сеть: один POST к `/sessions/{name}/compact`; собственный timeout 120 с; локальных subprocess/playwright/git/sleep в теле нет. |
| 2 | spawn_worker | 30.107 | сеть: POST создания сессии + POST initial-delivery; локальных subprocess/playwright/git/sleep в теле нет. |
| 3 | list_agents | 18.620 | сеть: GET sessions + GET tasks для orchestrator + GET role-icons; локальных subprocess/playwright/git/sleep в теле нет. |
| 4 | switch_worker_branch | 16.063 | сеть: POST branch-switch; git выполняется серверным endpoint, в теле тула subprocess/playwright/sleep нет. |
| 5 | report_bug | 5.881 | сеть: один POST `/api/report_bug`; локальных subprocess/playwright/git/sleep в теле нет. |
| 6 | search_memory | 5.549 | сеть: один POST memory search; timeout 5 с; локальных subprocess/playwright/git/sleep в теле нет. |
| 7 | kill_worker | 3.047 | сеть: один DELETE session endpoint; локальных subprocess/playwright/git/sleep в теле нет. |
| 8 | task_create | 3.007 | сеть: один POST task endpoint; локальных subprocess/playwright/git/sleep в теле нет. |
| 9 | task_get | 2.185 | сеть: один GET task endpoint; локальных subprocess/playwright/git/sleep в теле нет. |
| 10 | task_update | 1.699 | сеть: PUT/GET task endpoint; при portfolio_project второй POST link; локальных subprocess/playwright/git/sleep в теле нет. |

## Кандидаты на упрощение

Критерий списка: в сигнатуре больше шести параметров или тело больше 150 строк. «Ключей использовано» — число имён параметров, реально присутствовавших в JSON `logs.content` вызова; в скобках — из них с ненулевым/непустым значением.
- `spawn_worker` — 14 параметров, 129 строк тела; вызовов 78, ключей использовано 10/14 (с непустым/ненулевым значением 10); не появлялись: mcp_servers,tg_topic,delivery_id,disabled_tools.
- `merge_worker` — 8 параметров, 168 строк тела; вызовов 191, ключей использовано 6/8 (с непустым/ненулевым значением 6); не появлялись: next_task_id,operation_id.
- `project_goal` — 7 параметров, 64 строк тела; вызовов 1, ключей использовано 2/7 (с непустым/ненулевым значением 2); не появлялись: objective,goal_id,note,watchdog_enabled,stall_after_seconds.
- `task_create` — 11 параметров, 35 строк тела; вызовов 130, ключей использовано 6/11 (с непустым/ненулевым значением 5); не появлялись: status,acceptance_command,acceptance_manifest,acceptance_required,request_key.
- `task_update` — 14 параметров, 63 строк тела; вызовов 19, ключей использовано 7/14 (с непустым/ненулевым значением 7); не появлялись: price,acceptance_command,acceptance_manifest,acceptance_required,clear_acceptance_command,clear_acceptance_oracle,portfolio_project.
- `bg_create` — 11 параметров, 47 строк тела; вызовов 411, ключей использовано 9/11 (с непустым/ненулевым значением 9); не появлялись: path,host.

## Файлы вычислений

`tool-source.tsv`, `schema.txt`, `log-samples.txt`, `pair-counts.txt`, `stats.tsv`, `registered-all-stats.txt`, `top10-p95.tsv`, `error-counts.txt`, `candidate-usage.tsv`, `chain-counts.txt`, `chain-samples.tsv`, `async-result-counts-all.txt` — сохранённые результаты команд аудита рядом с этим отчётом.
