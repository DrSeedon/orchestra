#!/usr/bin/env python3
"""Classify legacy Orchestra paths and verify pinned historical evidence bindings."""

# LEGACY_PATH_FIXTURE: literals below are rejection targets, never runtime fallbacks.

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


FIELDS = ("stable_id", "git_commit", "source_path", "git_blob", "source_sha256")
DOC_LITERALS = ("docs/kb", "docs/tasks", "docs/workers", "docs/archive")
PIPELINE_LITERAL = "pipelines/"
NEGATIVE_MARKER = "LEGACY_PATH_FIXTURE"
HISTORICAL_FILES = {"CHANGELOG.md"}
HISTORICAL_PREFIXES = ("deploy/",)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def tracked_files(root: Path) -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    return sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)


def exact_occurrences(text: str) -> int:
    total = sum(text.count(literal) for literal in DOC_LITERALS)
    start = 0
    while True:
        offset = text.find(PIPELINE_LITERAL, start)
        if offset < 0:
            break
        if text[max(0, offset - len(".orchestra/")):offset] != ".orchestra/":
            total += 1
        start = offset + len(PIPELINE_LITERAL)
    return total


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
        return [
            str(argument.value)
            for argument in node.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        ]
    return []


def split_python_occurrences(relative: str, text: str) -> int:
    if not relative.endswith(".py"):
        return 0
    try:
        tree = ast.parse(text, relative)
    except SyntaxError:
        return 0
    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        values = _path_constants(node)
        if not values:
            continue
        joined = "/".join(value.strip("/") for value in values if value)
        source = ast.get_source_segment(text, node) or ""
        for literal in (*DOC_LITERALS, PIPELINE_LITERAL):
            normalized = literal.rstrip("/")
            if normalized in joined and literal not in source:
                if normalized == "pipelines" and ".orchestra/pipelines" in joined:
                    continue
                found.add((int(getattr(node, "lineno", 0)), literal))
    return len(found)


def occurrence_class(relative: str, text: str) -> str:
    if relative.startswith(".orchestra/pipelines/"):
        return "deferred"
    if relative.startswith(".orchestra/"):
        return "historical"
    if relative in HISTORICAL_FILES or relative.startswith(HISTORICAL_PREFIXES):
        return "historical"
    if relative.startswith("tests/") or NEGATIVE_MARKER in text:
        return "negative"
    return "live"


def classify_old_paths(root: Path) -> dict[str, object]:
    counts = {"live": 0, "historical": 0, "negative": 0, "deferred": 0}
    live_files: list[str] = []
    for relative in tracked_files(root):
        path = root / relative
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if b"\0" in content:
            continue
        text = content.decode("utf-8", errors="replace")
        occurrences = exact_occurrences(text) + split_python_occurrences(relative, text)
        if not occurrences:
            continue
        category = occurrence_class(relative, text)
        counts[category] += occurrences
        if category == "live":
            live_files.append(relative)
    return {
        "live_old_path_occurrences": counts["live"],
        "historical_old_path_occurrences": counts["historical"],
        "negative_guard_occurrences": counts["negative"],
        "deferred_prompt_occurrences": counts["deferred"],
        "unclassified_old_path_occurrences": counts["live"],
        "live_old_path_files": sorted(set(live_files))[:50],
    }


def _records(root: Path) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for record_path in sorted((root / ".orchestra/kb/records").rglob("*.json")):
        value = json.loads(record_path.read_text(encoding="utf-8"))
        if not set(FIELDS) <= set(value):
            continue
        record = {field: str(value[field]) for field in FIELDS}
        stable_id = record["stable_id"]
        if stable_id in records:
            raise ValueError(f"duplicate historical stable_id: {stable_id}")
        records[stable_id] = record
    return records


def verify_historical_bindings(root: Path) -> dict[str, object]:
    frozen = json.loads(
        (root / ".orchestra/tasks/430/evidence-bindings-frozen.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {str(key): str(value) for key, value in frozen["bindings"].items()}
    records = _records(root)
    current_hashes = {
        stable_id: hashlib.sha256(canonical(records[stable_id])).hexdigest()
        if stable_id in records
        else ""
        for stable_id in expected
    }
    mismatches = {
        stable_id
        for stable_id, expected_hash in expected.items()
        if current_hashes[stable_id] != expected_hash
    }

    selected = [records[stable_id] for stable_id in expected if stable_id in records]
    by_commit: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in selected:
        by_commit[record["git_commit"]].append(record)
    for commit, commit_records in by_commit.items():
        try:
            raw = subprocess.check_output(
                [
                    "git", "ls-tree", "-r", "-z", "--format=%(objectname)%x09%(path)",
                    commit,
                ],
                cwd=root,
            )
        except subprocess.CalledProcessError:
            mismatches.update(record["stable_id"] for record in commit_records)
            continue
        tree = {}
        for item in raw.split(b"\0"):
            if item:
                blob, path = item.split(b"\t", 1)
                tree[path.decode()] = blob.decode()
        for record in commit_records:
            if tree.get(record["source_path"]) != record["git_blob"]:
                mismatches.add(record["stable_id"])

    blobs = sorted({record["git_blob"] for record in selected})
    contents: dict[str, bytes] = {}
    if blobs:
        batch = subprocess.run(
            ["git", "cat-file", "--batch"],
            cwd=root,
            input=b"".join(blob.encode() + b"\n" for blob in blobs),
            capture_output=True,
            check=True,
        ).stdout
        offset = 0
        for expected_blob in blobs:
            header_end = batch.index(b"\n", offset)
            blob, object_type, raw_size = batch[offset:header_end].decode().split()
            size = int(raw_size)
            start = header_end + 1
            end = start + size
            if blob != expected_blob or object_type != "blob" or batch[end:end + 1] != b"\n":
                raise ValueError(f"invalid git cat-file response for {expected_blob}")
            contents[blob] = batch[start:end]
            offset = end + 1
        if offset != len(batch):
            raise ValueError("trailing bytes in git cat-file response")
    for record in selected:
        content = contents.get(record["git_blob"])
        digest = "sha256:" + hashlib.sha256(content or b"").hexdigest()
        if content is None or digest != record["source_sha256"]:
            mismatches.add(record["stable_id"])

    binding_set_sha256 = hashlib.sha256(canonical(dict(sorted(current_hashes.items())))).hexdigest()
    return {
        "historical_path_blob_sha_checked": len(expected),
        "historical_binding_set_sha256": binding_set_sha256,
        "historical_path_blob_sha_mismatches": len(mismatches),
        "historical_mismatch_ids": sorted(mismatches)[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    summary = {
        "schema_version": 1,
        **classify_old_paths(root),
        **verify_historical_bindings(root),
    }
    print(
        json.dumps(summary, ensure_ascii=False, sort_keys=True)
        if args.json
        else "\n".join(f"{key}={value}" for key, value in sorted(summary.items()))
    )
    clean = (
        summary["live_old_path_occurrences"] == 0
        and summary["unclassified_old_path_occurrences"] == 0
        and summary["historical_path_blob_sha_mismatches"] == 0
        and summary["negative_guard_occurrences"] > 0
    )
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
