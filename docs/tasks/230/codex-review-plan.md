## Summary

План не готов к реализации: RED-набор проверяет отдельные примитивы, но не доказывает основной контракт — старый supervisor сохраняет FD и состояние хода, новый действительно принимает тот же CLI, продолжает поток событий и не запускает второй процесс. Самые опасные пробелы — T4, shutdown-path и порядок T6.

## Findings

blocking: T1 — `store_fds()` входит в AC, но ни один тест его не вызывает; реализация может оставить текущий `NotImplementedError`, реализовать только `acquire_fds()`, и весь T1 станет зелёным → добавить oracle на один `sendmsg` с точным payload `FDSTORE=1\nFDNAME=...`, `SCM_RIGHTS`, обработку отказа/переполнения store и проверку `LISTEN_PID`, чтобы чужое окружение не принималось за наследство.

blocking: T4 — monkeypatch `app.fdstore.acquire_fds` является реализуемым seam, если `auto_resume_all()` вызывает модульную функцию динамически; проблема не в недостижимости seam, а в слабом oracle: тест вообще не утверждает вызов `backend.adopt()`, передачу FD/`active_turn_id`, запуск event iterator или продолжение хода. Простая ветка «если наследство непустое — выставить RUNNING и не вызвать connect» проходит тест без adoption → подменить `backend.adopt` tracking-double, проверить точные аргументы и последующее событие завершения; отдельно добавить обещанный, но отсутствующий случай «сессия без наследства гасится в idle». Сейчас T4 также не закрывает заявленное на строке 55 завершение второго хода.

blocking: shutdown/T1–T5 — в плане нет тикета и oracle на критический путь передачи владения: перед завершением нужно сохранить оба FD каждой живой сессии, `active_turn_id` и остаток частичной строки, не вызвать обычные `AgentSession.stop()`/`backend.disconnect()`, а затем убедиться, что systemd принял FD. Текущий `lifespan` вызывает `manager.shutdown_all()`, который вызывает `session.stop()`, а тот disconnect’ит/прерывает CLI. Ни T1, ни T4 это не проверяют → добавить end-to-end shutdown/adopt oracle с настоящими pipes и проверкой отсутствия interrupt/terminate/close.

blocking: T6 ordering — `blocked-by: T1, T5` позволяет установить `KillMode=process` и FD retention до T2–T4. Это худшее промежуточное состояние: дети переживут рестарт, новый supervisor не сможет их принять, сбросит DB в idle и может запустить вторые CLI; оставшиеся процессы и новый backend могут конкурировать за поток либо жить сиротами → T6 должен зависеть минимум от T1–T5 и проходить delivery smoke-test до активации. Безопаснее сначала поставить неактивные unit/socket artifacts, а включать `KillMode=process` последним атомарным шагом с rollback.

blocking: F11/T5 — потолок 5 секунд опровергается собственным измеренным примером: единственный показанный успешно дренированный запрос занял 8.08 с. После пяти секунд уже начатый mutating endpoint нельзя превратить в честное «не начинал»; побочный эффект мог состояться, а ответ — потеряться. Поэтому вариант (c) не является fallback после истечения budget → либо нужен idempotency/result ledger, либо restart admission gate: сначала прекратить принимать новые mutating calls, дождаться всех уже принятых без произвольного меньшего лимита, а при невозможности честно отказаться от рестарта. Обосновать «5 с почти всегда хватает» текущие измерения не позволяют.

blocking: T5 — глобальный счётчик HTTP-запросов конфликтует с SSE: dashboard streams могут жить бессрочно, поэтому ноль не наступит никогда; после пяти секунд план всё равно продолжит shutdown. Если SSE исключить, это должно быть явным правилом и тестом. Также нужно определить long-running endpoints и порядок shutdown: сначала закрыть admission, затем дождаться mutating handlers, затем сохранить FD. Текущий oracle подменяет `inflight_request_count` готовым числом и не проверяет middleware, классификацию SSE, запрет новых запросов или порядок; source-inspection на имя функции проходит даже от комментария/недостижимой ветки.

blocking: coverage — перечисленные обязательные изменения не разложены по тикетам и oracle: сохранение `active_turn_id` и остатка буфера в `app/session.py`; восстановление event iterator; fail-closed orphan collector; громкий отказ при переполнении FD store; socket inheritance в реальном `app/main.py`; переключение tools/prompts именно на следующем ходе; безопасная смена CLI на границе хода. T4 с одним status assertion этого не покрывает → каждому контракту нужен ticket либо явное включение в AC с поведенческим тестом.

