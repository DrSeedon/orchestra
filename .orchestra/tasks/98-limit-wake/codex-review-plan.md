😏 Таймер на `0.1` секунды, конечно, славится терпением к гонкам. План правильно фиксирует Anthropic-инвариант, но до реализации нужно закрыть три блокирующих разрыва: freshness-контракт, состояние мгновенного запуска и конкурентную замену таймеров.

## Summary

`current_provider_usage(provider, force_refresh=True)` пригоден как источник только для запрошенного провайдера: он гарантирует свежесть через исключение, но не возвращает признак ошибки/устаревания. Основная readiness-логика сформулирована верно, однако response/status и replace-семантика пока не могут гарантировать заявленный контракт.

Проверены только перечисленные файлы. Тесты не запускались, изменений нет.

## Findings

1. **blocking: Передавайте freshness/error в единый readiness helper**

[План](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/plan.md:41) требует, чтобы helper классифицировал `stale/fetch failed`, но нормализованный snapshot таких данных не содержит. При обязательном fresh-fetch [`current_provider_usage()`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/routes/system.py:869) выбрасывает исключение для запрошенного провайдера, а не возвращает его helper-у. Кроме того, функция возвращает все провайдеры, хотя свежесть гарантирована только для requested provider; объединение полных ответов нескольких вызовов может перезаписать ранее свежие данные кешированным fallback другого вызова. Зафиксируйте контракт: извлекать только `snapshot[provider]`, ловить fetch-error и передавать helper-у явный provider-scoped envelope с состоянием freshness/error.

2. **blocking: Определите авторитетный источник POST/status для мгновенных jobs**

[План](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/plan.md:77) запускает доступный provider через `delay=0.1`, но [`wake_status()`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/limit_wake.py:229) читает только активные jobs, а [`_analyticsScheduleWake()`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/static/js/analytics.js:228) выбрасывает top-level plan и отображает только `result.state`. Job может завершиться до построения `state`, поэтому имена и `available_now` исчезнут из ответа; manual/unavailable решения вообще не сохраняются и после reload не могут быть точно восстановлены. Нужно либо сделать POST decision snapshot авторитетным для feedback, либо явно спроектировать сохранение/recomputation статуса; текущий запрет на schema change оставляет только первый простой вариант, но тогда AC для последующего GET/status надо скорректировать.

3. **blocking: Сериализуйте весь цикл refresh → replace/cancel**

В [алгоритме scheduling](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/plan.md:70) нет защиты от двух одновременных POST. Пока первый запрос ждёт другие provider-fetches, второй может создать более актуальный immediate timer, после чего первый заменит его решением из более раннего snapshot либо удалит своим cancellation sweep. Для текущего single-process сервиса достаточно одного `asyncio.Lock` вокруг полного цикла загрузки кандидатов, refresh, create/replace и cancel; без этого replace-семантика недетерминирована.

4. **suggestion: Разведите Anthropic и текущую reset-семантику Codex/Grok**

Общее правило [«every exhausted window has a valid future reset»](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/plan.md:53) строже заявленного сохранения поведения Codex/Grok. Текущий [`build_wake_plan()`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/limit_wake.py:146) игнорирует exhausted-окна без будущего reset и планирует по последнему валидному. Укажите provider-specific правило и добавьте non-Anthropic тест с двумя exhausted-окнами, одно из которых не имеет валидного reset.

5. **suggestion: Не называйте сохранённый таймер “unavailable/not scheduled”**

[Пункт о сохранении таймера](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/plan.md:81) противоречит сообщению `unavailable: who was not scheduled`: после fetch failure старый cohort всё ещё запланирован. Отмечайте такой результат как `scheduled` с `preserved=true`/`existing_timer` и отдельным предупреждением о неудачном refresh либо вводите отдельный outcome; также покажите различие между старым job cohort и новыми кандидатами.

6. **suggestion: Добавьте тест, запрещающий extra-полям авторизовать wake**

Тест №2 в [TDD-протоколе](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/plan.md:167) проверяет, что заблокированное extra-поле не запрещает открытый base, но не ловит обратную ошибку. Нужны exhausted и partial base snapshots с максимально разрешающими extra-полями: результат обязан остаться `reset`/`unavailable`, а pre-send — ничего не отправить. Мутация `extra clear → available` должна ломать эти тесты.

