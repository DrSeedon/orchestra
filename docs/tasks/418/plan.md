# #418 — План authoritative project portfolio

Статус: Phase 2, план + frozen RED only. Реализация не начата.

## 1. Зафиксированные решения пользователя

1. **Project — source of truth.** `scope` остаётся техническим runtime key.
2. **Worker↔task binding не меняется.** Existing `tm_tasks.project_id`, session `task_id`, scoped
   bind/merge/requeue и canonical task identity остаются в нынешней семантике.
3. **Portfolio project у task опционален.** Task без human project — законное состояние, не debt.
   Все старые tasks остаются без portfolio-link, пока их явно не свяжут.
4. **Goal принадлежит project.** Project может существовать без goal; watchdog выключен по
   умолчанию и работает только для active project goal.
5. **Owner один; sub-orchestrator помогает как contributor.** Owner и contributor оба видят
   project и могут работать с goal, но ownership/watchdog policy меняет только owner.
6. **Semantic/vector search не участвует.** После #419 `RAG_ENABLED=false`; board, access,
   cleanup и watchdog используют exact SQL/IDs/statuses и literal grep, не embeddings.

## 2. Supersession вывода Phase 1

Phase 1 отвергала новую project table, потому что `tm_projects` уже владела всеми tasks. Новое
решение пользователя меняет premise: task должен оставаться в прежнем mandatory technical
namespace и одновременно может не иметь human project вообще.

Поэтому:

- `tm_projects` сохраняется без semantic rename/migration как **legacy technical task namespace**;
- existing `tm_tasks.project_id NOT NULL` и canonical `task.state.project_id` не меняются;
- новая authoritative human entity называется `portfolio_projects`;
- optional relation хранится отдельно в `portfolio_task_links` и не входит в task binding.

Это не две конкурирующие human project identity: `tm_projects` больше не используется как owner/
goal/board truth. Старую формулировку в `docs/kb/project-portfolio.md` нужно отозвать, не удалять.

## 3. Архитектура данных

### 3.1 `portfolio_projects`

```text
id TEXT PRIMARY KEY                   # immutable project slug/id
name TEXT NOT NULL
revision INTEGER NOT NULL DEFAULT 1
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
archived_at TEXT NULL
```

`scope` в таблице отсутствует. Project path/repository можно позже добавить отдельным attachment,
но #418 этого не требует.

### 3.2 `portfolio_members`

```text
project_id TEXT NOT NULL REFERENCES portfolio_projects(id)
session_id TEXT NOT NULL REFERENCES sessions(id)
role TEXT CHECK role IN ('owner','contributor')
created_at TEXT NOT NULL
revoked_at TEXT NULL
PRIMARY KEY(project_id, session_id, created_at)
```

```sql
CREATE UNIQUE INDEX uq_portfolio_one_owner
ON portfolio_members(project_id)
WHERE role='owner' AND revoked_at IS NULL;
CREATE UNIQUE INDEX uq_portfolio_active_member
ON portfolio_members(project_id,session_id)
WHERE revoked_at IS NULL;
```

Один `session_id` может быть owner нескольких projects. DB index обеспечивает cardinality, а
service authorization дополнительно проверяет lifecycle:

- owner — только non-archived `role='orchestrator'` без parent;
- contributor — только non-archived `role='sub-orchestrator'`, чей acyclic `parent_id` chain
  достигает current owner;
- worker/reducer/full-cycle не могут быть member; sub не может быть owner;
- respawn получает новый session id и не наследует grant;
- archive или reparent вне owner ancestry делает membership неактивным; одно имя/тот же scope
  ничего не восстанавливают.

### 3.3 `portfolio_task_links`

```text
project_id TEXT NOT NULL REFERENCES portfolio_projects(id)
task_stable_id TEXT NOT NULL
task_row_id INTEGER NOT NULL REFERENCES tm_tasks(id)
task_namespace_id TEXT NOT NULL        # frozen tm_tasks.project_id receipt
task_display_number INTEGER NOT NULL   # frozen par_number receipt
linked_by_session_id TEXT NOT NULL
created_at TEXT NOT NULL
removed_at TEXT NULL
```

