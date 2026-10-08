#!/usr/bin/env python3
import os
import pwd
import re
import sqlite3
import stat
import subprocess
import sys
import time
import uuid


TMP = "/tmp"
HOME = "/home/kesha"
CODEX_ROOT = f"{HOME}/.orchestra/codex-home"
CACHE_TARGETS = [
    f"{HOME}/.cache/pip",
    f"{HOME}/.cache/ms-playwright",
    f"{HOME}/.cache/electron",
    f"{HOME}/.cache/conda",
    f"{HOME}/.cache/node-gyp",
    f"{HOME}/.cache/mesa_shader_cache",
    f"{HOME}/.cache/google-chrome-for-testing-headless",
]
RUNTIME_NAMES = {".X11-unix", ".ICE-unix", ".font-unix", ".Test-unix"}
DB_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm")
PRESERVE_MARKERS = {".git", ".hg", ".svn"}
KESHA_UID = pwd.getpwnam("kesha").pw_uid


def proc_references():
    refs = set()
    homes = set()
    errors = 0
    vanished = 0
    pids = [name for name in os.listdir("/proc") if name.isdigit()]
    for pid in pids:
        base = f"/proc/{pid}"
        values = []
        try:
            try:
                with open(f"{base}/environ", "rb") as stream:
                    env = stream.read().split(b"\0")
                for pair in env:
                    key, sep, value = pair.partition(b"=")
                    if not sep:
                        continue
                    value = os.fsdecode(value)
                    if key == b"CODEX_HOME":
                        homes.add(os.path.realpath(value))
                    if key == b"XDG_CACHE_HOME" and value == b"/home/kesha/.cache":
                        refs.add(f"{HOME}/.cache")
                    values.append(value)
            except (FileNotFoundError, ProcessLookupError):
                pass
            try:
                with open(f"{base}/cmdline", "rb") as stream:
                    values.append(stream.read().replace(b"\0", b" ").decode("utf-8", "replace"))
            except (FileNotFoundError, ProcessLookupError):
                pass
            for leaf in ("cwd", "exe"):
                try:
                    values.append(os.readlink(f"{base}/{leaf}"))
                except (FileNotFoundError, ProcessLookupError):
                    pass
                except OSError:
                    errors += 1
            try:
                for fd in os.listdir(f"{base}/fd"):
                    try:
                        values.append(os.readlink(f"{base}/fd/{fd}"))
                    except (FileNotFoundError, ProcessLookupError):
                        pass
                    except OSError:
                        errors += 1
            except (FileNotFoundError, ProcessLookupError):
                pass
            except OSError:
                errors += 1
        except (FileNotFoundError, ProcessLookupError):
            vanished += 1
            continue
        except OSError:
            errors += 1
            continue

        for value in values:
            value = value.removesuffix(" (deleted)")
            if value.startswith(TMP + "/"):
                refs.add(TMP + "/" + value[len(TMP + "/"):].split("/", 1)[0])
            for target in CACHE_TARGETS + [CODEX_ROOT]:
                if value == target or value.startswith(target + "/"):
                    if target == CODEX_ROOT:
                        refs.add(target + "/" + value[len(target + "/"):].split("/", 1)[0])
                    else:
                        refs.add(target)
    return refs, homes, errors, vanished, len(pids)


def tree_info(path, root_dev):
    newest = 0.0
    blocks = 0
    contains_git = False
    contains_db = False
    crossed_device = False
    errors = 0
    try:
        root_stat = os.lstat(path)
    except OSError:
        return 0, 0, False, False, False, 1
    if stat.S_ISLNK(root_stat.st_mode):
        return root_stat.st_blocks * 512, root_stat.st_mtime, False, False, False, 0
    if root_stat.st_dev != root_dev or os.path.ismount(path):
        return root_stat.st_blocks * 512, root_stat.st_mtime, False, False, True, 0
    blocks += root_stat.st_blocks * 512
    newest = root_stat.st_mtime
    if not stat.S_ISDIR(root_stat.st_mode):
        contains_db = path.lower().endswith(DB_SUFFIXES)
        return blocks, newest, False, contains_db, False, 0

    def on_walk_error(_error):
        nonlocal errors
        errors += 1

    for directory, subdirs, files in os.walk(path, followlinks=False, onerror=on_walk_error):
        for dirname in list(subdirs):
            child = os.path.join(directory, dirname)
            try:
                child_stat = os.lstat(child)
                if "backup" in dirname.lower() or "database" in dirname.lower():
                    contains_db = True
                if dirname.lower().endswith(DB_SUFFIXES):
                    contains_db = True
                if stat.S_ISLNK(child_stat.st_mode):
                    blocks += child_stat.st_blocks * 512
                    newest = max(newest, child_stat.st_mtime)
                if os.path.ismount(child):
                    crossed_device = True
            except OSError:
                errors += 1
        for marker in PRESERVE_MARKERS:
            if marker in subdirs or marker in files:
                contains_git = True
        try:
            dir_stat = os.lstat(directory)
            if dir_stat.st_dev != root_dev:
                crossed_device = True
                subdirs[:] = []
                continue
            blocks += dir_stat.st_blocks * 512
            newest = max(newest, dir_stat.st_mtime)
        except OSError:
            errors += 1
            subdirs[:] = []
            continue
        for filename in files:
            lower = filename.lower()
            if lower.endswith(DB_SUFFIXES) or "backup" in lower or "database" in lower:
                contains_db = True
            file_path = os.path.join(directory, filename)
            try:
                file_stat = os.lstat(file_path)
                if file_stat.st_dev != root_dev:
                    crossed_device = True
                    continue
                blocks += file_stat.st_blocks * 512
                newest = max(newest, file_stat.st_mtime)
            except OSError:
                errors += 1
    return blocks, newest, contains_git, contains_db, crossed_device, errors


