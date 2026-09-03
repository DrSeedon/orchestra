# #169 — adversarial Sol self-review of Phase 2 plan

## Status

**external verdict unavailable**

Внешний `codex_review` для Phase 2 не запускался: после Phase 1 действует тот же quota gate, а
оркестратор явно запретил обход, повторный provider turn, Claude fallback и restart. Точная gate
error, полученная на обязательной внешней попытке Phase 1:

```text
weekly_quota_unknown: New Codex worker turn blocked: weekly quota status for gpt-5.6-sol is unavailable or stale (missing or legacy readiness policy). Stop/model change remain available.
```

Ниже — строгий adversarial self-review финального `docs/tasks/169/plan.md` текущей Sol-сессией.
Это **не** внешний Codex verdict, не `APPROVED` от второй модели и не замена недоступному review.

## Проверенный материал

- утверждённые boundaries из задания и `docs/tasks/169/research.md`;
- `app/tm.py`: project creation, task resolution, update/status/prepayment, commit linking;
- `app/routes/tm.py` и `app/mcp_stdio.py`: list/get/update authority propagation;
- `app/manager.py`, `app/routes/sessions.py`, `app/workspace.py`: spawn/switch/merge-next/CAS/link;
- `app/db.py:change_scope` и текущие collision tests;
- все production `ensure_project`, `resolve_task_ref`, `link_commits_to_task` call sites;
- behavioral/mutation matrices и границы cleanup/prod.

## Findings

### R1

`blocking: route-only guards оставили бы optional/global resolve_task_ref доступным direct callers.`

Первый draft требовал authority в `api_get_task`, `api_update_task` и link helper, но сохранял
optional `resolve_task_ref(conn, ref, project_id="")`. Это оставляло тот же dangerous primitive:
globally unique `par` снова мог бы стать mutation/link seam при следующем caller.

**Resolution:** план исправлен: `resolve_task_ref` сам требует project, canonicalizes его
exact-first/casefold-unique и никогда не выполняет global task lookup. Read-only
`get_task_by_par(..., project_id="")` может остаться для import diagnostics, но side-effect APIs
не используют его без authority. M5b/M8 отдельно мутируют task/link границы.

### R2

`blocking: ensure_project возвращает canonical stored id, но import продолжал бы использовать requested spelling.`

`app/tm_import_yougile.py` сейчас игнорирует return `ensure_project()` и передаёт константу
`PROJECT_ID` в `ensure_client`/task writes. После unique-alias reuse это могло дать stale FK или
ошибку вместо безопасного reuse.

**Resolution:** T1 включает import consumer и требует использовать returned stored id во всех
последующих FK. M3 отдельно ломает consumer, чтобы behavioral test доказал контракт.

### R3

`blocking: casefold lookup не должен делать exact legacy id ambiguous.`

Если сначала собрать все casefold matches, exact `Seedon` при существующем `seedon` ошибочно
получит ambiguity, что нарушает главную compatibility boundary.

**Resolution:** exact SELECT — обязательная первая ветка. Casefold применяется только при
отсутствии exact. M1 удаляет exact-first branch; exact legacy test обязан покраснеть.

### R4

`blocking: canonical project id надо использовать для create_task и API response, не только для collision check.`

Иначе single alias мог бы быть правильно найден, но `create_task(conn, requested_id, ...)`
либо упал бы по FK, либо (при legacy exact variant) записал бы не ту authority.

**Resolution:** T1 явно проводит returned stored id через scope comparison, task/client FK и
response. Для совершенно нового id хранится deterministic `requested.casefold()`, display name
сохраняет requested/explicit name; existing ids не переписываются.

### R5

`question: нужен ли DB NOCASE index/trigger для абсолютного запрета case-only INSERT?`

