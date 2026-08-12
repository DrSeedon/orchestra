Spark remains unselectable, but configured Spark telemetry is silently omitted for access-gated task classes, producing a routing-v2 candidate inconsistent with the specified contract.

Review comment:

- [P2] Observe Spark regardless of Codex access mode — /home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/app/runtime_router.py:474-479
  blocking: When `codex_access="review_only"` handles a non-review task, or access is `off`, this branch skips loading `codex_spark`; `_spark_candidate` then returns the access reason without utilization or timestamp. That violates the T1 contract requiring every configured Spark lane to remain `excluded` with `reason="spark_not_eligible"` and real telemetry ([docs/tasks/216/plan.md:242-243](docs/tasks/216/plan.md#L242-L243)), and contradicts the changed-file statement `"Observe the Spark bucket honestly, but never select it."`. Load `codex_spark` whenever `models.spark` is configured and keep access gating from replacing Spark's observation verdict.

> ⚠ Codex usage unaccounted: caller did not provide usage attribution

## Round (2026-08-12T06:59:35Z)

Re-review status: FIXED in the working tree. I accept symmetry with Sol as the coherent contract: access gating owns observation for both Codex lanes, and no concrete consumer requires telemetry from an access-excluded lane.

New blocking defect:

- NEW BUG: the Round 2 fix is not fully staged. `app/runtime_router.py` and `tests/test_runtime_router_spark.py` are `MM`/`AM`, while `docs/tasks/216/plan.md` is unstaged. Committing the index now would omit the revised contract and symmetry tests, retaining the prior inconsistency.

Sight-verification quote from changed code:

> “When telemetry is read it is real and comes from `codex_spark`, never from `codex`.”

Focused verification: 20 passed.

Verdict: STILL BROKEN as a staged change; otherwise approved once the Round 2 working-tree changes are staged.

> ⚠ Codex usage unaccounted: caller did not provide usage attribution

## Round 2 resolution (author note)

Раунд 2 снял единственный содержательный спор: ревьюер принял симметрию с полосой Sol как
верный контракт и подтвердил, что потребителя, которому нужна телеметрия исключённой доступом
полосы, не существует. Семантика не менялась — менялись мой докстринг и AC плана, оба
переоценивали поведение.

Второе замечание раунда 2 было практическим и верным: правки лежали в рабочем дереве, но не в
индексе (`MM`/`AM`, а `plan.md` вовсе не проиндексирован), и коммит взял бы прежнюю версию.
Проиндексировано полностью; проверено прогоном по одному содержимому индекса
(`git stash --keep-index`) — **78 passed**, после чего рабочее дерево восстановлено.

Вердикт записи: **approved once staged**, условие выполнено и проверено. Потолок раундов для кода
(3) не исчерпан: второй раунд закрыл обе находки.

## Infrastructure note

Оба раунда артефакт записался штатно — после хотфикса #217 (`7283e769`). Остаточный след прежней
несовместимости виден в хвосте job'а: `Codex usage unaccounted: caller did not provide usage
attribution` — мой MCP-процесс поднят до #215 и атрибуцию расхода не передаёт. Результат ревью
это больше не уничтожает (ровно та развязка, которую просили в баг-репорте); недоучёт расхода
уйдёт при следующем реконнекте.
