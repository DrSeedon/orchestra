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
    now_ts = now_dt.timestamp()

    # Exact measured scenario: 64% before reset on 19.11, 13.5h overnight idle gap, 1.4% on 20.11
    t1 = datetime(2026, 11, 19, 15, 13, tzinfo=timezone.utc).timestamp()
    reset1 = datetime(2026, 11, 19, 19, 30, tzinfo=timezone.utc).timestamp()
    t2 = datetime(2026, 11, 20, 4, 41, tzinfo=timezone.utc).timestamp()
    reset2 = datetime(2026, 11, 20, 9, 4, tzinfo=timezone.utc).timestamp()

    payload["rule"]["antigravity_default_hard_stop_pct"] = 95
    payload["rule"]["gated_lanes"].append("agy_gemini")
    b7 = _bucket("antigravity_gemini", "Gemini", 51.0, 0.29, [_lane("agy_gemini", "Gemini · 7d", True, False)], window_minutes=10080)
    b7["window"]["resets_at"] = (now_dt + timedelta(days=5)).isoformat()
    b5 = _bucket("antigravity_gemini_5h", "Gemini · 5h", 20.4, 0.43, [_lane("agy_gemini_5h", "Gemini · 5h", False, False)], window_minutes=300)
    b5["window"]["resets_at"] = datetime.fromtimestamp(reset2, timezone.utc).isoformat()
    b5["timeline"] = {"points": [
        {"ts": t1, "utilization": 64.0, "resets_at": reset1, "window_minutes": 300},
        {"ts": t2, "utilization": 1.4, "resets_at": reset2, "window_minutes": 300},
    ]}
    payload["buckets"].extend([b7, b5])

    page, errors = _render(browser, payload, as_json=False)
    assert errors == []
    assert page.locator('[data-ql-panel]').count() == 1
    assert page.locator('svg.ql-chart').count() == 2

    line = page.locator('[data-ql-timeline-history="antigravity_gemini_5h"]')
    pts = [tuple(map(float, p.split(","))) for p in line.get_attribute("points").split()]
    # Expected SVG geometry:
    # 0: (t1, 64%), 1: (reset1, 64%), 2: (reset1, 0%), 3: (reset2 - 5h, 0%), 4: (t2, 1.4%), 5: (now, 20.4%)
    assert len(pts) >= 5
    # Verify flat 64% until reset1, vertical drop at reset1 to bottom y(0)=426, and flat 0% across night until winStart2!
    assert pts[0][1] == pytest.approx(pts[1][1])
    assert pts[1][0] == pytest.approx(pts[2][0])
    assert pts[2][1] == pytest.approx(426.0)
    assert pts[3][1] == pytest.approx(426.0)
    assert pts[3][0] > pts[2][0] + 40.0  # >8h overnight flat 0% segment on bottom axis
    page.close()


def test_equal_utilization_labels_do_not_overlap_and_timeline_labels_sit_right_of_now(browser):
    payload = _payload()
    payload["buckets"] = [
        _bucket("codex", "Codex (Sol)", 54.0, 0.84, [
            _lane("sol", "Sol", True, False),
            _lane("luna", "Luna", False, False),
        ]),
        _bucket("antigravity_gemini", "Gemini", 62.0, 0.29, [
            _lane("agy_gemini", "Gemini · 7d", True, False),
        ], window_minutes=10080),
        _bucket("antigravity_gemini_5h", "Gemini · 5h", 60.0, 0.48, [
            _lane("agy_gemini_5h", "Gemini · 5h", False, False),
        ], window_minutes=300),
    ]
    payload["rule"]["antigravity_default_hard_stop_pct"] = 95
    payload["rule"]["gated_lanes"] = ["sol", "agy_gemini"]

    page, errors = _render(browser, payload, as_json=False)
    assert errors == []

    # 1. All timeline point labels are cleanly right of `now` and do not overlap vertically.
    t_boxes = page.locator('[data-ql-timeline-label]').evaluate_all(
        "els => els.map(e => ({lane: e.dataset.qlTimelineLabel, anchor: e.getAttribute('text-anchor'), r: e.getBoundingClientRect()}))"
    )
    assert len(t_boxes) == 4
    assert all(item["anchor"] == "start" for item in t_boxes)
    t_boxes.sort(key=lambda item: item["r"]["top"])
    for a, b in zip(t_boxes, t_boxes[1:]):
        assert a["r"]["bottom"] <= b["r"]["top"] + 0.5, (a, b)

    # 2. Equal (progress, util) pairs (Luna 54% & Sol 54%) stay vertically separated.
    chart_groups = page.locator('[data-ql-label]').evaluate_all(
        """els => els.map(e => {
            const lane = e.dataset.qlLabel;
            const detail = document.querySelector(`[data-ql-detail="${lane}"]`);
            const r1 = e.getBoundingClientRect();
            const r2 = detail ? detail.getBoundingClientRect() : r1;
            return {
                lane,
                top: Math.min(r1.top, r2.top),
                bottom: Math.max(r1.bottom, r2.bottom),
                left: Math.min(r1.left, r2.left),
                right: Math.max(r1.right, r2.right),
            };
        })"""
    )
    assert len(chart_groups) == 4
    for i in range(len(chart_groups)):
        for j in range(i + 1, len(chart_groups)):
            a, b = chart_groups[i], chart_groups[j]
            h_overlap = min(a["right"], b["right"]) - max(a["left"], b["left"]) > 0
            v_overlap = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"]) > 0
            assert not (h_overlap and v_overlap), (a, b)

    page.close()
