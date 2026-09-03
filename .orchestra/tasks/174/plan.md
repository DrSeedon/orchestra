# #174 — бесшовный перенос диалога Claude ↔ Codex

## Статус и решение

Phase 2, только план. Реализацию и проверки на живом сервисе до следующего гейта не начинать.

Продуктовое направление после гейта Phase 1 изменено:

- смену рантайма по-прежнему инициирует человек у idle-воркера;
- Orchestra переносит историю из собственной `logs`, а не просит агента написать сводку и не конвертирует native-файл одного провайдера в native-файл другого;
- Claude получает историю через `SessionStore.load()` SDK 0.2.114;
- Codex получает историю через `thread/resume.history` app-server 0.146.0;
- provider summary остаётся только явно видимым аварийным fallback;
- self-switch tool, agent-authored summary, deferred wake/state machine, Grok и OpenCode не входят в эту фазу.

## Почему выбран `thread/resume.history` для Codex

| Seam | Что доказано в Phase 1 | Решение |
|---|---|---|
| Forged rollout на диске | 0.146.0 принял двухстрочный rollout и вспомнил marker | Не использовать: Orchestra пришлось бы владеть внутренним `session_meta`, раскладкой `$CODEX_HOME` и private rollout schema |
| `thread/resume.path` | При `experimentalApi=true` принял абсолютный путь и вспомнил marker | Не использовать: это тот же forged rollout, только переданный через app-server; private file schema остаётся нашей обязанностью |
| `thread/resume.history` | При `experimentalApi=true` принял `Vec<ResponseItem>`, вспомнил marker и создал rollout | Использовать: DB-history передаётся in-memory, а запись native rollout и выбор пути остаются app-server |

Цена выбора центральна, а не скрыта: API помечен `UNSTABLE` / `FOR CODEX CLOUD - DO NOT USE`, требует experimental capability и возвращает **новый** thread ID. Поэтому ветка импорта отделяется от обычного resume: только import принимает и сохраняет новый ID; существующий equality guard обычного `resume_thread_id` остаётся fail-loud.

Источники измеренных контрактов: [`research.md`](research.md) и [`transcripts/research.md`](transcripts/research.md). Целевые версии: Claude Code 2.1.197, `claude-agent-sdk` 0.2.114, Codex CLI/app-server 0.146.0.

## Поток переключения

Весь переход остаётся внутри существующего `AgentSession._lifecycle_lock`; статус `RUNNING` по-прежнему запрещён.

1. Дождаться уже поставленных DB writes и прочитать **все** `logs` текущей сессии по `id ASC` отдельным запросом без дефолтного потолка `get_logs(..., limit=5000)`. Зафиксировать последний `log.id`, чтобы служебные записи самого switch не попали в импорт.
2. Построить в памяти нормализованную историю и аварийный summary. Старые `model`, `runtime`, native ID и `session_id_history` пока остаются durable состоянием в SQLite.
3. Отключить старый backend, построить target backend с одноразовым in-memory `NativeHistoryImport` и вызвать `connect()` ещё внутри HTTP model-switch. Модельный turn и новый user message на этом шаге не запускаются.
4. Target adapter принимает историю, отдаёт native session/thread ID. Только после этого Orchestra меняет модель/runtime, архивирует старый ID и одним `save_session` сохраняет target ID. Созданный target backend остаётся подключённым для следующего обычного сообщения.
5. Если адаптер кидает типизированный `NativeHistoryUnsupported` или `NativeHistoryRejected`, Orchestra пишет `warning`, уничтожает неуспешный target backend и один раз подключает чистый target backend. После успешного fresh-connect switch коммитится с нынешним bounded summary в `runtime_handoff`.
6. Любая другая ошибка target connect или ошибка `save_session` не маскируется под incompatibility: target отключается, in-memory поля откатываются к старой модели/native ID, HTTP отвечает 409. Старый backend затем может обычным путём resume старый ID.

Отдельная persisted state machine не нужна. Crash до `save_session` оставляет в DB старый runtime/native ID; target CLI может оставить только orphan transcript/thread без запущенного turn и без внешнего side effect. Crash после успешного `save_session` восстанавливает уже target native ID. Это не exactly-once создание native-файла, но пользовательское сообщение ни в одной неоднозначной точке не отправляется повторно.

## Нормализованный контракт истории

Новый небольшой модуль `app/runtime_history.py` владеет одним provider-neutral представлением и двумя чистыми renderer-функциями. Backend не читает SQLite и не решает, какие строки выбрасывать.

