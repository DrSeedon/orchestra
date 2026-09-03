#!/usr/bin/env python3
"""Build a read-only pytest/source inventory for #313."""
from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TESTS = ROOT / "tests"
OUT = ROOT / "docs/tasks/313/inventory.json"
COLLECT = ROOT / "docs/tasks/313/evidence/collect-default-patched.txt"
FROZEN_MAIN_SHA = "1d9be7ae8511a1c5657362cc56eef395b4585bf2"


def dotted(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [dotted(d) or ast.unparse(d) for d in node.decorator_list]


def module_markers(tree: ast.Module) -> list[str]:
    out = []
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets):
            out.append(ast.unparse(n.value))
    return out


def source_slice(lines: list[str], node: ast.AST) -> str:
    return "".join(lines[node.lineno - 1 : getattr(node, "end_lineno", node.lineno)])


def patterns(node: ast.AST, source: str) -> list[str]:
    found: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Assert):
            found.add("assert")
            if isinstance(n.test, ast.Call) and dotted(n.test.func) in {"all", "any"}:
                found.add(dotted(n.test.func))
            if isinstance(n.test, ast.Compare):
                found.add("assert_compare")
        if isinstance(n, ast.Call):
            fn = dotted(n.func)
            if fn in {"all", "any"}:
                found.add(fn)
            if fn.endswith("getsource") or fn == "inspect.getsource":
                found.add("inspect.getsource")
            if fn.endswith("wait_for") or fn.endswith("sleep"):
                found.add("wall_clock_wait")
            if fn.endswith("MagicMock") or fn.endswith("AsyncMock"):
                found.add(fn.split(".")[-1])
            if fn.endswith("TestClient") or fn.endswith("Page"):
                found.add("client_or_browser")
        if isinstance(n, ast.Compare):
            text = ast.unparse(n)
            if any(token in text for token in ("len(", ".count(", "==", "!=", "is None")):
                found.add("representation_or_cardinality_compare")
    for literal in ("route.count", "snapshot", "__file__", "argv", "query_selector", "assert_called"):
        if literal in source:
            found.add(literal)
    return sorted(found)


def module_imports(tree: ast.Module) -> list[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name for a in n.names if a.name.startswith(("app", "scripts")))
        elif isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(("app", "scripts")):
            out.add(n.module)
    return sorted(out)


def production_imports(tree: ast.Module) -> list[dict[str, str]]:
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith(("app", "scripts")):
                    out.append({"module": a.name, "symbol": "*", "as": a.asname or ""})
        elif isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(("app", "scripts")):
            for a in n.names:
                out.append({"module": n.module, "symbol": a.name, "as": a.asname or ""})
    return sorted(out, key=lambda x: (x["module"], x["symbol"], x["as"]))


def fixture_names(tree: ast.Module) -> list[dict[str, object]]:
    out = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            marks = decorators(n)
            if any("fixture" in d for d in marks):
                out.append({"name": n.name, "line": n.lineno, "scope": next((d for d in marks if "scope=" in d), "function")})
    return sorted(out, key=lambda x: (x["line"], x["name"]))


def test_defs(tree: ast.Module, lines: list[str], path: str) -> list[dict[str, object]]:
    out = []
    parents: list[str] = []
    parent_markers: list[list[str]] = []
    inherited_module_markers = module_markers(tree)

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            parents.append(node.name)
            parent_markers.append(decorators(node) if hasattr(node, "decorator_list") else [])
            self.generic_visit(node)
            parent_markers.pop()
            parents.pop()

        def _fn(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            if not node.name.startswith("test"):
                return
            name = "::".join([*parents, node.name])
            src = source_slice(lines, node)
            args = [a.arg for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]]
            out.append({
                "source_node": name,
                "file": path,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "loc": getattr(node, "end_lineno", node.lineno) - node.lineno + 1,
                "async": isinstance(node, ast.AsyncFunctionDef),
                "decorators": decorators(node),
                "markers_inherited": [*inherited_module_markers, *(m for group in parent_markers for m in group)],
                "fixture_args": args,
                "static_assert_patterns": patterns(node, src),
                "file_imports_ref": path,
            })

        visit_FunctionDef = _fn
        visit_AsyncFunctionDef = _fn

    Visitor().visit(tree)
    return out


def collected_nodes() -> list[str]:
    nodes = []
    for line in COLLECT.read_text().splitlines():
        if line.startswith("tests/") and "::" in line:
            nodes.append(line)
    return nodes


def collection_totals() -> dict[str, int]:
    text = COLLECT.read_text(encoding="utf-8")
    match = re.search(r"(\d+)/(\d+) tests collected \((\d+) deselected\)", text)
    if not match:
        raise AssertionError("collection summary missing from frozen collect output")
    live_text = COLLECT.with_name("collect-live-patched.txt").read_text(encoding="utf-8")
    live_match = re.search(r"^(\d+)/(\d+) tests collected \((\d+) deselected\)", live_text, re.MULTILINE)
    if not live_match:
        raise AssertionError("live collection summary missing from frozen collect output")
    return {
        "default_selected_nodes": int(match.group(1)),
        "total_nodes": int(match.group(2)),
        "deselected_live_nodes": int(match.group(3)),
        "live_probe_nodes": int(live_match.group(1)),
    }


def main() -> None:
    files = []
    nodes = []
    for path in sorted(TESTS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        tree = ast.parse(text, filename=str(path))
        rel = path.relative_to(ROOT).as_posix()
        defs = test_defs(tree, lines, rel)
        files.append({
            "file": rel,
            "loc": len(lines),
            "nonblank_loc": sum(bool(line.strip()) for line in lines),
            "pytest_markers": sorted({d for item in defs for d in [*item["decorators"], *item["markers_inherited"]] if "pytest.mark" in d}),
            "fixtures_defined": fixture_names(tree),
            "imported_production_symbols": production_imports(tree),
            "test_definitions": len(defs),
            "static_assert_pattern_counts": {p: sum(p in item["static_assert_patterns"] for item in defs) for p in sorted({p for item in defs for p in item["static_assert_patterns"]})},
        })
        nodes.extend(defs)
    collected = collected_nodes()
    totals = collection_totals()
    result = {
        "baseline": {"main_sha": FROZEN_MAIN_SHA},
        "collection": {"command": "uv run python -c 'import os,pytest; os.pidfd_open=lambda *a: -1; raise SystemExit(pytest.main([\"--collect-only\",\"-q\"]))'", "collected_node_lines": len(collected), "node_ids": collected, "source_definition_records": len(nodes), **totals},
        "files": files,
        "nodes": nodes,
        "summary": {"test_files": len(files), "test_source_loc": sum(x["loc"] for x in files), "test_nonblank_loc": sum(x["nonblank_loc"] for x in files), "source_test_definitions": len(nodes)},
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
