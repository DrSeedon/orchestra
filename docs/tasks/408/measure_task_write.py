"""Measure the task-create write path without mutating the live Orchestra state.

The script takes SQLite backups and a private canonical Git copy, then invokes the
real MCP HTTP client, FastAPI route, canonical task store, runtime head writer, and
legacy SQLite writer.  Its only mutation target is a temporary directory below the
current worktree.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import shutil
import sqlite3
import tempfile
import time
import types
from pathlib import Path

import httpx
from fastapi import FastAPI


def _backup_sqlite(source: Path, target: Path) -> None:
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_db:
        with sqlite3.connect(target) as target_db:
            source_db.backup(target_db)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _legacy_refresh(owner) -> None:
    """Exact pre-#405 synchronous current-projection refresh."""
    from app.ia.projections import SQLiteProjectionBackend

    path = owner.paths["current_projection"]
    if path.is_file():
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                row = connection.execute(
                    "SELECT projection_head FROM projection_meta WHERE singleton=1"
                ).fetchone()
            if row is not None and str(row[0]) == owner.state["canonical_head"]:
                return
        except sqlite3.Error:
            pass
    backend = SQLiteProjectionBackend(path=path)
    retained = backend.replace_current_retaining_resources(
        records=owner._mutable_projection_records(),
        resource_records=owner._retained_evidence_records(),
        canonical_head=owner.state["canonical_head"],
    )
    if retained is not None:
        return
    backend.replace_current(
        records=owner._projection_records(),
        canonical_head=owner.state["canonical_head"],
    )


def _project_mapping(legacy_db: Path, state_root: Path) -> dict[str, str]:
    registry = json.loads((state_root / "scope-registry.json").read_text(encoding="utf-8"))
    by_scope = {
        str(item["scope"]).rstrip("/"): str(item["canonical_project_id"])
        for item in registry["entries"]
    }
    with sqlite3.connect(legacy_db) as connection:
        rows = connection.execute("SELECT id,scope FROM tm_projects ORDER BY id").fetchall()
    return {
        str(project_id): by_scope.get(str(scope or "").rstrip("/"), str(project_id))
        for project_id, scope in rows
    }


