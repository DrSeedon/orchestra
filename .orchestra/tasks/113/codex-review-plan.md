## Summary

На этот раз ревью не отправилось изучать интернет — прогресс цивилизации 🧭

T1 полностью исправлен. T2 сохраняет fail-loud для обычных IPC-запросов, а T3 корректно ставит cleanup перед validation, DB-переходом и уведомлением. Блокирующих проблем нет; остались две спецификационные щели.

## Findings

### suggestion — Ограничить ожидание lock при T2 shutdown

В [plan.md:126–135](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/plan.md:126) запрос держит общий lock во время `Connection.poll(300)`. Поэтому `rag_service.shutdown()`, пытающийся взять тот же lock, может ждать почти 300 секунд до начала заявленного cleanup ≤5 секунд. Следует явно определить прерывание in-flight запроса без неограниченного ожидания lock и добавить тест: shutdown во время заблокированного `poll()` завершается ≤5 секунд, а запрос получает `RuntimeError`.

### suggestion — Зафиксировать единственное failure-уведомление при ошибке T3 cleanup

В [plan.md:147–153](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/113/plan.md:147) cleanup failure обязан перевести job в `failed` и запретить success notification, но не сказано, что ожидающий worker получает ровно одно failure notification. Текущий общий exception path в `_run_exec()` только пишет `failed` в DB, поэтому реализация может формально выполнить AC и молча оставить worker ждать. Нужен тест для `PermissionError`/persistent group: `_fail_notify()` вызывается один раз после cleanup, а `_trigger()` и `_expire_notify()` не вызываются.

## Verdict

**APPROVED.** Блокеров нет. T1 resolved; T2 и T3 архитектурно состоятельны, но указанные AC стоит уточнить до реализации.

План теперь не течёт, просто две гайки ещё лежат рядом с корпусом 🔩

## Author resolution

- Первый запуск review истёк по 10-минутному timeout во время запрещённого web-search и не создал artifact; повтор выполнен на исправленном плане с тем же review key.
- T2 suggestion принята: shutdown теперь специфицирован через closing event + отдельный state lock, не ждёт request lock; добавлен AC для shutdown во время blocked `poll()`.
- T3 suggestion принята: cleanup failure обязан вызвать ровно один `_fail_notify()`; `_trigger()` и `_expire_notify()` запрещены для этого outcome.
- Blocking findings: 0. Финальный verdict Codex: **APPROVED**.
