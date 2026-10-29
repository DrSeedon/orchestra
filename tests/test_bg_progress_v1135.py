"""V-1135: durable progress samples of long `run` jobs, without waking the model per sample."""
import asyncio
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import bg_progress as bp


def _ing(prev, raw, now, **kw):
    return bp.ingest(prev, raw, "raw", "command", 5, now=now)


# ── pure sample logic ─────────────────────────────────────────────────────────

def test_percent_comes_only_from_completed_over_total():
    rec = _ing(None, {"completed": 30, "total": 120, "unit": "MB"}, 100)
    assert rec["sample"]["percent"] == 25.0
    no_total = _ing(None, {"completed": 30, "unit": "MB"}, 100)
    assert no_total["sample"]["percent"] is None
    assert no_total["sample"]["total"] is None
    only_pct = _ing(None, {"percent": 41.5}, 100)
    assert (only_pct["sample"]["completed"], only_pct["sample"]["total"]) == (41.5, 100.0)
    assert only_pct["sample"]["unit"] == "%"


def test_overshoot_is_clamped_and_garbage_numbers_are_dropped():
    over = _ing(None, {"completed": 150, "total": 100}, 100)["sample"]
    assert over["completed"] == 100 and over["percent"] == 100.0
    junk = _ing(None, {"completed": 5, "total": 0, "rate": -3, "eta_seconds": float("nan")}, 100)["sample"]
    assert junk["total"] is None and junk["percent"] is None
    assert junk["rate"] is None and junk["eta_seconds"] is None
    for bad in ({"completed": -1}, {"completed": True}, {"completed": "5"},
                {"completed": float("inf")}, {}, {"unrelated": 1}):
        with pytest.raises(ValueError):
            _ing(None, bad, 100)
    with pytest.raises(ValueError):
        bp.normalize([1])


def test_text_fields_are_bounded_and_flattened():
    sample = _ing(None, {"label": "a\n" + "x" * 500, "unit": "u" * 99, "completed": 1}, 1)["sample"]
    assert len(sample["label"]) == bp.MAX_LABEL and "\n" not in sample["label"]
    assert len(sample["unit"]) == bp.MAX_UNIT
    assert _ing(None, {"completed": 1, "status": "bogus"}, 1)["sample"]["status"] == "unknown"


def test_eta_needs_enough_observations_and_is_estimated():
    rec = _ing(None, {"completed": 0, "total": 100}, 100)
    assert rec["sample"]["eta_seconds"] is None            # one point: unknown, not invented
    rec = _ing(rec, {"completed": 10, "total": 100}, 105)
    assert rec["sample"]["eta_seconds"] is None            # two points: rate only
    assert rec["sample"]["rate"] == 2.0 and rec["sample"]["rate_source"] == "estimated"
    rec = _ing(rec, {"completed": 20, "total": 100}, 110)
    assert rec["sample"]["eta_seconds"] == 40 and rec["sample"]["eta_source"] == "estimated"


def test_reported_eta_and_rate_win_but_only_while_running():
    rec = _ing(None, {"completed": 1, "total": 9, "rate": 2, "eta_seconds": 77}, 1)["sample"]
    assert (rec["rate"], rec["rate_source"], rec["eta_seconds"], rec["eta_source"]) == (2, "reported", 77, "reported")
    paused = _ing(None, {"completed": 1, "total": 9, "eta_seconds": 77, "status": "paused"}, 1)["sample"]
    assert paused["eta_seconds"] is None
    huge = _ing(None, {"completed": 1, "total": 9, "eta_seconds": 1e12}, 1)["sample"]
    assert huge["eta_seconds"] is None


def test_rewind_resets_history_and_drops_the_estimate():
    rec = None
    for i, now in enumerate((100, 105, 110, 115)):
        rec = _ing(rec, {"completed": i * 10, "total": 100}, now)
    assert rec["sample"]["eta_seconds"] is not None
    rec = _ing(rec, {"completed": 5, "total": 100}, 120)
    assert rec["resets"] == 1 and rec["sample"]["reset"] is True
    assert rec["sample"]["eta_seconds"] is None and len(rec["history"]) == 1


