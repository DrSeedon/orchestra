<worker-lifecycle>
## Worker assignment, WIP gate & archival

- **Lifecycle tag**: prefix worker `description` with `lifecycle=one-shot` or `lifecycle=persistent` (unmarked legacy sessions default to persistent); keep strictly one active task per worker.
- **Outcome-driven briefs**: specify the target outcome, acceptance checks, task artifacts path and hard exclusions—leave implementation/research method to the worker unless a specific technique is part of the contract. For data collection, specify schema, unit and coverage rules.
- **Shared close gate (`worker_wip` -> `kill_worker`)**:
  1. Always call `worker_wip` right before `kill_worker`. Uncommitted files block permanent archival—either have the worker commit/clean within scope or use reversible `stop_worker`.
  2. Merge accepted commits via `merge_worker` (or record rejection reason + branch provenance) and confirm all assigned phases and owner-facing research explanations are delivered.
- **Prompt archival**: archive completed Hub workers and `lifecycle=one-shot` native workers immediately via `kill_worker` in the same completion turn once the close gate passes; keep at most one idle `lifecycle=persistent` native worker per active recurring track when imminent work exists.
</worker-lifecycle>
