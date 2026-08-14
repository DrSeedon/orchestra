"""#271: empty inventory must not look like 'no processes' when the check is blind."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "cli-inventory.py"


def _spawn_canary() -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", "app-server", "--stdio"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            argv = Path(f"/proc/{proc.pid}/cmdline").read_bytes().split(b"\0")
            if argv and argv[-1] == b"":
                argv = argv[:-1]
        except OSError:
            time.sleep(0.05)
            continue
        if len(argv) >= 2 and tuple(argv[-2:]) == (b"app-server", b"--stdio"):
            return proc
        time.sleep(0.05)
    proc.kill()
    proc.wait(timeout=2)
    raise RuntimeError(f"canary pid={proc.pid} never appeared in /proc")


def _starttime(pid: int) -> str:
    stat = Path(f"/proc/{pid}/stat").read_text()
    return stat[stat.rindex(")") + 2 :].split()[19]


def _run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def test_check_empty_snapshot_while_live_cli_exists_is_blind(tmp_path):
    """Oracle: tool returned empty while a matching CLI is alive → must refuse.

    Today's check only walks the snapshot file. An empty file does zero
    iterations, prints '0 still alive' and exits 0 — the same answer as
    'there are no processes'. This is the blind case, not the empty world.
    """
    snap = tmp_path / "pre-A-inventory.txt"
    snap.write_text("")
    canary = _spawn_canary()
    try:
        result = _run("check", str(snap))
    finally:
        canary.kill()
        canary.wait(timeout=2)
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "0 still alive" not in result.stdout or result.returncode != 0
    assert "UNRESOLVED" not in out


def test_check_reports_unresolved_for_live_snapshot_entry(tmp_path):
    canary = _spawn_canary()
    try:
        snap = tmp_path / "pre-A-inventory.txt"
        snap.write_text(f"{canary.pid} {_starttime(canary.pid)} python3\n")
        result = _run("check", str(snap))
    finally:
        canary.kill()
        canary.wait(timeout=2)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"UNRESOLVED: pid={canary.pid}" in result.stdout


def test_check_dead_pid_is_resolved(tmp_path):
    snap = tmp_path / "pre-A-inventory.txt"
    snap.write_text("1 0 init\n")
    # pid 1's starttime is not 0, so identity does not match → treated as gone.
    result = _run("check", str(snap))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "UNRESOLVED" not in result.stdout
    assert "1 still alive" not in result.stdout


def test_snapshot_refuses_when_scanner_cannot_see_canary(monkeypatch, capsys):
    """Broken matcher: canary is live, live() sees nothing → snapshot must not exit 0."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("cli_inventory", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ARGV_TAIL", (b"no-such", b"tail"))
    monkeypatch.setattr(sys, "argv", ["cli-inventory.py", "snapshot"])
    rc = mod.main()
    err = capsys.readouterr().err
    assert rc == 2, err
    assert "BLIND" in err


def test_snapshot_does_not_list_the_inventory_script_itself():
    result = _run("snapshot")
    assert result.returncode in {0, 2}, result.stdout + result.stderr
    if result.returncode != 0:
        pytest.skip("snapshot refused (blind/probe); nothing to inspect")
    for line in result.stdout.splitlines():
        pid = int(line.split()[0])
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            continue
        assert b"cli-inventory.py" not in cmdline
