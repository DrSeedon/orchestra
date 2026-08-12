# #224 — план: секреты из argv в файл 600 + маскирование обоих швов

Основание — `docs/tasks/224/research.md` (смержен, `5fee7145`). Порядок тикетов задан
оркестратором и отличается от порядка постановки: маскирование первым, потому что живой
SSE-поток в БД не пишется вовсе и его не закрывает ничто другое.

Все тесты написаны ДО реализации и **закоммичены КРАСНЫМИ** — вывод прогона ниже, в тикетах.

---

## ⚠️ Предпосылка тикета «белый список для Claude-ветки» не подтвердилась

Оркестратор поставил задачу так: «кросс-проектная утечка живёт в `backend_claude.py:227-233`,
где чужие `.mcp.json` мерджатся в один конфиг… агент видит секреты соседей потому, что мы ему
их СОБИРАЕМ». **Проверил перед планированием — это не так.** Замеры:

1. `~/.claude.json` **не содержит `mcpServers` вообще** (пустой список имён) →
   `_load_user_mcp_servers` на этой машине всегда возвращает `{}`.
2. `pipelines/default/pipeline.yaml:7` задаёт `mcp_servers: []`, а пайплайн в репозитории
   ровно один → ветка `role.mcp_servers == "all"` (`runtime_registry.py:175`) не срабатывает.
3. Чужие серверы в argv живых агентов (`mcp-pandoc`, `websearch`) пришли **не из мерджа**, а
   из `sessions.mcp_servers_custom` — их передали ЯВНО при спавне двум оркестраторам
   (`seedon-orchestrator`, `kesha-tg-bot-orchestrator`). Это намеренная конфигурация.
4. `_load_scope_mcp_servers(context.scope)` читает `.mcp.json` **своего** scope агента —
   свой проект, а не соседний. Сверка «что в argv» против «что в своём `.mcp.json`» дала
   расхождение ровно на `mcp_servers_custom`, и ни на что больше.

Итого: **сборки чужих секретов у нас нет.** Кросс-проектная видимость, которую мы намерили,
объясняется целиком тем, что argv читает любой процесс, — то есть её закрывают тикеты T3/T4,
а не переделка мерджа. Переделывать `backend_claude.py:227-233` под «белый список» означало бы
отобрать у ролей серверы, которые им выданы намеренно.

**Что от этой задачи осталось настоящего — один fail-open дефолт (T5).** `Defaults.mcp_servers`
в `app/pipeline.py:186` = `"all"`, и `"all"` в `_merge_list` **поглощает** любой список. Пайплайн,
забывший строку `mcp_servers:`, раздаст каждой роли все user-level серверы. Сегодня это прикрыто
только тем, что единственный yaml задаёт `[]` явно. Закрываю дефолт — правка нулевого риска
(поведение сегодня не меняется вовсе), убирающая грабли на будущее.

**Нужно решение оркестратора:** согласен ли он, что T5 закрывает его пункт 2, или он видел
другой сценарий, который я не воспроизвёл. Реализацию T5 без ответа не начинаю; T1–T4, T6, T7
от этого не зависят и идут своим ходом.

---

## Что меняется, по файлам

| Файл | Что | Тикет |
|---|---|---|
| `app/secret_mask.py` (НОВЫЙ, leaf) | `mask_secrets(text) -> str` — единственный владелец правила | T1 |
| `app/db.py:1353` `add_log` | маскирует `content` перед INSERT | T1 |
| `app/live_broker.py` `LiveBroker.publish` | маскирует `payload["content"]` до `_accum` и до рассылки | T2 |
| `app/backend_claude.py:181-245` `_make_client` | конфиг в файл 600, в `options.mcp_servers` — путь | T3 |
| `app/backend_codex.py` `__init__`/`connect`/`_mcp_config_args`/`_runtime_context` | свой `CODEX_HOME`, конфиг собирается, поле вместо `os.environ` | T4 |
| `app/pipeline.py:186` | `mcp_servers: AllOrList = []` | T5 |
| `docs/tasks/224/telegram-bot-api/` (НОВЫЕ) | подготовленный юнит + образец env + INSTALL.md | T6 |
| `app/backend_claude.py` (та же функция) | fail-loud на не-stdio/http сервер | T7 |