```sql
CREATE UNIQUE INDEX uq_portfolio_active_stable_task
ON portfolio_task_links(task_stable_id) WHERE removed_at IS NULL;
CREATE UNIQUE INDEX uq_portfolio_active_legacy_task
ON portfolio_task_links(task_row_id) WHERE removed_at IS NULL;
```

Link создаётся только после exact resolution canonical stable id ↔ legacy row id/project/#N.
Снятие link не меняет task. Existing task create/bind/switch/merge/requeue paths не читают эту
таблицу; project board читает её как optional association.

Link authorization is the conjunction of two independent checks:

1. caller has active owner/contributor membership in the portfolio project;
2. existing task authorization resolves the technical task only through the caller session's
   authoritative scope (`caller_scope → tm_projects.id`); caller-supplied `task_project` must equal
   that result. Arbitrary explicit-project lookup is not accepted for linking.

Thus membership cannot expose a foreign technical task. One active link per stable task is enforced
by the partial unique indexes above.

### 3.4 `portfolio_goals`

```text
id TEXT PRIMARY KEY                    # UUID
project_id TEXT NOT NULL REFERENCES portfolio_projects(id)
objective TEXT NOT NULL CHECK(length(objective) BETWEEN 1 AND 4000)
status TEXT CHECK status IN ('active','paused','completed','cancelled')
watchdog_enabled INTEGER NOT NULL DEFAULT 0
stall_after_seconds INTEGER NOT NULL DEFAULT 1800
last_progress_at TEXT NOT NULL
stall_generation INTEGER NOT NULL DEFAULT 1
revision INTEGER NOT NULL DEFAULT 1
created_by_session_id TEXT NOT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
completed_at TEXT NULL
```

```sql
CREATE UNIQUE INDEX uq_portfolio_active_goal
ON portfolio_goals(project_id) WHERE status IN ('active','paused');
```

Default: no goal rows, therefore no watchdog candidates. `objective` 4000-char limit mirrors the
public Codex goal surface but this is an Orchestra cross-runtime contract.

### 3.5 Wait/activity/watchdog receipts

`portfolio_waits`:

```text
id TEXT PRIMARY KEY
claim_key TEXT NOT NULL UNIQUE
project_id TEXT NOT NULL
goal_id TEXT NOT NULL
opened_by_session_id TEXT NOT NULL
question TEXT NOT NULL
task_stable_id TEXT NULL
status TEXT CHECK status IN ('open','resolved','cancelled')
opened_at TEXT NOT NULL
resolved_at TEXT NULL
```

`claim_key = sha256(goal_id, stall_generation, caller_session_id, normalized_question,
task_stable_id-or-empty)`. Concurrent/retried opens in one generation use `INSERT OR IGNORE` in one
transaction and return the same wait row. After resolve plus a new generation, the same question
may open again.

`portfolio_activity_leases`:

```text
project_id TEXT NOT NULL
goal_id TEXT NOT NULL
session_id TEXT NOT NULL
heartbeat_at TEXT NOT NULL
lease_expires_at TEXT NOT NULL
PRIMARY KEY(project_id, goal_id, session_id)
```

`portfolio_watchdog_outbox`:

```text
goal_id TEXT NOT NULL
stall_generation INTEGER NOT NULL
delivery_id TEXT NOT NULL
target_owner_session_id TEXT NOT NULL
state TEXT CHECK state IN ('pending','delivering','accepted','retryable')
attempts INTEGER NOT NULL DEFAULT 0
claimed_at TEXT NOT NULL
lease_expires_at TEXT NOT NULL
accepted_at TEXT NULL
PRIMARY KEY(goal_id, stall_generation)
UNIQUE(delivery_id)
```