def test_stalled_counter_gives_no_rate_and_no_eta_but_keeps_moved_at():
    rec = None
    for now in (100, 105, 110, 115):
        rec = _ing(rec, {"completed": 50, "total": 100}, now)
    assert rec["sample"]["rate"] is None and rec["sample"]["eta_seconds"] is None
    assert rec["moved_at"] == bp._iso(100)


def test_clock_going_backwards_never_breaks_history():
    rec = _ing(None, {"completed": 1, "total": 10}, 100)
    rec = _ing(rec, {"completed": 2, "total": 10}, 90)
    assert len(rec["history"]) == 1
    assert rec["sample"]["rate"] is None or math.isfinite(rec["sample"]["rate"])


def test_history_is_bounded():
    rec = None
    for i in range(60):
        rec = _ing(rec, {"completed": i, "total": 1000}, 100 + i * 5)
    assert len(rec["history"]) == bp.HISTORY_POINTS


def test_parse_text_takes_last_object_line_and_ignores_noise():
    text = "\n".join([
        'ORCHESTRA_PROGRESS {"completed": 1}', "downloading...", "{broken",
        '{"completed": 2, "total": 4}', "50% done", "[1,2]",
    ])
    data, raw = bp.parse_text(text)
    assert data == {"completed": 2, "total": 4} and raw.startswith("{")
    prefixed, _ = bp.parse_text('x\nORCHESTRA_PROGRESS {"percent": 5}\n')
    assert prefixed == {"percent": 5}
    assert bp.parse_text("45%\n[#### ] 20%\n") is None            # no guessing from prose
    assert bp.parse_text("") is None
    big = "noise\n" * 100000 + '{"completed": 3}\n'
    assert bp.parse_text(big)[0] == {"completed": 3}


def test_mark_error_keeps_last_good_sample():
    good = _ing(None, {"completed": 3, "total": 4}, 10)
    bad = bp.mark_error(good, "x" * 400, "command", 5, now=20)
    assert bad["sample"] == good["sample"] and len(bad["error"]) == bp.MAX_ERROR
    assert bad["errors"] == 1
    again = bp.mark_error(bad, "timeout", "command", 5, now=30)
    assert again["errors"] == 2
    fresh = _ing(again, {"completed": 4, "total": 4}, 40)
    assert fresh["error"] == "" and fresh["errors"] == 0
    assert bp.mark_error(None, "no line", "output", 5)["errors"] == 1


def test_validate_config():
    assert bp.validate_config({"mode": "output"}) is None
    assert bp.validate_config({"mode": "command", "command": "echo", "interval_seconds": 5}) is None
    for bad in ("x", {"mode": "nope"}, {"mode": "command"}, {"mode": "command", "command": " "},
                {"mode": "command", "command": "x" * 3000},
                {"mode": "output", "interval_seconds": 1}, {"mode": "output", "interval_seconds": True},
                {"mode": "output", "interval_seconds": float("nan")},
                {"mode": "output", "interval_seconds": 99999}):
        assert bp.validate_config(bad), bad


def test_summary_line():
    rec = _ing(None, {"completed": 5, "total": 10, "unit": "MB", "eta_seconds": 30}, 1)
    assert bp.summary({"_progress": rec}) == "50% · 5/10 MB · ETA ~30s"
    assert bp.summary({}) == ""


# ── manager integration (local synthetic commands only) ───────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "test.db")
    from app.db import init_db
    init_db()


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(bp, "MIN_INTERVAL", 0.05)


@pytest.fixture
def target(db):
    from app.db import save_session
    save_session({
        "id": "s-1", "name": "w1", "scope": "/s", "cwd": "/s", "model": "claude-opus-5-5[1m]",
        "system_prompt": "", "status": "idle", "session_id": None, "cost_usd": 0,
        "worktree_path": "", "branch": "", "is_orchestrator": False, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
    })
    sess = MagicMock(id="s-1", scope="/s", task_id="", branch="", needs_switch=False)
    sess.name = "w1"
    sess.send = AsyncMock()
    manager = MagicMock()
    manager.ensure_loaded_by_id = AsyncMock(return_value=sess)
    manager.ensure_loaded = AsyncMock(return_value=sess)
    manager.ensure_loaded_any = AsyncMock(return_value=sess)
    sent = []

    async def deliver(_sid, message, *, provenance):
        sent.append(message)

    manager.send = AsyncMock(side_effect=deliver)
    return manager, sent


