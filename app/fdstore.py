"""Hand agent pipe FDs to systemd and take them back after a restart (#230 T1).

The mechanism is measured, not assumed: with `KillMode=process` plus systemd's file descriptor
store, a real Codex and a real Claude CLI survive `systemctl restart` and keep streaming their
turn to the NEXT supervisor generation (.orchestra/tasks/230/research.md, F1).
"""

import array
import fcntl
import os
import re
import socket

SD_LISTEN_FDS_START = 3

#: systemd accepts only these characters in an FDNAME and SILENTLY rewrites anything else to
#: `stored` — measured in #237: `agent:<uuid>:stdin` and `agent:<uuid>:stdout` both came back
#: as `stored`, collided as duplicates, and the next generation refused to start. `:` cannot
#: be legal in any case: it is the LISTEN_FDNAMES separator.
_SAFE_FDNAME = re.compile(r"[A-Za-z0-9_.-]+")


class FdStoreUnavailable(RuntimeError):
    """The handover did NOT happen. Never swallow this: silence here loses live agents."""


def notify_ready() -> bool:
    """Tell systemd that FastAPI startup gates completed.

    Service environment is inherited by test/agent children, so NOTIFY_SOCKET alone is
    insufficient: only the exact SYSTEMD_EXEC_PID may publish readiness. Type=simple legacy
    units have no notify socket and remain compatible until the unit is upgraded.
    """
    if not os.environ.get("NOTIFY_SOCKET"):
        return False
    if os.environ.get("SYSTEMD_EXEC_PID") != str(os.getpid()):
        return False
    _notify("READY=1", ())
    return True


def _check_fdname(name: str) -> None:
    """Refuse a name systemd would rewrite, before anything is handed over (#237 T2)."""
    if not _SAFE_FDNAME.fullmatch(name):
        raise ValueError(
            f"unsafe FDNAME {name!r}: systemd accepts only [A-Za-z0-9_.-] and silently "
            "replaces anything else with 'stored', which collides across agents"
        )


def remove_fds(name: str) -> None:
    """Drop whatever systemd holds under `name` (#230).

    Needed because the store SURVIVES the restart it exists for: re-submitting the same name on
    the next shutdown would ADD a second entry, and duplicates accumulate generation after
    generation until `FileDescriptorStoreMax` is exhausted. Removal makes the handover
    idempotent per name.
    """
    _notify(f"FDSTOREREMOVE=1\nFDNAME={name}", ())


def store_fds(name: str, fds: list[int]) -> None:
    """Give `fds` to systemd under `name`, so they outlive this process.

    Replaces any entry already held under that name — see `remove_fds`.
    """
    if not fds:
        raise FdStoreUnavailable(f"no descriptors to hand over under {name}")

    _check_fdname(name)
    remove_fds(name)
    _notify(f"FDSTORE=1\nFDNAME={name}", fds)


def _notify(payload: str, fds) -> None:
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        raise FdStoreUnavailable(f"NOTIFY_SOCKET is not set: cannot send {payload!r}")
    exec_pid = os.environ.get("SYSTEMD_EXEC_PID")
    if exec_pid and exec_pid != str(os.getpid()):
        raise FdStoreUnavailable(
            f"SYSTEMD_EXEC_PID={exec_pid} does not name this process: "
            f"refusing inherited systemd notification {payload!r}"
        )
    if address.startswith("@"):
        address = "\0" + address[1:]
    ancillary = (
        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", list(fds)))] if fds else []
    )
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
    try:
        sock.sendmsg([payload.encode()], ancillary, 0, address)
    except OSError as exc:
        raise FdStoreUnavailable(
            f"systemd refused {payload!r}: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        sock.close()


def _activation_fds() -> dict[str, int]:
    count = int(os.environ.get("LISTEN_FDS") or 0)
    if count <= 0:
        return {}

    # LISTEN_* may have been inherited from a PARENT: then it names the parent's descriptors,
    # and adopting them here would attach us to something we do not own.
    listen_pid = os.environ.get("LISTEN_PID")
    if listen_pid != str(os.getpid()):
        return {}

    names = (os.environ.get("LISTEN_FDNAMES") or "").split(":")
    if names == [""]:
        names = []
    if len(names) != count:
        raise ValueError(
            f"LISTEN_FDS={count} but LISTEN_FDNAMES has {len(names)} entries ({names}): "
            "refusing to guess which descriptor is which"
        )
    for index, name in enumerate(names):
        if not name:
            # keep the slot in the message: a positional protocol error is more useful than
            # a generic count mismatch
            raise ValueError(f"LISTEN_FDNAMES slot {index} has no name: {names}")
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        # Silently keeping one copy would leak the others until the store is exhausted —
        # exactly what accumulates when a handover re-adds a name it never removed.
        raise ValueError(f"duplicate FDNAME(s) inherited: {sorted(duplicates)}")

    return {name: SD_LISTEN_FDS_START + index for index, name in enumerate(names)}


def acquire_fds() -> dict[str, int]:
    """Return inherited descriptors keyed by their FDNAME.

    Keyed by NAME only: systemd does not preserve the order in which the descriptors were
    handed over (measured — stdin,stdout came back as stdout,stdin), so trusting the position
    attaches an agent's stdin to its stdout.
    """
    return _activation_fds()


def seal_activation_fds() -> dict[str, int]:
    """Set close-on-exec on every inherited systemd descriptor without closing it."""
    fds = _activation_fds()
    for fd in fds.values():
        flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
    return fds