**НЕ трогаем:** `app/backend_grok.py` (конфиг едет в JSON-RPC `session/new`, не в argv),
`app/backend_opencode.py` (едет в env-переменной `OPENCODE_CONFIG_CONTENT`),
`app/manager.py:393` `_make_mcp_config` (сигнатура и содержимое сохраняются — меняется только
СПОСОБ доставки), `runtime_registry.py:227-233` мердж (см. раздел выше), `data/orchestra.db`
и логи (санитизация — решение владельца), ротация секретов, рестарт сервиса.

## Формат маски — ДОСЛОВНО, не изобретать

```
[secret len=<N> tail=<последние 4 символа значения>]
```
Пример: значение `abcdefghijklmnopqrst` (20 символов) → `[secret len=20 tail=qrst]`.
Отладка остаётся возможной (длина + хвост), значение не восстановимо.

**Порог и хвост:**
- длина значения < 12 → **не трогать вовсе** (иначе шум забивает журнал);
- 12–15 → `[secret len=N]`, хвост не отдаём (4 символа из 12 — слишком много);
- ≥16 → `[secret len=N tail=XXXX]`.

**Границу значения определяет ФОРМА, а не класс символов.** Первая редакция задавала
алфавит `[A-Za-z0-9_\-.+/]` — ревью справедливо показало, что он несовместим с половиной
объявленных классов: URL, DSN и cookie содержат `:` `@` `?` `&` `=` `;` `%`, а base64
кончается на `=`. По алфавиту `DATABASE_URL=postgres://user:PASS@host/db` замаскировался бы
частично или никак. Правильные границы:

| Форма | Значение читается | Пример |
|---|---|---|
| в двойных кавычках (JSON/TOML) | до ближайшей неэкранированной `"` | `"INTERNAL_TOKEN": "…"` |
| в одинарных кавычках | до ближайшей `'` | `PASSWORD='…'` |
| без кавычек (shell/env/флаг) | до пробела, `,`, `;`, `}` или конца строки | `--api-hash=…`, `DATABASE_URL=postgres://…` |

**Правило срабатывания — по ИМЕНИ ключа:**
- значение ≥12 символов;
- суффиксы: `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `API_KEY`/`APIKEY`/`API-KEY`;
- явный список (суффикс их не ловит): `COOKIE`, `CREDENTIAL`, `PRIVATE_KEY`, `PASSPHRASE`,
  `DATABASE_URL`, `CONNECTION_STRING`, `DSN`, `AUTH_TOKEN`, `API_HASH`, `api-hash`,
  `YANDEX_DIRECT_LOGIN`.
  **Записи явного списка тоже матчатся как суффикс по границе `_`/`-`** — иначе
  `SENTRY_DSN` из матрицы не совпал бы с записью `DSN`, и спецификация провалила бы
  собственный тест (находка ревью). То есть `SENTRY_DSN`, `SESSION_COOKIE`,
  `PG_CONNECTION_STRING` ловятся, а `DSNAME` — нет;
- **`_HASH` НЕ брать суффиксом** — крупнейший класс ложных срабатываний
  (`TEMPLATE_HASH`/`_TEMPLATE_HASH`, 33 вхождения в живой БД, это хеши содержимого);
- формы `Bearer <токен>` / `Basic <токен>` и PEM-блоки — **переиспользовать готовые**
  `_AUTH_VALUE` и `_PEM_PRIVATE_KEY` из `app/runtime_history.py:114-155`, не писать заново.

Площадь замерена на одном снимке живой БД (81 433 строки): базовое правило трогает
323 строки (0.40%), объединение с добавленными формами — 351 (0.43%).

**Известные ограничения — записать в отчёт, а не чинить.** Список не закрытый: правило
по имени ключа по построению не ловит всё.
1. Контекст самой модели: агент, запустивший `ps`, видит значение в своём `tool_result`.
2. Секрет, разорванный между двумя partial-чанками SSE, не совпадёт ни с одним из них.
   Персистентная запись (`text`-событие) маскируется на шве T1 и потому чиста; риск
   ограничен живым просмотром в браузере.
3. Секрет без распознаваемого имени ключа (голая строка в выводе) не маскируется вовсе.
4. Закодированные и экранированные представления (base64 целого JSON, `\"` внутри строки).

