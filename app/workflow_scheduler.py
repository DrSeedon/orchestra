"""Durable, process-wide admission control for dynamic workflow model calls."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path


def _read_number(path: Path) -> int | None:
    try:
        value = path.read_text().strip()
        return int(value) if value != "max" else None
    except (OSError, ValueError):
        return None


def _pressure(path: Path) -> float | None:
    try:
        for line in path.read_text().splitlines():
            if line.startswith("some "):
                return float(dict(item.split("=", 1) for item in line.split()[1:])["avg10"])
    except (OSError, ValueError, KeyError):
        return None
    return None


def resource_snapshot(cgroup: Path | None = None, proc: Path = Path("/proc")) -> dict:
    cgroup = cgroup or Path(os.environ.get(
        "ORCHESTRA_AGENT_ROOT", "/sys/fs/cgroup/system.slice/orchestra.service/agents",
    ))
    try:
        cpu_count = len(os.sched_getaffinity(0))
    except AttributeError:
        cpu_count = os.cpu_count() or 1
    try:
        quota, period = (cgroup / "cpu.max").read_text().split()
        if quota != "max":
            cpu_count = min(cpu_count, max(1, int(quota) / int(period)))
    except (OSError, ValueError, ZeroDivisionError):
        pass
    high = _read_number(cgroup / "memory.high")
    maximum = _read_number(cgroup / "memory.max")
    current = _read_number(cgroup / "memory.current") or 0
    service = cgroup.parent
    service_high = _read_number(service / "memory.high")
    service_maximum = _read_number(service / "memory.max")
    service_current = _read_number(service / "memory.current") or 0
    cpu_pressure = _pressure(proc / "pressure/cpu")
    memory_pressure = _pressure(proc / "pressure/memory")
    return {
        "cpu_count": cpu_count,
        "cpu_capacity": int(cpu_count),
        "memory_high": high,
        "memory_max": maximum,
        "memory_current": current,
        "service_memory_high": service_high,
        "service_memory_max": service_maximum,
        "service_memory_current": service_current,
        "cpu_pressure": cpu_pressure,
        "memory_pressure": memory_pressure,
    }


def run_memory(run_id: str) -> int:
    """Memory of one workflow runner's own cgroup; 0 when it is not measurable."""
    root = os.environ.get("ORCHESTRA_AGENT_ROOT", "")
    return (_read_number(Path(root) / f"workflow-{run_id}" / "memory.current") or 0) if root else 0


def _prune_empty_run_groups(active_run_ids: set[str]) -> None:
    root = os.environ.get("ORCHESTRA_AGENT_ROOT", "")
    if not root:
        return
    try:
        for group in Path(root).glob("workflow-*"):
            if group.name[len("workflow-"):] not in active_run_ids:
                try:
                    group.rmdir()  # fails while populated, which is the safe answer
                except OSError:
                    pass
    except OSError:
        pass


