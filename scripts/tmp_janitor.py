#!/usr/bin/env python3
"""Delete stale temporary trees that no process uses (bg cron_command, pattern `TMP_JANITOR:`).

Workers leave multi-GB scratch in /tmp (test trees, source copies, mktemp dirs) and nothing
ever removed it: on the VPS /tmp is the root disk, and about 3.5 GB/day of such scratch was
part of the 01.11.2026 disk-full incident. The owner's standing rule for cleanup without
asking (02.11.2026) is mechanised here: only temporary files that no process uses and
nobody touched for 3+ days. Everything else is reported, never deleted:

* only direct children of the given roots (default /tmp/* and /var/tmp/*, no dot entries),
  owned by the running user, never followed through a symlink; roots must be real paths;
* "touched" is the newest mtime or ctime of anything in the tree, plus atime of regular
  files (a tool read from /tmp every day stays); a time in the future is reported;
* "used" is any process whose cwd, root, exe, open fd, mapped file, argv (relative
  arguments resolved against its cwd) or environment refers to the tree. As an ordinary
  user only argv of other users' processes is readable: their cwd and fds are not seen;
* a Git repository, worktree or bare repository anywhere inside (except pytest fixture
  repos under pytest-*/popen-gw* directories), a socket, FIFO or device node, a mount
  point or another filesystem, files of another owner, a `.orchestra-keep` marker, or a
  system name (systemd-private-*, tmux-*, ...) keep the tree. Stale big ones go to the
  owner. With --dead-sockets a socket nobody listens on (absent from /proc/net/unix) is an
  ordinary file; that switch is the owner's decision.

A tree is renamed to a hidden name before deletion, so a worker that recreates the same
name meanwhile gets a fresh directory. Without --apply nothing is deleted. Stdlib only.
"""

from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_ROOTS = ("/tmp", "/var/tmp")
DEFAULT_MIN_AGE_DAYS = 3.0
KEEP_MARKER = ".orchestra-keep"
TRASH_PREFIX = ".tmp-janitor-"
PROTECTED_NAMES = (
    "systemd-private-*", "snap-private-tmp", "tmux-*", "ssh-*", "pulse-*", "dbus-*",
    "*.sock", "*.socket", "*.pid", "*.lock",
)
# Repositories below such directories are pytest fixtures, not somebody's work.
FIXTURE_PARTS = ("pytest*", "popen-gw*")
# A tree this large is reported instead of walked further.
MAX_ENTRIES = 2_000_000
FUTURE_SLACK_SECONDS = 86400
REMIND_SECONDS = 7 * 86400
_PATH_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
GIB = 1024 ** 3


def _gib(value: int) -> str:
    return f"{value / GIB:.2f} ГБ"


class Tree:
    __slots__ = ("path", "bytes", "entries", "newest", "skip")

    def __init__(self, path: str):
        self.path = path
        self.bytes = 0
        self.entries = 0
        self.newest = 0.0
        self.skip = ""


class Host:
    """What the kernel says about sockets and mounts, read once per run."""

    def __init__(self, bound_sockets: set[str], mount_points: set[str]):
        self.bound_sockets = bound_sockets
        self.mount_points = mount_points

    @classmethod
    def read(cls) -> "Host":
        bound: set[str] = set()
        try:
            for line in Path("/proc/net/unix").read_text(errors="replace").splitlines()[1:]:
                parts = line.split(maxsplit=7)
                if len(parts) == 8 and parts[7].startswith("/"):
                    bound.add(parts[7])
        except OSError:
            bound = set()
        mounts: set[str] = set()
        try:
            for line in Path("/proc/self/mountinfo").read_text(errors="replace").splitlines():
                parts = line.split()
                if len(parts) > 4:
                    mounts.add(_unescape(parts[4]))
        except OSError:
            pass
        return cls(bound, mounts)


def _unescape(value: str) -> str:
    # mountinfo escapes space, tab, newline and backslash as \ooo.
    out, index = [], 0
    while index < len(value):
        if value[index] == "\\" and value[index + 1:index + 4].isdigit():
            out.append(chr(int(value[index + 1:index + 4], 8)))
            index += 4
        else:
            out.append(value[index])
            index += 1
    return "".join(out)


def _is_fixture(path: str, top: str) -> bool:
    parts = os.path.relpath(path, top).split(os.sep)
    return any(fnmatch.fnmatch(part, pattern) for part in parts for pattern in FIXTURE_PARTS)


