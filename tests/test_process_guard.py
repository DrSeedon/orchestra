import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.orchestra_process_guard import (
    CgroupFreezer,
    ConfigError,
    Decision,
    FreezeTimeout,
    Policy,
    ProcessGuard,
    ProcessGuardUnavailable,
    ProcessIdentityMismatch,
    ProcessReader,
    ProcessSnapshot,
    _validate_guard_context,
    decide,
    load_policy,
    main,
    matches_identity,
    open_verified_pidfd,
)


ROOT = Path(__file__).parents[1]


def policy(tmp_path: Path, **changes) -> Policy:
    base = Policy(
        enabled=False,
        dry_run=True,
        target_cgroup="/system.slice/orchestra.service",
        target_exe=str(Path("/bin/sleep").resolve()),
        target_argv0=b"ugrep",
        max_age_sec=181,
        max_rss_kib=528_578,
        poll_sec=10,
        rss_action="log",
        freeze_timeout_sec=2,
        freeze_marker=tmp_path / "freeze-owned",
    )
    return replace(base, **changes)


def snapshot(**changes) -> ProcessSnapshot:
    base = ProcessSnapshot(
        pid=1234,
        ppid=1200,
        start_ticks=10_000,
        cgroup="/system.slice/orchestra.service",
        exe=str(Path("/bin/sleep").resolve()),
        argv0=b"ugrep",
        comm="sleep",
        age_sec=200,
        rss_kib=10_000,
        hwm_kib=12_000,
    )
    return replace(base, **changes)


def config_env(tmp_path: Path) -> dict[str, str]:
    return {
        "ENABLED": "false",
        "DRY_RUN": "true",
        "TARGET_CGROUP": "/system.slice/orchestra.service",
        "TARGET_EXE": "/bin/sleep",
        "TARGET_ARGV0": "ugrep",
        "MAX_AGE_SEC": "181",
        "MAX_RSS_KIB": "528578",
        "POLL_SEC": "10",
        "RSS_ACTION": "log",
        "FREEZE_TIMEOUT_SEC": "2",
        "FREEZE_MARKER": str(tmp_path / "freeze-owned"),
    }


