---
slug: plan-review
topic: "Task #97 OpenCode reliable turn completion plan review"
created: "2026-06-15T06:57:46+02:00"
model: "gpt-5.5"
---

## Summary

Направление правильное: `GET /session/status` как граница хода лучше, чем fire-once SSE `session.idle`, а `prompt_async` убирает класс зависших `POST /message`. Но план в текущем виде еще не гарантирует главный контракт: `events()` всегда заканчивается ровно одним `turn_end` и не оставляет OpenCode-сессию в локальном `running`/`turn_active`. Самый опасный пробел: заявленный `TURN_TIMEOUT` из `session.py` не является backstop для нового polling loop, если backend не yield-ит событий во время вечного `busy/retry`. Вердикт: план рабочий по идее, но требует доработки перед реализацией.

## Findings

`blocking: docs/tasks/97/plan.md:16` — План считает `TURN_TIMEOUT (session.py)` backstop-ом, но в `app/session.py:413-421` timeout проверяется только внутри `async for`, то есть только когда `backend.events()` что-то yield-ит. Новый polling loop может бесконечно видеть `busy`/`retry` и не yield-ить вообще; тогда `_claude_event_loop` никогда не выполнит timeout-проверку, и stuck-running класс останется. -> Добавить hard deadline прямо в `OpenCodeBackend.events()` по `TURN_TIMEOUT`: при истечении yield `_error_turn_end("turn_timeout")`, сбросить `_turn_active`, закрыть SSE, желательно `abort`/disconnect daemon.

`blocking: docs/tasks/97/plan.md:133` — Утверждение “`prompt_async` 404 → raises → status flips IDLE” неверно для текущего `app/session.py:348-365`: статус переводится в `RUNNING` до `await backend.send(message)`, а исключение из `backend.send()` здесь не откатывается в `IDLE` и listener task еще не создан. Это новый путь stuck-running при старом opencode, transient 5xx/timeout или ошибке payload. -> Либо менять `app/session.py` и откатывать статус вокруг `await backend.send(message)`, либо в плане явно запрещать `send()`-исключения после установки RUNNING и переводить их в backend-level recoverable state до старта listener. Практичнее: маленький `try/except` в `session.py` вокруг строки 365.

`blocking: docs/tasks/97/plan.md:86` — После loop план строит `turn_end` через `await self._fetch_last_message()`, но error path описан только для `error_out`. Если `GET /session/{id}/message` упадет, вернет пустой список или не найдет assistant-сообщение после `session.error`/пустого хода, `events()` может выбросить исключение или не сможет построить корректный `turn_end`; `app/session.py:439-464` тогда переведет сессию в `IDLE` без contract-level `turn_end`. -> Финальный fetch должен быть total: `try`, validate, при любой проблеме yield ровно один `_error_turn_end("message_fetch_failed: ...")`.

`blocking: docs/tasks/97/plan.md:88` — Сброс `_turn_active=False` описан “after loop”, но генератор может быть закрыт/отменен во время SSE wait, во время yield-ов или во время `_fetch_last_message()`. Если флаг не сбрасывается в `finally`, следующий `send()` будет получать “turn already in progress” при уже завершенной/отмененной listener task. -> `_turn_active`, `_sse_response` и pending futures должны чиститься в одном `finally`, покрывающем весь `events()` после входа в активный ход.

`blocking: docs/tasks/97/plan.md:78` — “on httpx error return None, caller treats None as connection failure” слишком агрессивно для критического пути: одиночный `ReadTimeout`/локальный transient на status poll завершит локальный ход с error, пока daemon может продолжать выполнять prompt. Это не stuck-running, но это false completion/data loss для streaming/control plane. -> Требовать несколько последовательных poll-failures в коротком окне и/или проверить `self._proc.returncode`; при подтвержденной смерти daemon завершать `_error_turn_end`, при живом daemon retry-ить до backend hard deadline.

`suggestion: docs/tasks/97/plan.md:75` — SSE `session.idle` оставлен как `break (fast path)`, хотя цель плана — не использовать SSE idle как boundary. Даже если событие пришло, безопаснее трактовать его как “poll status now”, а завершать только после `GET /session/status == idle` с теми же guard-ами. -> Заменить fast-path break на immediate status poll; это сохраняет скорость, но держит единственный authoritative boundary.

`suggestion: docs/tasks/97/plan.md:52` — Payload для `prompt_async` в плане отличается от текущего `/message` payload `app/backend_opencode.py:253-257`: сейчас `providerID`/`modelID` лежат top-level, в плане они вложены в `model`. Research говорит “same payload shape as `/message`”, а snippet показывает другое. -> Перед реализацией зафиксировать фактическую OpenAPI-схему и добавить unit-тест на точный JSON body; иначе риск 400 после перевода статуса в RUNNING.

`suggestion: docs/tasks/97/plan.md:94` — План правильно говорит, что `GET /session/{id}/message` содержит cost/tokens, но оставляет ambiguity “`{info, parts}` OR flat AssistantMessage”. Текущий `_turn_end` читает только `msg["info"]` (`app/backend_opencode.py:515-527`), а flat shape даст нулевую стоимость/токены. -> Сделать нормализацию `info = msg.get("info") or msg`, покрыть оба формата тестами, и явно выбирать последнее assistant-сообщение именно текущего хода, если API отдает всю историю.

`question: docs/tasks/97/plan.md:31` — `first SSE part` как guard закрывает только `message.part.updated`; неясно, должны ли `file.edited`, `session.error`, tool-only ход или пустой assistant считаться activity. Иначе быстрые не-text/tool-heavy ходы будут ждать `SUBMIT_GRACE` без необходимости. -> Определить “activity” как любой event с нашим `sessionID`, кроме явно игнорируемого шума, плюс `busy/retry` из status.

`suggestion: docs/tasks/97/plan.md:137` — Тест-стратегия не покрывает самые опасные контракты: send failure after status RUNNING, вечный `busy/retry` без SSE событий, `_fetch_last_message()` failure/empty, cancellation while `events()` is active and `_turn_active` reset. -> Добавить эти unit tests; именно они защищают от повторения stuck-running, а не только happy path busy→idle.

## Verdict

требует доработки
