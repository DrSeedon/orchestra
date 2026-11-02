from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import tmp_janitor as janitor

DAY = 86400


def _args(root: Path, *, apply: bool = False, log: Path | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        root=[str(root)], min_age_days=3.0, apply=apply,
        log=str(log) if log else None, report_mb=0,
    )


def _tree(root: Path, name: str, size: int = 4096) -> Path:
    tree = root / name
    (tree / "sub").mkdir(parents=True)
    (tree / "sub" / "data.bin").write_bytes(b"x" * size)
    return tree


@pytest.fixture
def root(tmp_path: Path) -> Path:
    # conftest's autouse isolation writes its own files into tmp_path itself.
    scan = tmp_path.resolve() / "scan"
    scan.mkdir()
    return scan


def _no_refs():
    return []


def _later(days: float = 4) -> float:
    # ctime cannot be set back, so the clock moves forward instead.
    return time.time() + days * DAY


def _paths(items):
    return [Path(item["path"]).name for item in items]


def test_dry_run_lists_but_deletes_nothing(root):
    tree = _tree(root, "worker-scratch")
    report = janitor.run(_args(root), now=_later(), refs_source=_no_refs)
    assert _paths(report["deleted"]) == ["worker-scratch"]
    assert report["deleted"][0]["dry_run"] is True
    assert tree.exists()


def test_apply_deletes_only_stale_unused_trees_and_logs_them(tmp_path):
    root = tmp_path / "tmp"
    root.mkdir()
    stale = _tree(root, "stale")
    loose = root / "codex_review_x.jsonl"
    loose.write_text("{}\n")
    log = tmp_path / "janitor.jsonl"
    report = janitor.run(_args(root, apply=True, log=log), now=_later(), refs_source=_no_refs)
    assert sorted(_paths(report["deleted"])) == ["codex_review_x.jsonl", "stale"]
    assert not stale.exists() and not loose.exists()
    assert len(log.read_text().splitlines()) == 2


def test_recent_tree_is_kept(root):
    tree = _tree(root, "fresh")
    report = janitor.run(_args(root, apply=True), now=_later(2.5), refs_source=_no_refs)
    assert report["deleted"] == [] and tree.exists()
    assert "меньше срока" in report["kept"][0]["reason"]


def test_one_recent_file_deep_inside_keeps_the_whole_tree(root):
    tree = _tree(root, "mixed")
    now = _later()
    deep = tree / "sub" / "new.log"
    deep.write_text("still writing\n")
    os.utime(deep, (now - 3600, now - 3600))  # mtime "an hour ago" relative to the fake clock
    old = now - 10 * DAY
    for path in (tree, tree / "sub", tree / "sub" / "data.bin"):
        os.utime(path, (old, old))
    report = janitor.run(_args(root, apply=True), now=now, refs_source=_no_refs)
    assert report["deleted"] == [] and deep.exists()


@pytest.mark.parametrize("ref", [
    "{path}", "{path}/sub/data.bin", "--basetemp={path}/sub", "TMPDIR={path}",
])
def test_tree_used_by_a_process_is_kept(root, ref):
    tree = _tree(root, "busy")
    refs = lambda: [(4242, ref.format(path=tree))]  # noqa: E731
    report = janitor.run(_args(root, apply=True), now=_later(), refs_source=refs)
    assert report["deleted"] == [] and tree.exists()
    assert "4242" in report["kept"][0]["reason"]


@pytest.mark.parametrize("ref", ["{path}-other/file", "/var{path}", "{path}2"])
def test_similar_paths_are_not_holders(root, ref):
    tree = _tree(root, "busy")
    refs = lambda: [(4242, ref.format(path=tree))]  # noqa: E731
    report = janitor.run(_args(root, apply=True), now=_later(), refs_source=refs)
    assert _paths(report["deleted"]) == ["busy"] and not tree.exists()


def test_real_process_cwd_is_detected(root):
    tree = _tree(root, "cwd-held")
    proc = subprocess.Popen(["sleep", "30"], cwd=tree)
    try:
        report = janitor.run(_args(root, apply=True), now=_later())
    finally:
        proc.kill()
        proc.wait()
    assert tree.exists()
    assert str(proc.pid) in report["kept"][0]["reason"]


def test_git_repository_or_worktree_goes_to_the_owner(root):
    repo = _tree(root, "clone")
    (repo / ".git").mkdir()
    worktree = _tree(root, "linked")
    (worktree / ".git").write_text("gitdir: /somewhere/.git/worktrees/linked\n")
    report = janitor.run(_args(root, apply=True), now=_later(), refs_source=_no_refs)
    assert sorted(_paths(report["owner"])) == ["clone", "linked"]
    assert repo.exists() and worktree.exists()
    lines = janitor.render(report, True, 0)
    assert lines[0].startswith("TMP_JANITOR: ")
    assert "нужно решение владельца: 2 шт." in lines[0]


