## Summary

Реализация близка к плану по форме: есть отдельный daemon, raw httpx SSE, split provider/model, MCP translation, turn_end metadata в целом совпадает с Codex success-path. Но asyncio/lifecycle часть пока не дожата: есть реальные пути без гарантированного `turn_end`, без явного закрытия SSE stream и с неawait'нутым `_chat_task`.

## Tests

Команда:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_backend_opencode.py -q
```

Результат в этой среде: `23 passed, 2 failed`.

Оба падения из-за sandbox-запрета на создание socket:

```text
FAILED tests/test_backend_opencode.py::test_free_port_returns_usable_int - PermissionError: [Errno 1] Operation not permitted
FAILED tests/test_backend_opencode.py::test_integration_real_turn - PermissionError: [Errno 1] Operation not permitted
```

То есть unit-логика прошла, но реальный daemon/integration path здесь не проверился.

## Findings

blocking: `events()` ловит только `StopAsyncIteration` из `next_line.result()` (`app/backend_opencode.py:198-202`). Если SSE stream упадёт через `httpx.ReadError`/`RemoteProtocolError`/другой runtime exception, исключение вылетит наружу, `turn_end` не будет, `_chat_task` останется жить/падать отдельно. Фикс: ловить ожидаемые исключения чтения SSE, явно закрывать SSE, затем yield `error` + `_error_turn_end("sse_failed: ...")` или дождаться/отменить chat task через общий cleanup helper.

blocking: `_chat_task` может остаться неawait'нутым (`app/backend_opencode.py:172`, `app/backend_opencode.py:348-359`). Нормальный `events()` его await'ит, но `disconnect()`/`interrupt()` во время хода, ранний выход consumer'а из `events()` или новый `send()` до drain старого хода оставляют task с возможным unhandled exception. Фикс: в `disconnect()` и в `events()` `finally` cancel/await task через `contextlib.suppress`, а в `send()` запретить новый turn пока старый `_chat_task` не завершён/не собран.

blocking: SSE async generator не закрывается явно на штатном `session.idle`/`session.error`/clean chat-first path (`app/backend_opencode.py:185`, `app/backend_opencode.py:232-248`). После `__anext__()` generator suspended внутри `async with self._http.stream(...)`; локальный `sse` просто теряется после `turn_end`, закрытие зависит от asyncgen finalizer/GC. На нескольких turns это риск утечки HTTP stream/connection. Фикс: `finally: ... await sse.aclose()`; pending `next_line.cancel()` тоже лучше await'ить с suppress `CancelledError`.

blocking: raw SSE frame парсится как будто всегда есть `properties` и `type` (`app/backend_opencode.py:203-208`). Любое валидное JSON-событие без этих ключей даст `KeyError`, оборвёт `events()` и не выдаст `turn_end`. Фикс плоский: `props = evt.get("properties") or {}`, `t = evt.get("type", "")`, неизвестные/неполные события игнорировать.

suggestion: `_map_part()` эмитит весь `part["text"]`/reasoning на каждый `message.part.updated` (`app/backend_opencode.py:264-269`). Если OpenCode присылает cumulative updated несколько раз для одного part, downstream получит дубли/повторный префикс в transcript. Фикс: держать per-turn `seen_text_len_by_part_id`/`seen_reasoning_len_by_part_id` и emit только suffix, либо эмитить только финальный update если у события есть надёжный terminal marker.

suggestion: тесты почти не покрывают критичный dual-source loop, хотя комментарий в `tests/test_backend_opencode.py:3-5` говорит обратное. Сейчас проверены mapper/metadata/config и один gated real turn, но нет fake-SSE тестов на `session.idle`, chat exception before idle, SSE exception, timeout, external cancellation/disconnect cleanup. Фикс: добавить unit-тесты с подменой `_sse_lines()`, `_chat_task` и `interrupt()`; именно они поймают первые четыре пункта без реального daemon.

nit: `_turn_end()` при `info.error` кладёт metadata `stop_reason="error"`, но content остаётся `stop_reason=<finish>` (`app/backend_opencode.py:303-306`). Если кто-то смотрит на content, это рассинхрон. Фикс: вычислить `stop_reason` один раз и использовать и в content, и в metadata.

## Verdict

требует доработки

## Round 2 — Re-review

### Статус blocking из Round 1

blocking #1, SSE read exception → FIXED. `events()` теперь ловит не только `StopAsyncIteration`, но и обычные исключения из `next_line.result()` (`httpx.ReadError`, `RemoteProtocolError`, runtime ошибки fake-SSE), отдаёт `error` и завершает ход через `_error_turn_end("sse_failed: ...")`. Добавленный тест `test_events_sse_read_exception` покрывает этот путь.

blocking #2, `_chat_task` lifecycle → STILL BROKEN. Часть фикса есть: `send()` запрещает overlapping turn, `disconnect()` cancel+await/retrieve exception делает корректно. Но `events()` не reaps `_chat_task` в `finally`: если consumer закрывает `events()` до `turn_end`, если SSE падает раньше завершения chat, или если timeout ставит `error_out`, `_chat_task` остаётся жить. Воспроизводится fake-SSE сценарием: получить первый `text`, вызвать `agen.aclose()`, после этого `b._chat_task.done() == False`, а следующий `send()` падает `RuntimeError: OpenCodeBackend turn already in progress`. Нужен cleanup в `events()` для нештатных/early-exit путей: отменить и await `_chat_task` с `contextlib.suppress(BaseException)` или явно дождаться/собрать результат, если task уже завершён.

blocking #3, явное закрытие SSE generator → NEW BUG. Явный `await sse.aclose()` добавлен, и штатный `session.idle` path теперь лучше. Но в `finally` сначала делается `next_line.cancel()`, а потом сразу `await sse.aclose()` без `await next_line`. Для async generator, у которого pending `__anext__()`, это реально даёт `RuntimeError: aclose(): asynchronous generator is already running`; `_aclose_gen()` проглатывает `Exception`, поэтому явное закрытие silently не происходит в этот момент. Минимальный asyncio probe это подтверждает. Фикс: после `next_line.cancel()` обязательно `await next_line` под `contextlib.suppress(BaseException)`, и только затем `await sse.aclose()`. Либо не глотать `RuntimeError` в `_aclose_gen`, чтобы такие ошибки не маскировались.

blocking #4, raw SSE `KeyError` на неполных событиях → FIXED. `props = evt.get("properties") or {}` и `t = evt.get("type", "")` убирают crash на валидном JSON без нужных ключей; `test_events_malformed_event_no_keyerror` покрывает этот случай.

### Новые замечания

blocking: concurrent `disconnect()`/external cancel `_chat_task` может пробросить `CancelledError` из `events()` без `turn_end` (`app/backend_opencode.py:237-245`). Если `asyncio.wait()` возвращает уже cancelled `_chat_task`, вызов `self._chat_task.exception()` сам raises `CancelledError` в Python 3.12. Это не ловится `except Exception`, потому что `CancelledError` наследуется от `BaseException`. Нужна отдельная ветка `if self._chat_task.cancelled(): ...` или `try/except BaseException` вокруг получения exception с нормальным `_error_turn_end("chat_cancelled")`.

medium: `_map_part()` suffix-only keyed только по `part["id"]`, fallback `""` (`app/backend_opencode.py:297-303`). Если OpenCode пришлёт два text/reasoning part без `id`, они будут делить один offset и второй part может быть частично или полностью подавлен. Если протокол гарантирует `id` для этих parts, это ок; иначе лучше fallback key делать из типа и стабильного локального индекса/объекта события, либо не применять suffix suppression без `id`.

### Tests

Команда:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_backend_opencode.py -q
```

