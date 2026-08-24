"""Read-only AST inventory for #332; prints JSON, never imports app or writes files."""
from __future__ import annotations

import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
AREAS = (ROOT / "app", ROOT / "scripts")
EXCLUDE = {"__pycache__"}


def dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def walk_files() -> list[pathlib.Path]:
    found = []
    for area in AREAS:
        for path in area.rglob("*.py"):
            if not any(part in EXCLUDE for part in path.parts):
                found.append(path)
    return sorted(found)


def main() -> None:
    files = walk_files()
    defs: dict[str, list[dict]] = {}
    calls: list[dict] = []
    imports: list[dict] = []
    dynamic: list[dict] = []
    syntax_errors: list[dict] = []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            syntax_errors.append({"file": rel, "error": f"{type(exc).__name__}: {exc}"})
            continue
        module = rel[:-3].replace("/", ".")
        if module.endswith(".__init__"):
            module = module[:-9]
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                key = f"{module}:{node.name}"
                defs.setdefault(key, []).append({
                    "file": rel, "line": node.lineno, "end_line": getattr(node, "end_lineno", node.lineno),
                    "kind": type(node).__name__,
                })
            elif isinstance(node, ast.Call):
                name = dotted(node.func)
                if name:
                    calls.append({"file": rel, "line": node.lineno, "callee": name})
                if name in {"getattr", "importlib.import_module", "__import__", "import_module"}:
                    dynamic.append({"file": rel, "line": node.lineno, "callee": name,
                                    "args": [literal(arg) for arg in node.args]})
            elif isinstance(node, ast.Import):
                imports.extend({"file": rel, "line": node.lineno, "module": alias.name,
                                "name": "", "asname": alias.asname} for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.extend({"file": rel, "line": node.lineno,
                                "module": node.module or "", "name": alias.name,
                                "asname": alias.asname} for alias in node.names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                pass
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for dec in node.decorator_list:
                    name = dotted(dec.func) if isinstance(dec, ast.Call) else dotted(dec)
                    dynamic.append({"file": rel, "line": node.lineno, "decorator": name,
                                    "args": [literal(arg) for arg in dec.args] if isinstance(dec, ast.Call) else []})
    out = {
        "root": str(ROOT),
        "files": len(files),
        "defs": defs,
        "calls": calls,
        "imports": imports,
        "dynamic_and_decorators": dynamic,
        "syntax_errors": syntax_errors,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
