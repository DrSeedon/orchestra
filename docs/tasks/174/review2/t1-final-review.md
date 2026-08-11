# #174 T1 — финальное повторное кросс-ревью

## Вердикт

**Не мержить итоговое состояние как есть. Мержить после четырёх правок:**

1. общий лимит 256 000 должен ограничивать весь model-visible tool history, включая
   omission/truncation markers и synthetic completion;
2. sanitizer должен удалять валидный base64 с разрешёнными форматом пробелами и
   переносами строк, а не только одну непрерывную строку;
3. ошибка version preflight при внутреннем Claude reconnect не должна оставлять
   недисконнекченный client после того, как `AgentSession` теряет ссылку на backend;
4. WIP T2 `41f2ca4` нужно убрать из T1 delivery или вынести на отдельную ветку: он не
   входил в предмет и не был отревьюен.

Четыре из пяти blocking первого круга закрыты. Пятый закрыт только частично:
обычный и URL-safe contiguous base64 редактируются, `tool_name` очищается и режется,
но общий бюджет и валидный wrapped base64 всё ещё обходятся.

## Что именно проверено

Указанный в постановке локальный ref оказался устаревшим:

```text
task-174/feat-runtime-switch -> 0aa53d2
git diff $(git merge-base main task-174/feat-runtime-switch) task-174/feat-runtime-switch
0 bytes
```

Поэтому итог проверен по названному immutable commit `b978572`, который находится на
активном author-worktree ref `adhoc-1786436618-3/feat-runtime-switch`; его merge-base с
веткой разработки — `bf9d8b1`. Фактический `/tmp/t1-final.diff` — 150 799 байт.

Первый и единственный раунд внешнего Codex review состоялся. Ревьюер сообщил о 43
запущенных focused tests (`all passed`) и привёл отсутствовавшую в запросе дословную
строку:

```text
remaining_tool_budget = TOOL_DETAIL_BUDGET
```

Проверка чтения артефакта:

```text
$ grep -F 'remaining_tool_budget = TOOL_DETAIL_BUDGET' /tmp/t1-final.diff
+    remaining_tool_budget = TOOL_DETAIL_BUDGET
```

Внешний вердикт — `NEEDS WORK`. Полный артефакт: [`codex-t1-final.md`](codex-t1-final.md).

Полный suite повторно не запускался по постановке. Заявленный автором результат
`2139 passed, 10 skipped` не считается моей самостоятельной проверкой. Помимо 43
focused tests внешнего ревьюера я исполнил три минимальные репродукции на точном
`b978572`; их результаты приведены ниже.

## Пять находок первого круга

### 1. Закрыто — reconnect читает актуальные logs

`AgentSession._reconnect_backend()` при `history_import_source == 'logs:claude'`
вызывает `_build_claude_history_import()` с текущими `session_id` и `model`, передаёт
результат в `backend.replace_history_import()` и только затем вызывает reconnect.
Сам builder ждёт текущие `_log_futures` и делает новый `get_history_logs()` snapshot.

Оба recovery path теперь проходят через этот owner:

- listener — `app/session.py:1349`;
- heartbeat — `app/session_hibernate.py:174`.

`ClaudeBackend.reconnect()` повторно проверяет pinned versions и создаёт client уже из
заменённого `ClaudeLogSessionStore`. Устаревший первоначальный snapshot больше не
переиспользуется на штатном успешном reconnect.

Отдельная новая ошибка failure path описана ниже; она не отменяет закрытие исходной
потери новых logs на успешном reconnect.

### 2. Закрыто — identified result не забирает чужой call

В `app/runtime_history.py:335-340` непустой `source_id` ищется только в
`pending_by_source[source_id]`. Ветка FIFO выполняется лишь при одновременно пустом
`source_id` результата и наличии `pending_legacy`.

Identified calls больше не добавляются в legacy FIFO. Непустой неизвестный ID доходит
до `matched is None`, получает отдельный synthetic call и немедленный result. Смешанный
случай identified + legacy закреплён тестом, который вошёл в зелёный focused набор.

### 3. Закрыто — synthetic completion стоит до assistant text

Ветка `row_type == 'text'` теперь вызывает `close_pending(row)` до записи assistant
message (`app/runtime_history.py:311-315`). Та же граница уже есть перед следующим user
message. Порядок для `tool -> text` теперь:

```text
assistant tool_use
user tool_result (synthetic terminal)
assistant text
```

Тест проверяет именно последовательность блоков, а не только совпадение ID.

### 4. Закрыто — fallback preflight не полупереключает объект

И native history, и emergency summary строятся до `old_state`, `_disconnect_backend()`
и любых изменений model/runtime/session/marker/handoff. Исключение из
`_build_runtime_handoff()` возвращает ошибку, пока старый backend остаётся тем же живым
объектом; target backend/process ещё не создавался.

