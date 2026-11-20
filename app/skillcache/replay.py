"""The fixture replay executes after loading a fail-closed Linux seccomp filter."""

from copy import deepcopy
import ctypes
from pathlib import Path
import errno
import json
import resource
import sys

from .abi import Rejected, canonical, check_manifest
from .fixtures import SyntheticSources, cases
from .pilots import catalog
from .registry import digest
from .runner import advance, initial_state


def _lock_down():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024**2, 384 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (8, 8))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    seccomp = ctypes.CDLL("libseccomp.so.2")
    seccomp.seccomp_init.argtypes = (ctypes.c_uint32,)
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = (ctypes.c_char_p,)
    seccomp.seccomp_rule_add.argtypes = (ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint)
    seccomp.seccomp_load.argtypes = (ctypes.c_void_p,)
    seccomp.seccomp_release.argtypes = (ctypes.c_void_p,)
    ctx = seccomp.seccomp_init(0x00050000 | errno.EPERM)  # deny anything outside the Python computation profile
    if not ctx:
        raise RuntimeError("seccomp unavailable")
    try:
        for syscall in (
            "read", "write", "writev", "close", "fstat", "newfstatat", "lseek", "mmap", "mprotect",
            "munmap", "brk", "mremap", "madvise", "futex", "rt_sigaction", "rt_sigprocmask",
            "rt_sigreturn", "exit", "exit_group", "getrandom", "clock_gettime", "getpid", "gettid",
        ):
            nr = seccomp.seccomp_syscall_resolve_name(syscall.encode())
            if nr < 0 or seccomp.seccomp_rule_add(ctx, 0x7FFF0000, nr, 0):
                raise RuntimeError("failed to configure replay filter")
        if seccomp.seccomp_load(ctx):
            raise RuntimeError("failed to install replay filter")
    finally:
        seccomp.seccomp_release(ctx)


def _trial(manifest, abi, fixture):
    source = SyntheticSources(fixture)
    state = initial_state(manifest, abi, fixture["bindings"], fixture["workspace"])
    result = advance(manifest, abi, state, source, {})
    if result["status"] == "your_steps" and fixture["answer"]:
        result = advance(manifest, abi, state, source, fixture["answer"])
    if result["status"] != "complete":
        return False, state, source
    actual = deepcopy(result["result"])
    # The independent oracle checks all report fields except the separately
    # verified canonical checksum.
    if manifest["skill"] == "direct-reports":
        actual["totals"].pop("checksum", None)
    return actual == fixture["expected"], state, source


def main():
    manifest = json.loads(sys.stdin.read(65537))
    abi = catalog({})
    check_manifest(manifest, abi)
    baseline, changed = cases(manifest["skill"])
    suite = digest([baseline, changed, Path(__file__).read_text()])
    _lock_down()
    original_ok, old_state, _ = _trial(manifest, abi, baseline)
    changed_ok, new_state, source = _trial(manifest, abi, changed)
    stale_rejected = False
    if original_ok and changed_ok:
        for name in manifest["return"]:
            new_state["values"][name] = old_state["values"][name]
        result = advance(manifest, abi, new_state, source, {})
        stale_rejected = result["status"] == "verification_failed"
    print(canonical({"suite": suite, "checks": {
        "baseline": original_ok, "counterexample": changed_ok, "reject_stale": stale_rejected,
    }}))

