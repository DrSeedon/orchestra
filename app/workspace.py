"""Worktree management — create and remove git worktrees for agent sessions."""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import subprocess
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, NotRequired, TypedDict

if TYPE_CHECKING:
    # Только для аннотаций (строковые аннотации + from __future__ import annotations):
    # рантайм-импорт не нужен, объекты приходят готовыми от вызывающего. Так избегаем
    # циклической зависимости (pipeline ← workspace).
    from app.pipeline import Symlink, Worktree as WorktreeCfg

logger = logging.getLogger(__name__)

WORKTREE_ROOT = Path(__file__).parent.parent / "worktrees"
# Files copied into each new worktree so workers get project config without
# being on the main branch (CLAUDE.md = project rules, .env = secrets, .mcp.json = tools)
PROJECT_FILES = ("CLAUDE.md", ".worktreeinclude", ".mcp.json", ".env")


@dataclass
class Worktree:
    path: str
    branch: str
    branch_created: bool = False
    initial_head: str = ""


class MergeOutcome(TypedDict):
    ok: bool
    state: Literal["merged", "conflict", "failed", "partial"]
    commit_point: Literal["not_reached", "rolled_back", "target_committed", "unknown"]
    target_branch: str
    target_before: str
    target_after: str
    worker_branch: str
    worker_head: str
    conflicts: list[str]
    error: NotRequired[str]
    commits_merged: NotRequired[int]
    branch: NotRequired[str]
    merged_commits: NotRequired[dict[str, list[dict]]]


def _slugify(s: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]", "-", s).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug.lower()[:80]


_TASK_ID_RE = re.compile(r"^([A-Z]{2,5})-(\d+)$", re.IGNORECASE)
_TASK_ID_BARE = re.compile(r"^(\d+)$")


def _normalize_task_id(task_id: str) -> str:
    tid = task_id.strip().lstrip("#")
    m = _TASK_ID_RE.match(tid)
    if m:
        n = int(m.group(2))
        if n < 1:
            raise ValueError(f"Invalid task_id '{task_id}': number must be >= 1")
        return str(n)
    m = _TASK_ID_BARE.match(tid)
    if m:
        n = int(m.group(1))
        if n < 1:
            raise ValueError(f"Invalid task_id '{task_id}': number must be >= 1")
        return str(n)
    raise ValueError(f"Invalid task_id '{task_id}': expected number, #N, or PREFIX-N (legacy)")


def _within(child: Path, *roots: Path) -> bool:
    """True, если резолвнутый ``child`` лежит внутри одного из ``roots`` (или равен).

    Защита от symlink-побега: строковый валидатор (:class:`Symlink`/``copies``) ловит
    abs/``..`` в спеке, но если сам ``repo/docs_work`` — симлинк наружу, путь после
    ``resolve()`` уйдёт за границу. Здесь проверяем уже резолвнутый реальный путь.
    """
    rc = child.resolve()
    for root in roots:
        rr = root.resolve()
        if rc == rr or rr in rc.parents:
            return True
    return False


def _resolve_src(repo: Path, rel: str) -> Path | None:
    """Резолв source: ``repo/rel`` → fallback ``repo.parent/rel``. None если нет/побег.

    Возвращает существующий путь, лежащий внутри ``repo`` или ``repo.parent``.
    Симлинк, уводящий за обе границы, отбрасывается (containment по resolve()).
    """
    for base in (repo, repo.parent):
        cand = base / rel
        if cand.exists() and _within(cand, repo, repo.parent):
            return cand
    return None


def _apply_symlink(repo: Path, wt_path: Path, sl: "Symlink") -> None:
    """Создать симлинк ``wt_path/sl.target`` → source внутри/рядом с repo.

    source резолвится как ``repo/sl.source`` с fallback ``repo.parent/sl.source``
    (та же логика, что у copies: docs_work лежит в основном репо, gitignored).
    Несуществующий source → warning + пропуск (worktree не падает, как у copies).
    Пути sl.source/sl.target уже провалидированы pydantic (:class:`Symlink`);
    дополнительно проверяем resolved-containment (symlink-побег).
    """
    src = _resolve_src(repo, sl.source)
    if src is None:
        logger.warning("symlink source '%s' not found/escapes (repo=%s) — skipped", sl.source, repo)
        return
    target = wt_path / sl.target
    if not _within(target.parent, wt_path):
        raise ValueError(f"symlink target '{sl.target}' escapes worktree")
    os.symlink(str(src), str(target))


