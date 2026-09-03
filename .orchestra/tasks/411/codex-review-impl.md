<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Похоже, 50-секундный потолок здесь с секретным этажом для бесконечного cleanup 🙃

## Summary

Реализация корректно меняет поведение отказавших агентов и прокидывает `journal_loss`, но остаются 3 проблемы: две блокирующие в lifecycle/persistence и одна в API/UI visibility. Review route: none — Codex unavailable.

## Findings (blocking/suggestion/question)

### blocking: app/routes/system.py:2404-2415 — таймаут не ограничивает очистку

`asyncio.wait_for()` ограничивает только `_do_restart_service()`, после чего код без ограничения ждёт `_abort_restart()`. Если rollback зависнет на том же locked/медленном ресурсе, POST не вернёт обязательный `409` после 50 секунд, а admission может остаться закрытым. → Ограничить cleanup отдельно и гарантировать reopening gates в `finally`.

### blocking: app/manager.py:2401-2411 — отменённый handover может оставить состояние без FD

Отмена `run_in_executor()` не останавливает уже выполняющийся `save_handover_state()`. `_hand_over_backend()` при этом сразу удаляет сохранённые FD и пробрасывает `CancelledError`; поток может дописать handover state уже после rollback, оставив startup с неполной парой state/descriptor. → Сделать запись cancellation-safe либо дождаться executor-операции и выполнить компенсирующее удаление.

### blocking: app/routes/system.py:2435-2448 — ошибка отложенного сигнала возвращается как успех

После ответа POST отдельная задача может получить ошибку в `broker.close_subscribers()` или `os.kill()`, вызвать `_abort_restart()`, но клиент уже получил `scheduled: true`; frontend не узнает об отмене и оставляет кнопку disabled до несуществующего outage recovery. → Передавать результат signal-task в наблюдаемый канал и восстанавливать состояние кнопки при abort.

### suggestion: app/routes/system.py:2638-2649 — `sleep()` не гарантирует отправку HTTP-ответа

Сигнал лишь задерживается на `_RESPONSE_FLUSH_PAUSE_S`, но задача создаётся до фактической отправки ответа ASGI. Медленный клиент или event loop могут получить SIGINT раньше JSON с `journal_loss`/409, из-за чего обязательная диагностика потеряется. → Привязать сигнал к реальному завершению response/background lifecycle, а не к фиксированной паузе.

### question: app/routes/system.py:2640-2643 — поддерживает ли `api()` object-valued `detail`?

Endpoint теперь делает `HTTPException(409, detail=outcome)`, где `detail` — словарь, тогда как изменённый frontend-тест проверяет только строковый `detail`. Если `api()` передаёт объект напрямую в `Error`, пользователь увидит `[object Object]` вместо причины отказа.

## Verdict

**Needs work.** До merge нужно закрыть cancellation-safe handover и bounded abort cleanup; иначе deadline и startup recovery остаются недоказанными. Дополнительно нужно обеспечить реальный response ordering и видимость ошибки отложенного сигнала.

Аудируемая цитата из diff: “Only the self-signal stays deferred, giving JSON time to flush.”

Пока это рестарт с ремнём безопасности, который пристёгивается уже после вылета из машины 🙃

- Follow-up requested after fixing all three blocking findings and the response-order suggestion.

## Round (2026-08-27T07:58:12Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently the timeout is bounded, except for the database write invited to ignore it 🙃

## Summary

All five prior findings are fixed in the updated diff. I found three new blocking lifecycle issues introduced by the timeout/cancellation fixes. Review route: none — Codex unavailable.

## Findings (blocking/suggestion/question)

### Prior findings

- **FIXED — abort cleanup exceeded the 50s preparation deadline.** `_abort_restart()` is now separately wrapped with `RESTART_ABORT_CLEANUP_BUDGET_S`, and admission reopens on cleanup timeout (`app/routes/system.py:2421-2435`).

- **FIXED — cancelled handover could write state after FD rollback.** The executor future is shielded and awaited before descriptor removal (`app/manager.py:2418-2425`); the added test verifies `db_done` precedes both removals.