7. **suggestion: Сделайте replace-гарантии конкретными AC**

Список тестов не проверяет три наиболее рискованных обещания плана: fresh-fetch failure сохраняет тот же job/config/trigger, успешное отсутствие timed path удаляет старый timer, а immediate job остаётся видимым в POST даже при завершении до формирования ответа. Добавьте эти сценарии в T1/T2 вместе с конкурентными POST; общая формулировка «fetch-failed fail-closed» сохранность таймера не доказывает.

8. **suggestion: Tickets сейчас последовательные, но не vertical**

[T1](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/plan.md:192) является backend-срезом, а [T2](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/plan.md:209) добавляет response/UI и повторно меняет `limit_wake.py`. Если нужны именно vertical tickets, разделите по пользовательским исходам — например, schedule-now/later end-to-end и failure/preserved/empty feedback end-to-end. Иначе честнее назвать их последовательными фазами реализации.

## Verdict

❌ **Needs revision before implementation.** Anthropic readiness и отсутствие watcher спроектированы правильно, но freshness, immediate feedback и конкурентный replace пока не имеют безопасного однозначного пути реализации. Сначала зафиксируйте эти контракты и тесты — иначе кнопка получится как два человека у одного будильника: один уже поставил, второй «аккуратно» переставил назад.

## Round (2026-07-28T12:54:14Z)

😏 Почти одобрено — один старый таймер всё ещё притворяется, что знает новый turn.

## Re-review status

1. **FIXED** — provider-scoped freshness envelope.
2. **PARTIAL** — POST snapshot исправлен, но T2 всё ещё обещает неперсистентные manual/unavailable данные через `status`.
3. **FIXED** — полный scheduling cycle сериализован.
4. **FIXED** — Anthropic и Codex/Grok semantics разделены.
5. **PARTIAL** — preserved coverage не определён через `limit_turn_id`.
6. **FIXED** — extra-поля защищены тестами и mutation.
7. **FIXED** — race/replace/immediate AC конкретизированы.
8. **FIXED** — tickets теперь vertical.

## New findings

- **BLOCKING:** preserved job должен покрывать кандидата только при совпадении `(agent_id, limit_turn_id)`. Тот же агент с новым limited turn будет пропущен текущим turn-id guard, хотя план может ошибочно показать его покрытым.
- **SUGGESTION:** разделить T2 AC на authoritative POST decision и ограниченный active-job `wake_status()`.
- **SUGGESTION:** уточнить, что известного reset одного Anthropic-окна достаточно лишь при наличии будущих reset у остальных exhausted required windows.

## Verdict

**CHANGES REQUESTED.** Текущие структуры bg manager позволяют реализовать всё без schema change, но turn-specific preserved coverage остаётся блокером.

Round 2 добавлен в [plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/plan.md:331). Файл новый/untracked, поэтому обычный `git diff` был пуст; проверено его текущее полное содержимое. Тесты не запускались.

Старый будильник можно сохранить, но записку на нём надо сверять целиком, а не только имя владельца.

## Round (2026-07-28T12:57:21Z)

😏 Наконец старый таймер сверяет и агента, и конкретный turn. Все восемь предыдущих замечаний исправлены; новых correctness gaps нет.

## Summary

1. **FIXED** — provider-scoped freshness envelope.
2. **FIXED** — POST и `wake_status()` имеют раздельные контракты.
3. **FIXED** — scheduling transaction сериализован.
4. **FIXED** — Anthropic и Codex/Grok reset semantics разделены.
5. **FIXED** — preserved coverage использует `(id, limit_turn_id)` и имеет regression.
6. **FIXED** — extra-поля не могут авторизовать wake.
7. **FIXED** — race/replace/immediate сценарии закреплены AC и тестами.
8. **FIXED** — tickets вертикальные.

## Findings

Новых blocking, suggestion или question findings нет.

## Verdict

**APPROVED.**

Проверен только [plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/plan.md). Файлы не изменялись, тесты не запускались.

Будильник теперь будит нужную смену, а не любого с подходящим бейджиком.
