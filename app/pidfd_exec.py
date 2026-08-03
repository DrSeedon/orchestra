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


def group_signal_supported() -> bool:
    """Whether the kernel can signal a process group through a pidfd.

    Probes the syscall instead of parsing a version: the capability arrived in
    Linux 6.9, and only with it does a group stay reachable after its leader is
    reaped. Below that we fall back to killpg, which is safe only while the
    leader is unreaped — so callers that depend on the stronger guarantee must
    ask here rather than assume.
    """
    if _pidfd_send_signal is None:
        return False
    fd = pidfd_open_self()
    try:
        if _pidfd_send_signal(fd, 0, None, PIDFD_SIGNAL_PROCESS_GROUP) == 0:
            return True
        return ctypes.get_errno() != errno.EINVAL
    finally:
        os.close(fd)


def pidfd_pid(pidfd: int) -> int:
    """PID behind a pidfd, or 0 once the kernel has reaped that process.

    ``/proc/self/fdinfo/<fd>`` is the only way back from a pidfd to a pid. The
    kernel reports ``Pid: 0`` (``-1`` when seen from another namespace) after
    reaping — precisely the moment the number becomes free for reuse.
    """
    try:
        with open(f"/proc/self/fdinfo/{pidfd}", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("Pid:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def _send_group_via_killpg(pidfd: int, sig: int) -> bool:
    """Group-signal fallback anchored on the pidfd, for kernels below 6.9.

    Safe for the same reason the flag is: while the leader is unreaped its pid
    cannot be recycled, so its pgid still names OUR group. Once the pidfd shows
    no pid, we report the group gone instead of signalling a stranger.
    """
    pid = pidfd_pid(pidfd)
    if pid <= 0:
        return False
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        return False
    return True


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
    if error == errno.EINVAL:
        # PIDFD_SIGNAL_PROCESS_GROUP only exists since Linux 6.9; older kernels
        # reject the flag outright, which killed every background job on a 6.8
        # host. Probing the syscall beats parsing a version string.
        return _send_group_via_killpg(pidfd, sig)
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