Evaluator first inserts/claims the outbox row in a transaction, commits, then delivers. Concurrent
evaluators lose `INSERT OR IGNORE` and do not call delivery. Crash/failure leaves a retryable or
expired claim; the next evaluator reuses the same `delivery_id`. Accepted delivery seals exactly
one logical wake per generation. Progress, linked task activity and wait resolution bump
`last_progress_at` and `stall_generation`.

### 3.6 Attention integration

`portfolio_attention_events` stores
`kind IN ('legacy','incident','reversal','plan_change')`, reason, source session, optional project
id, created/delivered timestamps. Existing one-argument `notify_user(reason)` remains legal as
projectless `kind='legacy'` during rollout. Waiting is rejected here and goes only through
`project_wait`.

TG bridge accepts a successful tool-result carrying a durable attention event id. The explicit
`notify_user` tool-call remains a fail-loud fallback under the pre-existing #241 contract: a DB
failure must not silently swallow an explicit request to tag. Project-wait and watchdog have
different tool names and result markers, so neither can enter either tag path.

## 4. Owner и sub-orchestrator

### Выбранная механика: explicit owner/contributor membership

- Root orchestrator creates/owns project.
- Sub-orchestrator receives `contributor` membership by exact `session_id`.
- If parent owns exactly one project, sub spawn UI may offer that project preselected, but the
  persisted grant is still explicit. If parent owns multiple, project selection is mandatory.
- Owner-only: rename/archive/transfer project, add/revoke members, set/replace/complete goal,
  enable watchdog or change threshold.
- Contributor: read board/goal, link tasks it may already access, record goal progress, open/resolve
  waits and refresh its activity lease.
- Ordinary worker never becomes member. It contributes only through its existing task; if that task
  has a portfolio link, its running/waiting/task lifecycle counts as project activity.

### Отвергнутые варианты и что в них ломается

1. **Dynamic inheritance from `parent_id/parent_name`.** Reparent silently changes authorization;
   name/id can drift; a parent with several projects leaks all of them to every sub; historical
   grant/revoke audit disappears.
2. **Owner у parent и sub одновременно.** Violates user invariant and makes watchdog target,
   membership mutation and goal completion ambiguous.
3. **Scope-derived contributor.** Any orchestrator in the same technical scope gets project access;
   this recreates the Seedon defect under another name.

Trade-off explicit membership: respawned sub has a new session id and needs a new grant; reparent
does not carry access silently. Every authorization read revalidates current role/status/ancestry;
archive/reparent hooks eagerly revoke where possible, with fail-closed lazy rejection as the safety
net. Это намеренный fail-closed cost.

## 5. Agent tools и tool-utility gate

### `project_goal(project, action, ...)`

Actions: `get`, `set`, `progress`, `pause`, `resume`, `complete`, `cancel`, `watchdog`.

- `set/pause/resume/complete/cancel/watchdog`: owner-only.
- `get/progress`: owner or contributor.
- `progress` updates generation and member activity lease.

Без tool агент должен exact-resolve project membership, сделать optimistic revision/CAS goal,
обновить progress/generation/lease и вернуть receipt. Это multi-write Python/curl workflow; tool
проходит гейт.

### `project_wait(project, action, ...)`

Actions: `open(question, task_ref?)`, `resolve(wait_id)`, `cancel(wait_id)`. `project` mandatory.
Owner/contributor only; optional task must already be linked to that project. Open wait suppresses
watchdog; resolve bumps goal generation.

Без tool агент должен resolve member/project/goal/task, создать durable wait и suppression state
с duplicate-safe CAS. Это multi-write workflow; tool проходит гейт.

### Новых tools больше нет

- Project/task link идёт через existing `task_update(..., portfolio_project=...)` extension or UI;
  отдельный `project_link_task` не нужен — без него это один короткий mutation.
- Board/listing — UI/API; agent already has task/list agents plus exact project tools.
- Owner assignment — rare admin/API action.

## 6. Watchdog contract

Loop: one server task from FastAPI lifespan, interval 300 seconds.

Candidate iff:

