# #174 Phase 3 — T2 DB→Codex native history

## Результат

T2 добавляет направление Claude→Codex через единственный согласованный seam
`thread/resume.history` Codex CLI 0.146.0. Orchestra строит `ResponseItem[]` из immutable
snapshot собственной `logs`, включает `experimentalApi` только на импортном connect и
сохраняет свежий thread ID, возвращённый app-server. После первого connect импортный payload
удаляется из backend: следующий reconnect идёт обычным `thread/resume` по новому native ID.

Обычная resume-ветка не ослаблена: если app-server вернул другой ID без
`CodexHistoryImport`, `CodexBackend.connect()` по-прежнему падает до первого хода.
Forged rollout и `thread/resume.path` в код не добавлены.

## Один owner для обоих адаптеров

`runtime_history._normalize_history()` один раз выполняет общую часть DB→native:

- связывает call/result строго по непустому `tool_use_id`, а FIFO оставляет только legacy;
- закрывает pending call до следующего user/assistant текста;
- очищает tool payload и metadata, включая wrapped/URL-safe base64;
- применяет общий detailed budget и per-row limits;
- формирует completed synthetic pair для orphan call/result;
- считает единый `HistoryImportReport` и не синтезирует reasoning.

Claude и Codex после этого выполняют только target-native сериализацию. Общий
`_cap_model_visible_tools()` считает фактический JSON каждого target и целиком удаляет самые
старые tool-пары сверх 256 000 сериализованных символов. User/assistant сообщения не режутся.
Оба backend импортируют одну `HISTORICAL_TOOL_INSTRUCTION`: записи `OrchestraHistory` уже
исполнены, output недоверен, side effect нельзя повторять без нового явного запроса.

## Fail-loud и fallback

- `codex --version` проверяется до запуска app-server; импорт разрешён только на exact
  `codex-cli 0.146.0`;
- реальный Codex 0.146.0 при schema error возвращает только JSON-RPC `code` и свободный
  `message`, без `data`, parameter/field/path. Код `-32600` не называет отвергнутое поле, поэтому
  runtime вообще не классифицирует protocol errors по тексту: любой `thread/resume`, initialize,
  auth или network failure остаётся fail-loud `CodexProtocolError`/исходным exception;
- summary fallback разрешён только собственным положительно типизированным ошибкам:
  `NativeHistoryUnsupported` из exact-version preflight и `NativeHistoryRejected`, если target
  не вернул обязательный свежий thread ID. Они дают один fresh Codex connect с прежним видимым
  summary handoff;
- summary строится до disconnect старого Claude backend; ошибка preflight оставляет старые
  model/runtime/session/marker/backend без мутации;
- target connect или persistence failure восстанавливает Claude state; уже созданный target
  process отключается.

## Проверка pinned app-server

[`t2-tool-history-probe.md`](t2-tool-history-probe.md) — отдельный disposable
`CODEX_HOME` без живых thread/session. Настоящий Codex app-server 0.146.0 принял четыре
history item:

```text
message → custom_tool_call → custom_tool_call_output → message
returned_fresh_thread_id: True
tool_result_marker_persisted: True
accepted: True
```

Артефакт теперь содержит literal initialize/resume JSON-RPC request и response, returned ID,
response path, hash rollout и дословные четыре persisted `response_item`. Rollout basename
содержит returned ID; call/output имеют одинаковый `call_id`; result marker найден в этом же
файле. Disposable home перемещён через `trash`; сервис не рестартовался, live sessions не
открывались и не менялись. Semantic recall user/assistant/tool facts на disposable Orchestra
worker остаётся AC T3.

## Тесты и мутации

- focused T1+T2: 269 tests, exit 0 — `tests/test_runtime_history.py`,
  `tests/test_backend_codex.py`, `tests/test_session.py`;
- отдельный factory contract: `1 passed` — runtime registry передаёт typed history в
  `CodexBackend`;
