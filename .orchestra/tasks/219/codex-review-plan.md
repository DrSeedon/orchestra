## Summary

План правильно фиксирует главный результат M4 — дешёвому ребёнку поручается таблица фактов, а гипотеза и соединение остаются у родителя. Но T1 построен на неверной предпосылке об единственной точке пробуждения, а T3 технически маршрутизирует по роли, хотя заявленная граница проходит по форме задания. Красные тесты частично проверяют примеры, но не заявленные инварианты.

Дословная строка из плана:

> **С T2 значение барьера растёт**: таблицы дёшевы, детей становится больше, пробуждений тоже.

## Findings

[suggestion] [docs/tasks/219/plan.md:84] Seam не единственный, поэтому AC-1 недостижим через гейт только в `routes/sessions.py:482`. Помимо HTTP `send_message`, ребёнок будит родителя напрямую из `manager.py`: `_make_idle_callback()` вызывает `self.send()` на строке 1599, а quota-block callback — на строке 1625. Первый путь особенно важен: даже если обычное DONE-сообщение задержать в route, завершение хода породит auto-report и всё равно разбудит родителя. План должен либо поставить барьер ниже — в `Manager.send()` с явным типом/источником доставки, либо перечислить и загейтить все parent-delivery paths. Также нужен AC, доказывающий, что обычное сообщение, auto-report и quota/failure notification проходят через одну политику.

[suggestion] [docs/tasks/219/plan.md:136] Порядок T2 → T3 → T1 противоречит собственной оценке риска. Строки 81–82 прямо говорят, что дешёвые таблицы увеличивают число детей и пробуждений, а строки 73–76 оценивают одно пробуждение дороже нескольких детей. Следовательно, включение T3 до барьера может сознательно создать wake-up storm. Безопасный порядок: T2 → T1 → T3 либо T2 → ограниченный пилот T3 с измеримым потолком пробуждений → обязательный T1 перед широким дефолтом. Формулировка «T1 можно не делать вовсе» требует критерия отмены: максимального числа вееров/детей и измеренного координационного расхода.

[suggestion] [docs/tasks/219/plan.md:55] T3 не реализует заявленную границу «по форме задания». `pipeline.yaml` разрешает модель по статической роли, а в текущем manifest нет отдельной роли сборщика фактов. AC-1 также проверяет именно «роль сбора фактов», то есть закрепляет role-based routing. План должен определить операционный механизм: например, новую узкую роль `fact-collector`, которую родитель обязан выбирать только для задания с явной схемой и счётными определениями, плюс негативный AC, что табличная форма сама по себе не понижает произвольный `full-cycle`. Иначе открытое исследование, ошибочно названное ролью сборщика, автоматически уйдёт на Luna.

[suggestion] [docs/tasks/219/plan.md:108] Красный тест AC-1 доказывает только отсутствие доставки в одном сценарии, но не положительный инвариант «N зарегистрированы, терминальный токен есть у каждого». Он может остаться зелёным при пустом реестре, незапущенном delivery path или молчаливой потере сообщения. Нужны проверки состояния: зарегистрированы N конкретных детей; N−1 `done` не снимают барьер; неизвестный ребёнок не засчитывается; отсутствие записи не эквивалентно terminal; последний terminal снимает барьер ровно один раз. Обязательная мутация — заменить проверку всех терминальных токенов на «нет активных/ожидающих» и убедиться, что тест краснеет.

[suggestion] [docs/tasks/219/plan.md:100] AC-4 описывает три семантических класса, но тестирует только строку «заблокирован». Это не ловит потерю двух остальных классов и не определяет, как сервер отличает их от обычного текста. Классификация свободного текста будет недетерминированной. Нужен явный машинный `message_kind`/enum с обратно совместимым default, параметризованный тест всех трёх bypass-классов и негативный тест для `done`/обычного сообщения. Каждый класс следует прогнать через все реальные пути доставки, включая auto-report и quota-block callback.

[suggestion] [docs/tasks/219/plan.md:115] Совместимость MCP заявлена риском, но отсутствует в acceptance criteria. Поскольку старые `mcp_stdio.py` живут до reconnect, T1 должен иметь красный контрактный тест, что старый payload без новых полей продолжает приниматься и сохраняет текущее поведение, а новый optional payload включает fan/barrier semantics. Сначала должна применяться принимающая сторона, читаемая живым сервером, и только потом — новый producer; новый обязательный аргумент запрещён тестом, а не только текстом плана.

[suggestion] [docs/tasks/219/plan.md:32] AC T2 частично непроверяемы указанным тестом. Якоря собранного prompt проверяют наличие четырёх фраз, но не AC-3 «ровно один владелец-файл»: одинаковая мысль может остаться в двух исходниках и один раз попасть в сборку либо быть перефразирована. Негативный якорь также ловит только одну дословную старую формулировку. Следует разделить acceptance: поведенческий тест собранного prompt и явная проверка owner-модуля/списка подключённых модулей. Требование найти «ту же мысль, сформулированную иначе» не является автоматизируемым AC и должно остаться обязательной ручной проверкой артефакта.