suggestion: T2/T3 — оба oracle допускают неполные имитации. T2 можно пройти, выставив фиктивные поля `is_alive/session_id`, не подняв JSON-RPC reader и проигнорировав `active_turn_id`; T3 проверяет только одну целую короткую JSON-строку и не проверяет остаток строки, несколько сообщений, EOF, `close/end_input` и интеграцию `ClaudeSDKClient(..., transport=...)` → добавить round-trip с фрагментированным сообщением больше `PIPE_BUF`, terminal event и следующим запросом; для T2 проверить обработку notification/`turn/completed` и отсутствие subprocess через реальный reader seam.

suggestion: T6 oracle — утверждение «ни поведенческой, ни доставочной проверки внутри pytest не существует» неверно. Можно закоммитить шаблоны `orchestra.service`/`orchestra.socket` или install-script и тестировать их через `systemd-analyze verify`; можно также закоммитить integration harness, создающий transient throwaway unit/socket, выполняющий restart под нагрузкой и проверяющий PID ребёнка, FD names и 90/90 ответов. Живой `orchestra.service` для этого трогать не требуется. Ручной вывод в `report.md` хуже воспроизводимого delivery-check.

question: measured claims — формулировки «что теперь известно точно», «риск снят» и «дефект стенда, не механизма» сильнее данных. Research отдельно предупреждает, что model-network wait не измерен, строки больше `PIPE_BUF` могут рваться, реальный startup/backlog не проверен, а завершение второго принятого хода не наблюдалось. Почему непроверенное завершение заранее классифицировано как дефект harness, если именно восстановление буфера/итератора является новой реализацией и текущий T4 его не тестирует?

## Verdict

CHANGES REQUIRED. Есть несколько blocking-пробелов, при которых тесты могут стать зелёными без сохранения агентского хода, а разрешённый порядок выката способен оставить пережившие рестарт CLI без владельца или породить дублирующие процессы.

## Round (2026-08-12T13:58:52Z)

## Round 2

### Re-review status

1. FIXED — T1 now exercises real `SCM_RIGHTS`, exact payload, foreign `LISTEN_PID`, and a distinct failure type.

2. STILL BROKEN — T5 calls `backend.adopt`, but does not deliver the promised post-adoption event through `AgentSession`. Its assertion also permits any fourth argument:

```python
assert adopted == [...] or (
    len(adopted) == 1 and adopted[0][:3] == (...)
)
```

Thus `active_turn_id` can be wrong or discarded. The test can pass with an `auto_resume_all()` that invokes a fake `adopt`, sets `RUNNING`, and never restores the event iterator.

3. STILL BROKEN — T4 verifies FD names and absence of teardown, but not its other acceptance criteria: exact FD-to-name mapping, persisted `active_turn_id`, partial buffer, or handover status. It starts through `auto_resume_all()` without inherited FDs, so the session has already been reset to idle before shutdown. An implementation that stores arbitrary backend fields for every idle session passes without preserving an actual running turn.

4. FIXED — T8 is last and depends on T1–T7 plus T9. The graph is acyclic and no earlier ticket activates `KillMode=process`.

5. STILL BROKEN — 120 seconds is defensible as a safety cutoff derived from the observed sample, and the artificial 8.08-second harness is not evidence about production tool latency. However, “restart is instant” cannot honestly include a possible 120-second drain. More importantly, an application cannot refuse an already-issued `systemctl restart` from inside lifespan: systemd has begun stopping the unit. Returning `False` may inform application code, but cannot cancel that transaction. The gate must run before invoking systemd—such as in the restart endpoint or a preflight command—and direct `systemctl restart` must either be prohibited operationally or guarded externally.

6. STILL BROKEN — SSE exclusion is asserted only by monkeypatching two unrelated counters. No oracle proves middleware classifies an actual SSE request separately, increments a real mutating request, closes admission atomically before counting, or wires the drain into the restart path.

7. STILL BROKEN — the coverage table is complete on paper, but several advertised behaviours remain absent from their ticket oracles: T4 state persistence, T5 event continuation, T7 process cleanup versus merely closing inherited FDs, and T9 prompt reconstruction.

8. STILL BROKEN — T2/T3 are materially stronger, but T9 is still trivially fakeable: `refresh_backend_at_turn_boundary()` can call `connect()` on the same backend, toggle `tools_are_stale`, and pass. The test does not prove disconnect/recreation, invocation from the next real `send()`, or a fresh result from `assemble_prompt()`.

9. FIXED — committed unit templates plus `systemd-analyze verify` are a viable delivery oracle.

10. STILL BROKEN — the updated plan still contains the old overclaim: “это дефект стенда, не механизма, и он закрывается тестом T4 ниже.” T4 no longer checks second-turn completion; the relevant ticket would be T5, whose current test also does not send an event.

### New findings

