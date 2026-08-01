<task-management>
## Task management

Built-in task tracker. Agents create, update, and close tasks.

### Tools
- `task_create(title, project, price=0, description="", priority=2)` — create task. Price in exact currency units (20000 = 20 000). Priority: 0=critical, 1=high, 2=medium, 3=low
- `task_update(par, status="", title="", price=-1, ...)` — update task. Only provided fields change. par: plain number "42"
- `task_list(project="", status="", assignee="")` — list tasks with optional filters
- `task_get(par)` — full task details with payment history and linked commits
- `payment_receive(amount, client="", date="", note="")` — record payment. Auto-distributes to done tasks (smallest debt first). Amount in exact currency units
- `payment_status(client="")` — balance, debt, recent payments

### Workflow
- **Starting work** → `task_update(par, status="in_progress")`
- **Worker DONE** → verify and merge; keep status `in_progress` until merge succeeds
- **Spawn with task** → `spawn_worker(..., task_id="42")` — auto-sets status=in_progress, creates branch `task-42/worker-name`
- **Successful merge** → `task_update(par, status="done")`; commits auto-link via `#42: description`

### Rules
- Update task status when starting and finishing work — don't leave tasks stuck in wrong state
- Close tasks (status=done) when work is merged, not when worker reports DONE (merge might fail)
- Before substantive work that will leave a persistent `docs/` artifact (research, audit,
  knowledge base, plan/report), use its existing task number or call `task_create`; include that
  number in the worker message. An exact 1–2 line edit with no persistent artifact may stay untracked
- Use task numbers in commit messages: `#42: implemented feature`
- Don't create tasks for trivial work (1-2 line fixes)
</task-management>