1. project has exactly one live owner membership;
2. goal status is `active` and `watchdog_enabled=1`;
3. no open wait for goal;
4. no unexpired owner/contributor activity lease;
5. no running/waiting worker bound to a task linked to the project;
6. `now - last_progress_at >= stall_after_seconds` (default 1800);
7. no receipt for current `stall_generation`.

Action: durable internal message to **owner session only**. Contributor is never the watchdog target.
Transport retries reuse one `delivery_id`; they do not create another model wake. A project action
opens a new generation; unchanged polling does not.

Goal with zero linked tasks **is watchdog-eligible** when active/enabled. The user's Phase-2
decision moved actionable truth from task to project goal; linked tasks contribute activity and
suppression but are not a prerequisite. This explicitly supersedes Phase-1's task-based predicate.

### Пересчёт старого replay

Task status is no longer the watchdog predicate. Existing rows have no portfolio links, there are no
portfolio projects/goals after schema migration, and watchdog defaults off. Therefore:

```text
initial watchdog candidates = 0
initial monthly wakes = 0
```

The Phase-1 synthetic `176` episode replay is superseded for product sizing; it remains evidence
only that polling dirty task status was the wrong design. After owners explicitly create goals and
enable watchdog, run 14 days in shadow (log candidate/suppression/generation, no delivery) before
allowing wakes.

## 7. Board contract

The board opens as a panel inside the existing dashboard. JavaScript injects a `PROJECTS` button
beside the existing `FILES` / `TASKS` / `JOBS` controls and renders into the existing
`#tasks-panel`; the agent list and chat remain unchanged. There is no standalone `/project-board`
route and no second page shell.

Each project lane shows owner, contributors, current goal/watchdog badge, last progress and:

1. **Планируется** — linked tasks `backlog/new`;
2. **В работе** — linked tasks `in_progress` plus active leases;
3. **Ждёт решения** — open project waits with exact question;
4. **Сделано** — recent linked `done/paid` tasks and completed goal summary.

Project with goal and zero linked tasks is still visible. Tasks without link never appear on board
but remain visible through existing task tools. Data is exact SQL joins; no semantic search/vector.

## 8. Разбор старых 44 dead + 31 idle tasks

### Свежий срез

At `2026-08-30T07:38:24.082Z` live read-only SQL returned:

```text
dead:archived    26
dead:no-binding  18
idle             31
running           4
```

The user's «32 idle» changed to 31 while planning; cleanup must always recompute from a fresh
snapshot, never trust either frozen count.

Final pre-commit rerun at `2026-08-30T08:12:18.197Z` still had 44 dead but idle had moved again
to 33 and running to 2. This second drift is why the operator procedure begins with a fresh backup/
manifest instead of a hard-coded list.

### Inventory SQL (read-only)

```sql
WITH candidates AS (
  SELECT
    t.id AS task_row_id,
    t.project_id AS task_namespace_id,
    t.par_number,
    t.title,
    t.status AS task_status,
    t.sync_revision,
    t.worker_session_id,
    ws.name AS worker_name,
    ws.status AS worker_status,
    ws.role AS worker_role,
    ws.parent_id,
    ws.parent_name,
    p.scope AS task_scope,
    CASE
      WHEN t.worker_session_id IS NULL OR ws.id IS NULL THEN 'dead:no-binding'
      WHEN ws.status='archived' THEN 'dead:archived'
      WHEN ws.status='idle' THEN 'idle'
      WHEN ws.status='waiting' THEN 'waiting'
      WHEN ws.status='running' THEN 'running'
      ELSE 'other:' || COALESCE(ws.status,'NULL')
    END AS bucket,
    (
      SELECT substr(replace(l.content,char(10),' '),1,500)
      FROM logs l
      WHERE l.session_id=ws.id AND l.type IN ('text','user_message')
      ORDER BY l.ts DESC LIMIT 1
    ) AS last_text,
    (
      SELECT MAX(l.ts) FROM logs l
      WHERE l.session_id=ws.id AND l.type IN ('text','user_message')
    ) AS last_text_at
  FROM tm_tasks t
  JOIN tm_projects p ON p.id=t.project_id
  LEFT JOIN sessions ws ON ws.id=t.worker_session_id
  WHERE t.status='in_progress'
), heirs AS (
  SELECT
    c.task_row_id,
    COUNT(DISTINCT h.id) AS live_heir_count,
    GROUP_CONCAT(DISTINCT h.id) AS live_heir_ids
  FROM candidates c
  LEFT JOIN sessions h
    ON RTRIM(h.scope,'/')=RTRIM(c.task_scope,'/')
   AND h.task_id=CAST(c.par_number AS TEXT)
   AND h.status!='archived'
  GROUP BY c.task_row_id
)
SELECT c.*, h.live_heir_count, h.live_heir_ids
FROM candidates c JOIN heirs h USING(task_row_id)
WHERE c.bucket IN ('dead:no-binding','dead:archived','idle')
ORDER BY c.bucket, c.task_namespace_id, c.par_number;
```

