from __future__ import annotations

from app import native_memory


def test_trim_native_heap_collects_python_and_calls_glibc(monkeypatch):
    calls = []

    class Trim:
        argtypes = None
        restype = None

        def __call__(self, pad):
            calls.append(pad)
            return 1

    class Libc:
        malloc_trim = Trim()

    monkeypatch.setattr(native_memory.gc, "collect", lambda: calls.append("gc") or 7)
    monkeypatch.setattr(native_memory.ctypes, "CDLL", lambda _name: Libc())

    assert native_memory.trim_native_heap("test") is True
    assert calls == ["gc", 0]


def test_trim_native_heap_is_fail_soft_without_glibc_symbol(monkeypatch):
    monkeypatch.setattr(native_memory.gc, "collect", lambda: 0)
    monkeypatch.setattr(native_memory.ctypes, "CDLL", lambda _name: object())

    assert native_memory.trim_native_heap("test") is False
