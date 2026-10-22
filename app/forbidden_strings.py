"""Publish guard (V-1014): strings that must never reach a public repository.

The list lives OUTSIDE git (`data/secrets/forbidden-strings.txt`, one string per line, `#`
comments). Matches are reported by rule number only — the value itself is never printed.
Stdlib only: `scripts/secret_scan.py` imports this module in the pre-push hook.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ENV_VAR = "ORCHESTRA_FORBIDDEN_STRINGS"
REL_PATH = Path("data/secrets/forbidden-strings.txt")


def list_path(repo: str | Path | None = None) -> Path:
    """Explicit env override, else `data/secrets/` of the main checkout of `repo`
    (worktrees have no `data/`), else of this installation."""
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override)
    candidates = []
    if repo is not None:
        common = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True,
        )
        if common.returncode == 0 and common.stdout.strip():
            candidates.append(Path(common.stdout.strip()).parent / REL_PATH)
    candidates.append(Path(__file__).resolve().parents[1] / REL_PATH)
    return next((c for c in candidates if c.is_file()), candidates[-1])


def load_rules(path: Path) -> list[tuple[str, str]]:
    """`(rule name, forbidden string)`; the name carries the line number, not the value."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [
        (f"forbidden-string line {n} of {path.name}", s)
        for n, raw in enumerate(lines, 1)
        if (s := raw.strip()) and not s.startswith("#")
    ]


def scan_text(text: str, origin: str, rules: list[tuple[str, str]]) -> list[str]:
    return [f"{origin}: {name}" for name, value in rules if value in text]


def scan_range(repo: str | Path, base: str, head: str, rules: list[tuple[str, str]]) -> list[str]:
    """Findings in what `base..head` would publish: commit messages, paths and ADDED lines.
    Removed lines are ignored — deleting a leak must not be blocked."""
    if not rules:
        return []

    def git(*args: str) -> str:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
        if done.returncode:
            raise RuntimeError(f"git {args[0]} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
        return done.stdout.decode("utf-8", "replace")

    findings = scan_text(git("log", "--format=%B", f"{base}..{head}"), "commit message", rules)
    merge_base = subprocess.run(
        ["git", "-C", str(repo), "merge-base", base, head], capture_output=True,
    )
    if merge_base.returncode not in (0, 1):
        raise RuntimeError(
            f"git merge-base failed: {merge_base.stderr.decode('utf-8', 'replace').strip()}"
        )
    # Unrelated histories publish the worker's entire tree, including shared lines.
    diff_refs = (
        ("4b825dc642cb6eb9a060e54bf8d69288fbee4904", head)
        if merge_base.returncode == 1 else (f"{base}...{head}",)
    )
    patch = git("diff", "--no-renames", "-U0", *diff_refs)
    path, added = "?", []
    for line in patch.splitlines():
        if line.startswith("+++ "):
            path = line[4:].removeprefix("b/")
            findings += scan_text(path, f"path {path}", rules)
        elif line.startswith("+") and not line.startswith("+++"):
            added.append((path, line[1:]))
    seen = set()
    for file, text in added:
        for f in scan_text(text, file, rules):
            if f not in seen:
                seen.add(f)
                findings.append(f)
    return findings


def block_message(findings: list[str]) -> str:
    return (
        "PUBLISH GUARD (V-1014): the change contains a string from the forbidden list "
        "(kept outside git, data/secrets/forbidden-strings.txt):\n  "
        + "\n  ".join(findings)
        + "\nMove the artifact to .orchestra/private/ or remove the string, then retry."
    )