blocking: T6 — mutating classification has no fail-closed contract → the single checked path, `/api/merge_worker`, is not an actual route shown by the application surface, so a hard-coded special case passes. Classify from authoritative route/tool metadata, default unknown routes to mutating, and add a table-driven oracle covering every registered HTTP route plus a deliberately unknown route. Do not assume GET is read-only or POST is mutating.

blocking: T1 oracle — `server.recvmsg()` has no timeout → an implementation that successfully sends a datagram without `SCM_RIGHTS`, sends to the wrong address, or sends nothing can hang the suite instead of failing. Set a socket timeout before invoking `store_fds()` and turn timeout into an assertion failure.

### Verdict

CHANGES REQUIRED.

The deployment ordering and low-level FD tests are substantially improved, and I agree that the 8.08-second synthetic sleep should not drive the production budget. The remaining blockers are at the central seams: T4/T5 still do not prove turn-state continuation, T6 cannot refuse a restart after systemd has initiated it, and route classification can miss a mutating operation.

Verbatim updated-plan line:

> `Порядок: T1 → T2, T3 → T4 → T5 → T6 → T7 → T9 → **T8 последним** (включение \`KillMode\` только`

## Round (2026-08-12T14:09:31Z)

## Round 3

### Re-review status

1. T1 FD-store oracle — FIXED.

2. T4/T5 state and event continuation — STILL BROKEN. T4 checks only FD names, not their values, so swapping stdin/stdout passes and destroys the agent stream. T5 explicitly accepts any fourth `adopt()` argument and creates no persisted `active_turn_id`; losing it still passes. Require exact pairs and persist `turn-xyz` in the startup fixture.

3. T6 preflight before systemd — NEW BUG. With the real census, `/api/restart` itself is an in-flight mutating request. If `restart_preflight()` closes admission and drains before `restart_server()` returns, it waits on its own request, reaches 120 seconds, and refuses every restart. The endpoint oracle calls `restart_server()` directly, bypassing middleware, so it cannot detect this deadlock. Exclude the initiating restart request from the drain or acquire a restart lease before entering the counted request, and test `/api/restart` through the real ASGI middleware.

4. T6 middleware/SSE — FIXED.

5. T6 route classification — STILL BROKEN. The route-table oracle only asserts that every result is a `bool`; `is_mutating_path = lambda *_: True` passes. That is fail-safe for integrity but defeats “drain only mutating calls,” can make read-only calls block restart, and does not prove route metadata contains an authoritative mutability classification. Assert expected classifications for representative real mutating, read-only, SSE, and deliberately nonstandard routes, plus unknown=true.

6. T7 orphan cleanup — FIXED for the stated known-PID contract.

7. T9 next-turn refresh — STILL BROKEN. Object replacement and prompt rebuilding are now tested, but the test invokes `refresh_backend_at_turn_boundary()` directly. A fake method that works perfectly but is never called by `send()` passes, so tools/prompts need not swap on the next actual turn. Drive the oracle through `session.send(...)`, or assert the real send path invokes the boundary refresh before submitting to the new backend.

8. T8 ordering/delivery — FIXED. The dependency graph is acyclic, and enabling `KillMode=process` last avoids the dangerous mixed deployment. Earlier tickets may retain today’s interrupted-restart behavior, but do not introduce surviving unadoptable children.

9. Overclaiming — FIXED. The updated text now states the second completion was not observed and does not assign blame to the harness as fact.

10. `AttributeError` REDs — FIXED / acceptable. For explicitly planned new symbols, `AttributeError` is legitimate missing behaviour. Stubs would improve diagnostics and protect against spelling the seam incorrectly, but this is nice-to-have, not blocking.

### New findings

blocking: T4 — the oracle permits crossed descriptors → assert the complete mapping:

```python
{
    "agent:handover-1:stdin": (11,),
    "agent:handover-1:stdout": (12,),
}
```

using the backend’s documented directionality.

blocking: T6 — restart preflight can drain its own counted `/api/restart` request forever → add an end-to-end ASGI request oracle proving a successful preflight reaches the systemd scheduling seam without waiting on itself.

blocking: T9 — direct helper invocation does not prove next-turn wiring → initiate a real next `send()` and verify the stale backend is replaced before message submission.

nice-to-have: plan evidence — “120 s is above the observed maximum” is supported only for the measured historical sample, not a future upper bound. Describe it as a provisional operational cutoff; refusal on expiry is the correct safety behavior.

### Verdict

CHANGES REQUIRED. The remaining blocking findings should be handed to the orchestrator after this final review round. The deployment order is now safe, but the oracles still permit crossed agent pipes, a self-deadlocking restart endpoint, and an unwired next-turn refresh.