Aggregate check:

```sql
WITH candidates AS (
  SELECT
    t.project_id AS task_namespace_id,
    CASE
      WHEN t.worker_session_id IS NULL OR ws.id IS NULL THEN 'dead:no-binding'
      WHEN ws.status='archived' THEN 'dead:archived'
      WHEN ws.status='idle' THEN 'idle'
      WHEN ws.status='waiting' THEN 'waiting'
      WHEN ws.status='running' THEN 'running'
      ELSE 'other:' || COALESCE(ws.status,'NULL')
    END AS bucket
  FROM tm_tasks t
  LEFT JOIN sessions ws ON ws.id=t.worker_session_id
  WHERE t.status='in_progress'
)
SELECT bucket,COUNT(*) tasks,COUNT(DISTINCT task_namespace_id) namespaces
FROM candidates GROUP BY bucket ORDER BY bucket;
```

### Decision procedure

1. Make a WAL-safe `sqlite3.Connection.backup` on real disk; record DB max log id, canonical task
   head and a SHA-256 manifest of `(row id, namespace, #N, revision, status, binding, worker state,
   heir ids)`.
2. **Dead rows:**
   - exactly one live heir → `REBIND` to that session, keep `in_progress`;
   - zero heirs → `REQUEUE` to `new`, clear binding;
   - >1 heirs → `STOP/manual`, no automatic choice.
3. **Idle rows:** no bulk rule. For each row inspect exact last text, branch/merge receipt and task
   commits using literal SQL/git. Choose `KEEP`, `REQUEUE`, `DONE`, or `CANCELLED`; `DONE` requires
   merge/acceptance evidence, not words in title.
4. Freeze per task: `stable_id`, canonical head, canonical content SHA, legacy revision/status/
   binding and heir ids. Before each apply, reread both stores and compare every frozen field;
   **do not replace expected values with the fresh read**. Any mismatch refuses that row. Earlier
   successful rows remain valid receipts; do not roll them back.
5. Apply through `app.tm.api_update_task_if_current`, never raw `UPDATE tm_tasks`: canonical Git is
   task truth and raw SQL would create projection drift.
6. After each receipt, verify canonical state and legacy projection agree on status/binding. Final
   inventory must have zero `dead:*`; remaining idle rows equal explicit `KEEP` decisions.

Safe apply skeleton for the operator script:

```python
detail = tm.api_get_task(str(par_number), project=task_namespace_id)
if detail["stable_id"] != frozen_stable_id:
    raise RuntimeError("REFUSED: stable task identity changed")
if detail["canonical_head"] != frozen_canonical_head:
    raise RuntimeError("REFUSED: canonical head changed since inventory")
if canonical_content_sha(detail) != frozen_canonical_content_sha:
    raise RuntimeError("REFUSED: canonical task content changed since inventory")
live_row = read_legacy_task(task_row_id)
if legacy_manifest_tuple(live_row) != frozen_legacy_manifest_tuple:
    raise RuntimeError("REFUSED: legacy task changed since inventory")
identity = {
    "id": task_row_id,
    "project_id": task_namespace_id,
    "par_number": par_number,
    "sync_revision": frozen_sync_revision,
    "stable_id": frozen_stable_id,
    "canonical_head": frozen_canonical_head,
}
tm.api_update_task_if_current(
    identity,
    status="in_progress" if action == "REBIND" else target_status,
    worker_session_id=heir_session_id if action == "REBIND" else None,
)
```

