# #416 — `merge_worker` скрывает причину pre-merge отказа

## Вопрос

- **Контекст:** `merge_worker` проводит результат `merge_worktree_to_main()` через
  `normalize_merge_result()` перед сохранением и показом оркестратору.
- **Изменение под проверкой:** гипотеза, что merge ломается из-за checkout целевой ветки,
  уже занятой другим worktree.
- **Baseline:** тот же расходящийся worker-коммит с чистым checkout-владельцем целевой ветки.
- **Решающий outcome:** какая команда Git реально не проходит, какой raw error создаёт workspace,
  что из него показывает нормализатор и меняется ли target ref.

Пользовательские факты об операции, fingerprint, budget и сохранности `3041d70` приняты как
исходные и повторно не проверялись. Для установления причины дополнительно прочитаны только
Orchestra-код и read-only журналы Orchestra; чужой репозиторий не открывался.

## Гипотезы и фальсификаторы

1. **H1 — занятая target-ветка ломает production merge.** Git checkout из worker-worktree
   возвращает `fatal: 'main' is already used by worktree ...`, а Orchestra не находит owner.
   **Фальсификатор:** при той же занятой `main` функция находит checkout-владельца и успешно
   мержит в нём.
2. **H2 — target-worktree был грязным, workspace законно отказал до Git mutation, а
   нормализатор уничтожил конкретную причину.** **Фальсификатор:** target был чистым во время
   отказа либо raw `TARGET_DIRTY` доходит до результата без замены на `NO_COMMITS_MERGED`.
3. **H3 — worker-коммит фактически даёт no-op.** **Фальсификатор:** после удаления единственного
   target WIP тот же worker-коммит меняет target ref и даёт `commits_merged=1`.

## Минимальное воспроизведение

Стенд создан в `/tmp/orchestra-416-stand-qPWTxz` и содержит только два checkout одного scratch
репозитория:

1. основной checkout держит `main` и имеет один untracked `orphan.txt`;
2. linked worktree держит `task-416/worker` с одним новым tracked `worker.txt`;
3. прямой `git checkout main` из worker доказывает Git busy-guard;
4. `merge_worktree_to_main(..., target_branch="main", waive_diff_budget=True)` вызывается сначала
   с грязной целью, затем повторно после `git clean -f -- orphan.txt`.

Измеренный вывод:

```text
TARGET_STATUS=?? orphan.txt
DIRECT_CHECKOUT_RC=128
DIRECT_CHECKOUT=fatal: 'main' is already used by worktree at '/tmp/orchestra-416-stand-qPWTxz/repo'
RAW={"commit_point": "not_reached", "diff_insertions": 1,
     "error": "target working tree is dirty (1 file(s): orphan.txt) — commit or discard first",
     "ok": false, "state": "failed",
     "target_after": "b1f6cf7ad08f543e7bdd242891a554bd20850062",
     "target_before": "b1f6cf7ad08f543e7bdd242891a554bd20850062"}
NORMALIZED={"code": "NO_COMMITS_MERGED",
            "message": "merge produced no new commits",
            "next_action": {"code": "CHECK_WORKER_THEN_NEW_OPERATION",
                            "message": "No commits reached the target branch; verify the worker branch before retrying."}}
CLEAN_CONTROL={"commits_merged": 1, "ok": true, "state": "merged", "target_changed": true}
```

Существующий production-shaped контроль занятой цели:

```text
uv run pytest -q \
  tests/test_workspace.py::TestMergeTarget::test_default_target_is_main \
  tests/test_workspace.py::TestMergeTarget::test_merge_child_into_checked_out_parent_branch
2 passed in 3.13s
```

## Findings

### F1 — H1 опровергнута: занятая ветка не является причиной инцидента

**REFUTED — tier 1, два прямых прогона плюс production source.**

`_branch_worktree_path()` читает `git worktree list --porcelain` и возвращает checkout,
владеющий `refs/heads/<target>`; merge затем выполняется с `cwd` этого checkout. Поэтому прямой
checkout из worker действительно падает с RC 128, но production функция в том же стенде после
удаления target WIP успешно смержила один коммит. Два существующих интеграционных теста также
зелёные [1][2].

### F2 — подтверждённая причина третьей попытки: dirty target-worktree

**CONFIRMED — tier 1, incident log + exact scratch reproduction.**

