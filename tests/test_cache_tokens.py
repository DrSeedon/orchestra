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
        from app.models import MODELS, TOKEN_PRICES
        p = TOKEN_PRICES["claude-opus-5[1m]"]
        assert "claude-opus-5[1m]" not in MODELS
        r = self._row(total_input_tokens=1000, total_output_tokens=500,
                      total_cache_read_tokens=2000, total_cache_create_tokens=100,
                      cost_usd_cached=999.0)  # stored is stale/wrong
        expected = (1000 * p["input"]
                    + 2000 * p["input"] * p["cache_read_multiplier"]
                    + 100 * p["input"] * p["cache_write_1h_multiplier"]
                    + 500 * p["output"]) / 1_000_000
        assert _cost_cached_for(r) == pytest.approx(expected)

    def test_price_change_reprices_history(self, monkeypatch):
        from app.routes.system import _cost_cached_for
        import app.models as models
        r = self._row(total_input_tokens=1000, total_output_tokens=500,
                      total_cache_read_tokens=2000, total_cache_create_tokens=100)
        before = _cost_cached_for(r)
        monkeypatch.setitem(models.TOKEN_PRICES, "claude-opus-5[1m]",
                            {**models.TOKEN_PRICES["claude-opus-5[1m]"],
                             "input": 15.0, "output": 75.0})
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

    def test_dashboard_keeps_backend_haiku_request_price_for_aggregated_turn(self, db):
        from app.db import _conn, save_session, turn_usage_add
        from app.routes.system import _get_agents_cost

        save_session(_session(
            model="claude-haiku-5-5",
            cost_usd=1.0,
            cost_usd_cached=0.012242,
            total_input_tokens=120000,
            total_output_tokens=484,
            total_cache_read_tokens=0,
            total_cache_create_tokens=0,
        ))
        turn_usage_add(
            event_id="haiku-tier-turn",
            session_id="s1",
            runtime="claude",
            model="claude-haiku-5-5",
            ok=True,
            stop_reason="end_turn",
            cost_usd=0.123,
            input_tokens=120000,
            output_tokens=484,
            cache_read_tokens=0,
            cache_create_tokens=0,
        )

        result = _get_agents_cost()

        assert result["agents"][0]["cost_usd_cached"] == pytest.approx(0.0122)
        with _conn() as conn:
            persisted_cost = conn.execute(
                "SELECT cost_usd FROM turn_usage WHERE event_id='haiku-tier-turn'"
            ).fetchone()[0]
        assert persisted_cost == pytest.approx(0.123)
