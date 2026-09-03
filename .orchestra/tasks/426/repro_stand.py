"""Isolated operation-time reproduction for task #426.

The canonical snapshot is deliberately taken before legacy task #399 is created.
This recreates the store ordering measured for the three failed merge operations.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path


WORKTREE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKTREE_ROOT))


def _production_repo() -> Path:
    common_dir = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            text=True,
        ).strip()
    )
    return common_dir.parent


def _session_count(path: Path) -> int:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return int(connection.execute("SELECT count(*) FROM sessions").fetchone()[0])
    finally:
        connection.close()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts or not path.is_file():
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    production_db = _production_repo() / "data" / "orchestra.db"
    production_canonical = Path.home() / ".local/state/orchestra/knowledge-v1/canonical"
    production_before = _session_count(production_db)
    canonical_before = _tree_digest(production_canonical)

    with tempfile.TemporaryDirectory(prefix="orchestra-426-") as raw_root:
        root = Path(raw_root)
        isolated_db = root / "orchestra.db"
        canonical_root = root / "canonical" / "tasks"
        projection_path = root / "task-current.db"
        os.environ["ORCHESTRA_DB_PATH"] = str(isolated_db)

        from app import db, tm
        import app
        from app.ia.runtime import _RuntimeTaskStore
        from app.routes.sessions import apply_merge_finalization

        if not Path(app.__file__).resolve().is_relative_to(WORKTREE_ROOT):
            raise AssertionError(f"worktree import failed: {app.__file__}")
        if db.DB_PATH != isolated_db:
            raise AssertionError(f"DB isolation failed: {db.DB_PATH} != {isolated_db}")
        db.init_db()
        with tm._conn() as connection:
            tm.ensure_project(connection, "orchestra", scope=str(_production_repo()))
            tm.create_task(
                connection,
                "orchestra",
                "Canonical predecessor",
                par_number=398,
                status="done",
            )

        # Freeze the candidate owner before #399 exists, matching the failed operations.
        with tm.ia_task_store_mode(
            mode="canonical",
            canonical_root=canonical_root,
            projection_path=projection_path,
            cutoff="2026-08-26T08:40:00+00:00",
            source_head="operation-time-426",
        ) as raw_store:
            assert raw_store is not None
        if raw_store.canonical_root.resolve() != canonical_root.resolve():
            raise AssertionError("canonical root isolation failed")
        if raw_store.projection_path.resolve() != projection_path.resolve():
            raise AssertionError("projection path isolation failed")
        predecessor = raw_store.task_get("398", project="orchestra")
        try:
            raw_store.task_get("399", project="orchestra")
        except ValueError as error:
            canonical_399_missing = str(error) == "399 not found"
        else:
            canonical_399_missing = False
        if predecessor["par"] != "398" or not canonical_399_missing:
            raise AssertionError("canonical reproduction preconditions failed")

        with tm._conn() as connection:
            task = tm.create_task(
                connection,
                "orchestra",
                "Legacy-only merge task",
                par_number=399,
                status="in_progress",
            )
            legacy_399 = tm.get_task_by_par(connection, 399, "orchestra")
        if legacy_399 is None or legacy_399["id"] != task["id"]:
            raise AssertionError("legacy reproduction precondition failed")

        store = _RuntimeTaskStore(
            store=raw_store,
            legacy_to_canonical={"orchestra": "orchestra"},
            debt_writer=lambda _debt: None,
            head_writer=lambda _head: None,
        )
        payload = {
            "project_id": "orchestra",
            "task": {
                "project_id": "orchestra",
                "task_id": task["id"],
                "par_number": 399,
            },
            "commits": {"399": [{"hash": "426-repro-commit"}]},
            "outcome": "complete",
            "reservation_id": "operation-426-repro",
            "session_id": "worker-426-repro",
            "operation_id": "",
        }

        print(f"ISOLATED_DB={db.DB_PATH}")
        print(f"ISOLATED_CANONICAL={raw_store.canonical_root}")
        print(f"ISOLATED_PROJECTION={raw_store.projection_path}")
        print(f"APP_ROOT={Path(app.__file__).resolve().parent}")
        print(f"PRECONDITION_CANONICAL_398={predecessor['par']}")
        print(f"PRECONDITION_CANONICAL_399_MISSING={canonical_399_missing}")
        print(f"PRECONDITION_LEGACY_399={legacy_399['par_number']}")
        print(f"IA_CONTEXT_BEFORE={tm._ia_context()}")
        try:
            with tm.ia_process_task_store_mode(store=store, mode="canonical"):
                print(f"IA_CONTEXT_DURING={tm._ia_context()}")
                asyncio.run(apply_merge_finalization(payload))
        except ValueError as error:
            print(f"REPRO_EXCEPTION={type(error).__name__}: {error}")
            frames = traceback.extract_tb(error.__traceback__)
            throw_frame = frames[-1]
            expected_file = WORKTREE_ROOT / "app" / "ia" / "task_store.py"
            throw_verified = (
                Path(throw_frame.filename).resolve() == expected_file.resolve()
                and throw_frame.lineno == 583
                and throw_frame.name == "_find_state"
            )
            print(
                "THROW_FRAME="
                f"{throw_frame.filename}:{throw_frame.lineno}:{throw_frame.name}"
            )
            print(f"THROW_FRAME_VERIFIED={throw_verified}")
            if not throw_verified:
                raise AssertionError("unexpected ValueError throw frame") from error
            print("REPRO_TRACEBACK_BEGIN")
            print(
                "".join(
                    traceback.format_exception(type(error), error, error.__traceback__)
                ).rstrip()
            )
            print("REPRO_TRACEBACK_END")
            if str(error) != "399 not found":
                raise
        else:
            raise AssertionError("expected ValueError: 399 not found")

        # Positive control: the same process-global path succeeds when both owners contain #399.
        healthy_canonical = root / "healthy-canonical" / "tasks"
        healthy_projection = root / "healthy-task-current.db"
        with tm.ia_task_store_mode(
            mode="canonical",
            canonical_root=healthy_canonical,
            projection_path=healthy_projection,
            cutoff="2026-08-26T09:10:00+00:00",
            source_head="healthy-control-426",
        ) as healthy_raw_store:
            assert healthy_raw_store is not None
        healthy_store = _RuntimeTaskStore(
            store=healthy_raw_store,
            legacy_to_canonical={"orchestra": "orchestra"},
            debt_writer=lambda _debt: None,
            head_writer=lambda _head: None,
        )
        healthy_payload = {
            **payload,
            "commits": {"399": [{"hash": "426-healthy-commit"}]},
        }
        with tm.ia_process_task_store_mode(store=healthy_store, mode="canonical"):
            healthy_result = asyncio.run(apply_merge_finalization(healthy_payload))
        healthy_canonical_state = healthy_raw_store.task_get("399", project="orchestra")
        with tm._conn() as connection:
            healthy_legacy_state = tm.get_task_by_par(connection, 399, "orchestra")
        healthy_pass = (
            healthy_result["linked_tasks"]["399"]["ok"] is True
            and healthy_canonical_state["status"] == "done"
            and healthy_legacy_state is not None
            and healthy_legacy_state["status"] == "done"
        )
        print(f"HEALTHY_CONTROL={healthy_pass}")
        if not healthy_pass:
            raise AssertionError("dual-owner finalization control failed")

    production_after = _session_count(production_db)
    canonical_after = _tree_digest(production_canonical)
    print(f"PROD_SESSIONS_BEFORE={production_before}")
    print(f"PROD_SESSIONS_AFTER={production_after}")
    print(f"PROD_SESSIONS_UNCHANGED={production_before == production_after}")
    print(f"PROD_CANONICAL_SHA256_BEFORE={canonical_before}")
    print(f"PROD_CANONICAL_SHA256_AFTER={canonical_after}")
    print(f"PROD_CANONICAL_UNCHANGED={canonical_before == canonical_after}")
    if production_before != production_after:
        raise AssertionError("production sessions count changed during the stand")
    if canonical_before != canonical_after:
        raise AssertionError("production canonical tree changed during the stand")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
