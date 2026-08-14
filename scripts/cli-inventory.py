#!/usr/bin/env python3
"""Inventory of live agent CLI processes, for the #237 activation gate.

Three modes, all read-only:

    snapshot          write `pid starttime argv0` per live CLI process to stdout
    check FILE        print UNRESOLVED for every snapshot entry still alive
    count             print the number of CLIs and how many outlived a supervisor

Why a script and not a shell snippet in the runbook: the snippet version matched
`codex app-server`, a substring that does not occur in the real argv
(`node /usr/bin/codex -c ... app-server --stdio`). It found nothing, so the gate
would have reported "no orphans" without ever looking at one. Matching is done on
the argv TAIL, the same shape `terminate_cli_process` verifies before signalling.

Identity is the pair (pid, starttime). A bare pid is not identity: numbers are
reused, and after #258 an unproven candidate is deliberately left alive.

An empty snapshot is not «no processes». `check` on an empty file used to walk
zero lines and exit 0 — the same answer as a blind matcher (#271). Fail-closed
on both arms: leftover CLI while the file is empty, and a canary the scanner
cannot see.
"""
import os
import subprocess
import sys
import time

ARGV_TAIL = (b"app-server", b"--stdio")
_CANARY_ARGV = [sys.executable, "-c", "import time; time.sleep(30)", "app-server", "--stdio"]


def _starttime(pid: int) -> str:
    # field 22, counted AFTER the comm field: comm is parenthesised and may contain
    # spaces, so splitting the whole line would shift every column.
    stat = open(f"/proc/{pid}/stat").read()
    return stat[stat.rindex(")") + 2:].split()[19]


def _ppid(pid: int) -> int:
    return int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])


def live() -> dict[int, tuple[str, str, int]]:
    """pid -> (starttime, argv0 basename, ppid) for every live agent CLI."""
    found: dict[int, tuple[str, str, int]] = {}
    for pid in sorted(int(p) for p in os.listdir("/proc") if p.isdigit()):
        try:
            argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")[:-1]
            if tuple(argv[-2:]) != ARGV_TAIL:
                continue
            found[pid] = (_starttime(pid), os.path.basename(argv[0].decode()), _ppid(pid))
        except (OSError, ValueError, IndexError):
            continue  # process died mid-read, or an unreadable /proc entry
    return found


def _spawn_canary() -> subprocess.Popen:
    return subprocess.Popen(
        _CANARY_ARGV,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


def _canary_visible(pid: int, tries: int = 40) -> bool:
    for _ in range(tries):
        if pid in live():
            return True
        time.sleep(0.05)
    return False


def _prove_vision() -> str | None:
    """Return an error string if the scanner cannot see a process it just started."""
    try:
        canary = _spawn_canary()
    except OSError as exc:
        return f"BLIND: cannot spawn canary: {exc}"
    try:
        if _canary_visible(canary.pid):
            return None
        return "BLIND: inventory cannot see a live canary"
    finally:
        _kill(canary)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "snapshot":
        blind = _prove_vision()
        if blind:
            print(blind, file=sys.stderr)
            return 2
        for pid, (start, comm, _ppid) in live().items():
            print(pid, start, comm)
        return 0
    if mode == "check":
        if len(sys.argv) < 3:
            print("usage: cli-inventory.py check FILE", file=sys.stderr)
            return 2
        current = live()
        entries: list[list[str]] = []
        for line in open(sys.argv[2]):
            parts = line.split()
            if len(parts) < 2:
                continue
            entries.append(parts)
        if not entries:
            if current:
                print(
                    f"BLIND: snapshot is empty but live inventory sees "
                    f"{len(current)} CLI process(es)",
                    file=sys.stderr,
                )
                return 2
            blind = _prove_vision()
            if blind:
                print(blind, file=sys.stderr)
                return 2
            print("checked 0 entries, 0 still alive")
            return 0
        unresolved = 0
        for parts in entries:
            pid, start = int(parts[0]), parts[1]
            try:
                still = _starttime(pid)
            except (OSError, ValueError, IndexError):
                continue  # gone: reaped, which is what we want
            if still == start:
                print(f"UNRESOLVED: pid={pid} starttime={start} "
                      f"{' '.join(parts[2:])}")
                unresolved += 1
        print(f"checked {sum(1 for _ in open(sys.argv[2]))} entries, "
              f"{unresolved} still alive")
        return 1 if unresolved else 0
    if mode == "count":
        found = live()
        # One CLI is two processes (a `node` wrapper and the real binary). Count the
        # top of each pair, so the number is comparable with the session count.
        top = [p for p, (_s, _c, ppid) in found.items() if ppid not in found]
        print(f"processes={len(found)} clis={len(top)} "
              f"survived_a_restart={sum(1 for p in top if found[p][2] == 1)}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