Между второй и третьей попытками read-only снимок основного checkout показал
`?? docs/tasks/49/` (log id `532074`, `2026-08-29T14:24:11.683425+00:00`). Третья попытка
стартовала в `14:24:17.080704+00:00`; между снимком и вызовом не было мутаций. Workspace после
фиксации `target_before` вызывает `_clean_worktree_error(target_wt, "target")` и отказывает на
любом tracked или untracked WIP до `git merge --squash` [1]. Scratch-стенд воспроизвёл именно
этот raw outcome, а чистый control тем же worker-коммитом прошёл.

Для второй попытки raw причина уже невосстановима: persistent operation хранит только
нормализованный result. Одинаковый outcome и отсутствие мутаций target между попытками делают
тот же dirty-target механизм **LIKELY**, но не повышают его до CONFIRMED.

### F3 — ложный текст создаёт `normalize_merge_result`, а не Git/workspace

**CONFIRMED — tier 1, source + direct before/after measurement.**

Добавленный 28.08.2026 в `43a96ed3` predicate считает no-op по трём полям — непустой
`target_before`, равные snapshots и нулевой `commits_merged` — без проверки, что raw результат
вообще заявлял успех [3][4]. Любой нормальный pre-merge отказ после чтения target ref имеет ровно
эти поля. Поэтому конкретный raw `target working tree is dirty ...` превращается в
`NO_COMMITS_MERGED` и действие `CHECK_WORKER_THEN_NEW_OPERATION`; scratch вывел обе структуры
подряд.

Это также объясняет различие первой попытки без отдельного дефекта: diff budget исполняется до
чтения target ref, поэтому у budget refusal `target_before` остаётся пустым и faulty predicate не
срабатывает. После waiver выполнение доходит до target snapshot, target остаётся неизменным при
следующем pre-merge отказе, и тот же `commits_merged=0` уже запускает разрушительную нормализацию.

Три дополнительных raw controls с equal snapshots показали ту же потерю класса:

```text
[('conflict', 'NO_COMMITS_MERGED'),
 ('head', 'NO_COMMITS_MERGED'),
 ('unknown', 'NO_COMMITS_MERGED')]
```

Комментарий над predicate сам ограничивает инвариант словами `A successful response`, то есть
реализация противоречит собственному контракту [3].

### F4 — безопасная граница фикса

**LIKELY — tier 2, production contracts and counter-example; реализация ещё не написана.**

Нельзя просто удалить zero-commit guard. #413 закрыл другой дефект: противоречивый legacy/resume
result может одновременно заявить `commit_point=target_committed`, `ok=false`, равные snapshots
и ноль коммитов; без guard последующая логика классифицирует Git как `SUCCEEDED` [4][5].

Нужное различение: coercion в `NO_COMMITS_MERGED` применяется только к результату, который
**заявляет success/достигнутый commit point**, но не к well-typed
`ok=false + state=failed + commit_point=not_reached` с конкретной ошибкой. После сохранения raw
ошибки существующий `_classify_failure()` уже выдаёт:

```text
TARGET_DIRTY
CLEAN_TARGET_THEN_NEW_OPERATION
Clean the target worktree, then start a new merge operation.
```

Truth table для Phase 2 при одинаковых непустых snapshots и `commits_merged=0`:

| Raw evidence (в порядке приоритета) | Нормализация |
|---|---|
| `state=conflict` или непустой `conflicts` | сохранить `CONFLICT` и paths |
| `commit_point=unknown` (включая partial/rollback uncertainty) | сохранить `UNKNOWN` quarantine |
| `ok=false`, `state=failed`, `commit_point in {not_reached, rolled_back}` | сохранить raw error/code; dirty → `TARGET_DIRTY`, head drift → `TARGET_HEAD_CHANGED` |
| уже задан `code=NO_COMMITS_MERGED` | сохранить explicit no-op failure |
| после предыдущих исключений есть success claim: `ok=true`, `state=merged` или `commit_point=target_committed` | coercion в `NO_COMMITS_MERGED` |
| иных success claims нет | сохранить исходный failure; равенство snapshots само по себе причину не доказывает |

Так таблица сохраняет как incident message, так и #413: его raw
`ok=false + state=partial + commit_point=target_committed` попадает в success-claim строку, а не
в well-typed pre-merge failure.

