## Summary

План в целом рабочий для MVP: правильная ставка на raw SSE, `chat()` как источник итоговой стоимости/токенов, и отдельный daemon на backend instance достаточно просты для текущего масштаба. Но в текущем виде есть два места, которые могут подвесить turn или оставить процесс: ожидание только `session.idle` при уже упавшем `chat()` task и неполный teardown daemon.

## Findings

blocking: `events()` ждёт `session.idle` как единственный barrier, но если `client.session.chat()` быстро упадёт HTTP-ошибкой, а SSE stream останется живым и не пришлёт `session.error/session.idle`, цикл на `plan.md:64-75` может висеть бесконечно -> в `events()` надо одновременно мониторить `_chat_task` и SSE: если task завершился с exception до idle, сразу yield `error` + error `turn_end`; плюс общий timeout на turn с `abort()` и `ok=False`.

blocking: teardown может оставить daemon/zombie: `plan.md:105-106` делает `proc.kill()`, но не требует `await proc.wait()` после kill, и `session.abort`/закрытие SSE могут сами зависнуть до убийства процесса -> обернуть abort/close в короткие `wait_for` и `finally`, всегда делать `terminate -> wait -> kill -> wait`, затем чистить `_proc`; stdout/stderr daemon надо либо дренировать task-ами, либо redirect в `DEVNULL`, иначе pipe со временем может заблокировать subprocess.

suggestion: metadata `turn_end` не полностью совпадает с `CodexBackend`: в `backend_codex.py:165-180` есть `cached_input_tokens`, а в плане `plan.md:188-200` его нет -> добавить `"cached_input_tokens": cache_read`; для error `turn_end` явно зафиксировать минимальный набор как у Codex error path: `ok=False`, `stop_reason`, `cost_usd=0`, `context_pct=0`, `context_tokens=0`, `max_tokens`, и диагностический tail/error.

suggestion: dedup tool events на `plan.md:140-152` защищает только `tool_use`, но верит, что `completed/error` придут один раз; для SSE `message.part.updated` это хрупко, и быстрый tool может впервые попасться уже в `completed` -> хранить per-callID состояние (`seen_use`, `seen_result`/last terminal status); при terminal без prior use сначала emit `tool_use`, потом один `tool_result`.

suggestion: `session.error` в псевдокоде `plan.md:71` описан как "also triggers turn_end-on-error", но не сказано, что делать с `_chat_task` -> на `session.error` надо break из SSE-turn, дождаться `_chat_task` с коротким timeout или cancel, и гарантированно yield один `turn_end`; иначе можно получить дубль turn_end или зависнуть на task.

suggestion: port allocation `bind(:0) -> close -> opencode serve --port` на `plan.md:101-104` имеет признанный TOCTOU -> не нужен registry, но нужен простой retry: если daemon не поднялся из-за занятого порта/EADDRINUSE, выбрать новый порт и повторить 2-3 раза.

nit: `AgentEvent("thinking", ...)` на `plan.md:132-134` не соответствует текущему `app/events.py`: список известных типов не содержит `thinking` -> либо добавить `thinking` в `events.py` и проверить потребителей, либо для Phase 3 явно мапить reasoning в поддерживаемый тип/metadata; иначе план заявляет parity, которой контракт не описывает.

nit: ссылка "mirror Codex backend_codex.py:199" на `plan.md:81` неточная по смыслу: в `backend_codex.py:199-212` это fallback после выхода subprocess без `turn.completed`, а не обработка заранее упавшего async task -> переформулировать как "синтезировать error turn_end с тем же минимальным metadata-набором".

## Verdict

требует доработки
