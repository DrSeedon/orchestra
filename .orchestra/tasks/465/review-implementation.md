<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну да, Git опять решил, что «неизвестно» — это почти то же самое, что «безопасно» 😏 Дифф проверен строго по `/tmp/465-production.diff`; найдено 4 блокирующих риска, тесты не запускались.

## Summary

Промоушен действительно фиксирует HEAD и запрещает `force`, но содержит fail-open ветки и TOCTOU-окна, способные оставить рассинхрон Git/SQLite или привязать неподходящую задачу.

## Findings (blocking/suggestion/question)

### blocking: [P1] Fail closed when task resolution is unknown

**File:** [app/tm.py:1774](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/app/tm.py:1774) | **Confidence:** 0.99

`task_binding_requires_quarantine()` возвращает `False`, если проект или задача не найдены. Для `needs_switch=True` и непустого `task_id` это разрешает автоматическое переключение без доказательства, что binding завершён; безопасным явно объявлен только `done` + отсутствие владельца. Частичная canonical/shadow-запись или исчезнувшая задача должна вести в quarantine, иначе текущая adhoc-ветка может быть потеряна.

### blocking: [P1] Revalidate idle status and session revision before promotion

**File:** [app/routes/sessions.py:2408](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/app/routes/sessions.py:2408) | **Confidence:** 0.96

Durable-проверка отвергает только `archived`, existing task и `needs_switch`; статус `IDLE` и revision сессии не фиксируются. После внешней проверки другой ход может запустить worker или изменить lifecycle до `git branch -m`, после чего промоушен переименует живую worktree и последующий `transition_lifecycle()` перезапишет уже изменённое состояние.

### blocking: [P1] Recheck reservations in the canonical mutation path

**File:** [app/tm.py:3116](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/app/tm.py:3116) | **Confidence:** 0.94

`require_unreserved` проверяется в SQLite precondition, но canonical-проверка после него повторяет только status и owner. Если reservation появляется между SQLite-проверкой и canonical update, canonical mode всё ещё может привязать зарезервированную задачу; shadow mode способен классифицировать это как partial, но canonical path — нет.

### blocking: [P1] Roll back or quarantine after post-rename verification failure

**File:** [app/workspace.py:2162](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/app/workspace.py:2162) | **Confidence:** 0.98

После успешного `git branch -m` ошибка `inspect_worktree_identity()` или проверки ref возвращает `rollback_failed`, но rollback не выполняется. Вызывающий код немедленно возвращает этот результат на [app/routes/sessions.py:2451](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/app/routes/sessions.py:2451), ещё не изменив lifecycle и не записав quarantine; durable session остаётся на старой adhoc-ветке, тогда как worktree уже на новой.

## Verdict

**Overall Correctness:** ❌ Incorrect | **Confidence:** 0.98

Не одобряю production diff до исправления четырёх рисков выше. Сейчас это переезд, где ветку уже переименовали, а адрес в базе ещё не обновили — зато табличка «ошибка» висит аккуратно.

## Round (2026-09-03T13:21:09Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну да, после ремонта rollback всё ещё может упасть прямо на финальной проверке 😏 Дифф пересмотрен строго по `/tmp/465-production.diff`.

## Summary

Round 1:

- #1 **FIXED** — missing task quarantines; legacy no-project recovery accepted.
- #2 **FIXED** — durable idle/status/branch checks повторяются под lifecycle locks.
- #3 **FIXED** — final legacy CAS повторяет reservation/status/owner/revision; `canonical_applied` превращается в debt и сохраняет quarantine.
- #4 **FIXED** для возвращаемого `promote_worktree_branch(... state="rollback_failed")`.

Остался один blocking-риск.

## Findings (blocking/suggestion/question)

### blocking: [P1] Convert rollback verification exceptions into quarantine results

**File:** [app/workspace.py:2238](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-deadlock/app/workspace.py:2238) | **Confidence:** 0.98

После успешного `git branch -m previous_branch` повторный `inspect_worktree_identity()` вызывается без `try/except`. Если проверка упадёт, исключение выйдет из `to_thread()` до формирования `rollback_failed`; оба вызывающих пути не дойдут до своей quarantine-ветки, а route вернёт 500 уже после изменения Git ref. Нужно превратить эту ошибку в структурированный `rollback_failed` с фактической branch/head и сохранить lifecycle quarantine.

## Verdict

**Overall Correctness:** ❌ Incorrect | **Confidence:** 0.97

Предыдущие четыре замечания закрыты, но rollback всё ещё имеет необработанный post-mutation crash path. Сейчас это чемодан, который уже вернули на место, но акт приёма решил уйти в HTTP 500.

## Round (2026-09-03T13:23:22Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну наконец-то rollback перестал считать исключение нормальным исходом 😏 Обновлённый diff закрывает последний blocker; новых блокирующих проблем не найдено.

## Summary

- Предыдущий rollback blocker — **FIXED**: post-rename inspection нормализует исключение в `rollback_failed`.
- Quarantine теперь выполняется и при неудаче отката после отказа binding.
- Новых findings нет.

## Findings (blocking/suggestion/question)

Нет.

## Verdict

**APPROVED**

Точная строка из обновлённого diff:

> `"error": f"promotion rollback verification failed: {error}",`

Проверка теперь выглядит как нормальный откат, а не как чемодан, который вернули, но расписку потеряли.