async def _run_once(source_state: Path, source_legacy: Path, refresh_mode: str) -> dict:
    from app import mcp_stdio
    from app import tm
    from app.ia.knowledge import KnowledgeService
    from app.ia.runtime import KnowledgeRuntime, RuntimeConfig, _RuntimeTaskStore
    from app.ia.task_store import TaskStore
    from app.routes.tm import router

    timings: dict[str, list[float]] = {}

    def record(name: str, elapsed: float) -> None:
        timings.setdefault(name, []).append(round(elapsed, 3))

    with tempfile.TemporaryDirectory(prefix=".task-write-bench-", dir=Path.cwd()) as raw_tmp:
        root = Path(raw_tmp)
        state_root = root / "knowledge-v1"
        canonical_root = state_root / "canonical"
        shutil.copytree(source_state / "canonical", canonical_root, copy_function=shutil.copy2)
        shutil.copy2(source_state / "runtime-state.json", state_root / "runtime-state.json")
        shutil.copy2(source_state / "scope-registry.json", state_root / "scope-registry.json")
        if (source_state / "bootstrap-topic-registry.json").is_file():
            shutil.copy2(
                source_state / "bootstrap-topic-registry.json",
                state_root / "bootstrap-topic-registry.json",
            )
        else:
            (state_root / "bootstrap-topic-registry.json").write_text(
                '{"registry_version":1,"topics":[]}\n', encoding="utf-8"
            )
        if (source_state / "debt").is_dir():
            shutil.copytree(source_state / "debt", state_root / "debt")
        _backup_sqlite(source_state / "task-current.db", state_root / "task-current.db")
        _backup_sqlite(source_state / "current.db", state_root / "current.db")
        legacy_db = root / "orchestra.db"
        _backup_sqlite(source_legacy, legacy_db)

        store = TaskStore(
            canonical_root=canonical_root / "tasks",
            projection_path=state_root / "task-current.db",
        )
        owner = object.__new__(KnowledgeRuntime)
        owner.config = RuntimeConfig(
            state_root=state_root,
            legacy_db_path=legacy_db,
            vector_db_path=root / "vec.db",
            scope_roots={},
            prompt_assembler=lambda _runtime, _role: "",
        )
        owner.paths = {
            "state_root": state_root,
            "canonical_root": canonical_root,
            "task_projection": state_root / "task-current.db",
            "current_projection": state_root / "current.db",
            "vector_projection": root / "vec.db",
        }
        owner.state = json.loads((state_root / "runtime-state.json").read_text(encoding="utf-8"))
        registry = json.loads(
            (state_root / "scope-registry.json").read_text(encoding="utf-8")
        )
        owner.scope_registry = {
            str(item["scope"]).rstrip("/"): copy.deepcopy(item)
            for item in registry["entries"]
        }
        owner._evidence_records_cache = None

        raw_create = store.task_create

        def timed_raw_create(**kwargs):
            started = time.perf_counter()
            try:
                return raw_create(**kwargs)
            finally:
                record("canonical_task_store_ms", _elapsed_ms(started))

        store.task_create = timed_raw_create

        wrapped = _RuntimeTaskStore(
            store=store,
            legacy_to_canonical=_project_mapping(legacy_db, state_root),
            debt_writer=owner._record_debt,
            head_writer=lambda _head: None,
        )
        owner.task_store = wrapped
        owner.knowledge_service = KnowledgeService(
            canonical_root=canonical_root / "knowledge",
            registry_path=state_root / "bootstrap-topic-registry.json",
            task_store=wrapped,
        )

        # A post-restart current runtime builds the resource receipts once before it
        # accepts task mutations.  The measured call must not charge that startup-only
        # migration to every subsequent task_create.
        startup_prepare_ms = None
        if refresh_mode == "current":
            started = time.perf_counter()
            owner._refresh_current_projection()
            startup_prepare_ms = _elapsed_ms(started)

        for method_name in ("_save_state", "_commit_canonical", "_refresh_current_projection"):
            original = getattr(owner, method_name)
            if method_name == "_refresh_current_projection" and refresh_mode == "baseline":
                original = types.MethodType(lambda self: _legacy_refresh(self), owner)

            def timed_method(*args, __name=method_name, __original=original, **kwargs):
                started = time.perf_counter()
                try:
                    return __original(*args, **kwargs)
                finally:
                    record(f"runtime{__name}_ms", _elapsed_ms(started))

            setattr(owner, method_name, timed_method)

        def timed_head_writer(head: str) -> None:
            started = time.perf_counter()
            try:
                owner._record_task_head(head)
            finally:
                record("runtime_head_writer_ms", _elapsed_ms(started))

        wrapped._head_writer = timed_head_writer

        original_conn = tm._conn
        original_legacy_create = tm._legacy_api_create_task

        def copied_conn():
            connection = sqlite3.connect(legacy_db)
            connection.row_factory = sqlite3.Row
            return connection

        def timed_legacy_create(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original_legacy_create(*args, **kwargs)
            finally:
                record("legacy_sqlite_ms", _elapsed_ms(started))

        tm._conn = copied_conn
        tm._legacy_api_create_task = timed_legacy_create

        app = FastAPI()

        @app.middleware("http")
        async def measure_http(request, call_next):
            started = time.perf_counter()
            response = await call_next(request)
            record("http_route_ms", _elapsed_ms(started))
            return response

        app.include_router(router)
        real_async_client = mcp_stdio.httpx.AsyncClient

        class LocalAsyncClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.ASGITransport(app=app)
                kwargs["base_url"] = "http://task-write-bench"
                super().__init__(*args, **kwargs)

        load_before = os.getloadavg()
        try:
            with tm.ia_process_task_store_mode(store=wrapped, mode="canonical"):
                mcp_stdio.httpx.AsyncClient = LocalAsyncClient
                started = time.perf_counter()
                response = await mcp_stdio._api(
                    "POST",
                    "/api/tm/tasks",
                    json={
                        "title": f"#405 isolated {refresh_mode} measurement",
                        "project": "orchestra",
                        "price": 0,
                        "description": "д" * 3500,
                        "assignee": "",
                        "status": "new",
                        "scope": "",
                        "priority": 2,
                        "acceptance_command": "",
                    },
                )
                mcp_total_ms = _elapsed_ms(started)
        finally:
            mcp_stdio.httpx.AsyncClient = real_async_client
            tm._legacy_api_create_task = original_legacy_create
            tm._conn = original_conn

        return {
            "refresh_mode": refresh_mode,
            "description_chars": 3500,
            "source_task_rows": len(store._states()) - 1,
            "source_current_db_bytes": (source_state / "current.db").stat().st_size,
            "loadavg_before": [round(value, 3) for value in load_before],
            "loadavg_after": [round(value, 3) for value in os.getloadavg()],
            "mcp_total_ms": mcp_total_ms,
            "mcp_http_overhead_ms": round(mcp_total_ms - timings["http_route_ms"][-1], 3),
            "startup_prepare_ms": startup_prepare_ms,
            "response_par": response.get("par") if isinstance(response, dict) else None,
            "timings": {
                name: {
                    "count": len(values),
                    "total_ms": round(sum(values), 3),
                    "max_ms": round(max(values), 3),
                }
                for name, values in sorted(timings.items())
            },
        }


def _run_deleted_task_projection(source_state: Path) -> dict:
    from app.ia.runtime import _RuntimeTaskStore
    from app.ia.task_store import TaskStore

    with tempfile.TemporaryDirectory(prefix=".task-index-rebuild-", dir=Path.cwd()) as raw_tmp:
        root = Path(raw_tmp)
        canonical = root / "tasks"
        shutil.copytree(source_state / "canonical" / "tasks", canonical)
        projection = root / "task-current.db"
        store = TaskStore(canonical_root=canonical, projection_path=projection)
        states = store._states()
        state = next(
            (item for item in states.values() if item.get("git_commit_refs")),
            next(iter(states.values())),
        )
        commits = list(state.get("git_commit_refs") or [{
            "hash": "d" * 40,
            "message": "#405: deleted projection probe",
        }])
        facade = _RuntimeTaskStore(
            store=store,
            legacy_to_canonical={state["project_id"]: state["project_id"]},
            debt_writer=lambda _debt: None,
            head_writer=lambda _head: None,
        )
        started = time.perf_counter()
        result = facade.link_commits_to_task(
            str(state["display_number"]), commits, state["project_id"],
        )
        elapsed_ms = _elapsed_ms(started)
        with sqlite3.connect(projection) as connection:
            projection_rows = connection.execute(
                "SELECT count(*) FROM ia_task_projection"
            ).fetchone()[0]
        return {
            "canonical_json_files": sum(1 for _ in canonical.rglob("*.json")),
            "canonical_task_states": len(states),
            "projection_existed_before": False,
            "projection_exists_after": projection.is_file(),
            "projection_rows_after": int(projection_rows),
            "post_commit_link_ok": result.get("ok"),
            "post_commit_added": result.get("added"),
            "canonical_head": facade.canonical_head,
            "projection_head": facade.projection_head,
            "elapsed_ms": elapsed_ms,
            "loadavg": [round(value, 3) for value in os.getloadavg()],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-mode", choices=("baseline", "current"))
    parser.add_argument("--sequence", default="")
    parser.add_argument("--projection-delete-probe", action="store_true")
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path.home() / ".local/state/orchestra/knowledge-v1",
    )
    parser.add_argument(
        "--legacy-db",
        type=Path,
        default=Path("/mnt/data/Projects/Python/orchestra/data/orchestra.db"),
    )
    args = parser.parse_args()
    if args.projection_delete_probe:
        print(json.dumps(
            _run_deleted_task_projection(args.state_root),
            ensure_ascii=False,
            sort_keys=True,
        ))
        return
    modes = [mode.strip() for mode in args.sequence.split(",") if mode.strip()]
    if modes:
        if any(mode not in {"baseline", "current"} for mode in modes):
            parser.error("--sequence accepts only baseline,current")
        results = [
            asyncio.run(_run_once(args.state_root, args.legacy_db, mode))
            for mode in modes
        ]
        result = {
            "sequence": [
                {
                    "mode": item["refresh_mode"],
                    "loadavg_before": item["loadavg_before"],
                    "loadavg_after": item["loadavg_after"],
                    "mcp_total_ms": item["mcp_total_ms"],
                    "startup_prepare_ms": item["startup_prepare_ms"],
                    "canonical_task_store_ms": item["timings"]["canonical_task_store_ms"]["total_ms"],
                    "canonical_git_ms": item["timings"]["runtime_commit_canonical_ms"]["total_ms"],
                    "current_projection_ms": item["timings"]["runtime_refresh_current_projection_ms"]["total_ms"],
                    "legacy_sqlite_ms": item["timings"]["legacy_sqlite_ms"]["total_ms"],
                    "mcp_http_overhead_ms": item["mcp_http_overhead_ms"],
                }
                for item in results
            ]
        }
    else:
        if args.refresh_mode is None:
            parser.error("one of --refresh-mode or --sequence is required")
        result = asyncio.run(_run_once(args.state_root, args.legacy_db, args.refresh_mode))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
