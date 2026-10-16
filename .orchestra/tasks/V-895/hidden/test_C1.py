import asyncio, json
from datetime import datetime
import pytest

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
    from app.db import init_db
    init_db()

def _create(job_type, config, timeout):
    from app.bg_jobs import BgJobManager
    m = BgJobManager()
    m._start_task = lambda *a, **k: None
    return asyncio.run(m.create(job_type, config, "m", "s-1", "n", "/scope", "tester", timeout_seconds=timeout))

def test_long_timer_expiry_after_trigger(db):
    r = _create("timer", {"delay_seconds": 10 * 86400}, 3600)
    assert "error" not in r, r
    assert r["timeout_seconds"] == 10 * 86400 + 3600
    gap = (datetime.fromisoformat(r["expires_at"]) - datetime.fromisoformat(r["trigger_at"])).total_seconds()
    assert 3590 <= gap <= 3610

def test_very_long_timer(db):
    r = _create("timer", {"delay_seconds": 100 * 86400}, 3600)
    assert r["timeout_seconds"] == 100 * 86400 + 3600

def test_short_timer_clamped_to_max_timeout(db):
    r = _create("timer", {"delay_seconds": 60}, 5 * 86400)
    assert r["timeout_seconds"] == 86400

def test_short_timer_min_is_delay_plus_hour(db):
    r = _create("timer", {"delay_seconds": 60}, 10)
    assert r["timeout_seconds"] == 3660

def test_timer_cap_constant_removed():
    import app.bg_jobs as b
    assert not hasattr(b, "MAX_TIMER_TIMEOUT")

def test_other_types_clamped(db):
    r = _create("run", {"command": "true"}, 999999)
    assert "error" not in r, r
    assert r["timeout_seconds"] == 86400
