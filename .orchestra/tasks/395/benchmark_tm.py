"""Freeze and benchmark the #395 TM hot path without touching live state.

The frozen SQLite inputs are always created with ``sqlite3.Connection.backup``.
Every measured iteration runs in a fresh Python subprocess against a fresh clone
of that frozen input.  Clone setup is outside the measured intervals.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median


SQLITE_NAMES = ("current.db", "task-current.db")
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))


def _backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


def _drop_page_cache(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(descriptor)


def _heads(state_root: Path) -> dict[str, object]:
    from app.ia.task_store import TaskStore

    task_store = TaskStore(
        canonical_root=state_root / "canonical" / "tasks",
        projection_path=state_root / "task-current.db",
    )
    runtime_state = json.loads((state_root / "runtime-state.json").read_text())
    with sqlite3.connect(f"file:{state_root / 'current.db'}?mode=ro", uri=True) as connection:
        current_head = connection.execute(
            "SELECT projection_head FROM projection_meta WHERE singleton=1"
        ).fetchone()[0]
        current_rows = connection.execute("SELECT count(*) FROM current_records").fetchone()[0]
    return {
        "runtime_canonical_head": runtime_state["canonical_head"],
        "runtime_projection_head": runtime_state["projection_head"],
        "task_canonical_head": task_store.canonical_head,
        "task_projection_head": task_store.projection_head,
        "task_states": len(task_store._states()),
        "current_projection_head": current_head,
        "current_rows": current_rows,
    }


def _legacy_watermark(database: Path) -> dict[str, object]:
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        task_count, max_id = connection.execute(
            "SELECT count(*), COALESCE(max(id), 0) FROM tm_tasks"
        ).fetchone()
    return {"legacy_task_count": task_count, "legacy_task_max_id": max_id}


def freeze(live_database: Path, live_state: Path, destination: Path) -> None:
    if destination.exists():
        raise SystemExit(f"refusing to overwrite frozen fixture: {destination}")
    destination.mkdir(parents=True)
    before = {**_heads(live_state), **_legacy_watermark(live_database)}

    _backup(live_database, destination / "orchestra.db")
    frozen_state = destination / "knowledge-v1"
    shutil.copytree(
        live_state,
        frozen_state,
        ignore=shutil.ignore_patterns("*.db", "*.db-wal", "*.db-shm"),
    )
    for name in SQLITE_NAMES:
        _backup(live_state / name, frozen_state / name)

    after = {**_heads(live_state), **_legacy_watermark(live_database)}
    frozen = {**_heads(frozen_state), **_legacy_watermark(destination / "orchestra.db")}
    if before != after or frozen != after:
        raise SystemExit(
            "live task/projection heads changed while freezing; fixture is excluded\n"
            + json.dumps({"before": before, "after": after, "frozen": frozen}, indent=2)
        )
    manifest = {
        "backup_method": "sqlite3.Connection.backup from mode=ro sources",
        "live_database": str(live_database),
        "live_state": str(live_state),
        "watermark": frozen,
        "files": {
            "orchestra.db": (destination / "orchestra.db").stat().st_size,
            **{
                f"knowledge-v1/{name}": (frozen_state / name).stat().st_size
                for name in SQLITE_NAMES
            },
        },
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


def _clone_fixture(
    source: Path,
    destination: Path,
    startup_receipts: str = "preserved",
    startup_page_cache: str = "preserved",
) -> None:
    _backup(source / "orchestra.db", destination / "orchestra.db")
    shutil.copytree(
        source / "knowledge-v1",
        destination / "knowledge-v1",
        ignore=shutil.ignore_patterns("*.db", "*.db-wal", "*.db-shm"),
    )
    for name in SQLITE_NAMES:
        _backup(source / "knowledge-v1" / name, destination / "knowledge-v1" / name)
    if startup_receipts == "cleared":
        with sqlite3.connect(destination / "knowledge-v1" / "current.db") as connection:
            connection.execute(
                "UPDATE projection_meta SET "
                "resource_manifest_sha256='',resource_rows_sha256='' WHERE singleton=1"
            )
    if startup_page_cache == "dropped":
        _drop_page_cache(destination / "knowledge-v1" / "current.db")


def _once(root: Path, project: str) -> dict[str, object]:
    os.environ["ORCHESTRA_DB_PATH"] = str(root / "orchestra.db")
    os.environ["RAG_DB_PATH"] = str(root / "vec.db")
    os.environ.pop("STATE_DIRECTORY", None)
    os.environ.pop("XDG_STATE_HOME", None)

    from app import tm
    from app.ia.projections import SQLiteProjectionBackend
    from app.ia.runtime import (
        KnowledgeRuntime,
        _RuntimeTaskStore,
        knowledge_runtime_mode,
        production_runtime_config,
    )
    from app.ia.task_store import TaskStore

    writer_entered = threading.Event()
    measure_rebuilds = threading.Event()
    phase = "startup"
    task_projection_rebuild_seconds: list[float] = []
    current_projection_rebuild_seconds: list[tuple[str, float]] = []
    current_projection_refresh_seconds: list[tuple[str, float]] = []
    current_projection_seal_seconds: list[tuple[str, float]] = []
    current_projection_retain_seconds: list[tuple[str, float]] = []
    targeted_current_update_seconds: list[tuple[str, float]] = []
    original_task_create = _RuntimeTaskStore.task_create
    original_import_scope_evidence = KnowledgeRuntime._import_scope_evidence
    original_current_refresh = KnowledgeRuntime._refresh_current_projection
    original_task_rebuild = TaskStore._rebuild_projection
    original_current_rebuild = SQLiteProjectionBackend.replace_current
    original_current_seal = SQLiteProjectionBackend.seal_current_resources
    original_current_retain = SQLiteProjectionBackend.replace_current_retaining_resources
    original_targeted_current_update = SQLiteProjectionBackend.update_current_records

    def instrumented_task_create(self, *args, **kwargs):
        writer_entered.set()
        return original_task_create(self, *args, **kwargs)

    def timed_task_rebuild(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_task_rebuild(self, *args, **kwargs)
        finally:
            if measure_rebuilds.is_set():
                task_projection_rebuild_seconds.append(time.perf_counter() - started)

    def timed_current_rebuild(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_current_rebuild(self, *args, **kwargs)
        finally:
            current_projection_rebuild_seconds.append((phase, time.perf_counter() - started))

    def timed_current_refresh(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_current_refresh(self, *args, **kwargs)
        finally:
            current_projection_refresh_seconds.append((phase, time.perf_counter() - started))

    def timed_current_seal(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_current_seal(self, *args, **kwargs)
        finally:
            current_projection_seal_seconds.append((phase, time.perf_counter() - started))

    def timed_current_retain(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_current_retain(self, *args, **kwargs)
        finally:
            current_projection_retain_seconds.append((phase, time.perf_counter() - started))

    def timed_targeted_current_update(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_targeted_current_update(self, *args, **kwargs)
        finally:
            targeted_current_update_seconds.append((phase, time.perf_counter() - started))

    _RuntimeTaskStore.task_create = instrumented_task_create
    KnowledgeRuntime._refresh_current_projection = timed_current_refresh
    TaskStore._rebuild_projection = timed_task_rebuild
    SQLiteProjectionBackend.replace_current = timed_current_rebuild
    SQLiteProjectionBackend.seal_current_resources = timed_current_seal
    SQLiteProjectionBackend.replace_current_retaining_resources = timed_current_retain
    SQLiteProjectionBackend.update_current_records = timed_targeted_current_update
    # The frozen projection already contains its evidence generation.  Re-reading mutable
    # live Git scopes during clone startup would make nominally identical iterations differ.
    KnowledgeRuntime._import_scope_evidence = lambda self: None
    try:
        loadavg_before_startup = list(os.getloadavg())
        startup_started = time.perf_counter()
        with knowledge_runtime_mode(production_runtime_config()) as runtime_owner:
            startup_runtime_seconds = time.perf_counter() - startup_started
            loadavg_after_startup = list(os.getloadavg())
            with tm._conn() as connection:
                resolved = tm.resolve_project_selector(connection, project)
            if resolved is None:
                raise RuntimeError(f"benchmark project is not registered: {project}")
            project_id = str(resolved["id"])
            current_projection = root / "knowledge-v1" / "current.db"
            with sqlite3.connect(current_projection) as connection:
                current_rows = connection.execute(
                    "SELECT count(*) FROM current_records"
                ).fetchone()[0]
            task_states = len(runtime_owner.task_store.states())
            started = time.perf_counter()
            idle = tm.api_list_tasks(project=project_id)
            idle_list_seconds = time.perf_counter() - started

            title = "#395 isolated latency probe"
            with ThreadPoolExecutor(max_workers=1) as executor:
                phase = "create"
                measure_rebuilds.set()
                loadavg_before_create = list(os.getloadavg())
                create_started = time.perf_counter()
                future = executor.submit(
                    tm.api_create_task,
                    project_id,
                    title,
                    0,
                    "isolated benchmark; never written to live state",
                )
                deadline_observation: dict[str, object] = {}

                def observe_deadline() -> None:
                    deadline_observation.update(
                        observed_seconds=time.perf_counter() - create_started,
                        create_done=future.done(),
                    )
                    try:
                        with sqlite3.connect(root / "orchestra.db", timeout=0) as connection:
                            exact_title_count = connection.execute(
                                "SELECT count(*) FROM tm_tasks WHERE project_id=? AND title=?",
                                (project_id, title),
                            ).fetchone()[0]
                        deadline_observation["legacy_exact_title_count"] = exact_title_count
                    except sqlite3.OperationalError as error:
                        deadline_observation["legacy_read_error"] = (
                            f"{type(error).__name__}: {error}"
                        )

                deadline_timer = threading.Timer(30, observe_deadline)
                deadline_timer.start()
                if not writer_entered.wait(timeout=60):
                    if future.done():
                        future.result()
                    frames = sys._current_frames()
                    stacks = "\n\n".join(
                        f"thread={thread.name} ident={thread.ident}\n"
                        + "".join(traceback.format_stack(frames[thread.ident]))
                        for thread in threading.enumerate()
                        if thread.ident in frames
                    )
                    raise RuntimeError(
                        "task_create did not enter _RuntimeTaskStore.task_create\n" + stacks
                    )
                list_started = time.perf_counter()
                contended = tm.api_list_tasks(project=project_id)
                contended_list_seconds = time.perf_counter() - list_started
                created = future.result(timeout=180)
                create_seconds = time.perf_counter() - create_started
                loadavg_after_create = list(os.getloadavg())
                deadline_timer.cancel()
                deadline_timer.join(timeout=5)
    finally:
        _RuntimeTaskStore.task_create = original_task_create
        KnowledgeRuntime._refresh_current_projection = original_current_refresh
        TaskStore._rebuild_projection = original_task_rebuild
        SQLiteProjectionBackend.replace_current = original_current_rebuild
        SQLiteProjectionBackend.seal_current_resources = original_current_seal
        SQLiteProjectionBackend.replace_current_retaining_resources = original_current_retain
        SQLiteProjectionBackend.update_current_records = original_targeted_current_update
        KnowledgeRuntime._import_scope_evidence = original_import_scope_evidence

    return {
        "client_deadline_seconds": 30,
        "startup_runtime_seconds": startup_runtime_seconds,
        "startup_current_projection_refresh_calls": sum(
            measured_phase == "startup"
            for measured_phase, _seconds in current_projection_refresh_seconds
        ),
        "startup_current_projection_refresh_seconds": sum(
            seconds
            for measured_phase, seconds in current_projection_refresh_seconds
            if measured_phase == "startup"
        ),
        "startup_current_projection_refresh_samples_seconds": [
            seconds
            for measured_phase, seconds in current_projection_refresh_seconds
            if measured_phase == "startup"
        ],
        "startup_current_projection_seal_seconds": sum(
            seconds
            for measured_phase, seconds in current_projection_seal_seconds
            if measured_phase == "startup"
        ),
        "startup_current_projection_retain_seconds": sum(
            seconds
            for measured_phase, seconds in current_projection_retain_seconds
            if measured_phase == "startup"
        ),
        "startup_current_projection_rebuild_seconds": sum(
            seconds
            for measured_phase, seconds in current_projection_rebuild_seconds
            if measured_phase == "startup"
        ),
        "create_seconds": create_seconds,
        "create_exceeded_client_deadline": create_seconds > 30,
        "contended_task_list_seconds": contended_list_seconds,
        "idle_task_list_seconds": idle_list_seconds,
        "created_par": created["par"],
        "created_task_id": created.get("task_id") or created.get("stable_id"),
        "idle_count": idle["count"],
        "contended_count": contended["count"],
        "task_count_delta_after_create": contended["count"] - idle["count"],
        "deadline_observed": bool(deadline_observation),
        "create_done_at_deadline": deadline_observation.get("create_done"),
        "deadline_observed_seconds": deadline_observation.get("observed_seconds"),
        "legacy_exact_title_count_at_deadline": deadline_observation.get(
            "legacy_exact_title_count"
        ),
        "legacy_read_error_at_deadline": deadline_observation.get("legacy_read_error"),
        "task_projection_rebuild_calls": len(task_projection_rebuild_seconds),
        "task_projection_rebuild_seconds": sum(task_projection_rebuild_seconds),
        "current_projection_rebuild_calls": sum(
            measured_phase == "create"
            for measured_phase, _seconds in current_projection_rebuild_seconds
        ),
        "current_projection_rebuild_seconds": sum(
            seconds
            for measured_phase, seconds in current_projection_rebuild_seconds
            if measured_phase == "create"
        ),
        "create_current_projection_refresh_calls": sum(
            measured_phase == "create"
            for measured_phase, _seconds in current_projection_refresh_seconds
        ),
        "create_current_projection_refresh_seconds": sum(
            seconds
            for measured_phase, seconds in current_projection_refresh_seconds
            if measured_phase == "create"
        ),
        "create_current_projection_refresh_samples_seconds": [
            seconds
            for measured_phase, seconds in current_projection_refresh_seconds
            if measured_phase == "create"
        ],
        "create_current_projection_seal_seconds": sum(
            seconds
            for measured_phase, seconds in current_projection_seal_seconds
            if measured_phase == "create"
        ),
        "create_current_projection_retain_seconds": sum(
            seconds
            for measured_phase, seconds in current_projection_retain_seconds
            if measured_phase == "create"
        ),
        "create_targeted_current_update_calls": sum(
            measured_phase == "create"
            for measured_phase, _seconds in targeted_current_update_seconds
        ),
        "create_targeted_current_update_seconds": sum(
            seconds
            for measured_phase, seconds in targeted_current_update_seconds
            if measured_phase == "create"
        ),
        "current_projection_bytes": current_projection.stat().st_size,
        "current_projection_rows": current_rows,
        "task_state_rows": task_states,
        "loadavg_before_startup": loadavg_before_startup,
        "loadavg_after_startup": loadavg_after_startup,
        "loadavg_before_create": loadavg_before_create,
        "loadavg_after_create": loadavg_after_create,
    }


def run(
    source: Path,
    iterations: int,
    project: str,
    output: Path | None,
    startup_receipts: str,
    startup_page_cache: str,
) -> None:
    rows = []
    raw_lines = []
    base = source.parent / "runs"
    base.mkdir(parents=True, exist_ok=True)
    for iteration in range(1, iterations + 1):
        root = Path(tempfile.mkdtemp(prefix=f"iteration-{iteration}-", dir=base))
        try:
            _clone_fixture(source, root, startup_receipts, startup_page_cache)
            command = [sys.executable, __file__, "_once", "--root", str(root), "--project", project]
            result = subprocess.run(command, check=False, text=True, capture_output=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"benchmark child exit {result.returncode}\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )
            row = json.loads(result.stdout)
            row["iteration"] = iteration
            row["startup_receipts"] = startup_receipts
            row["startup_page_cache"] = startup_page_cache
            rows.append(row)
            line = json.dumps(row, ensure_ascii=False, sort_keys=True)
            raw_lines.append(line)
            print(line)
        finally:
            shutil.rmtree(root)
    summary = {
        "iterations": iterations,
        "startup_receipts": startup_receipts,
        "startup_page_cache": startup_page_cache,
        "median_startup_runtime_seconds": median(
            row["startup_runtime_seconds"] for row in rows
        ),
        "median_startup_current_projection_refresh_seconds": median(
            row["startup_current_projection_refresh_seconds"] for row in rows
        ),
        "median_create_seconds": median(row["create_seconds"] for row in rows),
        "median_create_current_projection_refresh_seconds": median(
            row["create_current_projection_refresh_seconds"] for row in rows
        ),
        "median_contended_task_list_seconds": median(
            row["contended_task_list_seconds"] for row in rows
        ),
        "median_idle_task_list_seconds": median(row["idle_task_list_seconds"] for row in rows),
        "creates_exceeding_30s": sum(row["create_exceeded_client_deadline"] for row in rows),
        "deadlines_observed": sum(row["deadline_observed"] for row in rows),
        "creates_incomplete_at_observed_deadline": sum(
            row["deadline_observed"] and row["create_done_at_deadline"] is False
            for row in rows
        ),
        "tasks_visible_at_observed_deadline": sum(
            row["deadline_observed"] and row["legacy_exact_title_count_at_deadline"] == 1
            for row in rows
        ),
    }
    raw_lines.append(json.dumps({"summary": summary}, ensure_ascii=False, sort_keys=True))
    print(raw_lines[-1])
    if output is None:
        revision = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        output = Path(__file__).with_name(f"benchmark-{revision}.raw.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(raw_lines) + "\n")
    print(json.dumps({"output": str(output)}, ensure_ascii=False, sort_keys=True))


def main() -> None:
    os.chdir(REPO_ROOT)
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--live-database", type=Path, required=True)
    freeze_parser.add_argument("--live-state", type=Path, required=True)
    freeze_parser.add_argument("--destination", type=Path, required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--source", type=Path, required=True)
    run_parser.add_argument("--iterations", type=int, default=3)
    run_parser.add_argument("--project", default="/home/kesha/orchestra")
    run_parser.add_argument("--output", type=Path)
    run_parser.add_argument(
        "--startup-receipts", choices=("preserved", "cleared"), default="preserved"
    )
    run_parser.add_argument(
        "--startup-page-cache", choices=("preserved", "dropped"), default="preserved"
    )
    once_parser = subparsers.add_parser("_once")
    once_parser.add_argument("--root", type=Path, required=True)
    once_parser.add_argument("--project", required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.live_database.resolve(), args.live_state.resolve(), args.destination.resolve())
    elif args.command == "run":
        run(
            args.source.resolve(),
            args.iterations,
            args.project,
            args.output.resolve() if args.output else None,
            args.startup_receipts,
            args.startup_page_cache,
        )
    else:
        print(json.dumps(_once(args.root.resolve(), args.project), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