Первая редакция утверждала «только два ограничения» — это было преувеличением, снято.

## Форма приёмки для T3/T4 (по образцу соседнего проекта)

Доказывать надо не только отсутствие секрета, но и **сохранность работы** — иначе тихая
потеря тулов пройдёт как успех:
1. в argv живого процесса значений нет (`grep` по `/proc/<pid>/cmdline` пуст);
2. в логе коннекта поднялись **ВСЕ** ожидаемые серверы — сверка со списком, а не «хотя бы один»;
3. **реальный вызов тула отвечает** — `probe_mcp.py` из `docs/tasks/224/probe/` умеет
   `tools/call`.

---

## Tickets

### T1 — маскирование на шве персистенции (`db.add_log`)
- Files: `app/secret_mask.py` (новый), `app/db.py`
- Test: `tests/test_secret_mask.py::test_t1_add_log_masks_secret_value` — committed RED в этом коммите
  ```
  >  assert SECRET not in stored, "значение секрета сохранено в logs дословно"
  E  AssertionError: значение секрета сохранено в logs дословно
  ```
- AC: `uv run python -m pytest tests/test_secret_mask.py -q` зелёный
  + `test_t1_add_log_keeps_content_hash_untouched` **остаётся зелёным** (это companion-guard
  против пере-маскирования: он зелёный и сейчас, покраснеет ровно если реализация начнёт
  трогать `TEMPLATE_HASH`)
  + формат маски совпадает с разделом «Формат маски» ДОСЛОВНО
- blocked-by: none

### T2 — маскирование на шве живой выдачи (`live_broker.publish`)
- Files: `app/live_broker.py`
- Test: `tests/test_secret_mask.py::test_t2_broker_publish_masks_content` и
  `::test_t2_broker_replay_is_masked` — committed RED
  ```
  >  assert SECRET not in got["content"], "секрет ушёл в SSE-поток дословно"
  E  AssertionError: секрет ушёл в SSE-поток дословно
  >  assert SECRET not in got["content"], "секрет остался в реплей-буфере"
  E  AssertionError: секрет остался в реплей-буфере
  ```
- AC: тесты выше зелёные + `test_t2_broker_publish_keeps_metadata` остаётся зелёным
  (маскируется ТОЛЬКО `content`; `type`, `tool_use_id`, `subagent_id` неизменны)
  + маскирование стоит ДО накопления в `_accum`, иначе реплей отдаёт сырое
  + `uv run python -m pytest tests/test_live_broker.py -q` зелёный (регрессия соседа)
- blocked-by: T1 (общий хелпер)

### T3 — Claude: конфиг в файл 600, в argv только путь
- Files: `app/backend_claude.py`
- Test: `tests/test_mcp_config_isolation.py::test_t3_claude_passes_config_path_not_dict`,
  `::test_t3_claude_config_file_is_0600_and_roundtrips`,
  `::test_t3_secret_value_absent_from_option_string` — committed RED
  ```
  >  assert isinstance(options.mcp_servers, (str, Path)), (
  E  AssertionError: options.mcp_servers всё ещё dict → SDK положит значения секретов в argv
  ```
  Плюс оракулы СОХРАННОСТИ и жизненного цикла (добавлены по ревью, тоже RED):
  `::test_t3_every_server_and_field_survives_the_move` — точное множество серверов и все
  поля (stdio с `args`/`env` + http с `url`), а не один сервер и одно поле;
  `::test_t3_config_dir_is_private_and_outside_worktree_and_tmp`;
  `::test_t3_repeated_make_client_reuses_one_file`;
  `::test_t3_disconnect_removes_the_config_file`
- AC: все семь тестов T3 зелёные + файл живёт всё время жизни процесса CLI, владелец
  жизненного цикла — **`ClaudeBackend.disconnect()`** (в первой редакции было ошибочно
  указано `_disconnect_backend`, это метод session-слоя, а не бэкенда) + повторный
  `_make_client()` переиспользует ОДИН файл, а не плодит осиротевшие
  + приёмка по тройке из раздела «Форма приёмки»
