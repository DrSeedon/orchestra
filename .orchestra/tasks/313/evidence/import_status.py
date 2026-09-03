#!/usr/bin/env python3
"""Resolve test imports against the current source tree (static only)."""
from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "docs/tasks/313/evidence/import-status.json"


def defs(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    names = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


def imported_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    names = set()
    for n in tree.body:
        if isinstance(n, ast.Import):
            names.update(a.asname or a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            names.update(a.asname or a.name for a in n.names)
    return names


def main() -> None:
    module_defs = {}
    module_imports = {}
    for p in sorted((ROOT / "app").rglob("*.py")):
        rel = p.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
        module_defs[rel] = defs(p)
        module_imports[rel] = imported_names(p)
    occurrences = Counter()
    for p in (ROOT / "app").rglob("*.py"):
        try:
            tree = ast.parse(p.read_text(), filename=str(p))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                occurrences[n.id] += 1
    rows = []
    for p in sorted((ROOT / "tests").glob("*.py")):
        try:
            tree = ast.parse(p.read_text(), filename=str(p))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("app"):
                for a in n.names:
                    module = n.module
                    module_path = ROOT / (module.replace(".", "/") + ".py")
                    submodule_path = ROOT / module.replace(".", "/") / (a.name + ".py")
                    imported_submodule = submodule_path.is_file()
                    direct = a.name in module_defs.get(module, set())
                    reexport = a.name in module_imports.get(module, set())
                    exists = a.name == "*" or direct or reexport or imported_submodule
                    rows.append({
                        "test_file": p.relative_to(ROOT).as_posix(),
                        "line": n.lineno,
                        "module": module,
                        "symbol": a.name,
                        "as": a.asname or "",
                        "module_exists": module in module_defs or (ROOT / module.replace(".", "/")).is_dir(),
                        "symbol_defined_in_module_ast": exists,
                        "symbol_reexported_by_module_ast": reexport,
                        "app_name_occurrences": occurrences.get(a.name, 0),
                    })
    OUT.write_text(json.dumps({
        "method": "AST import/name inventory; dynamic getattr/re-export paths require manual review",
        "summary": {
            "from_app_import_rows": len(rows),
            "module_missing_rows": sum(not r["module_exists"] for r in rows),
            "symbol_not_defined_rows": sum(not r["symbol_defined_in_module_ast"] for r in rows),
        },
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
