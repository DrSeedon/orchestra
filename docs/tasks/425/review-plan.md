<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Разумеется, RED уже красный — зато теперь понятно, где именно 😏

## Summary

Frozen tests match commits `4dbecb64` and `892ca2a0`; все четыре named commands остаются красными. T1/T2 preserve `before=577 after=577`, а каждый RED останавливается на своём seam. Ticket order T1 → T2 → T3 логичен.

Phase 2 пока не готов к Phase 3: есть два конкретных crash-рискa и несколько непокрытых security/data invariants.

## Findings

### [blocking] Создавать новые schema objects только после legacy migration

`docs/tasks/425/plan.md:44-65` требует новые индексы и trigger, но `app/db.py:481-523` выполняет DDL до `_migrate()` (`app/db.py:745`). На старой БД `portfolio_projects` ещё не содержит `task_namespace_id`; создание индекса до `ALTER TABLE` упадёт с `no such column` и не даст миграции стартовать. То же относится к trigger, который ссылается на новые поля waits.

Correction: сначала добавить колонки в `_migrate()`, затем выполнять backfill, индексы и trigger; fresh DDL должен использовать тот же безопасный порядок.

### [blocking] Описать async-интеграцию `resolve_wait`

План делает `resolve_wait` асинхронным (`docs/tasks/425/plan.md:168-171`), но текущий `_call()` синхронный и не await’ит action (`app/routes/portfolio.py:87-94,219-225`). Простая замена обработчика на `async def` вернёт coroutine в FastAPI и сломается при сериализации.

Correction: явно сделать async route с `await`, либо добавить отдельный async-wrapper, не ломая синхронные handlers.

### [blocking] Зафиксировать отрицательную CSRF-проверку

T2 проверяет только успешный запрос с корректным CSRF (`tests/test_project_roadmap_backend_425.py:359-375`). Отсутствующий или неверный токен не проверяется, а `_portfolio_app()` подключает только router без production middleware. Реализация, полностью пропустившая `require_operator_csrf()`, сможет пройти RED и останется уязвимой: production middleware проверяет cookie, но не CSRF (`app/main.py:539-545`).

Correction: добавить отдельный security probe без изменения frozen RED: missing/invalid CSRF → 403, valid token → 200; agent `{}` должен сохранить старый путь.

### [blocking] Проверить owner-only для source route

T1 проверяет contributor-only запрет для stages, но source меняется только owner’ом (`tests/test_project_roadmap_backend_425.py:192-222,248-265`). Поэтому route с `authorize(..., owner_only=False)` пройдёт тест, хотя contributor сможет переназначить namespace и изменить видимость всего roadmap.

Correction: отдельная проверка contributor → `PUT /source` возвращает 403.

### [blocking] Отвергать неоднозначный normalized scope

План использует `RTRIM(scope, '/')` (`docs/tasks/425/plan.md:72-79,140-142`), но `tm_projects.scope` уникален только в сыром виде (`app/db.py:376-385`). `/project` и `/project/` могут сосуществовать, а текущий scoped lookup берёт произвольный `fetchone()` (`app/portfolio.py:285-291`). Это нарушает требование exact technical project и может привязать неправильный namespace.

Correction: общий resolver должен требовать ровно один normalized match; при нескольких возвращать 409 и использовать тот же resolver в backfill, source binding и assignment.

### [suggestion] Сделать 274/0 migration proof исполняемым

План заявляет live-shaped proof (`docs/tasks/425/plan.md:258-261`), но frozen T1 создаёт свежую БД, вручную bind’ит `primary` и проверяет только четыре synthetic tasks (`tests/test_project_roadmap_backend_425.py:62-65,161-204`). Ошибка backfill или синтез 274 link rows останутся незамеченными.

Нужен отдельный backup-based прогон с точными assertions: `orchestra` → 274 tasks, 0 links до/после, payload = 274, sessions count unchanged, `init_db()` дважды.

### [suggestion] Проверить stale delivery и concurrency

T2 проверяет один successful submit и последовательный retry/unknown (`tests/test_project_roadmap_backend_425.py:394-455`), но не проверяет: submit старой попытки A после создания B, повторный submit B, unrelated delivery, два одновременных одинаковых ответа или crash между reservation и receipt.

Добавить изолированные probes: A не резолвит wait после перехода на B; двойной B увеличивает goal ровно один раз; concurrent POST создаёт один current delivery; recovery сохраняет UUID и frozen target.

### [suggestion] T3 не проверяет размещение задач по stages

Тест проверяет только пять `[data-road-stage]`, один marker и наличие текста (`tests/test_project_roadmap_frontend_425.py:203-218`). Renderer может создать пустые stage frames, сложить все cards в unlabelled segment и всё равно пройти. Active accents и status coding также не проверяются.

