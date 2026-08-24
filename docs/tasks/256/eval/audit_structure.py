#!/usr/bin/env python3
"""Mechanical, read-only structure/freshness audit for Orchestra knowledge stores."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


EXCLUDED_DIRS = {
    ".git", ".claude", ".gemini", ".kiro", ".github", ".serena",
    ".claude-plugin", "node_modules", "__pycache__", ".venv", "worktrees",
}
EXCLUDED_RE = re.compile(r"codex-review.*\.md$")


def run(*args: str, cwd: Path) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def indexable_files(root: Path) -> list[Path]:
    candidates = [
        path for path in root.rglob("*.md")
        if not any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts)
        and not EXCLUDED_RE.search(path.name)
    ]
    proc = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--stdin", "-z"],
        input=b"\0".join(str(path).encode() for path in candidates),
        capture_output=True,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(proc.stderr.decode(errors="replace"))
    ignored = {Path(value) for value in proc.stdout.decode(errors="replace").split("\0") if value}
    return sorted(path for path in candidates if path not in ignored)


def audit_index(root: Path, db_path: Path) -> dict:
    disk = indexable_files(root)
    disk_hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in disk
    }
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT path, sha256 FROM files WHERE project=?", (str(root),)
        ).fetchall()
    finally:
        conn.close()
    indexed = dict(rows)
    missing = sorted(path for path in disk_hashes if path not in indexed)
    stale = sorted(path for path, sha in disk_hashes.items() if indexed.get(path) not in (None, sha))
    orphaned = sorted(path for path in indexed if path not in disk_hashes)
    current = sorted(path for path, sha in disk_hashes.items() if indexed.get(path) == sha)
    return {
        "scope": str(root),
        "indexable_markdown": len(disk_hashes),
        "indexed_rows": len(indexed),
        "current_rows": len(current),
        "missing_rows": len(missing),
        "stale_rows": len(stale),
        "orphaned_index_rows": len(orphaned),
        "integration_freshness_debt": len(missing) + len(stale),
        "current_coverage": len(current) / len(disk_hashes) if disk_hashes else None,
        "missing_paths": missing,
        "stale_paths": stale,
        "orphaned_index_paths": orphaned,
    }


def audit_kb(worktree: Path) -> dict:
    kb = worktree / "docs/kb"
    readme = (kb / "README.md").read_text(encoding="utf-8")
    topic_files = sorted(path for path in kb.glob("*.md") if path.name != "README.md")
    targets = re.findall(r"\[[^]]+\]\(([^)]+\.md)\)", readme)
    target_counts = Counter(targets)
    unlisted = [path.name for path in topic_files if path.name not in target_counts]
    missing = [target for target in targets if not (kb / target).is_file()]

    exact_claims: dict[str, list[str]] = defaultdict(list)
    for path in topic_files:
        section = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line in ("## Установлено", "## Отвергнуто"):
                section = line
                continue
            if line.startswith("## "):
                section = None
            if section and line.startswith("- "):
                claim = re.sub(r"\s+", " ", line[2:].split(" · ", 1)[0]).strip().casefold()
                exact_claims[claim].append(path.name)
    duplicates = {
        claim: paths for claim, paths in exact_claims.items()
        if len(set(paths)) > 1
    }
    return {
        "topic_files": len(topic_files),
        "readme_topic_links": len(targets),
        "unique_readme_targets": len(target_counts),
        "unlisted_topic_files": unlisted,
        "orphan_topic_file_rate": len(unlisted) / len(topic_files) if topic_files else None,
        "missing_topic_targets": missing,
        "duplicate_readme_targets": {
            target: count for target, count in target_counts.items() if count > 1
        },
        "exact_duplicate_claims_cross_topic_lower_bound": duplicates,
    }


def audit_promotion(worktree: Path) -> dict:
    created = run(
        "git", "log", "--format=%H", "--diff-filter=A", "--", "docs/kb/README.md",
        cwd=worktree,
    ).splitlines()
    if not created:
        raise RuntimeError("docs/kb/README.md creation commit not found")
    contract_commit = created[-1]
    paths = run(
        "git", "diff", "--name-only", f"{contract_commit}^..HEAD", "--",
        "docs/tasks/*/research.md", cwd=worktree,
    ).splitlines()
    kb_text = "\n".join(
        path.read_text(encoding="utf-8") for path in (worktree / "docs/kb").glob("*.md")
    )
    linked = [path for path in paths if path in kb_text]
    unlinked = [path for path in paths if path not in kb_text]
    return {
        "contract_commit": contract_commit,
        "changed_research_files_since_contract_inclusive": paths,
        "denominator": len(paths),
        "source_linked": linked,
        "source_unlinked": unlinked,
        "source_link_coverage": len(linked) / len(paths) if paths else None,
        "unlinked_research_rate": len(unlinked) / len(paths) if paths else None,
        "semantic_promotion_recall": None,
        "promotion_recall_upper_bound_if_valid_promotion_requires_source_link": (
            len(linked) / len(paths) if paths else None
        ),
        "counting_rule": "research.md paths changed from README creation commit (inclusive) through HEAD; linked iff exact path occurs anywhere in docs/kb/*.md",
        "semantic_limit": "A source-path occurrence, including in ## Источники, does not prove that a specific atomic conclusion was integrated. Atomic fact IDs/anchors were not recorded historically, so semantic promotion recall is unmeasured.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--scope-root", type=Path, required=True)
    parser.add_argument("--vec-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    scope_root = args.scope_root.resolve()
    prompt = worktree / "pipelines/default/prompts/modules/memory-search.md"
    readme = worktree / "docs/kb/README.md"
    agents = worktree / "AGENTS.md"
    artifact = {
        "schema": "orchestra-kb-structure-audit-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": run("git", "rev-parse", "HEAD", cwd=worktree),
        "kb": audit_kb(worktree),
        "promotion": audit_promotion(worktree),
        "index": audit_index(scope_root, args.vec_db.resolve()),
        "prompt_footprint_bytes": {
            "memory_search_module": prompt.stat().st_size,
            "kb_readme_cold_gate": readme.stat().st_size,
            "mandatory_memory_instruction_plus_readme": prompt.stat().st_size + readme.stat().st_size,
            "full_project_agents_md": agents.stat().st_size if agents.exists() else None,
        },
    }
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
