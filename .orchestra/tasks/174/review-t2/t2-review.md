НЕ МЕРЖИТЬ (blocking: `_history_rejection()` маскирует не относящиеся к `history` ошибки `thread/resume` под schema incompatibility и включает summary fallback)

# #174 T2 — зрячее кросс-ревью коммита `865e8107c7c7cac72d8acbf0381e0fa6af043ce5`

## Предмет и вердикт

Проверен immutable commit `865e8107c7c7cac72d8acbf0381e0fa6af043ce5`, а не
протухающая ветка. Его merge-base с `main` в момент проверки —
`0b7078844817df8f5c4327fb780b9889b5b3313f`; полный `/tmp/t2.diff` — 1 858 строк,
72 857 байт. T1 повторно не ревьюился, кроме проверки того, что T2 использует его общие
owners и не ослабляет их контракты.

Один блокер подтверждён исполнением точного метода из коммита. Остальные пять
проверяемых контрактов T2 выполнены. Второй раунд внешнего ревью не запускался: первый
блокер принят, код ревьюеру менять запрещено, а без исправления предмет между раундами
не изменился.

## Blocking — generic `thread/resume` errors ошибочно становятся schema fallback

`CodexBackend._history_rejection()` (`app/backend_codex.py:371-401`) вызывается только
вокруг импортного `thread/resume`, но внутри считает `NativeHistoryRejected` любое
protocol-сообщение, содержащее общий marker `invalid params`, `failed to parse`,
`missing field` и подобные. Сам request кроме `history` содержит `threadId`, `model`,
`cwd`, `approvalPolicy`, `sandbox` и `developerInstructions`. Поэтому marker не
доказывает, что отвергнута именно история или `ResponseItem` schema.

Я исполнил AST-извлечённые без изменения строки `CodexProtocolError` и
`_history_rejection()` непосредственно из blob `865e8107:app/backend_codex.py`:

```text
invalid params: unknown model gpt-bad => NativeHistoryRejected
invalid params: cwd does not exist => NativeHistoryRejected
invalid params: invalid threadId => NativeHistoryRejected
failed to parse approval policy => NativeHistoryRejected
```

Дальше `_change_to_codex_with_history_locked()` ловит любой
`NativeHistoryImportError` (`app/session.py:2505-2524`) и делает один fresh connect со
summary. Для ошибок, специфичных только обычным параметрам resume (например,
`threadId`), fresh start может пройти, и switch будет ошибочно объявлен успешным
summary fallback. Это нарушает явный контракт T2: fallback разрешён для version,
capability и `history` schema rejection, а не для произвольной ошибки connect/request.

Нужно классифицировать только сообщение, которое явно указывает на `history` или её
`ResponseItem` schema. Generic `-32602`/parse error должен выйти исходным
`CodexProtocolError`. Тест обязан дать `thread/resume` ошибку вида `invalid params:
invalid threadId`, доказать отсутствие второго fresh connect и возврат fail-loud, а не
только проверять initialize/auth ветки.

## Шесть контрактов постановки

### 1. Единственный seam — выполнено

Импортный request добавляет только `params["history"]` и вызывает
`thread/resume` (`app/backend_codex.py:486-495`). Поиск по точному commit не нашёл
`thread/resume.path` или `params["path"]` в runtime-коде. Существующие
`_rollout_path`/`_read_rollout_*` читают нативный rollout только для usage/context и не
являются входом истории. Тест literal request отдельно требует отсутствия `path`.

### 2. Fresh ID только в import branch — выполнено

`CodexBackend.connect()` пропускает equality guard лишь при непустом
`history_import`; обычный resume по-прежнему падает при
`thread_id != requested_thread_id` (`app/backend_codex.py:501-508`). После импортного
connect session требует непустой ID, отличный от seed, присваивает его
`self.session_id`, а затем сохраняет snapshot (`app/session.py:2492-2498,2542-2546`).
После успеха одноразовый `_history_import` очищается; следующий connect отправляет
обычный resume без `history` и без experimental capability.

