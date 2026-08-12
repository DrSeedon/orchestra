#!/usr/bin/env python3
"""Selective OS process guard for Claude Code's embedded ugrep applet."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import secrets
import signal
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping


class GuardError(RuntimeError):
    pass


class ConfigError(GuardError):
    pass


class FreezeError(GuardError):
    pass


class FreezeTimeout(FreezeError):
    pass


class ThawError(FreezeError):
    pass


@dataclass(frozen=True)
class Policy:
    enabled: bool
    dry_run: bool
    target_cgroup: str
    target_exe: str
    target_argv0: bytes
    max_age_sec: float
    max_rss_kib: int
    poll_sec: float
    rss_action: str
    freeze_timeout_sec: float
    freeze_marker: Path

    @property
    def armed(self) -> bool:
        return self.enabled and not self.dry_run


@dataclass(frozen=True)
class ProcessSnapshot:
    pid: int
    ppid: int
    start_ticks: int
    cgroup: str
    exe: str
    argv0: bytes
    comm: str
    age_sec: float
    rss_kib: int
    hwm_kib: int


@dataclass(frozen=True)
class Decision:
    snapshot: ProcessSnapshot
    reasons: tuple[str, ...]
    actionable: bool


@dataclass(frozen=True)
class FreezeRecord:
    child_name: str
    pid: int
    start_ticks: int


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"missing required setting: {key}")
    return value


def _boolean(env: Mapping[str, str], key: str) -> bool:
    value = _required(env, key).lower()
    if value not in {"true", "false"}:
        raise ConfigError(f"{key} must be true or false, got {value!r}")
    return value == "true"


def _positive_float(env: Mapping[str, str], key: str) -> float:
    raw = _required(env, key)
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigError(f"{key} must be numeric, got {raw!r}") from error
    if value <= 0:
        raise ConfigError(f"{key} must be positive, got {raw!r}")
    return value


def _positive_int(env: Mapping[str, str], key: str) -> int:
    raw = _required(env, key)
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from error
    if value <= 0:
        raise ConfigError(f"{key} must be positive, got {raw!r}")
    return value


def load_policy(env: Mapping[str, str]) -> Policy:
    target_cgroup = _required(env, "TARGET_CGROUP")
    if not target_cgroup.startswith("/") or target_cgroup == "/" or ".." in Path(target_cgroup).parts:
        raise ConfigError("TARGET_CGROUP must be an absolute non-root cgroup path without '..'")

    target_exe_path = Path(_required(env, "TARGET_EXE"))
    if not target_exe_path.is_absolute():
        raise ConfigError("TARGET_EXE must be absolute")
    try:
        target_exe = str(target_exe_path.resolve(strict=True))
    except OSError as error:
        raise ConfigError(f"TARGET_EXE cannot be resolved: {error}") from error

    argv0_text = _required(env, "TARGET_ARGV0")
    if "\0" in argv0_text:
        raise ConfigError("TARGET_ARGV0 must not contain NUL")

    rss_action = _required(env, "RSS_ACTION").lower()
    if rss_action not in {"log", "kill"}:
        raise ConfigError("RSS_ACTION must be 'log' or 'kill'")

    marker = Path(_required(env, "FREEZE_MARKER"))
    if not marker.is_absolute():
        raise ConfigError("FREEZE_MARKER must be absolute")

    return Policy(
        enabled=_boolean(env, "ENABLED"),
        dry_run=_boolean(env, "DRY_RUN"),
        target_cgroup=target_cgroup.rstrip("/"),
        target_exe=target_exe,
        target_argv0=argv0_text.encode(),
        max_age_sec=_positive_float(env, "MAX_AGE_SEC"),
        max_rss_kib=_positive_int(env, "MAX_RSS_KIB"),
        poll_sec=_positive_float(env, "POLL_SEC"),
        rss_action=rss_action,
        freeze_timeout_sec=_positive_float(env, "FREEZE_TIMEOUT_SEC"),
        freeze_marker=marker,
    )


class ProcessReader:
    def __init__(
        self,
        proc_root: Path = Path("/proc"),
        *,
        boottime: Callable[[], float] | None = None,
        clock_ticks: int | None = None,
    ) -> None:
        self.proc_root = proc_root
        self.boottime = boottime or (lambda: time.clock_gettime(time.CLOCK_BOOTTIME))
        self.clock_ticks = clock_ticks or int(os.sysconf("SC_CLK_TCK"))

    def read(self, pid: int) -> ProcessSnapshot:
        root = self.proc_root / str(pid)
        stat_text = (root / "stat").read_text()
        _head, separator, tail = stat_text.rpartition(")")
        fields = tail.strip().split()
        if not separator or len(fields) < 20:
            raise ProcessLookupError(f"invalid stat for PID {pid}")

        status = {}
        for line in (root / "status").read_text().splitlines():
            key, separator, value = line.partition(":")
            if separator:
                status[key] = value.strip()

        cgroup = ""
        for line in (root / "cgroup").read_text().splitlines():
            if line.startswith("0::"):
                cgroup = line[3:]
                break
        if not cgroup:
            raise ProcessLookupError(f"PID {pid} has no unified cgroup")

        cmdline = (root / "cmdline").read_bytes()
        argv0 = cmdline.split(b"\0", 1)[0]
        start_ticks = int(fields[19])
        rss_kib = _status_kib(status, "VmRSS")
        hwm_kib = _status_kib(status, "VmHWM", default=rss_kib)
        return ProcessSnapshot(
            pid=pid,
            ppid=int(fields[1]),
            start_ticks=start_ticks,
            cgroup=cgroup,
            exe=str((root / "exe").resolve(strict=True)),
            argv0=argv0,
            comm=(root / "comm").read_text().rstrip("\n"),
            age_sec=max(0.0, self.boottime() - start_ticks / self.clock_ticks),
            rss_kib=rss_kib,
            hwm_kib=hwm_kib,
        )

    def snapshots(self) -> Iterator[ProcessSnapshot]:
        for entry in self.proc_root.iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                yield self.read(int(entry.name))
            except (FileNotFoundError, PermissionError, ProcessLookupError, OSError, ValueError):
                continue


def _status_kib(status: Mapping[str, str], key: str, *, default: int = 0) -> int:
    raw = status.get(key)
    if raw is None:
        return default
    fields = raw.split()
    if not fields or not fields[0].isdigit():
        raise ProcessLookupError(f"invalid {key}: {raw!r}")
    return int(fields[0])


def matches_identity(snapshot: ProcessSnapshot, policy: Policy) -> bool:
    return (
        snapshot.cgroup == policy.target_cgroup
        and snapshot.exe == policy.target_exe
        and snapshot.argv0 == policy.target_argv0
    )


def same_process_image(
    before: ProcessSnapshot, after: ProcessSnapshot, frozen_cgroup: str,
) -> bool:
    return (
        before.pid == after.pid
        and before.start_ticks == after.start_ticks
        and after.cgroup == frozen_cgroup
        and before.exe == after.exe
        and before.argv0 == after.argv0
    )


def decide(snapshot: ProcessSnapshot, policy: Policy) -> Decision | None:
    if not matches_identity(snapshot, policy):
        return None
    reasons = []
    age_exceeded = snapshot.age_sec >= policy.max_age_sec
    rss_exceeded = snapshot.rss_kib >= policy.max_rss_kib
    if age_exceeded:
        reasons.append("age")
    if rss_exceeded:
        reasons.append("rss")
    if not reasons:
        return None
    return Decision(
        snapshot=snapshot,
        reasons=tuple(reasons),
        actionable=age_exceeded or (rss_exceeded and policy.rss_action == "kill"),
    )


class CgroupFreezer:
    def __init__(
        self,
        cgroup_dir: Path,
        target_cgroup: str,
        marker: Path,
        timeout_sec: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cgroup_dir = cgroup_dir
        self.target_cgroup = target_cgroup
        self.marker = marker
        self.timeout_sec = timeout_sec
        self.monotonic = monotonic
        self.sleep = sleep

    def validate(self) -> None:
        for name in ("cgroup.controllers", "cgroup.procs"):
            path = self.cgroup_dir / name
            if not path.exists():
                raise ConfigError(f"missing cgroup v2 interface: {path}")
        if not self.marker.parent.is_dir():
            raise ConfigError(f"freeze marker directory does not exist: {self.marker.parent}")

    def _frozen(self, cgroup_dir: Path) -> bool:
        values = {}
        for line in (cgroup_dir / "cgroup.events").read_text().splitlines():
            key, separator, value = line.partition(" ")
            if separator:
                values[key] = value
        if values.get("frozen") not in {"0", "1"}:
            raise FreezeError("cgroup.events has no valid frozen field")
        return values["frozen"] == "1"

    def _write_state(self, cgroup_dir: Path, frozen: bool) -> None:
        (cgroup_dir / "cgroup.freeze").write_text("1\n" if frozen else "0\n")

    def _confirm_requested_state(self, cgroup_dir: Path, frozen: bool) -> None:
        requested = (cgroup_dir / "cgroup.freeze").read_text().strip()
        if requested != ("1" if frozen else "0"):
            raise FreezeError(f"cgroup.freeze did not retain requested state {int(frozen)}")

    def _wait_for(self, cgroup_dir: Path, frozen: bool) -> None:
        deadline = self.monotonic() + self.timeout_sec
        while self._frozen(cgroup_dir) != frozen:
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                action = "freeze" if frozen else "thaw"
                error = FreezeTimeout if frozen else ThawError
                raise error(f"cgroup did not {action} within {self.timeout_sec:g}s")
            self.sleep(min(0.01, remaining))

    def _read_record(self) -> FreezeRecord:
        try:
            raw = json.loads(self.marker.read_text())
            record = FreezeRecord(
                child_name=raw["child_name"],
                pid=int(raw["pid"]),
                start_ticks=int(raw["start_ticks"]),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise FreezeError(f"invalid owned-freeze marker: {error}") from error
        if not isinstance(record.child_name, str) or not re.fullmatch(
            r"process-guard-[0-9]+-[0-9a-f]{32}", record.child_name,
        ):
            raise FreezeError("invalid child cgroup name in owned-freeze marker")
        if record.pid <= 0 or record.start_ticks <= 0:
            raise FreezeError("invalid process identity in owned-freeze marker")
        return record

    def _child_dir(self, record: FreezeRecord) -> Path:
        return self.cgroup_dir / record.child_name

    def _read_pids(self, cgroup_dir: Path) -> list[int]:
        return [int(line) for line in (cgroup_dir / "cgroup.procs").read_text().splitlines()]

    def _move_pid(self, pid: int, destination: Path) -> None:
        (destination / "cgroup.procs").write_text(f"{pid}\n")

    @property
    def active_cgroup(self) -> str:
        record = self._read_record()
        return f"{self.target_cgroup}/{record.child_name}"

    def assert_frozen(self) -> None:
        record = self._read_record()
        if not self._frozen(self._child_dir(record)):
            raise FreezeError("target cgroup thawed before signal")

    def freeze(self, candidate: ProcessSnapshot) -> None:
        if self.marker.exists():
            raise FreezeError("stale owned-freeze marker requires recovery")
        if candidate.cgroup != self.target_cgroup:
            raise FreezeError("candidate is outside TARGET_CGROUP before migration")
        child_name = f"process-guard-{os.getpid()}-{secrets.token_hex(16)}"
        record = FreezeRecord(child_name, candidate.pid, candidate.start_ticks)
        child_dir = self._child_dir(record)
        child_dir.mkdir(mode=0o700)
        try:
            marker_fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            child_dir.rmdir()
            raise FreezeError("owned-freeze marker appeared concurrently") from error
        except OSError:
            child_dir.rmdir()
            raise
        with os.fdopen(marker_fd, "w") as marker_file:
            json.dump(record.__dict__, marker_file, sort_keys=True)
            marker_file.write("\n")
            marker_file.flush()
            os.fsync(marker_file.fileno())
        self._move_pid(candidate.pid, child_dir)
        self._write_state(child_dir, True)
        self._confirm_requested_state(child_dir, True)
        self._wait_for(child_dir, True)

    def thaw_owned(self) -> bool:
        if not self.marker.exists():
            return False
        record = self._read_record()
        child_dir = self._child_dir(record)
        if not child_dir.exists():
            self.marker.unlink()
            return True
        self._write_state(child_dir, False)
        self._confirm_requested_state(child_dir, False)
        deadline = self.monotonic() + self.timeout_sec
        while pids := self._read_pids(child_dir):
            for pid in pids:
                try:
                    self._move_pid(pid, self.cgroup_dir)
                except ProcessLookupError:
                    pass
            if self.monotonic() >= deadline:
                raise ThawError("owned child cgroup did not empty after thaw")
            self.sleep(0.01)
        child_dir.rmdir()
        self.marker.unlink()
        return True

    @contextmanager
    def hold(self, candidate: ProcessSnapshot) -> Iterator[None]:
        try:
            self.freeze(candidate)
            yield
        finally:
            if self.marker.exists():
                self.thaw_owned()


class ProcessGuard:
    def __init__(
        self,
        policy: Policy,
        reader: ProcessReader,
        freezer: CgroupFreezer,
        *,
        logger: logging.Logger | None = None,
        pidfd_open: Callable[[int], int] = os.pidfd_open,
        pidfd_signal: Callable[[int, int], None] | None = None,
    ) -> None:
        self.policy = policy
        self.reader = reader
        self.freezer = freezer
        self.logger = logger or logging.getLogger("orchestra-process-guard")
        self.pidfd_open = pidfd_open
        self.pidfd_signal = pidfd_signal or signal.pidfd_send_signal

    def _event(self, decision: Decision, action: str, **extra: object) -> dict[str, object]:
        snapshot = decision.snapshot
        event = {
            "action": action,
            "pid": snapshot.pid,
            "ppid": snapshot.ppid,
            "start_ticks": snapshot.start_ticks,
            "cgroup": snapshot.cgroup,
            "exe": snapshot.exe,
            "argv0": snapshot.argv0.decode(errors="backslashreplace"),
            "comm": snapshot.comm,
            "age_sec": round(snapshot.age_sec, 3),
            "rss_kib": snapshot.rss_kib,
            "hwm_kib": snapshot.hwm_kib,
            "max_age_sec": self.policy.max_age_sec,
            "max_rss_kib": self.policy.max_rss_kib,
            "reasons": decision.reasons,
            "enabled": self.policy.enabled,
            "dry_run": self.policy.dry_run,
            "rss_action": self.policy.rss_action,
        }
        event.update(extra)
        return event

    def _log(self, event: Mapping[str, object], *, error: bool = False) -> None:
        message = json.dumps(event, sort_keys=True, separators=(",", ":"))
        (self.logger.error if error else self.logger.warning)(message)

    def handle(self, decision: Decision) -> str:
        if not decision.actionable:
            self._log(self._event(decision, "observe_only"))
            return "observe_only"
        if not self.policy.enabled:
            self._log(self._event(decision, "disabled"))
            return "disabled"
        if self.policy.dry_run:
            self._log(self._event(decision, "dry_run"))
            return "dry_run"

        try:
            pidfd = self.pidfd_open(decision.snapshot.pid)
        except ProcessLookupError:
            self._log(self._event(decision, "candidate_gone"))
            return "candidate_gone"

        try:
            try:
                current = self.reader.read(decision.snapshot.pid)
            except (FileNotFoundError, ProcessLookupError, OSError, ValueError):
                self._log(self._event(decision, "candidate_gone_before_freeze"))
                return "candidate_gone_before_freeze"
            if not same_process_image(
                decision.snapshot, current, self.policy.target_cgroup,
            ):
                self._log(self._event(decision, "identity_changed_before_freeze"))
                return "identity_changed_before_freeze"
            try:
                with self.freezer.hold(decision.snapshot):
                    try:
                        current = self.reader.read(decision.snapshot.pid)
                    except (FileNotFoundError, ProcessLookupError, OSError, ValueError):
                        self._log(self._event(decision, "candidate_gone_after_freeze"))
                        return "candidate_gone_after_freeze"
                    if not same_process_image(
                        decision.snapshot, current, self.freezer.active_cgroup,
                    ):
                        self._log(self._event(decision, "identity_changed_after_freeze"))
                        return "identity_changed_after_freeze"
                    self.freezer.assert_frozen()
                    try:
                        self.pidfd_signal(pidfd, signal.SIGKILL)
                    except Exception as error:
                        self._log(
                            self._event(
                                decision,
                                "signal_failed",
                                signal="SIGKILL",
                                error=f"{type(error).__name__}: {error}",
                            ),
                            error=True,
                        )
                        raise
                    self._log(self._event(decision, "killed", signal="SIGKILL"))
                    return "killed"
            except FreezeTimeout as error:
                self._log(self._event(decision, "freeze_timeout", error=str(error)), error=True)
                return "freeze_timeout"
            except FreezeError as error:
                self._log(
                    self._event(
                        decision,
                        "freeze_failed",
                        error=f"{type(error).__name__}: {error}",
                    ),
                    error=True,
                )
                raise
        finally:
            os.close(pidfd)

    def run_once(self) -> list[str]:
        results = []
        for snapshot in self.reader.snapshots():
            decision = decide(snapshot, self.policy)
            if decision is not None:
                results.append(self.handle(decision))
        return results


def _cgroup_dir(policy: Policy, root: Path = Path("/sys/fs/cgroup")) -> Path:
    return root / policy.target_cgroup.lstrip("/")


def _validate_guard_context(policy: Policy, reader: ProcessReader, freezer: CgroupFreezer) -> None:
    freezer.validate()
    try:
        own_cgroup = reader.read(os.getpid()).cgroup
    except (FileNotFoundError, ProcessLookupError, OSError, ValueError) as error:
        raise ConfigError(f"cannot read guard's own cgroup: {error}") from error
    target = policy.target_cgroup.rstrip("/")
    if own_cgroup == target or own_cgroup.startswith(target + "/"):
        raise ConfigError("guard is inside TARGET_CGROUP and would freeze itself")


def _build(policy: Policy) -> ProcessGuard:
    reader = ProcessReader()
    freezer = CgroupFreezer(
        _cgroup_dir(policy), policy.target_cgroup, policy.freeze_marker,
        policy.freeze_timeout_sec,
    )
    _validate_guard_context(policy, reader, freezer)
    return ProcessGuard(policy, reader, freezer)


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check-config", action="store_true")
    modes.add_argument("--thaw", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("orchestra-process-guard")
    try:
        policy = load_policy(os.environ if env is None else env)
        guard = _build(policy)
        if args.check_config:
            logger.info(json.dumps({"action": "config_ok", "armed": policy.armed}))
            return 0
        if args.thaw:
            recovered = guard.freezer.thaw_owned()
            logger.warning(json.dumps({"action": "thaw_recovery", "recovered": recovered}))
            return 0

        recovered = guard.freezer.thaw_owned()
        if recovered:
            logger.warning(json.dumps({"action": "startup_thaw_recovery"}))
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
        signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
        while not stop.is_set():
            guard.run_once()
            stop.wait(policy.poll_sec)
        return 0
    except (ConfigError, GuardError) as error:
        logger.error(json.dumps({"action": "fatal", "error": f"{type(error).__name__}: {error}"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