def _progress_of(job_id):
    from app.db import bg_get_job
    return json.loads(bg_get_job(job_id)["config"]).get("_progress")


async def _wait_for(predicate, seconds=10):
    for _ in range(int(seconds / 0.05)):
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached")


@pytest.mark.asyncio
async def test_output_progress_updates_durably_and_wakes_only_on_completion(db, fast, target):
    from app.bg_jobs import BgJobManager
    from app.db import bg_get_job
    manager, sent = target
    mgr = BgJobManager()
    mgr.set_session_manager(manager)
    script = (
        "i=0; while [ $i -le 40 ]; do "
        "echo \"ORCHESTRA_PROGRESS {\\\"completed\\\": $((i*10)), \\\"total\\\": 400, \\\"unit\\\": \\\"MB\\\", \\\"label\\\": \\\"fetch\\\"}\"; "
        "i=$((i+1)); sleep 0.1; done"
    )
    created = await mgr.create(
        "run", {"command": script, "progress": {"mode": "output", "interval_seconds": 0.1}},
        "synthetic", "s-1", "w1", "/s", "w1", timeout_seconds=60,
    )
    job_id = created["id"]
    mid = await _wait_for(lambda: (p := _progress_of(job_id)) and p["sample"]["completed"] and p)
    assert mid["sample"]["unit"] == "MB" and 0 < mid["sample"]["percent"] <= 100
    assert bg_get_job(job_id)["status"] == "active"
    assert sent == []                                           # no wake while sampling
    await _wait_for(lambda: bg_get_job(job_id)["status"] == "triggered", 20)
    assert len(sent) == 1                                       # one terminal wake
    final = _progress_of(job_id)
    assert final["sample"]["completed"] == 400 and final["sample"]["percent"] == 100.0


@pytest.mark.asyncio
async def test_command_sampler_reports_and_failures_are_honest(db, fast, target, tmp_path):
    from app.bg_jobs import BgJobManager
    from app.db import bg_get_job
    manager, sent = target
    mgr = BgJobManager()
    mgr.set_session_manager(manager)
    state = tmp_path / "state"
    state.write_text("12")
    created = await mgr.create(
        "run",
        {"command": "sleep 3",
         "progress": {"mode": "command", "interval_seconds": 0.1,
                      "command": f"printf '{{\"completed\": %s, \"total\": 48, \"unit\": \"files\"}}\\n' $(cat {state})"}},
        "synthetic", "s-1", "w1", "/s", "w1", timeout_seconds=60,
    )
    job_id = created["id"]
    ok = await _wait_for(lambda: _progress_of(job_id))
    assert ok["sample"]["percent"] == 25.0 and ok["error"] == ""
    state.write_text("garbage")                                  # sampler now prints junk
    bad = await _wait_for(lambda: (p := _progress_of(job_id)) and p["error"] and p)
    assert bad["sample"]["percent"] == 25.0                     # last good value kept, error shown
    assert bad["errors"] >= 1
    await _wait_for(lambda: bg_get_job(job_id)["status"] == "triggered", 20)
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_sampler_has_a_time_limit_and_does_not_hang_the_job(db, fast, target, monkeypatch):
    from app.bg_jobs import BgJobManager
    from app.db import bg_get_job
    monkeypatch.setattr(bp, "SAMPLER_TIMEOUT", 0.3)
    manager, sent = target
    mgr = BgJobManager()
    mgr.set_session_manager(manager)
    created = await mgr.create(
        "run", {"command": "sleep 1.5",
                "progress": {"mode": "command", "command": "sleep 30", "interval_seconds": 0.1}},
        "synthetic", "s-1", "w1", "/s", "w1", timeout_seconds=60,
    )
    job_id = created["id"]
    rec = await _wait_for(lambda: (p := _progress_of(job_id)) and p["error"] and p)
    assert "timed out" in rec["error"]
    await _wait_for(lambda: bg_get_job(job_id)["status"] == "triggered", 20)


