"""Sparse (partial) worktrees for workers.

A worker copy of a large repository carries every tracked file, including generated media under
`artifacts/` and the reports of every past task. The rule keeps those directories out of the copy and
adds back only what the task needs: its own directories (by task number), explicitly listed ones, and
directories that tracked sources (KB, tests) point at. Policy lives in the pipeline manifest
(`defaults.worktree.sparse`), not here.

Everything runs through the `git` callable the caller passes (workspace._git_cmd), so the commands go
through the same agent-user path as the rest of worktree handling.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

MARKER = "# orchestra-sparse v1"
_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_TASK_BRANCH = re.compile(r"^task-([^/]+)/")

Git = Callable[..., "object"]


@dataclass
class Rule:
    exclude: list[str]
    include: list[str] = field(default_factory=list)
    own: list[str] = field(default_factory=list)
    reference_scan: list[str] = field(default_factory=list)


def task_id_from_branch(branch: str) -> str:
    m = _TASK_BRANCH.match(branch or "")
    return m.group(1) if m else ""


def resolve_rule(sparse, repo: Path) -> Rule | None:
    """Merge the default rule with the first matching `projects` override. None = sparse is off."""
    if sparse is None or not sparse.enabled:
        return None
    override = None
    for pattern, candidate in sparse.projects.items():
        if fnmatch.fnmatch(str(repo), pattern):
            override = candidate
            break
    if override is not None and override.enabled is False:
        return None
    exclude = list(sparse.exclude if override is None or override.exclude is None else override.exclude)
    own = list(sparse.own if override is None or override.own is None else override.own)
    include = list(sparse.include) + (list(override.include) if override else [])
    scan = list(sparse.reference_scan) + (list(override.reference_scan) if override else [])
    if not exclude:
        return None
    return Rule(exclude=_dirs(exclude), include=_dirs(include), own=own, reference_scan=scan)


def _dirs(items: list[str]) -> list[str]:
    return [i.strip("/") + "/" for i in items if i.strip("/")]


def own_patterns(rule: Rule, task_id: str) -> list[str]:
    if not task_id or not re.fullmatch(_NAME, task_id):
        return []
    return [t.replace("{id}", task_id).strip("/") + "/" for t in rule.own]


def referenced_dirs(rule: Rule, git: Git, repo: Path, ref: str) -> list[str]:
    """Directories under an excluded prefix that tracked sources in `reference_scan` mention
    (`.orchestra/tasks/224`, `../tasks/V-5/report.md`, `".orchestra" / "tasks" / "V-3"`), limited to
    directories that exist at `ref`. A rule instead of a hand-kept list: a new test fixture or KB link
    is picked up by the next spawn."""
    if not rule.reference_scan or not ref:
        return []
    found: list[str] = []
    for prefix in rule.exclude:
        segs = prefix.strip("/").split("/")
        quoted = r"\s*[/,]\s*".join(rf"[\"']{re.escape(s)}[\"']" for s in segs)
        regexes = [
            re.escape(prefix) + rf"({_NAME})",
            r"\.\./" + re.escape(segs[-1]) + rf"/({_NAME})",
            quoted + rf"\s*[/,]\s*[\"']({_NAME})[\"']",
        ]
        grep = git(
            ["git", "grep", "-h", "-o", "-I", "-E", *sum((["-e", r] for r in regexes), []),
             ref, "--", *rule.reference_scan],
            capture_output=True, text=True, cwd=str(repo),
        )
        if grep.returncode not in (0, 1):
            continue
        names = set()
        for line in grep.stdout.splitlines():
            for r in regexes:
                m = re.search(r, line)
                if m:
                    names.add(m.group(1))
        if not names:
            continue
        tree = git(["git", "ls-tree", "-d", "--name-only", ref, prefix],
                   capture_output=True, text=True, cwd=str(repo))
        if tree.returncode != 0:
            continue
        existing = {Path(p).name for p in tree.stdout.splitlines()}
        found += [prefix + n + "/" for n in sorted(names & existing)]
    return found


def build_patterns(rule: Rule, task_id: str, git: Git, repo: Path, ref: str) -> list[str]:
    lines = [f"{MARKER} task={task_id}", f"# rule={json.dumps(asdict(rule), sort_keys=True)}", "/*"]
    lines += [f"!/{p}" for p in rule.exclude]
    lines += [f"/{p}" for p in rule.include]
    lines += [f"/{p}" for p in own_patterns(rule, task_id)]
    lines += [f"/{p}" for p in referenced_dirs(rule, git, repo, ref)]
    return lines


def apply_patterns(wt: Path, patterns: list[str], git: Git) -> str:
    """Write non-cone patterns for this worktree and update its files. Returns '' or an error."""
    done = git(
        ["git", "sparse-checkout", "set", "--no-cone", "--stdin"],
        cwd=str(wt), input="\n".join(patterns) + "\n", capture_output=True, text=True,
    )
    if done.returncode != 0:
        return done.stderr.strip() or done.stdout.strip() or f"exit {done.returncode}"
    return ""


def _patterns_file(wt: Path, git: Git) -> Path | None:
    path = git(["git", "rev-parse", "--git-path", "info/sparse-checkout"],
               cwd=str(wt), capture_output=True, text=True)
    if path.returncode != 0:
        return None
    p = Path(path.stdout.strip())
    return p if p.is_absolute() else wt / p


def _read_patterns(wt: Path, git: Git) -> list[str]:
    p = _patterns_file(wt, git)
    try:
        lines = p.read_text().splitlines() if p else []
    except OSError:
        return []
    return lines if lines and lines[0].startswith(MARKER) else []


def is_orchestra_sparse(wt: Path, git: Git) -> bool:
    return bool(_read_patterns(wt, git))


def current_exclude(wt: Path, git: Git) -> list[str]:
    return [ln[2:] for ln in _read_patterns(wt, git) if ln.startswith("!/")]


def stored_rule(wt: Path, git: Git) -> Rule | None:
    """The rule this worktree was created with (kept in the patterns file), so a task switch
    recomputes with the same rule instead of re-reading a manifest that may have changed."""
    for ln in _read_patterns(wt, git):
        if ln.startswith("# rule="):
            try:
                return Rule(**json.loads(ln[len("# rule="):]))
            except (ValueError, TypeError):
                return None
    return None


def retarget(wt: Path, task_id: str, git: Git, repo: Path) -> str:
    """Recompute own/referenced directories for a new task number in an existing sparse worktree.
    Returns '' (also when the worktree is not an Orchestra sparse one) or an error text."""
    rule = stored_rule(wt, git)
    if rule is None:
        return ""
    return apply_patterns(wt, build_patterns(rule, task_id, git, repo, "HEAD"), git)


def hidden_paths(wt: Path, paths: list[str], git: Git, limit: int = 30) -> list[str]:
    """Subset of `paths` that git refuses to stage because they lie outside the sparse checkout."""
    hidden = []
    for p in paths[:limit]:
        r = git(["git", "add", "-n", "--", p], cwd=str(wt), capture_output=True, text=True)
        if r.returncode != 0 and "sparse" in (r.stderr or "").lower():
            hidden.append(p)
    return hidden


def suggest_dir(path: str, prefixes: list[str]) -> str:
    """Directory to pass to `git sparse-checkout add` for a hidden path."""
    for pre in prefixes:
        pre = pre.strip("/") + "/"
        if path.startswith(pre):
            rest = path[len(pre):].split("/", 1)
            return "/" + pre + (rest[0] + "/" if len(rest) > 1 else "")
    parent = path.rsplit("/", 1)[0] if "/" in path else ""
    return "/" + (parent + "/" if parent else "")
