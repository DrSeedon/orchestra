## Summary

Исследование убедительно доказывает физическую возможность FD handover и правильно отделяет Claude от первого релиза. Но production-вывод пока не закрывает invariant «ни одного прерванного или задублированного хода»: процедура первой активации имеет гонку admission, а exactly-once перенос Grok не доказан на критической границе записи prompt.

## Findings

1. **blocking:** `docs/tasks/237/research.md:269-274` — первая активация предлагает сначала дождаться `idle`, а затем закрыть admission. Между проверкой idle и закрытием admission может начаться новый внешний, agent→agent или auto-report ход; рестарт его оборвёт. Это противоречит доказанной в `docs/tasks/220/report.md:46` атомарной последовательности. Процедура должна сначала вызвать глобальный `begin_drain()`, затем дождаться устойчивого `is_busy == false` для всех сессий, повторно проверить это непосредственно перед сигналом и только после этого рестартовать.

2. **blocking:** `docs/tasks/237/research.md:135-145,199-203` — «перенос ровно одного активного `session/prompt`» основан на одном stand-only прогоне и не доказывает exactly-once на границе записи. В production `send()` увеличивает `_active_prompts`, затем запускает отдельную task; `_request()` регистрирует request ID и выполняет `write()+drain()`. Рестарт возможен до записи, во время неё либо после полной записи, но до получения response. Synthetic turn identity не доказывает, был ли prompt принят Grok, и не задаёт связь с настоящими `request_id`/`promptId`. До включения Grok нужны fault-injection oracle для всех трёх границ и доказательство: один prompt side effect, ровно один `turn_end`, отсутствие вечного synthetic active turn. Иначе Grok следует исключить из первого поезда, а не только из пользовательского обещания из-за MCP identity.

3. **blocking:** `docs/tasks/237/research.md:27-29,48-51,235-239` — Codex run9 покрывает один фиксированный момент рестарта, тогда как документ признаёт непроверенные разрывы JSONL. Это недостаточно для rollout-инварианта zero loss: `quiesce_for_handover()` отдельно переносит parsed queue и приватный `_buffer`, то есть минимум два самостоятельных race seam. Acceptance должна явно включать рестарт:

   - на частичном JSONL-кадре;
   - после парсинга terminal event, но до потребления очередью;
   - при байтах одновременно в `_buffer` и kernel pipe;
   - через два последовательных поколения.

   Для каждого необходимы точные sequence/count assertions по входу, tool events и terminal event. Общего требования «два поколения, точный файл, terminal event» недостаточно, поскольку оно может пройти при потере промежуточного события.

4. **suggestion:** `docs/tasks/237/research.md:37,170,174-178` — H3 корректно подтверждает только транспортную осуществимость parent-owned pipes. Зонд не измеряет ownership при handover, systemd duplication, rollback после частично сохранённой пары, teardown и повторное подключение. Формулировку «рекомендация первого поезда» стоит обозначить как prototype inference до полного transient-unit E2E. Сам документ это частично признаёт, но итог звучит сильнее доказательства.

5. **suggestion:** `docs/tasks/237/research.md:180-184` — bounded drain назван safety fallback, хотя при deadline 900 секунд он режет все ходы дольше 15 минут. По данным `docs/tasks/220/research.md` только 79.8% исторически завершившихся ходов укладывались в 15 минут; следовательно, не менее 20.2% этой уже смещённой выборки были бы оборваны, не считая зависших и убитых ходов. Это operational fallback, но не safety fallback относительно заявленного zero-interruption invariant. Нужна явная маркировка и число `cut_turns` как rollout blocker.

6. **suggestion:** `docs/tasks/237/research.md:119-122,204-207,272-276` — зависимость от #258 названа, но acceptance сформулирован только для stale/reused PID oracle. Первый rollout также должен доказать, что ни один путь сигнализации не обходит `(runtime, starttime, pidfd)`. Текущий `manager.terminate_orphan_process()` всё ещё вызывает `os.kill(pid, SIGTERM)` только по PID. Перед активацией нужен отрицательный тест именно через production orphan-sweep path, а не только тест нового примитива.

7. **question:** `docs/tasks/237/research.md:160-163,171` — session-host для Claude является разумным направлением, но run4 доказывает лишь возможность продолжить поток через private `Query`. Какие acceptance criteria сделают host «надёжной границей»? Минимально нужны durable correlation входов и terminal events, replay/dedup после смерти HTTP-супервизора, host identity/upgrade protocol, orphan cleanup и доказательство следующего хода с новым MCP/prompt. Пока это архитектурная гипотеза, не подтверждённое решение.

## Verdict

**NEEDS WORK.** Физическая feasibility доказана, Claude обоснованно вынесен отдельно, а ограничения drain описаны честно. Однако первый rollout пока заблокирован гонкой в процедуре активации и отсутствием exactly-once доказательства для Grok и cut-point coverage для Codex. Production restart во время исследования не выполнялся.

## Round (2026-08-13T08:27:44Z)

## Re-review status

Note: `git diff -- docs/tasks/237/research.md` returned empty, so I reviewed the current file contents.

1. **FIXED** — activation closes both admission gates before waiting, rechecks `is_busy`, and identifies the current 0.5-second ordering as a rollout blocker.

2. **FIXED** — Grok is excluded from the first train; all three write-boundary states and exactly-once assertions are explicit.

3. **FIXED** — Codex acceptance covers partial frame, parsed terminal queue, simultaneous userspace/kernel buffering, and two generations with sequence/count assertions.

4. **FIXED** — parent-owned FD is consistently presented as prototype inference in the comparison and recommendation.

5. **STILL BROKEN** — the main comparison correctly calls drain an “operational fallback, not safety,” but two stale claims contradict it:

   - `research.md:40`: “остаётся safety fallback”
   - `research.md:300`: “fail-closed fallback”

   With a 900-second deadline that may cut ≥20.2% of the measured completed-turn sample, neither label is compatible with the zero-interruption invariant. Both should say `operational fallback`.

6. **FIXED** — #258 now requires the complete production orphan-sweep path and proof that no raw-PID signaling bypass remains.

7. **FIXED** — Claude session-host is explicitly an architectural hypothesis with adequate future acceptance criteria.

Exact artifact quote: “До этих проверок слово «надёжный» к host не применяется.”

## New findings

**blocking:** `research.md:214-219,250-258,285-286` — closing mutating HTTP admission prevents new handlers, but the pre-signal procedure waits only for session `is_busy`. The document separately acknowledges that an already in-flight mutating MCP HTTP handler must finish, while current shutdown drains it only after the signal. That can still interrupt a mutating operation during the first activation. Add a positive pre-signal condition that all admitted mutating HTTP handlers have completed; timeout or nonzero in-flight count must abort the restart rather than proceed.

## Verdict

**NEEDS WORK.** Prior blockers for agent turns, Grok, Codex, #258, and Claude are resolved. Final approval is blocked by the missing pre-signal drain of already-admitted mutating HTTP handlers. The stale “safety/fail-closed fallback” wording is a non-blocking but material contradiction.
