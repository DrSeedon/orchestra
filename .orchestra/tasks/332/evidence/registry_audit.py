"""Stdlib-only registry/cross-reference inventory for #332 (no app imports/IO)."""
from __future__ import annotations

import ast
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[4]


def source(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def mcp_tools() -> list[dict]:
    path = ROOT / "app/mcp_stdio.py"
    tree = ast.parse(source(path))
    result = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            is_tool = isinstance(dec, ast.Attribute) and dec.attr == "tool"
            is_tool = is_tool or (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "tool"
            )
            if is_tool:
                result.append({"name": node.name, "line": node.lineno})
                break
    return result


def routes() -> list[dict]:
    result = []
    for path in sorted((ROOT / "app/routes").glob("*.py")):
        tree = ast.parse(source(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                if not dec.args or not isinstance(dec.args[0], ast.Constant):
                    continue
                if not isinstance(dec.args[0].value, str):
                    continue
                if dec.func.attr not in {"get", "post", "put", "patch", "delete", "head", "api_route"}:
                    continue
                result.append({"file": path.relative_to(ROOT).as_posix(), "line": node.lineno,
                               "verb": dec.func.attr.upper(), "path": dec.args[0].value,
                               "owner": node.name})
    return sorted(result, key=lambda x: (x["path"], x["verb"], x["file"], x["line"]))


def prompts() -> dict:
    root = ROOT / "pipelines/default"
    manifest = source(root / "pipeline.yaml")
    roles = sorted(re.findall(r"^  ([A-Za-z0-9_-]+):$", manifest, re.M))
    skills = sorted(set(re.findall(r"skills:\s*\[([^\]]*)\]", manifest)))
    skill_names = sorted(set(re.findall(r"[A-Za-z0-9_-]+", " ".join(skills))))
    files = sorted(p.stem for p in (root / "prompts/skills").glob("*.md"))
    modules = sorted(p.stem for p in (root / "prompts/modules").glob("*.md"))
    return {"roles": roles, "skill_names": skill_names, "skill_files": files,
            "skill_files_without_manifest_name": sorted(set(files) - set(skill_names)),
            "module_files": modules}


def js() -> dict:
    html = "\n".join(source(p) for p in (ROOT / "app/templates").glob("*.html"))
    js_paths = sorted((ROOT / "app/static/js").glob("*.js"))
    js_text = "\n".join(source(p) for p in js_paths)
    api_literals = sorted(set(re.findall(r"(?:['\"])(/api/[^'\"]+)", js_text)))
    inline = sorted(set(re.findall(r"onclick=\"[^\"]*?\b([A-Za-z_$][\w$]*)\s*\(", html)))
    definitions = sorted(set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", js_text)))
    assets = sorted(set(re.findall(r"g\.asset\(['\"]([^'\"]+)", html)))
    return {"js_files": [p.relative_to(ROOT).as_posix() for p in js_paths],
            "api_literals": api_literals, "inline_handler_names": inline,
            "js_function_definitions": len(definitions), "template_assets": assets,
            "missing_template_assets": sorted(a for a in assets if not (ROOT / "app/static" / a).is_file()),
            "dead_name_check": {name: len(re.findall(r"(?<![\\w$])" + re.escape(name) + r"(?![\\w$])", js_text))
                                for name in ("deleteOrchestrator", "openDeleteOrchModal", "initProxy")}}


def main() -> None:
    route_rows = routes()
    route_keys = [(r["verb"], r["path"]) for r in route_rows]
    duplicates = sorted({f"{verb} {path}" for verb, path in route_keys if route_keys.count((verb, path)) > 1})
    tracked = __import__("subprocess").check_output(
        ["git", "ls-files"], cwd=ROOT, text=True,
    ).splitlines()
    all_text = "\n".join(
        source(ROOT / rel) for rel in tracked
        if pathlib.Path(rel).suffix in {".py", ".js", ".html", ".md", ".yaml", ".sh"}
        and (ROOT / rel).is_file()
    )
    scripts = []
    for p in sorted((ROOT / "scripts").iterdir()):
        if p.is_file():
            token = p.name
            refs = len(re.findall(re.escape(token), all_text))
            scripts.append({"file": p.relative_to(ROOT).as_posix(), "repo_text_refs": refs})
    print(json.dumps({
        "commit": __import__("subprocess").check_output(["git", "rev-parse", "main"], cwd=ROOT, text=True).strip(),
        "mcp": {"count": len(mcp_tools()), "tools": mcp_tools()},
        "fastapi_ast_registry": {"route_count": len(route_rows), "duplicate_keys": duplicates,
                                  "include_router_files": ["app/main.py"], "routes": route_rows},
        "prompts": prompts(), "js": js(), "scripts": scripts,
        "runtime_registry_ids": ["claude", "codex", "grok", "opencode", "harness"],
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