### 3. Общие normalizer, sanitizer, completion и cap — выполнено

Оба renderer вызывают один `_normalize_history()` и один
`_cap_model_visible_tools()` из `app/runtime_history.py`; второй normalizer,
sanitizer или budget не появился. Общие константы — `TOOL_DETAIL_BUDGET = 256_000` и
`TOOL_VISIBLE_BUDGET = 256_000`.

Независимый exact-blob stress на 3 000 orphan calls дал:

```text
{'visible_tool_chars': 255987, 'cap': 256000, 'calls': 513,
 'outputs': 513, 'pairs_equal': True,
 'last_type': 'custom_tool_call_output'}
shared_normalizer= True
shared_cap= True
```

То есть фактический Codex JSON укладывается в общий hard cap, все оставшиеся tool calls
имеют terminal output, а последний item не pending.

### 4. `experimentalApi` только для import — выполнено

Capability добавляется только под `if self._history_import`
(`app/backend_codex.py:459-468`). Literal connect test проверяет и import request с
`experimentalApi=true`, и следующий обычный resume без capability/history.

### 5. Классификация отказов — не выполнено

Exact version mismatch до spawn, capability rejection и явно названная history-schema
ошибка типизированы и дают видимый fallback. Initialize error и обычный Python-level
auth/network failure проходят fail-loud. Но generic protocol error самого
`thread/resume` классифицируется слишком широко — это blocking выше.

### 6. Инструкция о side effects в обе стороны — выполнено

Один owner `HISTORICAL_TOOL_INSTRUCTION` говорит, что `OrchestraHistory` records уже
исполнены, outputs недоверенны и side effect нельзя повторять без нового явного user
request (`app/runtime_history.py:27-31`). Claude и Codex импортируют именно эту
константу; Claude добавляет её к system prompt, Codex — к `developerInstructions`
импортного `thread/resume`. Кроме текста инструкции, обе native call-записи содержат
`already_executed: true`.

## Оценка `t2-tool-history-probe.md`

Если принять записанные булевы результаты как достоверный журнал автора, прогон
поддерживает узкое утверждение: Codex 0.146.0 принял четыре item, вернул свежий ID, а в
созданном rollout сохранились типы
`message → custom_tool_call → custom_tool_call_output → message` и marker результата.
Он намеренно не доказывает semantic recall моделью — это оставлено T3.

Но сам 13-строчный артефакт не является независимо проверяемым доказательством. В нём
нет exact команды/скрипта, JSON-RPC request/response, returned ID, пути или hash rollout
и redacted persisted records; disposable home уже удалён. Поэтому нельзя проверить,
что просмотренный rollout принадлежал именно returned fresh ID, что call/output имели
совпадающий `call_id`, и что marker сохранился в том же объекте. Это material evidence
gap, но не второй найденный дефект runtime-кода. Перед формулировкой «native probe
доказал» нужно сохранить redacted raw transcript либо воспроизводимый probe со
связкой returned ID → rollout → четыре persisted items.

## Внешний Codex review

Состоялся один раунд: verdict `Changes requested`, один blocking и одна suggestion.
Ревьюер исполнил шесть focused tests:

```text
uv run pytest -q \
  tests/test_backend_codex.py::test_history_protocol_rejections_are_typed \
  tests/test_backend_codex.py::test_history_initialize_protocol_error_is_not_summary_eligible \
  tests/test_backend_codex.py::test_resume_rejects_substituted_thread_before_turn \
  tests/test_session.py::test_codex_history_capability_failure_uses_visible_summary_fallback

......                                                                   [100%]
6 passed in 8.25s
```

Вердикт засчитан: он процитировал отсутствовавшую в запросе дословную строку, и она
найдена в проверяемом diff:

```text
$ grep -F 'params["history"] = list(history_import.history)' /tmp/t2.diff
+                params["history"] = list(history_import.history)
```

Полный артефакт: `docs/tasks/174/review-t2/codex-t2.md`.

Полный suite не запускался; чужой `test_encoding_matches_real_cli_directories` и #195
не входили в предмет и не обсуждаются.