There is intentionally **no UPDATE SQL** in this plan. The SQL above is inventory only; applying it
directly would bypass the canonical owner. This cleanup is independent of portfolio launch because
old tasks have no links and goal/watchdog are opt-in.

## 9. Rollout order

1. T1 complete foundation (schema/membership/task links/goal/wait); migrate no legacy rows and
   reconnect a disposable agent to prove tools before any prompt instruction references them.
2. T2 watchdog in shadow mode; initial candidates/wakes must be 0.
3. T3 dashboard panel populated from the portfolio API.
4. T4 attention integration; prompt change last, after live route/tool-result success.
5. Operator separately runs §8 cleanup with fresh evidence. It is not a prerequisite for watchdog
   because unlinked tasks are outside the predicate.

## 10. What not to touch

- No change to `ORCHESTRA_SCOPE`, session scope cardinality, worker task binding, merge lifecycle or
  `task.state.project_id` meaning.
- No automatic conversion of the 19 legacy `tm_projects` rows into portfolio projects.
- No automatic linking of 732 old tasks.
- No vector/semantic/RAG dependency.
- No replacement or redesign of existing dashboard/agent list/chat.
- No user ping from project wait or watchdog.

## 11. Review gate inputs

- Changed artifacts/consumers: `plan.md`, frozen acceptance test, KB supersession; future production
  consumers are schema, task API wrapper, membership authorization, lifecycle observer, scheduler,
  TG attention path and dashboard portfolio panel.
- Author: `research-projects-board`, `gpt-5.6-sol`, runtime Codex (live session metadata from Phase 1).
- AC: decisions in §1 + ticket commands below.
- Oracle: `d4c634de` is excluded for dependency-only route gates; `be398ad6` is excluded because its
  DB fixture wrote fake sessions to production. `cb8ea22d` is excluded because two tests imported
  application modules before installing the guard. `f05eb5e1` remains immutable for T1/T2/T4;
  its T3 standalone-page oracle is excluded after the user changed scope to an in-dashboard panel.
  T3 replacement `2f6e7256` is also excluded: its browser harness loaded `utils.js` without
  the production `marked`/`DOMPurify` vendor chain and therefore could not reach its own final
  no-console-errors assertion. Current T3 immutable RED is `d4fd8d2c`: production vendor chain,
  RC=1 at `#418 T3 missing behavior: portfolio dashboard panel control`.
- Risk floor: persistence schema, cross-project authorization, shared message delivery and lifecycle
  observer. Sol review would be the preferred route but auxiliary Sol is not authorized; use one
  fresh Luna plan/test pass and report the limitation.

## Tickets

### T1 — Complete project foundation: membership, optional tasks, goal and wait
- Files: `app/db.py`; new `app/portfolio.py`; new `app/routes/portfolio.py`; `app/main.py` router registration; `app/mcp_stdio.py` (`project_goal`, `project_wait`, existing `task_update` portfolio-link extension); session archive/reparent membership hook; focused tests under `tests/`. Do not change task binding or canonical `task.state.project_id` semantics.
- Test: `docs/tasks/418/acceptance/test_project_portfolio_418.py::test_t1_project_foundation_preserves_tasks_and_enforces_membership_goal_wait` — committed RED in `f05eb5e1`; `d4c634de`, `be398ad6`, `cb8ea22d` excluded.
- RED: `uv run python -m pytest -q docs/tasks/418/acceptance/test_project_portfolio_418.py::test_t1_project_foundation_preserves_tasks_and_enforces_membership_goal_wait` → exit 1: `AssertionError: #418 missing portfolio route: /api/portfolio/projects`.
- AC: named command is green + one project has exactly one active root-orchestrator owner; one owner owns two projects; explicit direct/ancestral sub contributor reads/progresses/waits; worker membership and sub ownership return 422; outsider/respawn/reparented-away sub get 403; task link additionally enforces caller-scope technical task authorization and rejects foreign task; linking preserves `tm_tasks.project_id`, session/binding/merge and canonical task project; unlinked task stays legal; project may have no goal; goal watchdog defaults off; owner controls policy; two concurrent identical waits return one id/row via server-derived claim; migration auto-creates zero projects/links; disposable live MCP call proves `project_goal` and `project_wait` before prompt delivery.
- blocked-by: none

