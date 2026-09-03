"""Read-only proof of canonical state at the three failed merge timestamps."""

from __future__ import annotations

import io
import json
import sqlite3
import subprocess
import tarfile
from datetime import datetime, timedelta
from pathlib import Path


OPERATION_IDS = {
    399: "4455dca2-5f68-4516-88f7-f654a15eff31",
    400: "43fa5be4-c26a-473f-af3a-083c2ed75710",
    410: "7f7bf89f-6ad0-4c85-a8fc-184698e0a195",
}


def _production_repo() -> Path:
    common_dir = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            text=True,
        ).strip()
    )
    return common_dir.parent


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _states_at(repo: Path, revision: str) -> list[dict]:
    archive = subprocess.check_output(
        [
            "git",
            "-C",
            str(repo),
            "archive",
            "--format=tar",
            revision,
            "tasks/projects/orchestra/tasks",
        ]
    )
    states = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        for member in bundle.getmembers():
            if not member.isfile() or not member.name.endswith("/state.json"):
                continue
            source = bundle.extractfile(member)
            assert source is not None
            states.append(json.loads(source.read()))
    return states


def _first_current_event(canonical_repo: Path, number: int) -> dict:
    matches = []
    for path in (canonical_repo / "tasks/projects/orchestra/tasks").rglob("events/*.json"):
        event = json.loads(path.read_text(encoding="utf-8"))
        if event.get("project_id") == "orchestra" and event.get("display_number") == number:
            matches.append(event)
    if not matches:
        raise AssertionError(f"current canonical event for #{number} is absent")
    return min(matches, key=lambda event: str(event["occurred_at"]))


def main() -> int:
    production_db = _production_repo() / "data/orchestra.db"
    canonical_repo = Path.home() / ".local/state/orchestra/knowledge-v1/canonical"
    connection = sqlite3.connect(f"file:{production_db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    sessions_before = int(connection.execute("SELECT count(*) FROM sessions").fetchone()[0])
    try:
        for number, operation_id in OPERATION_IDS.items():
            row = connection.execute(
                "SELECT operation_id,created_at,commit_point,state,result_json "
                "FROM merge_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise AssertionError(f"operation {operation_id} is absent")
            result = json.loads(row["result_json"])
            error = result.get("error") or {}
            expected = f"merge finalization failed: ValueError: {number} not found"
            if error.get("message") != expected:
                raise AssertionError(f"unexpected operation error: {error}")
            failure_window_end = (
                datetime.fromisoformat(row["created_at"]) + timedelta(minutes=2)
            ).isoformat()
            failure_logs = [
                log
                for log in connection.execute(
                    "SELECT id,session_id,ts,content FROM logs "
                    "WHERE type='tool_result' AND ts>=? AND ts<=? ORDER BY ts",
                    (row["created_at"], failure_window_end),
                ).fetchall()
                if operation_id in log["content"] and expected in log["content"]
            ]
            if not failure_logs:
                raise AssertionError(
                    f"initial failure log for #{number} is absent"
                )
            failure_log = failure_logs[0]
            observations = [
                {"id": log["id"], "ts": log["ts"]}
                for log in connection.execute(
                    "SELECT id,ts,content FROM logs "
                    "WHERE session_id=? AND type='tool_result' AND ts>=? "
                    "AND ts<'2026-09-01T23:59:59+00:00' ORDER BY ts",
                    (failure_log["session_id"], failure_log["ts"]),
                ).fetchall()
                if operation_id in log["content"] and expected in log["content"]
            ]
            revision = _git(
                canonical_repo,
                "rev-list",
                "-1",
                f"--before={failure_log['ts']}",
                "--all",
            )
            historical = _states_at(canonical_repo, revision)
            historical_matches = [
                state
                for state in historical
                if state.get("project_id") == "orchestra"
                and state.get("display_number") == number
            ]
            current = _states_at(canonical_repo, "HEAD")
            current_matches = [
                state
                for state in current
                if state.get("project_id") == "orchestra"
                and state.get("display_number") == number
            ]
            first_event = _first_current_event(canonical_repo, number)
            if historical_matches or len(current_matches) != 1:
                raise AssertionError(f"canonical identity check failed for #{number}")
            if not str(first_event["occurred_at"]) > str(failure_log["ts"]):
                raise AssertionError(f"canonical event does not postdate failure #{number}")
            print(json.dumps({
                "task": number,
                "operation_id": operation_id,
                "operation_created_at": row["created_at"],
                "failure_log_id": failure_log["id"],
                "failure_at": failure_log["ts"],
                "matching_tool_result_observations": observations,
                "operation_state": row["state"],
                "commit_point": row["commit_point"],
                "error": error["message"],
                "canonical_snapshot": revision,
                "snapshot_state_count": len(historical),
                "snapshot_target_matches": len(historical_matches),
                "first_current_event_type": first_event["event_type"],
                "first_current_event_at": first_event["occurred_at"],
                "current_target_matches": len(current_matches),
            }, ensure_ascii=False, sort_keys=True))
    finally:
        connection.close()
    verification = sqlite3.connect(f"file:{production_db}?mode=ro", uri=True)
    try:
        sessions_after = int(verification.execute("SELECT count(*) FROM sessions").fetchone()[0])
    finally:
        verification.close()
    print(f"PROD_SESSIONS_BEFORE={sessions_before}")
    print(f"PROD_SESSIONS_AFTER={sessions_after}")
    print(f"PROD_SESSIONS_UNCHANGED={sessions_before == sessions_after}")
    if sessions_before != sessions_after:
        raise AssertionError("production sessions count changed during read-only evidence scan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
