#!/usr/bin/env python3
"""Destructive rehearsal of the seamless restart, against the mini stand only (#237 T4).

Unit tests prove the seams; they cannot prove that systemd really keeps the descriptors, that
the CLI really survives, or that the turn really finishes. This runner drives one real agent
through a real restart and reports the evidence that decides it.

The target unit is a hard-coded constant with no CLI surface, and both `--dry-run` and
`--execute` go through the SAME builder — a runner whose safe dry-run and destructive run
construct their commands separately would be a lie in exactly the place it matters.
Everything here refuses to touch the production supervisor: see `docs/tasks/237/stand.md`.

Usage:
    rehearse-seamless-restart.py --dry-run                 # print the restart argv, do nothing
    rehearse-seamless-restart.py --execute --agent codex-237 --marker /path/final.txt \\
        --expect "DONE-237"
"""

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

#: The ONLY unit this script may ever touch. Not a default, not an option: the whole point of
#: a versioned destructive runner is that no invocation can retarget it at the live service.
UNIT = "orchestra-237.service"
STAND_ENV = Path("/home/kesha/orchestra-scratch/237/stand.env")
STAND_URL = "http://127.0.0.1:18888"
#: Production terminal marker of a finished Codex turn: `type=status`, content starts with
#: "turn ended". Codex has no distinct terminal EVENT type — an oracle that waited for one
#: measured nothing and reported failure on a working mechanism (#237, run7).
TERMINAL_PREFIX = "turn ended"


def restart_command() -> list[str]:
    """The single command builder shared by the dry run and the destructive run."""
    return ["sudo", "systemctl", "restart", UNIT]


def _token() -> str:
    for line in STAND_ENV.read_text().splitlines():
        if line.startswith("INTERNAL_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"no INTERNAL_TOKEN in {STAND_ENV}")


def _api(path: str) -> dict | list:
    request = urllib.request.Request(
        f"{STAND_URL}{path}", headers={"Authorization": f"Bearer {_token()}"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())


def _unit_property(name: str) -> str:
    result = subprocess.run(
        ["systemctl", "show", UNIT, "-p", name, "--value", "--no-pager"],
        text=True, capture_output=True, check=False)
    return result.stdout.strip()


def _proc_start_time(pid: int) -> int:
    """Field 22 of /proc/<pid>/stat: distinguishes this process from a reused pid."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return 0
    return int(stat[stat.rindex(")") + 2:].split()[19])


def _session(agent: str) -> dict:
    for row in _api("/api/sessions"):
        if row.get("name") == agent:
            return row
    raise SystemExit(f"agent {agent!r} is not on the stand")


def _events(agent: str) -> list[dict]:
    logs = _api(f"/api/sessions/{agent}/logs")
    return logs if isinstance(logs, list) else logs.get("logs", [])


def _loop_is_production_shaped() -> tuple[bool, str]:
    """The stand must run the SAME event loop as production, i.e. uvloop.

    Measured in #237: `get_extra_info("pipe")` returns None under uvloop, so a rehearsal on
    the default asyncio loop is the exact false positive that hid the production failure for
    a whole day. A forced `--loop asyncio` therefore invalidates the whole run.
    """
    exec_start = _unit_property("ExecStart")
    if "--loop asyncio" in exec_start or "--loop=asyncio" in exec_start:
        return False, "stand forces --loop asyncio; uvloop is the production shape"
    return True, "uvloop (no --loop override in ExecStart)"


def rehearse(agent: str, marker: Path, expect: str, *, settle_s: float,
             run=subprocess.run) -> dict:
    """One real mid-turn restart, reported by positive evidence only."""
    loop_ok, loop_note = _loop_is_production_shaped()

    before = _session(agent)
    if before.get("status") != "running":
        raise SystemExit(
            f"{agent} is {before.get('status')!r}: with no live turn the run would prove "
            "nothing — absence of a cut is not evidence of a survived cut")
    actual_cli_pid = int(before.get("cli_pid") or 0)
    if not actual_cli_pid:
        raise SystemExit(f"{agent} exposes no CLI pid; it cannot have been handed over")
    cli_started_at = _proc_start_time(actual_cli_pid)
    main_pid_before = _unit_property("MainPID")
    events_before = len(_events(agent))
    if marker.exists():
        marker.unlink()

    run(restart_command(), check=True)
    time.sleep(settle_s)

    main_pid_after = _unit_property("MainPID")
    fd_store = _unit_property("NFileDescriptorStore")
    after = _session(agent)
    events = _events(agent)
    tail = events[events_before:]
    # The turn's own frames, in the order the next generation delivered them. Both the order
    # and the count matter: a replayed handover shows a duplicate here and nowhere else.
    sequence = [row.get("type", "") for row in tail]
    terminal = [row for row in tail
                if row.get("type") == "status"
                and str(row.get("content", "")).startswith(TERMINAL_PREFIX)]

    result_text = marker.read_text() if marker.exists() else ""
    checks = {
        "loop_is_uvloop": loop_ok,
        "supervisor_restarted": main_pid_before != main_pid_after and main_pid_after != "0",
        "cli_survived": _proc_start_time(actual_cli_pid) == cli_started_at
                        and cli_started_at != 0,
        "descriptors_were_stored": (fd_store.isdigit() and int(fd_store) > 0),
        "result_is_byte_exact": result_text == expect,
        "terminal_event_delivered": len(terminal) == 1,
        "left_running": after.get("status") != "running",
        "no_duplicate_terminal": len(terminal) <= 1,
    }
    return {
        "unit": UNIT,
        "agent": agent,
        "loop": loop_note,
        "main_pid_before": main_pid_before,
        "main_pid_after": main_pid_after,
        "actual_cli_pid": actual_cli_pid,
        "cli_started_at": cli_started_at,
        "NFileDescriptorStore": fd_store,
        "sequence": sequence,
        "count": len(tail),
        "terminal_count": len(terminal),
        "result": result_text,
        "checks": checks,
        "verdict": "PASS" if all(checks.values()) else "FAIL",
    }


def main(argv=None, *, run=subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="print the restart argv and exit without touching anything")
    mode.add_argument("--execute", action="store_true",
                      help="restart the mini stand mid-turn and report the evidence")
    parser.add_argument("--agent", default="")
    parser.add_argument("--marker", default="")
    parser.add_argument("--expect", default="")
    parser.add_argument("--settle", type=float, default=90.0)
    args = parser.parse_args(argv)

    if args.dry_run:
        print(json.dumps({"restart_argv": restart_command()}))
        return 0

    if os.geteuid() == 0:
        parser.error("run as the stand user, not root")
    if not (args.agent and args.marker and args.expect):
        # A bare restart of the stand: the same destructive action through the same builder,
        # just with nothing to measure. Reported as such instead of pretending it is evidence.
        run(restart_command(), check=True)
        print(json.dumps({"restarted": UNIT, "measured": False}))
        return 0
    report = rehearse(args.agent, Path(args.marker), args.expect,
                      settle_s=args.settle, run=run)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
