import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app import backend_antigravity as agy, db, quota_gate
from app.routes import system


def quota_response(now):
    groups = []
    for index, (_, label, weekly, short) in enumerate(agy.QUOTA_BUCKETS):
        windows = [(weekly, "weekly", 4 * 86400)]
        if label != "Argon":
            windows.append((short, "5h", 10800))
        groups.append({"name": label, "buckets": [
            {"id": key, "window": period, "remaining_fraction": 0.9 - index / 10,
             "reset_time": datetime.fromtimestamp(now + seconds, timezone.utc).isoformat()}
            for key, period, seconds in windows
        ]})
    return {"status": "SUCCESS", "command": {"data": {"groups": groups}}}


@pytest.mark.asyncio
async def test_five_windows_survive_one_probe_restart_hydration_and_graph(monkeypatch):
    import time

    db.init_db()
    now = time.time()
    raw = quota_response(now)
    sample = agy.normalize_antigravity_quota(raw), agy.normalize_antigravity_five_hour_quota(raw)
    fetch = AsyncMock(return_value=sample)
    monkeypatch.setattr(system, "_fetch_antigravity_usage", fetch)
    monkeypatch.setattr(system, "is_provider_disabled", lambda _: False)
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(system, "_antigravity_usage_cache", {"ts": 0})
    monkeypatch.setitem(system._quota_refresh_locks, "antigravity", asyncio.Lock())
    await asyncio.gather(*(system.refresh_antigravity_quota() for _ in range(8)))
    fetch.assert_awaited_once()
    observed = system._antigravity_usage_cache["ts"]
    saved = db.latest_usage_snapshot(tuple(group[0] for group in agy.QUOTA_BUCKETS), since=now - 1)
    assert saved[0] == pytest.approx(observed)
    assert sum(len(provider["windows"]) for provider in saved[1].values()) == 5
    monkeypatch.setattr(system, "_antigravity_usage_cache", {"ts": 0})
    system.hydrate_antigravity_quota()
    assert system._antigravity_usage_cache["ts"] == pytest.approx(observed)
    assert system._antigravity_usage_cache["data"] == sample[0]
    assert system._antigravity_usage_cache["five_hour"] == sample[1]
    history = system.usage_history_data()["rows"]
    assert sum(len(data["windows"]) for data in history[-1]["providers"].values()) == 5
    graph = await system.build_quota_map()
    pools = [bucket for bucket in graph["buckets"] if bucket["bucket"].startswith("antigravity_")]
    assert len(pools) == 5
    assert all(bucket["fresh"] and bucket["timeline"]["points"] for bucket in pools)
    assert {bucket["window"]["window_minutes"] for bucket in pools} == {300, 10080}
    assert all(bucket["lanes"][0]["headroom_pp"] is not None for bucket in pools)


def test_argon_has_own_weekly_line_and_short_stops_do_not_gate_by_diagonal():
    import time
    from dataclasses import replace

    now = time.time()
    raw = quota_response(now)
    weekly = agy.normalize_antigravity_quota(raw)
    short = agy.normalize_antigravity_five_hour_quota(raw)
    weekly["gemini-argon-wtu-weekly"]["remaining_fraction"] = 0.05
    short["gemini-5h"]["remaining_fraction"] = 0.01
    providers = system._provider_usage_snapshot(None, None, None, weekly, short)
    timestamps = dict.fromkeys(providers, now)
    policy = replace(quota_gate.quota_policy(), gated_lanes=frozenset(quota_gate.ANTIGRAVITY_LANES.values()))
    def decision(model):
        return quota_gate.evaluate_worker_admission(model, providers, timestamps, now=now, policy=policy)

    assert decision("agy-argon").lane == "agy_argon"
    assert decision("agy-argon").state == "blocked"
    assert decision("agy-hydrogen").reason_key == "hard_stop"
    assert decision("agy-opus").state == "available"
    short["gemini-5h"]["remaining_fraction"] = 0.1
    providers = system._provider_usage_snapshot(None, None, None, weekly, short)
    assert decision("agy-hydrogen").state == "available"
    timestamps["antigravity_gemini"] = now - agy.QUOTA_CACHE_TTL
    assert decision("agy-hydrogen").state == "unknown"
    assert decision("agy-hydrogen").allowed
