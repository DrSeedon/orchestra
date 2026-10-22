"""Publish guard (V-1014): strings that must never reach a public repository.

The list lives OUTSIDE git (`data/secrets/forbidden-strings.txt`, one string per line, `#`
comments). Matches are reported by rule number only — the value itself is never printed.
Stdlib only: `scripts/secret_scan.py` imports this module in the pre-push hook.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app import publication_secrets

ENV_VAR = "ORCHESTRA_FORBIDDEN_STRINGS"
REL_PATH = Path("data/secrets/forbidden-strings.txt")


class _RulePath(Path):
    """Keep the caller's repo through the existing load_rules(list_path(repo)) API.

    An explicit list override can live anywhere, so its parent cannot identify the
    project. Per-value context avoids global state and cross-project races.
    """
    def __init__(self, *args, repo: str | Path | None = None):
        super().__init__(*args)
        self.repo = Path(repo).resolve() if repo is not None else None


def list_path(repo: str | Path | None = None) -> Path:
    """Explicit env override, else `data/secrets/` of the main checkout of `repo`
    (worktrees have no `data/`), else of this installation."""
    override = os.environ.get(ENV_VAR)
    if override:
        return _RulePath(override, repo=repo)
    candidates = []
    if repo is not None:
        common = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True,
        )
        if common.returncode == 0 and common.stdout.strip():
            candidates.append(Path(common.stdout.strip()).parent / REL_PATH)
    candidates.append(Path(__file__).resolve().parents[1] / REL_PATH)
    return _RulePath(next((c for c in candidates if c.is_file()), candidates[-1]), repo=repo)


def load_rules(path: Path) -> list[tuple[str, str]]:
    """List entries plus local credentials when path came from list_path(repo).

    secret_scan's existing pre-push call uses exactly this API. A missing stop-list
    must not skip credentials; a plain explicit Path keeps its list-only semantics.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    rules = [
        (f"forbidden-string line {n} of {path.name}", s)
        for n, raw in enumerate(lines, 1)
        if (s := raw.strip()) and not s.startswith("#")
    ]
    repo = getattr(path, "repo", None)
    if repo is not None:
        rules += publication_secrets.literal_rules(repo)
    return list(dict.fromkeys(rules))


def scan_text(text: str, origin: str, rules: list[tuple[str, str]]) -> list[str]:
    return publication_secrets.findings(text, origin, rules)


def scan_patch(patch: str, rules: list[tuple[str, str]]) -> list[str]:
    """Scan added text with destination line numbers, including binary blobs as text."""
    import ast
    import re

    found = []
    path, number, start = "?", 0, 0
    old_left, new_left = 0, 0
    added: list[str] = []

    def flush() -> None:
        found.extend(publication_secrets.content_findings("\n".join(added), path, rules, start))
        added.clear()

    for line in patch.split("\n"):
        # Hunk counts distinguish file headers from added text beginning with ++.
        if old_left or new_left:
            if line.startswith("+"):
                if not added:
                    start = number
                added.append(line[1:])
                number += 1
                new_left -= 1
            elif line.startswith("-"):
                flush()
                old_left -= 1
            elif line.startswith(" "):
                flush()
                number += 1
                new_left -= 1
                old_left -= 1
            continue
        if line.startswith("+++ "):
            flush()
            raw = line[4:]
            path = (ast.literal_eval(raw) if raw.startswith('"') else raw).removeprefix("b/")
            found += scan_text(path, f"{path}:1 (path)", rules)
        elif line.startswith("@@ "):
            flush()
            match = re.match(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if not match:
                raise RuntimeError("publish guard: malformed git diff hunk")
            old_left = int(match[1]) if match[1] is not None else 1
            number = int(match[2])
            new_left = int(match[3]) if match[3] is not None else 1
    flush()
    return found


def scan_range(repo: str | Path, base: str, head: str, rules: list[tuple[str, str]]) -> list[str]:
    """Findings in what `base..head` would publish: commit messages, paths and ADDED lines.
    Removed lines are ignored — deleting a leak must not be blocked."""
    rules = list(dict.fromkeys(rules + publication_secrets.literal_rules(repo)))

    def git(*args: str) -> str:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
        if done.returncode:
            # Git diagnostics may quote a secret-bearing path or commit message.
            raise RuntimeError(f"publish guard: git {args[0]} failed")
        return done.stdout.decode("utf-8", "replace")

    empty = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    if base != empty:
        merge_base = subprocess.run(
            ["git", "-C", str(repo), "merge-base", base, head], capture_output=True,
        )
        if merge_base.returncode not in (0, 1):
            raise RuntimeError("git merge-base failed")
    revisions = (head,) if base == empty else (head, f"^{base}")
    found = []
    # Every introduced commit matters: a later deletion does not remove its secret
    # from published history. Root and merge commits also need their own patches.
    for commit in git("rev-list", *revisions).splitlines():
        message = git("show", "-s", "--format=%B", commit)
        found += publication_secrets.content_findings(message, f"commit {commit} message", rules)
        # Empty files and mode-only changes have no +++ header in a patch.
        for path in git("diff-tree", "--root", "--no-commit-id", "-r", "-m", "--no-renames",
                        "--name-only", "--diff-filter=ACMT", "-z", commit).split("\0"):
            if path:
                found += scan_text(path, f"{path}:1 (path)", rules)
        patch = git("show", "--format=", "--root", "--diff-merges=separate",
                    "--no-ext-diff", "--no-textconv", "--no-renames", "--text", "-U0", commit)
        found += scan_patch(patch, rules)
    return list(dict.fromkeys(found))


def block_message(findings: list[str]) -> str:
    return (
        "PUBLISH GUARD: publication contains a local credential or forbidden string:\n  "
        + "\n  ".join(findings)
        + "\nMove the artifact to .orchestra/private/ or remove the string, then retry."
    )
