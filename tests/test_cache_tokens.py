"""Tests for raw cache-token storage + on-the-fly cost_cached recompute (#cost-tokens).

Root bug: cache_read/cache_create tokens were never accumulated, only baked-in
cost_usd_cached was stored → price change couldn't reprice history. Fix stores raw
tokens and recomputes cost_cached from current TOKEN_PRICES, falling back to stored
cached cost for old/no-cache/no-price rows.
"""

from datetime import datetime, timezone

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


def _session(**kw):
    base = {
        "id": "s1", "name": "w1", "scope": "/s", "cwd": "/s",
        "model": "claude-opus-5[1m]", "system_prompt": "", "status": "idle",
        "session_id": "sid", "cost_usd": 1.0, "worktree_path": "/s", "branch": "main",
        "is_orchestrator": False, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
    }
    base.update(kw)
    return base


class TestMigration:
    def test_columns_added_default_zero(self, db):
        from app.db import _conn
        with _conn() as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
        assert "total_cache_read_tokens" in cols
        assert "total_cache_create_tokens" in cols

    def test_migration_idempotent_drops_new_cols_simulating_old_db(self, db):
        """Simulate an OLD db by dropping the new columns, then re-run _migrate:
        columns come back additively, legacy row is untouched, re-run is idempotent."""
        import sqlite3
        from app.db import _conn, init_db, save_session, get_session
        save_session(_session(cost_usd_cached=0.42))
        # drop the two new columns to emulate a pre-migration schema (sqlite 3.35+)
        with _conn() as c:
            try:
                c.execute("ALTER TABLE sessions DROP COLUMN total_cache_read_tokens")
                c.execute("ALTER TABLE sessions DROP COLUMN total_cache_create_tokens")
            except sqlite3.OperationalError:
                pytest.skip("sqlite build without DROP COLUMN support")
        init_db()  # re-migrate
        init_db()  # twice → idempotent, no crash
        with _conn() as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
        assert "total_cache_read_tokens" in cols and "total_cache_create_tokens" in cols
        row = get_session("s1")
        assert row["total_cache_read_tokens"] == 0
        assert row["total_cache_create_tokens"] == 0
        assert row["cost_usd_cached"] == 0.42  # legacy data intact


class TestAccumulation:
    def test_cache_tokens_accumulate(self):
        from app.session_cost import CostTracker

        class S:
            session_id = "sid"
            cost_usd = cost_usd_cached = 0.0
            _last_cost = _last_cost_cached = 0.0
            _context_cost = _session_cost = _turn_cost = 0.0
            total_turns = 0
            total_input_tokens = total_output_tokens = 0
            total_cache_read_tokens = total_cache_create_tokens = 0
            _last_turn_ok = True
            _last_stop_reason = ""

        s = S()
        ct = CostTracker(s)
        for cr, cc in [(100, 10), (200, 0), (50, 5)]:
            ct.apply_turn_result({"session_id": "sid", "cache_read": cr, "cache_create": cc,
                                  "input_tokens": 1, "output_tokens": 1})
        assert s.total_cache_read_tokens == 350
        assert s.total_cache_create_tokens == 15

    def test_missing_cache_keys_no_crash(self):
        from app.session_cost import CostTracker

        class S:
            session_id = "sid"
            cost_usd = cost_usd_cached = 0.0
            _last_cost = _last_cost_cached = 0.0
            _context_cost = _session_cost = _turn_cost = 0.0
            total_turns = 0
            total_input_tokens = total_output_tokens = 0
            total_cache_read_tokens = total_cache_create_tokens = 0
            _last_turn_ok = True
            _last_stop_reason = ""

        s = S()
        # old-format turn: no cache_read/cache_create keys
        CostTracker(s).apply_turn_result({"session_id": "sid", "input_tokens": 5, "output_tokens": 3})
        assert s.total_cache_read_tokens == 0
        assert s.total_cache_create_tokens == 0


class TestPersistRestore:
    def test_round_trip(self, db):
        from app.db import save_session, get_session
        save_session(_session(total_input_tokens=1000, total_output_tokens=500,
                              total_cache_read_tokens=350, total_cache_create_tokens=15))
        row = get_session("s1")
        assert row["total_cache_read_tokens"] == 350
        assert row["total_cache_create_tokens"] == 15

    def test_legacy_dict_without_keys(self, db):
        from app.db import save_session, get_session
        save_session(_session())  # no cache keys → setdefault(0)
        row = get_session("s1")
        assert row["total_cache_read_tokens"] == 0
        assert row["total_cache_create_tokens"] == 0

    def test_hydrate_row_restores(self, db):
        from app.db import save_session, get_session
        from app.manager import SessionManager
        save_session(_session(total_cache_read_tokens=350, total_cache_create_tokens=15))
        s = SessionManager._hydrate_row(get_session("s1"))
        assert s.total_cache_read_tokens == 350
        assert s.total_cache_create_tokens == 15


class TestRecompute:
    def _row(self, **kw):
        base = dict(name="w", model="claude-opus-5[1m]", cost_usd=1.0, cost_usd_cached=0.0,
                    total_input_tokens=0, total_output_tokens=0,
                    total_cache_read_tokens=0, total_cache_create_tokens=0)
        base.update(kw)
        return base

    def test_new_row_recomputes_from_raw(self):
        from app.routes.system import _cost_cached_for
        from app.models import TOKEN_PRICES
        p = TOKEN_PRICES["claude-opus-5[1m]"]
        r = self._row(total_input_tokens=1000, total_output_tokens=500,
                      total_cache_read_tokens=2000, total_cache_create_tokens=100,
                      cost_usd_cached=999.0)  # stored is stale/wrong
        expected = (1000 * p["input"] + 2000 * p["input"] * 0.1
                    + 100 * p["input"] * 1.25 + 500 * p["output"]) / 1_000_000
        assert _cost_cached_for(r) == pytest.approx(expected)

    def test_price_change_reprices_history(self, monkeypatch):
        from app.routes.system import _cost_cached_for
        import app.models as models
        r = self._row(total_input_tokens=1000, total_output_tokens=500,
                      total_cache_read_tokens=2000, total_cache_create_tokens=100)
        before = _cost_cached_for(r)
        monkeypatch.setitem(models.TOKEN_PRICES, "claude-opus-5[1m]",
                            {"input": 15.0, "output": 75.0})
        after = _cost_cached_for(r)
        assert after > before  # raw tokens repriced under new prices

    def test_old_row_falls_back_to_stored(self):
        from app.routes.system import _cost_cached_for
        r = self._row(cost_usd_cached=0.42)  # no cache tokens
        assert _cost_cached_for(r) == 0.42

    def test_no_price_model_falls_back(self):
        from app.routes.system import _cost_cached_for
        # gpt-5.5 not in TOKEN_PRICES → must not KeyError, fallback to stored
        r = self._row(model="gpt-5.5", total_cache_read_tokens=5000, cost_usd_cached=1.23)
        assert _cost_cached_for(r) == 1.23
