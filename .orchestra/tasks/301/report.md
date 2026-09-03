# #301 — visibility-aware dashboard polling

## Что изменено

В `app/static/js/app.js` сетевые периодические обновления переведены на единый coordinator:

- hidden tab и `navigator.onLine === false` останавливают расписание; `visibilitychange`/`online` будят его немедленно;
- одинаковые одновременные вызовы `models`, `orchestrators`, `context`, `tasks` и `jobs` coalesce-ятся по ключу;
- timeout/network/abort ошибки увеличивают задержку экспоненциально до 120 секунд, успешный ответ сбрасывает backoff;
- `/api/sessions` и `/api/stats` сохраняют существующий single-flight, а обновления после возврата видимости проходят немедленно;
- SSE не закрывается при сворачивании вкладки и не заменяется polling; reconnect выполняется только если поток действительно отсутствует.

Время heartbeat оставлено 8 секунд вместо прежних 3: это сохраняет автоматическое снятие состояния после восстановления и не создаёт лишних запросов. Платформа не рестартовалась и не деплоилась.

## Эквивалент 12 минут

Playwright-замер с одним и тем же API-стендом, масштаб времени 100×, окно 7200 мс (эквивалент 720 секунд), статика main против текущей ветки. После стартового кадра вкладка переводится в `hidden`: так измеряется именно заявленная visibility-aware пауза, а не шум стартовых запросов:

```text
#301 equivalent 12m before={'/api/sessions/fe-orch/stream': 128, '/api/sessions': 87, '/api/stats': 87, '/api/models': 4, '/api/sessions/fe-orch/context': 87, '/api/logs/sync': 86, '/api/sessions/fe-orch/logs': 86, '/api/orchestrators': 85} after={'/api/sessions/fe-orch/stream': 86, '/api/models': 2, '/api/logs/sync': 62, '/api/sessions/fe-orch/logs': 61, '/api/sessions': 61, '/api/stats': 61, '/api/orchestrators': 61, '/api/sessions/fe-orch/context': 61}
```

Главный профиль `/api/models`: 4 → 2; `/api/sessions` и связанные обновления также уменьшились: 87 → 61. Ветка не делает запросов после перехода hidden из-за остановки coordinator, тогда как main продолжает фиксированные таймеры.

## Приёмка

- active → hidden → visible → offline → online: `test_dashboard_polling_pauses_hidden_and_resumes_after_visibility_and_online` — зелёный; уже зарегистрированный poller допускает максимум один in-flight tick, новый poller в hidden не стартует;
- смена статуса idle → running после возврата видимости: `test_dashboard_polling_resume_refreshes_status_after_hidden` — зелёный, stale UI не остаётся;
- coalescing двух одновременных вызовов: `runs=1`, оба результата одинаковы;
- `uv run pytest -q tests/test_frontend.py` — **69 passed**;
- `uv run pytest -q tests/test_static_js_globals.py` — **1 passed**;
- `node --check app/static/js/app.js` и `python -m py_compile tests/test_frontend.py` — зелёные.

## Мутации

- visibility: `return !document.hidden && navigator.onLine !== false` → `return true`; focused test красный (`hidden_registered_hits == 11`, ожидался `0`), после точечного отката маркер снова `1`, зелёный повтор — 1 passed;
- coalescing: проверка in-flight key отключена; focused test красный (`runs=2`, ожидался `1`), после точечного отката маркер снова `1`, зелёный повтор — 1 passed.

Оба оракула проверяют поведение, а не наличие строки: мутация действительно меняет наблюдаемый результат.

Review route: Luna review301-luna → CHANGES REQUIRED → targeted Sol escalation.

## Luna follow-up

Luna review301-luna found two blockers. The scheduler now coalesces the complete scheduled
callback (`poller:<key>`) in `_pollSchedule`, so repeated visibility/online wakeups cannot start a
second pending poller call. File refreshes pass `pollKey: 'files'`; HTTP 5xx errors retain the
existing UI fallback while updating the coordinator failure counter and increasing the next delay.

New browser oracle:
`test_dashboard_polling_scheduler_coalesces_wake_and_file_failure_backoff` holds one scheduler
callback pending while dispatching repeated visibility/online events, then forces a file-service
503. It asserts one underlying pending call, a file failure count, delay above the 10-second base,
and that the file-tree UI remains present.

Mutation evidence after the fix:

- scheduler key changed to a fresh `Date.now()` key → focused oracle failed with
  `schedulerCalls301 == 2` instead of `1`; restored marker count `const requestKey = ...` = 1;
- `{pollKey: 'files'}` removed → focused oracle timed out waiting for
  `_pollFailures.get('files') > 0`; restored marker count = 1;
- restored focused polling suite: 5 passed, 64 deselected; static globals: 1 passed.

## Targeted Sol escalation

Sol confirmed the production coordinator fix, but rejected the first oracle as insufficient in three
ways: it checked only that `#file-tree` existed, it covered only HTTP 503 and not the timeout/retry
branch, and it inspected `_pollDelay()` directly instead of observing the scheduler's actual
post-failure timer. The oracle was expanded to seed and preserve visible `ok.txt`, drive the real
`AbortSignal.timeout`/three-attempt path through a hanging fetch, and capture the scheduler's
actual `setTimeout` delay after failure. It also asserts the poller makes exactly one subsequent
call after the pending callback is released.

Sol re-review: **APPROVED**. All three initial oracle blockers and the post-release scheduler
assertion are fixed; no new findings. Artifact: `docs/tasks/301/codex-review-sol.md`, Round 3.

## Reconcile с exact silent-marker semantics (#297)

`_isSilentTurnMarker` и вызов `addChatEntry` не входят в production diff #301. На доступном
`main=b47679c1` exact history oracle #295 и тот же тест на временном дереве `main + diff #301`
проходят (`1 passed`); полный merged прогон дал 68/69, единственный fail был прежний active-window
oracle, а не silent marker. Его окно переведено в hidden после стартового кадра, чтобы не сравнивать
шум запуска. Exact тест повторно: `1 passed`; polling-фокус: `5 passed, 64 deselected`.

## Merge-gate race

На merged-main один раз `wait_for_function(51009)` проходил, но следующий round-trip
возвращал пустой `#chat`: фоновый `refreshSessions` успевал вызвать перерисовку между ожиданием
узла и чтением DOM. Это не изменение exact predicate. Chat helper теперь ждёт готовые
`currentScope`/`orchData`, останавливает только `sessions` poller, ждёт завершения его последнего
refresh и получает ID/курсор одним атомарным `wait_for_function` snapshot. Exact near-match и
telemetry assertions сохранены без ослабления.

Проверка после исправления: три последовательных полных прогона `tests/test_frontend.py` —
`69 passed`, `69 passed`, `69 passed`; static globals — `1 passed`; polling focus — `5 passed,
64 deselected`. Мутации scheduler-key и file `pollKey` обе красные, после отката focused oracle
зелёный; production diff и Sol APPROVED не изменены.
