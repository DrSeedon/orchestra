"""Systemd readiness, socket activation and deployment unit contracts."""
import grp
import os
import pwd
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from app import fdstore


def test_t1_acquire_maps_fds_by_name_not_position(monkeypatch):
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "2")
    monkeypatch.setenv("LISTEN_FDNAMES", "agent-1-stdout:agent-1-stdin")

    assert fdstore.acquire_fds() == {
        "agent-1-stdout": fdstore.SD_LISTEN_FDS_START,
        "agent-1-stdin": fdstore.SD_LISTEN_FDS_START + 1,
    }


def test_t1_acquire_without_inheritance_is_empty(monkeypatch):
    monkeypatch.delenv("LISTEN_FDS", raising=False)
    monkeypatch.delenv("LISTEN_FDNAMES", raising=False)

    assert fdstore.acquire_fds() == {}


def test_t1_name_count_mismatch_fails_loudly(monkeypatch):
    """Silent truncation would attach a live agent to the wrong descriptor."""
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "3")
    monkeypatch.setenv("LISTEN_FDNAMES", "only-one-name")

    with pytest.raises(ValueError):
        fdstore.acquire_fds()


def test_t1_foreign_listen_pid_is_ignored(monkeypatch):
    """LISTEN_* inherited from a PARENT names that parent's descriptors, not ours."""
    monkeypatch.setenv("LISTEN_PID", str(os.getpid() + 1))
    monkeypatch.setenv("LISTEN_FDS", "2")
    monkeypatch.setenv("LISTEN_FDNAMES", "agent-1-stdin:agent-1-stdout")

    assert fdstore.acquire_fds() == {}


def test_t1_duplicate_and_empty_fdnames_fail_loudly(monkeypatch):
    """Added after impl review: a duplicate name silently kept one descriptor and leaked the
    rest until the store was exhausted; an empty slot is a positional protocol error."""
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "2")
    monkeypatch.setenv("LISTEN_FDNAMES", "agent-1-stdin:agent-1-stdin")
    with pytest.raises(ValueError, match="duplicate"):
        fdstore.acquire_fds()

    monkeypatch.setenv("LISTEN_FDNAMES", "agent-1-stdin:")
    with pytest.raises(ValueError, match="slot 1"):
        fdstore.acquire_fds()






def test_ready_notification_is_sent_only_by_the_systemd_main_process(tmp_path, monkeypatch):
    sock_path = tmp_path / "notify-ready.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(str(sock_path))
    server.settimeout(2)
    monkeypatch.setenv("NOTIFY_SOCKET", str(sock_path))
    monkeypatch.setenv("SYSTEMD_EXEC_PID", str(os.getpid()))
    try:
        assert fdstore.notify_ready() is True
        assert server.recv(1024) == b"READY=1"
    finally:
        server.close()


def test_ready_notification_ignores_inherited_systemd_environment(monkeypatch):
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    monkeypatch.setenv("SYSTEMD_EXEC_PID", str(os.getpid() + 1))

    assert fdstore.notify_ready() is False


def test_t8_unit_templates_are_valid_and_complete(tmp_path):
    """Delivery check for T8: the unit files live in the repo, so they can be verified.

    Replaces the `oracle: none` the plan first claimed — review named this check, correctly.
    """
    root = Path(__file__).resolve().parents[1]
    service = root / "deploy" / "orchestra.service"
    sock = root / "deploy" / "orchestra.socket"
    readiness = root / "deploy" / "orchestra-readiness.conf"
    memory = root / "deploy" / "orchestra-memory.conf"
    assert service.is_file(), "deploy/orchestra.service must be versioned to be reviewable"
    assert sock.is_file(), "deploy/orchestra.socket must be versioned to be reviewable"
    readiness_text = readiness.read_text()
    assert "Type=notify" in readiness_text
    assert "TimeoutStartSec=300" in readiness_text
    assert "\nStateDirectory=" not in readiness.read_text()

    service_text = service.read_text()
    assert "Type=notify" in service_text, "systemd must wait for application startup"
    assert "NotifyAccess=main" in service_text, "READY/FDSTORE need NOTIFY_SOCKET"
    assert "KillMode=control-group" in service_text, "children must survive the restart"
    assert "FileDescriptorStoreMax=" in service_text, "no store, no handover"
    assert "--fd 3" in service_text, "the listening socket must be inherited"
    assert "Accept=no" in sock.read_text()

    # The tracked unit intentionally names the VPS user/path. Verify the exact syntax with
    # only those host-specific values adapted to this machine; a missing remote interpreter
    # is not a unit syntax failure.
    local_service = tmp_path / "orchestra.service"
    local_service.write_text(
        (service_text
        .replace("User=kesha", f"User={pwd.getpwuid(os.getuid()).pw_name}")
        .replace("Group=kesha", f"Group={grp.getgrgid(os.getgid()).gr_name}")
        .replace("WorkingDirectory=/home/kesha/orchestra", f"WorkingDirectory={root}")
        .replace("EnvironmentFile=/home/kesha/orchestra/.env", "EnvironmentFile=-/dev/null")
        .replace(
            "ExecStart=/home/kesha/orchestra/.venv/bin/python",
            f"ExecStart={sys.executable}",
        ))
        + "\n"
        + memory.read_text()
    )
    proc = subprocess.run(
        ["systemd-analyze", "verify", str(local_service), str(sock)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"systemd-analyze verify failed: {proc.stderr[:400]}"


def test_memory_dropin_bounds_native_arenas_and_cgroup_memory():
    root = Path(__file__).resolve().parents[1]
    text = (root / "deploy" / "orchestra-memory.conf").read_text()

    assert "Environment=MALLOC_ARENA_MAX=2" in text
    assert "Environment=MALLOC_TRIM_THRESHOLD_=131072" in text
    assert "MemoryHigh=8G" in text
    assert "MemoryMax=12G" in text
    assert "MemorySwapMax=4G" in text
    assert "OOMScoreAdjust=800" in text