def test_keep_marker_socket_symlink_and_system_names_are_kept(root):
    marked = _tree(root, "marked")
    (marked / janitor.KEEP_MARKER).write_text("")
    sock_dir = _tree(root, "with-socket")
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(sock_dir / "s"))
    target = _tree(root / "elsewhere", "target")
    (root / "link").symlink_to(target)
    system = _tree(root, "systemd-private-abc")
    try:
        report = janitor.run(_args(root, apply=True), now=_later(), refs_source=_no_refs)
    finally:
        server.close()
    assert _paths(report["deleted"]) == ["elsewhere"]  # the real dir is fine, the link is not
    assert marked.exists() and sock_dir.exists() and system.exists()
    assert (root / "link").is_symlink()
    assert not target.exists()
    kept = {Path(item["path"]).name: item["reason"] for item in report["kept"]}
    owner = {Path(item["path"]).name: item["reason"] for item in report["owner"]}
    # A marker is a decision already taken; a stale socket tree is reported to the owner.
    assert "метка" in kept["marked"] and "сокет" in owner["with-socket"]
    assert {"link", "systemd-private-abc"}.isdisjoint(kept | owner)


def test_recheck_before_delete_keeps_a_tree_that_became_busy(root):
    tree = _tree(root, "race")
    calls = iter([[], [(7, str(tree))]])
    report = janitor.run(_args(root, apply=True), now=_later(), refs_source=lambda: next(calls))
    assert tree.exists()
    assert "изменилось" in report["kept"][0]["reason"]


def test_quiet_summary_below_report_threshold(root):
    _tree(root, "tiny", size=10)
    report = janitor.run(_args(root, apply=True), now=_later(), refs_source=_no_refs)
    assert janitor.render(report, True, 100)[0].startswith("tmp-janitor: удалено 1 шт.")
    assert janitor.render(report, True, 0)[0].startswith("TMP_JANITOR: удалено 1 шт.")


def test_main_refuses_relative_root_and_tiny_age(tmp_path):
    with pytest.raises(ValueError):
        janitor.candidates(["relative"])
    with pytest.raises(SystemExit):
        janitor.main(["--root", str(tmp_path), "--min-age-days", "0.5"])


def test_process_refs_include_own_children(tmp_path):
    tmp_path = tmp_path.resolve()
    proc = subprocess.Popen(["sleep", "30"], cwd=tmp_path)
    try:
        refs = janitor._process_refs()
    finally:
        proc.kill()
        proc.wait()
    assert (proc.pid, str(tmp_path)) in refs


def test_mount_point_or_other_filesystem_is_never_walked_into_deletion(root, monkeypatch):
    tree = _tree(root, "mounted")
    real_lstat = os.lstat

    def lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if os.fspath(path) == str(root):
            values = list(info)
            values[2] = info.st_dev + 1  # st_dev: the scan root sits on another device
            return os.stat_result(values)
        return info

    monkeypatch.setattr(janitor.os, "lstat", lstat)
    report = janitor.run(_args(root, apply=True), now=_later(), refs_source=_no_refs)
    assert tree.exists() and report["deleted"] == []
    reasons = [item["reason"] for item in report["kept"] + report["owner"]]
    assert any("другая файловая система" in reason for reason in reasons)


def test_ctime_counts_as_touched_even_when_mtimes_are_old(root):
    """`cp -a` of an old tree keeps old mtimes; only ctime shows it is a fresh copy."""
    tree = _tree(root, "fresh-copy")
    old = time.time() - 10 * DAY
    for path in (tree / "sub" / "data.bin", tree / "sub", tree):
        os.utime(path, (old, old))
    report = janitor.run(_args(root, apply=True), now=time.time(), refs_source=_no_refs)
    assert tree.exists() and report["deleted"] == []
    report = janitor.run(_args(root), now=_later(4), refs_source=_no_refs)
    assert _paths(report["deleted"]) == ["fresh-copy"]


@pytest.mark.parametrize("layout", ["nested", "bare", "linked-deep"])
def test_repository_anywhere_inside_goes_to_the_owner(root, layout):
    tree = _tree(root, "scratch")
    inner = tree / "sub" / "deeper"
    inner.mkdir()
    if layout == "nested":
        (inner / ".git").mkdir()
    elif layout == "bare":
        for name in ("objects", "refs"):
            (inner / name).mkdir()
        (inner / "HEAD").write_text("ref: refs/heads/main\n")
    else:
        (inner / ".git").write_text("gitdir: /elsewhere/.git/worktrees/deeper\n")
    report = janitor.run(_args(root, apply=True), now=_later(), refs_source=_no_refs)
    assert tree.exists() and _paths(report["owner"]) == ["scratch"]
    assert str(inner) in report["owner"][0]["reason"]


def test_pytest_fixture_repositories_do_not_block_cleanup(root):
    tree = _tree(root, "orchestra-v9999")
    fixture = tree / "full" / "pytest-base" / "popen-gw0" / "test_merge0" / "repo"
    fixture.mkdir(parents=True)
    (fixture / ".git").mkdir()
    report = janitor.run(_args(root, apply=True), now=_later(), refs_source=_no_refs)
    assert _paths(report["deleted"]) == ["orchestra-v9999"] and not tree.exists()