- blocked-by: none

### T4 — Codex: свой CODEX_HOME, конфиг собирается, бэкенд помнит свой каталог
- Files: `app/backend_codex.py`
- Test: `tests/test_mcp_config_isolation.py::test_t4_no_env_fragment_in_codex_argv`,
  `::test_t4_config_written_to_own_codex_home`, `::test_t4_foreign_global_servers_not_copied`,
  `::test_t4_rollout_found_via_backend_home_not_parent_environ` — committed RED
  ```
  >  assert not leaking, f"env всё ещё уходит в argv: ..."
  E  AssertionError: env всё ещё уходит в argv: ['mcp_servers.orchestra.env']
  >  assert ctx is not None, "rollout не найден: _runtime_context всё ещё смотрит в os.environ"
  E  AssertionError: rollout не найден: _runtime_context всё ещё смотрит в os.environ
  ```
  Добавлено по ревью (тоже RED): `::test_t4_child_env_points_at_the_same_home`,
  `::test_t4_home_is_stable_across_reconnect`,
  `::test_t4_subscription_auth_is_reachable_from_isolated_home` (требует ИМЕННО симлинк:
  копия протухнет при перелогине), `::test_t4_custom_server_cannot_hijack_the_identity`,
  `::test_t4_malformed_session_id_fails_loudly`,
  `::test_t4_every_server_and_field_survives_into_config_toml` (точный round-trip по
  разобранному TOML: stdio + http + env + enabled_tools — без него реализация может
  потерять `env`/`args`/тулы и пройти проверку «секция на месте»), а
  `::test_t4_foreign_global_servers_not_copied` теперь ПОДКЛАДЫВАЕТ базовый конфиг с
  чужими секциями — без него тест проходил бы и при полном игнорировании base config,
  то есть не отличал сборку от копии.
- AC: все тесты T4 зелёные, плюс условия, каждое из которых ломает прод, если забыть:
  1. каталог **стабилен по `ORCHESTRA_SESSION_ID`** (не временный): `sessions/`, `history`,
     записанные Codex'ом `trust_level` обязаны переживать реконнект, иначе перестанут
     находиться thread-id для resume.
     **Ключ уже существует до старта процесса** — ревью опасалось, что стабильного
     идентификатора нет, потому что codex thread id появляется только после `thread/start`.
     Проверено: `ORCHESTRA_SESSION_ID` кладётся в env всеми четырьмя вызовами
     `_make_mcp_config` (`manager.py:687, 997, 1066, 1547`); в живых процессах непусто
     **50 из 50**. Менять `BackendBuildContext` не нужно.

     **⚠️ Но брать его из `mcp_env` НЕЛЬЗЯ — это доверительная дыра, найденная во втором
     раунде ревью и воспроизведённая на коде.** `_codex_factory`
     (`runtime_registry.py:230-234`) схлопывает env ВСЕХ серверов в один плоский dict, а
     `_make_mcp_config` (`manager.py:409-414`) добавляет кастомные серверы ПОСЛЕ `orchestra` —
     значит их ключи ПЕРЕТИРАЮТ доверенные. Защищено только ИМЯ `orchestra`, имена
     переменных — нет. Воспроизведение:
     ```
     orchestra.env.ORCHESTRA_SESSION_ID = "real-session-abc"
     evil.env.ORCHESTRA_SESSION_ID      = "../../attacker-controlled"
     → flattened ORCHESTRA_SESSION_ID = "../../attacker-controlled"
     ```
     Последствия: два агента делят один `CODEX_HOME` (перемешанные sessions/resume) либо
     каталог уезжает по обходу пути. **Источник идентичности — только
     `self._mcp_servers["orchestra"]["env"]["ORCHESTRA_SESSION_ID"]`**, с валидацией формата
     (непустой, без `/`, `..` и `\0`) и ГРОМКИМ отказом при отсутствии или несоответствии.
     Закрыто тестами `::test_t4_custom_server_cannot_hijack_the_identity` и
     `::test_t4_malformed_session_id_fails_loudly` (5 параметров);
  2. `config.toml` **собирается по белому списку** — MCP-блок только из `context.mcp_servers`
     этого воркера; `[projects.*]` и глобальные серверы не клонируются;
  3. из базового `~/.codex/config.toml` перенести `project_doc_max_bytes` (иначе воркер молча
     теряет потолок обрезки `AGENTS.md`);
  4. каталог **не под `/tmp`** — Codex отказывается создавать там PATH-алиасы (замер в F14);
  5. **подписочная авторизация обязана остаться доступной.** Изолированный home отрезает
     процесс не только от чужих MCP, но и от `auth.json`. Проверено живым прогоном:
     `CODEX_HOME=<изолированный>` + **symlink на `~/.codex/auth.json`** + `config.toml`
     → настоящий ход модели проходит (`ok`, 3 191 токен). Реальные креды в репозиторий
     не копировать никогда — только симлинк на боевой файл.
  + приёмка по тройке из раздела «Форма приёмки»
