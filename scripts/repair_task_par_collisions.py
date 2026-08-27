#!/usr/bin/env python3
"""Repair cross-store task-number collisions; dry-run unless --apply is given."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ia.task_store import TaskStore, build_migration_manifest


def _default_state_root(legacy_db: Path) -> Path:
    state_directory = os.environ.get("STATE_DIRECTORY", "").strip()
    xdg_state = os.environ.get("XDG_STATE_HOME", "").strip()
    if os.environ.get("ORCHESTRA_DB_PATH", "").strip() and not state_directory and not xdg_state:
        return legacy_db.parent / "knowledge-v1"
    if state_directory:
        parts = [part for part in state_directory.split(os.pathsep) if part]
        if len(parts) != 1:
            raise ValueError("STATE_DIRECTORY must contain exactly one path")
        return Path(parts[0]) / "knowledge-v1"
    base = Path(xdg_state) / "orchestra" if xdg_state else Path.home() / ".local/state/orchestra"
    return base / "knowledge-v1"


def _json_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _load_legacy(connection: sqlite3.Connection, project_id: str):
    connection.row_factory = sqlite3.Row
    project = connection.execute(
        "SELECT * FROM tm_projects WHERE id=?", (project_id,)
    ).fetchone()
    if project is None:
        raise ValueError(f"legacy project {project_id!r} does not exist")
    rows = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM tm_tasks WHERE project_id=? ORDER BY par_number,id",
            (project_id,),
        ).fetchall()
    ]
    return dict(project), rows


def _load_canonical(store: TaskStore, project_id: str):
    head = store.canonical_head
    states = [
        state
        for state in store._states().values()
        if state["project_id"] == project_id
    ]
    if store.canonical_head != head:
        raise RuntimeError("canonical task head changed while reading the snapshot")
    return head, states


def _numeric_task_dirs(scope: str) -> list[int]:
    root = Path(scope) / "docs" / "tasks" if scope else None
    if root is None or not root.is_dir():
        return []
    return sorted(
        int(path.name)
        for path in root.iterdir()
        if path.is_dir() and path.name.isdigit()
    )


def _snapshot(project: dict, legacy: list[dict], head: str, canonical: list[dict]) -> dict:
    def compact(
        row: dict,
        *,
        number_key: str,
        id_key: str,
        ignored: frozenset[str] = frozenset(),
    ) -> dict:
        return {
            "par": int(row[number_key]),
            "id": str(row[id_key]),
            "title": str(row.get("title") or ""),
            "digest": _json_digest({
                key: value for key, value in row.items() if key not in ignored
            }),
        }

    return {
        "schema_version": 1,
        "project": str(project["id"]),
        "canonical_head": head,
        "legacy": [compact(row, number_key="par_number", id_key="id") for row in legacy],
        "canonical": [
            compact(
                row,
                number_key="display_number",
                id_key="stable_id",
                ignored=frozenset({"canonical_head", "projection_head"}),
            )
            for row in canonical
        ],
        "docs_task_numbers": _numeric_task_dirs(str(project.get("scope") or "")),
    }


def _encode_snapshot(snapshot: dict) -> str:
    raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return "v1." + base64.urlsafe_b64encode(zlib.compress(raw, level=9)).decode().rstrip("=")


def _decode_snapshot(token: str) -> dict:
    if not token.startswith("v1."):
        raise ValueError("snapshot token has an unsupported version")
    encoded = token[3:]
    encoded += "=" * (-len(encoded) % 4)
    value = json.loads(zlib.decompress(base64.urlsafe_b64decode(encoded)))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("snapshot token is malformed")
    return value


def _snapshot_diff(before: dict, after: dict) -> list[str]:
    differences: list[str] = []
    if before.get("project") != after.get("project"):
        differences.append(f"project changed: {before.get('project')} -> {after.get('project')}")
    if before.get("canonical_head") != after.get("canonical_head"):
        differences.append(
            "canonical head changed: "
            f"{before.get('canonical_head')} -> {after.get('canonical_head')}"
        )
    for owner in ("legacy", "canonical"):
        old = {int(row["par"]): row for row in before.get(owner, [])}
        new = {int(row["par"]): row for row in after.get(owner, [])}
        for number in sorted(new.keys() - old.keys()):
            row = new[number]
            differences.append(f"{owner} added #{number}: {row['id']} {_label(row['title'])}")
        for number in sorted(old.keys() - new.keys()):
            row = old[number]
            differences.append(f"{owner} removed #{number}: {row['id']} {_label(row['title'])}")
        for number in sorted(old.keys() & new.keys()):
            if old[number] != new[number]:
                differences.append(
                    f"{owner} changed #{number}: {old[number]['id']} -> {new[number]['id']}"
                )
    old_docs = set(before.get("docs_task_numbers", []))
    new_docs = set(after.get("docs_task_numbers", []))
    for number in sorted(new_docs - old_docs):
        differences.append(f"docs task directory added #{number}")
    for number in sorted(old_docs - new_docs):
        differences.append(f"docs task directory removed #{number}")
    return differences


def _restored_state(task: dict, project: dict, head: str) -> dict:
    manifest = build_migration_manifest({
        "source": {
            "cutoff": str(task.get("updated_at") or task.get("created_at") or "repair"),
            "source_head": head,
            "source_schema_sha256": "sha256:task-par-repair-v1",
        },
        "projects": [{"id": project["id"], "scope": project.get("scope") or ""}],
        "tasks": [task],
        "evidence": [],
    })
    return manifest["tasks"][0]


def _pending_legacy_moves(
    store: TaskStore,
    project_id: str,
    canonical: list[dict],
    legacy: list[dict],
) -> list[dict]:
    states = {state["stable_id"]: state for state in canonical}
    legacy_by_id = {int(row["id"]): row for row in legacy}
    legacy_by_number = {int(row["par_number"]): row for row in legacy}
    pending: dict[int, dict] = {}
    for path in store.canonical_root.glob(
        f"projects/{project_id}/tasks/*/events/*.json"
    ):
        event = json.loads(path.read_text(encoding="utf-8"))
        if event.get("event_type") != "task.display-renumbered":
            continue
        changes = event.get("changes") or {}
        if "legacy_row_id" not in changes:
            continue
        row_id = int(changes["legacy_row_id"])
        target = int(changes["to_display_number"])
        source = int(changes["legacy_from_display_number"])
        state = states.get(str(event.get("stable_id") or ""))
        row = legacy_by_id.get(row_id)
        if state is None or int(state["display_number"]) != target or row is None:
            raise RuntimeError(f"recorded repair for legacy row {row_id} is incomplete")
        current = int(row["par_number"])
        if current == target:
            continue
        if current != source:
            raise RuntimeError(
                f"legacy row {row_id} moved unexpectedly: expected #{source} "
                f"or #{target}, found #{current}"
            )
        target_owner = legacy_by_number.get(target)
        if target_owner is not None and int(target_owner["id"]) != row_id:
            raise RuntimeError(
                f"pending repair target #{target} was claimed by legacy row "
                f"{target_owner['id']}"
            )
        pending[row_id] = {
            "legacy_row_id": row_id,
            "legacy_from_display_number": source,
            "replacement_number": target,
            "canonical_title": state["title"],
        }
    return list(pending.values())


def _plan_repairs(
    store: TaskStore,
    project: dict,
    legacy: list[dict],
    head: str,
    canonical: list[dict],
) -> tuple[list[dict], list[dict]]:
    project_id = str(project["id"])
    pending = _pending_legacy_moves(store, project_id, canonical, legacy)
    legacy_by_number = {int(row["par_number"]): row for row in legacy}
    canonical_by_number = {int(row["display_number"]): row for row in canonical}
    collisions = [
        number
        for number in sorted(legacy_by_number.keys() & canonical_by_number.keys())
        if (
            legacy_by_number[number].get("title") != canonical_by_number[number].get("title")
            or legacy_by_number[number].get("description")
            != canonical_by_number[number].get("description")
        )
    ]
    occupied = set(legacy_by_number) | set(canonical_by_number)
    blocked_dirs = set(_numeric_task_dirs(str(project.get("scope") or "")))
    next_number = max(occupied, default=0) + 1
    actions: list[dict] = []
    used_mirrors: set[int] = set()
    for number in collisions:
        old = legacy_by_number[number]
        collided = canonical_by_number[number]
        mirrors = [
            row for row in legacy
            if int(row["id"]) != int(old["id"])
            and row.get("title") == collided.get("title")
            and row.get("description") == collided.get("description")
        ]
        if len(mirrors) != 1:
            raise RuntimeError(
                f"collision #{number} has {len(mirrors)} matching legacy tasks; refusing inference"
            )
        mirror = mirrors[0]
        if int(mirror["id"]) in used_mirrors:
            raise RuntimeError("one legacy task mirrors more than one canonical collision")
        if str(old.get("created_at") or "") >= str(collided.get("created_at") or ""):
            raise RuntimeError(f"collision #{number} does not prove that the legacy task is older")
        if mirror.get("worker_session_id"):
            raise RuntimeError(f"legacy mirror #{mirror['par_number']} is bound to a live worker")
        while next_number in occupied or next_number in blocked_dirs:
            next_number += 1
        replacement = next_number
        occupied.add(replacement)
        next_number += 1
        used_mirrors.add(int(mirror["id"]))
        actions.append({
            "stable_id": collided["stable_id"],
            "from_display_number": number,
            "replacement_number": replacement,
            "legacy_row_id": int(mirror["id"]),
            "legacy_from_display_number": int(mirror["par_number"]),
            "legacy_old": old,
            "canonical_new": collided,
            "legacy_mirror": mirror,
            "restored_state": _restored_state(old, project, head),
        })
    return actions, pending


def _label(value: str, limit: int = 84) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _print_plan(actions: list[dict], pending: list[dict]) -> None:
    print(f"COLLISION_COUNT={len(actions)}")
    if actions:
        print(
            "| par | legacy (old) | created | canonical (new) | created "
            "| legacy mirror | replacement |"
        )
        print("|---:|---|---|---|---|---:|---:|")
        for action in actions:
            old = action["legacy_old"]
            new = action["canonical_new"]
            print(
                f"| #{action['from_display_number']} | {_label(old['title'])} "
                f"| {old['created_at']} "
                f"| {_label(new['title'])} | {new['created_at']} "
                f"| #{action['legacy_from_display_number']} | #{action['replacement_number']} |"
            )
    for move in pending:
        print(
            f"PENDING legacy row {move['legacy_row_id']}: "
            f"#{move['legacy_from_display_number']} -> #{move['replacement_number']}"
        )


def _commit_canonical(canonical_root: Path) -> None:
    repository = canonical_root.parent
    if not (repository / ".git").is_dir():
        return
    subprocess.run(["git", "-C", str(repository), "add", "--", "tasks"], check=True)
    changed = subprocess.run(
        ["git", "-C", str(repository), "diff", "--cached", "--quiet", "--", "tasks"],
        check=False,
    )
    if changed.returncode == 1:
        subprocess.run(
            ["git", "-C", str(repository), "commit", "-qm", "repair canonical task par collisions"],
            check=True,
        )
    elif changed.returncode != 0:
        raise RuntimeError("cannot inspect canonical task Git changes")


def _dry_connection(path: Path) -> sqlite3.Connection:
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    memory = sqlite3.connect(":memory:")
    source.backup(memory)
    source.close()
    return memory


def main(argv: list[str] | None = None) -> int:
    default_db = Path(os.environ.get("ORCHESTRA_DB_PATH") or REPO_ROOT / "data/orchestra.db")
    default_state = _default_state_root(default_db)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-db", type=Path, default=default_db)
    parser.add_argument("--canonical-root", type=Path, default=default_state / "canonical/tasks")
    parser.add_argument("--projection", type=Path, default=default_state / "task-current.db")
    parser.add_argument("--project", default="orchestra")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-snapshot")
    args = parser.parse_args(argv)
    if args.apply and not args.expected_snapshot:
        parser.error("--apply requires --expected-snapshot from the immediately preceding dry-run")

    store = TaskStore(canonical_root=args.canonical_root, projection_path=args.projection)
    connection = sqlite3.connect(args.legacy_db) if args.apply else _dry_connection(args.legacy_db)
    try:
        if args.apply:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("BEGIN IMMEDIATE")
        project, legacy = _load_legacy(connection, args.project)
        head, canonical = _load_canonical(store, args.project)
        current_snapshot = _snapshot(project, legacy, head, canonical)
        if args.apply:
            expected = _decode_snapshot(args.expected_snapshot)
            differences = _snapshot_diff(expected, current_snapshot)
            if differences:
                connection.rollback()
                print("REFUSED: snapshot changed before --apply")
                for difference in differences:
                    print(f"- {difference}")
                return 2
        actions, pending = _plan_repairs(store, project, legacy, head, canonical)
        _print_plan(actions, pending)
        if not args.apply:
            token = _encode_snapshot(current_snapshot)
            print(f"SNAPSHOT_TOKEN={token}")
            print("DRY_RUN: no task store was modified")
            return 0
        if not actions and not pending:
            connection.rollback()
            _commit_canonical(args.canonical_root)
            print("NOOP: stores are already collision-free")
            return 0
        if actions:
            store.repair_display_collisions(
                [
                    {
                        "stable_id": action["stable_id"],
                        "from_display_number": action["from_display_number"],
                        "to_display_number": action["replacement_number"],
                        "legacy_row_id": action["legacy_row_id"],
                        "legacy_from_display_number": action["legacy_from_display_number"],
                        "restored_state": action["restored_state"],
                    }
                    for action in actions
                ],
                expected_head=head,
            )
        now = datetime.now(timezone.utc).isoformat()
        for move in [*actions, *pending]:
            cursor = connection.execute(
                "UPDATE tm_tasks SET par_number=?,updated_at=?,sync_revision=sync_revision+1 "
                "WHERE id=? AND project_id=? AND par_number=?",
                (
                    move["replacement_number"], now, move["legacy_row_id"], args.project,
                    move["legacy_from_display_number"],
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"legacy row {move['legacy_row_id']} changed during repair")
        connection.commit()
        _commit_canonical(args.canonical_root)
        for action in actions:
            print(
                f"APPLIED #{action['from_display_number']} -> #{action['replacement_number']}: "
                f"{_label(action['canonical_new']['title'])}"
            )
        for move in pending:
            print(
                f"APPLIED pending legacy row {move['legacy_row_id']} -> "
                f"#{move['replacement_number']}"
            )
        return 0
    except Exception:
        if args.apply:
            connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
