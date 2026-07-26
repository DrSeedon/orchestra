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