Тесты для обоих направлений проверяют старое состояние, identity backend, отсутствие
его disconnect и отсутствие `_ensure_backend()`. Для T1 существенна Claude-ветка;
Codex-ветка относится к отложенному T2.

### 5. Всё ещё blocking — sanitizer и общий budget закрыты не полностью

Исправленная `_LARGE_BASE64` распознаёт непрерывный standard и URL-safe alphabet.
`tool_name` теперь проходит `_sanitize(binary=True)`, имеет отдельный предел 512 и
участвует в `tool_detailed_chars`. Эти две исходные конкретные дыры закрыты.

Остались два исполняемо подтверждённых обхода.

#### 5a. Generated history не входит в 256k

`_bounded_tool_text()` при исчерпанном бюджете возвращает model-visible omission marker,
но добавляет к `tool_detailed_chars` ноль. `close_pending()` создаёт terminal result для
каждого незакрытого call вообще вне бюджета. Wrapper metadata также не входит в счётчик.

Репродукция на 3 000 identified calls без results:

```text
{'budget': 256000, 'reported': 256000,
 'visible_record_chars': 680548, 'records': 6000, 'truncated': 539}
```

То есть счётчик достигает формального потолка, а фактический текст tool records уже
680 548 символов и продолжает линейно расти. Внешний ревьюер независимо получил тот же
класс дефекта: 352 893 model-visible символа при лимите 256 000.

Это не косметика отчёта: длинная сессия с большим числом незакрытых/обрезанных calls
способна переполнить context или сорвать native import/reconnect — именно риск, от
которого общий budget должен был защищать.

#### 5b. Валидный wrapped base64 проходит целиком

Base64 допускает пробельные символы между группами. Payload из 1 024 бинарных байт,
закодированный стандартным base64 и разбитый по 76 символов, успешно декодируется, но
ни один непрерывный фрагмент не достигает regex-порога 512.

Прямая проверка sanitizer:

```text
{'wrapped_b64_chars': 1385, 'valid_decode': True,
 'redactions': 0, 'survives': True}
```

Проверка полного Claude renderer:

```text
{'payload_equal': True, 'payload_chars': 1385,
 'redactions': 0, 'truncated': 0}
```

Payload остаётся дословным `recorded_call`. Это конкретный binary/base64 format, а не
обещание распознать произвольный секрет.

## Новая blocking-находка — reconnect version failure теряет owned client

`ClaudeBackend.reconnect()` сначала делает `await self._verify_history_versions()`, а
`disconnect()` вызывается только после успешной проверки (`app/backend_claude.py:443-445`).
Это разумно для сохранения старого transport до preflight, но оба caller failure path
затем без cleanup присваивают `self._backend = None`:

- listener — `app/session.py:1355-1359`;
- heartbeat — `app/session_hibernate.py:179-183`.

Если после установки другой CLI/SDK версии listener требует recovery, typed
`NativeHistoryUnsupported` возникает до disconnect. `AgentSession` теряет последнюю
ссылку на backend, хотя его прежний `ClaudeSDKClient` всё ещё принадлежит ему и может
держать subprocess.

Минимальная репродукция на точном final backend:

```text
{'old_client_still_owned': True, 'disconnect_awaits': 0}
```

Failure path должен либо безопасно перевести DB-backed import в видимый summary fallback,
либо явно очистить owned client до удаления ссылки. Просто обнулить `_backend` нельзя.

## Отложенный WIP T2

`b978572` содержит в ancestry `41f2ca4 WIP #174: add Codex history import before T1
review fixes`: 7 файлов, `+1091/-101`. Он затрагивает `app/backend_codex.py`, а также
пересекается с общими `runtime_history.py`, `session.py` и их тестами.

По прямому условию этот код не ревьюился. Однако merge ветки/commit `b978572` как T1
физически включит WIP. Поэтому перед merge delivery нужно перепостроить так, чтобы T1
содержал `333fb31` и релевантные исправления `4502a2a`, но не отложенную T2
реализацию; после перепостроения проверить, что исправления общих файлов сохранились.

## Итоговый список обязательных исправлений

- Ввести настоящий hard cap на полный сериализованный tool history либо ограничить
  число импортируемых completed records; стресс-тест должен считать фактические строки
  в native entries, а не `report.tool_detailed_chars`.
- Редактировать wrapped/whitespace base64 до budget и добавить planted fixture.
- Закрыть ownership/fallback при `NativeHistoryImportError` из reconnect preflight;
  тест должен одновременно проверять отсутствие orphan client/process и видимое
  согласованное состояние сессии.
- Удалить T2 WIP из T1 merge target и повторить focused T1 tests на собранном результате.
