# V-782 — shared admission and cgroup isolation

## Result

Implemented the delegated cgroup setup and dynamic workflow admission path. On 2026-10-08 the service root initially had `cgroup.controllers=cpu io memory pids`, an empty `cgroup.subtree_control`, `populated=1`, and 22 direct PIDs. Writing `+cpu +io +memory` returned `EBUSY`. With the owner's explicit instruction, moved every listed PID into `orchestra-api` without signaling it; the service root then had no direct PIDs and the controllers enabled successfully.

The live `agents` cgroup now has CPU weight 50 versus 100 for `orchestra-api`, IO weight `default 50` versus `default 100`, `memory.high=4,823,277,568` bytes, and `memory.max=6,970,761,216` bytes. These are derived at startup from effective cgroup files: `agents.limit = max(agents.current, service.limit - (service.current - agents.current) - (service.max - service.high))`, applied separately to the service high and max limits. At configuration, service memory current was 8,061,624,320 bytes, agents current was 0, service high was 15,032,385,536, and service max was 17,179,869,184. This keeps the observed non-agent service usage and the high-to-max emergency margin outside the agent allocation. A later resource read showed service current 7,889,805,312, agents current 0, CPU capacity 8, and CPU/memory PSI `avg10=0.0` each. The calculated bootstrap limit was 1 while the online mean was unmeasured. A controlled `pidfd_exec` launch was observed in `/system.slice/orchestra.service/agents` and exited normally.

On each non-pytest application startup, the cgroup setup moves direct root processes to `orchestra-api`, enables `cpu`, `io`, and `memory`, and creates or updates the `agents` limits. Test lifespans skip this host mutation. Dynamic workflow runner processes move into `agents` before `exec`; normal Claude SDK, Codex, and Grok CLI subprocesses also enter the group before executing provider code.

The scheduler stores requests and leases in `data/workflow-scheduler.sqlite3`, independent from `orchestra.db`. Each model attempt asks Orchestra for a slot before incrementing `dispatched_calls`; API errors keep polling and do not dispatch. Active calls renew leases; abandoned leases and queued entries expire after the lease interval. Queue order interleaves each run's FIFO requests round-robin. The per-run semaphore remains in force. The limit is recomputed on each request from available CPU capacity, agents and service cgroup memory headroom, observed agents memory divided by active leases, and CPU/memory PSI. Its current formula is `max(0, min(cpu_capacity, floor(memory_headroom / measured_average), floor(cpu_capacity * (1 - max(cpu_psi, memory_psi) / 100))))`; missing PSI closes admission at zero. Before the first completed-workload sample, memory allows one bootstrap slot, unless CPU pressure or memory headroom reduces the limit to zero. Existing leases are never revoked when the limit drops.

At the later live resource read: effective CPU capacity was 8, agents `memory.high` headroom was 4,823,277,568 bytes, agents `memory.max` headroom was 6,970,761,216 bytes, service memory current was 7,889,805,312 bytes, agents memory current was 0, and CPU/memory PSI `avg10` were both 0.0. The scheduler had no completed task memory sample (`average_task_bytes=0`), so the formula selected one bootstrap slot. No provider/model call was made to manufacture a workload sample; completed dynamic workflow attempts populate the measured mean during normal use.

The workflow manifest records the last scheduler state. The V-776 card displays waiting status and position, plus the current active/queued slot data and the calculated limit reason.

## Processes moved by owner-authorized repair

The following direct members of `/system.slice/orchestra.service/cgroup.procs` were moved to `/system.slice/orchestra.service/orchestra-api/cgroup.procs`. `cwd` was read from `/proc/<pid>/cwd` before each move; `(deleted)` is the kernel's reported cwd target.

| PID | comm | cwd |
|---:|---|---|
| 1764588 | xray | /tmp |
| 4131256 | python3 | /home/kesha/orchestra/worktrees/home-kesha-projects-comfy-image-pipeline/painter-geometry/oil-paint (deleted) |
| 736 | python3 | /home/kesha/orchestra/worktrees/home-kesha-projects-comfy-image-pipeline/painter-geometry/oil-paint (deleted) |
| 865393 | python | /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-ci-green (deleted) |
| 881271 | python | /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-ci-green (deleted) |
| 1823051 | node | /home/kesha/orchestra/worktrees/home-kesha-projects-comfy-image-pipeline/painter-wall-v2/oil-paint (deleted) |
| 1823057 | node | /home/kesha/orchestra/worktrees/home-kesha-projects-comfy-image-pipeline/painter-wall-v2/oil-paint (deleted) |
| 1823080 | python3 | /home/kesha/orchestra/worktrees/home-kesha-projects-comfy-image-pipeline/painter-wall-v2/oil-paint (deleted) |
| 1256326 | python3 | /home/kesha/orchestra/worktrees/opt-cog-second-brain/balatro-vps/04-projects/balatro (deleted) |
| 1332343 | python3 | /home/kesha/orchestra/worktrees/opt-cog-second-brain/balatro-vps/04-projects/balatro (deleted) |
| 1336221 | python3 | /home/kesha/orchestra/worktrees/opt-cog-second-brain/balatro-vps/04-projects/balatro (deleted) |
| 1340650 | python3 | /home/kesha/orchestra/worktrees/opt-cog-second-brain/balatro-vps/04-projects/balatro (deleted) |
| 2334703 | python3 | /home/kesha/orchestra/worktrees/opt-cog-second-brain/autobattler/04-projects/autobattler (deleted) |
| 2338767 | python3 | /home/kesha/orchestra/worktrees/opt-cog-second-brain/balatro-vps/04-projects/balatro (deleted) |
| 2682935 | bash | /home/kesha/komandor-data |
| 2682938 | jupyter-lab | /home/kesha/komandor-data |
| 2688110 | python3 | /home/kesha/komandor-data |
| 2697550 | python3 | /home/kesha/komandor-data |
| 1545102 | python3 | /home/kesha/orchestra/worktrees/home-kesha-projects-seedon-site/seo-cro (deleted) |
| 2079424 | python3 | /home/kesha/orchestra/worktrees/home-kesha-projects-seedon-site/seo-cro (deleted) |
| 578260 | ssh | /tmp |
| 1544432 | ssh | /home/kesha/orchestra/worktrees/home-kesha-projects-seedon/b2b-tenders |