@pytest.mark.asyncio
async def test_cancel_stops_sampling_and_nothing_resurrects_the_record(db, fast, target, tmp_path):
    from app.bg_jobs import BgJobManager
    from app.db import bg_get_job, bg_record_progress
    manager, _sent = target
    mgr = BgJobManager()
    mgr.set_session_manager(manager)
    marker = tmp_path / "ticks"
    created = await mgr.create(
        "run", {"command": "sleep 60",
                "progress": {"mode": "command", "interval_seconds": 0.1,
                             "command": f"echo x >> {marker}; echo '{{\"completed\":1,\"total\":2}}'"}},
        "synthetic", "s-1", "w1", "/s", "w1", timeout_seconds=120,
    )
    job_id = created["id"]
    await _wait_for(lambda: _progress_of(job_id))
    await mgr.cancel(job_id)
    assert bg_get_job(job_id)["status"] == "cancelled"
    before = marker.read_text().count("x")
    await asyncio.sleep(0.5)
    assert marker.read_text().count("x") == before
    assert bg_record_progress(job_id, {"v": 1}) is False


@pytest.mark.asyncio
async def test_adopted_run_resumes_sampling_from_the_stored_record(db, fast, target, tmp_path):
    from app.bg_jobs import BgJobManager, _process_start_ticks
    from app.db import bg_get_job, bg_save_job
    manager, sent = target
    out, rc = tmp_path / "out", tmp_path / "rc"
    out.write_text('{"completed": 7, "total": 14, "unit": "GB"}\n')
    child = subprocess.Popen(["sleep", "1.2"])
    process = {"out": str(out), "rc": str(rc), "pid": child.pid, "start": _process_start_ticks(child.pid)}
    previous = bp.ingest(None, {"completed": 3, "total": 14, "unit": "GB"}, "r", "output", 5)
    config = {"command": "x", "progress": {"mode": "output", "interval_seconds": 0.1},
              "_process": process, "_progress": previous}
    now = datetime.now(timezone.utc).isoformat()
    bg_save_job({
        "id": "bg-adopt", "type": "run", "config": json.dumps(config), "message": "m",
        "target_session_id": "s-1", "target_name": "w1", "target_scope": "/s",
        "created_by_name": "w1", "status": "active", "expires_at": "2099-01-01T00:00:00+00:00",
        "trigger_at": None, "created_at": now, "last_output": "",
    })
    mgr = BgJobManager()
    mgr.set_session_manager(manager)
    mgr._start_task("bg-adopt", "run", config, "m", "s-1", "w1", "/s", 60)
    rec = await _wait_for(lambda: (p := _progress_of("bg-adopt")) and p["sample"]["completed"] == 7 and p)
    assert len(rec["history"]) >= 2                              # continued, not restarted
    rc.write_text("0\n")
    child.wait()
    await _wait_for(lambda: bg_get_job("bg-adopt")["status"] == "triggered", 20)
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_create_validation_and_caller_cannot_forge_a_record(db, target):
    from app.bg_jobs import BgJobManager
    from app.db import bg_get_job
    manager, _sent = target
    mgr = BgJobManager()
    mgr.set_session_manager(manager)
    args = ("m", "s-1", "w1", "/s", "w1")
    bad = await mgr.create("run", {"command": "true", "progress": {"mode": "command"}}, *args)
    assert "progress.command" in bad["error"]
    other = await mgr.create("timer", {"delay_seconds": 5, "progress": {"mode": "output"}}, *args)
    assert "only for run" in other["error"]
    forged = await mgr.create(
        "run", {"command": "sleep 5", "_progress": {"sample": {"percent": 99}}}, *args, timeout_seconds=30,
    )
    assert "_progress" not in json.loads(bg_get_job(forged["id"])["config"])
    await mgr.cancel(forged["id"])


