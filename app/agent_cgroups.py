"""Place external agent commands in the delegated, resource-limited cgroup."""

from __future__ import annotations

import os
from pathlib import Path


# Fixed shares of the service limits, independent of current usage, so every startup
# (and any re-run) yields the same values. high=75% throttles agents while the API and
# orchestrators keep >= 25% of service.high; max=87.5% keeps the emergency margin
# between the two limits for the API side.
AGENTS_MEMORY_HIGH_SHARE = 0.75
AGENTS_MEMORY_MAX_SHARE = 0.875


def delegated_service_cgroup(proc_cgroup: Path = Path("/proc/self/cgroup"), root: Path = Path("/sys/fs/cgroup")) -> Path:
    for line in proc_cgroup.read_text().splitlines():
        if line.startswith("0::"):
            current = root / line[3:].lstrip("/")
            for candidate in (current, *current.parents):
                if candidate.name == "orchestra.service":
                    return candidate
            break
    raise RuntimeError("current process is not inside orchestra.service cgroup")


def _read_limit(path: Path) -> int:
    value = path.read_text().strip()
    if value == "max":
        raise RuntimeError(f"unbounded parent cgroup limit: {path}")
    return int(value)


def _read_weight(path: Path, prefix: str = "") -> int:
    value = path.read_text().split()
    if prefix:
        value = [item for item in value if item != prefix]
    return int(value[-1])


def _move_processes(source_group: Path, destination_group: Path) -> None:
    source = source_group / "cgroup.procs"
    destination = destination_group / "cgroup.procs"
    while True:
        try:
            pids = [int(value) for value in source.read_text().split()]
        except OSError as error:
            raise RuntimeError(f"cannot read delegated service processes: {error}") from error
        if not pids:
            return
        moved = False
        for pid in pids:
            try:
                destination.write_text(str(pid))
            except ProcessLookupError:
                moved = True
            except OSError as error:
                if error.errno != 3:
                    raise RuntimeError(f"cannot move service process {pid} to orchestra-api: {error}") from error
                moved = True
            else:
                moved = True
        if not moved:
            raise RuntimeError("delegated service cgroup did not make progress while evacuating processes")


def configure_agent_cgroup(service: Path | None = None) -> Path:
    service = service or delegated_service_cgroup()
    _move_processes(service, service / "orchestra-api")
    controllers = set((service / "cgroup.controllers").read_text().split())
    required = {"cpu", "io", "memory"}
    if not required.issubset(controllers):
        raise RuntimeError(f"delegated cgroup controllers missing: {sorted(required - controllers)}")
    subtree = service / "cgroup.subtree_control"
    enabled = set(subtree.read_text().split())
    missing = required - enabled
    if missing:
        with subtree.open("w") as stream:
            stream.write(" ".join(f"+{name}" for name in sorted(missing)))
    agents = service / "agents"
    agents.mkdir(exist_ok=True)
    workers = agents / "workers"
    workers.mkdir(exist_ok=True)
    # agents becomes an internal node (per-workflow groups need memory accounting),
    # so every process must live in a leaf beneath it.
    if (agents / "cgroup.procs").exists():
        _move_processes(agents, workers)
    agents_subtree = agents / "cgroup.subtree_control"
    if not required.issubset(set(agents_subtree.read_text().split()) if agents_subtree.exists() else set()):
        agents_subtree.write_text(" ".join(f"+{name}" for name in sorted(required)))
    cpu_weight = max(1, _read_weight(service / "cpu.weight") // 2)
    io_weight = max(1, _read_weight(service / "io.weight", "default") // 2)
    values = {
        "cpu.weight": str(cpu_weight),
        "io.weight": f"default {io_weight}",
        "memory.high": str(int(_read_limit(service / "memory.high") * AGENTS_MEMORY_HIGH_SHARE)),
        "memory.max": str(int(_read_limit(service / "memory.max") * AGENTS_MEMORY_MAX_SHARE)),
    }
    for name, value in values.items():
        path = agents / name
        if path.exists() and path.read_text().strip() == value:
            continue
        path.write_text(value)
    return agents


def move_current_process(cgroup: str | None = None) -> None:
    target = cgroup or os.environ.get("ORCHESTRA_AGENT_CGROUP", "")
    if target:
        (Path(target) / "cgroup.procs").write_text(str(os.getpid()))


def _move_subprocess_before_exec() -> None:
    target = os.environ.get("ORCHESTRA_AGENT_CGROUP", "")
    if not target:
        return
    fd = os.open(Path(target) / "cgroup.procs", os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
    finally:
        os.close(fd)


def enter_workflow_cgroup(run_id: str) -> Path | None:
    """Move this runner into its own leaf under agents so its memory is measurable alone."""
    root = os.environ.get("ORCHESTRA_AGENT_ROOT", "")
    if not root:
        return None
    group = Path(root) / f"workflow-{run_id}"
    try:
        group.mkdir(exist_ok=True)
        (group / "cgroup.procs").write_text(str(os.getpid()))
    except OSError:
        return None
    os.environ["ORCHESTRA_AGENT_CGROUP"] = str(group)
    return group


def leave_workflow_cgroup(group: Path | None) -> None:
    if group is not None:
        try:
            group.rmdir()
        except OSError:
            pass


def agent_process_options(orchestrator: bool = False) -> dict:
    # Orchestrators stay beside the API: they are part of the service the agent limits protect.
    if orchestrator:
        return {}
    if os.environ.get("ORCHESTRA_AGENT_CGROUP"):
        return {"preexec_fn": _move_subprocess_before_exec}
    if os.environ.get("ORCHESTRA_AGENT_CGROUP_REQUIRED") == "1":
        raise RuntimeError("delegated agent cgroup is unavailable; refusing to launch provider process")
    return {}
