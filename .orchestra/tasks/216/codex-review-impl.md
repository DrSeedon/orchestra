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

- Attempt 1 (T2) started 2026-08-12: review of the T2 diff (Spark opt-in, lane order, continuation carve-out).

## Round (2026-08-12T07:12:29Z)

Re-review status: FIXED. T1 staging issue is gone/merged.

New findings:

- suggestion: `RoutingPolicyV1.validate_activation` returns immediately for `manifest_default`, so `"spark thresholds require models.spark"` is not enforced in that mode. If the invariant is unconditional, move that check before the mode return. This does not currently cause wrong routing because manifest mode ignores quota blocks.

- suggestion: Add focused tests showing a staying Spark continuation remains blocked by access gating, terminal limit, stale telemetry, and hard-stop threshold. The production ordering is correct, but the current continuation test would stay green if one of those guards later moved below the carve-out.

Design ruling:

- Sol-first lane preference is correct. Emergency mode explicitly admits `reserve_only`, so choosing reserve Sol over normal Spark preserves the stated quality-first policy. Review independence and Claude fallback still operate correctly; latch computation is lane-filtered and unaffected.
- The `staying` carve-out is correct. It cannot bypass access, terminal, freshness, or threshold checks because all execute first. A Sol continuation cannot reach Spark because Spark remains ineligible for `continuation`.
- Removing the duplicate runtime forbidden-class check is sound for production paths: stored and replacement policies both pass through `RoutingPolicyV1.model_validate*`. `model_construct()` could violate this, but no application path uses it.
- Duplicate/order normalization for `eligible_classes` is unnecessary for routing: membership is the only semantic operation. Canonicalization would only reduce policy-document noise.

Sight-verification quote:

> “Spark adds capacity when the Sol pool is burning; it never becomes the cheap default.”

Verdict: APPROVED — no blocking defect found.

> ⚠ Codex usage unaccounted: caller did not provide usage attribution

## T2 round 1 outcome (author note)

Вердикт **APPROVED**, блокирующих находок нет. Обе suggestion приняты и реализованы в этом же
тикете:

1. **`spark thresholds require models.spark` проверялся только в quota-режиме** — `validate_activation`
   выходит раньше при `manifest_default`. Инвариант про согласованность документа, а не про
   активный режим, поэтому проверка поднята выше раннего `return`. Мутация «вернуть проверку под
   ранний return» краснит новый тест.
2. **Carve-out `staying` не должен становиться обходом.** Порядок в коде уже верный (доступ,
   терминальный лимит, свежесть и пороги идут раньше), но тест continuation остался бы зелёным,
   если бы гард однажды переехал ниже. Добавлены четыре случая: `codex_access=off`, терминальный
   лимит бакета, протухшая телеметрия, hard stop по порогу. Мутация «staying обходит hard stop»
   краснит их.

Ревьюер также подтвердил три моих решения по существу: Sol-first порядок полос (в emergency
`reserve_only` допустим, поэтому зарезервированный Sol честно выигрывает у свободного Spark),
корректность carve-out (все гарды исполняются до него) и обоснованность удаления недостижимой
рантайм-проверки (единственный обход — `model_construct()`, которым приложение не пользуется).
Нормализация `eligible_classes` признана ненужной: единственная операция над множеством —
проверка вхождения.

### Зрячесть: подтверждена, но НЕ предъявленной цитатой

Строки «Spark adds capacity when the Sol pool is burning; it never becomes the cheap default»
**нет ни в одном файле** — это пересказ моего комментария, а не дословная цитата. По моему же
критерию такая цитата зрячести не доказывает, и записывать «подтверждено цитатой» нельзя.

Зрячесть тем не менее установлена другим путём: ревьюер назвал ранний `return` в
`validate_activation` и `model_construct()` как единственный обход валидации — обе детали
специфичны для текущего кода и в запросе ревью не упоминались. То есть код прочитан, а
самопроверочная цитата собрана небрежно.
