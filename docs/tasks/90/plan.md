# Задача #90 — план реализации

План принят Orchestra-orchestrator 2026-07-26. Реализация идёт вертикальными срезами
T1→T7; после каждого среза — полный `pytest`, отдельный коммит, отчёт и STOP для merge.
Сервер не рестартовать, live worktree и live DB не изменять.

## Общие инварианты

- Git target определяется одним persisted contract, не литералом `main` и не текущим HEAD.
- Платформа не stash/commit/discard пользовательский WIP.
- Ошибка после изменения Git либо полностью откатывается, либо возвращает отдельное
  состояние частичного успеха с commit SHA; generic retry не допускается.
- Lifecycle mutation одинаково сохраняется для loaded и detached session.
- После Git-изменений read-only validation охватывает union живых `sessions.scope` и
  canonical repositories из `worktree_path` через Git common-dir.

## Tickets

### T1 — Persisted base-branch lifecycle contract

- Files: `app/db.py`, `app/session.py`, `app/manager.py`, `app/workspace.py`,
  `app/routes/sessions.py`, `app/mcp_stdio.py`, tests этих модулей.
- Change:
  - additive columns `base_branch TEXT DEFAULT ''` и
    `needs_switch INTEGER DEFAULT 0`;
  - resolve spawn base один раз: explicit override first; затем
    `base_branch_strategy=parent` → parent branch, а `strategy=main` → verifiable
    repository mainline; symbolic remote HEAD либо единственная local `main`/`master`,
    ambiguity fails loud;
  - blank MCP/HTTP defaults resolve through persisted `base_branch`;
  - merge keeps `branch` equal to actual worker checkout, persists merge target as
    `base_branch`, clears task and persists `needs_switch`;
  - loaded/detached lifecycle updates use one DB contract.
- AC:
  - omitted base works in main-only and master-only repositories and persists the
    selected branch;
  - a primary checkout on a feature branch does not change resolved mainline;
  - repositories with both `main` and `master` and no symbolic remote HEAD reject
    omitted base without Git mutation;
  - explicit and parent-feature bases remain supported;
  - migration is idempotent, old rows receive non-destructive defaults, and an insert
    that omits the new columns still succeeds;
  - default merge/switch/auto-switch/WIP/kill use the stored base; blank ambiguous
    legacy rows fail before destructive Git;
  - after loaded and detached merge, DB holds actual `branch`, target `base_branch`,
    empty `task_id`, and `needs_switch=1`;
  - full pytest passes.
- blocked-by: none

### T2 — Merge in target-owning checkout; reject dirty target

- Files: `app/workspace.py`, merge route tests, workspace Git tests.
- AC:
  - child merges into a parent branch checked out in the parent worktree;
  - dirty target returns paths and changes neither target nor child;
  - auto-stash is absent from merge path;
  - clean main/master merge remains green.
- blocked-by: T1

### T3 — Atomic squash and task-link results

- Files: `app/workspace.py`, `app/tm.py`, `app/routes/sessions.py`,
  `app/mcp_stdio.py`, tests.
- AC:
  - rejecting hook in related and unrelated paths restores target HEAD/index/worktree
    and leaves child unchanged;
  - successful task linking reports added count; unknown task reports an explicit error;
  - MCP never renders successful linking as `FAILED — unknown`.
- blocked-by: T2

### T4 — DONE-to-IDLE synchronization

- Files: `app/session.py`, `app/session_turns.py`, `app/routes/sessions.py`, tests.
- AC:
  - merge waits on explicit turn completion, not a guessed grace timeout;
  - signal is published after `finish_turn_status()`;
  - `WAITING` is not merge-ready;
  - no hidden interrupt/`stop_worker` occurs.
- blocked-by: T3

### T5 — Fail-loud remove and stale cleanup

- Files: `app/workspace.py`, `app/manager.py`, routes/tests.
- AC:
  - nonzero Git removal is returned and session is not archived as success;
  - detached sessions remove their worktree before archive;
  - cleanup reports a path only after disappearance;
  - `scope_dir` is renamed `repo_dir` without algorithm changes.
- blocked-by: T4

### T6 — Atomic spawn/switch/task transitions

- Files: `app/workspace.py`, `app/manager.py`, `app/routes/sessions.py`, tests.
- AC:
  - running status is rechecked under the shared lifecycle lock;
  - send auto-switch follows the same lock order;
  - failure does not mark task in progress;
  - spawn marks a task in progress only after successful worktree creation/session start,
    and a failed spawn leaves the previous task state unchanged;
  - real merge conflict is rolled back or persisted as an explicit resumable state,
    never mixed failure/success.
- blocked-by: T5

### T7 — Repo identity and managed snapshots

- Files: `app/workspace.py`, `app/manager.py`, managed-skill sync code, tests.
- AC:
  - distinct canonical repo paths cannot collide after readable slug truncation;
  - existing worktree paths are not migrated;
  - managed skills synchronize exact-set on reconnect;
  - arbitrary copied files remain explicit snapshots unless separately marked managed.
- blocked-by: T6

## Не входит

- Рестарт или deploy сервера.
- Запись в live DB.
- Изменение или cleanup живых worktree.
- Рефакторинг соседнего runtime вне конкретного ticket.