def tmp_candidates(refs, now):
    root_dev = os.lstat(TMP).st_dev
    candidates = []
    counts = {"fresh": 0, "referenced": 0, "runtime": 0, "symlink": 0, "mount": 0, "git": 0, "db_or_backup": 0, "scan_error": 0}
    for name in os.listdir(TMP):
        path = os.path.join(TMP, name)
        try:
            entry = os.lstat(path)
        except OSError:
            counts["scan_error"] += 1
            continue
        if name in RUNTIME_NAMES or name.startswith("systemd-private-"):
            counts["runtime"] += 1
            continue
        if stat.S_ISLNK(entry.st_mode):
            counts["symlink"] += 1
            continue
        if entry.st_dev != root_dev or os.path.ismount(path):
            counts["mount"] += 1
            continue
        blocks, newest, contains_git, contains_db, crossed_device, errors = tree_info(path, root_dev)
        if errors:
            counts["scan_error"] += 1
            continue
        if crossed_device:
            counts["mount"] += 1
            continue
        if contains_git:
            counts["git"] += 1
            continue
        if contains_db or "backup" in name.lower() or "database" in name.lower():
            counts["db_or_backup"] += 1
            continue
        if TMP + "/" + name in refs:
            counts["referenced"] += 1
            continue
        if newest >= now - 7200:
            counts["fresh"] += 1
            continue
        candidates.append((path, blocks, entry.st_uid))
    return candidates, counts


def run_as(uid, command, path):
    env = os.environ.copy()
    env.pop("XDG_DATA_HOME", None)
    if uid == KESHA_UID:
        argv = ["sudo", "-n", "-u", "kesha", "-H", command, path]
    else:
        argv = [command, path]
        env["HOME"] = "/root"
    return subprocess.run(argv, capture_output=True, text=True, env=env)


def trash_stage(stage, uid):
    trash = run_as(uid, "/usr/bin/trash", stage)
    if trash.returncode:
        return False, "trash", trash.stderr[-300:]
    purge = run_as(uid, "/usr/bin/trash-rm", stage)
    if purge.returncode:
        return False, "trash-rm", purge.stderr[-300:]
    if os.path.exists(stage):
        return False, "stage-still-exists", ""
    return True, "", ""


def stage_and_remove(parent, items, uid):
    stage = os.path.join(parent, f".V-764-stage-{uuid.uuid4().hex}")
    os.mkdir(stage, 0o700)
    if uid == KESHA_UID:
        kesha = pwd.getpwnam("kesha")
        os.chown(stage, KESHA_UID, kesha.pw_gid)
    moved = []
    for index, (source, _blocks, _owner) in enumerate(items):
        destination = os.path.join(stage, f"item-{index:05d}")
        try:
            os.rename(source, destination)
            moved.append((source, destination))
        except OSError:
            for old, staged in reversed(moved):
                if os.path.lexists(staged) and not os.path.lexists(old):
                    os.rename(staged, old)
            os.rmdir(stage)
            return False, "stage-rename", source
    okay, phase, detail = trash_stage(stage, uid)
    if not okay and phase == "trash":
        for old, staged in reversed(moved):
            if os.path.lexists(staged) and not os.path.lexists(old):
                os.rename(staged, old)
        if os.path.isdir(stage):
            os.rmdir(stage)
    return okay, phase, detail