### T2 — Goal-only watchdog with atomic durable outbox
- Files: new `app/portfolio_watchdog.py`; `app/portfolio.py`; `app/db.py`; `app/main.py` lifespan startup/teardown; existing durable message delivery seam; focused async/race tests.
- Test: `docs/tasks/418/acceptance/test_project_portfolio_418.py::test_t2_watchdog_goal_only_atomic_claim_and_retry_reuse_delivery_id` — committed RED in `f05eb5e1`.
- RED: `uv run python -m pytest -q docs/tasks/418/acceptance/test_project_portfolio_418.py::test_t2_watchdog_goal_only_atomic_claim_and_retry_reuse_delivery_id` → exit 1: `AssertionError: #418 T2 missing behavior: app.portfolio_watchdog`.
- AC: named command is green + loop interval 300s; active/enabled goal with zero linked tasks is eligible; no goal/off watchdog/open wait/unexpired lease/linked running-or-waiting worker suppress correctly; threshold `>=1800s`; concurrent evaluators call delivery once; claim is durable before delivery; failure/crash recovery reuses exact delivery id; progress creates new generation; target owner only; fresh migration candidates=0/wakes=0; shadow mode emits no delivery.
- Additional focused regression required before T2 completion: lifespan starts one 300-second loop and cancels it cleanly; a fresh DB returns candidates=0 in both active and shadow modes; a pending outbox row survives closing/reopening the SQLite connection and reuses its delivery id.
- blocked-by: T1

### T3 — Dashboard portfolio panel backed by real project data
- Files: `app/routes/portfolio.py`; `app/static/js/app.js`; `app/static/css/style.css`; focused browser tests. Reuse existing `#tasks-panel`; create the button and panel contents in JavaScript; do not replace the dashboard, agent list or chat.
- Test: `docs/tasks/418/acceptance/test_project_portfolio_418.py::test_t3_dashboard_button_opens_portfolio_panel_with_real_project_payload` — committed RED in `d4fd8d2c`; T3 from `f05eb5e1` excluded because the user changed scope from a standalone page to a dashboard panel; `2f6e7256` excluded because its browser harness omitted production vendor assets.
- RED: `uv run python -m pytest -q docs/tasks/418/acceptance/test_project_portfolio_418.py::test_t3_dashboard_button_opens_portfolio_panel_with_real_project_payload` → exit 1: `AssertionError: #418 T3 missing behavior: portfolio dashboard panel control`.
- AC: named command is green at a 1440×900 desktop viewport + injected `PROJECTS` button opens the existing `#tasks-panel`; four left-to-right columns render the linked task, goal, exact wait question, owner and contributor; an unlinked task is absent; a second goal-only project remains visible; exact SQL/IDs only, no semantic search; agent list/chat behavior stays unchanged; no `/project-board` route or separate page is added.
- blocked-by: T1

