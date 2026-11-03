from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts import disk_watch as watch

GIB = 1024 ** 3
TOTAL = 290 * GIB


def _args(tmp_path: Path, **extra) -> argparse.Namespace:
    values = dict(
        path="/", state=str(tmp_path / "disk_watch.json"),
        fallback_state=str(tmp_path / "shm" / "disk_watch.json"), thresholds=[85, 90, 95],
        top_dir=[], top_seconds=5, top_limit=5,
    )
    values.update(extra)
    return argparse.Namespace(**values)


def _disk(monkeypatch: pytest.MonkeyPatch, pct: int) -> None:
    used = TOTAL * pct // 100
    monkeypatch.setattr(watch, "measure", lambda _path: {
        "total": TOTAL, "used": used, "avail": TOTAL - used, "pct": pct,
    })


def _run(tmp_path, monkeypatch, pct, now, **extra):
    _disk(monkeypatch, pct)
    lines, state = watch.check(_args(tmp_path, **extra), now=now)
    return lines, state


def test_quiet_below_threshold_and_a_crossing_alerts_once_after_confirmation(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, 84, 1000)[0] == []
    # One sample above the threshold may be the nightly backup: not yet.
    lines, state = _run(tmp_path, monkeypatch, 88, 1600)
    assert lines == [] and state["level"] == "ok"
    lines, state = _run(tmp_path, monkeypatch, 88, 2200)
    assert len(lines) == 1 and lines[0].startswith("DISK_WATCH: уровень=warn (порог 85%), диск /:")
    assert state["level"] == "warn"
    assert _run(tmp_path, monkeypatch, 88, 2200 + 3600)[0] == []
    assert _run(tmp_path, monkeypatch, 89, 2200 + 86400)[0][0].startswith("DISK_WATCH: уровень=warn")


def test_backup_spike_seen_once_does_not_alert(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, 88, 0)
    _run(tmp_path, monkeypatch, 88, 600)  # warn confirmed and alerted
    assert _run(tmp_path, monkeypatch, 92, 1200)[0] == []  # backup temp files for minutes
    lines, state = _run(tmp_path, monkeypatch, 88, 1800)
    assert lines == [] and state["level"] == "warn"


def test_first_run_on_an_already_full_disk_alerts_on_the_second_check(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, 93, 0)[0] == []
    assert _run(tmp_path, monkeypatch, 93, 600)[0][0].startswith("DISK_WATCH: уровень=high")
    assert _run(tmp_path, monkeypatch, 93, 1200)[0] == []


def test_crit_alerts_immediately_and_repeats_hourly(tmp_path, monkeypatch):
    assert "уровень=crit" in _run(tmp_path, monkeypatch, 97, 0)[0][0]
    assert _run(tmp_path, monkeypatch, 97, 1800)[0] == []
    assert "уровень=crit" in _run(tmp_path, monkeypatch, 97, 3600)[0][0]


def test_hysteresis_and_lowered_and_recovered_messages(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, 97, 0)
    lines, state = _run(tmp_path, monkeypatch, 94, 60)
    assert lines == [] and state["level"] == "crit"  # 94 >= 95 - 2
    lines, state = _run(tmp_path, monkeypatch, 86, 120)
    assert state["level"] == "warn"
    assert lines == ["DISK_WATCH: уровень снизился до warn, диск /: занято 86%, свободно 40.6 ГБ из 290.0 ГБ"]
    assert _run(tmp_path, monkeypatch, 84, 180)[0] == []  # 84 >= 85 - 2
    lines, state = _run(tmp_path, monkeypatch, 82, 240)
    assert state["level"] == "ok"
    assert lines == ["DISK_WATCH: уровень=ok, диск /: занято 82%, свободно 52.2 ГБ из 290.0 ГБ: снова ниже 85%"]
    assert _run(tmp_path, monkeypatch, 82, 300)[0] == []


def test_alert_reports_daily_loss_and_time_to_full(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, 80, 0)
    _run(tmp_path, monkeypatch, 82, 12 * 3600)
    _run(tmp_path, monkeypatch, 86, 24 * 3600 - 600)
    lines, _ = _run(tmp_path, monkeypatch, 86, 24 * 3600)
    # 6 % of 290 GiB per day lost; 14 % left -> about 2.3 days.
    assert "за сутки свободного места меньше на 17.4 ГБ" in lines[0]
    assert "заполнится примерно через 2.3 сут" in lines[0]


