# #425 — Implementation report: «Дорога по этапам»

## Outcome

Выбранная concept 01 реализована в существующей панели `PROJECTS`:

- primary technical namespace является полным источником задач; optional links только добавляют
  explicit foreign tasks;
- task имеет 0/1 theme label, project — ordered 0–7 labels;
- одна project row рисует stages слева направо, tasks внутри вертикально, derived marker
  `мы здесь`, open waits и сворачиваемую unlabelled queue/history;
- task detail остаётся read-only modal;
- user answer доставляется exact `opened_by_session_id` через existing `message_deliveries`, без
  второго канала.

Live-backup acceptance доказал главный production case: `orchestra` имеет 274 namespace tasks и
0 links, после migration payload содержит все 274, а links остаются 0.

## Tickets and commits

### T1 — Complete task source + bounded theme labels

Commit `0679f47c`:

- additive legacy-safe columns/migration/backfill/index;
- owner-only source/order/stage routes;
- full primary-source query + additive explicit links;
- atomic rename, exact normalized-scope authorization, casefold uniqueness, 0–7 cap;
- route snapshot updated in the same commit as the routes.

### T2 — Durable wait response

Commit `6991254d`:

- optional-compatible `WaitResolve.response` and CSRF token for dashboard operator;
- async resolve bypasses sync `_call()` and awaits existing receipt acceptance;
- deterministic attempts; retry only `FAILED_BEFORE_SUBMIT`; ambiguous state is a barrier;
- SQLite trigger resolves only the current receipt on `SUBMITTED` and bumps goal once;
- archived/missing opener returns 409; legacy agent resolve/cancel remains compatible.

### T3 — Concept-01 dashboard road

Commit `11e382be`:

- project roads/stages/status signals/marker;
- no-stage state, complete lazy queue/history, disclosure state preserved across poll refresh;
- waiting task glow, explicit namespace task detail, answer form in existing modal;
- 1280/1920 body containment and project-owned horizontal scroll.

### Review hardening

Commit `edd92a8d`:

- stage link creation and label write combined into one final transaction;
- durable wait/opener revalidated immediately before receipt acceptance;
- pending response prevents competing agent close;
- multiple waits per task plus project-level/orphaned waits all get independent answer controls.

## Changed production files

- `app/db.py` `+114/-1` — roadmap/wait schema migration, safe backfill, indexes, current-attempt
  submission trigger.
- `app/portfolio.py` `+453/-12` — complete payload, source/order/label services, reservation/retry/
  validation state machine.
- `app/routes/portfolio.py` `+142/-7` — owner mutations, operator CSRF payload, awaited resolve.
- `app/static/js/app.js` `+267/-60` — roads, complete disclosures, wait controls, explicit task detail.
- `app/static/css/style.css` `+143/-1` — industrial road/stage/task/wait visual system.
- `tests/route_surface_snapshot.json` `+22/-4` — actual route surface, committed with T1.

`dashboard.html`, task/canonical binding, `message_deliveries.py`, manager, MCP tools and prompts were
not changed.

## Acceptance evidence

### Frozen focused oracles

```text
uv run python -m pytest -q -s \
  tests/test_project_roadmap_backend_425.py \
  tests/test_project_roadmap_frontend_425.py \
  tests/test_frontend.py::test_project_road_425_uses_real_dashboard_dom_and_load_path \
  tests/test_frontend.py::test_task_card_uses_real_long_description_and_shared_expandable_body \
  tests/test_portfolio_integrity_418.py tests/test_portfolio_attention_418.py \
  tests/test_portfolio_watchdog_418.py tests/test_routes_surface.py

21 passed in 10.19s
#425 production sessions invariant: before=577 after=577 (T1 and T2)
```

After review hardening:

```text
12 passed in 11.15s
#425 production sessions invariant: before=578 after=578 (T1 and T2)
```

The changing absolute count (`577→578`) came from concurrent live platform activity; each command's
before/after invariant remained equal.

### Live migration and idempotency

