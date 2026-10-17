# V-928: CI red on e25c4310 — test_t6_grok_spawns_with_parent_owned_pipes

**Cause: environment leak between tests, exposed by shard re-composition (not by V-927 code).**
`app.agent_cgroups.initialize_agent_cgroup()` writes `os.environ` directly
(`ORCHESTRA_AGENT_CGROUP_REQUIRED=1` when cgroup setup fails, as in CI). `tests/test_workflow_scheduler.py`
calls it directly; `monkeypatch.delenv(..., raising=False)` does not undo direct writes made afterwards.
Every later provider spawn in the same xdist worker then raised
`delegated agent cgroup is unavailable; refusing to launch provider process` (`agent_process_options`).
e25c4310 added `tests/test_temp_rules_v927.py`; CI shards are `sorted files, (NR-1)%6`, so the new file moved
`test_workflow_scheduler.py` into shard 0 together with `test_instant_restart.py` (shard list: `shard0.txt`).
V-924 (dae6b676) introduced the latent leak; it just never shared a worker with a spawn test before.

**Reproduction.** Locally the failure was hidden: the agent process itself has `ORCHESTRA_AGENT_CGROUP` set, and a
full shard-0 run passed (`shard0-before.log`, 1292 passed). With the three vars unset (as in CI):
`env -u ORCHESTRA_AGENT_CGROUP -u ORCHESTRA_AGENT_ROOT -u ORCHESTRA_AGENT_CGROUP_REQUIRED pytest tests/test_workflow_scheduler.py tests/test_instant_restart.py -n 0`
→ `1 failed, 22 passed` (the same test, same error).

**Fix.** `tests/conftest.py`: autouse `_restore_agent_cgroup_env` snapshots and restores the three vars around each test.
Regression test `tests/test_agent_cgroup_env_isolation_v928.py` (test_a sets them directly, test_b asserts the baseline).
Mutation (fixture made non-autouse): both test_b and test_t6 go red; with the fixture: 25 passed.
Production code untouched, no restart.
