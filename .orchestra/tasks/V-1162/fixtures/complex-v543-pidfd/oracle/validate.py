from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


def load(path: Path):
    candidate = path / "src" / "process_manager.py"
    if not candidate.exists():
        candidate = path / "process_manager.py"
    spec = importlib.util.spec_from_file_location("candidate_process_manager", candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pidfd_count() -> int:
    count = 0
    for name in os.listdir("/proc/self/fd"):
        try:
            target = os.readlink(f"/proc/self/fd/{name}")
        except OSError:
            continue
        if target == "anon_inode:[pidfd]":
            count += 1
    return count


def child_code(delay: float) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({delay!r})"]


def assert_reaped(pid: int) -> None:
    assert not Path(f"/proc/{pid}").exists(), f"child {pid} remains after run_child returned"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    if not sys.platform.startswith("linux") or not hasattr(os, "pidfd_open"):
        raise RuntimeError("fixture requires Linux os.pidfd_open")
    module = load(args.candidate)
    baseline = pidfd_count()

    for _ in range(6):
        result = module.run_child(child_code(0.015), timeout=1.0)
        assert result["returncode"] == 0 and not result["timed_out"] and not result["cancelled"]
        assert_reaped(result["pid"])

    for _ in range(4):
        result = module.run_child(child_code(1.0), timeout=0.015)
        assert result["timed_out"] and not result["cancelled"] and result["returncode"] is not None
        assert_reaped(result["pid"])

    for _ in range(4):
        cancel = threading.Event()
        timer = threading.Timer(0.015, cancel.set)
        timer.start()
        result = module.run_child(child_code(1.0), timeout=2.0, cancel_event=cancel)
        timer.join()
        assert result["cancelled"] and not result["timed_out"] and result["returncode"] is not None
        assert_reaped(result["pid"])

    assert pidfd_count() == baseline, "pidfd count increased after normal/timeout/cancel runs"
    print("PASS: 6 normal, 4 timeout, 4 cancellation runs; children reaped and pidfd count stable")


if __name__ == "__main__":
    main()
