НЕ МЕРЖИТЬ (blocking: `_history_rejection()` считает любое `history` в тексте доказательством history-schema rejection)

# #174 T2 — второй круг зрячего ревью

Проверен immutable commit
`33ceee998f7955950972c771d8ba0bcce2283aa5`, а не протухающая ветка. Merge-base с
`main` — `0b7078844817df8f5c4327fb780b9889b5b3313f`; `/tmp/t2-final.diff` —
2 023 строки, 83 074 байта. Пять контрактов, закрытых первым кругом,
не перепроверялись: после `865e8107` из production-кода изменён только
классификатор в `app/backend_codex.py`; остальные правки — тесты и evidence-документы.

## Blocking — subject не привязан к отвергнутому полю

Обычные generic-ошибки без слова `history` теперь действительно выходят исходным
`CodexProtocolError`. Однако `app/backend_codex.py:397-402` определяет subject
простыми substring-проверками по всему тексту ошибки. Это не доказывает,
что app-server отверг именно поле `history` или `ResponseItem` schema.

Исполнён без изменений AST-извлечённый `_history_rejection()` из blob
`33ceee9:app/backend_codex.py`:

```text
SCHEMA     | NativeHistoryRejected    | invalid params: invalid type for history item
SCHEMA     | NativeHistoryRejected    | failed to deserialize ResponseItem variant
SCHEMA     | NativeHistoryUnsupported | unknown field `history`
GENERIC    | CodexProtocolError       | invalid params: unknown model gpt-bad
GENERIC    | CodexProtocolError       | invalid params: cwd does not exist
GENERIC    | CodexProtocolError       | invalid params: invalid threadId
GENERIC    | CodexProtocolError       | failed to parse approval policy
GENERIC    | CodexProtocolError       | method not found
INCIDENTAL | NativeHistoryRejected    | invalid params: cwd '/srv/history' does not exist
INCIDENTAL | NativeHistoryRejected    | invalid params: unknown model 'history-large'
INCIDENTAL | NativeHistoryRejected    | failed to parse developerInstructions: history must be preserved
INCIDENTAL | NativeHistoryRejected    | invalid params: invalid threadId history-legacy
LOUD       | RuntimeError             | authentication required
LOUD       | RuntimeError             | network connection reset
```

Итог: прежние четыре generic-примера починены, но четыре из четырёх ошибок
со случайным `history` в значении всё ещё ложно типизируются. Внешнее Codex-review
независимо получило тот же результат на cwd/model/thread/developer-instructions.

Это не только ошибка лейбла: `app/session.py:2505-2524` ловит получившийся
`NativeHistoryImportError`, делает второй fresh connect и объявляет summary fallback.
Тест `tests/test_backend_codex.py:570-612` даёт generic-примеры только без
случайного `history`, а session regression проверяет только `invalid threadId`.
Авторская мутация «убрать subject целиком» поэтому не проверяет нужную границу.

## Обратные случаи

Три genuine schema/capability примера при исполнении остались типизированными.
Исторически сохранённое реальное сообщение app-server 0.146.0 про capability
получило `NativeHistoryUnsupported`; реальные ошибки thread store / missing rollout /
empty rollout остались `CodexProtocolError`:

```text
NativeHistoryUnsupported | thread/resume.history requires experimentalApi capability
CodexProtocolError       | thread/resume failed: failed to read thread: thread-store internal error
CodexProtocolError       | thread/resume failed: no rollout found for thread id 00000000-0000-0000-0000-000000000000
CodexProtocolError       | rollout at /tmp/probe/forged.jsonl is empty
```

Видимый fallback при типизированном отказе и fail-loud при auth закрыты отдельными
session-тестами в immutable blob: fallback сохраняет `runtime_handoff`, присваивает
`history_transfer.mode == "summary"` и пишет warning (`tests/test_session.py:4430-4488`);
auth возвращает `ok=False`, старый runtime/session и только один connect
(`tests/test_session.py:4534-4566`). После правок блокера эти ветки не сломаны.

## Evidence автора

Дыра первого круга закрыта. `t2-tool-history-probe.md` теперь показывает:

- literal `thread/resume` request с четырьмя item;
- literal response, где один и тот же fresh ID стоит в `thread.id`, `sessionId` и
  basename возвращённого `path`;
- отдельную проверку существования этого файла, совпадения ID с basename и SHA-256;
- дословные четыре persisted `response_item`, где call/output имеют один
  `call_id`, а result marker присутствует.

Связь «возвращённый ID → указанный самим app-server rollout → четыре persisted
payload» показана сырыми значениями, а не только итоговыми boolean или пересказом.
Артефакт не доказывает semantic recall, но это явно оставлено T3 и не является
утверждением T2.

## Внешнее Codex-review

Раунд 2 состоялся: verdict `DO NOT MERGE`, один blocking, без suggestions.
Ревьюер независимо исполнил classifier matrix и подтвердил блокер.
Вердикт засчитан: цитата из проверяемого diff, которой не было в запросе,
найдена дословно:

```text
$ grep -F '"history" in detail' /tmp/t2-final.diff
+            "history" in detail
```

Полный артефакт: `docs/tasks/174/review-t2-final/codex-review.md`.

Новых independent production-blockers в правках не найдено; найден неполный фикс
прежнего blocking.
