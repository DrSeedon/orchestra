import sys
import pytest
from app.workspace import _git_cmd

BAD = [sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'a\\x80b')"]

def test_text_default_replaces():
    r = _git_cmd(BAD, capture_output=True, text=True)
    assert r.stdout == "a�b"

def test_explicit_errors_respected():
    with pytest.raises(UnicodeDecodeError):
        _git_cmd(BAD, capture_output=True, text=True, errors="strict")

def test_bytes_unchanged():
    r = _git_cmd(BAD, capture_output=True)
    assert r.stdout == b"a\x80b"

def test_valid_utf8_roundtrip():
    r = _git_cmd([sys.executable, "-c", "print('привет')"], capture_output=True, text=True)
    assert r.stdout.strip() == "привет"