[suggestion] [docs/tasks/219/plan.md:103] T1 расширяет подтверждённый измерениями барьер до файлового манифеста, размера, времени, стоимости, конкатенации и нового MCP tool, хотя для измеренного эффекта достаточно подавить промежуточные пробуждения и один раз доставить статусы с путями. `barrier.md` поддерживает пути вместо тел и серверную механическую сборку, но не доказывает необходимость полноценного persistent fan registry плюс новый публичный tool именно в первой реализации. Разделите минимальный T1 — идентификатор веера, фиксированный состав, terminal states, deadline, один manifest wake-up — и последующее расширение метаданными. Это уменьшит общий runtime/MCP blast radius.

## Verdict

Changes requested. Блокирующих crash/security-дефектов в плане нет, но в текущем виде T1 не перекрывает реальные пути пробуждения, T3 не может соблюдать заявленную границу, а тесты AC-1/AC-4 допускают ложнозелёную реализацию.

## Round (2026-08-12T09:55:29Z)

## Re-review status

- Seam / AC-8: **FIXED**
- AC-4 machine-readable classes: **FIXED**
- AC-1 mutation: **FIXED**
- MCP compatibility / AC-10: **FIXED**
- T2 ownership AC: **FIXED**
- T3 operational boundary: **STILL BROKEN**
- T1 scope creep: **FIXED**
- Ordering T2 → T3 → T1: **STILL BROKEN**

`git diff -- docs/tasks/219/plan.md` is empty; this review therefore covers the current file content rather than an uncommitted patch.

Verbatim current-plan line not present in the request:

> Замеренный эффект даёт подавление промежуточных пробуждений, всё остальное — догадка о полезности.

## Findings

[suggestion] [docs/tasks/219/plan.md:57] **STILL BROKEN:** T3 now says routing is keyed by assignment content, but its Files, AC, and red test still specify role-based routing: “модель по умолчанию для роли”, “с ролью сбора фактов”, and “тест на резолв модели по роли” at lines 57, 60, and 64. An implementation following the executable parts of the ticket would reproduce the rejected role-name boundary. Rewrite all three around one explicit parsed field or structured spawn property. Scanning prose for “column schema” and “no conclusions” is itself brittle unless their representation and parser are specified.

[suggestion] [docs/tasks/219/plan.md:173] **STILL BROKEN:** the exit condition detects the wake-up storm only after T3 has enabled it, and `average children per fan > 3` can hide costly large fans behind many one-child fans. It also has no observation window or definition of which sessions constitute a fan. Use a pre-rollout/pilot gate and a direct wake-cost measure, or at least a per-fan percentile/count such as “any production fan ≥4” over a stated window. Otherwise T1 can remain “optional” while the exact expensive four-child case already occurs.

[suggestion] [docs/tasks/219/plan.md:121] **NEW BUG:** AC-2 requires killed children to emit `killed`, but the inspected auto-report path explicitly skips manually interrupted workers at `app/session_turns.py:266`. Merely gating `fire_auto_report` cannot create that terminal token because this path returns before invoking `on_idle`. The plan needs to name the kill/stop lifecycle producer for `killed` and add a red test beginning with the real interruption path. The same producer-level mapping should be explicit for `timeout`; otherwise the roster may wait until the fan deadline despite already-known terminal outcomes.

## P1 — ACK

The two-gated/N-exempt architecture is correct: do not gate shared `Manager.send()`. The inspected code confirms:

- Explicit child reporting reaches `routes/sessions.py:482`.
- Silent child completion independently reaches `on_idle` through `session_turns.py:256–292`.
- All five inspected `bg_jobs.py` calls deliver operational events to their target session, including FAILED and TIMEOUT; buffering these would be incorrect.

Given implementation at exactly the two child-report seams, AC-9’s FAILED-job and Telegram tests are a sufficient regression guard against accidentally moving the barrier into shared `Manager.send()`. Testing all nine exemptions individually is unnecessary.

I cannot independently certify the exact “nine” count or exclude a tenth path because this round explicitly disallowed opening the other named caller files. Within the supplied eleven-call-site inventory and the three permitted files, there is no counterexample. The ordering hazard I found is not another `manager.send` path; it is the manually interrupted child bypassing terminal-token production before `on_idle`.

## Verdict

Changes requested: P1 is accepted and the principal seam design is now sound. Before implementation, resolve the contradictory T3 contract and name/test the lifecycle source of `killed` terminal tokens. The remaining ordering objection should be handed to the orchestrator explicitly if the chosen rollout order is retained.

## Round 2
