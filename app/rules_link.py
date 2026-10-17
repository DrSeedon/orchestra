"""AGENTS.md и CLAUDE.md в корне проекта — один файл и симлинк, а не две копии (V-902).

Codex читает AGENTS.md, Claude Agent SDK — CLAUDE.md, `app/harness/prompts.py` берёт AGENTS.md
первым. Две расходящиеся копии молча отдают часть агентов под устаревшие правила. Правило из
V-900 держалось бы на доверии; здесь его проверяет платформа (решение владельца 14.10.2026:
«чтобы не на доверии соблюдали, всё на реальности… нарушил — по рукам побить»).

`reconcile(root)` разбирает пару файлов так:
- один файл — ссылка на другой (или `CLAUDE.md` = `@AGENTS.md`) → ничего;
- копии побайтно равны, либо файл один → второй становится симлинком на каноничный. Каноничный
  — AGENTS.md, если он обычный файл (его читают и Codex, и платформа); если есть только
  CLAUDE.md, он остаётся каноничным — переименование стёрло бы историю файла;
- копии разные → НИЧЕГО не пишем (иначе правила одной из них пропадут), вызывающий поднимает
  тревогу оркестратору проекта.
Где симлинки недоступны (Windows, `core.symlinks=false`) вместо симлинка кладётся точная копия.

Изменение в чужом репозитории не должно оставлять грязное дерево (`merge_worker` отказывает от
любого неучтённого файла): правка делается только если оба пути чисты, ветка — основная, нет
merge/rebase, и сразу коммитится локально ровно этими двумя путями. Не вышло — откат до
исходных байтов. Ничего не пушится, remote не трогаем.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

AGENTS = "AGENTS.md"
CLAUDE = "CLAUDE.md"
_IMPORT_STUB = b"@AGENTS.md"
_IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")

REALERT_SECONDS = 24 * 3600
SWEEP_SECONDS = 6 * 3600
OK_STATES = frozenset({"absent", "linked", "linked_copy", "converted", "copied"})

_lock = threading.Lock()


@dataclass
class Outcome:
    state: str
    detail: str = ""
    sizes: dict[str, int] = field(default_factory=dict)

    @property
    def needs_attention(self) -> bool:
        return self.state not in OK_STATES


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, errors="replace",
    )


def symlinks_supported(root: Path) -> bool:
    if os.name == "nt":
        return False
    return _git(root, "config", "--type=bool", "core.symlinks").stdout.strip() != "false"


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _snapshot(path: Path):
    if path.is_symlink():
        return ("link", os.readlink(path))
    if path.exists():
        return ("file", path.read_bytes(), path.stat().st_mode & 0o7777)
    return ("none",)


def _restore(path: Path, snap) -> None:
    if snap[0] == "none":
        if path.is_symlink() or path.exists():
            path.unlink()
        return
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    if snap[0] == "link":
        os.symlink(snap[1], tmp)
    else:
        tmp.write_bytes(snap[1])
        tmp.chmod(snap[2])
    os.replace(tmp, path)


def _place(path: Path, source: Path, use_symlink: bool) -> bool:
    """Make `path` a symlink to `source.name` (or an exact copy). Returns whether it is a link."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        linked = False
        if use_symlink:
            try:
                os.symlink(source.name, tmp)
                linked = True
            except OSError:
                pass
        if not linked:
            tmp.write_bytes(_read(source))
            tmp.chmod(source.stat().st_mode & 0o7777)
        os.replace(tmp, path)
        return linked
    finally:
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()


def _git_blocker(root: Path) -> str:
    """Why a commit in this checkout would be unsafe or impossible; '' = go ahead."""
    from app.workspace import resolve_base_branch

    top = _git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return ""  # not a repository: nothing to commit, nothing to dirty
    if _git(root, "rev-parse", "--verify", "-q", "HEAD").returncode != 0:
        return "repository has no commits"
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if not branch:
        return "HEAD is detached"
    try:
        mainline = resolve_base_branch(str(root))
    except ValueError as error:
        return f"mainline unknown: {error}"
    if branch != mainline:
        return f"checked-out branch is {branch}, not mainline {mainline}"
    for name in _IN_PROGRESS:
        marker = _git(root, "rev-parse", "--git-path", name).stdout.strip()
        if marker and (root / marker if not os.path.isabs(marker) else Path(marker)).exists():
            return f"a git operation is in progress ({name})"
    status = _git(root, "status", "--porcelain", "--ignored", "--", AGENTS, CLAUDE)
    dirty = [line for line in status.stdout.splitlines() if not line.startswith("!!")]
    if status.returncode != 0 or dirty:
        return "uncommitted or untracked changes in AGENTS.md/CLAUDE.md: " + "; ".join(dirty)
    return ""


def _commit(root: Path, paths: list[str], message: str) -> str:
    """Commit exactly `paths` (ignored ones stay out). Returns an error text or ''."""
    if _git(root, "rev-parse", "--show-toplevel").returncode != 0:
        return ""
    wanted = [p for p in paths if _git(root, "check-ignore", "-q", p).returncode != 0]
    if not wanted:
        return ""
    added = _git(root, "add", "--", *wanted)
    if added.returncode != 0:
        return f"git add: {added.stderr.strip()}"
    done = _git(root, "commit", "-m", message, "--only", "--", *wanted)
    if done.returncode != 0:
        return f"git commit: {(done.stderr or done.stdout).strip()}"
    return ""