### T4 — Durable typed attention integration; wait/watchdog never tag
- Files: `app/db.py`; `app/portfolio.py`; `app/routes/portfolio.py`; `app/mcp_stdio.py`; `app/tg_bridge.py`; `pipelines/default/prompts/roles/orchestrator.md` only after live route/tool proof; focused tests.
- Test: `docs/tasks/418/acceptance/test_project_portfolio_418.py::test_t4_attention_is_durable_before_tag_and_wait_watchdog_never_tag` — committed RED in `f05eb5e1`.
- RED: `uv run python -m pytest -q docs/tasks/418/acceptance/test_project_portfolio_418.py::test_t4_attention_is_durable_before_tag_and_wait_watchdog_never_tag` → exit 1: `AssertionError: #418 T4 missing project attention integration`.
- AC: named command is green + legacy one-argument call remains legal with `kind=legacy` and no project; typed `incident|reversal|plan_change` accepts optional exact project; attention row is durable before tool result; durable marker is sufficient for a tag and explicit `notify_user` call remains the #241 fail-loud fallback; `kind=waiting` points to `project_wait`; project-wait/watchdog tool names and result markers never tag; prompt stops recommending notify for decisions and changes only after live success.
- Additional focused regression required before T4 completion: use a real isolated portfolio DB/route and bridge parser (no `_api` fake) to prove the attention row is committed before tag eligibility; project-wait/watchdog rows remain ineligible.
- blocked-by: T1, T3

## 12. Full RED evidence

```text
uv run python -m pytest -q docs/tasks/418/acceptance/test_project_portfolio_418.py
FFFF
4 failed
exit 1
```

Per-ticket rerun produced RC=1 for all four named nodes and the exact missing-behavior assertion
recorded in each ticket. No collection/import failure is used as RED. Commit `d4c634de` is excluded
forever because reviewer proved its T2/T3/T5 failures were dependency-only route gates. Commit
`be398ad6` is excluded because `_init_db()` used the production DB. `cb8ea22d` is excluded because
T2/T3 installed the guard after their first application-module import. T3 in `f05eb5e1` is also
excluded after the user changed scope from a standalone page to a dashboard panel. Replacement
`2f6e7256` is excluded because it loaded `utils.js` without the production `marked`/`DOMPurify`
assets and failed outside the T3 seam. Current T3 immutable RED is `d4fd8d2c`; current T1/T2/T4 in `f05eb5e1` patch
`DB_PATH` and `ORCHESTRA_DB_PATH` to `tmp_path` before `init_db()` and guards every
`sqlite3.connect` against the production path **before any DB/application-layer import in each
DB-using test**.

Isolation proof for the full current RED run:

```text
PRODUCTION_SESSIONS_BEFORE=563
PRODUCTION_SESSIONS_AFTER=563
PYTEST_RC=1
FFFF / 4 failed
```

Task-local Python audit: the acceptance file is the only #418 writer importing `app.db`, and its
three DB-using tests all call the isolated helper. `watchdog_replay.py` opens its DB with
`mode=ro`; the other #418 artifacts contain no DB fixture.

## 13. Review outcome

Route: fresh Luna, two prose rounds. Round 1 found five blocking issues in cleanup, membership,
task authorization, wait idempotency and watchdog delivery claiming. They were accepted; RED
`d4c634de` was excluded and strengthened oracle `be398ad6` frozen. Round 2 verdict: **APPROVED**,
blocking 0. Post-review, `be398ad6` was excluded for production DB pollution, `cb8ea22d` for late
guard installation, and safety-only oracle `f05eb5e1` frozen; production count proof is 563→563 and
the same four RED seams remain.
Nonblocking KB/SQL suggestions were applied, and the three remaining acceptance-strength
suggestions are explicit per-ticket focused regressions above.
Evidence: `docs/tasks/418/review-plan-luna.md`.

## 14. Oracle isolation incident

The excluded `be398ad6` oracle created ten fake `owner/sub/helper/worker/outsider` sessions in the
production DB during two RED runs. The orchestrator removed them after a backup; supplied incident
check reports 563 real sessions intact, no logs and no tasks for the fakes. `cb8ea22d` was an
intermediate excluded freeze; current oracle `f05eb5e1` has the direct 563→563 invariant in §12.

Rule candidate for orchestrator triage:

> 📝 RULE: When an oracle starts the application or its DB layer → prove isolation with a
> production row-count before/after invariant, not the author's intent.
