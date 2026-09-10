"""Systemd socket activation and readiness notification."""

import fcntl
import os
import socket

SD_LISTEN_FDS_START = 3


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
    _notify("READY=1")
    return True


def _notify(payload: str) -> None:
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        raise RuntimeError(f"NOTIFY_SOCKET is not set: cannot send {payload!r}")
    exec_pid = os.environ.get("SYSTEMD_EXEC_PID")
    if exec_pid and exec_pid != str(os.getpid()):
        raise RuntimeError(
            f"SYSTEMD_EXEC_PID={exec_pid} does not name this process: "
            f"refusing inherited systemd notification {payload!r}"
        )
    if address.startswith("@"):
        address = "\0" + address[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
    try:
        sock.sendto(payload.encode(), address)
    except OSError as exc:
        raise RuntimeError(
            f"systemd refused {payload!r}: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        sock.close()


def _activation_fds() -> dict[str, int]:
    count = int(os.environ.get("LISTEN_FDS") or 0)
    if count <= 0:
        return {}

    # LISTEN_* may have been inherited from a PARENT: then it names the parent's descriptors,
    # and reading them here would use descriptors we do not own.
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
        # A dictionary would silently discard duplicate names and lose their descriptors.
        raise ValueError(f"duplicate FDNAME(s) inherited: {sorted(duplicates)}")

    return {name: SD_LISTEN_FDS_START + index for index, name in enumerate(names)}


def acquire_fds() -> dict[str, int]:
    """Return socket activation descriptors by their systemd names."""
    return _activation_fds()


def seal_activation_fds() -> dict[str, int]:
    """Set close-on-exec on every inherited systemd descriptor without closing it."""
    fds = _activation_fds()
    for fd in fds.values():
        flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
    return fds