def calculate_limit(snapshot: dict, active: int, average_task_bytes: int) -> tuple[int, str]:
    cpu_count = max(1, int(snapshot.get("cpu_capacity", snapshot["cpu_count"])))
    high = snapshot.get("memory_high")
    maximum = snapshot.get("memory_max")
    current = max(0, int(snapshot.get("memory_current") or 0))
    memory_headrooms = [max(0, int(limit) - current) for limit in (high, maximum) if limit is not None]
    service_current = max(0, int(snapshot.get("service_memory_current") or 0))
    memory_headrooms.extend(
        max(0, int(limit) - service_current)
        for limit in (snapshot.get("service_memory_high"), snapshot.get("service_memory_max"))
        if limit is not None
    )
    headroom = min(memory_headrooms) if memory_headrooms else 0
    memory_limit = headroom // average_task_bytes if average_task_bytes else 1
    cpu_pressure = snapshot.get("cpu_pressure")
    memory_pressure = snapshot.get("memory_pressure")
    if cpu_pressure is None or memory_pressure is None:
        pressure_factor = 0.0
        pressure_limit = 0
        pressure_detail = "unavailable=>0"
    else:
        pressure_factor = max(0.0, 1.0 - max(float(cpu_pressure), float(memory_pressure)) / 100)
        pressure_limit = int(cpu_count * pressure_factor)
        pressure_detail = f"{pressure_factor:.3f}=>{pressure_limit}"
    limit = max(0, min(cpu_count, memory_limit, pressure_limit))
    idle_floor = False
    # With nothing running the queue must still move while the host is not saturated.
    if active == 0 and limit == 0 and cpu_pressure is not None and memory_pressure is not None \
            and max(float(cpu_pressure), float(memory_pressure)) < 90:
        limit, idle_floor = 1, True
    memory_detail = (
        f"{headroom}/{average_task_bytes}={memory_limit}"
        if average_task_bytes else f"{headroom}/measuring=>{memory_limit}"
    )
    reason = (
        f"min(cpu={cpu_count}, memory_headroom={memory_detail}, pressure_factor={pressure_detail}); "
        f"active={active}, avg_task_memory={average_task_bytes or 'measuring'}"
        + ("; idle floor=1" if idle_floor else "")
    )
    return limit, reason


