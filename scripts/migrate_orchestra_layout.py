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
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    try:
        if args.repair and _preserve_journal_path(args.repository).exists():
            result = migrate_project_layout_preserving_dirty(args.repository)
        else:
            result = migrate_project_layout(args.repository, repair=args.repair)
    except LayoutMigrationError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": exc.code,
                    "repository": str(exc.repository),
                    "error": str(exc),
                    "repair_command": exc.repair_command,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
