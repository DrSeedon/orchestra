#!/usr/bin/env python3
"""Evaluate observe-only process-guard journal events against the T2 gate."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable, Mapping


EMERGENCY_AGE_SEC = 720
ARMED_POLL_SEC = 10
MAX_SCAN_P99_MS = 1000
MAX_GUARD_RSS_KIB = 32 * 1024


class CalibrationError(RuntimeError):
    pass


def _key(event: Mapping[str, object]) -> tuple[int, int]:
    try:
        return int(event["pid"]), int(event["start_ticks"])
    except (KeyError, TypeError, ValueError) as error:
        raise CalibrationError(f"event has no valid process identity: {event}") from error


def _number(event: Mapping[str, object], key: str) -> float:
    try:
        return float(event[key])
    except (KeyError, TypeError, ValueError) as error:
        raise CalibrationError(f"event has no valid {key}: {event}") from error


def _nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def analyze(events: Iterable[Mapping[str, object]]) -> dict[str, object]:
    active = {}
    completed_upper = []
    identity_changes = 0
    scan_durations = []
    guard_rss = []
    blockers = []

    for event in events:
        action = event.get("action")
        if action in {"calibration_sample", "calibration_complete", "scan_complete"}:
            if event.get("dry_run") is not True:
                blockers.append("non_dry_run_event")
        if action == "calibration_sample":
            active[_key(event)] = event
        elif action == "calibration_complete":
            key = _key(event)
            active.pop(key, None)
            completed_upper.append(_number(event, "lifetime_upper_sec"))
        elif action == "calibration_identity_changed":
            active.pop(_key(event), None)
            identity_changes += 1
        elif action == "scan_complete":
            scan_durations.append(_number(event, "duration_ms"))
            guard_rss.append(_number(event, "guard_maxrss_kib"))

    if not scan_durations:
        blockers.append("no_scan_events")
    if not completed_upper:
        blockers.append("no_completed_exact_matches")
    if active:
        blockers.append("right_censored_exact_matches")

    scan_p99_ms = _nearest_rank(scan_durations, 0.99) if scan_durations else None
    guard_maxrss_kib = max(guard_rss) if guard_rss else None
    if scan_p99_ms is not None and scan_p99_ms >= MAX_SCAN_P99_MS:
        blockers.append("scan_p99_not_below_1s")
    if guard_maxrss_kib is not None and guard_maxrss_kib >= MAX_GUARD_RSS_KIB:
        blockers.append("guard_rss_not_below_32mib")

    max_lifetime_upper_sec = max(completed_upper) if completed_upper else None
    proposed_age_sec = None
    worst_detection_sec = None
    if max_lifetime_upper_sec is not None:
        proposed_age_sec = math.ceil(
            math.sqrt(max_lifetime_upper_sec * EMERGENCY_AGE_SEC),
        )
        worst_detection_sec = proposed_age_sec + ARMED_POLL_SEC
        if worst_detection_sec >= EMERGENCY_AGE_SEC:
            blockers.append("age_plus_poll_not_below_emergency_endpoint")

    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "eligible_for_t3_age_gate": not unique_blockers,
        "blockers": unique_blockers,
        "completed_exact_matches": len(completed_upper),
        "right_censored_exact_matches": len(active),
        "identity_changes": identity_changes,
        "scan_count": len(scan_durations),
        "scan_p99_ms": scan_p99_ms,
        "guard_maxrss_kib": guard_maxrss_kib,
        "max_legitimate_lifetime_upper_sec": max_lifetime_upper_sec,
        "proposed_age_sec": proposed_age_sec,
        "armed_poll_sec": ARMED_POLL_SEC,
        "worst_detection_sec": worst_detection_sec,
        "emergency_endpoint_sec": EMERGENCY_AGE_SEC,
        "age_formula": "ceil(sqrt(max_legitimate_lifetime_upper_sec * 720))",
        "rss_action": "log",
    }


def read_events(path: Path) -> list[dict[str, object]]:
    events = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise CalibrationError(f"invalid JSON on line {line_number}: {error}") from error
        if not isinstance(event, dict):
            raise CalibrationError(f"line {line_number} is not a JSON object")
        events.append(event)
    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("journal", type=Path)
    args = parser.parse_args(argv)
    try:
        report = analyze(read_events(args.journal))
    except (OSError, CalibrationError) as error:
        print(json.dumps({"error": f"{type(error).__name__}: {error}"}, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["eligible_for_t3_age_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