def inspect_tree(path: str, uid: int, host: Host, *, dead_sockets: bool = False) -> Tree:
    """Size, newest change and the first reason this tree must not be deleted."""
    tree = Tree(path)
    try:
        top = os.lstat(path)
        device = os.lstat(os.path.dirname(path)).st_dev
    except OSError as error:
        tree.skip = f"не читается: {error.strerror}"
        return tree
    if stat.S_ISLNK(top.st_mode):
        tree.skip = "символьная ссылка"
        return tree
    if top.st_uid != uid:
        tree.skip = "чужой владелец"
        return tree
    name = os.path.basename(path)
    if any(fnmatch.fnmatch(name, pattern) for pattern in PROTECTED_NAMES):
        tree.skip = "системное имя"
        return tree
    if any(point == path or point.startswith(path + "/") for point in host.mount_points):
        tree.skip = "внутри точка монтирования"
    stack = [(path, top)]
    while stack:
        current, info = stack.pop()
        tree.entries += 1
        tree.bytes += info.st_blocks * 512
        mode = info.st_mode
        tree.newest = max(tree.newest, info.st_mtime, info.st_ctime)
        if stat.S_ISREG(mode):
            tree.newest = max(tree.newest, info.st_atime)
        other_device = info.st_dev != device
        if not tree.skip:
            if stat.S_ISSOCK(mode):
                if not dead_sockets or current in host.bound_sockets:
                    tree.skip = f"внутри сокет: {current}"
            elif stat.S_ISFIFO(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
                tree.skip = f"внутри канал или устройство: {current}"
            elif info.st_uid != uid:
                tree.skip = f"внутри файл другого владельца: {current}"
            elif other_device:
                tree.skip = f"внутри другая файловая система: {current}"
        if tree.entries >= MAX_ENTRIES:
            tree.skip = tree.skip or f"больше {MAX_ENTRIES} файлов, не обойдён целиком"
            break
        if not stat.S_ISDIR(mode) or other_device:
            continue
        children: list[tuple[str, os.stat_result]] = []
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        children.append((entry.path, entry.stat(follow_symlinks=False)))
                    except OSError:
                        tree.skip = tree.skip or f"не читается: {entry.path}"
        except OSError:
            tree.skip = tree.skip or f"не читается: {current}"
        names = {os.path.basename(child) for child, _ in children}
        repo = ".git" in names or {"HEAD", "objects", "refs"} <= names
        if repo and not tree.skip and not _is_fixture(current, path):
            where = "" if current == path else f": {current}"
            tree.skip = f"Git-репозиторий или worktree, может быть несохранённая работа{where}"
        if KEEP_MARKER in names and current == path and not tree.skip:
            tree.skip = f"есть метка {KEEP_MARKER}"
        stack.extend(children)
    return tree


def _process_refs(proc: Path = Path("/proc")) -> list[tuple[int, str]]:
    """Every path-like reference of every readable process: (pid, text)."""
    refs: list[tuple[int, str]] = []
    own = os.getpid()
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == own:
            continue
        pid = int(entry.name)
        cwd = ""
        for link in ("cwd", "root", "exe"):
            try:
                target = os.readlink(entry / link)
            except OSError:
                continue
            refs.append((pid, target))
            if link == "cwd":
                cwd = target
        try:
            for fd in (entry / "fd").iterdir():
                try:
                    refs.append((pid, os.readlink(fd)))
                except OSError:
                    pass
        except OSError:
            pass
        try:
            for line in (entry / "maps").read_text(errors="replace").splitlines():
                parts = line.split(maxsplit=5)
                if len(parts) == 6:
                    refs.append((pid, parts[5]))
        except OSError:
            pass
        for blob in ("cmdline", "environ"):
            try:
                items = (entry / blob).read_bytes().split(b"\0")
            except OSError:
                continue
            for raw in items:
                item = os.fsdecode(raw)
                if not item:
                    continue
                if "/" in item:
                    refs.append((pid, item))
                if blob == "cmdline" and cwd:
                    # `cd /tmp && python3 x/serve.py` names x only relative to its cwd.
                    for token in (item, item.partition("=")[2]):
                        if token and not token.startswith(("/", "-")):
                            refs.append((pid, os.path.normpath(os.path.join(cwd, token))))
    return refs


def _mentions(text: str, path: str) -> bool:
    start = text.find(path)
    while start != -1:
        end = start + len(path)
        if end == len(text) or text[end] == "/" or text[end] not in _PATH_CHARS:
            before = text[start - 1] if start else ""
            if not before or before not in _PATH_CHARS:
                return True
        start = text.find(path, start + 1)
    return False


def holders(path: str, refs: Iterable[tuple[int, str]]) -> list[int]:
    return sorted({pid for pid, text in refs if _mentions(text, path)})


def real_roots(roots: Iterable[str]) -> list[str]:
    """/proc shows resolved paths, so a symlinked root would blind the holder check."""
    checked = []
    for root in roots:
        if not os.path.isabs(root):
            raise ValueError(f"root must be absolute: {root}")
        normal = os.path.normpath(root)
        if os.path.islink(normal) or os.path.realpath(normal) != normal:
            raise ValueError(f"root must be a real directory, not through a symlink: {root}")
        checked.append(normal)
    return checked


def candidates(roots: Iterable[str]) -> list[str]:
    found: list[str] = []
    for root in real_roots(roots):
        found.extend(sorted(glob.glob(os.path.join(glob.escape(root), "*"))))
    return found


def _remove(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.unlink(path)


def _purge_leftover_trash(roots: list[str], uid: int, report: dict) -> None:
    """Finish deletions an earlier run renamed but could not complete."""
    for root in roots:
        for path in glob.glob(os.path.join(glob.escape(root), TRASH_PREFIX + "*")):
            try:
                info = os.lstat(path)
                if info.st_uid == uid and not stat.S_ISLNK(info.st_mode):
                    _remove(path)
            except OSError as error:
                report["errors"].append(
                    {"path": path, "bytes": 0, "newest": 0, "reason": f"{type(error).__name__}: {error}"}
                )


def run(args: argparse.Namespace, now: float | None = None,
        refs_source: Callable[[], list[tuple[int, str]]] = _process_refs,
        host: Host | None = None) -> dict:
    now = time.time() if now is None else now
    uid = os.getuid()
    host = Host.read() if host is None else host
    cutoff = now - args.min_age_days * 86400
    roots = real_roots(args.root)
    report = {"deleted": [], "kept": [], "owner": [], "errors": []}
    if args.apply:
        _purge_leftover_trash(roots, uid, report)
    refs = refs_source()
    big = args.report_mb * 2**20
    dead = getattr(args, "dead_sockets", False)
    for path in candidates(roots):
        tree = inspect_tree(path, uid, host, dead_sockets=dead)
        item = {"path": path, "bytes": tree.bytes, "newest": tree.newest}
        if tree.skip in ("чужой владелец", "символьная ссылка", "системное имя"):
            continue
        if not tree.skip and tree.newest > now + FUTURE_SLACK_SECONDS:
            tree.skip = "время изменения в будущем"
        if tree.skip:
            stale = tree.newest < cutoff or tree.skip == "время изменения в будущем"
            marked = tree.skip.startswith("есть метка")
            bucket = "owner" if stale and tree.bytes >= big and not marked else "kept"
            report[bucket].append({**item, "reason": tree.skip})
            continue
        if tree.newest >= cutoff:
            report["kept"].append({**item, "reason": "менялось меньше срока назад"})
            continue
        users = holders(path, refs)
        if users:
            report["kept"].append({**item, "reason": f"используется процессами {users[:5]}"})
            continue
        if not args.apply:
            report["deleted"].append({**item, "dry_run": True})
            continue
        outcome = _delete_checked(path, uid, host, cutoff, refs_source, dead)
        if outcome == "deleted":
            report["deleted"].append(item)
            if args.log:
                _append_log(Path(args.log), {**item, "deleted_at": now})
        elif outcome.startswith("kept:"):
            report["kept"].append({**item, "reason": outcome[5:]})
        else:
            report["errors"].append({**item, "reason": outcome})
    return report


def _delete_checked(path, uid, host, cutoff, refs_source, dead) -> str:
    # Re-check right before deleting: a worker may have started using it meanwhile.
    again = inspect_tree(path, uid, host, dead_sockets=dead)
    if again.skip or again.newest >= cutoff or holders(path, refs_source()):
        return "kept:изменилось во время проверки"
    trash = os.path.join(os.path.dirname(path), f"{TRASH_PREFIX}{os.getpid()}-{os.path.basename(path)}")
    try:
        os.rename(path, trash)
    except OSError as error:
        return f"{type(error).__name__}: {error}"
    # A process holding it by cwd or fd now shows the trash name.
    if holders(trash, refs_source()):
        try:
            os.rename(trash, path)
        except OSError as error:
            return f"занят после переименования, оставлен как {trash}: {error}"
        return "kept:занят после переименования"
    try:
        _remove(trash)
    except OSError as error:
        return f"{type(error).__name__}: {error} (остаток {trash} удалится следующим запуском)"
    return "deleted"


def _append_log(path: Path, record: dict) -> None:
    try:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass  # the deletion already happened; a full disk must not turn it into a failure


def _load_reported(path: str | None) -> dict[str, float]:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    reported = data.get("owner_reported", {}) if isinstance(data, dict) else {}
    return {
        key: float(value) for key, value in reported.items()
        if isinstance(key, str) and isinstance(value, (int, float))
    }


def _save_reported(path: str | None, reported: dict[str, float]) -> None:
    if not path:
        return
    try:
        directory = os.path.dirname(path) or "."
        fd, temp = tempfile.mkstemp(prefix=".tmp_janitor-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"owner_reported": reported}, stream, sort_keys=True)
            os.replace(temp, path)
        finally:
            Path(temp).unlink(missing_ok=True)
    except OSError:
        pass


def remember_owner(report: dict, state: str | None, now: float) -> int | None:
    """How many owner items are new or due again; the daily job must not nag daily."""
    if not state:
        return None
    reported = _load_reported(state)
    fresh = [
        item["path"] for item in report["owner"]
        if item["path"] not in reported or now - reported[item["path"]] >= REMIND_SECONDS
    ]
    current = {item["path"] for item in report["owner"]}
    kept = {path: ts for path, ts in reported.items() if path in current}
    kept.update({path: now for path in fresh})
    _save_reported(state, kept)
    return len(fresh)


def _when(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else "?"


def render(report: dict, apply: bool, report_mb: int, fresh_owner: int | None = None) -> list[str]:
    """`fresh_owner` is how many owner items were not reported recently (None: all)."""
    lines: list[str] = []
    deleted = sum(item["bytes"] for item in report["deleted"])
    verb = "удалено" if apply else "можно удалить (пробный прогон)"
    for item in report["deleted"]:
        lines.append(f"  - {_gib(item['bytes'])} {item['path']} (менялось {_when(item['newest'])})")
    for item in report["owner"]:
        lines.append(f"  ? {_gib(item['bytes'])} {item['path']}: {item['reason']}")
    for item in report["errors"]:
        lines.append(f"  ! {item['path']}: {item['reason']}")
    fresh = len(report["owner"]) if fresh_owner is None else fresh_owner
    loud = (deleted and deleted >= report_mb * 2**20) or fresh or report["errors"]
    head = f"{verb} {len(report['deleted'])} шт., {_gib(deleted)}"
    if report["owner"]:
        head += f"; нужно решение владельца: {len(report['owner'])} шт., "
        head += _gib(sum(item["bytes"] for item in report["owner"]))
        if fresh_owner is not None and fresh < len(report["owner"]):
            head += f" (новых {fresh}, остальные уже сообщены)"
    if report["errors"]:
        head += f"; ошибок удаления: {len(report['errors'])}"
    prefix = "TMP_JANITOR: " if loud else "tmp-janitor: "
    return [prefix + head, *lines]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", action="append", help="directory whose direct children are checked")
    parser.add_argument("--min-age-days", type=float, default=DEFAULT_MIN_AGE_DAYS)
    parser.add_argument("--apply", action="store_true", help="really delete (default: dry run)")
    parser.add_argument("--dead-sockets", action="store_true",
                        help="a socket nobody listens on does not keep a tree (owner's decision)")
    parser.add_argument("--log", help="append one JSON line per deleted tree")
    parser.add_argument("--state", help="remember owner items so they are re-sent only weekly")
    parser.add_argument("--report-mb", type=int, default=100,
                        help="print the TMP_JANITOR: alert only above this many MB")
    args = parser.parse_args(argv)
    args.root = args.root or list(DEFAULT_ROOTS)
    if args.min_age_days < 1:
        parser.error("--min-age-days below 1 is not a stale tree")
    try:
        report = run(args)
    except ValueError as error:
        parser.error(str(error))
    fresh = remember_owner(report, args.state, time.time())
    print("\n".join(render(report, args.apply, args.report_mb, fresh)))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
