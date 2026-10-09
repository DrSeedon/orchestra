import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.agent_cgroups import configure_agent_cgroup
from app.runtime_process_group import RuntimeProcessGroup
from app.workflow_scheduler import WorkflowScheduler, calculate_limit, resource_snapshot


def test_limit_uses_cpu_memory_headroom_and_pressure():
    limit, reason = calculate_limit({
        "cpu_count": 8,
        "memory_high": 8_000,
        "memory_current": 2_000,
        "cpu_pressure": 50,
        "memory_pressure": 20,
    }, active=2, average_task_bytes=2_000)
    assert limit == 3
    assert "memory_headroom=6000/2000=3" in reason
    assert "pressure_factor=0.500=>4" in reason


def test_resource_snapshot_reads_cgroup_cpu_limit_and_psi(tmp_path, monkeypatch):
    cgroup = tmp_path / "agents"
    cgroup.mkdir()
    (cgroup / "cpu.max").write_text("250000 100000")
    (cgroup / "memory.high").write_text("9000")
    (cgroup / "memory.max").write_text("12000")
    (cgroup / "memory.current").write_text("3000")
    (tmp_path / "memory.high").write_text("10000")
    (tmp_path / "memory.max").write_text("12000")
    (tmp_path / "memory.current").write_text("5000")
    proc = tmp_path / "proc"
    (proc / "pressure").mkdir(parents=True)
    (proc / "pressure/cpu").write_text("some avg10=12.50 avg60=0.00 avg300=0.00 total=1\n")
    (proc / "pressure/memory").write_text("some avg10=2.00 avg60=0.00 avg300=0.00 total=1\n")
    monkeypatch.setattr("os.sched_getaffinity", lambda _pid: set(range(8)))
    snapshot = resource_snapshot(cgroup, proc)
    assert snapshot == {
        "cpu_count": 2.5,
        "cpu_capacity": 2,
        "memory_high": 9000,
        "memory_max": 12000,
        "memory_current": 3000,
        "service_memory_high": 10000,
        "service_memory_max": 12000,
        "service_memory_current": 5000,
        "cpu_pressure": 12.5,
        "memory_pressure": 2.0,
    }


def test_unavailable_pressure_closes_admission():
    limit, reason = calculate_limit({
        "cpu_count": 8, "memory_high": 8_000, "memory_max": 10_000,
        "memory_current": 1_000, "cpu_pressure": None, "memory_pressure": 0,
    }, active=0, average_task_bytes=1_000)
    assert limit == 0
    assert "pressure_factor=unavailable=>0" in reason


def test_scheduler_fairly_alternates_runs_with_persisted_queue(tmp_path):
    snapshot = {"cpu_count": 4, "memory_high": 10_000, "memory_current": 0,
                "cpu_pressure": 0, "memory_pressure": 0}
    scheduler = WorkflowScheduler(tmp_path / "scheduler.sqlite3", snapshot=lambda: snapshot)
    assert scheduler.acquire("a1", "run-a")["granted"]
    assert scheduler.acquire("a2", "run-a")["granted"] is False
    assert scheduler.acquire("b1", "run-b")["granted"] is False
    assert scheduler.snapshot()["queued"] == 2
    scheduler.release("a1")
    assert scheduler.acquire("a2", "run-a")["granted"] is False
    assert scheduler.acquire("b1", "run-b")["granted"]
    scheduler.release("b1")
    assert scheduler.acquire("a2", "run-a")["granted"]
    reopened = WorkflowScheduler(tmp_path / "scheduler.sqlite3", snapshot=lambda: snapshot)
    assert reopened.snapshot()["active"] == 1


def test_pressure_recalculation_waits_without_revoking_active_leases(tmp_path):
    readings = {"cpu_count": 4, "memory_high": 10_000, "memory_current": 1000,
                "cpu_pressure": 0, "memory_pressure": 0}
    scheduler = WorkflowScheduler(tmp_path / "scheduler.sqlite3", snapshot=lambda: readings,
                                  run_memory_reader=lambda _run: 1000)
    assert scheduler.acquire("one", "run-one")["granted"]
    scheduler.release("one")
    assert scheduler.snapshot()["average_task_bytes"] == 1000
    assert scheduler.acquire("one", "run-one")["granted"]
    assert scheduler.acquire("two", "run-two")["granted"]
    assert scheduler.acquire("one", "run-one")["granted"]
    readings["memory_pressure"] = 100
    waiting = scheduler.acquire("three", "run-three")
    assert waiting["granted"] is False
    assert waiting["limit"] == 0
    assert scheduler.snapshot()["active"] == 2
    scheduler.release("one")
    assert scheduler.acquire("three", "run-three")["granted"] is False
    readings["memory_pressure"] = 0
    scheduler.release("two")
    assert scheduler.acquire("three", "run-three")["granted"]


