<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну конечно, ревью-гейт запланировали проверить до коммита, хотя он требует уже закоммиченный diff 🤡

## Summary

План содержит блокирующее противоречие в порядке T1 и недостаточно проверяет заявленные fail-safe/idempotency свойства.

Цитата из `plan.md`: “Perform the selected high-risk review route on the complete T1 diff” (`.orchestra/tasks/506/plan.md:147`).

## Findings

### blocking

**T1 review невозможно выполнить в указанном порядке**  
``.orchestra/tasks/506/plan.md:147-148`

`codex_review(mode='implementation')` вызывает `resolve_implementation_subject()`, который требует чистый committed worktree. План требует выполнить review на полном T1 diff до шага commit, поэтому заявленный порядок гарантированно упрётся в dirty-worktree отказ. Переставьте commit перед implementation review либо явно разделите review незакоммиченной работы и финального pinned diff.

### suggestion

**Замороженный T1-оракул не покрывает часть заявленного fail-safe контракта**  
` `.orchestra/tasks/506/plan.md:121-124`

Тест проверяет большой diff и количество файлов, но не проверяет binary diff, malformed numstat, unresolved ref/измерительную ошибку и повторный вызов с тем же identity. Реализация может пропустить эти ветки или создать второй receipt при retry, оставаясь зелёной. Добавьте независимые RED-кейсы для этих условий.

## Verdict

**Incorrect**

План нельзя исполнять буквально из-за порядка commit/review. После исправления порядка остаётся усилить T1-оракул проверками binary/measurement failure и idempotency.

Иначе это не workflow, а очередь в дверь, которую по плану ещё даже не построили.

## Round (2026-09-05T08:47:24Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну вот, теперь порядок действий хотя бы не пытается пройти сквозь стену коммита 😏

## Round 2

### Re-review status

- Prior blocking order defect: **FIXED**. Step 4 теперь коммитит T1 до `codex_review(mode='implementation')`, а исправления оформляются новыми коммитами с resumed review.
- Prior edge-coverage suggestion: **FIXED**. Добавлен отдельный RED-оракул для binary diff, malformed numstat, unresolved ref/measurement failure и idempotent retry.

### New findings

Нет новых blocking, suggestion или question findings в проверенном scope.

Изменённая строка плана:

> “Commit the complete T1 implementation so `mode='implementation'` has a clean pinned subject; then perform the selected high-risk review route on that committed diff.”

## Verdict

**PASS** — текущий план устраняет оба прежних замечания, а последовательность T1 → commit → live probe → T2 сохраняет prompt-last gate. Файлы не изменялись.

Теперь план выглядит как процесс, а не как инструкция по сборке лестницы после того, как с неё уже упали.