def _link(root: Path, canonical: Path, other: Path, outcome: str) -> Outcome:
    blocker = _git_blocker(root)
    if blocker:
        return Outcome("blocked", blocker)
    snaps = {p: _snapshot(p) for p in (canonical, other)}
    try:
        linked = _place(other, canonical, symlinks_supported(root))
        error = _commit(
            root, [other.name],
            f"rules: {other.name} is {'a symlink to' if linked else 'an exact copy of'} "
            f"{canonical.name} (Orchestra V-902)",
        )
    except OSError as exc:
        error = f"{type(exc).__name__}: {exc}"
    if error:
        for path, snap in snaps.items():
            _restore(path, snap)
        _git(root, "reset", "-q", "--", other.name)
        return Outcome("blocked", f"could not record the change, rolled back: {error}")
    return Outcome(outcome if linked or outcome != "converted" else "copied",
                   f"{other.name} -> {canonical.name}")


def reconcile(root: str | Path) -> Outcome:
    root = Path(root)
    agents, claude = root / AGENTS, root / CLAUDE
    with _lock:
        present = [p for p in (agents, claude) if os.path.lexists(p)]
        for p in present:
            if not p.exists():
                return Outcome("broken", f"{p.name} is a dangling symlink")
            if not p.is_file():
                return Outcome("blocked", f"{p.name} is not a regular file")
        if not present:
            return Outcome("absent")
        sizes = {p.name: p.stat().st_size for p in present}
        if len(present) == 1:
            only = present[0]
            other = claude if only == agents else agents
            result = _link(root, only, other, "converted")
            result.sizes = sizes
            return result
        if agents.resolve() == claude.resolve() or _read(claude).strip() == _IMPORT_STUB:
            return Outcome("linked", sizes=sizes)
        if _read(agents) != _read(claude):
            # A git symlink checked out as text (core.symlinks=false) holds just the target name.
            if not symlinks_supported(root) and (
                _read(claude).strip() == AGENTS.encode() or _read(agents).strip() == CLAUDE.encode()
            ):
                return Outcome("linked_copy", "git symlink checked out as a text stub", sizes)
            return Outcome("diverged", sizes=sizes)
        if not symlinks_supported(root):
            return Outcome("linked_copy", sizes=sizes)
        canonical = agents if not agents.is_symlink() else claude
        other = claude if canonical == agents else agents
        result = _link(root, canonical, other, "converted")
        result.sizes = sizes
        return result


def alert_text(scope: str, outcome: Outcome) -> str:
    sizes = ", ".join(f"{name} {size} B" for name, size in outcome.sizes.items())
    if outcome.state == "diverged":
        body = (
            f"AGENTS.md and CLAUDE.md in {scope} are two different files ({sizes}). Codex reads "
            "AGENTS.md, Claude reads CLAUDE.md, so part of the agents works by outdated rules. "
            "Platform did not overwrite anything. Fix: merge the content into ONE file "
            "(AGENTS.md), make the other a symlink to it (`ln -sf AGENTS.md CLAUDE.md`), commit. "
            "The platform re-checks every few hours and reminds you daily until it is fixed."
        )
    else:
        body = (
            f"AGENTS.md/CLAUDE.md in {scope} could not be unified automatically: "
            f"{outcome.state}: {outcome.detail}. Fix the cause (commit or clean the two files, "
            "return to the main branch) or make them one file plus a symlink by hand; "
            "the platform retries every few hours and reminds daily."
        )
    return "RULES FILES: " + body


def due_for_alert(scope: str, outcome: Outcome, now: float | None = None) -> bool:
    """Daily reminder, immediately when the kind of problem changes; a fixed scope forgets itself."""
    from app.db import kv_delete, kv_get, kv_set

    key = f"rules_link_alert:{scope}"
    if not outcome.needs_attention:
        if kv_get(key):
            kv_delete(key)
        return False
    now = time.time() if now is None else now
    try:
        last = json.loads(kv_get(key) or "{}")
    except ValueError:
        last = {}
    if last.get("state") == outcome.state and now - float(last.get("at", 0)) < REALERT_SECONDS:
        return False
    kv_set(key, json.dumps({"state": outcome.state, "at": now}))
    return True


async def sweep(session_manager) -> dict[str, str]:
    """Reconcile every project where Orchestra has live sessions; alert its orchestrator."""
    import asyncio

    from app.db import get_all_sessions
    from app.events import MessageProvenance
    from app.notify import orchestrator_for_scope

    scopes = sorted({(row.get("scope") or "").rstrip("/") for row in get_all_sessions()} - {""})
    states: dict[str, str] = {}
    for scope in scopes:
        if not Path(scope).is_dir():
            continue
        try:
            outcome = await asyncio.to_thread(reconcile, scope)
        except Exception as error:
            outcome = Outcome("blocked", f"{type(error).__name__}: {error}")
        states[scope] = outcome.state
        if outcome.state in ("converted", "copied"):
            logger.info("rules_link %s: %s %s", scope, outcome.state, outcome.detail)
        if not due_for_alert(scope, outcome):
            continue
        orch = orchestrator_for_scope(scope)
        if not orch:
            logger.warning("rules_link %s: %s %s — no orchestrator to tell",
                           scope, outcome.state, outcome.detail)
            continue
        try:
            await session_manager.send(
                orch["id"], alert_text(scope, outcome),
                provenance=MessageProvenance(
                    origin="platform", senders=("Orchestra",), subtype="rules_link", ref=scope),
            )
        except Exception as error:
            logger.warning("rules_link %s: alert to %s failed: %s", scope, orch["name"], error)
    return states