def audit_only():
    refs, homes, proc_errors, vanished, proc_count = proc_references()
    db = sqlite3.connect(f"file:{HOME}/orchestra/data/orchestra.db?mode=ro", uri=True)
    nonarchived = {row[0] for row in db.execute("select id from sessions where status!='archived'")}
    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
    homes_on_disk = [name for name in os.listdir(CODEX_ROOT) if uuid_re.fullmatch(name) and os.path.isdir(os.path.join(CODEX_ROOT, name))]
    active_homes = [name for name in homes_on_disk if name in nonarchived or os.path.realpath(os.path.join(CODEX_ROOT, name)) in homes or os.path.join(CODEX_ROOT, name) in refs]
    print({"proc_count": proc_count, "proc_errors": proc_errors, "proc_vanished": vanished,
           "db_total": db.execute("select count(*) from sessions").fetchone()[0],
           "db_archived": db.execute("select count(*) from sessions where status='archived'").fetchone()[0],
           "db_nonarchived": len(nonarchived), "codex_uuid_dirs": len(homes_on_disk),
           "codex_protected": len(active_homes), "codex_archived_candidates": len(homes_on_disk)-len(active_homes)})
    candidates, counts = tmp_candidates(refs, time.time())
    print({"tmp_eligible": len(candidates), "tmp_allocated_bytes": sum(row[1] for row in candidates), "tmp_preserved": counts})
    for path in CACHE_TARGETS:
        if not os.path.lexists(path):
            print({"cache": path, "status": "absent"})
            continue
        blocks, _newest, _git, _db, mount, errors = tree_info(path, os.lstat(HOME).st_dev)
        print({"cache": path, "allocated_bytes": blocks, "referenced": path in refs, "mount": mount, "scan_errors": errors})


def clean():
    refs, _homes, proc_errors, vanished, proc_count = proc_references()
    if proc_errors:
        raise SystemExit(f"refusing cleanup: {proc_errors} /proc read errors across {proc_count} processes")
    now = time.time()
    candidates, counts = tmp_candidates(refs, now)
    # Refresh process references and tree mtimes before moving anything.
    refs, _homes, proc_errors, vanished2, proc_count2 = proc_references()
    if proc_errors:
        raise SystemExit(f"refusing cleanup: {proc_errors} /proc read errors across {proc_count2} processes")
    candidates, counts = tmp_candidates(refs, time.time())
    tmp_bytes = sum(row[1] for row in candidates)
    tmp_result = stage_and_remove(TMP, candidates, 0) if candidates else (True, "", "")

    refs, _homes, proc_errors, vanished3, proc_count3 = proc_references()
    if proc_errors:
        raise SystemExit(f"refusing cache cleanup: {proc_errors} /proc read errors across {proc_count3} processes")
    cache_items = []
    cache_preserved = []
    for path in CACHE_TARGETS:
        if not os.path.lexists(path):
            continue
        st = os.lstat(path)
        blocks, _newest, _git, contains_db, crossed_device, errors = tree_info(path, st.st_dev)
        if stat.S_ISLNK(st.st_mode) or os.path.ismount(path) or contains_db or crossed_device or errors or path in refs or f"{HOME}/.cache" in refs:
            cache_preserved.append((path, blocks, "active-or-uncertain"))
            continue
        if st.st_uid != KESHA_UID:
            cache_preserved.append((path, blocks, "unexpected-owner"))
            continue
        cache_items.append((path, blocks, st.st_uid))
    cache_bytes = sum(row[1] for row in cache_items)
    cache_stage_result = stage_and_remove(os.path.dirname(CACHE_TARGETS[0]), cache_items, KESHA_UID) if cache_items else (True, "", "")

    db = sqlite3.connect(f"file:{HOME}/orchestra/data/orchestra.db?mode=ro", uri=True)
    nonarchived = {row[0] for row in db.execute("select id from sessions where status!='archived'")}
    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
    homes_on_disk = [name for name in os.listdir(CODEX_ROOT) if uuid_re.fullmatch(name) and os.path.isdir(os.path.join(CODEX_ROOT, name))]
    codehome_candidates = [name for name in homes_on_disk if name not in nonarchived and os.path.realpath(os.path.join(CODEX_ROOT, name)) not in _homes and os.path.join(CODEX_ROOT, name) not in refs]
    print({"proc_count_before": proc_count, "proc_errors": proc_errors, "proc_vanished": vanished+vanished2,
           "tmp_candidates": len(candidates), "tmp_allocated_bytes": tmp_bytes, "tmp_delete_result": tmp_result,
           "tmp_preserved_counts": counts,
           "cache_candidates": [(path, blocks) for path, blocks, uid in cache_items],
           "cache_allocated_bytes": cache_bytes, "cache_delete_result": cache_stage_result,
           "cache_preserved": cache_preserved,
           "db_archived": db.execute("select count(*) from sessions where status='archived'").fetchone()[0],
           "db_nonarchived": len(nonarchived), "codex_uuid_dirs": len(homes_on_disk),
           "codex_archived_candidates": len(codehome_candidates)})


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"audit", "clean"}:
        raise SystemExit("usage: cleanup.py audit|clean")
    audit_only() if sys.argv[1] == "audit" else clean()
