#!/usr/bin/env python3
"""Stateless stdlib-only code-intelligence MCP used by frozen experiment #346.

Two read-only tools deliberately stop short of an LSP: a file outline and an exact-name
reference inventory with coarse syntactic classification.  The project root is the server
process cwd.  No config, cache, index, dependency, shell, or write path exists.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path.cwd().resolve()
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "dist", "build", "worktrees",
}
TEXT_SUFFIXES = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".html"}
MAX_FILE_BYTES = 1_000_000
MAX_ROWS = 400


def _response(req_id: Any, result: Any = None, error: Any = None) -> None:
    payload = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _inside(path: str) -> Path:
    candidate = (ROOT / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ValueError(f"path outside project: {path}")
    return candidate


def _files() -> list[Path]:
    found: list[Path] = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        for name in names:
            path = Path(base) / name
            if path.suffix.lower() in TEXT_SUFFIXES:
                try:
                    if path.stat().st_size <= MAX_FILE_BYTES:
                        found.append(path)
                except OSError:
                    continue
    return sorted(found)


def _outline(path_arg: str) -> dict[str, Any]:
    path = _inside(path_arg)
    text = path.read_text(encoding="utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    if path.suffix.lower() in {".py", ".pyi"}:
        tree = ast.parse(text, filename=str(path.relative_to(ROOT)))
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                owner = parents.get(node)
                rows.append({
                    "name": node.name,
                    "kind": type(node).__name__,
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "owner": getattr(owner, "name", None),
                })
    else:
        patterns = [
            ("function", r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\("),
            ("class", r"\bclass\s+([A-Za-z_$][\w$]*)\b"),
            ("binding", r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\b"),
        ]
        for number, line in enumerate(text.splitlines(), 1):
            for kind, pattern in patterns:
                for match in re.finditer(pattern, line):
                    rows.append({"name": match.group(1), "kind": kind, "line": number})
    return {"path": path.relative_to(ROOT).as_posix(), "symbols": rows}


class _PythonRows(ast.NodeVisitor):
    def __init__(self, symbol: str, rel: str, lines: list[str]) -> None:
        self.symbol = symbol
        self.rel = rel
        self.lines = lines
        self.rows: list[dict[str, Any]] = []
        self.parents: list[ast.AST] = []

    def _add(self, node: ast.AST, kind: str) -> None:
        line = getattr(node, "lineno", 0)
        self.rows.append({
            "path": self.rel,
            "line": line,
            "kind": kind,
            "text": self.lines[line - 1].strip() if 0 < line <= len(self.lines) else "",
        })

    def visit(self, node: ast.AST) -> Any:
        self.parents.append(node)
        try:
            return super().visit(node)
        finally:
            self.parents.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == self.symbol:
            self._add(node, "definition")
            for decorator in node.decorator_list:
                self._add(decorator, "decorator_on_definition")
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == self.symbol:
            self._add(node, "definition")
            for decorator in node.decorator_list:
                self._add(decorator, "decorator_on_definition")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == self.symbol:
            parent = self.parents[-2] if len(self.parents) > 1 else None
            if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._add(node, "name_load" if isinstance(node.ctx, ast.Load) else "name_store")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == self.symbol:
            self._add(node, "attribute")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == self.symbol or alias.asname == self.symbol:
                self._add(node, "import")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.rsplit(".", 1)[-1] == self.symbol or alias.asname == self.symbol:
                self._add(node, "import")

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and self.symbol in node.value:
            self._add(node, "string")


def _references(symbol: str, definition_path: str = "") -> dict[str, Any]:
    del definition_path  # reserved for future disambiguation; output stays honest about exact-name scope
    token = re.compile(r"(?<![\w$])" + re.escape(symbol) + r"(?![\w$])")
    rows: list[dict[str, Any]] = []
    for path in _files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if path.suffix.lower() in {".py", ".pyi"}:
            try:
                tree = ast.parse(text, filename=rel)
            except SyntaxError as exc:
                rows.append({"path": rel, "line": exc.lineno or 0, "kind": "syntax_error", "text": str(exc)})
                continue
            visitor = _PythonRows(symbol, rel, lines)
            visitor.visit(tree)
            rows.extend(visitor.rows)
            ast_lines = {row["line"] for row in visitor.rows}
            for number, line in enumerate(lines, 1):
                if number not in ast_lines and token.search(line):
                    rows.append({"path": rel, "line": number, "kind": "comment_or_text", "text": line.strip()})
        else:
            for number, line in enumerate(lines, 1):
                if not token.search(line):
                    continue
                stripped = line.strip()
                if path.suffix.lower() == ".html":
                    kind = "html"
                elif stripped.startswith("//") or "//" in stripped[: stripped.find(symbol) + 1]:
                    kind = "comment_or_text"
                elif re.search(r"\bfunction\s+" + re.escape(symbol) + r"\b", line):
                    kind = "definition"
                elif re.search(r"['\"]" + re.escape(symbol) + r"['\"]", line):
                    kind = "string"
                else:
                    kind = "code"
                rows.append({"path": rel, "line": number, "kind": kind, "text": stripped})
        if len(rows) >= MAX_ROWS:
            break
    unique = {(row["path"], row["line"], row["kind"]): row for row in rows}
    ordered = sorted(unique.values(), key=lambda row: (row["path"], row["line"], row["kind"]))
    return {"symbol": symbol, "scope": "exact-name syntactic and lexical, not binding-resolved", "rows": ordered[:MAX_ROWS]}


TOOLS = [
    {
        "name": "code_outline",
        "description": "Return a compact top-level/nested symbol outline for one Python/JS/TS file. Read-only, no index.",
        "inputSchema": {
            "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
        },
    },
    {
        "name": "code_references",
        "description": "Find and classify exact-name Python/JS/TS/HTML occurrences. Includes definitions, imports, decorators, strings and comments; syntactic/lexical, not binding-resolved. Read-only, no index.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "definition_path": {"type": "string", "default": ""},
            },
            "required": ["symbol"],
        },
    },
]


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "code_outline":
        value = _outline(str(arguments.get("path", "")))
    elif name == "code_references":
        value = _references(str(arguments.get("symbol", "")), str(arguments.get("definition_path", "")))
    else:
        raise ValueError(f"unknown tool: {name}")
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}]}


def main() -> None:
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
            method = request.get("method")
            req_id = request.get("id")
            if method == "initialize":
                _response(req_id, {
                    "protocolVersion": request.get("params", {}).get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "light-codeintel-346", "version": "1"},
                    "instructions": "Use code_outline/code_references for structured navigation; keep native search for wider text and edits.",
                })
            elif method == "tools/list":
                _response(req_id, {"tools": TOOLS})
            elif method == "tools/call":
                params = request.get("params", {})
                _response(req_id, _call(str(params.get("name", "")), params.get("arguments") or {}))
            elif method == "ping":
                _response(req_id, {})
            elif req_id is not None:
                _response(req_id, error={"code": -32601, "message": f"method not found: {method}"})
        except Exception as exc:
            req_id = request.get("id") if isinstance(locals().get("request"), dict) else None
            if req_id is not None:
                _response(req_id, error={"code": -32000, "message": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()