def test_active_lease_renewal_prevents_expiration(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.workflow_scheduler.time.time", lambda: now[0])
    readings = {"cpu_count": 2, "memory_high": 1000, "memory_current": 100,
                "cpu_pressure": 0, "memory_pressure": 0}
    scheduler = WorkflowScheduler(tmp_path / "scheduler.sqlite3", snapshot=lambda: readings,
                                  lease_seconds=10)
    assert scheduler.acquire("long-call", "run")["granted"]
    now[0] += 9
    assert scheduler.acquire("long-call", "run")["granted"]
    now[0] += 9
    assert scheduler.acquire("next", "other-run")["granted"] is False
    assert scheduler.snapshot()["active"] == 1


def test_abandoned_lease_expires_for_restart_recovery(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.workflow_scheduler.time.time", lambda: now[0])
    readings = {"cpu_count": 2, "memory_high": 1000, "memory_current": 100,
                "cpu_pressure": 0, "memory_pressure": 0}
    scheduler = WorkflowScheduler(tmp_path / "scheduler.sqlite3", snapshot=lambda: readings,
                                  lease_seconds=10)
    assert scheduler.acquire("abandoned", "old-run")["granted"]
    now[0] += 11
    assert scheduler.snapshot()["active"] == 0
    assert scheduler.snapshot()["queued"] == 0
    assert scheduler.acquire("replacement", "new-run")["granted"]


def test_delegated_cgroup_configuration_moves_root_members_and_sets_limits(tmp_path, monkeypatch):
    service = tmp_path / "orchestra.service"
    api = service / "orchestra-api"
    api.mkdir(parents=True)
    (service / "cgroup.controllers").write_text("cpu io memory pids")
    (service / "cgroup.subtree_control").write_text("")
    (service / "cgroup.procs").write_text("")
    (service / "memory.high").write_text("1400")
    (service / "memory.max").write_text("1600")
    (service / "memory.current").write_text("900")
    (service / "cpu.weight").write_text("100")
    (service / "io.weight").write_text("default 100")
    for name in ("cgroup.procs",):
        (api / name).write_text("")
    moved = []
    (service / "cgroup.procs").write_text("101\n")

    def move_all(source, _destination):
        if source != service:
            return
        pids = (service / "cgroup.procs").read_text().split()
        moved.extend(pids)
        (service / "cgroup.procs").write_text("")
        (api / "cgroup.procs").write_text("\n".join(pids))

    import app.agent_cgroups as cgroups
    monkeypatch.setattr(cgroups, "_move_processes", move_all)
    original_mkdir = Path.mkdir

    def fake_mkdir(path, *args, **kwargs):
        result = original_mkdir(path, *args, **kwargs)
        if path.name == "agents":
            for filename, value in {
                "cpu.weight": "100", "io.weight": "default 100",
                "memory.high": "0", "memory.max": "0", "memory.current": "0",
            }.items():
                (path / filename).write_text(value)
        return result

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    agents = configure_agent_cgroup(service)
    assert moved == ["101"]
    assert (service / "cgroup.subtree_control").read_text() == "+cpu +io +memory"
    assert (api / "cgroup.procs").read_text() == "101"
    assert (agents / "workers").is_dir()
    assert (agents / "cgroup.subtree_control").read_text() == "+cpu +io +memory"
    assert (agents / "cpu.weight").read_text() == "50"
    assert (agents / "io.weight").read_text() == "default 50"
    assert (agents / "memory.high").read_text() == "1050"
    assert (agents / "memory.max").read_text() == "1400"


def test_workflow_balancer_can_be_disabled_without_blocking_workers(monkeypatch):
    import app.agent_cgroups as cgroups

    monkeypatch.setenv("ORCHESTRA_WORKFLOW_BALANCER_ENABLED", "0")
    monkeypatch.setenv("ORCHESTRA_AGENT_CGROUP", "/stale/workers")
    monkeypatch.setenv("ORCHESTRA_AGENT_ROOT", "/stale/agents")
    monkeypatch.setenv("ORCHESTRA_AGENT_CGROUP_REQUIRED", "1")
    monkeypatch.setattr(
        cgroups, "configure_agent_cgroup",
        lambda: (_ for _ in ()).throw(AssertionError("cgroup setup must be skipped")),
    )

    agents, reason, required = cgroups.initialize_agent_cgroup()

    assert agents is None
    assert reason == "disabled by ORCHESTRA_WORKFLOW_BALANCER_ENABLED"
    assert required is False
    assert cgroups.agent_process_options() == {}
    assert "ORCHESTRA_AGENT_CGROUP" not in os.environ
    assert "ORCHESTRA_AGENT_ROOT" not in os.environ
    assert "ORCHESTRA_AGENT_CGROUP_REQUIRED" not in os.environ


def test_missing_systemd_delegation_skips_setup_but_delegate_failure_stays_required(monkeypatch):
    import app.agent_cgroups as cgroups

    monkeypatch.setenv("ORCHESTRA_WORKFLOW_BALANCER_ENABLED", "1")
    monkeypatch.delenv("ORCHESTRA_AGENT_CGROUP", raising=False)
    monkeypatch.delenv("ORCHESTRA_AGENT_ROOT", raising=False)
    monkeypatch.delenv("ORCHESTRA_AGENT_CGROUP_REQUIRED", raising=False)
    monkeypatch.setattr(cgroups, "_systemd_delegate_enabled", lambda: False)
    monkeypatch.setattr(
        cgroups, "configure_agent_cgroup",
        lambda: (_ for _ in ()).throw(AssertionError("setup must be skipped without Delegate=yes")),
    )
    agents, reason, required = cgroups.initialize_agent_cgroup()
    assert agents is None
    assert reason == "systemd Delegate=no"
    assert required is False
    assert cgroups.agent_process_options() == {}

    from app.bg_jobs import BgJobManager
    import app.bg_jobs as bg_jobs

    spawn_kwargs = {}

    async def fake_spawn(_command, *, shell, **kwargs):
        spawn_kwargs.update(kwargs)
        return object()

    async def await_spawn(task):
        return await task

    monkeypatch.setattr(bg_jobs, "_spawn_bg_process", fake_spawn)
    monkeypatch.setattr(bg_jobs, "_await_owned_spawn", await_spawn)
    asyncio.run(BgJobManager()._spawn_managed_process(
        "job", ["provider"], shell=False, agent_workload=True,
    ))
    assert "env" not in spawn_kwargs

    from app.routes.bg import WorkflowSlotRequest, bg_workflow_slot_acquire
    request = type("Request", (), {"app": type("App", (), {"state": type("State", (), {
        "agent_cgroup": "", "agent_cgroup_error": reason,
        "agent_cgroup_required": False,
    })()})()})()
    response = asyncio.run(bg_workflow_slot_acquire(
        WorkflowSlotRequest(request_id="request-1", run_id="run-1"), request,
    ))
    assert response.status_code == 404
    assert json.loads(response.body)["scheduler_missing"] is True

    monkeypatch.setattr(
        cgroups, "configure_agent_cgroup",
        lambda: (_ for _ in ()).throw(RuntimeError("orchestra-api cgroup missing")),
    )
    monkeypatch.setattr(cgroups, "_systemd_delegate_enabled", lambda: True)
    agents, reason, required = cgroups.initialize_agent_cgroup()
    assert agents is None
    assert "orchestra-api cgroup missing" in reason
    assert required is True
    assert os.environ["ORCHESTRA_AGENT_CGROUP_REQUIRED"] == "1"
    with pytest.raises(RuntimeError, match="refusing to launch provider process"):
        cgroups.agent_process_options()

    monkeypatch.setattr(cgroups, "_systemd_delegate_enabled", lambda: None)
    agents, reason, required = cgroups.initialize_agent_cgroup()
    assert agents is None
    assert "orchestra-api cgroup missing" in reason
    assert required is True


def test_provider_cli_preexec_moves_process_before_exec(tmp_path, monkeypatch):
    from app.agent_cgroups import agent_process_options

    cgroup = tmp_path / "agents"
    cgroup.mkdir()
    membership = cgroup / "cgroup.procs"
    membership.write_text("")
    monkeypatch.setenv("ORCHESTRA_AGENT_CGROUP", str(cgroup))
    result = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        check=True, capture_output=True, text=True, **agent_process_options(),
    )
    assert membership.read_text() == result.stdout.strip()


def test_claude_cli_wrapper_moves_then_execs_original_cli(tmp_path):
    from app.agent_cli_exec import __file__ as wrapper

    cgroup = tmp_path / "agents"
    cgroup.mkdir()
    membership = cgroup / "cgroup.procs"
    membership.write_text("")
    target = tmp_path / "cli"
    target.write_text("#!/usr/bin/env python3\nimport os\nprint(os.getpid())\n")
    target.chmod(0o755)
    env = {
        **os.environ,
        "ORCHESTRA_AGENT_CGROUP": str(cgroup),
        "ORCHESTRA_AGENT_CLI": str(target),
    }
    result = subprocess.run([wrapper], check=True, capture_output=True, text=True, env=env)
    assert membership.read_text() == result.stdout.strip()


def test_codex_runtime_group_is_nested_under_agent_cgroup(tmp_path, monkeypatch):
    agents = tmp_path / "agents"
    agents.mkdir()
    monkeypatch.setenv("ORCHESTRA_AGENT_CGROUP", str(agents))
    original_mkdir = Path.mkdir

    def fake_mkdir(path, *args, **kwargs):
        result = original_mkdir(path, *args, **kwargs)
        if path.parent == agents:
            (path / "cgroup.procs").touch()
            (path / "cgroup.kill").touch()
        return result

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    group, reason = RuntimeProcessGroup.create()
    assert reason == ""
    assert group.path.parent == agents


def test_task_average_ignores_memory_of_ordinary_workers(tmp_path):
    # agents holds 6 GB of ordinary worker memory; the workflow's own group holds 300 MB.
    gb = 1 << 30
    readings = {"cpu_count": 4, "memory_high": 16 * gb, "memory_current": 6 * gb,
                "cpu_pressure": 0, "memory_pressure": 0}
    scheduler = WorkflowScheduler(tmp_path / "scheduler.sqlite3", snapshot=lambda: readings,
                                  run_memory_reader=lambda _run: 300 << 20)
    assert scheduler.acquire("one", "run")["granted"]
    assert scheduler.acquire("one", "run")["granted"]
    scheduler.release("one")
    average = scheduler.snapshot()["average_task_bytes"]
    assert average == 300 << 20
    result = scheduler.acquire("two", "run")
    assert result["granted"] and result["limit"] >= 1


def test_idle_queue_always_gets_one_slot_below_pressure_threshold():
    snapshot = {"cpu_count": 4, "memory_high": 1000, "memory_current": 990,
                "cpu_pressure": 10, "memory_pressure": 10}
    limit, reason = calculate_limit(snapshot, active=0, average_task_bytes=5000)
    assert limit == 1 and "idle floor" in reason
    limit, _ = calculate_limit({**snapshot, "memory_pressure": 95}, active=0, average_task_bytes=5000)
    assert limit == 0
    limit, _ = calculate_limit(snapshot, active=1, average_task_bytes=5000)
    assert limit == 0


def test_orchestrator_stays_outside_agent_cgroup_and_worker_enters(tmp_path, monkeypatch):
    from app.agent_cgroups import agent_process_options

    monkeypatch.setenv("ORCHESTRA_AGENT_CGROUP", str(tmp_path))
    assert agent_process_options(orchestrator=True) == {}
    assert "preexec_fn" in agent_process_options(orchestrator=False)
    monkeypatch.setenv("ORCHESTRA_AGENT_CGROUP_REQUIRED", "1")
    monkeypatch.delenv("ORCHESTRA_AGENT_CGROUP")
    assert agent_process_options(orchestrator=True) == {}
    group, _ = RuntimeProcessGroup.create(orchestrator=True)
    assert group is None or tmp_path not in group.path.parents
    if group is not None:
        group.path.rmdir()


def test_workflow_runner_gets_its_own_leaf_group(tmp_path, monkeypatch):
    from app.agent_cgroups import enter_workflow_cgroup

    monkeypatch.setenv("ORCHESTRA_AGENT_ROOT", str(tmp_path))
    monkeypatch.setenv("ORCHESTRA_AGENT_CGROUP", str(tmp_path / "workers"))
    original_mkdir = Path.mkdir

    def fake_mkdir(path, *args, **kwargs):
        result = original_mkdir(path, *args, **kwargs)
        (path / "cgroup.procs").touch()
        return result

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    group = enter_workflow_cgroup("run-7")
    assert group == tmp_path / "workflow-run-7"
    assert group.joinpath("cgroup.procs").read_text() == str(os.getpid())
    assert os.environ["ORCHESTRA_AGENT_CGROUP"] == str(group)


def test_agent_limits_do_not_depend_on_service_usage(tmp_path, monkeypatch):
    import app.agent_cgroups as cgroups

    monkeypatch.setattr(cgroups, "_move_processes", lambda *_: None)
    results = []
    for current in ("0", "900", "1399"):
        service = tmp_path / current / "orchestra.service"
        (service / "orchestra-api").mkdir(parents=True)
        (service / "agents").mkdir()
        for name, value in {
            "cgroup.controllers": "cpu io memory", "cgroup.subtree_control": "cpu io memory",
            "memory.high": "1400", "memory.max": "1600", "memory.current": current,
            "cpu.weight": "100", "io.weight": "default 100",
        }.items():
            (service / name).write_text(value)
        (service / "agents/memory.current").write_text("0")
        agents = cgroups.configure_agent_cgroup(service)
        results.append(((agents / "memory.high").read_text(), (agents / "memory.max").read_text()))
    assert results == [("1050", "1400")] * 3
