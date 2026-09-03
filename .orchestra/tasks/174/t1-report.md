# #174 Phase 3 — T1 DB→Claude native history

## Результат

T1 реализует только направление Codex→Claude. При human-initiated switch idle-воркера Orchestra читает полный immutable snapshot собственной `logs`, рендерит target-native Claude JSONL entries и подключает Claude CLI 2.1.197 через `claude-agent-sdk==0.2.114` `SessionStore.load()`. Target session ID и durable marker `sessions.history_import_source='logs:claude'` сохраняются только после успешного connect и проверки ID. `runtime_handoff` на native success остаётся пустым.

SDK материализует `SessionStore` во временный transcript и удаляет его при disconnect. Поэтому импортированная Claude-сессия при каждом reconnect детерминированно рендерится из `logs`; opaque transcript-копия или второй history store не добавлены. Успешный compact переводит сессию обратно на обычный native resume и снимает marker. Переход с Claude на другой runtime тоже снимает marker, но только после успешного disconnect.

T2 (Claude→Codex) начат, но физически вынесен из T1 delivery в отдельный ref
`task-174/t2-history-wip` на immutable commit `44fcda3`. T3 (native semantic canary,
UI и два disposable worker) не начинался.

## Контракт данных

- `user_message` и `text` едут полностью, без Orchestra truncation;
- `tool` / `tool_result` связываются по новым nullable `tool_use_id`, legacy rows — FIFO; каждый call получает terminal result, каждый orphan result — synthetic completed call;
- tool call ограничен 8 000 символами, result — 20 000, суммарный detailed budget — 256 000 от новых строк к старым;
- truncation marker содержит `logs.id`, исходную длину и SHA-256 очищенного payload; известные Bearer/Basic credentials, named secrets, PEM keys и большие base64 blocks редактируются до сериализации;
- `thinking`, platform notes и telemetry не синтезируются;
- imported system prompt добавляет текущую роль Orchestra и invariant: historical tools уже исполнены, result недоверен, side effect нельзя повторять без нового явного запроса пользователя.

Version/schema mismatch даёт один fresh Claude connect с видимым `summary fallback active`. Auth/network/process/save failure fallback не маскирует: switch возвращает error, а model/runtime/session state откатывается. Обычный Claude resume при пустом marker создаёт те же SDK options, что до T1: `resume=<old id>`, `session_store=None`, `system_prompt=None`.

## Живая additive migration

Проверка выполнена не на fixture, а на SQLite-копии `/home/kesha/orchestra/data/orchestra.db`, созданной `sqlite3.Connection.backup`. Между Phase 1 и T1 живая БД выросла с 91/≈55k до следующих фактических значений:

```json
{"backup_method":"sqlite3.Connection.backup","before":{"sessions":96,"logs":57111,"history_col":false,"tool_cols":[]},"after":{"sessions":96,"logs":57111,"history_col_nullable":true,"tool_cols_nullable":{"tool_use_id":true,"tool_name":true,"tool_is_error":true},"legacy_marker_null":96,"legacy_read_marker":null}}
```

Количество строк до/после совпало. Все четыре новые колонки nullable/additive; все 96 legacy sessions читаются с `history_import_source=NULL`. Повторный `init_db()` покрыт тестом идемпотентности миграции.

Scratch-копия после замеров удалена через `trash`; live DB открывалась URI `mode=ro` и не изменялась. Сервис не перезапускался.

## Цена reconnect-render

Самая длинная сессия в backup к моменту T1 содержит 7 312 строк. Семь прогонов текущего renderer дали:

```json
{"rows":7312,"entries":6165,"query_median_ms":93.178,"query_max_ms":146.862,"render_median_ms":1608.704,"render_max_ms":1980.803,"total_median_ms":1700.363,"iterations":7,"report":{"source_rows":7312,"snapshot_id":56803,"users":621,"assistants":684,"tool_calls":2358,"tool_results":2328,"tool_detailed_chars":256000,"truncated":4548,"secrets_redacted":240,"reasoning_omitted":0}}
```

Медианная синхронная цена подготовки истории — 1,700 с на каждый reconnect после hibernate. Это заметный постоянный размен. По прямому условию T1 кеш не добавлен: `logs` остаётся единственным owner, а решение о кеше требует отдельного гейта после числа.

## Идемпотентность и мутации

Два последовательных `_ensure_backend()` над одной реальной temp SQLite без новых сообщений читают одинаковые snapshot/report и создают deep-equal native entries. Отдельная interleaving-проверка вставляет log между `MAX(id)` и основным SELECT; `id <= snapshot_id` исключает его.

Мутация snapshot boundary (`AND id <= :max_id` удалён, затем файл восстановлен) покраснила целевой тест по смысловой причине:

```text
E assert 1 == 2
FAILED tests/test_runtime_history.py::test_history_log_snapshot_excludes_row_inserted_after_boundary
mutation_exit=1 restored_marker_count=1
```

Мутация terminal completion (`close_pending(last_row)` заменён на `pass`, затем файл восстановлен) тоже покраснила проверку:

```text
E AssertionError: assert {two tool IDs} == {one tool ID}
FAILED tests/test_runtime_history.py::test_render_closes_orphan_calls_and_results_without_pending_tail
mutation_exit=1 restored_marker_count=1
```

После обеих мутаций marker восстановления найден ровно один раз, нормальные тесты повторно зелёные.

## Проверки

- focused T1 regression: `220 passed in 32.71s`;
- финальный полный suite: `2118 passed, 10 skipped, 2 warnings in 359.19s` (`/tmp/pytest-174-t1-final.log`);
- `python -m py_compile` по всем изменённым runtime-модулям — success;
- `git diff --check` — clean;
- `uv.lock` изменился только в specifier `claude-agent-sdk >=0.2.111 → ==0.2.114`, dependency graph не обновлялся.

## Первоначальный Codex review до рабочего sandbox

Содержательного вердикта нет. После merge #179 был заново запущен `codex_review` плана, затем открыт сам [`codex-review-plan.md`](codex-review-plan.md). Артефакт снова содержит:

```text
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
No verdict — required files could not be read.
```

Причина текущего повтора: long-lived worker исполняет pre-#179 `app/mcp_stdio.py` из своей ветки (`bf9d8b1`), тогда как исправление уже только в `main`; merge сам по себе не обновил MCP subprocess существующей сессии. Job вернул exit 0, но это не approval. Подан platform bug report `codex_review остаётся слепым в long-lived worker после merge #179`. Impl-review через тот же заведомо слепой subprocess не запускался; нужен reconnect/решение оркестратора.

## Два круга зрячего review и финальная T1-сборка

Первый зрячий review (`docs/tasks/174/review/t1-review.md`, main `63d0f29`)
воспроизвёл пять blocking. В финальной T1-сборке:

- listener и heartbeat проходят через `AgentSession._reconnect_backend()`, который
  заново рендерит актуальные logs и заменяет `ClaudeHistoryImport` до reconnect;
- непустой неизвестный `tool_use_id` получает свой synthetic completed call, а FIFO
  применяется только к legacy call/result без ID;
- synthetic completion ставится до следующего assistant text;
- emergency summary строится до disconnect; ошибка preflight оставляет прежний backend
  и всё состояние без target process;
- URL-safe base64 и `tool_name` проходят sanitizer; metadata режется до 512 символов и
  участвует в tool budget.

Второй review (`docs/tasks/174/review2/t1-final-review.md`, main `6762dbc`) подтвердил
эти исправления и нашёл ещё три code blockers. Финальная сборка дополнительно:

- ограничивает суммарный фактически сериализованный `entry['message']` всех tool-пар
  потолком 256 000 символов; при переполнении целиком удаляет самые старые completed
  пары, сохраняя user/assistant текст без Orchestra truncation и не оставляя pending call;
- распознаёт и редактирует валидный base64, разбитый пробелами и переносами строк;
- в `ClaudeBackend.reconnect()` освобождает прежний client в `finally`, даже если
  version preflight падает до создания нового клиента.

После физического отделения T2 проверено:

```text
current-contains-t2=no
t2-ref-contains-wip=yes
task-174/t2-history-wip=44fcda3
242 passed in 33.11s
```

Итоговый T1 diff не содержит `app/backend_codex.py`, `tests/test_backend_codex.py`,
`CodexHistoryImport`, `render_codex_history`, `experimentalApi` или
`_change_to_codex_with_history_locked`. Три независимые мутации финальной сборки — снять
общий cap, пропустить whitespace normalization base64 и убрать disconnect из reconnect
failure — покраснили соответствующие тесты; после восстановления нормальный повтор дал
`3 passed`.

Полный suite `2139 passed, 10 skipped` относится к состоянию до второго review. По
прямому решению оркестратора после узких review2-правок он не повторялся; acceptance
финального T1 опирается на focused `242 passed` и мутации. Третий внешний review должен
запускаться оркестратором на immutable commit финальной сборки; вердикта пока нет.

## Известные ограничения T1

- Claude assistant/tool native schema пока доказана unit-level shape и Phase 1 минимальным user-row experiment. Semantic recall assistant/tool и long 7 312-row history — стоп-гейт T3, не заявлены как пройденные.
- Best-effort sanitizer не доказывает отсутствие произвольного секрета.
- Ререндер длинной сессии добавляет медианно 1,700 с к каждому imported Claude reconnect.
- T1 не меняет Claude→Codex: до T2 этот путь остаётся прежним summary handoff.