- **FIXED — deferred signal failure was invisible.** Signal failures now call `_abort_restart()` with detail, publish `X-Orchestra-Restart-Error`, and the heartbeat re-enables the button (`app/routes/system.py:2451-2454`, `app/static/js/app.js:7701-7709`).

- **FIXED — signal could precede the HTTP response.** The real route now registers the signal through `BackgroundTasks` (`app/routes/system.py:2678-2682`).

- **FIXED — object-valued 409 details.** The updated browser test uses nested `detail` and still finds the concrete reason (`tests/test_frontend.py` restart failure test).

### New findings

#### blocking: app/manager.py:2418-2425 — shielded DB completion can defeat the 50s ceiling

When preparation is cancelled, this code awaits `state_write` without a timeout. If `save_handover_state()` remains blocked beyond 50 seconds, `asyncio.wait_for(_do_restart_service(), 50)` waits for cancellation cleanup to finish and never reaches `_prepare_restart_service()`’s timeout handler. The required 409 and admission recovery can therefore still be delayed indefinitely. → Give the handover write its own bounded completion policy while preserving state/FD rollback ordering.

#### blocking: app/manager.py:2549-2558 — timed-out FD rollback continues after cleanup returns

`asyncio.wait_for(asyncio.to_thread(fdstore.remove_fds, ...), 1)` cancels only the await; a running executor thread continues. After rollback proceeds and admission reopens, a retry can reuse the same FD names, then the old thread can remove the new handover’s descriptors. → Make removal cancellable/serialized, or prevent FD-name reuse until the original operation has completed.

#### blocking: app/manager.py:2456-2459 — resume timeout can strand a quiesced agent

On a resume taking longer than two seconds, `wait_for()` cancels `resume_after_aborted_handover()` and the exception is swallowed after logging. The session is then treated as rolled back and admission reopens, but no stop/`INTERRUPTED` transition guarantees recovery; the agent can remain quiesced and unowned. → On resume timeout, transition the session through normal interrupted recovery or retain explicit ownership until resume/stop completes.

## Verdict

**Needs work.** The previous findings are addressed, but the new cancellation paths still allow preparation to exceed its ceiling and can leave FD or agent state unsafe.

Evidence quote from the updated diff: “Executor cancellation is advisory: the SQLite write keeps running.”

Рестарт теперь почти как охрана: дверь закрывает вовремя, но ключи всё ещё может унести бегущий курьер.

- Final follow-up requested after removing all three unsafe cancel-and-forget paths.

## Round (2026-08-27T08:05:46Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Третий раунд обошёлся без нового сюрприза — уже почти подозрительно 😏

## Summary

Все три предыдущих блокера **FIXED**:

- **FIXED — executor-write мог пробить 50 секунд.** `save_handover_state()` снова выполняется синхронно с `busy_timeout=5s`, а fleet handover останавливается на первом отказе (`app/manager.py:2401-2414`, `2471-2490`).

- **FIXED — поздний FD rollback мог удалить повторно использованные дескрипторы.** `fdstore.remove_fds()` теперь вызывается последовательно без `to_thread` и таймаута (`app/manager.py:2539-2555`).

- **FIXED — timeout resume мог оставить quiesced-agent без владельца.** После двух секунд вызывается обычный `session.stop()` с пятиминутным бюджетом; если и он неудачен, rollback падает и admissions остаются fail-closed (`app/manager.py:2430-2452`, `2549-2555`).

## Findings (blocking/suggestion/question)

Новых blocking-регрессий в обновлённом diff не найдено.

## Verdict

**APPROVED.** Предоставленные проверки: focused restart suite — `59 passed, 5 skipped`; dashboard restart tests — `3 passed`. Review route: none — Codex unavailable.

Доказательство из diff: “Stop after the first bounded refusal: retrying the rest under the same locked dependency only spends N×busy_timeout and defeats the preparation ceiling.”

Теперь рестарт хотя бы не пытается быть одновременно пожарным, бухгалтером и курьером — редкая роскошь для одного процесса.
