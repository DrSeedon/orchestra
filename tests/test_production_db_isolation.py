import sqlite3

import pytest

from tests.conftest import _guard_sqlite_connect


def test_production_db_guard_is_autouse():
    from app import db

    assert sqlite3.connect._orchestra_production_db_guard == db._DEFAULT_DB_PATH.resolve()
    assert db.DB_PATH != db._DEFAULT_DB_PATH


def test_production_db_guard_rejects_before_connect(tmp_path):
    production_path = tmp_path / "data" / "orchestra.db"
    calls = []

    def connect(database, *args, **kwargs):
        calls.append(database)
        return "connected"

    guarded = _guard_sqlite_connect(connect, production_path)
    with pytest.raises(AssertionError, match="production database"):
        guarded(production_path)
    with pytest.raises(AssertionError, match="production database"):
        guarded(f"file:{production_path}?mode=ro", uri=True)
    with pytest.raises(AssertionError, match="production database"):
        guarded(f"file://localhost{production_path}?mode=ro", uri=True)
    assert calls == []

    test_path = tmp_path / "test.db"
    assert guarded(test_path) == "connected"
    assert calls == [test_path]
