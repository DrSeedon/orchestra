<worker-lifecycle>
## Tasks, dynamic workflows & worker lifecycle

### Task tracker & checklists
- **Tools & automatic lifecycle**: `task_create` (repeat with identical `request_key` if ambiguous), `task_update`, `task_list`, `task_get` and worker-only `update_checklist`. `spawn_worker`, assignment and `merge_worker(task_outcome="complete"|"continue")` own `in_progress`/`done` transitions automatically; fresh task state is returned in spawn/send/merge/`list_agents` responses.
- **Catalog, prefixes & estimates**: `.orchestra/projects.yaml` defines valid `project` and `tags` values. Quote `source` when task numbers span machines (`#161 · laptop`), preserve `V-` prefixes (`V-42`) across tools/branches/commits/`.orchestra/tasks/V-42/`, skip task creation for trivial 1-2 line fixes, and pass positive numeric `estimates_minutes` on new/edited `update_checklist` steps (`null` keeps stored estimates; owner decision, 2026-10-15).

### Multi-stage & batch workflows (`wf_run`)
- Use MCP `wf_run` (not CLI shell invocation) for structured parallel fans, sequential pipelines or `items` batch sweeps across admitted local/API models when stage outputs feed downstream prompts or JSON schemas. Pass an explicit `model` per task or stage under `model-routing` (`billing="api_credit"` requires explicit task authorization), target committed files at `base_commit`, and use ordinary `spawn_worker` for Hub routes (`hub*`), since `wf_run` has no Hub adapter.

### Worker assignment, WIP gate & archival
- **Lifecycle tag & briefs**: prefix worker `description` with `lifecycle=one-shot` or `lifecycle=persistent` (unmarked legacy sessions default to persistent) and keep strictly one active task per worker. Specify target outcome, acceptance checks, artifact paths, data schemas and hard exclusions—leave technical method to the worker.
- **Shared close gate (`worker_wip` -> `kill_worker`)**: always call `worker_wip` right before `kill_worker`. Uncommitted files block permanent archival (commit/clean within scope or use reversible `stop_worker`). Merge accepted commits via `merge_worker` (or save rejection reason + branch provenance) and confirm all assigned phases and owner-facing research explanations are delivered.
- **Prompt archival**: archive completed Hub workers and `lifecycle=one-shot` native workers immediately via `kill_worker` in the same completion turn once the close gate passes; retain at most one idle `lifecycle=persistent` native worker per active recurring track when imminent work exists.
</worker-lifecycle>
