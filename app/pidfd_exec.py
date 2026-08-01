"""Exec shim that hands its own pidfd to the parent before running a target."""

import array
import ctypes
import errno
import os
import socket
import sys


PIDFD_SIGNAL_PROCESS_GROUP = 1 << 2

_libc = ctypes.CDLL(None, use_errno=True)
try:
    _pidfd_open = _libc.pidfd_open
    _pidfd_send_signal = _libc.pidfd_send_signal
except AttributeError:
    _pidfd_open = _pidfd_send_signal = None
else:
    _pidfd_open.argtypes = (ctypes.c_int, ctypes.c_uint)
    _pidfd_open.restype = ctypes.c_int
    _pidfd_send_signal.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint,
    )
    _pidfd_send_signal.restype = ctypes.c_int


def pidfd_open_self() -> int:
    if _pidfd_open is None:
        raise OSError(errno.ENOSYS, "libc pidfd functions are unavailable")
    fd = _pidfd_open(os.getpid(), 0)
    if fd < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return fd


def pidfd_send_group(pidfd: int, sig: int) -> bool:
    """Signal the retained process group; return False once the group is gone."""
    if _pidfd_send_signal is None:
        raise OSError(errno.ENOSYS, "libc pidfd functions are unavailable")
    if _pidfd_send_signal(
        pidfd, sig, None, PIDFD_SIGNAL_PROCESS_GROUP,
    ) == 0:
        return True
    error = ctypes.get_errno()
    if error == errno.ESRCH:
        return False
    raise OSError(error, os.strerror(error))


def _send_pidfd(control: socket.socket, pidfd: int) -> None:
    rights = array.array("i", [pidfd])
    control.sendmsg(
        [b"P"],
        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)],
    )


def main() -> int:
    if len(sys.argv) < 4 or sys.argv[2] not in {"shell", "argv"}:
        return 64
    control = socket.socket(fileno=int(sys.argv[1]))
    try:
        try:
            pidfd = pidfd_open_self()
        except OSError as exc:
            control.send((f"E{exc.errno}:{exc.strerror}").encode())
            return 70
        try:
            _send_pidfd(control, pidfd)
        finally:
            os.close(pidfd)
        if control.recv(1) != b"A":
            return 71
    finally:
        control.close()

    if sys.argv[2] == "shell":
        os.execv("/bin/sh", ["/bin/sh", "-c", sys.argv[3]])
    os.execvp(sys.argv[3], sys.argv[3:])
    return 72


if __name__ == "__main__":
    raise SystemExit(main())
