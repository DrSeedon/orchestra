# Задача #90 — implementation report

## T1 — Persisted base-branch lifecycle contract

Статус: **DONE**, ожидает merge Orchestra-orchestrator.

### Что изменено

- SQLite:
  - additive `sessions.base_branch TEXT DEFAULT ''`;
  - additive `sessions.needs_switch INTEGER DEFAULT 0`;
  - единый `update_session_lifecycle()` для loaded/detached rows;
  - старый explicit INSERT не обязан знать о новых колонках.
- Spawn:
  - explicit base имеет приоритет;
  - `strategy=parent` использует фактическую ветку родителя;
  - `strategy=main` использует symbolic remote HEAD либо единственную local
    `main`/`master`;
  - текущий checkout не участвует в определении mainline;
  - неоднозначность падает до Git mutation.
- Session state:
  - `branch` хранит фактическую checkout-ветку;
  - `base_branch` хранит merge/switch/WIP/kill target;
  - `needs_switch` переживает persistence/reload.
- Lifecycle routes/MCP:
  - пустые defaults merge, switch, auto-switch, WIP и kill разрешаются через persisted
    base;
  - merge сохраняет actual worker branch и target base для loaded/detached session;
  - explicit merge target становится новым persisted base.

### Файлы

- Runtime: `app/db.py`, `app/session.py`, `app/manager.py`, `app/workspace.py`,
  `app/routes/sessions.py`, `app/mcp_stdio.py`.
- Tests: `tests/test_db.py`, `tests/test_session.py`, `tests/test_manager.py`,
  `tests/test_workspace.py`, `tests/test_api.py`, `tests/test_mcp_stdio.py`.
- Plan/review: `docs/tasks/90/plan.md`, `docs/tasks/90/codex-review-plan.md`,
  `docs/tasks/90/codex-review-t1.md`.

### Проверка

- Targeted suite: `417 passed in 73.67s`.
- Full suite: `1020 passed in 96.15s`; raw log: `/tmp/pytest-90-t1.log`.
- Read-only live validation:
  - 80 non-archived sessions;
  - 24 unique canonical repositories from union `sessions.scope` +
    `worktree_path` Git common-dir;
  - 24/24 base branches resolved, 0 ambiguous/failing repositories;
  - выборка включала `main`, `master` и remote-HEAD custom `develop`.
- `git diff --check`: clean.

### Review

- Plan review: `APPROVED` after two findings were fixed.
- Implementation Codex review: unavailable after three infrastructure timeouts; no
  content verdict was produced. The honest record and adversarial self-review are in
  `docs/tasks/90/codex-review-t1.md`.
- Self-review closed a persistence ordering race: in-memory lifecycle fields are updated
  before the awaited DB write, so a concurrent generic persist cannot replay old fields.

### Compatibility / intentional behavior change

- Existing rows receive empty/non-destructive defaults.
- Repositories whose mainline cannot be proven now require explicit `base_branch`;
  current HEAD is never guessed.
- An old server using its old explicit INSERT/UPSERT column list continues to work on
  the additive schema.

### Не выполнено в T1

- T2/T3 partial Git states and auto-stash.
- T4 DONE synchronization.
- T5 remove/cleanup.
- T6 switch/spawn atomicity.
- T7 slug/snapshot hardening.

Сервер не рестартовал; live DB и live worktree не изменялись.

## T2 — Merge in target-owning checkout

Статус: **DONE**, ожидает merge Orchestra-orchestrator.

### Что изменено

- `merge_worktree_to_main()` разрешает владельца target-ветки через
  `git worktree list --porcelain` и выполняет precheck/squash/commit в этом checkout.
- Если target-ветка никем не занята, сохранён прежний путь: временный checkout в primary
  repo с восстановлением исходной ветки.
- Worker и target обязаны быть чистыми. Ошибка перечисляет изменённые пути; merge больше
  не делает скрытых `stash`/`stash pop`.
- После успешного merge child worktree остаётся на своей branch, но его HEAD/index/tree
  сбрасываются к новому target commit.
- `prunable`/исчезнувший target checkout даёт явный `{ok: false}` без автоматического
  `git worktree prune` и без изменения child.

### Проверка

- Реальные Git-тесты:
  - child → feature-ветка, checked out в parent worktree;
  - dirty parent и dirty primary отклоняются без stash и без изменения HEAD;
  - удалённый зарегистрированный checkout воспроизводит `prunable` и отклоняется без
    исключения.
- `tests/test_workspace.py`: `66 passed in 6.40s`.
- Full suite: `1023 passed in 116.84s`; raw log: `/tmp/pytest-90-t2.log`.
- Read-only live validation:
  - 80 non-archived sessions;
  - 24 canonical repositories from union `sessions.scope` + actual `worktree_path`
    Git common-dir;
  - 62/62 existing active worktrees resolved to their actual Git owner;
  - 89/89 non-prunable registry entries resolved; 4/4 prunable entries rejected;
  - 0 validation errors, 1 pre-existing missing worktree;
  - 13 legacy `sessions.branch` values differ from actual checkout branch; live DB was
    not changed, and T2 validation used Git as the source of truth.
- `git diff --check`: clean.

### Review

- Codex first found that the parser returned a path before reading the record's trailing
  `prunable` marker. The defect was reproduced in `/tmp`, fixed by complete-record parsing,
  and covered by a real Git regression.
- Resume round: **APPROVED**, prior P2 fixed, no new findings. Full record:
  `docs/tasks/90/codex-review-t2.md`.

### Compatibility / remaining work

- Intentional behavior change: dirty target now fails loud instead of being auto-stashed.
- Stale worktree metadata is reported but never pruned automatically.
- Commit/link rollback and honest link result remain T3.

Сервер не рестартовал; live DB и live worktree не изменялись.
