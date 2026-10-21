# V-1004 — background run job cgroup isolation

On 21.10.2026, eight `node sim.js` processes launched by `bg_create(type=run)` reached about 10.6 GB RSS in `agents`. The group crossed its 11.27 GB `memory.high` (recorded `memory.events high=8,180,077`), after which Claude CLI startup timed out across projects. Cancelling the run dropped agent usage to 1.5 GB and the failures stopped.

`configure_agent_cgroup()` now creates `agents/jobs` beside `agents/workers`. Worker and orchestrator CLI placement is unchanged: CLI agents use `workers`, and orchestrators remain outside the agent cgroup. Locally launched `run` workloads flagged as agent workloads now receive the `jobs` cgroup path through the existing pidfd exec shim. Ordinary jobs do not inherit agent cgroup placement. When delegation is absent, setup clears the cgroup environment and run jobs continue through the pre-existing unisolated path.

The jobs group receives 50% of the configured `agents/memory.high` and 50% of `agents/memory.max`. With the cgroup setup test's agents values (1050 and 1400 bytes), this yields jobs limits of 525 and 700 bytes. On the incident host, with `agents/memory.high=11.27 GB`, the jobs `memory.high` is approximately 5.64 GB; its max is half the configured agents max. The earlier high limit throttles a large job before it reaches the agents parent's high threshold, and the child max contains an eventual OOM to `agents/jobs`.

Verification: `uv run --frozen python -m pytest tests/test_workflow_scheduler.py tests/test_bg_agent_isolation.py -q` passed (25 tests). The tests use temporary directories for cgroup files; one also launches a CLI process and a managed run process to verify membership in `workers` and `jobs`, respectively. The no-delegation test verifies the run receives no cgroup path. The test that checks the run's actual cgroup membership will fail if its target is changed back to `workers`. Imported `app` path: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-bg-cgroup/app/__init__.py`.

The running service was not changed. This Python change takes effect after the owner's authorized restart.
