#!/usr/bin/env python3
"""Native rg + stdlib-AST arm for frozen experiment #346; prints raw JSON."""

from __future__ import annotations

import argparse
import ast
import json
import os
import resource
import subprocess
import time
from pathlib import Path
from typing import Any


def _rss() -> dict[str, int]:
    own = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024
    return {"self_max_rss_bytes": own, "children_max_rss_bytes": children}


def _rg(root: Path, symbol: str) -> dict[str, Any]:
    before = time.monotonic()
    proc = subprocess.run(
        ["rg", "-n", "-w", "--hidden", "--glob", "!.serena/**", symbol, "."],
        cwd=root,
        text=True,
        capture_output=True,
    )
    return {
        "command": ["rg", "-n", "-w", "--hidden", "--glob", "!.serena/**", symbol, "."],
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "elapsed_s": time.monotonic() - before,
    }


def _ast_rows(root: Path, symbol: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.py")):
        if ".serena" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        tree = ast.parse(text, filename=rel)
        for node in ast.walk(tree):
            kind = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
                kind = "definition"
            elif isinstance(node, ast.Name) and node.id == symbol:
                kind = "name"
            elif isinstance(node, ast.Attribute) and node.attr == symbol:
                kind = "attribute"
            elif isinstance(node, ast.ImportFrom) and any(a.name == symbol or a.asname == symbol for a in node.names):
                kind = "import"
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and symbol in node.value:
                kind = "string"
            if kind:
                line = getattr(node, "lineno", 0)
                rows.append({
                    "path": rel,
                    "line": line,
                    "kind": kind,
                    "text": lines[line - 1].strip() if 0 < line <= len(lines) else "",
                })
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
                for decorator in node.decorator_list:
                    line = getattr(decorator, "lineno", node.lineno)
                    rows.append({
                        "path": rel,
                        "line": line,
                        "kind": "decorator_on_definition",
                        "text": lines[line - 1].strip(),
                    })
    unique = {(row["path"], row["line"], row["kind"]): row for row in rows}
    return sorted(unique.values(), key=lambda row: (row["path"], row["line"], row["kind"]))


def _query(root: Path, case: str, symbol: str) -> dict[str, Any]:
    before = time.monotonic()
    rg = _rg(root, symbol)
    ast_rows = _ast_rows(root, symbol)
    return {"case": case, "symbol": symbol, "rg": rg, "ast_rows": ast_rows, "elapsed_s": time.monotonic() - before}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    root = Path(args.cwd).resolve()
    started = time.monotonic()
    out: dict[str, Any] = {
        "name": args.name,
        "scenario": "baseline",
        "cwd": str(root),
        "loadavg_start": os.getloadavg(),
        "started_wall": time.time(),
    }
    queries = [
        ("R1", "plain_target"),
        ("R2-route", "refresh_models_endpoint"),
        ("R2-tool", "update_progress"),
        ("R3", "dynamic_target"),
        ("R4", "openDeleteOrchModal"),
        ("R5-dead-leaf", "dead_leaf"),
        ("R5-dead-root", "dead_root"),
        ("R5-live-root", "live_root"),
        ("R6-old-before", "stale_target"),
    ]
    calls = []
    for index, (case, symbol) in enumerate(queries):
        calls.append(_query(root, case, symbol))
        if index == 0:
            out["ready_elapsed_s"] = time.monotonic() - started
            out["ready_rss"] = _rss()
    stale = root / "python/stale.py"
    before = stale.read_text(encoding="utf-8")
    changed = before.replace("stale_target", "stale_renamed")
    temp = stale.with_suffix(".py.swap346")
    temp.write_text(changed, encoding="utf-8")
    os.replace(temp, stale)
    calls.append(_query(root, "R6-old-immediate", "stale_target"))
    calls.append(_query(root, "R6-new-immediate", "stale_renamed"))
    out.update({
        "calls": calls,
        "status": "ok",
        "post_query_rss": _rss(),
        "loadavg_end": os.getloadavg(),
        "wall_elapsed_s": time.monotonic() - started,
        "ended_wall": time.time(),
    })
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    import sys
    main()

