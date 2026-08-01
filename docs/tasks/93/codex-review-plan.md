## Summary

Ну конечно, самая опасная гонка снова живёт между словами «shielded» и «finalize» 🧯 План близок, но содержит один блокирующий разрыв в quarantine и несколько недоопределённых границ. Проверен только `plan.md`; файлы репозитория и тесты не открывались.

## Findings

1. **blocking** — [plan.md:50–52](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:50): при ошибке persistence quarantine существует только в памяти. После рестарта или выгрузки session старая DB-запись может восстановить `needs_switch=false` и прежний `task_id`, разрешив работу на непроверенном Git state. Нужен durable fail-closed marker либо обязательная проверка Git snapshot при загрузке такой session.

2. **suggestion** — [plan.md:110–113](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:110): AC доказывает полный lock scope только для `switch`. Требование «используют один helper» не гарантирует, что `create/merge/remove` удерживают flock непрерывно через все preflight, ref/worktree mutations и rollback. Зафиксируйте scope каждой операции явно и добавьте хотя бы один concurrent-operation barrier test.

3. **suggestion** — [plan.md:151–152](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:151): «после начала finalize» не определяет атомарную точку передачи ownership от compensation к finalize. Требуется явно создать finalize task и выставить ownership без промежуточного `await`, а cancellation test поставить ровно на этой границе, а не только внутри уже начавшегося finalize.

4. **suggestion** — [plan.md:160–163](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:160): после успешного `session.start(persist=False)` cancellation или final DB failure должны закрыть запущенный client/background lifecycle до удаления worktree. Сейчас AC проверяет Git/DB/task cleanup, но не отсутствие живого unpublished backend, который продолжит работать в удалённом cwd.

5. **suggestion** — [plan.md:87–89](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:87): для `SessionManager.send` не задан cancellation contract. Cancellation во время auto-switch/persist или между persist и принятием сообщения освобождает session/lifecycle locks и может потерять fresh delivery при уже изменённом состоянии. Критический участок должен быть shielded до явной точки «message accepted», с ожиданием внутренней операции перед освобождением locks.

6. **suggestion** — [plan.md:186](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:186): `blocked-by: T1` разрешает T4 выполняться до T2/T3, хотя central auto-switch использует project-scoped task contract T2 и пересекается с T3 по `manager.py`, routes и tests. Зафиксируйте строгий порядок `T1 → T2 → T3 → T4` либо укажите `blocked-by: T2, T3`.

7. **suggestion** — [plan.md:129–136](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:129): project-scoped resolution устраняет межпроектную неоднозначность, но план не требует сохранить resolved immutable task identity до post-Git update. Если numeric task удалён и переиспользован во время Git operation, повторный lookup обновит уже другую задачу. Передавайте стабильный DB id/version из prevalidation в условный update.

8. **suggestion** — [plan.md:118–120](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:118), [plan.md:137–138](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:137): T1 первым меняет route DTO для `rollback_failed`, но обязательная проверка текущим MCP parser появляется только в T2. Для independently landable vertical tickets rolling-compatibility test должен входить в T1; иначе промежуточный route contract остаётся непроверенным.

## Verdict

**NEEDS WORK**

Блокирует durable quarantine: после persistence failure план не гарантирует fail-closed поведение через reload/restart. Остальные пункты закрывают реальные cancellation, identity и ticket-ordering разрывы.

Пока это четыре вертикальных тикета, скреплённые одним горизонтальным «авось».

## Round (2026-08-01T07:26:35Z)

## Summary

Ну почти — все восемь дыр залатали, но инструкцию к одной заплатке оставили противоположную 🩹 Все прежние findings исправлены; осталась одна load-bearing внутренняя противоречивость.

## Findings

Статус прежних findings:

1. **FIXED** — durable write-ahead quarantine: [55–64](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:55).
2. **FIXED** — полный flock scope и concurrent barrier: [130–136](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:130).
3. **FIXED** — атомарная передача finalize ownership: [40–42](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:40).
4. **FIXED** — `abort_unpublished()` закрывает backend/tasks: [49–51](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:49).
5. **FIXED** — shielded serialized delivery до message acceptance: [102–106](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:102).
6. **FIXED** — T4 зависит от T1–T3: [222](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:222).
7. **FIXED** — immutable task id + `sync_revision`: [94–97](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:94).
8. **FIXED** — MCP compatibility test перенесён в T1: [125–146](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:125).

Новый load-bearing finding:

- **blocking** — [plan.md:108–112](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:108), [plan.md:141–146](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:141): формулировки «persist/update только при `ok=true`» и «lifecycle/task только при `ok=true`» противоречат обязательной pre-Git quarantine persistence и сохранению quarantine при `rollback_failed` с `ok=false`. Уточните: только task update выполняется при `ok=true`; lifecycle persistence также включает write-ahead quarantine, normal rollback restore и сохранение quarantine при rollback failure.

## Verdict

**NEEDS WORK**

Механика правильная; нужно убрать противоречащие ей два AC, иначе исполнитель может честно реализовать оба взаимоисключающих требования — классика плана, который спорит сам с собой.

## Round (2026-08-01T07:27:34Z)

## Summary

Противоречие наконец перестало спорить само с собой 🥳

## Findings

- **FIXED** — строки [110–112](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:110) и [142–146](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/93/plan.md:142) теперь однозначно разделяют task update и lifecycle persistence.
- Новых findings нет.

## Verdict

**APPROVED**

Теперь контракт один, а не два в одном плаще.
