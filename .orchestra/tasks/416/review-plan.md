<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Оба RED-командных прогона действительно падают по assertions: T1 — `4 failed, 1 passed`, T2 — на отсутствии пути в raw-сообщении. T2 корректно отделён от T1 и проверяет MCP-текст, cleanup action и сохранность WIP. Решение не добавлять публичный код выглядит обоснованным, но план нельзя принимать без исправления oracle и уточнения нескольких веток truth table.

## Findings (blocking/suggestion/question)

### blocking — Frozen T1 не проверяет сохранение conflict paths и UNKNOWN quarantine

**File:** [test_merge_reason_preservation_416.py:92](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/tests/test_merge_reason_preservation_416.py:92>), [plan.md:24](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/docs/tasks/416/plan.md:24>)

Тест проверяет только code/message/state/commit point/git status. Он не проверяет, что `shared.txt` остаётся в `result["git"]["conflicts"]`, а UNKNOWN-результат действительно quarantine: `outcome_unknown`, `retryable=False` и reconcile-only `next_action`. Реализация может потерять пути конфликта или разрешить retry, при этом команда станет зелёной. Это refutable oracle и блокирует приёмку.

### suggestion — `state=conflict` без списка путей не типизируется как `CONFLICT`

**File:** [merge_operations.py:946](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/app/merge_operations.py:946>), [plan.md:24](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/docs/tasks/416/plan.md:24>)

Truth table считает достаточным `state=conflict`, но `_classify_failure` распознаёт конфликт только по непустому `raw["conflicts"]`. Для `state="conflict", conflicts=[]` normalizer избежит `NO_COMMITS_MERGED`, но выдаст `LEGACY_UPSTREAM_ERROR`, а не `CONFLICT`. Нужно либо учитывать `state` в классификации, либо убрать state-only случай из таблицы и явно зафиксировать поддерживаемую форму.

### question — Не определён приоритет одновременного conflict и UNKNOWN

**File:** [plan.md:22](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/docs/tasks/416/plan.md:22>), [merge_operations.py:1050](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/app/merge_operations.py:1050>)

Payload с `state=conflict`, непустыми `conflicts` и `commit_point=unknown` попадает сразу в две строки таблицы: одна требует `CONFLICT`, другая — UNKNOWN quarantine. Текущий код при этом выбирает conflict для `git.status`, но UNKNOWN для итоговой ошибки. Нужно явно выбрать безопасный приоритет или запретить такую комбинацию контрактом и добавить oracle.

### suggestion — Явный `code=NO_COMMITS_MERGED` может быть перетёрт downstream-ветками

**File:** [plan.md:27](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/docs/tasks/416/plan.md:27>), [merge_operations.py:1144](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/app/merge_operations.py:1144>)

Само решение «не переиспользовать публичный umbrella code» верное, но строка таблицы про существующий `code=NO_COMMITS_MERGED` не определяет допустимую форму raw-результата. При `code=NO_COMMITS_MERGED` вместе с `state=partial` или `ok=true` последующая логика может вернуть `PARTIAL` либо `SUCCEEDED`, обойдя `_classify_failure`. Ограничьте эту строку валидной pre-commit формой или добавьте отдельную нормализацию и тест.

## Verdict

**Incorrect.** RED-прогоны настоящие, T2 спроектирован правильно, а новый публичный код не нужен. Но T1 — недостаточный oracle для двух заявленных гарантий, поэтому план требует доработки до реализации.

Иначе получится очередной #413: успех уверенный, коммитов — ноль 🙃

## Attempt log

- Round 2 requested after accepting the blocking oracle finding and re-freezing in `f472fcc7`.

## Round (2026-08-29T15:31:44Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Пять падений и один зелёный контроль — oracle теперь хотя бы не путает регрессию с setup 🧪

