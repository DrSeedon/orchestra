import json

import pytest

from scripts.analyze_process_guard_calibration import (
    CalibrationError,
    analyze,
    main,
    read_events,
)


def sample(action, **changes):
    event = {
        "action": action,
        "pid": 123,
        "start_ticks": 456,
        "dry_run": True,
    }
    event.update(changes)
    return event


def scan(duration_ms=50, guard_maxrss_kib=12_000, **changes):
    event = {
        "action": "scan_complete",
        "duration_ms": duration_ms,
        "guard_maxrss_kib": guard_maxrss_kib,
        "dry_run": True,
    }
    event.update(changes)
    return event


def test_age_formula_and_performance_gate_are_fixed_before_observation():
    report = analyze([
        scan(),
        sample("calibration_sample"),
        sample("calibration_complete", lifetime_upper_sec=100),
        scan(duration_ms=80),
    ])

    assert report["eligible_for_t3_age_gate"] is True
    assert report["max_legitimate_lifetime_upper_sec"] == 100
    assert report["proposed_age_sec"] == 269
    assert report["worst_detection_sec"] == 279
    assert report["age_formula"] == "ceil(sqrt(max_legitimate_lifetime_upper_sec * 720))"
    assert report["rss_action"] == "log"


@pytest.mark.parametrize(("events", "blocker"), [
    ([scan(), sample("calibration_sample")], "right_censored_exact_matches"),
    ([scan(duration_ms=1000), sample("calibration_complete", lifetime_upper_sec=100)],
     "scan_p99_not_below_1s"),
    ([scan(guard_maxrss_kib=32 * 1024),
      sample("calibration_complete", lifetime_upper_sec=100)],
     "guard_rss_not_below_32mib"),
    ([scan(dry_run=False), sample("calibration_complete", lifetime_upper_sec=100)],
     "non_dry_run_event"),
])
def test_gate_fails_closed(events, blocker):
    report = analyze(events)
    assert report["eligible_for_t3_age_gate"] is False
    assert blocker in report["blockers"]


def test_reader_and_cli_fail_loud_on_invalid_or_blocked_input(tmp_path, capsys):
    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text("not-json\n")
    with pytest.raises(CalibrationError):
        read_events(invalid)
    assert main([str(invalid)]) == 2
    assert "CalibrationError" in capsys.readouterr().out

    blocked = tmp_path / "blocked.jsonl"
    blocked.write_text(json.dumps(scan()) + "\n")
    assert main([str(blocked)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["eligible_for_t3_age_gate"] is False
