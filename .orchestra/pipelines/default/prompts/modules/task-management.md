<task-management>
## Task management

Built-in task tracker. Agents create, update, and close tasks.

### Tools
- `task_create(title, project, price=0, description="", priority=2)` — create task. Price in exact currency units (20000 = 20 000). Priority: 0=critical, 1=high, 2=medium, 3=low
- `task_update(par, status="", title="", price=-1, ...)` — update task. Only provided fields change. par: the exact returned reference, e.g. "42" or "V-42"
- `task_list(project="", status="", assignee="")` — list tasks with optional filters
- `task_get(par)` — full task details with payment history and linked commits

### Automatic lifecycle
- spawn/send/merge responses carry the fresh task state; `list_agents` includes a bounded live
  project-task view. Do not spend another model round-trip reconstructing state already returned.
- Planned spawn or assignment binds the canonical task before delivery. A successful
  `merge_worker(task_outcome="complete")` closes it; `task_outcome="continue"` keeps it bound.
- Manual `in_progress`/`done` updates from agent tools are rejected because those states belong to
  the platform lifecycle. Human edits and non-lifecycle fields remain available.

### Rules
- Before approved work that will leave a persistent `.orchestra/` artifact (research, audit,
  knowledge base, plan/report), use its existing task number or call `task_create`; include that
  number in the worker message. An exact 1–2 line edit with no persistent artifact may stay untracked
- `task_create` follows the user's approval, it does not precede it — see `<approval-gate>`.
  Class B research is the exception: it starts on your own decision and still gets a task number
- Use task numbers in commit messages: `#42: implemented feature`
- Don't create tasks for trivial work (1-2 line fixes)
</task-management>

New VPS tasks may use `V-` (e.g. `V-42`). Preserve that prefix in task tools, branch names, commit headers and `.orchestra/tasks/V-42/`. Do not turn it into `42`, rename existing tasks, or rewrite another machine’s task record to reuse its number.
