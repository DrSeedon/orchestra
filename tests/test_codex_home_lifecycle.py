"""Guard against cloning shared history and losing existing native threads."""
import sqlite3
from unittest.mock import AsyncMock

import pytest

import app.backend_codex as module


@pytest.fixture
def homes(tmp_path, monkeypatch):
    base = tmp_path / "base"
    (base / "sessions").mkdir(parents=True)
    (base / "sessions" / "foreign.jsonl").write_text("foreign history")
    (base / "state_5.sqlite").write_bytes(b"shared state")
    root = tmp_path / "managed"
    monkeypatch.setattr(module, "_CODEX_HOME_ROOT", root)
    monkeypatch.setattr(module, "_base_codex_home", lambda: base)
    monkeypatch.setattr(module, "_run_process", AsyncMock(return_value=(0, "codex-cli 0.153.4", "")))
    return base, root


def backend(tmp_path, sid, thread=None):
    return module.CodexBackend(
        model="gpt-5.6-luna", cwd=str(tmp_path), resume_thread_id=thread,
        mcp_servers={"orchestra": {
            "command": "/bin/true", "enabled_tools": [],
            "env": {"ORCHESTRA_SESSION_ID": sid},
        }},
    )


@pytest.mark.asyncio
async def test_new_home_does_not_read_or_seed_shared_state(tmp_path, monkeypatch, homes):
    # Without this guard every spawn can read/clone the entire shared thread index.
    base, root = homes
    be = backend(tmp_path, "fresh")
    seen = []

    def unexpected_sqlite(*args, **kwargs):
        pytest.fail("home preparation accessed SQLite instead of leaving state to Codex")

    async def provider_start():
        home = root / "fresh"
        seen.append(home)
        assert not (home / "state_5.sqlite").exists()

    monkeypatch.setattr(sqlite3, "connect", unexpected_sqlite)
    monkeypatch.setattr(be, "_connect_unlocked", provider_start)
    await be.connect()
    assert seen == [root / "fresh"]
    assert (base / "state_5.sqlite").read_bytes() == b"shared state"


@pytest.mark.asyncio
async def test_new_sessions_stay_private_across_reconnect(tmp_path, monkeypatch, homes):
    # Sharing sessions would rebuild the same large index inside the CLI without seeding.
    _, root = homes
    be = backend(tmp_path, "private")
    home = root / "private"
    calls = 0

    async def provider_start():
        nonlocal calls
        sessions = home / "sessions"
        assert sessions.is_dir() and not sessions.is_symlink()
        assert not (sessions / "foreign.jsonl").exists()
        if calls:
            assert (sessions / "own.jsonl").read_text() == "own history"
            assert (home / "state_5.sqlite").read_bytes() == b"provider state"
        else:
            (sessions / "own.jsonl").write_text("own history")
            (home / "state_5.sqlite").write_bytes(b"provider state")
        calls += 1

    monkeypatch.setattr(be, "_connect_unlocked", provider_start)
    await be.connect()
    await be.disconnect()
    await be.connect()
    assert calls == 2


@pytest.mark.parametrize("broken", [False, True])
def test_existing_sessions_link_is_not_retargeted(tmp_path, homes, broken):
    # A config refresh must not move an existing worker away from its history owner.
    _, root = homes
    home = root / "existing"
    home.mkdir(parents=True)
    target = tmp_path / "original-sessions"
    if not broken:
        target.mkdir()
        (target / "own.jsonl").write_text("old history")
    (home / "sessions").symlink_to(target)
    (home / "state_5.sqlite").write_bytes(b"existing native state")
    be = backend(tmp_path, "existing", "old-thread")
    be._prepare_codex_home()
    assert (home / "sessions").readlink() == target
    assert (home / "state_5.sqlite").read_bytes() == b"existing native state"
    assert be._thread_id == "old-thread"
    if not broken:
        assert (home / "sessions" / "own.jsonl").read_text() == "old history"


def test_existing_empty_private_sessions_is_not_linked(tmp_path, homes):
    _, root = homes
    sessions = root / "empty-private" / "sessions"
    sessions.mkdir(parents=True)
    inode = sessions.stat().st_ino
    backend(tmp_path, "empty-private")._prepare_codex_home()
    assert not sessions.is_symlink()
    assert sessions.stat().st_ino == inode
