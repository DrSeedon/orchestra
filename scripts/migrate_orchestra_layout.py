#!/usr/bin/env python3
"""CLI repair/forced migration for one project checkout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.orchestra_layout import (
    LayoutMigrationError,
    _preserve_journal_path,
    migrate_project_layout,
    migrate_project_layout_preserving_dirty,
    migrate_session_ownership,
    repair_registered_ownership,
)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repair", action="store_true")
    parser.add_argument(
        "--repair-ownership",
        action="store_true",
        help="repoint live worker ownership at the migrated .orchestra/ paths; "
        "idempotent, and without a repository it covers every registered project",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the ownership plan without writing it",
    )
    parser.add_argument("repository", type=Path, nargs="?")
    args = parser.parse_args()
    if args.dry_run and not args.repair_ownership:
        # Otherwise `--dry-run <repo>` silently performs and COMMITS a real layout
        # migration: the flag is only consumed on the ownership path.
        parser.error("--dry-run is only supported together with --repair-ownership")
    if args.repair_ownership:
        if args.repository is None:
            result = repair_registered_ownership(apply=not args.dry_run)
        else:
            result = migrate_session_ownership(
                args.repository, apply=not args.dry_run
            )
        _print(result)
        return 0
    if args.repository is None:
        parser.error("repository is required unless --repair-ownership is used")
    try:
        if args.repair and _preserve_journal_path(args.repository).exists():
            result = migrate_project_layout_preserving_dirty(args.repository)
        else:
            result = migrate_project_layout(args.repository, repair=args.repair)
    except LayoutMigrationError as exc:
        _print(
            {
                "status": "failed",
                "code": exc.code,
                "repository": str(exc.repository),
                "error": str(exc),
                "repair_command": exc.repair_command,
            }
        )
        return 2
    _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
