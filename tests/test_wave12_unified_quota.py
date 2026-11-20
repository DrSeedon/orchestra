"""Wave 12 regressions: unified 2-chart QuotaPanel, idle Antigravity freshness/reset projection, and reset sawtooth fix."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import db, provider_safety, quota_gate
from app.routes import system
from tests.test_t344_quota_lines_browser import _bucket, _lane, _payload, _render, browser  # noqa: F401


def _agy_providers(now: float, *, weekly_util: float = 15.0, short_util: float = 20.4,
                   weekly_reset_offset: float = 400000.0, short_reset_offset: float = 10000.0):
    w_reset = datetime.fromtimestamp(now + weekly_reset_offset, timezone.utc).isoformat().replace("+00:00", "Z")
    s_reset = datetime.fromtimestamp(now + short_reset_offset, timezone.utc).isoformat().replace("+00:00", "Z")
    return system._provider_usage_snapshot(
        None, None, None,
        {
            "gemini-weekly": {"remaining_fraction": 1.0 - weekly_util / 100.0, "reset_time": w_reset},
            "gemini-argon-wtu-weekly": {"remaining_fraction": 0.99, "reset_time": w_reset},
            "3p-weekly": {"remaining_fraction": 1.0, "reset_time": w_reset},
        },
        {
            "gemini-5h": {"remaining_fraction": 1.0 - short_util / 100.0, "reset_time": s_reset},
            "3p-5h": {"remaining_fraction": 1.0, "reset_time": s_reset},
        },
    )


def test_idle_antigravity_stays_fresh_for_24h_and_rolls_expired_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w12.db")
    db.init_db()
    provider_safety.reset_provider_safety_state_for_tests()

    t0 = 1795152379.0  # e.g. last turn at 05:26Z
    monkeypatch.setattr(provider_safety.time, "time", lambda: t0)
    provider_safety.record_provider_activity("antigravity")
    provider_safety.record_provider_quota_observation("antigravity", t0)

    providers = _agy_providers(t0, weekly_util=15.0, short_util=20.4, short_reset_offset=10800.0)
    timestamps = {"antigravity_gemini": t0, "antigravity_argon": t0, "antigravity_3p": t0}
    act = {"antigravity_gemini": provider_safety.provider_activity_state("antigravity")}

    # 1. 45 minutes idle (< 24h, no turns after t0 + 60s): still FRESH, NOT unknown!
    t_45m = t0 + 2700.0
    d_45m = quota_gate.evaluate_worker_admission(
        "antigravity/gemini-4-neon-high", providers, timestamps,
        now=t_45m, activity_by_provider=act, _include_alternatives=False,
    )
    assert d_45m.state == "available"
    assert d_45m.utilization == pytest.approx(15.0)
    assert d_45m.reason_key != "observation_stale"

    # 2. 6 hours idle: 5h window (reset at t0 + 3h) has rolled into new window -> 0%, STILL fresh!
    t_6h = t0 + 6 * 3600.0
    d_5h = quota_gate.evaluate_worker_admission(
        "antigravity/gemini-4-neon-high", providers, timestamps,
        now=t_6h, activity_by_provider=act, _include_alternatives=False, _window="5h",
    )
    assert d_5h.state == "available"
    assert d_5h.utilization == 0.0
    assert d_5h.reset_at is not None
    assert quota_gate.parse_quota_timestamp(d_5h.reset_at) == pytest.approx(t0 + 10800.0 + 5 * 3600.0)

    # 3. Turns DID run after t0 + 60s without updating quota for > QUOTA_OBSERVATION_MAX_AGE -> becomes unknown/stale!
    t_run1 = t0 + 120.0
    monkeypatch.setattr(provider_safety.time, "time", lambda: t_run1)
    provider_safety.record_provider_activity("antigravity")
    act_active = {"antigravity_gemini": provider_safety.provider_activity_state("antigravity")}

    d_stale = quota_gate.evaluate_worker_admission(
        "antigravity/gemini-4-neon-high", providers, timestamps,
        now=t_run1 + quota_gate.QUOTA_OBSERVATION_MAX_AGE + 10.0,
        activity_by_provider=act_active, _include_alternatives=False,
    )
    assert d_stale.state == "unknown"
    assert d_stale.reason_key == "observation_stale"

    # 4. Over 24h old -> always unknown even if idle
    d_24h = quota_gate.evaluate_worker_admission(
        "antigravity/gemini-4-neon-high", providers, timestamps,
        now=t0 + quota_gate.ANTIGRAVITY_IDLE_MAX_AGE + 1.0,
        activity_by_provider=act, _include_alternatives=False,
    )
    assert d_24h.state == "unknown"


@pytest.mark.asyncio
async def test_usage_quota_map_reports_idle_antigravity_fresh_and_hydrates_after_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w12_map.db")
    db.init_db()
    provider_safety.reset_provider_safety_state_for_tests()
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(system, "is_provider_disabled", lambda _p: False)
    monkeypatch.setattr(system, "manager", SimpleNamespace(sessions={}))

    t0 = 1795152000.0
    monkeypatch.setattr(system.time, "time", lambda: t0)
    monkeypatch.setattr(provider_safety.time, "time", lambda: t0)
    w_reset = datetime.fromtimestamp(t0 + 5 * 86400, timezone.utc).isoformat().replace("+00:00", "Z")
    s_reset = datetime.fromtimestamp(t0 + 3600, timezone.utc).isoformat().replace("+00:00", "Z")
    weekly = {"gemini-weekly": {"remaining_fraction": 0.49, "reset_time": w_reset},
              "gemini-argon-wtu-weekly": {"remaining_fraction": 0.99, "reset_time": w_reset},
              "3p-weekly": {"remaining_fraction": 1.0, "reset_time": w_reset}}
    short = {"gemini-5h": {"remaining_fraction": 0.79, "reset_time": s_reset},
             "3p-5h": {"remaining_fraction": 1.0, "reset_time": s_reset}}
    monkeypatch.setattr(system, "_antigravity_usage_cache", {"data": None, "five_hour": None, "ts": 0.0})
    system.publish_antigravity_quota(weekly, short, t0)

    # Simulate restart 4 hours later (> old 15m TTL, > 5h reset): hydrate_antigravity_quota recovers both!
    t_later = t0 + 4 * 3600.0
    monkeypatch.setattr(system.time, "time", lambda: t_later)
    monkeypatch.setattr(system, "_antigravity_usage_cache", {"data": None, "five_hour": None, "ts": 0.0})
    system.hydrate_antigravity_quota()

    payload = await system.build_quota_map()
    by_bucket = {b["bucket"]: b for b in payload["buckets"]}
    assert by_bucket["antigravity_gemini"]["fresh"] is True
    assert by_bucket["antigravity_gemini"]["window"]["utilization"] == pytest.approx(51.0)
    assert by_bucket["antigravity_gemini_5h"]["fresh"] is True
    assert by_bucket["antigravity_gemini_5h"]["window"]["utilization"] == 0.0
    assert by_bucket["antigravity_gemini_5h"]["lanes"][0]["release_status"] != "no_data"


def test_unified_panel_renders_2_svgs_and_breaks_cross_reset_diagonal_sawtooth(browser):
    payload = _payload()
    payload["generated_at"] = "2026-11-20T06:10:00+00:00"
    now_dt = datetime.fromisoformat(payload["generated_at"])

    # Verify cross-reset flat step-down geometry on a 7d pool (antigravity_gemini)
    t1 = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc).timestamp()
    reset1 = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc).timestamp()
    t2 = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc).timestamp()
    reset2 = datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc).timestamp()

    payload["rule"]["antigravity_default_hard_stop_pct"] = 95
    payload["rule"]["gated_lanes"].append("agy_gemini")
    b7 = _bucket("antigravity_gemini", "Gemini", 51.0, 0.29, [_lane("agy_gemini", "Gemini · 7d", True, False)], window_minutes=10080)
    b7["window"]["resets_at"] = datetime.fromtimestamp(reset2, timezone.utc).isoformat()
    b7["timeline"] = {"points": [
        {"ts": t1, "utilization": 64.0, "resets_at": reset1, "window_minutes": 10080},
        {"ts": t2, "utilization": 12.0, "resets_at": reset2, "window_minutes": 10080},
    ]}
    b5 = _bucket("antigravity_gemini_5h", "Gemini · 5h", 20.4, 0.43, [_lane("agy_gemini_5h", "Gemini · 5h", False, False)], window_minutes=300)
    payload["buckets"].extend([b7, b5])

    page, errors = _render(browser, payload, as_json=False)
    assert errors == []
    assert page.locator('[data-ql-panel]').count() == 1
    assert page.locator('svg.ql-chart').count() == 2
    # 5h pools are omitted from Wave 13 charts
    assert page.locator('[data-ql-timeline-history="antigravity_gemini_5h"]').count() == 0

    line = page.locator('[data-ql-timeline-history="antigravity_gemini"]')
    pts = [tuple(map(float, p.split(","))) for p in line.get_attribute("points").split()]
    assert len(pts) >= 4
    # Flat hold at 64%, vertical drop at reset1 to y(0)=426, horizontal 0% segment afterwards
    assert pts[0][1] == pytest.approx(pts[1][1])
    assert pts[1][0] == pytest.approx(pts[2][0])
    assert pts[2][1] == pytest.approx(426.0)
    page.close()


def test_deduplicated_codex_and_short_7d_labels_do_not_overlap(browser):
    payload = _payload()
    payload["buckets"] = [
        _bucket("codex", "Codex", 54.0, 0.84, [
            _lane("sol", "Sol", True, False),
            _lane("luna", "Luna", False, False),
        ]),
        _bucket("antigravity_gemini", "Gemini", 62.0, 0.29, [
            _lane("agy_gemini", "Gemini · 7d", True, True, "over limit"),
        ], window_minutes=10080),
        _bucket("antigravity_argon", "Argon", 1.0, 0.14, [
            _lane("agy_argon", "Argon · 7d", True, False),
        ], window_minutes=10080),
        _bucket("antigravity_3p", "Claude/3P", 0.0, 0.0, [
            _lane("agy_3p", "Claude/3P · 7d", True, False),
        ], window_minutes=10080),
        _bucket("antigravity_gemini_5h", "Gemini · 5h", 60.0, 0.48, [
            _lane("agy_gemini_5h", "Gemini · 5h", False, False),
        ], window_minutes=300),
    ]
    payload["rule"]["antigravity_default_hard_stop_pct"] = 95
    payload["rule"]["gated_lanes"] = ["sol", "agy_gemini", "agy_argon", "agy_3p"]

    page, errors = _render(browser, payload, as_json=False)
    assert errors == []

    # Consolidated Codex (no duplicate Luna) + no 5h + concise labels without ' · 7d'
    labels = page.locator('[data-ql-label]').evaluate_all("els => els.map(e => [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim())")
    assert labels == ["Claude/3P 0%", "Argon 1%", "Codex 54%", "Gemini 62%"]
    t_labels = page.locator('[data-ql-timeline-label]').evaluate_all("els => els.map(e => [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim())")
    assert t_labels == ["Claude/3P 0%", "Argon 1%", "Codex 54%", "Gemini 62%"]

    # Single-line 0% label has no detail row; active points have concise 'pace X%' only
    assert page.locator('[data-ql-detail="agy_3p"]').count() == 0
    assert page.locator('[data-ql-detail="agy_gemini"]').evaluate("e => [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim()") == "pace 29%"
    assert page.locator('[data-ql-trace-msg]').count() == 0
    assert page.locator('.ql-reasons').count() == 0
    assert page.locator('.ql-badges .ql-badge').count() == 5

    # All timeline point labels sit cleanly right of now with zero vertical overlap
    t_boxes = page.locator('[data-ql-timeline-label]').evaluate_all(
        "els => els.map(e => ({lane: e.dataset.qlTimelineLabel, anchor: e.getAttribute('text-anchor'), r: e.getBoundingClientRect()}))"
    )
    assert all(item["anchor"] == "start" for item in t_boxes)
    t_boxes.sort(key=lambda item: item["r"]["top"])
    for a, b in zip(t_boxes, t_boxes[1:]):
        assert a["r"]["bottom"] <= b["r"]["top"] + 0.5, (a, b)

    page.close()