def test_symlinked_root_is_refused(root, tmp_path):
    link = tmp_path / "linkroot"
    link.symlink_to(root)
    held = _tree(root, "held")
    with pytest.raises(ValueError):
        janitor.run(_args(link, apply=True), now=_later(), refs_source=_no_refs)
    assert held.exists()
    with pytest.raises(SystemExit):
        janitor.main(["--root", str(link)])


def test_relative_argument_from_a_parent_cwd_is_a_holder(root):
    tree = _tree(root, "served")
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", "served/sub/data.bin"], cwd=root,
    )
    cmdline = Path(f"/proc/{proc.pid}/cmdline")
    deadline = time.monotonic() + 5
    while b"served" not in cmdline.read_bytes() and time.monotonic() < deadline:
        time.sleep(0.01)  # until exec replaced the forked parent's argv
    try:
        report = janitor.run(_args(root, apply=True), now=_later())
    finally:
        proc.kill()
        proc.wait()
    assert tree.exists()
    assert str(proc.pid) in report["kept"][0]["reason"]


def test_dead_socket_is_a_file_only_with_the_owner_switch(root):
    tree = _tree(root, "pytest-scratch")
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(tree / "notify-ready.sock"))
    server.close()  # nobody listens any more, the file stays
    args = _args(root, apply=True)
    report = janitor.run(args, now=_later(), refs_source=_no_refs)
    assert tree.exists() and "сокет" in report["owner"][0]["reason"]
    args.dead_sockets = True
    report = janitor.run(args, now=_later(), refs_source=_no_refs)
    assert _paths(report["deleted"]) == ["pytest-scratch"] and not tree.exists()


def test_live_socket_keeps_the_tree_even_with_the_owner_switch(root):
    tree = _tree(root, "service")
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(tree / "live.sock"))
    server.listen()
    try:
        args = _args(root, apply=True)
        args.dead_sockets = True
        report = janitor.run(args, now=_later(), refs_source=_no_refs)
    finally:
        server.close()
    assert tree.exists() and report["deleted"] == []


def test_fifo_keeps_the_tree(root):
    tree = _tree(root, "pipe")
    os.mkfifo(tree / "fifo")
    args = _args(root, apply=True)
    args.dead_sockets = True
    report = janitor.run(args, now=_later(), refs_source=_no_refs)
    assert tree.exists() and "канал" in report["owner"][0]["reason"]


def test_future_timestamp_goes_to_the_owner(root):
    tree = _tree(root, "future")
    ahead = time.time() + 400 * DAY
    os.utime(tree / "sub" / "data.bin", (ahead, ahead))
    report = janitor.run(_args(root, apply=True), now=time.time(), refs_source=_no_refs)
    assert tree.exists() and "будущем" in report["owner"][0]["reason"]


def test_mount_point_inside_keeps_the_tree(root):
    tree = _tree(root, "mounted-inside")
    host = janitor.Host(bound_sockets=set(), mount_points={str(tree / "sub")})
    report = janitor.run(_args(root, apply=True), now=_later(), refs_source=_no_refs, host=host)
    assert tree.exists() and "монтирования" in report["owner"][0]["reason"]


def test_leftover_trash_of_an_interrupted_run_is_finished(root):
    leftover = root / f"{janitor.TRASH_PREFIX}123-old"
    leftover.mkdir()
    (leftover / "f").write_text("x")
    janitor.run(_args(root, apply=True), now=_later(), refs_source=_no_refs)
    assert not leftover.exists()
    dry = root / f"{janitor.TRASH_PREFIX}124-old"
    dry.mkdir()
    janitor.run(_args(root), now=_later(), refs_source=_no_refs)
    assert dry.exists()  # a dry run deletes nothing at all


def test_holder_seen_only_after_rename_restores_the_tree(root):
    tree = _tree(root, "late")
    trash = root / f"{janitor.TRASH_PREFIX}{os.getpid()}-late"
    calls = iter([[], [], [(9, str(trash))]])
    report = janitor.run(_args(root, apply=True), now=_later(), refs_source=lambda: next(calls))
    assert tree.exists() and not trash.exists()
    assert "переименования" in report["kept"][0]["reason"]


def test_owner_items_are_announced_once_a_week(tmp_path):
    state = str(tmp_path / "janitor-state.json")
    report = {"deleted": [], "kept": [], "errors": [],
              "owner": [{"path": "/tmp/a", "bytes": 1, "newest": 0, "reason": "git"}]}
    assert janitor.remember_owner(report, state, now=1000) == 1
    assert janitor.render(report, True, 100, 1)[0].startswith("TMP_JANITOR: ")
    assert janitor.remember_owner(report, state, now=1000 + DAY) == 0
    assert janitor.render(report, True, 100, 0)[0].startswith("tmp-janitor: ")
    assert janitor.remember_owner(report, state, now=1000 + 8 * DAY) == 1
    report["owner"] = []
    assert janitor.remember_owner(report, state, now=1000 + 9 * DAY) == 0
    report["owner"] = [{"path": "/tmp/a", "bytes": 1, "newest": 0, "reason": "git"}]
    assert janitor.remember_owner(report, state, now=1000 + 9 * DAY) == 1  # forgotten once gone
    assert janitor.remember_owner(report, None, now=0) is None