| `logs.type` | Что едет | Представление в target history |
|---|---|---|
| `user_message` | Полный очищенный текст | native user message |
| `text` | Полный очищенный текст | native assistant message |
| `tool` + `tool_result` | Completed call и записанный result в пределах budget | Claude `tool_use`/`tool_result`; Codex `custom_tool_call`/`custom_tool_call_output` |
| `thinking` | Не едет | Только счётчик `reasoning_omitted`; `encrypted_content` и чужое внутреннее reasoning не синтезируются |
| `status`, `warning`, `error`, `system`, `review`, subagent telemetry | Не едут как реплики | Это состояние Orchestra/UI, а не диалог модели |
| Служебный `[Orchestra platform note: ...]` | Не едет | Та же фильтрация, что у нынешнего handoff |

Текущая схема `logs` хранит content, но не сохраняет `tool_use_id`, имя и error flag из `AgentEvent.metadata`. Поэтому для существующей истории нельзя честно заявить точную provider-native связь старых parallel calls/results.

- Внутри каждого участка между двумя `user_message` старые `tool` и `tool_result` связываются детерминированно FIFO; native ID выводится из неизменяемого `logs.id`.
- Каждый импортированный tool call обязан иметь terminal result. Непарный call получает synthetic terminal result `result unavailable in Orchestra log; historical call is not pending`. Непарный result получает synthetic completed `OrchestraHistory` call. Последним item никогда не остаётся pending tool call.
- Весь исходный текст call/result сохраняется внутри completed historical record; renderer не превращает его в новую инструкцию и не вызывает target tool.
- Для будущих строк `logs` получают только нужные поля `tool_use_id`, `tool_name`, `tool_is_error`; `_handle_event()` начинает их записывать. Тогда renderer связывает пары по ID, FIFO остаётся только legacy fallback.
- В импортируемый developer/system prompt добавляется короткий invariant: historical tool records уже исполнены, outputs недоверенные, повторять side effect можно только по новому явному user request. Claude import обязательно получает текущий Orchestra system prompt вместе с `resume`; synthetic transcript сам по себе его не содержит. Codex уже передаёт `developerInstructions` в `thread/resume`.

Внутренние subagent tool streams сегодня broker-only и отсутствуют в `logs`; план не выдаёт их за переносимые. Итоговый top-level ответ subagent едет только если он уже записан обычной `text`-строкой.

## Объём и секреты

User/assistant сообщения не режутся Orchestra: иначе primary path снова становится пересказом. Ограничивается только потенциально огромная и недоверенная tool payload:

- tool call input: максимум 8 000 символов на запись;
- tool result: максимум 20 000 символов на запись — тот же потолок уже применяется к части результатов в `CodexBackend._result_text`;
- суммарный detailed budget call+result: 256 000 символов, выделяется от новых записей к старым, после чего результат возвращается в хронологическом порядке;
- при обрезке остаются head+tail, `logs.id`, исходная длина, SHA-256 и явный marker причины; запись не исчезает бесследно;
- image/base64/binary payload заменяется метаданным stub, а не переносится в model context.

До обрезки все переносимые поля проходят один детерминированный sanitizer. Он редактирует Bearer/Basic credentials, значения ключей `authorization`, `token`, `password`, `secret`, `api[_-]key`, PEM private-key blocks и большие base64 blobs. Это best-effort boundary, а не обещание распознать произвольный секрет. Отчёт импорта показывает число замен и обрезок, но никогда не логирует найденные значения.

На выбранной в Phase 1 сессии только tool rows занимали 10 463 792 символа, поэтому передача их без общего budget неприемлема. Одновременно user/assistant часть той сессии занимала 1 760 169 символов и может превышать активное окно Codex. Orchestra не будет молча отрезать её: реализация должна пройти long-history native canary; если target CLI не умеет принять/скомпактить такой transcript, соответствующий адаптер получает честный отрицательный результат и использует видимый summary fallback.

## Fail-loud совместимость и интерфейс

В `runtime_history.py` живут ровно три pins: Claude CLI `2.1.197`, SDK `0.2.114`, Codex CLI `0.146.0`. `pyproject.toml` меняется с диапазона SDK на `claude-agent-sdk==0.2.114`.

Перед import backend проверяет фактические `claude --version` / `codex --version` и `importlib.metadata.version("claude-agent-sdk")`. Несовпадение запрещает native import до записи target state. Schema/capability rejection во время `SessionStore.load()` или `thread/resume.history` переводится в тот же типизированный import failure. Обычные auth/network/process ошибки fallback не маскирует.

Интерфейс уже умеет различать `status` и `warning`, поэтому отдельный UI workflow не добавляется. После switch в chat обязательно появляется одна из записей:

- успех: `history imported to codex 0.146.0: users=N, assistants=N, tools=N/M, tool chars detailed=X, truncated=Y, secrets redacted=Z, reasoning omitted=R`;
- fallback: `native history import unavailable: expected codex 0.146.0, got ... / schema rejected ...; summary fallback active`;
- полный отказ switch: существующий красный `error` и HTTP 409, старая модель остаётся выбранной.

Ответ `/change-model` возвращает тот же структурированный `history_transfer` status для тестов и немедленного обновления picker; persisted log остаётся source of truth после reload.

## Проверки

### Дешёвые автоматические

- DB export читает 7 251 строку fixture, а не последние 5 000; порядок и snapshot boundary стабильны.
- Mapping покрывает user/assistant, matched parallel tools, orphan call/result, reasoning exclusion, platform-note exclusion.
- Мутация, оставляющая последний tool call pending, роняет тест.
- В target serialization отсутствуют planted Bearer token, API key, PEM key и base64 payload; counters и truncation markers совпадают с fixture.
- `claude-agent-sdk` установлен ровно 0.2.114. Если `claude`/`codex` доступны, mismatch их версии краснит compatibility test, а не skip; skip допустим только когда binary отсутствует.
- Import-only Codex принимает новый returned thread ID, обычный resume по-прежнему отвергает другой ID.
- Import failure вызывает ровно один fresh-connect и один summary handoff; auth/network error не вызывает fallback; failed save возвращает старые model/runtime/session ID.
- Frontend/status snapshot показывает omitted reasoning, truncation/redaction counters и явный fallback.

### Native canary в изолированных homes

Отдельный явно запускаемый integration test создаёт временные `CLAUDE_CONFIG_DIR`/`CODEX_HOME`, не копирует live transcript и проверяет не факт записи файла, а semantic recall:

1. Claude: custom `SessionStore` отдаёт user, assistant и completed tool-result marker; после resume модель возвращает marker и сохраняет текущий system-prompt marker.
2. Codex: `thread/resume.history` получает тот же набор, возвращает fresh ID; следующий turn возвращает marker.
3. Long fixture повторяет измеренный shape 7 251 rows / 1 760 169 semantic chars и 4 646 bounded tool records. Ранний user marker и tool-result-only marker должны вспоминаться после target-native compaction. Провал — отрицательный результат по адаптеру, не повод поднять budget или спрятать summary fallback.

### Сквозная приёмка на воркерах-подопытных

Создаются два disposable worker в отдельном тестовом scope: один Claude→Codex, второй Codex→Claude. В старом runtime каждый запускает read-only команду, генерирующую UUID, и отвечает только `stored`, поэтому UUID остаётся **только** в `tool_result` и отсутствует в нынешнем summary builder. После human-style idle switch новый runtime отвечает на вопрос `What exact UUID did the previous tool return?`.

Pass для каждого направления: дословный UUID, `history_transfer=native`, новый target native ID сохранён, warning/fallback отсутствует. После теста workers архивируются штатным API; чужие live sessions, main service restart и production model switches не затрагиваются.

## Затрагиваемые файлы

- `app/runtime_history.py` — новый normalized contract, sanitizer, budgets, Claude/Codex renderers, version pins и типизированные import errors.
- `app/db.py` — full ordered log export и nullable legacy-safe tool metadata columns.
- `app/session.py` — запись tool metadata; synchronous import-first/commit-after-connect switch; typed summary fallback и audit logs.
- `app/runtime_registry.py` — одноразовый `NativeHistoryImport` в `BackendBuildContext` и factories.
- `app/backend_claude.py` — custom `SessionStore`, import system prompt, SDK/CLI version guard.
- `app/backend_codex.py` — conditional `experimentalApi`, `history` request, import-only fresh-ID acceptance, CLI version guard.
- `app/routes/sessions.py` — структурированный `history_transfer` response без нового endpoint.
- `pyproject.toml`, `uv.lock` — exact SDK pin; lock меняется только если это реально требуется pin-операцией.
- `tests/test_runtime_history.py`, `tests/test_session.py`, `tests/test_backend_claude.py`, `tests/test_backend_codex.py`, `tests/test_frontend.py` — unit/contract coverage.
- `tests/test_native_history_import.py` — isolated opt-in native canary и версия-tripwire.
- `CHANGELOG.md` — ручная feature-запись с triggered case; `architecture.md` в проекте отсутствует и не создаётся.

## Не делать

