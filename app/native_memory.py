"""Return transient native allocations to the OS after bounded heavy phases."""

from __future__ import annotations

import ctypes
import gc
import logging


logger = logging.getLogger("orchestra.native_memory")


def trim_native_heap(reason: str) -> bool:
    """Collect Python cycles and ask glibc to release completely free heap pages.

    `malloc_trim` is an optimization, never a correctness dependency: musl and non-Linux
    runtimes may not expose it. The systemd arena bound remains the primary guard.
    """

    collected = gc.collect()
    try:
        trim = getattr(ctypes.CDLL(None), "malloc_trim")
        trim.argtypes = [ctypes.c_size_t]
        trim.restype = ctypes.c_int
        released = bool(trim(0))
    except (AttributeError, OSError):
        logger.debug("malloc_trim unavailable after %s", reason)
        return False
    if released:
        logger.debug("native heap trimmed after %s (gc=%d)", reason, collected)
    return released