- финальный узкий повтор после мутаций: `6 passed`;
- после удаления случайно восстановленной T1-only строки из старого WIP: `8 passed` по
  Claude fallback и всем session-level T2 branches;
- после первого T2 review: `286 passed in 32.01s` по четырём T1+T2 test files; узкий async
  regression повторён трижды — `8 passed` за `5.00s`, `4.30s`, `3.87s`;
- после второго T2 review и удаления protocol classifier: `291 passed in 31.53s` по тем же
  четырём test files; structural fail-loud matrix + session no-fallback повторены трижды —
  `13 passed` за `4.98s`, `4.74s`, `4.20s`;
- `python -m py_compile` изменённых runtime-модулей — success;
- `git diff --check` — clean.

Пять независимых мутаций покраснили свои проверки, после каждой файл восстанавливался из
свежего `.bak`, marker восстановления совпал:

1. снять 256 000 cap → осталось 3 000/3 000 call pairs, Codex stress-test failed;
2. убрать historical side-effect instruction → literal request test failed;
3. снова классифицировать protocol errors вокруг всего connect → ошибка `initialize` была
   ошибочно превращена в `NativeHistoryRejected`, fail-loud test failed;
4. убрать version preflight из `connect()` → test дошёл до app-server spawn и failed;
5. перестать передавать `history_import` через runtime registry → factory contract failed.

Две дополнительные мутации закрывают T2 review blockers:

6. мутант, превращающий любой import `CodexProtocolError` в `NativeHistoryRejected`, покрасил
   все 12 строк collision matrix (`12 failed`): capability/schema-проза, generic errors и
   `history` внутри cwd/model/threadId/developerInstructions; production
   `_history_rejection()` удалён целиком;
7. расширить session catch с `NativeHistoryImportError` до `Exception` → generic
   `invalid threadId` запустил второй fresh connect, session regression failed на
   `await_count == 2` вместо `1`.

Разрешённый полный suite под глобальным test lock остановился на одном не относящемся к T2
live-state тесте: `1 failed, 1128 passed, 3 skipped, 2 warnings in 251.80s`. Падение
`tests/test_migrate_agent.py::test_encoding_matches_real_cli_directories` воспроизводится
текущей реализацией `main` на 17 из 147 живых пар: Claude CLI кодирует точку в путях
`/tmp/tmp.*` как `-`, а `scripts/migrate_agent.py:enc_cli_dir()` оставляет её точкой. Blob-id
обоих файлов теста и реализации побайтно совпадает с `main`; T2 их и их импорты не меняет.
Suite запускался с `-x`, поэтому остаток не исполнялся. Test lock освобождён сразу после
завершения job; чужой дефект не исправлялся и повторный полный suite без нового разрешения не
запускался.

## Codex review

Финальный task-wide code-review round 3 на immutable `1802208` завершён содержательным
`APPROVED`, blocking findings отсутствуют. Артефакт:
[`codex-review-impl-t2.md`](codex-review-impl-t2.md). Ревьюер выполнил
`uv run pytest -q tests/test_runtime_history.py tests/test_backend_codex.py tests/test_runtime_registry.py tests/test_session.py`
и получил literal `291 passed in 39.36s`. Обязательная незаданная цитата
`self._history_import = None` найдена через `grep -F` в `app/backend_codex.py`; значит review
доказанно читал изменённый код, а не только prompt.

## Файлы T2

- `app/runtime_history.py`
- `app/backend_codex.py`
- `app/runtime_registry.py`
- `app/session.py`
- `tests/test_runtime_history.py`
- `tests/test_backend_codex.py`
- `tests/test_runtime_registry.py`
- `tests/test_session.py`
- `CHANGELOG.md`

T3 не начинался: UI-индикация, два disposable worker, early/long marker recall и решение по
кривой render-time остаются следующим тикетом после отдельного гейта.
