<task-management>
## Task tracker & checklists

- **Tools**: `task_create` (repeat with identical `request_key` if outcome was ambiguous), `task_update`, `task_list`, `task_get` and worker-only `update_checklist`.
- **Lifecycle**: `spawn_worker`, assignment and `merge_worker(task_outcome="complete"|"continue")` own `in_progress`/`done` transitions automatically; manual agent updates to those lifecycle states are rejected, and fresh task state is already included in spawn/send/merge/`list_agents` responses.
- **Catalog & IDs**: `.orchestra/projects.yaml` defines the closed vocabulary for `project` and `tags`. Quote `source` when task numbers come from multiple machines (e.g. `#161 · laptop`), and preserve `V-` prefixes (`V-42`) across tools, branches, commits and `.orchestra/tasks/V-42/`.
- **When to track**: create/bind a task after owner approval (or autonomously for research that leaves `.orchestra/` artifacts); skip task creation for trivial 1-2 line fixes.
- **Worker checklists**: `update_checklist(items, completed, current, estimates_minutes)` requires positive numeric `estimates_minutes` for every new or edited step text (`null` keeps stored estimates on unchanged steps; owner decision, 2026-10-15).
</task-management>
