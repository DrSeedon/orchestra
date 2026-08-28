#!/usr/bin/env python3
"""Dry-run, apply, or verify project-local knowledge distribution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ia.project_distribution import (
    DistributionError,
    PartialDistributionError,
    distribute_project_knowledge,
    global_receipt,
    verify_project_knowledge_distribution,
)


def _receipt_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    parent = resolved.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    probe = __import__("subprocess").run(
        ["git", "-C", str(parent), "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0 and probe.stdout.strip() == "true":
        raise DistributionError(f"receipt path is inside a managed Git repository: {resolved}")
    return resolved


def _write_receipt(path: Path, value: dict) -> None:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise DistributionError(f"receipt path conflicts: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--scope-registry", type=Path, required=True)
    parser.add_argument("--quarantine-root", type=Path, required=True)
    parser.add_argument("--expected-source-head", required=True)
    parser.add_argument("--expected-scope-registry-sha256", default="")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--receipt-path", type=Path)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--probe-remotes", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.commit and not args.apply:
        parser.error("--commit requires --apply")
    common = {
        "canonical_root": args.canonical_root,
        "scope_registry_path": args.scope_registry,
        "quarantine_root": args.quarantine_root,
        "expected_source_head": args.expected_source_head,
        "expected_scope_registry_sha256": args.expected_scope_registry_sha256,
        "probe_remotes": bool(args.probe_remotes),
    }
    try:
        receipt_path = None
        if args.receipt_path:
            receipt_path = _receipt_path(args.receipt_path)
            if receipt_path.exists():
                raise DistributionError(f"receipt path already exists: {receipt_path}")
        result = (
            verify_project_knowledge_distribution(**common)
            if args.verify
            else distribute_project_knowledge(
                **common,
                apply=bool(args.apply),
                commit=bool(args.commit),
            )
        )
        if receipt_path is not None:
            receipt = global_receipt(result, run_id=args.run_id)
            try:
                _write_receipt(receipt_path, receipt)
            except (DistributionError, OSError) as exc:
                if not args.apply:
                    raise
                partial = {
                    "schema_version": 1,
                    "status": "partial",
                    "source_head": result["source_head"],
                    "committed_projects": [
                        project["project_id"]
                        for project in result["projects"]
                        if project["target_commit"] != project["before_head"]
                    ],
                    "failed_project": "receipt",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                print(json.dumps(partial, ensure_ascii=False, sort_keys=True), file=sys.stderr)
                return 3
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
        return 0
    except PartialDistributionError as exc:
        if args.receipt_path:
            try:
                _write_receipt(_receipt_path(args.receipt_path), exc.partial_result)
            except DistributionError as receipt_error:
                print(f"DistributionError: {receipt_error}", file=sys.stderr)
        print(
            json.dumps(exc.partial_result, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 3
    except (DistributionError, OSError, ValueError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
