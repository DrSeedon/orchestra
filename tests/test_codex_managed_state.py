import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

from app.runtime_history import CODEX_CLI_HISTORY_VERSION

SEED_CLI_VERSION = "0.150.1"


def test_codex_01501_state_signature_is_pinned_exactly():
    from app.backend_codex import _CODEX_STATE_MIGRATIONS_BY_CLI

    migrations = _CODEX_STATE_MIGRATIONS_BY_CLI[SEED_CLI_VERSION]
    assert migrations[-1] == (
        51,
        bytes.fromhex(
            "23360a03a7fc307c3fd5bb8b432b66034dd8f8695cdba698"
            "b45278c20dd712c1af476b884e192237d80baa08a5f29505"
        ),
    )


def _state_db(
    path: Path,
    *,
    status: str = "complete",
    last_success_at: int | None = 100,
    migrations: tuple[tuple[int, bytes], ...] | None = None,
    threads: tuple[str, ...] = ("thread-source",),
) -> None:
    if migrations is None:
        from app.backend_codex import _CODEX_STATE_MIGRATIONS_BY_CLI

        migrations = _CODEX_STATE_MIGRATIONS_BY_CLI[SEED_CLI_VERSION]
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE _sqlx_migrations (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                installed_on TEXT NOT NULL,
                success INTEGER NOT NULL,
                checksum BLOB NOT NULL,
                execution_time INTEGER NOT NULL
            );
            CREATE TABLE backfill_state (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                last_watermark TEXT,
                last_success_at INTEGER,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE threads (id TEXT PRIMARY KEY);
            """
        )
        conn.executemany(
            "INSERT INTO _sqlx_migrations VALUES (?, 'state schema', 'now', 1, ?, 1)",
            migrations,
        )
        conn.execute(
            "INSERT INTO backfill_state VALUES (1, ?, NULL, ?, 101)",
            (status, last_success_at),
        )
        conn.executemany("INSERT INTO threads VALUES (?)", ((item,) for item in threads))


def _thread_ids(path: Path) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [row[0] for row in conn.execute("SELECT id FROM threads ORDER BY id")]


def _prepare(home: Path, source: Path):
    import app.backend_codex as module

    return module._prepare_managed_codex_state(
        home,
        source,
        cli_version=SEED_CLI_VERSION,
    )


def test_fresh_state_uses_sqlite_backup_with_committed_wal_rows(tmp_path):
    source = tmp_path / "base" / "state_5.sqlite"
    source.parent.mkdir()
    _state_db(source)
    writer = sqlite3.connect(source)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO threads VALUES ('thread-in-wal')")
        writer.commit()
        assert Path(f"{source}-wal").exists()

        home = tmp_path / "managed"
        home.mkdir()
        assert _prepare(home, source) == "seeded"
    finally:
        writer.close()

    assert _thread_ids(home / "state_5.sqlite") == ["thread-in-wal", "thread-source"]


def test_healthy_existing_state_is_untouched_without_reading_source(tmp_path):
    home = tmp_path / "managed"
    home.mkdir()
    target = home / "state_5.sqlite"
    _state_db(target, threads=("target-only",))
    before = target.read_bytes()
    before_stat = target.stat()
    corrupt_source = tmp_path / "corrupt-source.sqlite"
    corrupt_source.write_bytes(b"not sqlite")

    assert _prepare(home, corrupt_source) == "healthy"

    after_stat = target.stat()
    assert target.read_bytes() == before
    assert after_stat.st_ino == before_stat.st_ino
    assert after_stat.st_mtime_ns == before_stat.st_mtime_ns
    assert _thread_ids(target) == ["target-only"]


def test_stale_never_successful_running_state_is_preserved_then_reseeded(tmp_path):
    source = tmp_path / "base.sqlite"
    _state_db(source, threads=("healthy-thread",))
    home = tmp_path / "managed"
    home.mkdir()
    target = home / "state_5.sqlite"
    _state_db(
        target,
        status="running",
        last_success_at=None,
        threads=("stale-thread",),
    )

    assert _prepare(home, source) == "recovered"
    assert _thread_ids(target) == ["healthy-thread"]
    recovery = list(home.glob("state-recovery-*"))
    assert len(recovery) == 1
    assert _thread_ids(recovery[0] / "state_5.sqlite") == ["stale-thread"]

    assert _prepare(home, source) == "healthy"
    assert list(home.glob("state-recovery-*")) == recovery


@pytest.mark.parametrize("source_kind", ["partial", "corrupt"])
def test_fresh_state_refuses_partial_or_corrupt_source(tmp_path, source_kind):
    source = tmp_path / "source.sqlite"
    if source_kind == "partial":
        _state_db(source, status="running", last_success_at=None)
    else:
        source.write_bytes(b"not a sqlite database")
    home = tmp_path / "managed"
    home.mkdir()

    with pytest.raises(RuntimeError):
        _prepare(home, source)

    assert not (home / "state_5.sqlite").exists()
    assert not list(home.glob("state-recovery-*"))


def test_state_seed_refuses_unpinned_cli_version(tmp_path):
    import app.backend_codex as module

    source = tmp_path / "source.sqlite"
    _state_db(source)
    home = tmp_path / "managed"
    home.mkdir()

    with pytest.raises(RuntimeError, match="has no verified schema"):
        module._prepare_managed_codex_state(home, source, cli_version="0.999.0")

    assert not (home / "state_5.sqlite").exists()


def test_healthy_state_with_validated_older_prefix_is_left_for_provider_migration(
    tmp_path,
):
    import app.backend_codex as module

    migrations = module._CODEX_STATE_MIGRATIONS_BY_CLI[SEED_CLI_VERSION]
    assert len(migrations) > 4
    home = tmp_path / "managed"
    home.mkdir()
    target = home / "state_5.sqlite"
    _state_db(target, migrations=migrations[:-4], threads=("old-thread",))

    assert module._managed_codex_state_needs_seed(
        home,
        SEED_CLI_VERSION,
    ) is False
    assert _thread_ids(target) == ["old-thread"]


def test_fresh_state_can_seed_from_validated_older_prefix(tmp_path):
    import app.backend_codex as module

    migrations = module._CODEX_STATE_MIGRATIONS_BY_CLI[SEED_CLI_VERSION]
    source = tmp_path / "source.sqlite"
    _state_db(source, migrations=migrations[:-4], threads=("old-thread",))
    home = tmp_path / "managed"
    home.mkdir()

    assert _prepare(home, source) == "seeded"
    assert _thread_ids(home / "state_5.sqlite") == ["old-thread"]


@pytest.mark.parametrize("mutation", ["changed", "extra"])
def test_state_seed_refuses_unsupported_pinned_migration_signature(
    tmp_path, mutation,
):
    import app.backend_codex as module

    migrations = list(
        module._CODEX_STATE_MIGRATIONS_BY_CLI[SEED_CLI_VERSION]
    )
    if mutation == "changed":
        version, checksum = migrations[-1]
        migrations[-1] = (version, bytes([checksum[0] ^ 1]) + checksum[1:])
    else:
        migrations.append((migrations[-1][0] + 1, b"unsupported-migration"))
    source = tmp_path / "source.sqlite"
    _state_db(source, migrations=tuple(migrations))
    home = tmp_path / "managed"
    home.mkdir()

    with pytest.raises(RuntimeError, match="unsupported Codex state migration"):
        _prepare(home, source)

    assert not (home / "state_5.sqlite").exists()


def test_stale_target_with_unsupported_migration_is_preserved(tmp_path):
    import app.backend_codex as module

    source = tmp_path / "source.sqlite"
    _state_db(source)
    migrations = list(
        module._CODEX_STATE_MIGRATIONS_BY_CLI[SEED_CLI_VERSION]
    )
    migrations.append((migrations[-1][0] + 1, b"unsupported-migration"))
    home = tmp_path / "managed"
    home.mkdir()
    target = home / "state_5.sqlite"
    _state_db(
        target,
        status="running",
        last_success_at=None,
        migrations=tuple(migrations),
        threads=("stale-thread",),
    )

    with pytest.raises(RuntimeError, match="unsupported Codex state migration"):
        _prepare(home, source)

    assert _thread_ids(target) == ["stale-thread"]
    assert not list(home.glob("state-recovery-*"))


def test_failed_install_rolls_stale_state_back(monkeypatch, tmp_path):
    import app.backend_codex as module

    source = tmp_path / "source.sqlite"
    _state_db(source, threads=("healthy-thread",))
    home = tmp_path / "managed"
    home.mkdir()
    target = home / "state_5.sqlite"
    _state_db(
        target,
        status="running",
        last_success_at=None,
        threads=("stale-thread",),
    )
    real_replace = module.os.replace

    def fail_seed_install(src, dst):
        if Path(dst) == target and Path(src).name.startswith(".state_5.seed-"):
            raise OSError("injected install failure")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", fail_seed_install)

    with pytest.raises(OSError, match="injected install failure"):
        _prepare(home, source)

    assert _thread_ids(target) == ["stale-thread"]
    assert not list(home.glob(".state_5.seed-*"))


def test_source_selection_prefers_fullest_healthy_matching_index(monkeypatch, tmp_path):
    import app.backend_codex as module

    base = tmp_path / "base"
    base.mkdir()
    _state_db(base / "state_5.sqlite", threads=("base",))
    root = tmp_path / "managed-root"
    fullest = root / "fullest"
    fullest.mkdir(parents=True)
    _state_db(
        fullest / "state_5.sqlite",
        threads=("one", "two", "three"),
    )
    corrupt = root / "corrupt"
    corrupt.mkdir()
    (corrupt / "state_5.sqlite").write_bytes(b"not sqlite")
    monkeypatch.setattr(module, "_CODEX_HOME_ROOT", root)
    monkeypatch.setattr(module, "_base_codex_home", lambda: base)

    selected = module._select_managed_codex_state_source(
        root / "new-home",
        SEED_CLI_VERSION,
    )

    assert selected == fullest / "state_5.sqlite"


def test_source_selection_uses_valid_managed_state_when_base_is_corrupt(
    monkeypatch, tmp_path,
):
    import app.backend_codex as module

    base = tmp_path / "base"
    base.mkdir()
    (base / "state_5.sqlite").write_bytes(b"not sqlite")
    root = tmp_path / "managed-root"
    healthy = root / "healthy"
    healthy.mkdir(parents=True)
    _state_db(healthy / "state_5.sqlite")
    monkeypatch.setattr(module, "_CODEX_HOME_ROOT", root)
    monkeypatch.setattr(module, "_base_codex_home", lambda: base)

    selected = module._select_managed_codex_state_source(
        root / "new-home",
        SEED_CLI_VERSION,
    )

    assert selected == healthy / "state_5.sqlite"


@pytest.mark.asyncio
async def test_managed_home_lock_serializes_another_process(tmp_path):
    import app.backend_codex as module

    home = tmp_path / "managed-root" / "same-home"
    acquired = tmp_path / "child-acquired"
    script = """
import asyncio
import sys
from pathlib import Path
from app.backend_codex import _managed_home_lock

async def main():
    print("READY", flush=True)
    async with _managed_home_lock(Path(sys.argv[1])):
        Path(sys.argv[2]).write_text("acquired")

asyncio.run(main())
"""
    process = None
    try:
        async with module._managed_home_lock(home):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                script,
                str(home),
                str(acquired),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path(__file__).parents[1]),
            )
            assert await asyncio.wait_for(process.stdout.readline(), timeout=5) == b"READY\n"
            await asyncio.sleep(0.05)
            assert not acquired.exists()
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        assert process.returncode == 0, (stdout, stderr)
        assert acquired.read_text() == "acquired"
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()


@pytest.mark.asyncio
async def test_same_managed_home_connect_is_single_flight_and_repeatable(
    monkeypatch, tmp_path,
):
    import app.backend_codex as module

    root = tmp_path / "managed-root"
    base = tmp_path / "base"
    base.mkdir()
    monkeypatch.setattr(module, "_CODEX_HOME_ROOT", root)
    monkeypatch.setattr(module, "_base_codex_home", lambda: base)
    session_id = "same-managed-home"
    home = root / session_id
    home.mkdir(parents=True)
    _state_db(home / "state_5.sqlite")
    active = 0
    max_active = 0

    async def connect_unlocked(_self):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0)
        finally:
            active -= 1

    monkeypatch.setattr(module.CodexBackend, "_connect_unlocked", connect_unlocked)
    monkeypatch.setattr(
        module.CodexBackend,
        "_managed_state_cli_version",
        lambda _self: asyncio.sleep(0, result=SEED_CLI_VERSION),
    )

    for _ in range(10):
        backends = [
            module.CodexBackend(
                model="gpt-5.6-sol",
                cwd=str(tmp_path),
                mcp_servers={"orchestra": {
                    "command": "python",
                    "env": {"ORCHESTRA_SESSION_ID": session_id},
                }},
            )
            for _ in range(2)
        ]
        await asyncio.gather(*(backend.connect() for backend in backends))

    assert max_active == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cli_version", [CODEX_CLI_HISTORY_VERSION, "999.0.0", "probe_error", SEED_CLI_VERSION])
async def test_newer_cli_defers_managed_state_migration_to_provider(
    monkeypatch, tmp_path, cli_version,
):
    import app.backend_codex as module

    root = tmp_path / "managed-root"
    session_id = "newer-cli-home"
    home = root / session_id
    home.mkdir(parents=True)
    migrations = module._CODEX_STATE_MIGRATIONS_BY_CLI[SEED_CLI_VERSION] + ((52, b"new-provider-migration"),)
    _state_db(home / "state_5.sqlite", migrations=migrations)
    original = (home / "state_5.sqlite").read_bytes()
    connected = 0

    def prepare_home(_self):
        home.mkdir(parents=True)
        return home

    async def connect_unlocked(_self):
        nonlocal connected
        connected += 1

    def unexpected_seed_check(*_args):
        if cli_version in module._CODEX_STATE_MIGRATIONS_BY_CLI:
            raise RuntimeError("unsupported newer schema; no writes attempted")
        pytest.fail("an unvalidated CLI state must be migrated by Codex itself")

    async def version(_self):
        if cli_version == "probe_error":
            raise RuntimeError("version probe failed")
        return cli_version

    monkeypatch.setattr(module, "_CODEX_HOME_ROOT", root)
    monkeypatch.setattr(module.CodexBackend, "_prepare_codex_home", prepare_home)
    monkeypatch.setattr(
        module.CodexBackend,
        "_refresh_managed_config_sha256",
        lambda _self: "newer-cli-config",
    )
    monkeypatch.setattr(module.CodexBackend, "_connect_unlocked", connect_unlocked)
    monkeypatch.setattr(
        module.CodexBackend,
        "_managed_state_cli_version",
        version,
    )
    monkeypatch.setattr(
        module,
        "_managed_codex_state_needs_seed",
        unexpected_seed_check,
    )
    backend = module.CodexBackend(
        model="gpt-5.6-sol",
        cwd=str(tmp_path),
        mcp_servers={"orchestra": {
            "command": "python",
            "env": {"ORCHESTRA_SESSION_ID": session_id},
        }},
    )

    await backend.connect()

    assert connected == 1
    assert (home / "state_5.sqlite").read_bytes() == original


@pytest.mark.asyncio
async def test_cancelled_managed_home_connect_releases_single_flight_waiter(
    monkeypatch, tmp_path,
):
    import app.backend_codex as module

    root = tmp_path / "managed-root"
    base = tmp_path / "base"
    base.mkdir()
    monkeypatch.setattr(module, "_CODEX_HOME_ROOT", root)
    monkeypatch.setattr(module, "_base_codex_home", lambda: base)
    session_id = "cancelled-managed-home"
    home = root / session_id
    home.mkdir(parents=True)
    _state_db(home / "state_5.sqlite")
    first_started = asyncio.Event()
    never = asyncio.Event()
    calls = 0
    active = 0
    max_active = 0

    async def connect_unlocked(_self):
        nonlocal calls, active, max_active
        calls += 1
        active += 1
        max_active = max(max_active, active)
        try:
            if calls == 1:
                first_started.set()
                await never.wait()
        finally:
            active -= 1

    monkeypatch.setattr(module.CodexBackend, "_connect_unlocked", connect_unlocked)
    monkeypatch.setattr(
        module.CodexBackend,
        "_managed_state_cli_version",
        lambda _self: asyncio.sleep(0, result=SEED_CLI_VERSION),
    )

    def backend():
        return module.CodexBackend(
            model="gpt-5.6-sol",
            cwd=str(tmp_path),
            mcp_servers={"orchestra": {
                "command": "python",
                "env": {"ORCHESTRA_SESSION_ID": session_id},
            }},
        )

    owner = asyncio.create_task(backend().connect())
    await first_started.wait()
    waiter = asyncio.create_task(backend().connect())
    await asyncio.sleep(0)
    owner.cancel()
    await asyncio.gather(owner, return_exceptions=True)
    await asyncio.wait_for(waiter, timeout=1)

    assert calls == 2
    assert max_active == 1
