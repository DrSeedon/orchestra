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
"""
import os
import sys

ARGV_TAIL = (b"app-server", b"--stdio")


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


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "snapshot":
        for pid, (start, comm, _ppid) in live().items():
            print(pid, start, comm)
        return 0
    if mode == "check":
        current = live()
        unresolved = 0
        for line in open(sys.argv[2]):
            parts = line.split()
            if len(parts) < 2:
                continue
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
