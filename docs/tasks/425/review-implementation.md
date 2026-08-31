<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Because the road is beautifully drawn, naturally the waits are the parts without exits. 🛣️

Reviewed `/tmp/425-implementation.diff` and named production/tests. No blocking crash, corruption, or security findings. Fresh/legacy migration ordering is sound; no files were edited.

Focused verification:

```text
uv run pytest -q tests/test_project_roadmap_backend_425.py tests/test_project_roadmap_frontend_425.py tests/test_frontend.py::test_project_road_425_uses_real_dashboard_dom_and_load_path
....                                                                     [100%]
4 passed in 14.05s
```

## Findings (blocking/suggestion/question)

### [suggestion] Make primary task stage assignment atomic

**File:** `app/portfolio.py:520-523`

`set_task_stage()` reads state, then calls `link_task()` in a separate transaction, then reads state again. If the owner changes stage order between those operations, the request can return `422` after already creating a new portfolio link with no stage. Perform resolution, link creation, and stage update inside one `BEGIN IMMEDIATE` transaction.

### [suggestion] Render project-level waits as answerable controls

**File:** `app/static/js/app.js:3736-3749`

Project-level waits are rendered as plain text only. Since `task_ref` is optional in `project_wait`, these are normal waits, but the dashboard provides no wait ID, textarea, or response button for them. Reuse the response control for waits without a task card.

### [suggestion] Do not collapse task-bound waits to one card

**File:** `app/static/js/app.js:3627-3632, 3736-3749`

`waitForTask()` selects only the first open wait. Multiple waits for one task are allowed because the backend key includes the question, so the remaining waits disappear from the UI. A wait whose task is later unlinked or deleted also retains `task_stable_id` and is excluded from project-level rendering. Render every open wait by ID and surface orphaned waits separately.

### [suggestion] Revalidate the wait before accepting its delivery

**File:** `app/routes/portfolio.py:311-315`

`prepare_wait_response()` commits the reservation before the async preflight and delivery acceptance. During that gap, the opener can be archived or an agent can resolve the wait; the route then still accepts and sends the reserved message. Couple reservation with acceptance using a CAS/transactional guard, or revalidate both wait status and opener status immediately before accepting.

## Verdict

**APPROVED**

No blocking findings. The four suggestions affect wait usability and race semantics but do not meet the requested blocking threshold.

The road has excellent signage; the exits are apparently optional DLC. 🛣️
