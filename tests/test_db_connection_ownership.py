"""Owned connections close on exit; borrowed transactions stay with their caller."""
import gc
import sqlite3
from pathlib import Path

import pytest

import app.db as db


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'owned.sqlite')
    db.init_db()


def test_owned_connection_commits_and_closes(database):
    with db._conn() as connection:
        connection.execute("INSERT INTO kv(key,value) VALUES('ownership','committed')")
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')
    assert db.kv_get('ownership') == 'committed'


def test_owned_connection_rolls_back_and_closes(database):
    with pytest.raises(ValueError, match='abort'):
        with db._conn() as connection:
            connection.execute("INSERT INTO kv(key,value) VALUES('ownership','bad')")
            raise ValueError('abort')
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')
    assert db.kv_get('ownership') == ''


def test_borrowed_session_write_does_not_commit_or_close_outer_transaction(database):
    with db._conn() as connection:
        connection.execute('BEGIN IMMEDIATE')
        db.save_session({'id':'borrowed', 'name':'borrowed', 'scope':'/test', 'cwd':'/tmp',
                         'model':'test', 'created_at':'2026-09-08T00:00:00Z',
                         'system_prompt':'', 'status':'idle', 'session_id':None,
                         'cost_usd':0, 'worktree_path':None, 'branch':None,
                         'is_orchestrator':False, 'color':'', 'finished_at':None},
                        _connection=connection)
        assert connection.in_transaction
        assert connection.execute("SELECT id FROM sessions WHERE id='borrowed'").fetchone()[0] == 'borrowed'
        connection.rollback()
    assert db.get_session('borrowed') is None


def test_reads_release_file_descriptors_without_gc(database):
    descriptors = Path('/proc/self/fd')
    if not descriptors.exists():
        pytest.skip('Linux descriptor observation')
    gc.collect()
    before = len(list(descriptors.iterdir()))
    gc.disable()
    try:
        for _ in range(24):
            assert db.kv_get('missing') == ''
        assert len(list(descriptors.iterdir())) <= before + 1
    finally:
        gc.enable()
        gc.collect()