def test_pidfd_capability_is_import_safe_when_missing():
    script = """
import os

if hasattr(os, "pidfd_open"):
    del os.pidfd_open
from scripts import orchestra_process_guard

assert callable(orchestra_process_guard.open_verified_pidfd)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_pidfd_capability_missing_at_call_fails_explicitly(monkeypatch):
    monkeypatch.delattr(os, "pidfd_open", raising=False)

    with pytest.raises(ProcessGuardUnavailable, match=r"os\.pidfd_open"):
        open_verified_pidfd(12345, 67890)


def test_injected_pidfd_open_validates_starttime_and_closes_mismatch_fd():
    order: list[str] = []
    read_fd, write_fd = os.pipe()
    try:
        def pidfd_open(pid: int) -> int:
            assert pid == 12345
            order.append("pidfd_open")
            return read_fd

        def read_start(pid: int) -> int:
            assert pid == 12345
            order.append("read_starttime")
            return 67890

        assert open_verified_pidfd(
            12345,
            67890,
            pidfd_open=pidfd_open,
            read_starttime=read_start,
        ) == read_fd
        assert order == ["pidfd_open", "read_starttime"]
    finally:
        os.close(write_fd)
        os.close(read_fd)

    mismatch_fd = os.open(os.devnull, os.O_RDONLY)
    try:
        with pytest.raises(ProcessIdentityMismatch, match="starttime"):
            open_verified_pidfd(
                12345,
                11111,
                pidfd_open=lambda _pid: mismatch_fd,
                read_starttime=lambda _pid: 67890,
            )
    finally:
        with pytest.raises(OSError):
            os.close(mismatch_fd)


@pytest.mark.parametrize("missing", [
    "ENABLED", "DRY_RUN", "TARGET_CGROUP", "TARGET_EXE", "TARGET_ARGV0",
    "MAX_AGE_SEC", "MAX_RSS_KIB", "POLL_SEC", "RSS_ACTION",
    "FREEZE_TIMEOUT_SEC", "FREEZE_MARKER",
])
def test_policy_rejects_missing_required_setting(tmp_path, missing):
    env = config_env(tmp_path)
    env.pop(missing)
    with pytest.raises(ConfigError, match=missing):
        load_policy(env)


@pytest.mark.parametrize(("key", "value"), [
    ("ENABLED", "yes"),
    ("DRY_RUN", "0"),
    ("MAX_AGE_SEC", "0"),
    ("MAX_RSS_KIB", "1.5"),
    ("POLL_SEC", "-1"),
    ("FREEZE_TIMEOUT_SEC", "later"),
    ("RSS_ACTION", "stop"),
    ("TARGET_CGROUP", "/"),
])
def test_policy_rejects_invalid_setting(tmp_path, key, value):
    env = config_env(tmp_path)
    env[key] = value
    with pytest.raises(ConfigError):
        load_policy(env)


def test_invalid_config_exits_nonzero_and_logs_fatal(caplog):
    assert main(["--check-config"], {"ENABLED": "false"}) == 2
    assert '"action": "fatal"' in caplog.text


def test_shipped_config_is_inert_and_parseable(tmp_path):
    env = {}
    for line in (ROOT / "deploy/orchestra-process-guard.conf").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key] = value
    env["TARGET_EXE"] = "/bin/sleep"
    env["FREEZE_MARKER"] = str(tmp_path / "freeze-owned")

    parsed = load_policy(env)

    assert parsed.enabled is False
    assert parsed.dry_run is True
    assert parsed.armed is False
    assert parsed.rss_action == "log"


def test_exec_a_applet_is_distinct_from_real_same_named_executable(tmp_path):
    real_ugrep = tmp_path / "ugrep"
    shutil.copy2("/bin/sleep", real_ugrep)
    real_ugrep.chmod(0o755)
    reader = ProcessReader()
    processes = [
        subprocess.Popen(["ugrep", "30"], executable="/bin/sleep"),
        subprocess.Popen(["ugrep", "30"], executable=real_ugrep),
    ]
    try:
        embedded = reader.read(processes[0].pid)
        real = reader.read(processes[1].pid)
        target = policy(
            tmp_path,
            target_cgroup=embedded.cgroup,
            target_exe=str(Path("/bin/sleep").resolve()),
        )

        assert embedded.argv0 == real.argv0 == b"ugrep"
        assert embedded.comm == "sleep"
        assert real.comm == "ugrep"
        assert matches_identity(embedded, target) is True
        assert matches_identity(real, target) is False
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=5)


@pytest.mark.parametrize("innocent", [
    snapshot(cgroup="/system.slice/other.service"),
    snapshot(exe=str(Path("/bin/true").resolve())),
    snapshot(argv0=b"/usr/bin/claude"),
])
def test_each_identity_clause_rejects_an_otherwise_exact_innocent(tmp_path, innocent):
    # Each fixture differs in exactly one field, so the other two checks cannot mask a mutation.
    assert matches_identity(innocent, policy(tmp_path)) is False


def test_only_embedded_ugrep_identity_matches(tmp_path):
    target = policy(tmp_path)
    embedded_ugrep = snapshot()
    ordinary_claude = snapshot(argv0=b"/usr/bin/claude")
    uvicorn = snapshot(exe=str(Path("/usr/bin/python3").resolve()), argv0=b"uvicorn")
    outside_cgroup = snapshot(cgroup="/system.slice/other.service")

    assert matches_identity(embedded_ugrep, target) is True
    assert matches_identity(ordinary_claude, target) is False
    assert matches_identity(uvicorn, target) is False
    assert matches_identity(outside_cgroup, target) is False


def test_comm_is_not_an_identity_field(tmp_path):
    assert matches_identity(snapshot(comm="ugrep"), policy(tmp_path)) is True
    assert matches_identity(
        snapshot(comm="ugrep", argv0=b"/usr/bin/claude"), policy(tmp_path),
    ) is False


def test_thresholds_are_or_but_rss_log_is_not_actionable(tmp_path):
    age = decide(snapshot(age_sec=181, rss_kib=1), policy(tmp_path))
    rss_log = decide(snapshot(age_sec=1, rss_kib=528_578), policy(tmp_path))
    rss_kill = decide(
        snapshot(age_sec=1, rss_kib=528_578), policy(tmp_path, rss_action="kill"),
    )

    assert age and age.reasons == ("age",) and age.actionable
    assert rss_log and rss_log.reasons == ("rss",) and not rss_log.actionable
    assert rss_kill and rss_kill.reasons == ("rss",) and rss_kill.actionable
    assert decide(snapshot(age_sec=1, rss_kib=1), policy(tmp_path)) is None


class ModelFreezer(CgroupFreezer):
    def __init__(
        self, tmp_path, *, freeze_completes=True, freeze_parent_during_move=False,
    ):
        parent = tmp_path / "cgroup"
        runtime = tmp_path / "runtime"
        parent.mkdir()
        runtime.mkdir()
        (parent / "cgroup.controllers").write_text("memory cpu\n")
        (parent / "cgroup.procs").write_text("")
        super().__init__(
            parent,
            "/system.slice/orchestra.service",
            runtime / "freeze-owned",
            0.02,
        )
        self.state = False
        self.parent_frozen = False
        self.freeze_completes = freeze_completes
        self.freeze_parent_during_move = freeze_parent_during_move
        self.writes = []
        self.members = {parent: set()}

    def _frozen(self, cgroup_dir):
        if cgroup_dir == self.cgroup_dir:
            return self.parent_frozen
        return self.parent_frozen or self.state

    def _write_state(self, cgroup_dir, frozen):
        self.writes.append(frozen)
        if cgroup_dir == self.cgroup_dir:
            self.parent_frozen = frozen
            return
        if not frozen or self.freeze_completes:
            self.state = frozen

    def _confirm_requested_state(self, _cgroup_dir, _frozen):
        pass

    def _read_pids(self, cgroup_dir):
        return sorted(self.members.setdefault(cgroup_dir, set()))

    def _move_pid(self, pid, destination):
        for members in self.members.values():
            members.discard(pid)
        self.members.setdefault(destination, set()).add(pid)
        if destination != self.cgroup_dir and self.freeze_parent_during_move:
            self.parent_frozen = True


class FixedReader:
    def __init__(self, current, freezer=None):
        self.current = current
        self.freezer = freezer

    def read(self, _pid):
        if isinstance(self.current, BaseException):
            raise self.current
        if self.freezer is not None and self.freezer.state:
            return replace(self.current, cgroup=self.freezer.active_cgroup)
        return self.current

    def snapshots(self):
        return iter(())


class ScanReader:
    def __init__(self, snapshots):
        self.current = list(snapshots)

    def read(self, pid):
        for current in self.current:
            if current.pid == pid:
                return current
        raise ProcessLookupError(pid)

    def snapshots(self):
        return iter(self.current)


@pytest.mark.parametrize(("enabled", "dry_run", "expected"), [
    (False, False, "disabled"),
    (False, True, "disabled"),
    (True, True, "dry_run"),
])
def test_kill_path_requires_explicit_enable_and_dry_run_off(
    tmp_path, enabled, dry_run, expected,
):
    candidate = snapshot()
    freezer = ModelFreezer(tmp_path)

    def forbidden_pidfd_open(_pid):
        raise AssertionError("pidfd/freeze path must not be reachable")

    guard = ProcessGuard(
        policy(tmp_path, enabled=enabled, dry_run=dry_run),
        FixedReader(candidate),
        freezer,
        pidfd_open=forbidden_pidfd_open,
    )

    assert guard.handle(Decision(candidate, ("age",), True)) == expected
    assert freezer.writes == []


def test_observe_scan_logs_exact_samples_and_nonmatch_counters(tmp_path, caplog):
    exact = snapshot(age_sec=100)
    ordinary_claude = replace(exact, pid=1235, argv0=b"/usr/bin/claude")
    uvicorn = replace(
        exact,
        pid=1236,
        exe=str(Path("/usr/bin/python3").resolve()),
        argv0=b"uvicorn",
    )
    outside = replace(exact, pid=1237, cgroup="/system.slice/other.service")
    reader = ScanReader([exact, ordinary_claude, uvicorn, outside])
    guard = ProcessGuard(policy(tmp_path), reader, ModelFreezer(tmp_path))

    assert guard.run_once() == []

    events = [json.loads(record.message) for record in caplog.records]
    sample = next(event for event in events if event["action"] == "calibration_sample")
    summary = next(event for event in events if event["action"] == "scan_complete")
    assert (sample["pid"], sample["start_ticks"], sample["age_sec"]) == (1234, 10_000, 100)
    assert (sample["rss_kib"], sample["hwm_kib"]) == (10_000, 12_000)
    assert summary["scanned"] == 4
    assert summary["target_cgroup"] == 3
    assert summary["exact_matches"] == 1
    assert summary["exe_mismatches"] == 1
    assert summary["argv0_mismatches"] == 1
    assert summary["duration_ms"] >= 0
    assert summary["guard_maxrss_kib"] > 0


def test_observe_scan_records_completed_exact_lifetime(tmp_path, caplog):
    exact = snapshot(age_sec=100)
    reader = ScanReader([exact])
    guard = ProcessGuard(policy(tmp_path), reader, ModelFreezer(tmp_path))
    guard.run_once()
    reader.current = []

    guard.run_once()

    events = [json.loads(record.message) for record in caplog.records]
    completed = next(event for event in events if event["action"] == "calibration_complete")
    assert completed["completion"] == "exited"
    assert completed["lifetime_lower_sec"] == 100
    assert completed["lifetime_upper_sec"] >= completed["lifetime_lower_sec"]


def test_error_after_freeze_always_thaws(tmp_path, caplog):
    candidate = snapshot()
    freezer = ModelFreezer(tmp_path)
    fd = os.open("/dev/null", os.O_RDONLY)

    def signal_fails(_pidfd, _signal):
        raise RuntimeError("injected signal failure")

    guard = ProcessGuard(
        policy(tmp_path, enabled=True, dry_run=False),
        FixedReader(candidate, freezer),
        freezer,
        pidfd_open=lambda _pid: fd,
        pidfd_signal=signal_fails,
    )

    with pytest.raises(RuntimeError, match="injected signal failure"):
        guard.handle(Decision(candidate, ("age",), True))
    assert freezer.writes == [True, False]
    assert freezer.state is False
    assert freezer.marker.exists() is False
    event = json.loads(caplog.records[-1].message)
    assert event["action"] == "signal_failed"
    assert event["signal"] == "SIGKILL"


def test_pid_reuse_outside_target_is_not_moved_or_signalled(tmp_path):
    candidate = snapshot()
    reused = replace(
        candidate,
        start_ticks=candidate.start_ticks + 1,
        cgroup="/system.slice/innocent.service",
        exe=str(Path("/usr/bin/python3").resolve()),
        argv0=b"uvicorn",
    )
    freezer = ModelFreezer(tmp_path)
    fd = os.open("/dev/null", os.O_RDONLY)
    signals = []
    guard = ProcessGuard(
        policy(tmp_path, enabled=True, dry_run=False),
        FixedReader(reused),
        freezer,
        pidfd_open=lambda _pid: fd,
        pidfd_signal=lambda *args: signals.append(args),
    )

    result = guard.handle(Decision(candidate, ("age",), True))

    assert result == "identity_changed_before_freeze"
    assert signals == []
    assert freezer.writes == []
    assert freezer.marker.exists() is False


def test_identity_change_under_freeze_gets_no_signal_and_thaws(tmp_path):
    candidate = snapshot()
    freezer = ModelFreezer(tmp_path)
    fd = os.open("/dev/null", os.O_RDONLY)
    signals = []

    class ChangingReader(FixedReader):
        def read(self, _pid):
            if freezer.state:
                return replace(
                    candidate,
                    cgroup=freezer.active_cgroup,
                    argv0=b"/usr/bin/claude",
                )
            return candidate

    guard = ProcessGuard(
        policy(tmp_path, enabled=True, dry_run=False),
        ChangingReader(candidate),
        freezer,
        pidfd_open=lambda _pid: fd,
        pidfd_signal=lambda *args: signals.append(args),
    )

    result = guard.handle(Decision(candidate, ("age",), True))

    assert result == "identity_changed_after_freeze"
    assert signals == []
    assert freezer.writes == [True, False]
    assert freezer.state is False


def test_external_cont_cannot_change_modelled_image_while_frozen(tmp_path):
    candidate = snapshot()
    freezer = ModelFreezer(tmp_path)
    fd = os.open("/dev/null", os.O_RDONLY)
    state = {"image": candidate, "attempted_exec": False, "killed": False}

    class RacingReader(FixedReader):
        def read(self, _pid):
            if not freezer.state:
                return state["image"]
            state["attempted_exec"] = True  # Models same-PID exec + external SIGCONT.
            return replace(state["image"], cgroup=freezer.active_cgroup)

    def kill(_pidfd, sent_signal):
        assert freezer.state is True
        assert sent_signal == 9
        state["killed"] = True

    guard = ProcessGuard(
        policy(tmp_path, enabled=True, dry_run=False),
        RacingReader(candidate),
        freezer,
        pidfd_open=lambda _pid: fd,
        pidfd_signal=kill,
    )

    assert guard.handle(Decision(candidate, ("age",), True)) == "killed"
    assert state == {"image": candidate, "attempted_exec": True, "killed": True}
    assert freezer.state is False


def test_freeze_timeout_is_fail_closed_and_thaws(tmp_path):
    candidate = snapshot()
    freezer = ModelFreezer(tmp_path, freeze_completes=False)
    fd = os.open("/dev/null", os.O_RDONLY)
    guard = ProcessGuard(
        policy(tmp_path, enabled=True, dry_run=False, freeze_timeout_sec=0.02),
        FixedReader(candidate, freezer),
        freezer,
        pidfd_open=lambda _pid: fd,
        pidfd_signal=lambda *_args: pytest.fail("freeze timeout must not signal"),
    )

    assert guard.handle(Decision(candidate, ("age",), True)) == "freeze_timeout"
    assert freezer.writes == [True, False]
    assert freezer.state is False
    assert freezer.marker.exists() is False


def test_recovery_never_thaws_external_parent_freeze(tmp_path):
    freezer = ModelFreezer(tmp_path, freeze_parent_during_move=True)
    candidate = snapshot()

    freezer.parent_frozen = True
    assert freezer.thaw_owned() is False
    assert freezer.parent_frozen is True
    assert freezer.writes == []

    freezer.parent_frozen = False
    freezer.freeze(candidate)
    assert freezer.parent_frozen is True
    assert freezer.thaw_owned() is True
    assert freezer.state is False
    assert freezer.parent_frozen is True
    assert freezer.writes == [True, False]
    assert freezer.marker.exists() is False


def test_guard_refuses_target_cgroup_that_contains_it(tmp_path):
    class NoopFreezer:
        def validate(self):
            pass

    own = snapshot(pid=os.getpid(), cgroup="/system.slice/guard.service/child")
    with pytest.raises(ConfigError, match="freeze itself"):
        _validate_guard_context(
            policy(tmp_path, target_cgroup="/system.slice/guard.service"),
            FixedReader(own),
            NoopFreezer(),
        )


def test_log_is_allowlisted_not_full_cmdline_or_environment(tmp_path, caplog):
    candidate = snapshot(comm="ugrep")
    guard = ProcessGuard(
        policy(tmp_path, enabled=False, dry_run=False),
        FixedReader(candidate),
        ModelFreezer(tmp_path),
    )

    guard.handle(Decision(candidate, ("age",), True))
    event = json.loads(caplog.records[-1].message)

    assert event["argv0"] == "ugrep"
    assert event["action"] == "disabled"
    assert event["max_age_sec"] == 181
    assert event["max_rss_kib"] == 528_578
    assert "cmdline" not in event
    assert "environment" not in event


def test_unit_is_independent_and_has_crash_thaw_hook():
    unit = (ROOT / "deploy/orchestra-process-guard.service").read_text()
    assert "Requires=orchestra.service" not in unit
    assert "After=orchestra.service" not in unit
    assert "ExecStopPost=/usr/local/libexec/orchestra-process-guard --thaw" in unit
    assert "EnvironmentFile=/etc/orchestra-process-guard.conf" in unit
    assert "Restart=on-failure" in unit


def _fake_command(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
    path.chmod(0o755)
    return path


def test_manager_installs_disables_and_fully_rolls_back(tmp_path):
    destination = tmp_path / "root"
    existing_config = destination / "etc/orchestra-process-guard.conf"
    existing_config.parent.mkdir(parents=True)
    existing_config.write_text("PREVIOUS=true\n")
    existing_config.chmod(0o640)
    command_log = tmp_path / "commands.log"
    fake_systemctl = _fake_command(
        tmp_path / "systemctl",
        'printf "systemctl %s\\n" "$*" >> "$COMMAND_LOG"\n'
        'case "${1:-}" in is-enabled|is-active) exit 1;; esac\n',
    )
    fake_analyze = _fake_command(
        tmp_path / "systemd-analyze",
        'printf "systemd-analyze %s\\n" "$*" >> "$COMMAND_LOG"\n',
    )
    env = {
        **os.environ,
        "DESTDIR": str(destination),
        "SYSTEMCTL": str(fake_systemctl),
        "SYSTEMD_ANALYZE": str(fake_analyze),
        "COMMAND_LOG": str(command_log),
    }
    manager = ROOT / "deploy/manage-process-guard.sh"

    subprocess.run(["bash", "-n", manager], check=True)
    subprocess.run([manager, "stage"], check=True, env=env)

    installed_script = destination / "usr/local/libexec/orchestra-process-guard"
    installed_unit = destination / "etc/systemd/system/orchestra-process-guard.service"
    assert installed_script.read_bytes() == (ROOT / "scripts/orchestra_process_guard.py").read_bytes()
    assert installed_unit.read_bytes() == (ROOT / "deploy/orchestra-process-guard.service").read_bytes()
    assert existing_config.read_bytes() == (ROOT / "deploy/orchestra-process-guard.conf").read_bytes()
    staged_log = command_log.read_text()
    assert "systemd-analyze" in staged_log
    assert "systemctl daemon-reload" in staged_log
    assert "enable --now" not in staged_log

    subprocess.run([manager, "activate"], check=True, env=env)

    existing_config.write_text("manual post-activation change\n")
    refused = subprocess.run(
        [manager, "rollback"], env=env, text=True, capture_output=True,
    )
    assert refused.returncode == 1
    assert "changed since install" in refused.stderr
    assert existing_config.read_text() == "manual post-activation change\n"
    assert installed_script.exists()
    assert installed_unit.exists()
    existing_config.write_bytes((ROOT / "deploy/orchestra-process-guard.conf").read_bytes())

    subprocess.run([manager, "disable"], check=True, env=env)
    subprocess.run([manager, "rollback"], check=True, env=env)

    assert existing_config.read_text() == "PREVIOUS=true\n"
    assert existing_config.stat().st_mode & 0o777 == 0o640
    assert installed_script.exists() is False
    assert installed_unit.exists() is False
    assert not (destination / "var/lib/orchestra-process-guard/deploy-state").exists()
    assert list((destination / "var/lib/orchestra-process-guard").glob("rollback-*"))
    log = command_log.read_text()
    assert "systemctl enable --now orchestra-process-guard.service" in log
    assert "systemctl disable --now orchestra-process-guard.service" in log
    assert "systemctl daemon-reload" in log
