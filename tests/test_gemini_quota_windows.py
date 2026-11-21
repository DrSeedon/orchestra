import asyncio
from pathlib import Path
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


@pytest.mark.asyncio
async def test_quota_uses_print_cli_contract_and_isolates_with_active_acp(tmp_path, monkeypatch):
    import json
    import time
    from types import SimpleNamespace

    from app import antigravity_acp, models, provider_safety

    token = tmp_path / ".gemini/antigravity-acp/antigravity-oauth-token"
    token.parent.mkdir(parents=True)
    token.write_text("tok")
    link = tmp_path / agy.TOKEN_RELATIVE_PATH
    link.parent.mkdir()
    link.symlink_to(token)
    owner = SimpleNamespace(_start_lock=asyncio.Lock(), _check_settings=lambda: None,
                            process=SimpleNamespace(returncode=None))
    proc = SimpleNamespace(returncode=0, communicate=AsyncMock(
        return_value=(json.dumps(quota_response(time.time())).encode(), None)))
    launch = AsyncMock(return_value=proc)
    egress = AsyncMock()
    monkeypatch.setattr(agy, "canonical_profile", lambda: tmp_path)
    monkeypatch.setattr(antigravity_acp, "get_profile", lambda _: owner)
    monkeypatch.setattr(models, "is_provider_disabled", lambda _: False)
    monkeypatch.setattr(agy, "cli_environment", lambda h: {"HOME": str(h)})
    monkeypatch.setattr(agy.asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(provider_safety, "verify_provider_egress", egress)

    # Active ACP must probe using an isolated temporary home instead of returning None.
    weekly, short = await agy.probe_antigravity_quota()
    assert len(weekly) + len(short) == 5
    iso_cwd = Path(launch.call_args.kwargs["cwd"])
    assert iso_cwd != tmp_path
    assert iso_cwd.name.startswith("orch-agy-quota-")
    assert not iso_cwd.exists()  # cleaned up in finally
    assert launch.call_args.kwargs["env"] == {"HOME": str(iso_cwd)}
    assert launch.call_args.args == (
        agy._resolve_antigravity_bin({"HOME": str(iso_cwd)}),
        "--print",
        "/quota",
        "--output-format",
        "json",
    )

    owner.process = None
    weekly2, short2 = await agy.probe_antigravity_quota()
    assert len(weekly2) + len(short2) == 5
    assert launch.call_args.kwargs["cwd"] == str(tmp_path)
    assert launch.call_args.kwargs["env"] == {"HOME": str(tmp_path)}
    assert egress.await_count == 2


@pytest.mark.asyncio
async def test_quota_isolates_when_external_flock_held_and_resolves_bin(tmp_path, monkeypatch):
    import fcntl
    import json
    import os
    import stat
    import time
    from types import SimpleNamespace

    from app import antigravity_acp, models, provider_safety

    acp_dir = tmp_path / ".gemini/antigravity-acp"
    acp_dir.mkdir(parents=True)
    token = acp_dir / "antigravity-oauth-token"
    token.write_text(json.dumps({"access_token": "dummy"}))
    (acp_dir / "settings.json").write_text(json.dumps({"useG1Credits": False}))
    (tmp_path / ".gemini/oauth_creds.json").write_text(json.dumps({"refresh_token": "r"}))
    cfg_dir = tmp_path / ".gemini/config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({"userSettings": {"useAiCredits": False}}))
    link = tmp_path / agy.TOKEN_RELATIVE_PATH
    link.parent.mkdir(parents=True)
    link.symlink_to("../antigravity-acp/antigravity-oauth-token")

    # Simulate external acp_mux daemon holding exclusive flock on .orchestra-acp.lock.
    lock_fd = os.open(tmp_path / ".orchestra-acp.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    observed: dict = {}

    async def fake_exec(*args, **kwargs):
        cwd = Path(kwargs["cwd"])
        observed["args"] = args
        observed["cwd"] = cwd
        observed["mode"] = stat.S_IMODE(cwd.stat().st_mode)
        observed["has_lock"] = (cwd / ".orchestra-acp.lock").exists()
        observed["link_is_symlink"] = (cwd / agy.TOKEN_RELATIVE_PATH).is_symlink()
        observed["link_target_match"] = (
            (cwd / agy.TOKEN_RELATIVE_PATH).resolve()
            == (cwd / ".gemini/antigravity-acp/antigravity-oauth-token").resolve()
        )
        observed["oauth_creds"] = (cwd / ".gemini/oauth_creds.json").read_text()
        observed["settings"] = (cwd / ".gemini/antigravity-acp/settings.json").read_text()
        return SimpleNamespace(
            returncode=0,
            communicate=AsyncMock(return_value=(json.dumps(quota_response(time.time())).encode(), None)),
        )

    try:
        owner = SimpleNamespace(_start_lock=asyncio.Lock(), _check_settings=lambda: None, process=None)
        monkeypatch.setattr(agy, "canonical_profile", lambda: tmp_path)
        monkeypatch.setattr(antigravity_acp, "get_profile", lambda _: owner)
        monkeypatch.setattr(models, "is_provider_disabled", lambda _: False)
        monkeypatch.setattr(agy, "cli_environment", lambda h: {"HOME": str(h), "PATH": ""})
        monkeypatch.setattr(agy.asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(provider_safety, "verify_provider_egress", AsyncMock())

        weekly, short = await agy.probe_antigravity_quota()
        assert len(weekly) + len(short) == 5
        assert observed["cwd"] != tmp_path
        assert observed["cwd"].name.startswith("orch-agy-quota-")
        assert observed["mode"] == 0o700
        assert observed["has_lock"] is False
        assert observed["link_is_symlink"] is True
        assert observed["link_target_match"] is True
        assert "refresh_token" in observed["oauth_creds"]
        assert "useG1Credits" in observed["settings"]
        assert Path(observed["args"][0]).name == "agy"
        assert not observed["cwd"].exists()
    finally:
        os.close(lock_fd)


@pytest.mark.parametrize("model, bucket", [
    ("agy-neon", "antigravity_gemini"),
    ("agy-neon-low", "antigravity_gemini"),
    ("agy-neon-medium", "antigravity_gemini"),
    ("agy-neon-high", "antigravity_gemini"),
    ("agy-neon-orch", "antigravity_gemini"),
    ("antigravity/gemini-pro-orchestrator-g1-pro", "antigravity_argon"),
    ("antigravity/gemini-pro-orchestrator-argon", "antigravity_argon"),
])
def test_neon_and_argon_orchestrator_g1_quota_mapping(model, bucket):
    assert quota_gate.quota_bucket_for_model(model) == bucket


def test_neon_cost_and_fixed_orchestrator_effort():
    from app.models import get_model_spec, resolve_model
    from app.pipeline import resolve_effort

    for raw in agy.ANTIGRAVITY_NEON_RAW_MODELS:
        spec = get_model_spec("antigravity/" + raw)
        assert (spec.context_length, spec.price_input, spec.price_output) == (1_000_000, 3, 15)
        assert agy._antigravity_cost(raw, 1_000_000, 1_000_000, 1_000_000) == pytest.approx(18.15)
    assert resolve_effort({"default": "high"}, resolve_model("agy-neon-orch"), "antigravity") is None
    assert quota_gate.ANTIGRAVITY_ALTERNATIVES["antigravity_argon"][0] == resolve_model("agy-hydrogen")