Результат в этой среде: `32 passed, 2 failed`.

Оба падения прежние и связаны с sandbox-запретом на создание socket:

```text
FAILED tests/test_backend_opencode.py::test_free_port_returns_usable_int - PermissionError: [Errno 1] Operation not permitted
FAILED tests/test_backend_opencode.py::test_integration_real_turn - PermissionError: [Errno 1] Operation not permitted
```

### Вердикт

требует доработки

## Round 3

### Статус пунктов Round 2

blocking #2, `_chat_task` не reaped в `events()` early-exit → FIXED. В `finally` теперь при `not normal_end` отменяется и await'ится `_chat_task` под `suppress(BaseException)` (`app/backend_opencode.py:263-268`). `test_events_early_exit_reaps_chat_task` проходит: consumer может закрыть generator после первого `text`, task не остаётся live и следующий ход не блокируется старым in-flight task.

blocking #3, `aclose()` на running async generator → FIXED. Порядок cleanup стал правильным: `next_line.cancel()` → `await next_line` под `suppress(BaseException)` → `await sse.aclose()` (`app/backend_opencode.py:252-259`). Это закрывает прежний `RuntimeError: aclose(): asynchronous generator is already running`.

blocking, `CancelledError` из `_chat_task.exception()` → FIXED для chat-task-wins path. Перед `.exception()` добавлена ветка `self._chat_task.cancelled()` (`app/backend_opencode.py:239-242`), и `test_events_external_cancel_yields_turn_end` проходит: при внешней отмене `_chat_task` и молчащем SSE отдаётся один `turn_end` со `stop_reason=chat_cancelled`.

medium, suffix key по `id` с fallback `""` → FIXED. Если у text/reasoning part нет `id`, `_map_part()` больше не делит общий offset: он эмитит полный текст и выходит без suffix-dedup (`app/backend_opencode.py:311-316`). Это лучше, чем терять контент между безымянными parts; риск дубликатов без `id` не crash/leak.

### Новые findings

blocking: race `session.idle` + external cancel всё ещё может пробросить `CancelledError` без `turn_end`. Если `asyncio.wait()` возвращает SSE `session.idle` как completed branch, `events()` ставит `normal_end=True`, не reaps `_chat_task` в `finally`, а затем делает `await asyncio.wait_for(self._chat_task, timeout=10)` (`app/backend_opencode.py:273-276`). Если `_chat_task` уже cancelled к этому моменту, `CancelledError` наследуется от `BaseException` и не ловится `except Exception`, поэтому generator падает наружу. Минимальный fake-SSE probe с idle и одновременным `b._chat_task.cancel()` воспроизводит `asyncio.exceptions.CancelledError`. Фикс: в normal-end await path тоже отдельно обработать `task.cancelled()` / `except BaseException` для `CancelledError`, либо snapshot'ить task и использовать общий helper, который возвращает `_error_turn_end("chat_cancelled")`.