# ── MCP surface ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_output_reread_and_log_noise_do_not_invent_new_observations(db, tmp_path, monkeypatch):
    from app.bg_jobs import BgJobManager
    from app.db import bg_save_job
    now = datetime.now(timezone.utc).isoformat()
    config = {"command": "unused", "progress": {"mode": "output"}}
    bg_save_job({
        "id": "bg-freshness", "type": "run", "config": json.dumps(config), "message": "m",
        "target_session_id": "s-1", "target_name": "w1", "target_scope": "/s",
        "created_by_name": "w1", "status": "active", "expires_at": "2099-01-01T00:00:00+00:00",
        "trigger_at": None, "created_at": now, "last_output": "",
    })
    output = tmp_path / 'out'
    line = '{"completed": 5, "total": 10}\n'
    output.write_text(line)
    mgr = BgJobManager()
    monkeypatch.setattr(bp.time, 'time', lambda: 100.0)
    await mgr._sample_progress_once('bg-freshness', config['progress'], output, None, None, False)
    first = _progress_of('bg-freshness')
    monkeypatch.setattr(bp.time, 'time', lambda: 200.0)
    await mgr._sample_progress_once('bg-freshness', config['progress'], output, None, None, False)
    assert _progress_of('bg-freshness') == first
    output.write_text(line + 'ordinary log noise\n')
    await mgr._sample_progress_once('bg-freshness', config['progress'], output, None, None, False)
    assert _progress_of('bg-freshness') == first
    output.write_text(line + 'ordinary log noise\n' + line)
    await mgr._sample_progress_once('bg-freshness', config['progress'], output, None, None, False)
    second = _progress_of('bg-freshness')
    assert second['sample']['observed_at'] == bp._iso(200)
    assert len(second['history']) == 2
    # A new manager (adoption) must recognise the same durable source cursor.
    monkeypatch.setattr(bp.time, 'time', lambda: 300.0)
    await BgJobManager()._sample_progress_once('bg-freshness', config['progress'], output, None, None, False)
    assert _progress_of('bg-freshness') == second


@pytest.mark.asyncio
async def test_command_sampler_requires_complete_successful_bounded_output(monkeypatch):
    from app.bg_jobs import BgJobManager
    mgr = BgJobManager()
    text = await mgr._read_progress_command(
        {'command': "printf '{\"completed\":'; sleep 0.05; printf '5}\\n'"}, None, None, False,
    )
    assert bp.parse_text(text)[0]['completed'] == 5
    with pytest.raises(ValueError, match='exit'):
        await mgr._read_progress_command(
            {'command': "printf '{\"completed\":5}\\n'; exit 7"}, None, None, False,
        )
    monkeypatch.setattr(bp, 'SAMPLER_READ_LIMIT', 32)
    with pytest.raises(ValueError, match='limit'):
        await mgr._read_progress_command(
            {'command': "printf '%080d' 1"}, None, None, False,
        )


@pytest.mark.asyncio
async def test_sampler_timeout_includes_waiting_after_stdout_closes(monkeypatch):
    from app.bg_jobs import BgJobManager
    monkeypatch.setattr(bp, 'SAMPLER_TIMEOUT', 0.1)
    with pytest.raises(asyncio.TimeoutError):
        await BgJobManager()._read_progress_command(
            {'command': "printf '{\"completed\":5}\\n'; exec 1>&-; sleep 30"}, None, None, False,
        )

@pytest.mark.asyncio
async def test_bg_create_sends_progress_options_and_bg_list_shows_them(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/scope")
    monkeypatch.setattr(m, "WORKER_NAME", "w")
    captured = {}

    async def fake_api(method, path, **kwargs):
        captured.update(kwargs["json"])
        return {"id": "bg-1", "type": "run", "status": "active", "config": kwargs["json"]["config"]}

    with patch.object(m, "_api", side_effect=fake_api):
        await m.bg_create(type="run", command="sleep 1", progress_command="cat st",
                          progress_interval_seconds=10)
    assert captured["config"] == {"command": "sleep 1", "progress": {
        "mode": "command", "interval_seconds": 10, "command": "cat st"}}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.bg_create(type="run", command="sleep 1", progress_from_output=True)
    assert captured["config"]["progress"] == {"mode": "output", "interval_seconds": 5}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.bg_create(type="run", command="sleep 1")
    assert "progress" not in captured["config"]            # backwards compatible

    record = bp.ingest(None, {"completed": 5, "total": 10, "unit": "MB"}, "r", "output", 5)
    jobs = [{"id": "bg-1", "type": "run", "status": "active", "target_name": "w", "message": "",
             "config": json.dumps({"command": "x", "_progress": record})}]
    with patch.object(m, "_api", AsyncMock(return_value=jobs)):
        text = await m.bg_list()
    assert "📈 50% · 5/10 MB" in text