`UNIQUE COLLATE NOCASE` нельзя добавить поверх уже существующих `Seedon`/`seedon` и
`Orchestra`/`orchestra`. SQLite `lower()/NOCASE` также не эквивалентен Python `str.casefold()` для
Unicode, а custom-function trigger добавил бы новый connection-level contract для backup/manual
tools. Production project creation имеет только два caller paths (`api_create_task` и import), оба
идут через `ensure_project` под write transaction.

**Disposition:** не добавлять schema trigger/index в #169. Центральный exact-first helper плюс
`BEGIN IMMEDIATE` на обоих production create paths — минимальный доказуемый platform contract.
Focused source inventory остаётся acceptance check; появление нового direct INSERT caller до
implementation review считается blocking.

### R6

`blocking: prefixed ref validation должна происходить после project canonicalization и до task selection.`

Старый resolver сначала выбирает global project по prefix, поэтому непустой project argument не
является authority. Проверка только в HTTP route не защищает commit helper/direct API.

**Resolution:** core resolver сначала доказывает stored project, затем принимает plain/`TASK-N`
или prefix этого же stored project; любой foreign prefix отклоняется. M6 и M10 проверяют task
mutation и link независимо.

### R7

`blocking: payment finding нельзя формулировать как дефект direct allocation SQL.`

Research доказал, что direct payment уже ограничен client project. Cross-prepayment возникает,
когда status update выбирает wrong same-par task, а затем корректно deduct-ит его DB id.

**Resolution:** T2 не переписывает payment SQL. Behavioral tests разделены: status→prepayment
проверяет bound task id, direct receive проверяет существующий client-project predicate. M7a
ломает status resolution и запускает только payment-focused test; M7b независимо ломает direct
project predicate.

### R8

`blocking: current production merge linking не является воспроизведённым exploit и не требует workspace rewrite.`

Обе merge strategy нормализуют refs к `#N`, а sessions route передаёт worker-scope project.
Переписывание merge builder расширило бы scope и рисковало commit-point semantics.

**Resolution:** T3 меняет только lower-level fail-closed contract, если сигнатура требует, и
добавляет duplicate-project integration/mutation tests. `app/workspace.py`, Git и merge
orchestration не меняются; M9 доказывает, что существующий route argument load-bearing.

### R9

`blocking: scope collision нельзя исправить silent clear/remap task_id.`

Clear теряет association, remap по equal `par` повторяет исходный баг. Полный запрет всех scope
moves сломал бы явный relocation session без task association.

**Resolution:** T4 атомарно rejects только target project collision при непустом stored `task_id`,
до session/bg-job/test-lock UPDATE. Empty-task collision и free-target migration сохраняют старый
contract. M12 убирает ровно guard и доказывает identity drift.

### R10

`blocking: behavioral tests без independent mutants могут зеленеть на fallback markers.`

Один end-to-end assert на title не доказывает payment/link/CAS. План должен отдельно убивать
каждую authority boundary и запускать узкий тест, где foreign row имеет тот же `par`, но
side-effect marker проверяется непосредственно.

**Resolution:** финальная матрица M1–M12 (включая M7a/M7b и отдельные CAS clauses) задаёт один
mutant на один seam, fresh backup/restore и focused red→green evidence. Async merge/switch cases
дополнительно выполняются три раза подряд.

### R11

`suggestion: prefix generator с цифрами не расширять в этот fix.`

Unparseable `SE1` подтверждён research, но не вызывает case-only namespace или wrong-target
selection. Его исправление добавит compatibility decisions про legacy commit refs.

**Disposition:** явно исключено из T1–T4 и остаётся отдельным issue.

## Self-review disposition

После исправления R1–R4 и уточнения R5–R10 план покрывает все утверждённые boundaries четырьмя
vertical tickets:

1. canonical create + exact legacy compatibility;
2. public/MCP get-update-status-prepayment continuity;
3. commit linking + worker scope/CAS preservation;
4. atomic scope-collision rejection.

Unresolved blocking contradiction в тексте плана не найден. Это вывод self-review только;
**external verdict unavailable**.