- Что Codex сам создаёт в изолированном home (замерено): `sessions/`, `state_*.sqlite`,
  `goals_*.sqlite`, `memories_*.sqlite`, `models_cache.json`, `installation_id`, `cache/`,
  `shell_snapshots/`, `plugins/`, `skills/`. Это состояние на агента — приемлемо, но в
  отчёте назвать: ×N агентов по диску.
  **Скиллы при этом НЕ теряются:** Codex берёт их из `<cwd>/.codex/skills/` рабочего дерева
  (`app/prompting.py:200`, `runtime_registry.py:205`), а не из `CODEX_HOME`.
- blocked-by: none
- **Ломает существующий тест намеренно:** `tests/test_backend_codex.py:252` утверждает
  `'mcp_servers.orchestra.env={WORKER_NAME="w1"}' in args`. Это ЗАФИКСИРОВАННЫЙ СТАРЫЙ контракт
  («env едет в argv»), ровно тот, который тикет отменяет. Тест обновляется на противоположное
  утверждение — это смена контракта, а не подгонка под свой код.
  **Соседние утверждения 250–254 (`command`, `args`, `enabled`, `enabled_tools`) трогать
  нельзя без нужды:** если `_mcp_config_args()` остаётся владельцем безопасных argv-override'ов,
  они сохраняются как есть; если метод пустеет полностью — весь тест осознанно переписывается
  на проверку `config.toml`. Решение принимается в Фазе 3 и называется в отчёте явно.

### T5 — закрыть fail-open дефолт пайплайна ⛔ ЖДЁТ РЕШЕНИЯ ОРКЕСТРАТОРА
- Files: `app/pipeline.py`
- Test: `tests/test_mcp_config_isolation.py::test_t5_pipeline_default_denies_user_mcp_servers` — committed RED
  ```
  >  assert Defaults().mcp_servers == [], (
  E  AssertionError: дефолт пайплайна fail-open: 'all' раздаёт все user-level MCP-серверы
  ```
- AC: тест зелёный + `uv run python -m pytest tests/test_default_pipeline.py tests/test_legacy_pipeline_skills.py -q`
  зелёный (поведение сегодня не меняется: единственный yaml задаёт `[]` явно)
- blocked-by: решение по разделу «Предпосылка не подтвердилась»

### T6 — `telegram-bot-api.service`: креды уходят из ExecStart В ОКРУЖЕНИЕ (подготовка, БЕЗ установки)