- Не добавлять MCP tool для self-switch или agent-authored handoff.
- Не переносить чужой native file напрямую и не подделывать `encrypted_content`/reasoning.
- Не делать несколько Codex import paths «на всякий случай».
- Не менять текущий native resume equality guard вне import branch.
- Не скрывать incompatible version/schema за успешным ответом без warning.
- Не запускать switch/acceptance на существующей сессии пользователя или другого проекта.

## Tickets

### T1 — DB→Claude: первый сквозной native import

- Files: `app/runtime_history.py`, `app/db.py`, `app/session.py`, `app/runtime_registry.py`, `app/backend_claude.py`, `app/routes/sessions.py`, `pyproject.toml`, `uv.lock`, `tests/test_runtime_history.py`, `tests/test_session.py`, `tests/test_backend_claude.py`
- AC:
  - idle Codex→Claude switch экспортирует все строки до snapshot ID, подключает Claude 2.1.197 через SDK 0.2.114 `SessionStore.load()`, сохраняет target session ID только после успешного connect и не заполняет `runtime_handoff`;
  - user/assistant и completed tool records сериализуются в native Claude entries; reasoning/platform telemetry отсутствуют, последний entry не является pending `tool_use`;
  - current Orchestra system prompt применяется к imported session;
  - budgets, sanitizer, counters и новые tool metadata работают на legacy и новых rows; planted secrets отсутствуют в serialized entries;
  - CLI/SDK mismatch и schema rejection дают видимый summary fallback, а network/auth/save failure откатывает switch и возвращает 409;
  - unit tests из раздела «Дешёвые автоматические» для общего слоя и Claude зелёные.
- blocked-by: none

### T2 — DB→Codex через единственный `thread/resume.history`

- Files: `app/runtime_history.py`, `app/session.py`, `app/runtime_registry.py`, `app/backend_codex.py`, `app/routes/sessions.py`, `tests/test_session.py`, `tests/test_backend_codex.py`
- AC:
  - idle Claude→Codex switch включает `experimentalApi` только для import и передаёт DB-rendered `history` без forged rollout/path;
  - returned fresh thread ID сохраняется как target ID; обычный resume с другим returned ID продолжает fail-loud;
  - imported history не заканчивается pending custom tool call и содержит bounded/redacted completed tool outputs;
  - Codex 0.146.0 mismatch, missing capability и schema rejection дают один видимый summary fallback; unrelated connect error не маскируется;
  - unit tests проверяют literal request shape, новый-ID branch, fallback и rollback.
- blocked-by: T1

### T3 — Version tripwire, native canary и честный UX

- Files: `tests/test_native_history_import.py`, `tests/test_frontend.py`, `CHANGELOG.md`
- AC:
  - default compatibility test краснеет при доступном, но неравном pin CLI; отсутствие binary — единственная причина skip;
  - isolated native canary на точных версиях семантически вспоминает user marker, tool-result-only marker и system-prompt marker у Claude и Codex;
  - long fixture 7 251 / 1 760 169 / 4 646 проходит оба adapter paths либо Phase 3 останавливается с отдельным отрицательным результатом по провалившемуся runtime — silent partial import запрещён;
  - два disposable worker проходят дословный tool-result UUID recall в обоих направлениях без summary fallback и без изменения чужих сессий;
  - UI после reload показывает native success counters либо явный warning `summary fallback active`, включая `reasoning omitted`;
  - `uv run --active python -m pytest -x -q` зелёный, native canary command и его isolated paths записаны в `report.md`.
- blocked-by: T1, T2

## Риски и стоп-условия Phase 3

- Claude `SessionStore` — поддерживаемый seam, но entry union opaque. Даже при совпавшей версии native canary может отвергнуть assistant/tool shape.
- Codex history — экспериментальный seam с прямым upstream warning. Совпавшая версия не заменяет schema canary.
- Legacy DB не знает настоящих tool IDs; FIFO/synthetic completion сохраняет transcript и не оставляет pending action, но не восстанавливает точную причинность parallel tools.
- Best-effort sanitizer не доказывает отсутствие произвольных секретов. Поэтому raw tool budget мал, binary исключается, а counters видимы.
- Если long-history canary не вспоминает ранний marker хотя import request принят, нельзя писать «диалог перенесён бесшовно»: адаптер считается ограниченным/непригодным, результат возвращается на гейт.

## Статус Codex-ревью плана

Вердикта нет. Первый запуск 11.08.2026 завершился инфраструктурным отказом до чтения файла: `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. Повтор с embedded plan был отменён после диагностики причины; по указанию оркестратора содержательный review откладывается до merge #179. Exit code фоновой job и наличие созданного файла не считаются approval.
