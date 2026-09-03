#!/usr/bin/env python3
"""Build the reproducible old-path referrer inventory for task #430."""

from __future__ import annotations

import argparse
import ast
import subprocess
from collections import Counter
from pathlib import Path


LITERALS = ("docs/kb", "docs/tasks", "docs/workers", "docs/archive", "pipelines/")
EXTERNAL_DOC_FILES = {
    "docs/banner.png",
    "docs/dashboard.png",
    "docs/orchestrator-vps-onboarding.md",
    "docs/telegram-bot-api.service.template",
    "docs/tg-local-api-setup.md",
}


def tracked_files(root: Path, excluded_prefix: str) -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    paths = sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)
    prefix = excluded_prefix.rstrip("/") + "/"
    return [path for path in paths if path != excluded_prefix and not path.startswith(prefix)]


def classify(relative: str) -> tuple[str, str]:
    if relative.startswith("docs/kb/records/"):
        return "historical_evidence_record", "historical_pinned"
    if relative == "docs/kb/manifest.json":
        return "current_knowledge_manifest", "in_scope"
    if relative.startswith("docs/kb/"):
        return "current_knowledge", "in_scope"
    if relative.startswith("docs/tasks/"):
        return "historical_task_artifact", "historical"
    if relative.startswith("docs/workers/"):
        return "personal_memory", "in_scope"
    if relative.startswith("docs/archive/"):
        return "historical_archive", "historical"
    if relative.startswith("pipelines/"):
        return "shared_prompt_pipeline", "in_scope"
    if relative.startswith("app/"):
        return "app_referrer", "in_scope"
    if relative.startswith("tests/"):
        return "test_referrer", "in_scope"
    if relative.startswith("scripts/"):
        return "script_referrer", "in_scope"
    if relative in {".gitignore", "CLAUDE.md", "README.md"}:
        return "root_contract", "in_scope"
    if relative == "CHANGELOG.md":
        return "historical_changelog", "historical"
    if relative in {"Dockerfile", "TODO.md"}:
        return "root_contract", "in_scope"
    if relative.startswith("deploy/"):
        return "deployment_history", "historical"
    if relative.startswith("docs/portfolio/"):
        return "externalized_portfolio", "delete"
    if relative in EXTERNAL_DOC_FILES:
        return "external_reader_doc", "keep"
    if relative.startswith((
        "docs/artifacts/", "docs/experiments/", "docs/research/", "docs/reviews/",
        "docs/tg-media/",
    )):
        return "moving_task_output", "in_scope"
    if relative.startswith("docs/"):
        return "moving_agent_artifact", "in_scope"
    return "other_referrer", "decision_required"


def exact_rows(relative: str, text: str) -> list[tuple[str, int, str, int]]:
    rows: list[tuple[str, int, str, int]] = []
    for literal in LITERALS:
        offsets: list[int] = []
        start = 0
        while True:
            found = text.find(literal, start)
            if found < 0:
                break
            offsets.append(found)
            start = found + len(literal)
        if not offsets:
            continue
        line = 1
        previous = 0
        per_line: Counter[int] = Counter()
        for offset in offsets:
            line += text.count("\n", previous, offset)
            per_line[line] += 1
            previous = offset
        rows.extend((relative, line_no, literal, count) for line_no, count in per_line.items())
    return rows


def _path_constants(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _path_constants(node.left)
        right = _path_constants(node.right)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Call) and node.args:
        values: list[str] = []
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                values.append(arg.value)
        return values or []
    return []


def split_ast_rows(relative: str, text: str) -> list[tuple[str, int, str, int]]:
    if not relative.endswith(".py"):
        return []
    try:
        tree = ast.parse(text, relative)
    except SyntaxError:
        return []
    found: set[tuple[str, int, str, int]] = set()
    for node in ast.walk(tree):
        values: list[str] | None = None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            values = _path_constants(node)
        elif isinstance(node, (ast.Tuple, ast.List)):
            if all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.elts):
                values = [str(item.value) for item in node.elts]
        if not values:
            continue
        joined = "/".join(value.strip("/") for value in values if value)
        segment = ast.get_source_segment(text, node) or ""
        for literal in LITERALS:
            normalized = literal.rstrip("/")
            if normalized in joined and literal not in segment:
                found.add((relative, int(getattr(node, "lineno", 0)), literal, 1))
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        artifact_dir = Path(__file__).resolve().parent.relative_to(root).as_posix()
    except ValueError as exc:
        raise SystemExit("inventory generator must live inside --root") from exc

    rows: list[tuple[str, int, str, int, str, str, str]] = []
    # Task #430 necessarily spells every legacy literal and contains the generated TSV.
    # Exclude the whole artifact directory dynamically so the same script remains stable after
    # docs/tasks/430 itself moves to .orchestra/tasks/430 and becomes tracked.
    for relative in tracked_files(root, artifact_dir):
        content = (root / relative).read_bytes()
        if b"\0" in content:
            continue
        text = content.decode("utf-8", errors="replace")
        ref_class, owner = classify(relative)
        for path, line, literal, count in exact_rows(relative, text):
            rows.append((path, line, "exact", count, literal, ref_class, owner))
        for path, line, literal, count in split_ast_rows(relative, text):
            rows.append((path, line, "split_ast", count, literal, ref_class, owner))

    rows.sort()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        stream.write("path\tline\tkind\toccurrences\tliteral\treferrer_class\towner_status\n")
        for row in rows:
            stream.write("\t".join(map(str, row)) + "\n")
    print(f"rows={len(rows)} files={len({row[0] for row in rows})} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
