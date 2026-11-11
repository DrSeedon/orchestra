#!/usr/bin/env python3
"""Conservative one-shot cleanup. Dry-run by default; recheck live owners before each deletion."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import hub_workspace as hw
from app.multicode_client import MultiCodeClient


def owners(db_path: Path) -> list[dict]:
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT id,name,status,cwd,worktree_path,backend_type,session_id FROM sessions"
        )]


def plan_cleanup(sessions: list[dict], states: list[hw.WorkspaceState],
                 projects: list[dict], remote_root: str) -> list[dict]:
    projects_by_id = {p["id"]: p for p in projects}
    plan = []
    for state in states:
        project = projects_by_id.get(state.project_id)
        reason = ""
        local = os.path.realpath(state.worktree)
        matching = [s for s in sessions if os.path.realpath(s.get("worktree_path") or s.get("cwd") or "/") == local
                    or s.get("session_id") == state.ws_id]
        if any(s["status"] not in {"archived", "closed", "deleted"} for s in matching):
            reason = "live owner"
        elif not state.archived and not matching:
            reason = "closure unproven"
        elif state.pending_sync:
            reason = "pending sync"
        elif not hw._WS_ID.fullmatch(state.ws_id):
            reason = "invalid workspace identity"
        elif os.path.dirname(state.remote_dir) != remote_root or os.path.basename(state.remote_dir) != state.ws_id:
            reason = "remote directory mismatch"
        elif project is None:
            reason = "project not listed"
        elif project.get("title") != state.ws_id:
            reason = "not an owned hub project"
        elif project.get("workspaceRoot") != state.remote_dir:
            reason = "project directory mismatch"
        if not reason:
            try:
                hw.assert_archive_ready(state)
            except hw.HubWorkspaceError:
                reason = "file policy blocks cleanup"
        plan.append({"ws_id": state.ws_id, "project_id": state.project_id,
                     "remote_dir": state.remote_dir, "action": "keep" if reason else "delete",
                     "reason": reason or "closed workspace with no live owners"})
    return plan


async def list_projects(mc) -> list[dict]:
    projects, cursor = [], None
    while True:
        page = await mc.tool_call("t3_project_list", {"limit": 100, **({"cursor": cursor} if cursor is not None else {})})
        if not isinstance(page, dict) or not isinstance(page.get("projects"), list):
            raise RuntimeError("project list unavailable; no deletions permitted")
        projects.extend(page["projects"])
        cursor = page.get("nextCursor")
        if cursor is None:
            return projects


async def run(args) -> None:
    ssh = hw.HubSsh.from_env()
    if ssh is None:
        raise RuntimeError("Hub transport unavailable")
    remote_root = await ssh.root()
    states = [hw.WorkspaceState.load(p.stem) for p in hw.STATE_DIR.glob("hub-*.json")]
    states = [state for state in states if state]
    async with MultiCodeClient.from_env() as mc:
        projects = await list_projects(mc)
        plan = plan_cleanup(owners(args.db), states, projects, remote_root)
        report = {"projects_before": len([p for p in projects if hw._WS_ID.fullmatch(p.get("title", ""))]),
                  "plan": plan, "deleted": []}
        args.report.write_text(json.dumps(report, indent=2))
        if args.apply:
            for row in plan:
                if row["action"] != "delete":
                    continue
                # The database is read again immediately before every remote mutation.
                current = hw.WorkspaceState.load(row["ws_id"])
                if current is None:
                    raise RuntimeError("workspace disappeared; stop cleanup")
                fresh = plan_cleanup(owners(args.db), [current], await list_projects(mc), remote_root)
                if fresh[0]["action"] != "delete":
                    raise RuntimeError(f"{row['ws_id']}: live pre-delete validation refused")
                await hw.archive_workspace(current, ssh, mc)
                report["deleted"].append(row["ws_id"])
                args.report.write_text(json.dumps(report, indent=2))
        after = await list_projects(mc)
        report["projects_after"] = len([p for p in after if hw._WS_ID.fullmatch(p.get("title", ""))])
        args.report.write_text(json.dumps(report, indent=2))
        print(json.dumps({key: value for key, value in report.items() if key != "plan"}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=hw.DATA_DIR / "orchestra.db")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