Это чинит и диагноз, и действие без ослабления dirty-worktree safety guard и без автоматической
чистки/стеша пользовательского WIP.

## Counter-evidence

- Luna-review #413 требовал ловить contradictory zero-commit result независимо от `ok`, потому
  что `commit_point=target_committed` иначе даёт Git success [5]. Это валидное возражение против
  наивного `and raw.get("ok")`; fix должен учитывать все success claims, а не только один flag.
- Git busy-guard реально существует: прямой checkout дал RC 128. Но это не production failure,
  потому что owner-aware путь дал success control; чинить выбор `merge_cwd` оснований нет.
- Ручной `git merge --squash` может пройти рядом с непересекающимся untracked файлом. Orchestra
  намеренно строже и запрещает merge в любой грязный target; исследование не нашло основания
  снимать этот safety contract.

## Affected files, risks, edge cases

- `app/merge_operations.py::normalize_merge_result` — defect owner; consumer — все 19 проектов,
  replay/resume операций и MCP presentation.
- `app/merge_operations.py::_classify_failure` — уже содержит правильный `TARGET_DIRTY` message
  path; менять его для этого случая не требуется.
- `tests/test_merge_operations.py` — текущий `test_normalize_rejects_zero_commit_noop_even_when_upstream_is_failed`
  защищает важный contradictory post-commit случай, но не имеет нормального failed/not-reached
  control. Нужны оба плеча.
- Возможные regressions: ложный success legacy response; потеря `UNKNOWN/PARTIAL` quarantine;
  повторное превращение конкретных `TARGET_DIRTY`, `TARGET_HEAD_CHANGED`, conflict и identity
  errors в generic no-op; изменение retry action.
- Не трогать `app/workspace.py` owner-selection и dirty guard без нового evidence.

## Review decision gate

- **Artifact/consumers:** `docs/tasks/416/research.md`, `docs/kb/repo-ops.md`; вывод относится к
  `app/merge_operations.py` и общему merge-runtime всех проектов.
- **Author metadata:** Codex runtime, `gpt-5.6-sol`, full-cycle, xhigh (read-only `sessions` row).
- **AC:** причина воспроизводится на минимальном Git-стенде; H1 подтверждена или опровергнута;
  raw и user-visible message связаны одной измеренной цепочкой; counter-regression #413 сохранён.
- **Named checks:** scratch output выше; два focused workspace tests → `2 passed in 3.13s`.
- **Route:** high-risk shared runtime обычно требует Sol, но дополнительный Sol не авторизован;
  один независимый Luna completeness/falsification pass по research.

## Review outcome

Luna: blockers 0, question 1, suggestion 1; verdict `Approve Phase 1 research with follow-up`.
Reviewer подтвердил F1–F3 и отдельно воспроизвёл collapse conflict и `TARGET_HEAD_CHANGED`.
Question о полном predicate закрыт truth table выше; suggestion о snapshot-backed dirty/conflict/
head-change controls переносится в Phase 2 RED oracle. Второй раунд не запускался: blocking findings
нет. Evidence: `docs/tasks/416/review-research.md`, proof-of-read quote присутствует.

## Пробелы

- Raw error второй операции потерян при нормализации; по сохранённой БД восстановить его нельзя.
- Полный `tests/` regression и mutation проверки относятся к Phase 3 и в Phase 1 не запускались.

## Sources

1. `app/workspace.py:798-831, 1413-1480, 1688-1740` — owner selection, dirty guard, raw outcome.
2. `tests/test_workspace.py:1308-1330, 1430-1480, 1530-1575` — checked-out target success и dirty rejection.
3. `app/merge_operations.py:933-989, 1020-1036` — failure classification и faulty no-op coercion.
4. Git commit `43a96ed31200c3f61455fda8cdb4968dfd3792a9` — introduction of predicate and regression test.
5. `docs/tasks/413/codex-review-impl.md:3-8` — counter-evidence for contradictory post-commit raw results.
6. Read-only `/mnt/data/Projects/Python/orchestra/data/orchestra.db`: `logs.id=532074`,
   `merge_operations.operation_id IN ('c6956ef8-65a7-4482-8c76-777692610c89',
   'd8b065d3-49b8-4635-9db4-a1664dd02683')`.
