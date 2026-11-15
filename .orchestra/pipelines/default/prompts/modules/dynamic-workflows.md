## Dynamic workflows (`dynamic_workflow`)

`dynamic_workflow` runs durable server-side `wf_run` batches (up to 20 stages, 1,000 tasks, 1 MiB spec) and wakes your session on completion—never poll it:
- **Modes**: `parallel` (independent tasks), `chain` (each step receives the prior result) or `stages` (each stage receives all prior-stage results; supports `items` + `{item}` expansion).
- **Caps & billing**: `budget_usd` caps cumulative spend and `max_calls` caps dispatched calls (`partial_reason=budget|call_limit`). Pass `billing="api_credit"` only when the owner explicitly authorized API-credit spend for that task; exhausted credits fail closed without switching to subscriptions.
- **Adapter scope**: `wf_run` executes admitted cloud/API batch models and has no Hub worktree adapter—use `spawn_worker` (and `open_fan` when collecting fan-out) for Hub repository work or multi-turn sessions, and custom `wf_run.py` scripts only when Python branching/transforms are needed between steps.