def _git_cmd(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run command as agent user if ORCHESTRA_AGENT_UID is set (cap_drop=ALL workaround)."""
    agent_uid = os.environ.get("ORCHESTRA_AGENT_UID")
    if agent_uid:
        import shutil as _sh
        gosu = _sh.which("gosu")
        if gosu:
            args = [gosu, agent_uid] + args
    return subprocess.run(args, **kwargs)


def _merge_conflict_result(branch: str, conflicts: list[str]) -> dict[str, object]:
    shown = ", ".join(conflicts[:10])
    if len(conflicts) > 10:
        shown += f" … and {len(conflicts) - 10} more"
    return {
        "ok": False,
        "state": "conflict",
        "conflicts": conflicts,
        "error": f"merge conflict in {len(conflicts)} file(s): {shown}",
        "branch": branch,
    }


def _conflict_paths(cwd: str) -> list[str]:
    result = _git_cmd(
        ["git", "diff", "--name-only", "--diff-filter=U", "-z"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [path for path in result.stdout.split("\0") if path]


def _repo_lock_path(repo: str | Path) -> Path:
    """Stable cross-process lock identity for one Git common directory."""
    repo_path = Path(repo).resolve()
    common = _git_cmd(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(repo_path), capture_output=True, text=True,
    )
    if common.returncode != 0:
        detail = common.stderr.strip() or common.stdout.strip() or f"exit {common.returncode}"
        raise RuntimeError(f"cannot resolve git common dir for {repo_path}: {detail}")
    common_dir = Path(common.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo_path / common_dir
    common_dir = common_dir.resolve()
    digest = hashlib.sha256(os.fsencode(str(common_dir))).hexdigest()[:24]
    return common_dir / f"orchestra-repo-{digest}.lock"


@contextmanager
def repo_mutation_lock(repo: str | Path):
    """Serialize one standalone Git mutation for a repository across processes.

    Mutation helpers already acquire this lock. Callers must not wrap those helpers,
    because a second descriptor can block on the caller's own ``flock``.
    """
    lock_path = _repo_lock_path(repo)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    with os.fdopen(fd, "a+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _inspect_branch_ref(repo: Path, branch: str) -> str | None:
    ref = f"refs/heads/{branch}"
    exists = _git_cmd(
        ["git", "show-ref", "--verify", "--quiet", ref],
        cwd=str(repo), capture_output=True, text=True,
    )
    if exists.returncode == 0:
        current = _git_cmd(
            ["git", "rev-parse", ref], cwd=str(repo), capture_output=True, text=True,
        )
        if current.returncode != 0:
            detail = current.stderr.strip() or current.stdout.strip()
            raise RuntimeError(f"cannot resolve branch '{branch}': {detail}")
        return current.stdout.strip()
    if exists.returncode != 1:
        detail = exists.stderr.strip() or exists.stdout.strip() or f"exit {exists.returncode}"
        raise RuntimeError(f"cannot inspect branch '{branch}': {detail}")
    return None


def _resolve_commit_oid(repo: Path, ref: str) -> str:
    start = _git_cmd(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=str(repo), capture_output=True, text=True,
    )
    if start.returncode != 0:
        detail = start.stderr.strip() or start.stdout.strip() or f"exit {start.returncode}"
        raise RuntimeError(f"cannot resolve branch start '{ref}': {detail}")
    return start.stdout.strip()


def repo_root(path: str) -> str:
    """Repository that owns ``path``, asked of Git — never guessed from the directory layout.

    One scope can hold several independent repositories (seedon keeps `site/` and `infra/`
    inside the project directory, each with its own origin), so "same directory tree" and
    "same repository" are different questions (#67, #69).
    """
    return str(_resolve_repo(path, path))


def _create_branch_ref(repo: Path, branch: str, initial_oid: str) -> None:
    created = _git_cmd(
        ["git", "update-ref", f"refs/heads/{branch}", initial_oid, ""],
        cwd=str(repo), capture_output=True, text=True,
    )
    if created.returncode != 0:
        detail = created.stderr.strip() or created.stdout.strip() or f"exit {created.returncode}"
        raise RuntimeError(f"cannot create branch '{branch}': {detail}")


def _worktree_registered(repo: Path, worktree: Path) -> bool:
    listed = _git_cmd(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(repo), capture_output=True, text=True,
    )
    if listed.returncode != 0:
        detail = listed.stderr.strip() or listed.stdout.strip() or f"exit {listed.returncode}"
        raise RuntimeError(f"cannot inspect worktree registry: {detail}")
    wanted = worktree.resolve()
    return any(
        Path(line[len("worktree "):]).resolve() == wanted
        for line in listed.stdout.splitlines()
        if line.startswith("worktree ")
    )


def validate_repo_root(repo_path: str) -> Path:
    """Return the exact primary Git repository root or fail before Git discovery can climb."""
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        raise ValueError(f"repo_path does not exist: {repo_path}")

    bare_check = _git_cmd(
        ["git", "rev-parse", "--is-bare-repository"],
        cwd=str(repo), capture_output=True, text=True,
    )
    if bare_check.returncode != 0:
        # Git exits 128 both for "not a repository" and for "refuses to work here"
        # (dubious ownership, unreadable .git). Asserting the first one hides the
        # second and sends the caller chasing branches that exist.
        detail = bare_check.stderr.strip() or bare_check.stdout.strip() or f"exit {bare_check.returncode}"
        raise ValueError(f"git cannot read repo_path {repo_path}: {detail}")
    if bare_check.stdout.strip() == "true":
        raise ValueError(
            f"repo_path is a bare Git repository; a primary working tree is required: {repo_path}"
        )

    top_check = _git_cmd(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(repo), capture_output=True, text=True,
    )
    if top_check.returncode != 0:
        detail = top_check.stderr.strip() or top_check.stdout.strip() or f"exit {top_check.returncode}"
        raise ValueError(f"git cannot read the working tree at {repo_path}: {detail}")
    discovered_root = Path(top_check.stdout.strip()).resolve()
    if discovered_root != repo:
        raise ValueError(
            f"repo_path must be the Git repository root: {repo_path} "
            f"(discovered root: {discovered_root})"
        )

    expected_common = repo / ".git"
    common_check = _git_cmd(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(repo), capture_output=True, text=True,
    )
    if common_check.returncode != 0:
        detail = common_check.stderr.strip() or common_check.stdout.strip() or f"exit {common_check.returncode}"
        raise ValueError(f"git cannot read the git dir at {repo_path}: {detail}")
    common_dir = Path(common_check.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    if (
        not expected_common.is_dir()
        or expected_common.is_symlink()
        or common_dir.resolve() != expected_common.resolve()
    ):
        raise ValueError(
            "repo_path must be a primary Git repository root; "
            "linked worktrees, gitfile repositories, and external Git directories "
            f"are not supported: {repo_path}"
        )
    return repo


def resolve_base_branch(repo_path: str, requested: str = "") -> str:
    """Return a verified local base branch without consulting the current checkout."""
    repo = _resolve_repo(repo_path, repo_path)
    branch = requested.strip()
    if branch.startswith("refs/heads/"):
        branch = branch.removeprefix("refs/heads/")
    elif branch.startswith("refs/"):
        raise ValueError(f"base branch must be a local branch, got '{requested}'")

    if branch:
        valid = _git_cmd(
            ["git", "check-ref-format", "--branch", branch],
            cwd=str(repo), capture_output=True, text=True,
        )
        if valid.returncode != 0 or _inspect_branch_ref(repo, branch) is None:
            raise ValueError(f"local base branch '{branch}' does not exist in {repo}")
        return branch

    remote_heads = _git_cmd(
        ["git", "for-each-ref", "--format=%(refname)%09%(symref)", "refs/remotes"],
        cwd=str(repo), capture_output=True, text=True,
    )
    symbolic_targets: set[str] = set()
    if remote_heads.returncode == 0:
        for line in remote_heads.stdout.splitlines():
            refname, _, symref = line.partition("\t")
            if not refname.endswith("/HEAD") or not symref:
                continue
            prefix = refname.removesuffix("HEAD")
            if symref.startswith(prefix):
                symbolic_targets.add(symref.removeprefix(prefix))
    if symbolic_targets:
        if len(symbolic_targets) != 1:
            raise ValueError(
                "repository has conflicting symbolic remote HEAD branches; "
                "pass base_branch explicitly"
            )
        remote_branch = symbolic_targets.pop()
        if _inspect_branch_ref(repo, remote_branch) is None:
            raise ValueError(
                f"symbolic remote HEAD points to '{remote_branch}', but no matching "
                "local branch exists; pass base_branch explicitly"
            )
        return remote_branch

    well_known = []
    for candidate in ("main", "master"):
        if _inspect_branch_ref(repo, candidate) is not None:
            well_known.append(candidate)
    if len(well_known) == 1:
        return well_known[0]
    detail = "both main and master exist" if well_known else "no main or master branch exists"
    raise ValueError(f"cannot resolve repository mainline: {detail}; pass base_branch explicitly")


def _copy_file(src: Path, dst: Path) -> None:
    """Copy through the agent-user command path and fail loudly on errors."""
    result = _git_cmd(
        ["cp", "-p", str(src), str(dst)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise OSError(f"copy {src} -> {dst} failed: {detail}")


# Injected / machine-local artifacts that must never dirty the tree or block merge_worker:
# `.claude/` (injected skills+settings), and Codex session metadata written by codex_review
# (`codex_sessions.json` = thread UUIDs, `*.round` = per-round temp before append).
# AGENTS.md is mirrored from CLAUDE.md for codex workers (see create_worktree). Exclude so
# it doesn't dirty the tree / block merge. info/exclude only affects UNTRACKED files, so a
# repo that tracks its own AGENTS.md is unaffected (and we never overwrite an existing one).
_WORKTREE_EXCLUDES = (".claude/", ".codex/", "codex_sessions.json", "*.round", "AGENTS.md")


def tracked_paths(worktree_path: str | Path, rels: list[str]) -> set[str]:
    """Which of ``rels`` (worktree-relative file paths) are in this repo's index.

    Everything Orchestra writes into a worker's worktree must ask this first: ignore rules
    (`.gitignore`, `info/exclude`) do NOT apply to tracked files, so writing over one dirties
    the worker's tree permanently and blocks every merge — the worker cannot clean up work
    it never did. Git failing to answer is raised, not guessed: the caller decides.
    """
    if not rels:
        return set()
    result = _git_cmd(
        ["git", "-C", str(worktree_path), "ls-files", "-z", "--", *rels],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"git ls-files failed in {worktree_path}: {detail}")
    return {p for p in result.stdout.split("\0") if p}


def sync_agents_md(worktree_path: str) -> bool:
    """Mirror CLAUDE.md → AGENTS.md: Codex CLI reads project instructions from AGENTS.md only.

    Re-runs on every backend (re)connect, not just at worktree creation — a long-lived worker
    would otherwise keep the CLAUDE.md snapshot from the day it was spawned.
    A git-TRACKED AGENTS.md belongs to the repo (Orchestra is public — a third-party project
    may ship one) → left alone. mtime is useless here (the copy is always newer), compare bytes.
    """
    wt = Path(worktree_path)
    claude_md = wt / "CLAUDE.md"
    agents_md = wt / "AGENTS.md"
    if not claude_md.is_file():
        return False
    # Native Claude imports the canonical AGENTS.md. Mirroring this adapter back
    # into its own target would replace the rules with a circular import.
    if re.search(r"(?m)^@(?:\./)?AGENTS\.md\s*$", claude_md.read_text()):
        if not agents_md.is_file():
            raise RuntimeError(f"CLAUDE.md imports missing AGENTS.md in {wt}")
        return False
    try:
        tracked = tracked_paths(wt, ["AGENTS.md"])
    except RuntimeError as exc:
        # Git failing (not a repo, ownership, broken worktree) proves nothing about the
        # file — don't overwrite on a guess. A stale mirror is survivable; a clobbered
        # repo file is not.
        logger.warning(f"{exc} — AGENTS.md mirror skipped")
        return False
    if tracked:
        logger.info(f"AGENTS.md is tracked by the repo at {wt} — mirror skipped")
        return False
    if agents_md.is_symlink():
        logger.warning(f"AGENTS.md in {wt} is a symlink — mirror skipped (copy would clobber its target)")
        return False
    # Old worktrees predate AGENTS.md joining the exclude list — do this even when the mirror is
    # already current, otherwise it keeps showing up as untracked junk and can block merge.
    _exclude_worktree_artifacts(wt)
    if agents_md.exists() and agents_md.read_bytes() == claude_md.read_bytes():
        return False
    # Write via tmp + mv: a half-written mirror is exactly the silent truncation this whole
    # change exists to prevent. mv through _git_cmd for the same agent-user path as cp.
    # The tmp name is unique per call — a fixed one could hit an existing file (or symlink) in a
    # third-party repo, and two concurrent syncs would write into the same inode.
    tmp = wt / f".AGENTS.md.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        _copy_file(claude_md, tmp)
        moved = _git_cmd(["mv", "-f", str(tmp), str(agents_md)], capture_output=True, text=True)
        if moved.returncode != 0:
            detail = moved.stderr.strip() or moved.stdout.strip() or f"exit {moved.returncode}"
            raise OSError(f"mirror CLAUDE.md -> AGENTS.md failed: {detail}")
    finally:
        if tmp.exists():
            _git_cmd(["rm", "-f", str(tmp)], capture_output=True, text=True)
    return True


def _exclude_worktree_artifacts(
    wt_path: Path, extra: list[str] | None = None, only: tuple[str, ...] | None = None,
) -> None:
    """Ignore injected/machine-local artifacts via `info/exclude` — untracked, never committed,
    so they can't dirty the tree or block merge_worker. Idempotent. External repos that don't
    already ignore these would otherwise leave them as untracked files.

    `extra` = paths this spawn actually planted (copies/symlinks from the manifest, e.g. `.env`),
    anchored to the repo root so they don't shadow same-named files deeper in the tree. Only
    untracked ones get here — see `tracked_paths`.

    `only` narrows the default set to the patterns the caller actually needs. Skill injection
    now also runs in an agent's plain cwd — a repository the user works in by hand — where
    adding ignore rules for artifacts we did not plant (`AGENTS.md`, `codex_sessions.json`)
    would be an unmandated side effect in someone else's repo.

    Git reads `info/exclude` from the COMMON git dir (`--git-common-dir`), not the
    per-worktree dir — a per-worktree `info/exclude` is silently ignored.
    """
    gd = _git_cmd(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(wt_path), capture_output=True, text=True,
    )
    if gd.returncode != 0:
        logger.warning(f"could not locate git-common-dir for {wt_path}: {gd.stderr.strip()}")
        return
    git_dir = Path(gd.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (wt_path / git_dir).resolve()
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text() if exclude.exists() else ""
    have = {line.strip() for line in existing.splitlines()}
    patterns = list(only if only is not None else _WORKTREE_EXCLUDES) + [f"/{p}" for p in (extra or [])]
    missing = [p for p in patterns if p not in have]
    if not missing:
        return
    with exclude.open("a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("".join(f"{p}\n" for p in missing))


def create_worktree(repo_path: str, name: str, task_id: str = "",
                    base_branch: str = "",
                    worktree_cfg: "WorktreeCfg | None" = None) -> Worktree:
    repo = validate_repo_root(repo_path)
    with repo_mutation_lock(repo):
        base_branch = resolve_base_branch(str(repo), base_branch)

        # Слаг от repo root, НЕ от scope сессии: родитель может спавнить в чужой проект,
        # и тогда scope-имя папки/ветки врёт про то, какому репозиторию worktree принадлежит.
        repo_slug = _slugify(str(repo))
        wt_dir = WORKTREE_ROOT / repo_slug
        _git_cmd(["mkdir", "-p", str(wt_dir)], capture_output=True)
        wt_path = wt_dir / name

        if task_id:
            par = _normalize_task_id(task_id)
            branch = f"task-{par}/{name}"
        else:
            branch = f"feat/{repo_slug}/{name}"

        if wt_path.exists():
            raise ValueError(f"worktree already exists: {wt_path}. Remove session first.")

        fmt_check = _git_cmd(
            ["git", "check-ref-format", "--branch", branch],
            cwd=str(repo), capture_output=True, text=True,
        )
        if fmt_check.returncode != 0:
            raise ValueError(f"Invalid branch name '{branch}': {fmt_check.stderr.strip()}")

        branch_initial_oid = _inspect_branch_ref(repo, branch)
        branch_created = branch_initial_oid is None
        if branch_created:
            branch_initial_oid = _resolve_commit_oid(repo, base_branch)
            result = _git_cmd(
                ["git", "worktree", "add", "--detach", str(wt_path), branch_initial_oid],
                cwd=str(repo), capture_output=True, text=True,
            )
        else:
            if _is_branch_checked_out_elsewhere(str(repo), branch, wt_path):
                raise ValueError(f"Branch '{branch}' is checked out in another worktree.")
            result = _git_cmd(
                ["git", "worktree", "add", str(wt_path), branch],
                cwd=str(repo), capture_output=True, text=True,
            )
        if result.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")

        if branch_created:
            try:
                _create_branch_ref(repo, branch, branch_initial_oid)
            except RuntimeError as create_error:
                removed = _git_cmd(
                    ["git", "worktree", "remove", str(wt_path), "--force"],
                    cwd=str(repo), capture_output=True, text=True,
                )
                if removed.returncode != 0 and _worktree_registered(repo, wt_path):
                    detail = removed.stderr.strip() or removed.stdout.strip()
                    raise RuntimeError(
                        f"{create_error}; detached worktree cleanup failed: {detail}"
                    ) from create_error
                raise
            checkout = _git_cmd(
                ["git", "checkout", branch],
                cwd=str(wt_path), capture_output=True, text=True,
            )
            if checkout.returncode != 0:
                removed = _git_cmd(
                    ["git", "worktree", "remove", str(wt_path), "--force"],
                    cwd=str(repo), capture_output=True, text=True,
                )
                detail = checkout.stderr.strip() or checkout.stdout.strip()
                if removed.returncode != 0 and _worktree_registered(repo, wt_path):
                    cleanup_detail = removed.stderr.strip() or removed.stdout.strip()
                    detail = f"{detail}; worktree cleanup failed: {cleanup_detail}"
                raise RuntimeError(
                    f"git checkout created branch failed: {detail}; "
                    f"branch '{branch}' was preserved"
                )

        # worktree_cfg задан → правила манифеста (copies + symlinks) и ТОЛЬКО они.
        # None → upstream-fallback: хардкод PROJECT_FILES, симлинков нет.
        copies = worktree_cfg.copies if worktree_cfg is not None else list(PROJECT_FILES)
        try:
            planted: list[str] = []
            tracked = tracked_paths(wt_path, copies)
            for fname in copies:
                src = _resolve_src(repo, fname)
                if src is None:
                    continue
                if fname in tracked:
                    # Репозиторий версионирует этот файл сам → его версия уже в worktree,
                    # а перезапись сделала бы дерево воркера грязным навсегда.
                    logger.info(f"'{fname}' is tracked by {repo} — copy skipped")
                    continue
                dst = wt_path / fname
                if not _within(dst.parent, wt_path):
                    raise ValueError(f"copy target '{fname}' escapes worktree")
                _copy_file(src, dst)
                planted.append(fname)
            if worktree_cfg is not None:
                for sl in worktree_cfg.symlinks:
                    _apply_symlink(repo, wt_path, sl)
                    planted.append(sl.target)
            _exclude_worktree_artifacts(wt_path, planted)
            sync_agents_md(str(wt_path))
        except Exception as setup_error:
            cleanup_errors: list[str] = []
            branch_deleted = False
            if branch_created:
                current_branch = _git_cmd(
                    ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
                    cwd=str(wt_path), capture_output=True, text=True,
                )
                try:
                    current_oid = _inspect_branch_ref(repo, branch)
                except RuntimeError as inspect_error:
                    current_oid = None
                    cleanup_errors.append(str(inspect_error))
                ownership_changed = (
                    current_branch.returncode != 0
                    or current_branch.stdout.strip() != branch
                    or current_oid != branch_initial_oid
                )
                if cleanup_errors or ownership_changed:
                    cleanup_errors.append(
                        f"created branch ownership changed; preserving worktree and {branch}"
                    )
                else:
                    deleted = _git_cmd(
                        [
                            "git", "update-ref", "-d",
                            f"refs/heads/{branch}", branch_initial_oid,
                        ],
                        cwd=str(repo), capture_output=True, text=True,
                    )
                    if deleted.returncode != 0:
                        cleanup_errors.append(
                            "branch delete: "
                            f"{deleted.stderr.strip() or deleted.stdout.strip()}"
                        )
                    else:
                        branch_deleted = True
            if not cleanup_errors:
                removed = _git_cmd(
                    ["git", "worktree", "remove", str(wt_path), "--force"],
                    cwd=str(repo), capture_output=True, text=True,
                )
                try:
                    registered = _worktree_registered(repo, wt_path)
                except RuntimeError as inspect_error:
                    registered = True
                    cleanup_errors.append(str(inspect_error))
                if removed.returncode != 0 and registered:
                    cleanup_errors.append(
                        "worktree remove: "
                        f"{removed.stderr.strip() or removed.stdout.strip()}"
                    )
                elif registered:
                    cleanup_errors.append("worktree remains registered after removal")
                if registered and branch_deleted:
                    restored = _git_cmd(
                        [
                            "git", "update-ref", f"refs/heads/{branch}",
                            branch_initial_oid, "",
                        ],
                        cwd=str(repo), capture_output=True, text=True,
                    )
                    if restored.returncode != 0:
                        cleanup_errors.append(
                            "branch restore after failed removal: "
                            f"{restored.stderr.strip() or restored.stdout.strip()}"
                        )
            if branch_created and not cleanup_errors:
                remaining_ref = _inspect_branch_ref(repo, branch)
                if remaining_ref is not None:
                    cleanup_errors.append(
                        f"created branch {branch} remains at {remaining_ref}"
                    )
            if cleanup_errors:
                raise RuntimeError(
                    f"worktree setup failed: {setup_error}; "
                    f"cleanup failed: {'; '.join(cleanup_errors)}"
                ) from setup_error
            raise

        return Worktree(
            path=str(wt_path), branch=branch, branch_created=branch_created,
            initial_head=branch_initial_oid,
        )


def discard_prepared_worktree(repo_path: str, worktree: Worktree) -> None:
    """Remove an unpublished worktree and only the branch this spawn created."""
    repo = validate_repo_root(repo_path)
    wt_path = Path(worktree.path)
    with repo_mutation_lock(repo):
        if not wt_path.exists():
            if _worktree_registered(repo, wt_path):
                raise RuntimeError(
                    f"prepared worktree directory is missing but '{wt_path}' "
                    "remains registered"
                )
            if worktree.branch_created:
                remaining = _inspect_branch_ref(repo, worktree.branch)
                if remaining is not None:
                    raise RuntimeError(
                        f"prepared worktree disappeared but created branch "
                        f"'{worktree.branch}' remains at {remaining}"
                    )
            return

        branch_deleted = False
        if worktree.branch_created:
            if not worktree.initial_head:
                raise RuntimeError(
                    f"cannot prove ownership of created branch '{worktree.branch}'"
                )
            actual_branch = _git_cmd(
                ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
                cwd=str(wt_path), capture_output=True, text=True,
            )
            actual_head = _git_cmd(
                ["git", "rev-parse", "HEAD"],
                cwd=str(wt_path), capture_output=True, text=True,
            )
            current_ref = _inspect_branch_ref(repo, worktree.branch)
            if (
                actual_branch.returncode != 0
                or actual_branch.stdout.strip() != worktree.branch
                or actual_head.returncode != 0
                or actual_head.stdout.strip() != worktree.initial_head
                or current_ref != worktree.initial_head
            ):
                raise RuntimeError(
                    f"prepared worktree ownership changed; preserving "
                    f"'{worktree.path}' and branch '{worktree.branch}'"
                )
            deleted = _git_cmd(
                [
                    "git", "update-ref", "-d", f"refs/heads/{worktree.branch}",
                    worktree.initial_head,
                ],
                cwd=str(repo), capture_output=True, text=True,
            )
            if deleted.returncode != 0:
                detail = deleted.stderr.strip() or deleted.stdout.strip()
                raise RuntimeError(
                    f"cannot delete prepared branch '{worktree.branch}': {detail}"
                )
            branch_deleted = True

        removed = _git_cmd(
            ["git", "worktree", "remove", str(wt_path), "--force"],
            cwd=str(repo), capture_output=True, text=True,
        )
        try:
            registered = _worktree_registered(repo, wt_path)
        except RuntimeError as inspect_error:
            registered = True
            removal_detail = str(inspect_error)
        else:
            removal_detail = removed.stderr.strip() or removed.stdout.strip()
        if removed.returncode != 0 or registered or wt_path.exists():
            restore_error = ""
            if branch_deleted:
                restored = _git_cmd(
                    [
                        "git", "update-ref", f"refs/heads/{worktree.branch}",
                        worktree.initial_head, "",
                    ],
                    cwd=str(repo), capture_output=True, text=True,
                )
                if restored.returncode != 0:
                    restore_error = (
                        "; branch restore failed: "
                        f"{restored.stderr.strip() or restored.stdout.strip()}"
                    )
            raise RuntimeError(
                f"cannot discard prepared worktree '{wt_path}': "
                f"{removal_detail or 'worktree remains registered'}{restore_error}"
            )

        if branch_deleted:
            remaining = _inspect_branch_ref(repo, worktree.branch)
            if remaining is not None:
                raise RuntimeError(
                    f"discarded worktree but created branch '{worktree.branch}' "
                    f"remains at {remaining}"
                )


def _resolve_repo(worktree_path: str, fallback_repo: str) -> Path:
    wt = Path(worktree_path).resolve()
    git_common = _git_cmd(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(wt), capture_output=True, text=True,
    )
    if git_common.returncode == 0:
        git_dir = Path(git_common.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = (wt / git_dir).resolve()
        return git_dir.parent
    return Path(fallback_repo).resolve()


def _branch_worktree_path(repo: str, branch: str) -> Path | None:
    """Return the checkout that owns ``branch`` according to Git's worktree registry."""
    listed = _git_cmd(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo, capture_output=True, text=True,
    )
    if listed.returncode != 0:
        detail = listed.stderr.strip() or listed.stdout.strip()
        raise RuntimeError(f"cannot list repository worktrees: {detail}")

    wanted = f"refs/heads/{branch}"
    for record in listed.stdout.strip().split("\n\n"):
        path: Path | None = None
        branch_ref: str | None = None
        prunable: str | None = None
        for line in record.splitlines():
            if line.startswith("worktree "):
                path = Path(line.removeprefix("worktree ")).resolve()
            elif line.startswith("branch "):
                branch_ref = line.removeprefix("branch ")
            elif line == "prunable" or line.startswith("prunable "):
                prunable = line.removeprefix("prunable").strip()
        if branch_ref != wanted:
            continue
        if path is None:
            raise RuntimeError(f"target branch '{branch}' has no worktree path")
        if prunable is not None or not path.is_dir():
            detail = prunable or "checkout path does not exist"
            raise RuntimeError(
                f"target branch '{branch}' belongs to prunable worktree "
                f"'{path}': {detail}"
            )
        return path
    return None


def _clean_worktree_error(path: Path, label: str) -> str | None:
    status = _git_cmd(
        ["git", "status", "--porcelain"],
        cwd=str(path), capture_output=True, text=True,
    )
    if status.returncode != 0:
        detail = status.stderr.strip() or status.stdout.strip()
        return f"cannot inspect {label} working tree: {detail}"
    dirty_lines = [line for line in status.stdout.splitlines() if line]
    if not dirty_lines:
        return None
    dirty_files = [line[3:] for line in dirty_lines[:10]]
    suffix = f", +{len(dirty_lines) - 10} more" if len(dirty_lines) > 10 else ""
    return (
        f"{label} working tree is dirty at '{path.resolve()}' "
        f"({len(dirty_lines)} file(s): "
        f"{', '.join(dirty_files)}{suffix}) — commit or discard first"
    )


def _get_commit_messages(repo: str, branch: str, base: str) -> list[str]:
    """Return subject lines of commits in branch not in base."""
    log = _git_cmd(
        ["git", "log", f"{base}..{branch}", "--format=%s", "--reverse"],
        cwd=repo, capture_output=True, text=True,
    )
    if log.returncode != 0 or not log.stdout.strip():
        return []
    return [line for line in log.stdout.strip().splitlines() if line.strip()]


_RESERVED_OPERATION_TRAILER_RE = re.compile(
    r"^[ \t]*Orchestra-Operation[ \t]*:", re.IGNORECASE | re.MULTILINE,
)
_RESERVED_OPERATION_TRAILER_VALUE_RE = re.compile(
    r"^[ \t]*Orchestra-Operation[ \t]*:[ \t]*(.*?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


_HEADER_TASK_REFS_RE = re.compile(
    r"^\s*((?:#[0-9]+|[A-Z]{2,5}-[0-9]+)(?:\s*,\s*(?:#[0-9]+|[A-Z]{2,5}-[0-9]+))*)\s*:"
)
_ONE_TASK_REF_RE = re.compile(r"#([0-9]+)|([A-Z]{2,5})-([0-9]+)")


def _leading_task_refs(message: str) -> list[str]:
    """Task refs from the canonical leading ``#N[, #N]*:`` header only.

    Prose matches the historical ref pattern: ``UTF-8``, ``GPT-5`` and ``SHA-256``
    all look like ``PREFIX-N``. Resolving them as tasks refuses honest merges and
    links the squash to the numeric tail (``UTF-8`` -> ``#8``), so a ref counts
    only in the header position. The prefix stays case-sensitive on purpose:
    ``wip-2:`` is a word.
    """
    header = _HEADER_TASK_REFS_RE.match(message)
    if not header:
        return []
    refs: list[str] = []
    for match in _ONE_TASK_REF_RE.finditer(header.group(1)):
        ref = match.group(1) or f"{match.group(2)}-{match.group(3)}"
        if ref not in refs:
            refs.append(ref)
    return refs


def _extract_task_refs(messages: list[str]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for message in messages:
        for ref in _leading_task_refs(message):
            if ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def _inspect_candidate_commits(repo: str, base_ref: str, worker_head: str) -> dict:
    log = _git_cmd(
        [
            "git", "log", "-z", "--reverse", f"{base_ref}..{worker_head}",
            "--format=%H%x00%s%x00%B",
        ],
        cwd=repo, capture_output=True, text=True,
    )
    if log.returncode != 0:
        detail = log.stderr.strip() or log.stdout.strip() or f"exit {log.returncode}"
        raise RuntimeError(f"cannot inspect candidate commits: {detail}")
    fields = log.stdout.split("\0")
    if fields and not fields[-1]:
        fields.pop()
    if len(fields) % 3:
        raise RuntimeError("cannot inspect candidate commits: malformed git log output")
    subjects: list[str] = []
    for offset in range(0, len(fields), 3):
        commit, subject, body = fields[offset:offset + 3]
        if _RESERVED_OPERATION_TRAILER_RE.search(body):
            trailers = _RESERVED_OPERATION_TRAILER_VALUE_RE.findall(body)
            from app.merge_operations import operation_created_target_commit

            # Long-lived branches can inherit an earlier Orchestra target commit whose
            # content reached current main under a different squash SHA. Exact durable
            # operation→commit identity separates that history from an authored spoof.
            if not (
                len(trailers) == 1
                and operation_created_target_commit(trailers[0], commit)
            ):
                raise ValueError(
                    "worker commit contains reserved Orchestra-Operation: trailer"
                )
        subjects.append(subject)
    return {"refs": _extract_task_refs(subjects), "messages": subjects}


def _strip_leading_task_refs(summary: str) -> str:
    """Drop the header this module recognises as refs — and nothing else.

    A second, looser notion of "ref" here used to eat honest text (``wip-2:``),
    so the header is stripped only when `_leading_task_refs` actually claims it.
    """
    if not _leading_task_refs(summary):
        return summary
    return _HEADER_TASK_REFS_RE.sub("", summary, count=1).lstrip()


def _build_squash_message(branch: str, messages: list[str]) -> str:
    """Build squash commit message with task refs prefix and message list.

    Squash merge collapses N worker commits into one clean main-branch commit.
    The message aggregates all task refs so PM tooling can link the merge to tasks.
    """
    # `#248` and `PAR-248` are the same task: dedup AFTER the numeric collapse,
    # or one branch carrying both spellings emits `#248, #248:` into main forever.
    all_refs: list[str] = []
    for ref in _extract_task_refs(messages):
        numeric = f"#{ref.rsplit('-', 1)[-1]}"
        if numeric not in all_refs:
            all_refs.append(numeric)

    if messages:
        summary = messages[-1] if len(messages) == 1 else messages[0]
    else:
        summary = f"merge {branch}"
    summary = _strip_leading_task_refs(summary)

    prefix = ", ".join(all_refs) + ": " if all_refs else ""
    header = f"{prefix}{summary}"

    body_lines = "\n".join(f"- {m}" for m in messages)
    if len(messages) > 1:
        return f"{header}\n\nSquashed commits:\n{body_lines}"
    return header


def _validated_squash_message(
    branch: str,
    messages: list[str],
    candidate_refs: list[str],
    primary_task_ref: str,
    operation_id: str = "",
) -> str:
    message = _build_squash_message(branch, messages)
    expected_refs = candidate_refs or ([primary_task_ref] if primary_task_ref else [])
    if not candidate_refs and primary_task_ref:
        message = f"#{primary_task_ref}: {message}"
    subject = message.splitlines()[0] if message else ""
    emitted_refs = [ref.rsplit("-", 1)[-1] for ref in _extract_task_refs([subject])]
    if emitted_refs != expected_refs:
        raise ValueError(
            "squash subject task refs changed under repository lock: "
            f"expected {expected_refs}, found {emitted_refs}"
        )
    if operation_id:
        # Отдельным paragraph'ом и последним: так его читает `git interpret-trailers`,
        # и по нему операция узнаёт СВОЙ коммит, когда журнал потерян.
        message = f"{message}\n\nOrchestra-Operation: {operation_id}"
    return message


def _rollback_merge_target(repo: str, old_head: str, error: str) -> dict:
    if not old_head:
        return {
            "ok": False,
            "state": "rollback_failed",
            "error": f"{error}; rollback failed: original target HEAD is unknown",
        }
    reset = _git_cmd(
        ["git", "reset", "--hard", old_head],
        cwd=repo, capture_output=True, text=True,
    )
    if reset.returncode != 0:
        detail = reset.stderr.strip() or reset.stdout.strip()
        return {
            "ok": False,
            "state": "rollback_failed",
            "error": f"{error}; rollback failed: {detail}",
        }
    head = _git_cmd(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True,
    )
    status = _git_cmd(
        ["git", "status", "--porcelain"],
        cwd=repo, capture_output=True, text=True,
    )
    if (
        head.returncode != 0
        or head.stdout.strip() != old_head
        or status.returncode != 0
        or status.stdout.strip()
    ):
        detail = status.stderr.strip() or status.stdout.strip() or head.stderr.strip()
        return {
            "ok": False,
            "state": "rollback_failed",
            "error": f"{error}; rollback verification failed: {detail or 'target differs'}",
        }
    return {"ok": False, "error": error}


def _commit_failure_result(repo: str, old_head: str, commit) -> dict:
    detail = "\n".join(
        part for part in (commit.stdout.strip(), commit.stderr.strip()) if part
    )
    if not detail:
        detail = f"git commit exit code {commit.returncode}"
    return _rollback_merge_target(
        repo, old_head, f"squash commit failed: {detail}",
    )


def _cherry_pick_branch(
    repo: str,
    source_ref: str,
    old_head: str,
    *,
    branch_name: str = "",
    commit_message: str = "",
) -> tuple[dict, bool]:
    """Cherry-pick all commits from branch onto current HEAD.

    Fallback for unrelated histories: happens when a worker was spawned from a
    separate repo or rebased its branch, losing the common ancestor with main.
    git merge refuses unrelated histories; cherry-pick applies diffs anyway.
    """
    rev_list = _git_cmd(
        ["git", "rev-list", "--reverse", source_ref],
        cwd=repo, capture_output=True, text=True,
    )
    if rev_list.returncode != 0 or not rev_list.stdout.strip():
        return ({
            "ok": False,
            "error": f"cannot list commits on {source_ref}: {rev_list.stderr.strip()}",
        }, False)

    commits = rev_list.stdout.strip().splitlines()
    logger.info(f"cherry-pick fallback: {len(commits)} commits from {source_ref}")

    messages = _get_commit_messages(repo, source_ref, "")

    mutation_started = False
    for i, sha in enumerate(commits):
        mutation_started = True
        cp = _git_cmd(
            ["git", "cherry-pick", "--no-commit", sha],
            cwd=repo, capture_output=True, text=True,
        )
        if cp.returncode != 0:
            cp_err = cp.stderr.strip() or cp.stdout.strip()
            if "nothing to commit" in cp_err or "empty" in cp_err.lower():
                _git_cmd(["git", "reset"], cwd=repo, capture_output=True, text=True)
                continue
            _git_cmd(
                ["git", "cherry-pick", "--abort"],
                cwd=repo, capture_output=True, text=True,
            )
            return ({
                "ok": False,
                "error": (
                    f"cherry-pick failed on commit {sha[:7]} "
                    f"({i+1}/{len(commits)}): {cp_err}"
                ),
            }, mutation_started)

    status = _git_cmd(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo, capture_output=True, text=True,
    )
    if status.returncode != 0:
        commit_msg = commit_message or _build_squash_message(
            branch_name or source_ref, messages,
        )
        commit = _git_cmd(
            ["git", "commit", "-m", commit_msg],
            cwd=repo, capture_output=True, text=True,
        )
        if commit.returncode != 0:
            return _commit_failure_result(repo, old_head, commit), mutation_started

    merged_commits = _parse_merged_commits(repo, old_head) if old_head else {}
    return ({
        "ok": True,
        "commits_merged": len(commits),
        "branch": branch_name or source_ref,
        "strategy": "cherry-pick",
        "merged_commits": merged_commits,
    }, mutation_started)


def _reset_worktree_to_ref(worktree_path: str, ref: str, repo_path: str) -> None:
    wt = Path(worktree_path).resolve()
    repo = _resolve_repo(worktree_path, repo_path)
    rev = _git_cmd(
        ["git", "rev-parse", ref],
        cwd=str(repo), capture_output=True, text=True,
    )
    if rev.returncode != 0:
        logger.warning(f"_reset_worktree_to_ref: cannot resolve {ref}: {rev.stderr.strip()}")
        return
    target_sha = rev.stdout.strip()
    reset = _git_cmd(
        ["git", "reset", "--hard", target_sha],
        cwd=str(wt), capture_output=True, text=True,
    )
    if reset.returncode != 0:
        logger.warning(f"_reset_worktree_to_ref: reset failed in {wt}: {reset.stderr.strip()}")
    else:
        logger.info(f"_reset_worktree_to_ref: {wt} reset to {ref} ({target_sha[:8]})")


def classify_head_drift(
    worktree_path: str, expected_branch: str, expected_head: str,
) -> dict:
    """Классифицировать расхождение запомненной личности воркера с живым git.

    Между тем, как merge_worker снял снимок, и тем, как он дошёл до git, стоит ожидание
    чужого хода (десятки секунд). Воркер за это время ОБЯЗАН закоммитить — этого требует
    его собственный промпт. Такое продвижение той же ветки безобидно: отказ от него ничего
    не защищает, потому что повторный merge_worker секундой позже сольёт тот же коммит.

    Возвращает class: SAME | BENIGN_ADVANCE | FATAL. FATAL всегда с причиной, названной
    словами, — «HEAD changed» не отличает коммит воркера от переписанной истории.
    """
    try:
        actual_branch, actual_head = inspect_worktree_identity(worktree_path)
    except RuntimeError as e:
        return {
            "class": "FATAL", "actual_branch": "", "actual_head": "",
            "reason": f"cannot inspect worker identity: {e}",
        }
    out = {"class": "SAME", "actual_branch": actual_branch, "actual_head": actual_head,
           "reason": ""}
    if expected_branch and actual_branch != expected_branch:
        out["class"] = "FATAL"
        out["reason"] = f"branch changed: {expected_branch} → {actual_branch}"
        return out
    if not expected_head or actual_head == expected_head:
        return out
    known = _git_cmd(
        ["git", "rev-parse", "--quiet", "--verify", f"{expected_head}^{{commit}}"],
        cwd=str(Path(worktree_path).resolve()), capture_output=True, text=True,
    )
    if known.returncode != 0:
        out["class"] = "FATAL"
        out["reason"] = f"pinned commit {expected_head} unknown to repository"
        return out
    ancestor = _git_cmd(
        ["git", "merge-base", "--is-ancestor", expected_head, actual_head],
        cwd=str(Path(worktree_path).resolve()), capture_output=True, text=True,
    )
    if ancestor.returncode == 0:
        out["class"] = "BENIGN_ADVANCE"
        out["reason"] = (
            f"worker advanced {expected_branch or actual_branch} from {expected_head} "
            f"to {actual_head} after the operation was accepted"
        )
        return out
    out["class"] = "FATAL"
    out["reason"] = (
        f"history rewritten: {expected_head} is not an ancestor of {actual_head} "
        f"(rebase/amend/reset)"
    )
    return out


def inspect_worktree_identity(worktree_path: str) -> tuple[str, str]:
    """Return the current local branch and HEAD for later in-lock comparison."""
    wt = Path(worktree_path).resolve()
    try:
        branch = _git_cmd(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=str(wt), capture_output=True, text=True,
        )
    except OSError as e:
        raise RuntimeError(f"cannot inspect worker branch: {type(e).__name__}: {e}") from e
    if branch.returncode != 0:
        detail = branch.stderr.strip() or branch.stdout.strip() or f"exit {branch.returncode}"
        raise RuntimeError(f"cannot inspect worker branch: {detail}")
    try:
        head = _git_cmd(
            ["git", "rev-parse", "HEAD"], cwd=str(wt), capture_output=True, text=True,
        )
    except OSError as e:
        raise RuntimeError(f"cannot inspect worker HEAD: {type(e).__name__}: {e}") from e
    if head.returncode != 0:
        detail = head.stderr.strip() or head.stdout.strip() or f"exit {head.returncode}"
        raise RuntimeError(f"cannot inspect worker HEAD: {detail}")
    return branch.stdout.strip(), head.stdout.strip()


def merge_worktree_to_main(
    worktree_path: str,
    repo_path: str,
    target_branch: str = "",
    *,
    expected_worker_branch: str = "",
    expected_worker_head: str = "",
    expected_target_head: str = "",
    waive_diff_budget: bool = False,
    waived_by: str = "",
    expected_candidate_refs: list[str] | None = None,
    validated_task_refs: list[str] | None = None,
    primary_task_ref: str = "",
    operation_id: str = "",
    prepare: Callable[[str, str], None] | None = None,
    resolve_refs: Callable[[list[str]], list[str]] | None = None,
    commit_receipt: Callable[[dict], dict] | None = None,
) -> MergeOutcome:
    wt = Path(worktree_path).resolve()
    repo = _resolve_repo(str(wt), repo_path)

    original_branch = None
    result = None
    worker_head = ""
    target_before = ""
    diff_insertions = None
    target_after = ""
    worker_branch = ""
    mutation_started = False
    target_commit_succeeded = False
    merge_cwd = ""
    target_recheck = None
    prepared_squash_message = ""
    reset_worker_pending = False

    with repo_mutation_lock(repo):
        try:
            target_branch = resolve_base_branch(str(repo), target_branch)
        except Exception as e:
            # Ловим по МЕСТУ, а не по типу: это первый шаг под локом, ни один реф ещё не
            # тронут, поэтому исход Git известен для ЛЮБОГО отказа здесь — ничего не
            # произошло. resolve_base_branch поднимает не только ValueError, но и
            # RuntimeError (битый репозиторий, права) и OSError (нет git); улетев из
            # функции, они попадали в catch-all роута и становились partial/unknown с
            # удержанной резервацией задачи — хотя двумя шагами ниже то же условие
            # возвращается как failed/not_reached.
            from app.errtext import err_text

            return {
                "ok": False,
                "state": "failed",
                "commit_point": "not_reached",
                "error": f"cannot resolve target branch: {err_text(e)}",
                "target_branch": target_branch,
                "target_before": "",
                "target_after": "",
                # Запиннённые роутом значения: отказ обязан описывать воркера не беднее,
                # чем описывал улетавший наружу путь.
                "worker_branch": expected_worker_branch,
                "worker_head": expected_worker_head,
                "conflicts": [],
                "commits_merged": 0,
                # Негодная цель — ошибка запроса, отказ git'а — ошибка окружения.
                "_http_status": 400 if isinstance(e, ValueError) else 500,
            }
        try:
            worker_head_result = _git_cmd(
                ["git", "rev-parse", "HEAD"],
                cwd=str(wt), capture_output=True, text=True,
            )
            if worker_head_result.returncode == 0:
                worker_head = worker_head_result.stdout.strip()
                if expected_worker_head and worker_head != expected_worker_head:
                    result = {
                        "ok": False,
                        "error": (
                            "worker HEAD changed before merge: "
                            f"expected {expected_worker_head}, found {worker_head}"
                        ),
                    }
            else:
                detail = (
                    worker_head_result.stderr.strip()
                    or worker_head_result.stdout.strip()
                    or f"exit {worker_head_result.returncode}"
                )
                result = {"ok": False, "error": f"cannot resolve worker HEAD: {detail}"}
            branch_result = _git_cmd(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(wt), capture_output=True, text=True,
            )
            if branch_result.returncode != 0:
                if result is None:
                    result = {
                        "ok": False,
                        "error": f"cannot get branch: {branch_result.stderr.strip()}",
                    }
            else:
                branch = branch_result.stdout.strip()
                worker_branch = branch
                if (
                    result is None
                    and expected_worker_branch
                    and branch != expected_worker_branch
                ):
                    result = {
                        "ok": False,
                        "error": (
                            "worker branch changed before merge: "
                            f"expected {expected_worker_branch}, found {branch}"
                        ),
                    }
            if result is None:
                try:
                    from app.diff_budget import (
                        MAX_DIFF_INSERTIONS,
                        budget_error,
                        measure_insertions,
                    )
                    diff_insertions = measure_insertions(str(wt), target_branch)
                    budget = (
                        ""
                        if waive_diff_budget
                        else budget_error(diff_insertions, MAX_DIFF_INSERTIONS)
                    )
                except RuntimeError as e:
                    result = {"ok": False, "error": str(e)}
                else:
                    if budget:
                        result = {"ok": False, "error": budget}
            if result is None:
                child_error = _clean_worktree_error(wt, "worker")
                if child_error:
                    result = {"ok": False, "error": child_error}
                else:
                    try:
                        target_before_ref = _inspect_branch_ref(repo, target_branch)
                    except RuntimeError as e:
                        # Git refused to read refs at all (ownership, broken repo).
                        # That is not evidence the target branch is missing.
                        result = {"ok": False, "error": str(e)}
                    else:
                        if target_before_ref is None:
                            result = {"ok": False, "error": f"target branch '{target_branch}' does not exist"}
                        else:
                            target_before = target_before_ref
                            if result is None and target_before == worker_head:
                                result = {
                                    "ok": False,
                                    "state": "failed",
                                    "commit_point": "not_reached",
                                    "code": "NO_COMMITS_MERGED",
                                    "error": (
                                        f"target branch '{target_branch}' and worker branch "
                                        f"'{worker_branch}' point to the same commit; refusing "
                                        "to merge the worker branch into its target"
                                    ),
                                    "commits_merged": 0,
                                }
                            if expected_target_head:
                                target_recheck = {
                                    "expected": expected_target_head,
                                    "actual": target_before_ref,
                                    "matched": target_before_ref == expected_target_head,
                                }
                                if not target_recheck["matched"]:
                                    return {
                                        "ok": False,
                                        "state": "failed",
                                        "commit_point": "not_reached",
                                        "code": "TARGET_HEAD_CHANGED",
                                        "error": "target branch moved after admission",
                                        "target_recheck": target_recheck,
                                        "target_branch": target_branch,
                                        "target_before": target_before_ref,
                                        "target_after": target_before_ref,
                                        "worker_branch": worker_branch,
                                        "worker_head": worker_head,
                                        "conflicts": [],
                                        "commits_merged": 0,
                                        "diff_insertions": diff_insertions,
                                    }
                        if result is None and (
                            expected_candidate_refs is not None or resolve_refs is not None
                        ):
                            try:
                                candidate = _inspect_candidate_commits(
                                    str(repo), target_before, worker_head,
                                )
                                actual_refs = candidate["refs"]
                                if (
                                    expected_candidate_refs is not None
                                    and actual_refs != expected_candidate_refs
                                ):
                                    raise ValueError(
                                        "candidate task refs changed under repository lock: "
                                        f"expected {expected_candidate_refs}, found {actual_refs}"
                                    )
                                # Рефы разрешаются в задачи ЗДЕСЬ, под тем же локом и на том
                                # же запиннённом HEAD, что и проверка: между «прочитали» и
                                # «разрешили» воркер уже ничего не может дописать.
                                task_refs = (
                                    resolve_refs(actual_refs) if resolve_refs is not None
                                    else list(validated_task_refs or [])
                                )
                                prepared_squash_message = _validated_squash_message(
                                    branch,
                                    candidate["messages"],
                                    task_refs,
                                    primary_task_ref,
                                    operation_id,
                                )
                            except (RuntimeError, ValueError) as e:
                                result = {"ok": False, "error": str(e)}
                        if result is None:
                            try:
                                owner = _branch_worktree_path(str(repo), target_branch)
                            except RuntimeError as e:
                                result = {"ok": False, "error": str(e)}
                            else:
                                target_wt = owner or repo
                        if result is None:
                            if target_wt == wt:
                                result = {
                                    "ok": False,
                                    "error": "worker branch cannot be merged into itself",
                                }
                            else:
                                target_error = _clean_worktree_error(target_wt, "target")
                                if target_error:
                                    result = {"ok": False, "error": target_error}
                                else:
                                    if owner is None:
                                        original = _git_cmd(
                                            ["git", "symbolic-ref", "--short", "HEAD"],
                                            cwd=str(repo), capture_output=True, text=True,
                                        )
                                        original_branch = (
                                            original.stdout.strip()
                                            if original.returncode == 0 else None
                                        )
                                        checkout = _git_cmd(
                                            ["git", "checkout", target_branch],
                                            cwd=str(repo), capture_output=True, text=True,
                                        )
                                        if checkout.returncode != 0:
                                            result = {
                                                "ok": False,
                                                "error": (
                                                    f"cannot checkout {target_branch} in repo: "
                                                    f"{checkout.stderr.strip()}"
                                                ),
                                            }

                                    if result is None:
                                        merge_cwd = str(target_wt)
                                        target_head = _git_cmd(
                                            ["git", "symbolic-ref", "--short", "HEAD"],
                                            cwd=merge_cwd,
                                            capture_output=True,
                                            text=True,
                                        )
                                        if (
                                            target_head.returncode != 0
                                            or target_head.stdout.strip() != target_branch
                                        ):
                                            actual = target_head.stdout.strip() or "detached"
                                            result = {
                                                "ok": False,
                                                "error": (
                                                    f"target checkout moved from "
                                                    f"'{target_branch}' to '{actual}'"
                                                ),
                                            }

                                    if result is None:
                                        merge_cwd = str(target_wt)
                                        merge_base = _git_cmd(
                                            ["git", "merge-base", target_branch, worker_head],
                                            cwd=merge_cwd, capture_output=True, text=True,
                                        )
                                        unrelated = merge_base.returncode != 0

                                        precheck_ok = True
                                        expected_tree = ""
                                        if not unrelated:
                                            precheck = _git_cmd(
                                                [
                                                    "git", "merge-tree", "--write-tree",
                                                    "--name-only", "--no-messages", "-z",
                                                    target_branch, worker_head,
                                                ],
                                                cwd=merge_cwd,
                                                capture_output=True,
                                                text=True,
                                            )
                                            if precheck.returncode != 0:
                                                records = precheck.stdout.split("\0")
                                                conflict_files = [
                                                    path for path in records[1:] if path
                                                ]
                                                if not conflict_files:
                                                    err = (
                                                        precheck.stderr.strip()
                                                        or precheck.stdout.strip()
                                                        or f"merge-tree exit code {precheck.returncode}"
                                                    )
                                                    logger.error(
                                                        "merge-tree failed: repo=%s branch=%s err=%s",
                                                        repo, branch, err,
                                                    )
                                                    result = {
                                                        "ok": False,
                                                        "error": f"merge precheck failed: {err}",
                                                    }
                                                else:
                                                    result = _merge_conflict_result(
                                                        branch, conflict_files,
                                                    )
                                                precheck_ok = False
                                            else:
                                                # `--write-tree` печатает OID итогового
                                                # дерева первой записью: это ровно то
                                                # дерево, которое получит squash-коммит.
                                                expected_tree = precheck.stdout.split(
                                                    "\0",
                                                )[0].strip()

                                        if precheck_ok and expected_target_head:
                                            current_target = _inspect_branch_ref(repo, target_branch)
                                            target_recheck = {
                                                "expected": expected_target_head,
                                                "actual": current_target or "",
                                                "matched": current_target == expected_target_head,
                                            }
                                            if not target_recheck["matched"]:
                                                result = {
                                                    "ok": False,
                                                    "code": "TARGET_HEAD_CHANGED",
                                                    "error": "target branch moved after merge precheck",
                                                    "target_recheck": target_recheck,
                                                }
                                                precheck_ok = False

                                        if precheck_ok:
                                            old_head_result = _git_cmd(
                                                ["git", "rev-parse", "HEAD"],
                                                cwd=merge_cwd,
                                                capture_output=True,
                                                text=True,
                                            )
                                            old_head = (
                                                old_head_result.stdout.strip()
                                                if old_head_result.returncode == 0 else ""
                                            )
                                            prepare_failed = False
                                            if prepare is not None:
                                                # Последний момент под repo-локом, когда
                                                # рефы ещё не тронуты: журнал обязан лечь
                                                # ДО мутации, иначе восстанавливать нечем.
                                                try:
                                                    prepare(target_before, expected_tree)
                                                except Exception as prepare_error:
                                                    prepare_failed = True
                                                    result = {
                                                        "ok": False,
                                                        "error": (
                                                            "merge journal could not be prepared "
                                                            "before Git: "
                                                            f"{type(prepare_error).__name__}: "
                                                            f"{prepare_error}"
                                                        ),
                                                    }

                                            if prepare_failed:
                                                logger.error(
                                                    "merge preparation failed for %s: %s",
                                                    branch, result["error"],
                                                )
                                            elif unrelated:
                                                logger.info(
                                                    "unrelated histories for %s — using cherry-pick",
                                                    branch,
                                                )
                                                result, mutation_started = _cherry_pick_branch(
                                                    merge_cwd,
                                                    worker_head,
                                                    old_head,
                                                    branch_name=branch,
                                                    commit_message=prepared_squash_message,
                                                )
                                            else:
                                                commits_result = _git_cmd(
                                                    ["git", "rev-list", "--count",
                                                     f"{target_branch}..{worker_head}"],
                                                    cwd=merge_cwd,
                                                    capture_output=True,
                                                    text=True,
                                                )
                                                commits_merged = int(
                                                    commits_result.stdout.strip() or "0"
                                                )
                                                messages = _get_commit_messages(
                                                    merge_cwd, worker_head, target_branch,
                                                )
                                                mutation_started = True
                                                merge = _git_cmd(
                                                    ["git", "merge", "--squash", worker_head],
                                                    cwd=merge_cwd,
                                                    capture_output=True,
                                                    text=True,
                                                )
                                                if merge.returncode != 0:
                                                    conflict_files = _conflict_paths(merge_cwd)
                                                    _git_cmd(
                                                        ["git", "reset", "--merge"],
                                                        cwd=merge_cwd,
                                                        capture_output=True,
                                                        text=True,
                                                    )
                                                    err = (
                                                        merge.stderr.strip()
                                                        or merge.stdout.strip()
                                                        or f"git merge exit code {merge.returncode}"
                                                    )
                                                    logger.error(
                                                        "merge_worktree squash failed: "
                                                        "repo=%s branch=%s err=%s",
                                                        repo, branch, err,
                                                    )
                                                    result = (
                                                        _merge_conflict_result(branch, conflict_files)
                                                        if conflict_files
                                                        else {"ok": False, "error": err}
                                                    )
                                                else:
                                                    staged = _git_cmd(
                                                        ["git", "diff", "--cached", "--quiet"],
                                                        cwd=merge_cwd,
                                                        capture_output=True,
                                                        text=True,
                                                    )
                                                    if staged.returncode != 0:
                                                        commit_msg = (
                                                            prepared_squash_message
                                                            or _build_squash_message(
                                                                branch, messages,
                                                            )
                                                        )
                                                        commit = _git_cmd(
                                                            ["git", "commit", "-m", commit_msg],
                                                            cwd=merge_cwd,
                                                            capture_output=True,
                                                            text=True,
                                                        )
                                                        if commit.returncode != 0:
                                                            result = _commit_failure_result(
                                                                merge_cwd, old_head, commit,
                                                            )
                                                        else:
                                                            merged_commits = (
                                                                _parse_merged_commits(
                                                                    merge_cwd, old_head,
                                                                )
                                                                if old_head else {}
                                                            )
                                                            result = {
                                                                "ok": True,
                                                                "commits_merged": commits_merged,
                                                                "branch": branch,
                                                                "merged_commits": merged_commits,
                                                            }
                                                    else:
                                                        conflict_files = _conflict_paths(merge_cwd)
                                                        result = (
                                                            _merge_conflict_result(branch, conflict_files)
                                                            if conflict_files
                                                            else {
                                                                "ok": True,
                                                                "commits_merged": 0,
                                                                "branch": branch,
                                                                "merged_commits": {},
                                                            }
                                                        )

                                            if result and result.get("ok"):
                                                target_commit_succeeded = True
                                                reset_worker_pending = True
        finally:
            if original_branch and original_branch != target_branch:
                restore = _git_cmd(
                    ["git", "checkout", original_branch],
                    cwd=str(repo), capture_output=True, text=True,
                )
                if restore.returncode != 0:
                    logger.error(f"restore branch failed: {restore.stderr.strip()}")
                    result = {"ok": False, "state": "restore_failed",
                              "error": f"cannot restore branch '{original_branch}': {restore.stderr.strip()}"}
        target_after_result = _git_cmd(
            ["git", "show-ref", "--verify", f"refs/heads/{target_branch}"],
            cwd=str(repo), capture_output=True, text=True,
        )
        if target_after_result.returncode == 0:
            target_after = target_after_result.stdout.split()[0]
        target_snapshot_known = target_after_result.returncode in (0, 1)

        if result is None:
            result = {"ok": False, "error": "merge produced no result"}
        target_changed = target_after != target_before
        rollback_verified = False
        if mutation_started and merge_cwd and target_snapshot_known and not target_changed:
            final_target_status = _git_cmd(
                ["git", "status", "--porcelain"],
                cwd=merge_cwd, capture_output=True, text=True,
            )
            rollback_verified = (
                final_target_status.returncode == 0
                and not final_target_status.stdout.strip()
            )

        prior_state = result.get("state")
        if not target_snapshot_known or (target_before and not target_after):
            result["ok"] = False
            state = "partial"
            commit_point = "unknown"
            result["error"] = result.get("error") or "cannot obtain final target snapshot"
        elif prior_state in {"restore_failed", "rollback_failed"}:
            result["ok"] = False
            state = "partial"
            commit_point = "unknown"
            result["error"] = result.get("error") or f"merge ended in {prior_state}"
        elif result.get("ok"):
            if target_changed:
                state = "merged"
                commit_point = "target_committed"
            else:
                result["ok"] = False
                result["code"] = "NO_COMMITS_MERGED"
                result["error"] = result.get("error") or "merge produced no new commits"
                state = "failed"
                commit_point = "not_reached"
        elif target_commit_succeeded and target_changed:
            state = "partial"
            commit_point = "target_committed"
            result["error"] = result.get("error") or "merge changed target before failing"
        elif result.get("conflicts"):
            state = "conflict"
            commit_point = "not_reached"
        elif mutation_started and not rollback_verified:
            state = "partial"
            commit_point = "unknown"
            result["error"] = result.get("error") or "merge rollback could not be verified"
        else:
            state = "failed"
            commit_point = "rolled_back" if mutation_started else "not_reached"
            result["error"] = result.get("error") or "merge failed without an error detail"
        from app.diff_budget import MAX_DIFF_INSERTIONS
        result.update(
            state=state,
            commit_point=commit_point,
            target_branch=target_branch,
            target_before=target_before,
            target_after=target_after,
            worker_branch=worker_branch,
            worker_head=worker_head,
            conflicts=result.get("conflicts", []),
            diff_insertions=diff_insertions,
            diff_budget_limit=MAX_DIFF_INSERTIONS,
            diff_budget_waived=bool(waive_diff_budget),
            diff_budget_waived_by=waived_by if waive_diff_budget else "",
        )
        if expected_target_head:
            result["target_recheck"] = target_recheck or {
                "expected": expected_target_head,
                "actual": target_before,
                "matched": target_before == expected_target_head,
            }
        if (
            result.get("ok")
            and commit_point == "target_committed"
            and commit_receipt is not None
        ):
            try:
                result["receipt"] = commit_receipt(dict(result))
            except Exception as error:
                result.update(
                    ok=False,
                    state="partial",
                    error=(
                        "verified merge receipt could not be persisted before "
                        f"worktree reset: {type(error).__name__}: {error}"
                    ),
                    receipt_error=f"{type(error).__name__}: {error}",
                )
        if reset_worker_pending and (
            commit_point != "target_committed"
            or commit_receipt is None
            or isinstance(result.get("receipt"), dict)
        ):
            _reset_worktree_to_ref(str(wt), target_branch, str(repo))
        return result


def _parse_merged_commits(
    repo: str, old_head: str, head_ref: str = "HEAD",
) -> dict[str, list[dict]]:
    log = _git_cmd(
        ["git", "log", f"{old_head}..{head_ref}", "--format=%H%x00%s%x00%ad", "--date=short"],
        cwd=repo, capture_output=True, text=True,
    )
    if log.returncode != 0 or not log.stdout.strip():
        return {}

    by_par: dict[str, list[dict]] = {}
    for line in log.stdout.strip().splitlines():
        parts = line.split("\x00", 2)
        if len(parts) < 3:
            continue
        full_hash, message, date = parts
        short_hash = full_hash[:7]

        refs = _leading_task_refs(message)
        if not refs:
            continue

        stat = _git_cmd(
            ["git", "diff-tree", "--numstat", "--root", "-m", "--first-parent", full_hash],
            cwd=repo, capture_output=True, text=True,
        )
        files_changed = insertions = deletions = 0
        for stat_line in (stat.stdout.strip().splitlines() if stat.returncode == 0 else []):
            stat_parts = stat_line.split("\t")
            if len(stat_parts) == 3:
                try:
                    ins = int(stat_parts[0]) if stat_parts[0] != "-" else 0
                    dels = int(stat_parts[1]) if stat_parts[1] != "-" else 0
                    insertions += ins
                    deletions += dels
                    files_changed += 1
                except ValueError:
                    continue

        commit = {
            "hash": short_hash,
            "message": message,
            "date": date,
            "files": files_changed,
            "insertions": insertions,
            "deletions": deletions,
        }
        for ref in refs:
            by_par.setdefault(ref, []).append(commit)

    return by_par


def _is_branch_checked_out_elsewhere(repo: str, branch: str, current_wt: Path) -> bool:
    wt_list = _git_cmd(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo, capture_output=True, text=True,
    )
    current_path = ""
    for line in wt_list.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}":
            if current_path and Path(current_path).resolve() != current_wt:
                return True
    return False


def branch_content_status(worktree_path: str, base_ref: str) -> dict:
    wt = Path(worktree_path).resolve()
    git_kwargs = {
        "cwd": str(wt),
        "capture_output": True,
        "text": True,
        "timeout": 5,
    }
    try:
        ahead = _git_cmd(
            ["git", "rev-list", f"{base_ref}..HEAD", "--count"],
            **git_kwargs,
        )
        if ahead.returncode != 0:
            detail = ahead.stderr.strip() or ahead.stdout.strip() or f"exit code {ahead.returncode}"
            return {"error": f"git rev-list failed: {detail}"}
        raw_count = ahead.stdout.strip()
        if not raw_count.isdigit():
            return {"error": f"git rev-list returned invalid count: {raw_count!r}"}
        commits_ahead = int(raw_count)
        if commits_ahead == 0:
            return {
                "base_ref": base_ref,
                "commits_ahead": 0,
                "content_merged": True,
                "reason": "ancestor",
            }

        driver_config = _git_cmd(
            ["git", "config", "-z", "--name-only", "--get-regexp", r"^merge\..*\.driver$"],
            **git_kwargs,
        )
        if driver_config.returncode not in (0, 1):
            detail = (
                driver_config.stderr.strip()
                or driver_config.stdout.strip()
                or f"exit code {driver_config.returncode}"
            )
            return {"error": f"git config merge-driver check failed: {detail}"}
        driver_keys = []
        if driver_config.returncode == 0:
            driver_keys = list(dict.fromkeys(
                key for key in driver_config.stdout.split("\0") if key
            ))

        raw_config_count = os.environ.get("GIT_CONFIG_COUNT", "0")
        try:
            config_count = int(raw_config_count)
            if config_count < 0:
                raise ValueError
        except ValueError:
            return {"error": f"invalid GIT_CONFIG_COUNT: {raw_config_count!r}"}
        merge_env = os.environ.copy()
        overrides = [
            ("merge.default", "text"),
            ("merge.renormalize", "false"),
            ("merge.union.driver", "false"),
        ]
        for driver_key in driver_keys:
            overrides.append((driver_key, "false"))
        for index, (key, value) in enumerate(overrides, start=config_count):
            merge_env[f"GIT_CONFIG_KEY_{index}"] = key
            merge_env[f"GIT_CONFIG_VALUE_{index}"] = value
        merge_env["GIT_CONFIG_COUNT"] = str(config_count + len(overrides))

        prospective = _git_cmd([
            "git",
            "merge-tree", "--write-tree", "--no-messages", base_ref, "HEAD",
        ], env=merge_env, **git_kwargs)
        if prospective.returncode == 1:
            return {
                "base_ref": base_ref,
                "commits_ahead": commits_ahead,
                "content_merged": False,
                "reason": "conflict",
            }
        if prospective.returncode != 0:
            detail = (
                prospective.stderr.strip()
                or prospective.stdout.strip()
                or f"exit code {prospective.returncode}"
            )
            return {"error": f"git merge-tree failed: {detail}"}

        result_lines = [
            line.strip() for line in prospective.stdout.splitlines() if line.strip()
        ]
        if len(result_lines) != 1:
            return {"error": "git merge-tree returned an invalid result tree"}

        base_tree = _git_cmd(
            ["git", "rev-parse", "--verify", f"{base_ref}^{{tree}}"],
            **git_kwargs,
        )
        if base_tree.returncode != 0:
            detail = (
                base_tree.stderr.strip()
                or base_tree.stdout.strip()
                or f"exit code {base_tree.returncode}"
            )
            return {"error": f"git rev-parse base tree failed: {detail}"}
        result_tree = _git_cmd(
            ["git", "rev-parse", "--verify", f"{result_lines[0]}^{{tree}}"],
            **git_kwargs,
        )
        if result_tree.returncode != 0:
            detail = (
                result_tree.stderr.strip()
                or result_tree.stdout.strip()
                or f"exit code {result_tree.returncode}"
            )
            return {"error": f"git merge-tree result validation failed: {detail}"}

        content_merged = result_tree.stdout.strip() == base_tree.stdout.strip()
        return {
            "base_ref": base_ref,
            "commits_ahead": commits_ahead,
            "content_merged": content_merged,
            "reason": "content-noop" if content_merged else "content-change",
        }
    except subprocess.TimeoutExpired as e:
        command = " ".join(str(part) for part in e.cmd)
        return {"error": f"{command} timed out"}
    except OSError as e:
        return {"error": f"git content check failed: {type(e).__name__}: {e}"}


def promote_worktree_branch(
    worktree_path: str,
    new_branch: str,
    *,
    from_ref: str,
    expected_branch: str,
    expected_head: str,
) -> dict:
    """Rename taskless adhoc work without moving its committed HEAD."""
    wt = Path(worktree_path).resolve()
    repo = _resolve_repo(str(wt), str(wt))
    with repo_mutation_lock(repo):
        from_ref = resolve_base_branch(str(repo), from_ref)
        worker_name = new_branch.rsplit("/", 1)[-1]
        if (
            not expected_branch.startswith("adhoc-")
            or expected_branch.rsplit("/", 1)[-1] != worker_name
        ):
            return {
                "ok": False,
                "state": "not_taskless_adhoc",
                "error": f"branch '{expected_branch}' is not an adhoc branch for {worker_name}",
            }
        valid = _git_cmd(
            ["git", "check-ref-format", "--branch", new_branch],
            cwd=str(repo), capture_output=True, text=True,
        )
        if valid.returncode != 0:
            return {
                "ok": False,
                "state": "invalid_target_branch",
                "error": f"invalid branch '{new_branch}': {valid.stderr.strip()}",
            }
        status = _git_cmd(
            ["git", "status", "--porcelain"], cwd=str(wt),
            capture_output=True, text=True,
        )
        if status.returncode != 0:
            detail = status.stderr.strip() or status.stdout.strip()
            return {"ok": False, "state": "git_status_failed", "error": detail}
        if status.stdout.strip():
            return {
                "ok": False,
                "state": "dirty_worktree",
                "error": "dirty working tree — commit or discard first",
            }
        try:
            actual_branch, actual_head = inspect_worktree_identity(str(wt))
        except RuntimeError as error:
            return {"ok": False, "state": "identity_unavailable", "error": str(error)}
        if actual_branch != expected_branch or actual_head != expected_head:
            return {
                "ok": False,
                "state": "identity_changed",
                "error": (
                    f"worker identity changed: expected {expected_branch}@{expected_head}, "
                    f"found {actual_branch}@{actual_head}"
                ),
                "branch": actual_branch,
                "head": actual_head,
            }
        try:
            target_head = _inspect_branch_ref(repo, new_branch)
        except RuntimeError as error:
            return {"ok": False, "state": "target_inspection_failed", "error": str(error)}
        if target_head is not None:
            return {
                "ok": False,
                "state": "target_branch_exists",
                "error": f"branch '{new_branch}' already exists at {target_head}",
                "branch": expected_branch,
                "head": expected_head,
            }
        content = branch_content_status(str(wt), from_ref)
        if content.get("error"):
            return {
                "ok": False,
                "state": "content_check_failed",
                "error": str(content["error"]),
                "branch": expected_branch,
                "head": expected_head,
            }
        if content.get("commits_ahead", 0) <= 0 or content.get("content_merged"):
            return {
                "ok": False,
                "state": "no_unmerged_work",
                "error": "current adhoc branch has no unmerged committed work to promote",
                "branch": expected_branch,
                "head": expected_head,
                "commits_ahead": content.get("commits_ahead", 0),
                "reason": content.get("reason", ""),
            }
        renamed = _git_cmd(
            ["git", "branch", "-m", new_branch], cwd=str(wt),
            capture_output=True, text=True,
        )
        if renamed.returncode != 0:
            detail = renamed.stderr.strip() or renamed.stdout.strip()
            return {
                "ok": False,
                "state": "promotion_failed",
                "error": f"branch promotion failed: {detail}",
                "branch": expected_branch,
                "head": expected_head,
            }
        try:
            promoted_branch, promoted_head = inspect_worktree_identity(str(wt))
            old_head = _inspect_branch_ref(repo, expected_branch)
            new_head = _inspect_branch_ref(repo, new_branch)
        except RuntimeError as error:
            return {
                "ok": False,
                "state": "rollback_failed",
                "error": f"branch promoted but verification failed: {error}",
                "branch": new_branch,
                "head": expected_head,
            }
        if (
            promoted_branch != new_branch
            or promoted_head != expected_head
            or new_head != expected_head
            or old_head is not None
        ):
            return {
                "ok": False,
                "state": "rollback_failed",
                "error": "branch promotion verification failed; promoted ref was preserved",
                "branch": promoted_branch,
                "head": promoted_head,
            }
        return {
            "ok": True,
            "state": "promoted_current_work",
            "previous_branch": expected_branch,
            "branch": new_branch,
            "head": expected_head,
            "commits_ahead": content["commits_ahead"],
            "reason": content["reason"],
        }


def rollback_promoted_worktree_branch(
    worktree_path: str,
    *,
    promoted_branch: str,
    previous_branch: str,
    expected_head: str,
) -> dict:
    """Undo only a promotion whose checked-out ref still owns the pinned HEAD."""
    wt = Path(worktree_path).resolve()
    repo = _resolve_repo(str(wt), str(wt))
    with repo_mutation_lock(repo):
        try:
            actual_branch, actual_head = inspect_worktree_identity(str(wt))
            previous_head = _inspect_branch_ref(repo, previous_branch)
        except RuntimeError as error:
            return {"ok": False, "state": "rollback_failed", "error": str(error)}
        if actual_branch == previous_branch and actual_head == expected_head:
            return {"ok": True, "state": "already_rolled_back", "branch": previous_branch,
                    "head": expected_head}
        if (
            actual_branch != promoted_branch
            or actual_head != expected_head
            or previous_head is not None
        ):
            return {
                "ok": False,
                "state": "rollback_failed",
                "error": "promotion ownership changed; preserving all refs",
                "branch": actual_branch,
                "head": actual_head,
            }
        renamed = _git_cmd(
            ["git", "branch", "-m", previous_branch], cwd=str(wt),
            capture_output=True, text=True,
        )
        if renamed.returncode != 0:
            detail = renamed.stderr.strip() or renamed.stdout.strip()
            return {
                "ok": False,
                "state": "rollback_failed",
                "error": f"promotion rollback failed: {detail}",
                "branch": promoted_branch,
                "head": expected_head,
            }
        try:
            actual_branch, actual_head = inspect_worktree_identity(str(wt))
        except RuntimeError as error:
            return {
                "ok": False,
                "state": "rollback_failed",
                "error": f"promotion rollback verification failed: {error}",
                "branch": previous_branch,
                "head": expected_head,
            }
        if actual_branch != previous_branch or actual_head != expected_head:
            return {
                "ok": False,
                "state": "rollback_failed",
                "error": "promotion rollback verification failed; current ref was preserved",
                "branch": actual_branch,
                "head": actual_head,
            }
        return {"ok": True, "state": "rolled_back", "branch": previous_branch,
                "head": expected_head}


def switch_worktree_branch(worktree_path: str, new_branch: str,
                           from_ref: str = "",
                           force: bool = False,
                           expect_absent: bool = False,
                           recreate_from_base: bool = False) -> dict:
    """expect_absent=True — вызывающий создаёт ЗАВЕДОМО новую ветку (авто-switch перед
    доставкой). Тогда существующая ветка того же имени — отказ, а не переиспользование:
    усыновление чужой истории должно быть невозможно, а не маловероятно (#27, E2).

    recreate_from_base=True — вызывающий ДОКАЗАЛ, что содержимое ветки уже в базе, и просит
    начать её заново от базы вместо слияния базы в неё (#61). Доказательство git выдать не
    может: сквош-мерж не сохраняет предка, а сравнение деревьев после доработки базы даёт
    конфликт. Поэтому решение принимает вызывающий (роут, у которого есть запись об операции
    мержа), а здесь только механизм."""
    wt = Path(worktree_path).resolve()
    repo = _resolve_repo(str(wt), str(wt))
    with repo_mutation_lock(repo):
        from_ref = resolve_base_branch(str(repo), from_ref)
        valid = _git_cmd(
            ["git", "check-ref-format", "--branch", new_branch],
            cwd=str(repo), capture_output=True, text=True,
        )
        if valid.returncode != 0:
            return {"ok": False, "error": f"invalid branch '{new_branch}': {valid.stderr.strip()}"}

        status = _git_cmd(
            ["git", "status", "--porcelain"], cwd=str(wt), capture_output=True, text=True,
        )
        if status.returncode != 0:
            detail = status.stderr.strip() or status.stdout.strip() or f"exit code {status.returncode}"
            return {"ok": False, "error": f"git status failed: {detail}"}
        if status.stdout.strip():
            dirty_lines = status.stdout.strip().splitlines()[:10]
            dirty_files = [l[3:] for l in dirty_lines]
            return {"ok": False, "error": f"dirty working tree ({len(dirty_lines)} file(s): {', '.join(dirty_files)}) — commit or discard first"}

        if not force:
            content_status = branch_content_status(str(wt), from_ref)
            if content_status.get("error"):
                return {
                    "ok": False,
                    "error": f"cannot verify current branch content against {from_ref}: {content_status['error']}",
                }
            if not content_status["content_merged"]:
                n = content_status["commits_ahead"]
                reason = content_status["reason"]
                return {
                    "ok": False,
                    "error": (
                        f"{n} commit(s) could not be verified in {from_ref} ({reason}) — "
                        "merge_worker first or pass force=True"
                    ),
                }

        original_branch_result = _git_cmd(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=str(wt), capture_output=True, text=True,
        )
        if original_branch_result.returncode == 0:
            original_branch = original_branch_result.stdout.strip()
        elif original_branch_result.returncode == 1:
            original_branch = ""
        else:
            detail = (
                original_branch_result.stderr.strip()
                or original_branch_result.stdout.strip()
                or f"exit {original_branch_result.returncode}"
            )
            return {"ok": False, "error": f"cannot inspect current branch: {detail}"}
        original_head_result = _git_cmd(
            ["git", "rev-parse", "HEAD"], cwd=str(wt), capture_output=True, text=True,
        )
        if original_head_result.returncode != 0:
            return {"ok": False, "error": f"cannot resolve current HEAD: {original_head_result.stderr.strip()}"}
        original_head = original_head_result.stdout.strip()

        try:
            target_head = _inspect_branch_ref(repo, new_branch)
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}
        target_existed = target_head is not None
        target_created = False
        if target_existed and _is_branch_checked_out_elsewhere(str(repo), new_branch, wt):
            return {"ok": False, "error": f"branch '{new_branch}' is checked out in another worktree"}
        if original_branch == new_branch:
            # Идемпотентный ремонт — успех, а не ошибка. Раньше система здесь запиралась:
            # git уже прав, ремонт отказывает именно поэтому, а из-за ok=False никто не
            # записывал наблюдаемую ветку в БД, и мерж падал на «session branch changed».
            # Но «уже там» не значит «с той же базы»: просьбу сменить базу молча не глотаем.
            try:
                requested_base = _resolve_commit_oid(repo, from_ref)
            except RuntimeError as e:
                return {"ok": False, "error": str(e)}
            contained = _git_cmd(
                ["git", "merge-base", "--is-ancestor", requested_base, original_head],
                cwd=str(wt), capture_output=True, text=True,
            )
            if contained.returncode == 0:
                return {
                    "ok": True, "state": "already_on_branch",
                    "branch": new_branch, "head": original_head,
                }
            return {
                "ok": False,
                "error": (
                    f"worker is already on branch '{new_branch}', but requested base "
                    f"'{from_ref}' is not merged into it"
                ),
            }

        # Второй слой (#27): вызывающий ждал свежую ветку, а имя занято — значит на нём
        # лежит ЧУЖАЯ история. Переселять на неё нельзя даже молча-успешно: новая работа
        # легла бы поверх старой, а мерж принёс бы в main обе. Показываем, чью работу
        # система отказалась усыновить, — имя, HEAD и дату последнего коммита.
        if expect_absent and target_existed:
            when = _git_cmd(
                ["git", "log", "-1", "--format=%cI", new_branch],
                cwd=str(repo), capture_output=True, text=True,
            )
            last = when.stdout.strip() if when.returncode == 0 else "дата недоступна"
            return {
                "ok": False,
                "state": "target_branch_exists",
                "error": (
                    f"branch '{new_branch}' already exists (HEAD {target_head}, last commit "
                    f"{last}) — refusing to adopt someone else's history; a fresh branch was expected"
                ),
            }

        if target_existed and recreate_from_base:
            # Начать ветку заново от базы: ровно то, что человек делает руками одной
            # командой, когда возврат на смерженную сквошем ветку упирается в конфликт.
            # Коммиты старой ветки при этом теряются — поэтому сюда пускает только
            # доказательство вызывающего, а не догадка.
            recreated = _git_cmd(
                ["git", "checkout", "-B", new_branch, from_ref],
                cwd=str(wt), capture_output=True, text=True,
            )
            if recreated.returncode != 0:
                detail = recreated.stderr.strip() or recreated.stdout.strip()
                return {"ok": False, "error": f"recreate from {from_ref} failed: {detail}"}
            head_now = _git_cmd(
                ["git", "rev-parse", "HEAD"], cwd=str(wt), capture_output=True, text=True,
            ).stdout.strip()
            return {
                "ok": True, "state": "recreated_from_base",
                "branch": new_branch, "head": head_now, "previous_head": target_head,
            }

        try:
            from_head = _resolve_commit_oid(repo, from_ref)
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}

        def rollback(cause: str, conflicts: list[str] | None = None) -> dict:
            errors: list[str] = []
            merge_head = _git_cmd(
                ["git", "rev-parse", "--quiet", "--verify", "MERGE_HEAD"],
                cwd=str(wt), capture_output=True, text=True,
            )
            if merge_head.returncode == 0:
                abort = _git_cmd(
                    ["git", "merge", "--abort"], cwd=str(wt), capture_output=True, text=True,
                )
                if abort.returncode != 0:
                    errors.append(f"merge abort: {abort.stderr.strip() or abort.stdout.strip()}")

            if target_created:
                target_owner = _git_cmd(
                    ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
                    cwd=str(wt), capture_output=True, text=True,
                )
                try:
                    target_now = _inspect_branch_ref(repo, new_branch)
                except RuntimeError as inspect_error:
                    target_now = None
                    errors.append(str(inspect_error))
                if (
                    not errors
                    and target_owner.returncode == 0
                    and target_owner.stdout.strip() == new_branch
                    and target_now == target_head
                ):
                    deleted = _git_cmd(
                        [
                            "git", "update-ref", "-d",
                            f"refs/heads/{new_branch}", target_head,
                        ],
                        cwd=str(repo), capture_output=True, text=True,
                    )
                    if deleted.returncode != 0:
                        errors.append(
                            "delete owned target ref: "
                            f"{deleted.stderr.strip() or deleted.stdout.strip()}"
                        )
                else:
                    errors.append(
                        f"created target ref ownership is uncertain; preserving {new_branch}"
                    )

            original_ref_matches = True
            if original_branch:
                original_ref = _git_cmd(
                    ["git", "rev-parse", f"refs/heads/{original_branch}"],
                    cwd=str(repo), capture_output=True, text=True,
                )
                original_ref_head = (
                    original_ref.stdout.strip() if original_ref.returncode == 0 else ""
                )
                original_ref_matches = original_ref_head == original_head
                if not original_ref_matches:
                    errors.append(
                        "original ref changed concurrently: "
                        f"{original_ref_head or 'missing'} (expected {original_head})"
                    )
                restore_checkout = _git_cmd(
                    ["git", "checkout", original_branch],
                    cwd=str(wt), capture_output=True, text=True,
                )
            else:
                restore_checkout = _git_cmd(
                    ["git", "checkout", "--detach", original_head],
                    cwd=str(wt), capture_output=True, text=True,
                )
            if restore_checkout.returncode != 0:
                errors.append(
                    "restore checkout: "
                    f"{restore_checkout.stderr.strip() or restore_checkout.stdout.strip()}"
                )

            if not original_branch or original_ref_matches:
                restore_head = _git_cmd(
                    ["git", "reset", "--hard", original_head],
                    cwd=str(wt), capture_output=True, text=True,
                )
                if restore_head.returncode != 0:
                    errors.append(
                        f"restore HEAD: {restore_head.stderr.strip() or restore_head.stdout.strip()}"
                    )

            if new_branch != original_branch:
                target_now = _git_cmd(
                    ["git", "show-ref", "--verify", f"refs/heads/{new_branch}"],
                    cwd=str(repo), capture_output=True, text=True,
                )
                target_now_head = (
                    target_now.stdout.split()[0] if target_now.returncode == 0 else ""
                )
                if target_created:
                    if target_now.returncode == 0:
                        errors.append(
                            f"created target ref remains at {target_now_head}"
                        )
                    elif target_now.returncode != 1:
                        errors.append(
                            "inspect created target ref: "
                            f"{target_now.stderr.strip() or target_now.stdout.strip()}"
                        )
                elif target_existed and (
                    target_now.returncode != 0 or target_now_head != target_head
                ):
                    errors.append(
                        "existing target ref changed concurrently: "
                        f"{target_now_head or 'missing'} (expected {target_head})"
                    )

            actual_branch_result = _git_cmd(
                ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
                cwd=str(wt), capture_output=True, text=True,
            )
            actual_branch = (
                actual_branch_result.stdout.strip()
                if actual_branch_result.returncode == 0 else "HEAD"
            )
            actual_head_result = _git_cmd(
                ["git", "rev-parse", "HEAD"], cwd=str(wt), capture_output=True, text=True,
            )
            actual_head = (
                actual_head_result.stdout.strip()
                if actual_head_result.returncode == 0 else ""
            )
            final_status = _git_cmd(
                ["git", "status", "--porcelain"], cwd=str(wt), capture_output=True, text=True,
            )
            final_merge_head = _git_cmd(
                ["git", "rev-parse", "--quiet", "--verify", "MERGE_HEAD"],
                cwd=str(wt), capture_output=True, text=True,
            )
            expected_branch = original_branch or "HEAD"
            if actual_branch != expected_branch:
                errors.append(f"branch is {actual_branch}, expected {expected_branch}")
            if actual_head != original_head:
                errors.append(f"HEAD is {actual_head or 'unknown'}, expected {original_head}")
            if final_status.returncode != 0 or final_status.stdout.strip():
                detail = final_status.stderr.strip() or final_status.stdout.strip()
                errors.append(f"working tree not clean: {detail}")
            if final_merge_head.returncode == 0:
                errors.append("MERGE_HEAD still exists")

            target_after = _git_cmd(
                ["git", "show-ref", "--verify", f"refs/heads/{new_branch}"],
                cwd=str(repo), capture_output=True, text=True,
            )
            if target_existed:
                target_after_head = target_after.stdout.split()[0] if target_after.returncode == 0 else ""
                if target_after_head != target_head:
                    errors.append(
                        f"target ref is {target_after_head or 'missing'}, expected {target_head}"
                    )
            elif target_after.returncode == 0:
                errors.append("new target ref still exists")

            if errors:
                result = {
                    "ok": False,
                    "state": "rollback_failed",
                    "error": f"{cause}; rollback failed: {'; '.join(errors)}",
                    "actual_branch": actual_branch,
                    "actual_head": actual_head,
                }
                if conflicts:
                    result["conflicts"] = conflicts
                return result
            result = {"ok": False, "error": cause}
            if conflicts:
                result["conflicts"] = conflicts
            return result

        detach = _git_cmd(
            ["git", "checkout", "--detach", original_head],
            cwd=str(wt), capture_output=True, text=True,
        )
        if detach.returncode != 0:
            detail = detach.stderr.strip() or detach.stdout.strip()
            return rollback(f"detach current branch failed: {detail}")

        reset = _git_cmd(
            ["git", "reset", "--hard", from_head],
            cwd=str(wt), capture_output=True, text=True,
        )
        if reset.returncode != 0:
            detail = reset.stderr.strip() or reset.stdout.strip()
            return rollback(f"reset to {from_ref} failed: {detail}")

        if not target_existed:
            try:
                _create_branch_ref(repo, new_branch, from_head)
            except RuntimeError as e:
                return rollback(str(e))
            target_created = True
            target_head = from_head

        if target_existed:
            checkout = _git_cmd(
                ["git", "checkout", new_branch], cwd=str(wt), capture_output=True, text=True,
            )
            if checkout.returncode != 0:
                detail = checkout.stderr.strip() or checkout.stdout.strip()
                return rollback(f"checkout failed: {detail}")

            merge_main = _git_cmd(
                ["git", "merge", from_ref, "--no-edit"],
                cwd=str(wt), capture_output=True, text=True,
            )
            if merge_main.returncode != 0:
                conflict_files = []
                status_out = _git_cmd(
                    ["git", "diff", "--name-only", "--diff-filter=U"],
                    cwd=str(wt), capture_output=True, text=True,
                )
                if status_out.stdout.strip():
                    conflict_files = status_out.stdout.strip().splitlines()
                detail = merge_main.stderr.strip() or merge_main.stdout.strip()
                cause = f"merge with {from_ref} failed: {detail}"
                return rollback(cause, conflict_files)
        else:
            checkout = _git_cmd(
                ["git", "checkout", new_branch],
                cwd=str(wt), capture_output=True, text=True,
            )
            if checkout.returncode != 0:
                detail = checkout.stderr.strip() or checkout.stdout.strip()
                return rollback(f"branch create failed: {detail}")

        actual_branch_result = _git_cmd(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=str(wt), capture_output=True, text=True,
        )
        actual_head_result = _git_cmd(
            ["git", "rev-parse", "HEAD"], cwd=str(wt), capture_output=True, text=True,
        )
        final_status = _git_cmd(
            ["git", "status", "--porcelain"], cwd=str(wt), capture_output=True, text=True,
        )
        actual_branch = (
            actual_branch_result.stdout.strip()
            if actual_branch_result.returncode == 0 else "HEAD"
        )
        actual_head = (
            actual_head_result.stdout.strip() if actual_head_result.returncode == 0 else ""
        )
        if (
            actual_branch != new_branch
            or final_status.returncode != 0
            or bool(final_status.stdout.strip())
        ):
            detail = final_status.stderr.strip() or final_status.stdout.strip() or "state changed"
            return {
                "ok": False,
                "state": "rollback_failed",
                "error": f"switched worktree has inconsistent final state: {detail}",
                "actual_branch": actual_branch,
                "actual_head": actual_head,
            }
        return {"ok": True, "branch": new_branch}


def remove_worktree(repo_path: str, worktree_path: str) -> None:
    wt = Path(worktree_path)
    if not wt.exists():
        return
    cwd = repo_path
    git_file = wt / ".git"
    if git_file.exists() and git_file.is_file():
        try:
            content = git_file.read_text().strip()
            if content.startswith("gitdir:"):
                git_dir = Path(content.split("gitdir:", 1)[1].strip()).resolve()
                for parent in git_dir.parents:
                    if (parent / ".git").is_dir():
                        cwd = str(parent)
                        break
        except Exception as e:
            logger.warning(f"gitdir resolve failed for {wt}, using repo_path: {e}")
    repo = _resolve_repo(str(wt), repo_path)
    with repo_mutation_lock(repo):
        result = _git_cmd(
            ["git", "worktree", "remove", str(wt), "--force"],
            cwd=cwd, capture_output=True, text=True,
        )
        if result.returncode != 0:
            if not wt.exists():
                return
            detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
            raise RuntimeError(
                f"git worktree remove failed for {wt} "
                f"(exit {result.returncode}): {detail}"
            )


def cleanup_stale_worktrees() -> list[str]:
    """Remove working copies that no live session claims.

    Two safety catches, both required. This function deletes other agents' work, and it
    reads the roster from whatever database the process happens to point at — on 2026-08-03
    a pytest run in the main checkout combined an empty temporary DB with the real
    WORKTREE_ROOT and wiped every clean worktree of every project (.orchestra/tasks/62).

    1. An EMPTY roster means the roster is wrong, not that every working copy is dead.
    2. A directory named after a live session is never deleted, even when the recorded path
       disagrees — a path mismatch is a reason to look, not to erase.
    """
    from app.db import get_all_sessions
    if not WORKTREE_ROOT.is_dir():
        return []

    sessions = get_all_sessions()  # non-archived only
    alive_paths: set[str] = set()
    live_names: set[str] = set()
    for s in sessions:
        wt = s.get("worktree_path")
        if wt:
            alive_paths.add(str(Path(wt).resolve()))
            live_names.add(Path(wt).name)
        if s.get("name"):
            live_names.add(s["name"])

    if not alive_paths:
        logger.warning(
            "worktree cleanup refused: not a single live session has a worktree path. "
            "Deleting everything on that basis is how live work gets erased — "
            f"leaving {WORKTREE_ROOT} untouched"
        )
        return []

    removed: list[str] = []
    for repo_dir in WORKTREE_ROOT.iterdir():
        if not repo_dir.is_dir():
            continue
        for wt_dir in repo_dir.iterdir():
            if not wt_dir.is_dir():
                continue
            if str(wt_dir.resolve()) in alive_paths:
                continue
            if wt_dir.name in live_names:
                logger.warning(
                    f"stale worktree kept: {wt_dir} carries the name of a live session, but "
                    "no session records this path. Paths disagree — that is a reason to look, "
                    "not to delete someone's work"
                )
                continue
            git_file = wt_dir / ".git"
            if not (git_file.exists() and git_file.is_file()):
                continue
            dirty = _git_cmd(
                ["git", "status", "--porcelain"],
                cwd=str(wt_dir), capture_output=True, text=True,
            )
            if dirty.returncode != 0 or dirty.stdout.strip():
                logger.info(f"stale worktree skipped (dirty): {wt_dir}")
                continue
            repo_path = str(wt_dir)
            try:
                content = git_file.read_text().strip()
                if content.startswith("gitdir:"):
                    git_dir = Path(content.split("gitdir:", 1)[1].strip()).resolve()
                    for parent in git_dir.parents:
                        if (parent / ".git").is_dir():
                            repo_path = str(parent)
                            break
            except Exception as e:
                logger.warning(f"gitdir resolve failed for stale worktree {wt_dir}: {e}")
            try:
                remove_worktree(repo_path, str(wt_dir))
                if wt_dir.exists():
                    logger.warning(
                        f"stale worktree cleanup left path in place: {wt_dir}"
                    )
                    continue
                removed.append(str(wt_dir))
                # WARNING, not INFO: erasing a working copy is never routine, and INFO from
                # app.* modules was invisible in journald until this task fixed the handler.
                logger.warning(f"stale worktree removed: {wt_dir}")
            except Exception as e:
                logger.warning(f"stale worktree cleanup failed for {wt_dir}: {e}")

        if repo_dir.is_dir() and not any(repo_dir.iterdir()):
            try:
                repo_dir.rmdir()
                logger.info(f"empty repo dir removed: {repo_dir}")
            except Exception as e:
                logger.warning(f"empty repo dir cleanup failed ({repo_dir}): {e}")

    return removed


def parse_owned_dirs(raw) -> list[str]:
    """Normalize owned_dirs from any source (JSON string, list, None). Bad input → []."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for d in raw:
        if not isinstance(d, str):
            continue
        p = d.strip().strip("/")
        if p and p not in out:
            out.append(p)
    return out


def dirs_overlap(a: list[str], b: list[str]) -> list[str]:
    """Return overlapping dirs (prefix-aware): app/api conflicts with app/api/v1."""
    hits = []
    for x in a:
        for y in b:
            if x == y or x.startswith(y + "/") or y.startswith(x + "/"):
                hits.append(x if len(x) >= len(y) else y)
    return sorted(set(hits))


def simulate_conflict(repo_path: str, branch_a: str, branch_b: str) -> dict:
    """Dry-run merge of two existing branches. {ok:True, conflicts:[...]} = simulation ran.
    {ok:False, error} = couldn't run (missing branch / unrelated histories)."""
    repo = _resolve_repo(repo_path, repo_path)
    for ref in (branch_a, branch_b):
        v = _git_cmd(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            cwd=str(repo), capture_output=True, text=True,
        )
        if v.returncode != 0:
            return {"ok": False, "error": f"branch '{ref}' not found"}
    mb = _git_cmd(
        ["git", "merge-base", branch_a, branch_b],
        cwd=str(repo), capture_output=True, text=True,
    )
    if mb.returncode != 0:
        return {"ok": False, "error": "unrelated histories — cannot simulate"}
    r = _git_cmd(
        ["git", "merge-tree", "--write-tree", branch_a, branch_b],
        cwd=str(repo), capture_output=True, text=True,
    )
    if r.returncode == 0:
        return {"ok": True, "conflicts": []}
    conflicts = []
    for line in r.stdout.splitlines():
        if not line.startswith("CONFLICT"):
            continue
        m = re.search(r"Merge conflict in (.+)$", line)
        if not m:
            m = re.search(r"CONFLICT \([^)]+\): (\S+) ", line)
        if m:
            path = m.group(1).strip()
            if path not in conflicts:
                conflicts.append(path)
    if conflicts:
        return {"ok": True, "conflicts": conflicts}
    return {"ok": False, "error": (r.stderr.strip() or r.stdout.strip() or "merge-tree failed")}


def branch_wip_status(worktree_path: str, base_ref: str = "") -> dict:
    """Report uncommitted files, unmerged commits, and diff stats relative to base_ref.
    Returns {"error": ...} if git status or the base_ref comparison fails — never a false 'clean'."""
    wt = Path(worktree_path).resolve()
    base_ref = resolve_base_branch(str(wt), base_ref)
    dirty = _git_cmd(
        ["git", "status", "--porcelain"], cwd=str(wt), capture_output=True, text=True,
    )
    if dirty.returncode != 0:
        return {"error": f"git status failed: {dirty.stderr.strip()}"}
    uncommitted = [line[3:] for line in dirty.stdout.splitlines() if line]
    log = _git_cmd(
        ["git", "log", f"{base_ref}..HEAD", "--format=%s"],
        cwd=str(wt), capture_output=True, text=True,
    )
    if log.returncode != 0:
        return {"error": f"base_ref '{base_ref}' not found or comparison failed: {log.stderr.strip()}"}
    unmerged = [l for l in log.stdout.strip().splitlines() if l.strip()]

    changed: dict[str, dict] = {}
    for diff_range in (f"{base_ref}...HEAD", "HEAD"):
        stat = _git_cmd(
            ["git", "diff", "--numstat", diff_range],
            cwd=str(wt), capture_output=True, text=True,
        )
        if stat.returncode != 0:
            return {"error": f"git diff failed for '{diff_range}': {stat.stderr.strip()}"}
        for line in stat.stdout.splitlines():
            fields = line.split("\t", 2)
            if len(fields) != 3:
                continue
            added, deleted, path = fields
            entry = changed.setdefault(
                path, {"path": path, "insertions": 0, "deletions": 0, "binary": False},
            )
            if added == "-" or deleted == "-":
                entry["binary"] = True
                continue
            entry["insertions"] += int(added)
            entry["deletions"] += int(deleted)

    for path in uncommitted:
        changed.setdefault(
            path, {"path": path, "insertions": None, "deletions": None, "binary": False},
        )
    changed_files = list(changed.values())
    insertions = sum(f["insertions"] or 0 for f in changed_files)
    deletions = sum(f["deletions"] or 0 for f in changed_files)
    return {
        "base_ref": base_ref,
        "uncommitted": uncommitted,
        "unmerged_commits": unmerged,
        "changed_files": changed_files,
        "insertions": insertions,
        "deletions": deletions,
    }
