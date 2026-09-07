<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Проверил `plan.md`, `red-evidence.md`, RED-тест на `c36e22c6`, `_codex_cost` и `codex exec --help`.

Механические доказательства сходятся: RED-тест даёт 5 отдельных падений, `cmp` с immutable commit успешен. Однако есть блокирующие проблемы в accounting, failure taxonomy и oracle enforcement.

## Findings (blocking/suggestion/question)

- blocking: `docs/tasks/432/plan.md:37-45` — usage назван cumulative, но одновременно допускается несколько model/tool rounds и суммирование строк `turn_usage`; это может повторно посчитать один и тот же cumulative usage → явно зафиксировать: одна terminal cumulative row на role либо delta между последовательными событиями, и добавить RED/AC на multi-round fixture.

- blocking: `docs/tasks/432/plan.md:39-40`, `docs/tasks/432/acceptance/test_experiment_432.py:120-145, 205-240, 298-320` — pinned price revision фактически не проверяется: тест требует лишь 64-символьный hash и не проверяет его равенство между A/B, соответствие `CODEX_TOKEN_PRICES` или применение к каждой usage row → добавить проверку конкретного revision digest и общего значения для обеих рук/всех пар.

- blocking: `docs/tasks/432/plan.md:69-72` — timeout hidden oracle классифицируется как `model_failure`, хотя timeout самого judge/controller — инфраструктурный `harness_failure`; это нарушает требование не смешивать failure buckets и может исказить denominator → разделить provider/model timeout и oracle/controller timeout с fail-closed классификацией.

- blocking: `docs/tasks/432/plan.md:30-33` — auth упомянут как объект, который wrapper обязан скрыть, но canary проверяет только paths, traversal и result commit; `codex exec --help` подтверждает, что `--ignore-user-config` не отключает auth, а оставляет `CODEX_HOME` для него → добавить явный auth/env-secret canary и описать конкретную границу mount/sandbox, доказывающую, что CLI может аутентифицироваться, а model-generated shell — нет.

- blocking: `docs/tasks/432/plan.md:147-153` и `test_experiment_432.py:162-205` — T3 проверяет только переданное fixture-поле `bundle_bytes`; runner может вывести `120000`, не измерив фактически переданный handoff bundle, и тест останется зелёным → тестировать реальный сериализованный bundle или hash/байтовый размер именно созданного handoff payload.

## Verdict

NEEDS WORK. Дополнительный Codex review недоступен; Sol-вызов явно не авторизован.

Точная цитата из `plan.md`: “Long run запускается только server-side `bg_create(type="run")`, не обычным blocking shell.”

## Review log

- Round 1: `NEEDS WORK`, five blocking findings.
- Round 2 started after plan/test changes. RED oracle refrozen at `fe587b86`; previous
  `c36e22c6` excluded. Changes: one terminal cumulative row per role; exact price digest
  `ea27c8c…cdba3` on every arm; judge timeout=`harness_failure`; explicit auth/env/mount canary;
  actual canonical bundle bytes/hash and main-handoff hash.

## Round (2026-09-01T16:10:47Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Re-review status

- Prior cumulative-usage blocker: FIXED.
- Prior price-revision blocker: FIXED.
- Prior judge-timeout taxonomy blocker: FIXED in the explicit judge rule, but a new contradiction remains below.
- Prior auth/sandbox blocker: FIXED by the documented boundary and canary AC.
- Prior bundle-size/oracle blocker: FIXED; T3 now hashes the actual serialized file.

Mechanical checks: current acceptance file byte-equals `fe587b86`; full RED run remains 5 distinct failures, exit 1. `git diff` itself is empty because the reviewed task files are currently untracked.

## New findings

- blocking: `docs/tasks/432/plan.md:41-44, 78-81` — zero terminal events are classified as `harness_failure`, while the failure taxonomy classifies `missing terminal completion` as `availability_failure`; T2 also requires provider timeout to be availability failure → distinguish provider-side missing completion from parser/controller corruption and make the classification unambiguous.

- blocking: `docs/tasks/432/acceptance/test_experiment_432.py:92-173` — the updated T2 fixture covers intermediate usage plus one terminal event, but has no zero-terminal or multiple-terminal cases; an implementation could accept duplicate terminal events or misclassify a zero-terminal provider failure while all RED tests pass → add fixtures asserting `harness_failure` and no retry/accounting ambiguity for both cases.

## Verdict

NEEDS WORK.

Exact sentence proving current-plan reading: “Canary cost отчётна отдельно и не входит в A/B denominator.”

## Round 3 review log

- Round 2: `NEEDS WORK`; prior five blockers fixed, two new blockers on zero/duplicate terminal
  classification and test coverage.
- Round 3 started after final executable refreeze `db30b40d`: provider timeout/429/transport with
  zero terminal → availability; completed/exit-0 with zero terminal or duplicate terminal →
  harness failure; duplicate cost unaccounted. T2 now exercises success, provider timeout,
  completed-with-zero-terminal and duplicate-terminal fixtures.

## Round (2026-09-01T16:13:12Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Re-review status

- Round-2 terminal-event taxonomy blocker: FIXED. Provider timeout with zero terminals is `availability_failure`; completed-without-terminal and duplicate-terminal cases are explicit `harness_failure` sources.
- Round-2 missing oracle coverage blocker: FIXED. Immutable T2 oracle now executes all four fixtures, including intermediate-plus-one-terminal, zero-terminal, and duplicate-terminal cases.

Checks passed:

- `cmp` with `db30b40d`: exit 0.
- Full RED suite: 5 distinct missing-behavior failures, exit 1.
- `git diff` is empty; reviewed task files are currently untracked.

## New findings

None.

## Verdict

APPROVED.

Exact current-plan sentence: “Long run запускается только server-side `bg_create(type="run")`, не обычным blocking shell.”