```text
uv run python docs/tasks/425/live_backup_oracle.py
#425 live backup invariant: namespace_tasks=274 payload_tasks=274 links=0->0
production_sessions=577 copied_sessions=577 source=orchestra
#425 production sessions invariant: before=577 after=577

# separate backup probe
#425 revision idempotency: project_revision=1->1->1
copied_sessions=577 production_sessions=577->577
```

Both probes used `sqlite3.Connection.backup()`; production was opened read-only.

### Browser delivery

```text
uv run python -m pytest -q \
  tests/test_project_roadmap_frontend_425.py::test_t3_concept_one_keeps_every_task_and_answers_wait_in_read_only_modal \
  tests/test_frontend.py::test_project_road_425_uses_real_dashboard_dom_and_load_path
2 passed in 11.91s
```

The first path loaded the production vendor chain and checked stage placement, active accents,
96-row disclosure, exact 137-row no-slice control, read-only task detail, CSRF answer and 1280/1920
containment. The second started the isolated real dashboard, clicked the actual `PROJECTS` tab and
went through `PortfolioPanel.load()`.

Post-review manual browser probe:

```text
#425 wait UI probe: task_wait_controls=2 project_wait_controls=1
```

### Mutation / pre-mortem evidence

1. **Primary namespace query removed** → T1 failed with `visible["tasks"] == set()` while four
   primary tasks were expected; restored command passed and sessions stayed equal.
2. **Current delivery-id condition removed from SUBMITTED trigger** → T2 failed because stale attempt
   A resolved wait whose current attempt was B; restored command passed.
3. **Queue renderer changed to `slice(0,100)`** → T3 failed because the 137-row exact ID set lost
   IDs 400–436; restored command passed.
4. **Next consumer: ordinary TASKS detail** → existing shared-body regression passed after
   `showTaskDetail()` moved from raw `fetch` to `api` and gained an explicit project selector.
5. **Next consumer: multiple/project/orphaned waits** → review follow-up browser probe produced two
   task answer controls and one project answer control.

### Full-suite boundary

- Required `pytest -x -q` stopped at
  `tests/test_api.py::TestTaskProjectIdentity::test_create_defaults_to_callers_mapped_scope`
  (`400` vs `200`). The same focused node fails identically on current `main`; response is
  `create_task cannot allocate a task number...` from the pre-existing canonical/shadow task path.
- Full no-`-x` reached 83% and was killed with exit 137 before pytest could emit node IDs/summary.
  Kernel log exposed no #425-specific trace. The run is recorded as inconclusive resource failure,
  not green and not attributed to this diff.
- The project's mapped gate had only the four frozen #425 REDs before implementation; all four are
  now green, and the pre-existing route snapshot is green.

## Review

Route: Luna (explicitly requested; Sol not authorized), one completed implementation round.

Artifact: `docs/tasks/425/review-implementation.md`.

Reviewer command/evidence:

```text
uv run pytest -q tests/test_project_roadmap_backend_425.py \
  tests/test_project_roadmap_frontend_425.py \
  tests/test_frontend.py::test_project_road_425_uses_real_dashboard_dom_and_load_path
4 passed in 14.05s
```

Verdict: `APPROVED`, no blocking findings. Four suggestions were code-verified and implemented;
canonical policy does not permit another model round for suggestions, so follow-up evidence is the
focused `12 passed` command and manual multi-wait probe above.

## Breaking / rollout

- Intentional UI contract change: four portfolio status columns are replaced by per-project roads.
- Additive SQLite migration runs on service restart; no existing task links are synthesized.
- Frontend files are hot, but the user needs `Ctrl+Shift+R` after merge.
- Python routes/schema need the normal Orchestra restart.
- A pending operator response now blocks a competing agent resolve/cancel until its delivery reaches
  a terminal known state; this prevents a sent answer from racing a closed wait.

## TODO / gaps

- Full flat suite remains unable to produce a final summary on this machine; its first deterministic
  failure is present on `main`, and the no-`-x` run was resource-killed.
- Derived marker readability with simultaneous early/late active stages is covered mechanically and
  visually at 1440 px, but final product tuning remains a live user-feedback question.