blocking: concurrent `disconnect()` может обнулить `self._chat_task` во время `events()` и дать crash. `disconnect()` после reaping ставит `self._chat_task = None` (`app/backend_opencode.py:411`), а `events()` после `asyncio.wait()` продолжает читать mutable attribute (`app/backend_opencode.py:239`, `app/backend_opencode.py:242`, `app/backend_opencode.py:275`). Fake-сценарий с `disconnect()` во время молчащего SSE воспроизводит `AttributeError: 'NoneType' object has no attribute 'cancelled'`. Это реальная teardown-гонка для listener/cleanup path. Фикс: в начале `events()` сделать локальный snapshot `chat_task = self._chat_task` и дальше работать только с ним; `disconnect()` может параллельно обнулить поле, но не должен ломать текущий iterator.

### Double-yield / swallow / races

Double-yield `turn_end` в текущей структуре не вижу: `error_out` и `normal_end` разведены, а после `_error_turn_end` стоит `return` (`app/backend_opencode.py:270-279`).

`finally` может отбросить успешный chat result на error paths (`sse_failed`, timeout, early consumer close), но это не выглядит как отдельный bug: в этих путях ход уже считается нештатным, и отдаётся error `turn_end`. На normal path результат не reaped в `finally`, а await'ится ниже.

Гонки есть две blocking выше: cancelled chat на normal-end await и mutable `self._chat_task` при concurrent `disconnect()`.

### Tests

Команда:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_backend_opencode.py -q
```

Результат в этой среде: `34 passed, 3 failed`.

Все три падения из-за sandbox-запрета на создание socket:

```text
FAILED tests/test_backend_opencode.py::test_free_port_returns_usable_int - PermissionError: [Errno 1] Operation not permitted
FAILED tests/test_backend_opencode.py::test_integration_lifecycle - PermissionError: [Errno 1] Operation not permitted
FAILED tests/test_backend_opencode.py::test_integration_real_turn - PermissionError: [Errno 1] Operation not permitted
```

Новые unit-тесты `test_events_early_exit_reaps_chat_task` и `test_events_external_cancel_yields_turn_end` проходят.

### Вердикт

требует доработки

## Round 4

### Статус двух blocking-гонок из Round 3

blocking #1, normal-end await path + `CancelledError` → FIXED. В normal-end tail теперь используется локальный `chat_task`, сначала проверяется `chat_task.cancelled()`, затем `await asyncio.wait_for(chat_task, timeout=10)` имеет отдельный `except asyncio.CancelledError` и отдаёт `_error_turn_end("chat_cancelled")`. Это закрывает путь `session.idle`/SSE close → concurrent cancel → утечка `CancelledError` наружу без `turn_end`.

blocking #2, concurrent `disconnect()` обнуляет `self._chat_task` → FIXED. `events()` snapshot'ит `chat_task = self._chat_task` в начале и дальше в loop, cleanup и normal-end tail работает только с локальным task. Обнуление `self._chat_task` параллельным teardown больше не даёт `AttributeError`.

### Turn-end audit

Для backend-controlled путей выхода вижу ровно один terminal `turn_end`: `idle`/SSE EOF идут через `normal_end` и `_turn_end()` либо `_error_turn_end(...)`; `sse_failed`, `timeout`, `chat_failed`, `chat_cancelled` идут через `error_out` и сразу `return` после `_error_turn_end(...)`. Двойного `turn_end` в этой структуре не вижу: `error_out` и `normal_end` разведены, cleanup ничего не yield'ит.

`early-close` consumer'ом не может гарантированно доставить `turn_end` по семантике async generator close: если внешний consumer сам закрыл iterator до терминального события, yield из cleanup невозможен. Важный для этого пути критерий — отсутствие leak; текущий `finally` отменяет/await'ит pending `next_line`, закрывает SSE generator и reaps локальный `chat_task` при `not normal_end`, поэтому blocking leak здесь не вижу.

Свежих blocking-багов от snapshot не нашёл. Snapshot не меняет ownership semantics `disconnect()`: поле может быть `None`, но текущий iterator держит task reference до cleanup/terminal path.

### Tests

Команда:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_backend_opencode.py -q
```

Результат в этой среде: `36 passed, 3 failed`.

Три падения прежние и не относятся к `events()` lifecycle: sandbox запрещает создание socket (`PermissionError: [Errno 1] Operation not permitted`) в `test_free_port_returns_usable_int`, `test_integration_lifecycle`, `test_integration_real_turn`.

Новые regression-тесты `test_events_idle_then_chat_cancelled_yields_turn_end` и `test_events_survives_concurrent_disconnect_nulling_task` проходят в составе этих 36 passed.

### Вердикт

APPROVED
