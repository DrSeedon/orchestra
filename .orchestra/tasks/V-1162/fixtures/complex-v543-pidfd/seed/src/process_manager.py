from __future__ import annotations

import os
import signal
import subprocess
import time


def _stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=0.2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def run_child(argv, timeout, cancel_event=None):
    process = subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    pidfd = os.pidfd_open(process.pid)
    start = time.monotonic()
    timed_out = False
    cancelled = False
    try:
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                _stop_group(process)
                break
            if time.monotonic() - start >= timeout:
                timed_out = True
                _stop_group(process)
                break
            time.sleep(0.002)
        return {
            "pid": process.pid,
            "returncode": process.wait(),
            "timed_out": timed_out,
            "cancelled": cancelled,
        }
    finally:
        if not timed_out and not cancelled:
            os.close(pidfd)