def test_rate_needs_an_old_enough_sample(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, 80, 0)
    lines, _ = _run(tmp_path, monkeypatch, 96, 3600)
    assert "за сутки" not in lines[0]


def test_history_is_bounded_to_three_days(tmp_path, monkeypatch):
    for hour in range(0, 24 * 5, 6):
        _, state = _run(tmp_path, monkeypatch, 50, hour * 3600)
    assert all(state["history"][-1][0] - ts <= watch.HISTORY_SECONDS for ts, _ in state["history"])


def test_full_disk_falls_back_to_tmpfs_state_and_does_not_repeat(tmp_path, monkeypatch):
    (tmp_path / "disk_watch.json").mkdir()  # the primary path cannot be written
    lines, _ = _run(tmp_path, monkeypatch, 99, 0)
    assert lines[0].startswith("DISK_WATCH: уровень=crit")
    assert "не записано" not in "\n".join(lines)
    assert json.loads((tmp_path / "shm" / "disk_watch.json").read_text())["level"] == "crit"
    assert _run(tmp_path, monkeypatch, 99, 600)[0] == []


def test_unwritable_state_everywhere_still_prints_the_alert(tmp_path, monkeypatch):
    def full(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(watch.tempfile, "mkstemp", full)
    lines, _ = _run(tmp_path, monkeypatch, 99, 0)
    assert lines[0].startswith("DISK_WATCH: уровень=crit")
    assert "состояние сторожа не записано" in lines[-1]


def test_newest_of_primary_and_fallback_state_wins(tmp_path, monkeypatch):
    (tmp_path / "shm").mkdir()
    (tmp_path / "disk_watch.json").write_text(json.dumps({"level": "ok", "saved_at": 10}))
    (tmp_path / "shm" / "disk_watch.json").write_text(json.dumps({
        "level": "crit", "last_raw": "crit", "last_alert_at": 50, "saved_at": 50,
    }))
    assert _run(tmp_path, monkeypatch, 97, 100)[0] == []  # crit already alerted at 50


@pytest.mark.parametrize("state", [
    "{not json", "[]", json.dumps({"level": "crit", "last_alert_at": "x", "history": [["a", 1]]}),
    json.dumps({"level": 7, "history": "nope", "last_alert_at": None}),
])
def test_corrupt_or_badly_typed_state_is_treated_as_fresh(tmp_path, monkeypatch, state):
    (tmp_path / "disk_watch.json").write_text(state, encoding="utf-8")
    assert _run(tmp_path, monkeypatch, 96, 10 ** 9)[0][0].startswith("DISK_WATCH: уровень=crit")


def test_crash_is_loud(tmp_path, monkeypatch, capsys):
    def broken(_path):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(watch, "measure", broken)
    assert watch.main(["--state", str(tmp_path / "s.json"), "--fallback-state", ""]) == 1
    assert capsys.readouterr().out.startswith("DISK_WATCH: сторож диска упал: OSError")


def test_top_consumers_lists_biggest_children(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "big").mkdir(parents=True)
    (root / "small").mkdir()
    (root / "big" / "blob").write_bytes(b"x" * 300_000)
    (root / "small" / "blob").write_bytes(b"x" * 10)
    lines, _ = _run(tmp_path, monkeypatch, 96, 0, top_dir=[str(root)])
    assert lines[1] == "Крупнее всего:"
    assert lines[2].endswith(str(root / "big"))


def test_lowered_message_has_no_du_listing(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, 97, 0)
    monkeypatch.setattr(watch, "top_consumers", lambda *_a: pytest.fail("du on a lowered level"))
    lines, _ = _run(tmp_path, monkeypatch, 91, 60, top_dir=["/"])
    assert lines == ["DISK_WATCH: уровень снизился до high, диск /: занято 91%, свободно 26.1 ГБ из 290.0 ГБ"]


def test_top_consumers_time_budget_is_reported(monkeypatch):
    assert watch.top_consumers(["/"], 0, 5) == ["  /: не измерено, кончилось время"]


def test_measure_matches_df_definition(tmp_path):
    disk = watch.measure(str(tmp_path))
    assert 0 <= disk["pct"] <= 100
    assert disk["avail"] <= disk["total"] and disk["used"] <= disk["total"]


def test_main_rejects_unordered_thresholds(tmp_path):
    with pytest.raises(SystemExit):
        watch.main(["--state", str(tmp_path / "s.json"), "--thresholds", "90", "85", "95"])