class WorkflowScheduler:
    def __init__(self, db_path: Path, *, snapshot=resource_snapshot, lease_seconds: int = 90,
                 run_memory_reader=run_memory):
        self.db_path = Path(db_path)
        self.run_memory_reader = run_memory_reader
        self.snapshot_reader = snapshot
        self.lease_seconds = lease_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    queued_at REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    lease_until REAL,
                    granted_at REAL,
                    memory_sample INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS requests_queue ON requests(queued_at);
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO state(key, value) VALUES ('avg_task_bytes', '0');
                INSERT OR IGNORE INTO state(key, value) VALUES ('sample_count', '0');
                INSERT OR IGNORE INTO state(key, value) VALUES ('last_run', '');
            """)

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def acquire(self, request_id: str, run_id: str, label: str = "") -> dict:
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM requests WHERE last_seen < ?", (now - self.lease_seconds,))
            _prune_empty_run_groups({row[0] for row in db.execute("SELECT DISTINCT run_id FROM requests")} | {run_id})
            db.execute(
                "INSERT OR IGNORE INTO requests(request_id, run_id, label, queued_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                (request_id, run_id, label, now, now),
            )
            db.execute("UPDATE requests SET last_seen=?, lease_until=CASE WHEN lease_until IS NULL THEN NULL ELSE ? END WHERE request_id=?",
                       (now, now + self.lease_seconds, request_id))
            snapshot = self.snapshot_reader()
            active = db.execute("SELECT count(*) FROM requests WHERE lease_until IS NOT NULL").fetchone()[0]
            average = int(db.execute("SELECT value FROM state WHERE key='avg_task_bytes'").fetchone()[0])
            run_active = db.execute(
                "SELECT count(*) FROM requests WHERE run_id=? AND lease_until IS NOT NULL", (run_id,)).fetchone()[0]
            run_bytes = self.run_memory_reader(run_id) if run_active else 0
            if run_bytes > 0:
                db.execute("UPDATE requests SET memory_sample=max(memory_sample, ?) WHERE request_id=? AND lease_until IS NOT NULL",
                           (run_bytes // run_active, request_id))
            limit, reason = calculate_limit(snapshot, active, average)
            current = db.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
            if current["lease_until"] is not None:
                queued = db.execute("SELECT count(*) FROM requests WHERE lease_until IS NULL").fetchone()[0]
                db.commit()
                return {"granted": True, "position": 0, "active": active, "queued": queued,
                        "limit": limit, "reason": reason}
            queue = db.execute("""
                SELECT request_id, run_id, queued_at FROM requests
                WHERE lease_until IS NULL ORDER BY queued_at, request_id
            """).fetchall()
            by_run = {}
            for row in queue:
                by_run.setdefault(row["run_id"], []).append(row)
            last_run = db.execute("SELECT value FROM state WHERE key='last_run'").fetchone()[0]
            run_order = sorted(by_run, key=lambda run: by_run[run][0]["queued_at"])
            if last_run in run_order:
                start = run_order.index(last_run)
                run_order = run_order[start + 1:] + run_order[:start + 1]
            ordered = []
            while any(by_run.values()):
                for run in run_order:
                    if by_run[run]:
                        ordered.append(by_run[run].pop(0)["request_id"])
            if active < limit and ordered and ordered[0] == request_id:
                db.execute("UPDATE requests SET lease_until=?, granted_at=? WHERE request_id=?",
                           (now + self.lease_seconds, now, request_id))
                db.execute("UPDATE state SET value=? WHERE key='last_run'", (run_id,))
                queued = db.execute("SELECT count(*) FROM requests WHERE lease_until IS NULL").fetchone()[0]
                db.commit()
                return {"granted": True, "position": 0, "active": active + 1, "queued": queued,
                        "limit": limit, "reason": reason}
            position = ordered.index(request_id) + 1 if request_id in ordered else len(queue)
            db.commit()
            return {"granted": False, "position": position, "active": active, "queued": len(queue),
                    "limit": limit, "reason": reason}

    def release(self, request_id: str) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT run_id, memory_sample, lease_until FROM requests WHERE request_id=?", (request_id,)).fetchone()
            if row and row["lease_until"] is not None:
                run_active = db.execute(
                    "SELECT count(*) FROM requests WHERE run_id=? AND lease_until IS NOT NULL", (row["run_id"],)).fetchone()[0]
                sample = max(int(row["memory_sample"]), self.run_memory_reader(row["run_id"]) // max(1, run_active))
                if sample:
                    count = int(db.execute("SELECT value FROM state WHERE key='sample_count'").fetchone()[0])
                    average = int(db.execute("SELECT value FROM state WHERE key='avg_task_bytes'").fetchone()[0])
                    average = (average * count + sample) // (count + 1)
                    db.execute("UPDATE state SET value=? WHERE key='avg_task_bytes'", (str(average),))
                    db.execute("UPDATE state SET value=? WHERE key='sample_count'", (str(count + 1),))
            db.execute("DELETE FROM requests WHERE request_id=?", (request_id,))
            db.commit()

    def snapshot(self) -> dict:
        with self._connect() as db:
            now = time.time()
            db.execute("DELETE FROM requests WHERE last_seen < ?", (now - self.lease_seconds,))
            queued = db.execute("SELECT count(*) FROM requests WHERE lease_until IS NULL").fetchone()[0]
            active = db.execute("SELECT count(*) FROM requests WHERE lease_until IS NOT NULL").fetchone()[0]
            average = int(db.execute("SELECT value FROM state WHERE key='avg_task_bytes'").fetchone()[0])
            snapshot = self.snapshot_reader()
            limit, reason = calculate_limit(snapshot, active, average)
            head = db.execute("SELECT run_id FROM requests WHERE lease_until IS NULL ORDER BY queued_at LIMIT 1").fetchone()
            return {"active": active, "queued": queued, "limit": limit, "reason": reason,
                    "waiting_run": head["run_id"] if head else "", "average_task_bytes": average}

    def waiting_run_ids(self) -> set[str]:
        with self._connect() as db:
            cutoff = time.time() - self.lease_seconds
            rows = db.execute(
                "SELECT DISTINCT run_id FROM requests "
                "WHERE lease_until IS NULL AND last_seen >= ?",
                (cutoff,),
            ).fetchall()
        return {str(row["run_id"]) for row in rows}


_scheduler: WorkflowScheduler | None = None


def get_scheduler() -> WorkflowScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = WorkflowScheduler(Path(__file__).resolve().parents[1] / "data" / "workflow-scheduler.sqlite3")
    return _scheduler


def waiting_run_ids() -> set[str]:
    """Runs with at least one workflow call waiting for a shared slot."""
    return _scheduler.waiting_run_ids() if _scheduler is not None else set()