Предыдущие находки закрыты: oracle усилен, `UNKNOWN` precedence зафиксирован, state-only conflict ограничен scope, `NO_COMMITS_MERGED` получил valid-form restriction. T2 по-прежнему корректно отделён от T1 и проверяет raw/MCP-текст и сохранность WIP.

## Findings (blocking/suggestion/question)

### blocking — Добавьте control для success-claims с conflict/UNKNOWN evidence

**File:** [plan.md:24](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/docs/tasks/416/plan.md:24>), [test_merge_reason_preservation_416.py:41](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/tests/test_merge_reason_preservation_416.py:41>)

Все новые conflict/UNKNOWN cases используют `ok=false`, хотя truth table не ограничивает эти строки такой формой. При `ok=true` и non-empty `conflicts` текущая downstream-логика может вернуть `SUCCEEDED`; при `ok=true` и `commit_point=unknown` итоговая ошибка будет `UNKNOWN`, но `git.status` останется `SUCCEEDED`. Добавьте такие contradictory controls либо явно ограничьте допустимую raw-форму и отразите это в таблице. Иначе T1 станет зелёным при нарушении заявленного приоритета evidence.

### suggestion — Уточните обещание `LEGACY_UPSTREAM_ERROR` для state-only conflict

**File:** [plan.md:34](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/docs/tasks/416/plan.md:34>), [merge_operations.py:974](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/app/merge_operations.py:974>)

Для `state=conflict` без `conflicts` `_classify_failure` всё ещё может вернуть `ROLLBACK_FAILED`, `TARGET_DIRTY` или другой message-based code, а не всегда `LEGACY_UPSTREAM_ERROR`. Если требуется именно legacy code, нужен отдельный приоритет; если сохраняется текущая message-классификация, это следует явно написать в scope.

## Verdict

**Not ready — blocking issue remains.** Все четыре предыдущих замечания исправлены или явно выведены за scope, а RED-команды действительно красные по missing behavior. Но T1 пока не защищает новую precedence-логику от contradictory success claims.

## Attempt log — round 3

- Accepted the remaining blocker; added contradictory `ok=true` conflict and UNKNOWN controls,
  re-frozen in `937ce2fd`; `f472fcc7` excluded.

## Round (2026-08-29T15:37:30Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Раунд 2 blocker исправлен для заявленных `ok=true` + conflict/UNKNOWN controls: T1 — `7 failed, 1 passed`, T2 — предметный RED на checkout path, #413 остаётся зелёным. Но oracle всё ещё не полностью покрывает расширенную failure-evidence predicate.

> “When raw says `ok=true` but also carries higher-priority failure evidence, normalize an internal copy to effective `ok=false` while preserving its `error`, `code`, paths and snapshots.”

## Findings (blocking/suggestion/question)

### blocking — Сделайте T1 oracle ортогональным всем формам failure evidence

**File:** [plan.md:25](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/docs/tasks/416/plan.md:25>), [test_merge_reason_preservation_416.py:54](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-busy-branch/tests/test_merge_reason_preservation_416.py:54>)

Новый `ok=true` conflict control одновременно использует `state=conflict`, поэтому реализация, которая учитывает только state, но игнорирует `conflicts`, пройдёт тест. Также нет frozen cases для `state=merged` + non-empty conflicts, state-only conflict, который по плану всё равно нельзя коэрцировать, и `state=failed`/non-NO named code с `ok=true`. Такая реализация может пройти все 7 cases и #413, но вернуть `NO_COMMITS_MERGED` или `SUCCEEDED` для обещанных failure evidence. Добавьте ортогональные controls либо сузьте truth table.

## Verdict

**STILL BROKEN — not ready.** Предыдущий конкретный blocker закрыт, T2 и production scope выстроены корректно, новый public code не требуется. Но frozen oracle остаётся refutable относительно расширенной таблицы, а это блокирует реализацию по собственному decision gate.

Иначе семь лампочек докажут проблему, а восьмая снова назовёт отсутствие merge успехом 🙃