## Review follow-ups (orchestrator, 2026-10-08)

1. Orchestrator sessions are not placed in `agents`: `agent_process_options(orchestrator=True)` returns nothing, the Claude wrapper is skipped for `_is_orchestrator`, and Codex `RuntimeProcessGroup.create(orchestrator=True)` ignores the delegated group (stays beside the API). Test: `test_orchestrator_stays_outside_agent_cgroup_and_worker_enters`.
2. Layout is now `agents/workers` (leaf for ordinary workers, `ORCHESTRA_AGENT_CGROUP`) plus `agents/workflow-<run_id>` (leaf per `wf_run`, created by `enter_workflow_cgroup`; `ORCHESTRA_AGENT_ROOT` is `agents`). `agents` enables `+cpu +io +memory` in subtree_control and its direct processes are moved to `workers` at startup. The per-task memory sample is `workflow-<run>/memory.current / that run's active leases`, never the whole `agents` memory. Test: `test_task_average_ignores_memory_of_ordinary_workers` (6 GB of worker memory, 1 lease, limit stays >= 1). Empty `workflow-*` groups are removed on scheduler acquire.
3. Idle floor: with 0 active leases and max(CPU, memory PSI) < 90 the limit is at least 1 and the reason says "idle floor=1". Only unavailable PSI keeps the limit at 0, and the reason ("pressure_factor=unavailable=>0") appears on the card. Test: `test_idle_queue_always_gets_one_slot_below_pressure_threshold`.

Live probe (no restart): `configure_agent_cgroup()` created `agents/workers`, enabled `cpu io memory` in `agents/cgroup.subtree_control`, and a probe leaf `agents/workflow-probe` exposed `memory.current` (removed afterwards). Note: `agents` limits are computed from service usage at configuration time, so after this probe `memory.high` became 2,175,401,984 bytes because service memory was higher than at the first configuration; limits are recomputed only at startup.

## Verification

- `uv run --frozen python -m pytest tests/test_workflow_scheduler.py tests/test_workflow_cards.py::test_workflow_detail_maps_journal_progress_to_labeled_tasks tests/test_wf_run.py::test_waiting_for_global_slot_does_not_dispatch_or_spend tests/test_bg_jobs.py::TestPidfdProcessLifecycle::test_shell_and_argv_modes_preserve_arguments -q` — 10 passed.
- After the follow-ups: `uv run --frozen python -m pytest tests/test_workflow_scheduler.py tests/test_wf_run.py tests/test_dynamic_workflows.py tests/test_workflow_cards.py tests/test_runtime_process_group.py tests/test_backend_codex.py tests/test_backend_claude.py tests/test_backend_grok.py tests/test_bg_jobs.py tests/test_workspace.py -q` — 518 passed, 1 skipped.
- `git diff --check` and Python `py_compile` on changed application modules succeeded.

## Limits

The per-task memory estimate is an online mean of measured agents-cgroup memory divided by active leases, not a peak-isolated per-process measurement. A new scheduler starts at one slot until it has observations. Regular provider CLIs are isolated by cgroup placement; the shared dynamic-workflow scheduler gates dynamic workflow attempts only. No Orchestra restart was performed. Python changes require the owner-initiated restart before the new startup repair, routes, and process placement become active.

## Fixed agent limits (orchestrator decision, 2026-10-08)

`agents.memory.high = 75%` of `service.memory.high` and `agents.memory.max = 87.5%` of `service.memory.max` (`AGENTS_MEMORY_HIGH_SHARE`, `AGENTS_MEMORY_MAX_SHARE` in `app/agent_cgroups.py`), independent of current usage; this supersedes the usage-derived formula above. Live values after re-running `configure_agent_cgroup()`: high 11,274,289,152 (10.5 GiB), max 15,032,385,536 (14 GiB). Test: `test_agent_limits_do_not_depend_on_service_usage`.