Нужны assertions, что `Memory work` находится в Memory, `Decision task` — в Board, unlabelled task — справа, а stages с in-progress имеют active accent.

### [suggestion] 96 задач недостаточно для проверки no-slice

План запрещает hard limit (`docs/tasks/425/plan.md:223-227`), но fixture содержит ровно 96 queue tasks и проверяет только count плюс `Queue task 96` (`tests/test_project_roadmap_frontend_425.py:55,220-241`). Ограничение `slice(0, 100)` или дубликат одной карточки останутся зелёными.

Нужен supplemental case больше возможного лимита и сравнение полного множества task IDs/titles.

### [suggestion] T3 обходит production load и реальный dashboard DOM

Тест создаёт synthetic HTML, вручную вызывает `PortfolioPanel.render()` и не вызывает `PortfolioPanel.load()` (`tests/test_project_roadmap_frontend_425.py:118-189`). Поэтому сломанный polling, реальная интеграция вкладки или несовместимость с production template могут пройти. Проверка 1280/1920 сама по себе есть, но только для synthetic DOM.

Нужен отдельный production-path smoke: загрузка реальной страницы, переключение PROJECTS, вызов load/poll и проверка project-level wait/history/error states.

## Verdict

**CHANGES REQUESTED — не APPROVED.**

Frozen RED корректен и не является причиной отказа. До Phase 3 нужно уточнить порядок migration/trigger, async route integration и закрыть owner/CSRF security probes; live 274/0 и concurrency checks должны быть отдельным обязательным acceptance proof.

Сейчас это не дорога по ярлыкам, а дорога с шлагбаумами, которые забыли проверить.

## Round (2026-08-31T13:25:22Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Раунд два выглядит бодрее: RED всё ещё красный, зато теперь по делу 😏

## Round 2

Uncommitted `git diff` пуст. Round-2 artifacts совпадают с `60178ec3`, план — с `3890b42b`, snapshot не изменён.

Все проверки остаются RED с ожидаемыми seams:

- T1: отсутствуют три roadmap routes, `577→577`;
- T2: отсутствует `WaitResolve.response`, `577→577`;
- route snapshot: отсутствуют три PUT routes;
- live backup: отсутствует `task_namespace_id`, production `577→577`;
- synthetic T3: отсутствует concept-01 road;
- real dashboard smoke: отсутствует real road load path.

Предыдущие blocking findings закрыты:

- migration order — явно зафиксирован в `plan.md:44-53`;
- async route — прямой bypass sync `_call()` в `plan.md:179-185`;
- CSRF — missing/invalid negative checks в `tests/test_project_roadmap_backend_425.py:384-400`;
- owner-only source и normalized-scope ambiguity — проверки в `tests/test_project_roadmap_backend_425.py:200-242`;
- live 274/0, stale delivery, concurrency, placement, no-slice и production load — добавлены в frozen artifacts.

## Findings

### [suggestion] Проверить revision idempotency в backup oracle

`docs/tasks/425/live_backup_oracle.py:56-99` действительно вызывает `init_db()` дважды и проверяет payload/links/sessions, но не сравнивает `portfolio_projects.revision` и другие revision-поля до и после. Миграция, увеличивающая revision при каждом запуске, останется зелёной.

Добавить snapshot соответствующих revision/row values до первого `init_db()` и сравнение после второго.

### [suggestion] Зафиксировать реальное overlap в concurrent T2 probe

`tests/test_project_roadmap_backend_425.py:365-370,529-530` запускает два `TestClient`, но `ThreadPoolExecutor` не гарантирует, что reservation-фазы пересекутся; один запрос может полностью завершиться до старта второго.

Добавить barrier на reservation/accept seam, чтобы тест действительно проверял гонку, а не только последовательный replay.

### [question] Уточнить foreign-link путь для stage assignment

План требует owner-scope resolver (`docs/tasks/425/plan.md:150-162`), но одновременно говорит, что assignment работает с existing explicit link. В текущем T1 foreign task `extra` легально linked (`tests/test_project_roadmap_backend_425.py:244-257`); если тот же owner-scope resolver применить к `task_project="extra"`, owner не сможет назначить этому foreign task label.

Нужно явно определить: existing foreign link разрешается по сохранённому namespace, а owner-scope resolver применяется только к primary source, либо foreign labels намеренно запрещены.

## Verdict

**APPROVED.**

Все round-1 blocking findings закрыты, тесты frozen и Phase 3 editing не требуют. Оставшиеся пункты — non-blocking уточнения oracle/resolver semantics.

> “At 1280–1920 px the file panel keeps its current max width; each project road owns horizontal scroll, so 7 stages do not widen the document/body.”

Теперь шлагбаумы проверены — осталось построить дорогу и не оставить её на бумаге 😏