> **Правка по ревью, и она меняет суть тикета.** Ревьюер указал: `EnvironmentFile` прячет
> значение из ТЕКСТА юнита, но `ExecStart=... --api-id=${TELEGRAM_API_ID}` systemd развернёт,
> и значение всё равно окажется в `/proc/<pid>/cmdline` — то есть главная утечка (14 строк
> с `--api-hash=` в БД пришли именно из `ps`) осталась бы незакрытой. Замечание верное.
>
> Проверил, что умеет сам бинарник — и он умеет ровно то, что нужно:
> ```
> $ telegram-bot-api --help
>   --api-id=<arg>    ... (defaults to the value of the TELEGRAM_API_ID environment variable)
>   --api-hash=<arg>  ... (defaults to the value of the TELEGRAM_API_HASH environment variable)
> ```
> Значит **флаги убираются из `ExecStart` ЦЕЛИКОМ**, значения приходят только через
> `EnvironmentFile` 600 → их нет ни в тексте юнита, ни в argv. Тикет выполним в заявленной
> форме; вариант «оставить флаги со ссылкой на переменную» ЗАПРЕЩЁН — он лечит симптом.
- Files: `docs/tasks/224/telegram-bot-api/{telegram-bot-api.service,telegram-bot-api.env.example,INSTALL.md}`
- Test: `tests/test_tg_bot_api_unit.py` (4 теста) — committed RED
  ```
  >  assert UNIT.is_file(), f"подготовленный юнит не создан: {UNIT}"
  E  AssertionError: подготовленный юнит не создан: .../docs/tasks/224/telegram-bot-api/telegram-bot-api.service
  ```
  Это **delivery-check**, а не поведенческий тест: юнит устанавливает владелец в своё окно.
- AC: четыре теста зелёные + в `ExecStart` НЕТ ни `--api-id`, ни `--api-hash` ни в каком
  виде, включая ссылку на переменную + `daemon-reload`/установка/рестарт НЕ выполняются,
  а выписаны в `INSTALL.md` дословно + образец env в репозитории содержит только
  плейсхолдеры (файл трекается git — реальные значения туда попасть не могут)
  + **`INSTALL.md` обязан содержать проверку ПОСЛЕ установки, которую выполняет владелец:**
  `ps -o args= -C telegram-bot-api | grep -c -- '--api-'` → ожидается `0`, плюс проверка,
  что сервис поднялся (`systemctl is-active`). Delivery-check в тестах доказывает только
  подготовленный текст; что значение ушло из argv живого процесса, доказывает эта команда.
- blocked-by: none

### T7 — не-stdio/http сервер на файловом маршруте падает ГРОМКО
- Files: `app/backend_claude.py`
- Test: `tests/test_mcp_config_isolation.py::test_t7_sdk_server_refuses_file_route_loudly` — committed RED
  ```
  >  with pytest.raises(Exception) as exc:
  E  Failed: DID NOT RAISE <class 'Exception'>
  ```
- AC: тест зелёный; текст ошибки называет имя сервера и его `type`
- Обоснование: in-process sdk-сервер — объект в памяти, файлом он не объявляется. Сегодня
  таких у нас НЕТ (проверено разбором всех конфигов: 5 scope × 3 файла + `~/.claude.json`
  + все `mcp_servers_custom`; единственный sdk-сервер на хосте принадлежит чужому юниту
  `kesha-bot-vps.service`). Но `_parse_custom_mcp` (`manager.py:375`) пропускает произвольный
  dict со спавна → без гейта такой сервер однажды молча потеряет тулы.
- blocked-by: T3

---

## Порядок и параллельность

`T1 → T2` — цепочка (общий хелпер). `T3 → T7` — цепочка (одна функция).
`T4`, `T6` независимы и файлами ни с кем не пересекаются. `T5` ждёт решения.

## Окно применения

Правка в `app/` действует только после рестарта, окно назначает владелец — здесь рестарт не
предлагается. Замерено: `KillMode=control-group`, процессы агентов лежат в cgroup
`orchestra.service` → рестарт убивает их вместе с сервисом, они переподключаются с новым argv.
Отдельного «окна доживания» нет. Два процесса с `--mcp-config` из юнита `kesha-bot-vps.service`
наша правка не затрагивает вовсе.

## Риски

- **Тихая потеря тулов** — главный риск обоих файловых тикетов, поэтому приёмка требует
  живого вызова тула, а не только пустого grep по argv. Codex вдобавок молча стартует без
  пропавшего конфига (замер) → нужна fail-loud проверка применения.
- **Пере-маскирование** портит диагностику. Прикрыто двумя companion-guard'ами (T1, T2),
  которые зелены сейчас и покраснеют при жадном правиле.
- **Перф `publish`** — вызывается на каждый partial-чанк; правило регулярочное, O(len).
  Если станет горячо, замерять до оптимизаций.
