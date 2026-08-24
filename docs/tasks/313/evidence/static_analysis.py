#!/usr/bin/env python3
"""Static candidate generation and suite-cost metrics for #313.

Signals are deliberately non-verdict: each candidate needs production-path and
mutation evidence before any future cleanup.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TESTS = ROOT / "tests"
OUT = ROOT / "docs/tasks/313/evidence/static-signals.json"
CLUSTERS = ROOT / "docs/tasks/313/clusters.json"


def dotted(n: ast.AST | None) -> str:
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        p = dotted(n.value)
        return f"{p}.{n.attr}" if p else n.attr
    return ""


def norm_source(src: str) -> str:
    src = re.sub(r"#.*", "", src)
    src = re.sub(r"\s+", " ", src)
    return src.strip()


def token_set(src: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*|\d+|[^\sA-Za-z_0-9]", src))


def node_name(parents: list[str], name: str) -> str:
    return "::".join([*parents, name])


def imports(tree: ast.Module) -> dict[str, str]:
    result = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith(("app", "scripts")):
                    result[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(("app", "scripts")):
            for a in n.names:
                if a.name == "*":
                    result["*"] = n.module
                else:
                    result[a.asname or a.name] = f"{n.module}.{a.name}"
    return result


def markers(node: ast.AST) -> list[str]:
    result = []
    for d in getattr(node, "decorator_list", []):
        text = ast.unparse(d)
        if "pytest.mark" in text:
            result.append(text)
    return result


def signals(node: ast.AST, source: str) -> list[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Assert):
            out.add("assert")
            if isinstance(n.test, ast.Call) and dotted(n.test.func) in {"all", "any"}:
                out.add(f"{dotted(n.test.func)}_aggregate")
            if isinstance(n.test, ast.Compare):
                text = ast.unparse(n.test)
                if any(x in text for x in ("len(", ".count(", "==", "!=", "is None")):
                    out.add("representation_or_cardinality")
        if isinstance(n, ast.Call):
            fn = dotted(n.func)
            if fn.endswith(("MagicMock", "AsyncMock")):
                out.add("mock_double")
            if fn.endswith("wait_for") or fn.endswith("sleep"):
                out.add("wall_clock_wait")
            if fn.endswith("getsource"):
                out.add("inspect_source")
            if fn.endswith("TestClient") or fn.startswith("page.") or fn.startswith("browser"):
                out.add("browser_or_client")
            if fn.endswith("subprocess.run") or fn.endswith("check_output") or fn.endswith("Popen"):
                out.add("subprocess")
        if isinstance(n, ast.Attribute) and n.attr in {"argv", "route", "query_selector", "locator", "content", "inner_text"}:
            out.add("source_argv_dom_shape")
    for literal, label in {
        "__file__": "source_argv_dom_shape",
        "route.count": "source_argv_dom_shape",
        "inspect.getsource": "inspect_source",
        "query_selector": "source_argv_dom_shape",
        "assert_called_once": "call_shape",
        "assert_has_calls": "call_shape",
    }.items():
        if literal in source:
            out.add(label)
    return sorted(out)


def fixture_calls(node: ast.AST) -> list[str]:
    args = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args.extend(a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs)
    return args


def get_test_records(path: Path, tree: ast.Module) -> list[dict[str, object]]:
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    records = []
    parents: list[str] = []

    class V(ast.NodeVisitor):
        def visit_ClassDef(self, n: ast.ClassDef) -> None:
            parents.append(n.name)
            self.generic_visit(n)
            parents.pop()

        def _fn(self, n: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            if not n.name.startswith("test"):
                return
            src = "".join(lines[n.lineno - 1 : getattr(n, "end_lineno", n.lineno)])
            name = node_name(parents, n.name)
            body_dump = ast.dump(ast.Module(body=n.body, type_ignores=[]), include_attributes=False)
            records.append({
                "node": f"{path.relative_to(ROOT).as_posix()}::{name}",
                "file": path.relative_to(ROOT).as_posix(),
                "name": name,
                "line": n.lineno,
                "end_line": getattr(n, "end_lineno", n.lineno),
                "loc": getattr(n, "end_lineno", n.lineno) - n.lineno + 1,
                "markers": markers(n),
                "fixture_args": fixture_calls(n),
                "file_imports_ref": path.relative_to(ROOT).as_posix(),
                "signals": signals(n, src),
                "body_hash": hashlib.sha256(body_dump.encode()).hexdigest(),
                "normalized_source": norm_source(src),
            })

        visit_FunctionDef = _fn
        visit_AsyncFunctionDef = _fn

    V().visit(tree)
    return records


def main() -> None:
    records = []
    file_rows = []
    for path in sorted(TESTS.glob("*.py")):
        text = path.read_text()
        tree = ast.parse(text, filename=str(path))
        rows = get_test_records(path, tree)
        records.extend(rows)
        file_rows.append({
            "file": path.relative_to(ROOT).as_posix(),
            "loc": len(text.splitlines()),
            "nonblank_loc": sum(bool(x.strip()) for x in text.splitlines()),
            "tests": len(rows),
            "fixtures": sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and any("fixture" in x for x in markers(n))),
            "imported_production_symbols": imports(tree),
        })
    exact = defaultdict(list)
    for r in records:
        exact[r["body_hash"]].append(r["node"])
    exact_clusters = [v for v in exact.values() if len(v) > 1]

    near = []
    # Lower-bound candidate generation: compare only same-file tests and avoid
    # reporting very short bodies where similarity is mostly boilerplate.
    by_file = defaultdict(list)
    for r in records:
        by_file[r["file"]].append(r)
    for rows in by_file.values():
        token_rows = [(r, token_set(r["normalized_source"])) for r in rows]
        for i, (left, left_tokens) in enumerate(token_rows):
            if len(left["normalized_source"]) < 100:
                continue
            for right, right_tokens in token_rows[i + 1 :]:
                if len(right["normalized_source"]) < 100:
                    continue
                if not (0.75 <= len(left["normalized_source"]) / len(right["normalized_source"]) <= 1.33):
                    continue
                union = left_tokens | right_tokens
                ratio = len(left_tokens & right_tokens) / len(union) if union else 1.0
                if ratio >= 0.92:
                    near.append({"left": left["node"], "right": right["node"], "ratio": round(ratio, 4)})

    signal_counts = Counter(s for r in records for s in r["signals"])
    marker_counts = Counter(m for r in records for m in r["markers"])
    clusters = {
        "exact_body_hash_clusters": exact_clusters,
        "near_duplicate_lower_bound": near,
        "signal_counts": dict(sorted(signal_counts.items())),
        "marker_counts": dict(sorted(marker_counts.items())),
    }
    CLUSTERS.write_text(json.dumps(clusters, ensure_ascii=False, indent=2) + "\n")
    result = {
        "method": "AST static candidate generation; exact body hashes are lower bound; near duplicates are not deletion proof",
        "summary": {
            "files": len(file_rows),
            "source_test_definitions": len(records),
            "source_test_loc": sum(x["loc"] for x in file_rows),
            "nonblank_test_loc": sum(x["nonblank_loc"] for x in file_rows),
            "exact_duplicate_clusters": len(exact_clusters),
            "exact_duplicate_nodes_in_clusters": sum(len(x) for x in exact_clusters),
            "near_duplicate_pairs_lower_bound": len(near),
        },
        "files": file_rows,
        "tests": records,
        "clusters": clusters,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
