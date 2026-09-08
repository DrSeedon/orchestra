> **RETRACTED как описание текущего main (08.09.2026, #530).** Ниже — историческое доказательство ветки #504, а не действующий контракт. Утверждения о живых площадках A, необходимости внедрить T1/T2/T3/T5, ожидании T4 и текущей пригодности прежних оракулов отменены коммитом `264daeb75484bbe9f97e53c654180fca11c8a12a`: main уже отделяет управление от прозы, удаляет T4-классификатор и safeguard-fork, использует `provider_limit`, завершение CLI и временный round hint. Исторические результаты тестов остаются результатами своих снимков, не текущего main. Адресная развязка всех десяти площадок и тестов: [дифференциал #530](../530/diff-main-vs-504.md). Исходные байты: `git show bf496f8828e4ae5859ac09fd1a20a864ac9e895b:.orchestra/tasks/504/review-plan.md`.

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Ну да, RED почти рассказывает правду — кроме мест, где сам оракул подсовывает ему текст модели 😏 План требует изменений: T2 не доказывает typed command evidence, а T3 не проверяет оба хранилища.

## Findings (blocking/suggestion/question)

1. **blocking:** T2’s JSONL RED does not prove failure from typed command events. In [`tests/test_model_text_control_flow_504.py:39-59`](tests/test_model_text_control_flow_504.py:39), `all_commands_failed` includes model prose matching the legacy regex, while the first `prose_only` assertion fails before the typed-command assertion is reached. The claimed “independent” typed negative control is therefore unexecuted; use failed `command_execution` events without any matching `agent_message.text`.

2. **blocking:** T2 does not cover both branches of `app/bg_jobs.py:54`. The fixture in [`tests/test_bg_jobs.py:749-777`](tests/test_bg_jobs.py:749-777) places `bwrap:` only in the artifact, while `_blind_review_error()` also scans full process output. The named command can pass while the `output` prose path remains text-controlled, contradicting the T2 AC at [`plan.md:68-69`](.orchestra/tasks/504/plan.md:68).

3. **blocking:** T3’s positive oracle checks only `history`, despite the AC requiring identical producer-identity filtering for both `history` and `new_messages`. [`tests/test_harness_tools.py:300-313`](tests/test_harness_tools.py:300) can pass while model-authored assistant output is still removed from `new_messages`, losing the persisted copy. Add an assertion over both stores.

4. **question:** The T1 AC describes `RateLimitEvent(status="rejected")` at [`plan.md:63`](.orchestra/tasks/504/plan.md:63), but the installed SDK puts `status` on nested `RateLimitInfo`; `RateLimitEvent` accepts `rate_limit_info`, `uuid`, and `session_id`. Should the plan state the exact constructor shape to prevent an invalid oracle?

## Verdict

**NEEDS CHANGES.** T1’s SDK evidence and primary-vs-overage distinction are correct, and the ticket dependency graph is acyclic. T2/T3 need oracle corrections before Phase 3 approval; otherwise green results can still leave prose-driven control or data loss in place.

Пока оракул проверяет только половину шкафа, вторая половина вполне может продолжать жить своей криминальной жизнью.


> **Execution guard failed:** Codex reported that it could not execute workspace commands. The review above is preserved for diagnosis.

## Round (2026-09-05T07:54:44Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Теперь RED действительно разделён по швам, а не по настроению pytest 😏

Prior findings:

- T2 mixed JSONL controls — **FIXED**.
- T2 missing `bg_jobs.py:54` stdout coverage — **FIXED**.
- T3 only checked `history` — **FIXED**.
- T1 SDK constructor wording — **FIXED**.

Exact T2 command exits `1` with four behavioral failures; T3 exits `1` with both stores failing. No import or collection failure observed.

## Findings (blocking/suggestion/question)

1. **blocking:** T2 has no positive typed-command control proving that a completed `command_execution` with `exit_code=0` is accepted. [`plan.md:68-69`](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-text-oracles/.orchestra/tasks/504/plan.md:68>) tests agent prose and failed command events only; the artifact/stdout tests invoke `_run_exec` without JSONL evidence. An implementation that rejects every JSONL input could pass all named RED-derived tests while still rejecting every valid review, contradicting the required producer contract at [`plan.md:34`](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-text-oracles/.orchestra/tasks/504/plan.md:34>).

## Verdict

**NEEDS CHANGES.** All four prior findings are fixed, but T2 still lacks the required positive typed execution oracle. Add a JSONL fixture containing a completed successful `command_execution` and assert the guard accepts it; then the plan is ready for approval.

Без положительного контроля этот гейт проверяет только умение говорить «нет» — как особо принципиальный турникет без входной двери.
