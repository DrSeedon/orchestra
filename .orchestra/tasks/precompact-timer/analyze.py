#!/usr/bin/env python3
"""Reproducible idle-gap and preventive-compact analysis for Orchestra."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo


TTL_MINUTES = 60
SAFE_TIMER_MINUTES = 55
LOCAL_TZ = ZoneInfo("Asia/Krasnoyarsk")
CTX_RE = re.compile(r"ctx:(\d+)%")


@dataclass(frozen=True)
class Event:
    session_id: str
    name: str
    scope: str
    agent_class: str
    ts: datetime
    log_id: int
    kind: str
    content: str
    ctx_pct: int | None


@dataclass(frozen=True)
class Gap:
    session_id: str
    name: str
    agent_class: str
    minutes: float
    start: datetime
    end: datetime
    start_kind: str
    start_content: str
    end_kind: str
    end_content: str
    ctx_pct: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path, help="Read-only Orchestra SQLite snapshot")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def read_events(
    db_path: Path,
) -> tuple[list[Event], dict[str, dict[str, str]], dict[str, int]]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    source_counts = {
        "raw_logs": connection.execute("SELECT COUNT(*) FROM logs").fetchone()[0],
        "raw_sessions_with_logs": connection.execute(
            "SELECT COUNT(DISTINCT session_id) FROM logs"
        ).fetchone()[0],
        "excluded_non_claude_logs": connection.execute(
            """
            SELECT COUNT(*) FROM logs AS l JOIN sessions AS s ON s.id = l.session_id
            WHERE s.backend_type != 'claude'
            """
        ).fetchone()[0],
        "excluded_non_claude_sessions": connection.execute(
            """
            SELECT COUNT(DISTINCT s.id) FROM logs AS l JOIN sessions AS s ON s.id = l.session_id
            WHERE s.backend_type != 'claude'
            """
        ).fetchone()[0],
    }
    rows = connection.execute(
        """
        SELECT l.id, l.session_id, l.ts, l.type, l.content,
               s.name, s.scope, s.role, s.is_orchestrator, s.status
        FROM logs AS l
        JOIN sessions AS s ON s.id = l.session_id
        WHERE s.backend_type = 'claude'
        ORDER BY l.session_id, l.ts, l.id
        """
    ).fetchall()
    session_meta = {
        session_id: {"name": name, "scope": scope, "role": role, "status": status}
        for session_id, name, scope, role, status in connection.execute(
            "SELECT id, name, scope, role, status FROM sessions WHERE backend_type = 'claude'"
        )
    }
    connection.close()

    last_ctx: dict[str, int] = {}
    events: list[Event] = []
    for log_id, session_id, ts, kind, content, name, scope, _role, is_orchestrator, _status in rows:
        match = CTX_RE.search(content)
        if match:
            last_ctx[session_id] = int(match.group(1))
        events.append(
            Event(
                session_id=session_id,
                name=name,
                scope=scope,
                agent_class="orchestrator" if is_orchestrator else "worker",
                ts=datetime.fromisoformat(ts),
                log_id=log_id,
                kind=kind,
                content=content,
                ctx_pct=last_ctx.get(session_id),
            )
        )
    return events, session_meta, source_counts


def is_cache_relevant(event: Event) -> bool:
    if event.kind != "status":
        return True
    return event.content.startswith(("turn ended", "compact started", "compact done"))


def starts_after_completed_turn(gap: Gap) -> bool:
    """Match the deployable policy: arm only from a completed idle turn."""
    return gap.start_kind == "status" and gap.start_content.startswith("turn ended")


def make_gaps(events: list[Event]) -> tuple[list[Gap], int]:
    previous: dict[str, Event] = {}
    gaps: list[Gap] = []
    negative = 0
    for event in events:
        before = previous.get(event.session_id)
        if before is not None:
            minutes = (event.ts - before.ts).total_seconds() / 60
            if minutes < 0:
                negative += 1
            else:
                gaps.append(
                    Gap(
                        session_id=event.session_id,
                        name=event.name,
                        agent_class=event.agent_class,
                        minutes=minutes,
                        start=before.ts,
                        end=event.ts,
                        start_kind=before.kind,
                        start_content=before.content,
                        end_kind=event.kind,
                        end_content=event.content,
                        ctx_pct=before.ctx_pct,
                    )
                )
        previous[event.session_id] = event
    return gaps, negative


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def wilson(successes: int, total: int, z: float = 1.96) -> list[float | None]:
    if total == 0:
        return [None, None]
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [center - margin, center + margin]


def summarize_sweep(gaps: list[Gap]) -> list[dict[str, float | int | list[float | None]]]:
    result = []
    for timer in range(1, TTL_MINUTES):
        triggered = [gap for gap in gaps if gap.minutes > timer]
        correct = sum(gap.minutes > TTL_MINUTES for gap in triggered)
        false = len(triggered) - correct
        p_correct = correct / len(triggered) if triggered else 0.0
        threshold = breakeven_ctx(p_correct)
        result.append(
            {
                "timer": timer,
                "triggered": len(triggered),
                "correct": correct,
                "false": false,
                "p_correct": p_correct,
                "false_rate": 1 - p_correct,
                "correct_ci95": wilson(correct, len(triggered)),
                "breakeven_ctx_pct": 100 * threshold if threshold is not None else None,
                "ev_at_40pct": expected_value(p_correct, 0.40),
            }
        )
    return result


def breakeven_ctx(p_correct: float) -> float | None:
    p_false = 1 - p_correct
    coefficient = p_correct * (3.50 - 0.20) - p_false * 0.20
    if coefficient <= 0:
        return None
    return p_correct * 0.14 / coefficient


def expected_value(p_correct: float, ctx_fraction: float) -> float:
    p_false = 1 - p_correct
    correct_saving = 3.50 * ctx_fraction - 0.14 - 0.20 * ctx_fraction
    false_cost = 0.20 * ctx_fraction
    return p_correct * correct_saving - p_false * false_cost


HISTOGRAM_BINS = [
    ("≤1m", 0, 1),
    ("1–5m", 1, 5),
    ("5–15m", 5, 15),
    ("15–30m", 15, 30),
    ("30–45m", 30, 45),
    ("45–55m", 45, 55),
    ("55–60m", 55, 60),
    ("1–2h", 60, 120),
    ("2–6h", 120, 360),
    ("6–12h", 360, 720),
    ("12–24h", 720, 1440),
    (">24h", 1440, math.inf),
]


def histogram(gaps: list[Gap]) -> list[dict[str, float | int | str]]:
    total = len(gaps)
    result = []
    for label, lower, upper in HISTOGRAM_BINS:
        count = sum(lower < gap.minutes <= upper for gap in gaps)
        if lower == 0:
            count = sum(0 <= gap.minutes <= upper for gap in gaps)
        result.append({"label": label, "count": count, "share": count / total if total else 0})
    return result


def hour_segments(gaps: list[Gap]) -> list[dict[str, float | int | None]]:
    result = []
    for hour in range(24):
        bucket = [gap for gap in gaps if gap.start.astimezone(LOCAL_TZ).hour == hour]
        over_one = [gap for gap in bucket if gap.minutes > 1]
        triggered = [gap for gap in bucket if gap.minutes > SAFE_TIMER_MINUTES]
        correct = sum(gap.minutes > TTL_MINUTES for gap in triggered)
        result.append(
            {
                "hour": hour,
                "all": len(bucket),
                "over_1m": len(over_one),
                "over_55m": len(triggered),
                "over_60m": sum(gap.minutes > TTL_MINUTES for gap in bucket),
                "p_over_60_given_1": (
                    sum(gap.minutes > TTL_MINUTES for gap in over_one) / len(over_one)
                    if over_one
                    else None
                ),
                "p_correct_at_55": correct / len(triggered) if triggered else None,
            }
        )
    return result


def period_name(hour: int) -> str:
    if hour >= 23 or hour < 8:
        return "night 23–08"
    if hour < 12:
        return "morning 08–12"
    if hour < 18:
        return "day 12–18"
    return "evening 18–23"


def period_segments(gaps: list[Gap]) -> list[dict[str, float | int | str | None]]:
    buckets: dict[str, list[Gap]] = defaultdict(list)
    for gap in gaps:
        buckets[period_name(gap.start.astimezone(LOCAL_TZ).hour)].append(gap)
    result = []
    for name in ("night 23–08", "morning 08–12", "day 12–18", "evening 18–23"):
        bucket = buckets[name]
        over_one = [gap for gap in bucket if gap.minutes > 1]
        triggered = [gap for gap in bucket if gap.minutes > SAFE_TIMER_MINUTES]
        correct = sum(gap.minutes > TTL_MINUTES for gap in triggered)
        result.append(
            {
                "period": name,
                "all": len(bucket),
                "over_1m": len(over_one),
                "over_55m": len(triggered),
                "over_60m": sum(gap.minutes > TTL_MINUTES for gap in bucket),
                "p_over_60_given_1": (
                    sum(gap.minutes > TTL_MINUTES for gap in over_one) / len(over_one)
                    if over_one
                    else None
                ),
                "p_correct_at_55": correct / len(triggered) if triggered else None,
            }
        )
    return result


def group_summary(gaps: list[Gap]) -> dict[str, object]:
    minutes = [gap.minutes for gap in gaps]
    tail = [gap.minutes for gap in gaps if gap.minutes > 1]
    sweep = summarize_sweep(gaps)
    at_55 = sweep[SAFE_TIMER_MINUTES - 1]
    known_contexts = [gap.ctx_pct for gap in gaps if gap.minutes > SAFE_TIMER_MINUTES and gap.ctx_pct is not None]
    long_by_session = Counter(gap.name for gap in gaps if gap.minutes > TTL_MINUTES)
    control_endpoints = sum(
        gap.minutes > SAFE_TIMER_MINUTES
        and (
            (gap.start_kind == "status" and not gap.start_content.startswith(("turn ended", "compact")))
            or (gap.end_kind == "status" and not gap.end_content.startswith(("turn ended", "compact")))
        )
        for gap in gaps
    )
    at_55["ev_by_ctx_pct"] = {
        str(ctx): expected_value(at_55["p_correct"], ctx / 100) for ctx in (5, 10, 20, 40, 60, 80)
    }
    return {
        "gaps": len(gaps),
        "sessions": len({gap.session_id for gap in gaps}),
        "quantiles_minutes_all": {
            "p50": percentile(minutes, 0.50),
            "p75": percentile(minutes, 0.75),
            "p90": percentile(minutes, 0.90),
            "p95": percentile(minutes, 0.95),
            "p99": percentile(minutes, 0.99),
        },
        "quantiles_minutes_gt_1": {
            "p50": percentile(tail, 0.50),
            "p75": percentile(tail, 0.75),
            "p90": percentile(tail, 0.90),
            "p95": percentile(tail, 0.95),
        },
        "histogram": histogram(gaps),
        "sweep": sweep,
        "at_55": at_55,
        "known_ctx_at_55": {
            "count": len(known_contexts),
            "coverage": len(known_contexts) / at_55["triggered"] if at_55["triggered"] else 0,
            "median": median(known_contexts) if known_contexts else None,
            "p25": percentile(known_contexts, 0.25),
            "p75": percentile(known_contexts, 0.75),
        },
        "hour_segments": hour_segments(gaps),
        "period_segments": period_segments(gaps),
        "control_endpoint_triggers_at_55": control_endpoints,
        "top_long_gap_sessions": long_by_session.most_common(10),
    }


def build_report(db_path: Path) -> dict[str, object]:
    events, session_meta, source_counts = read_events(db_path)
    primary_gaps, negative_primary = make_gaps(events)
    filtered_events = [event for event in events if is_cache_relevant(event)]
    filtered_gaps, negative_filtered = make_gaps(filtered_events)
    snapshot_end = max(event.ts for event in events)
    session_ids_by_name: dict[str, set[str]] = defaultdict(set)
    for event in events:
        session_ids_by_name[event.name].add(event.session_id)
    last_by_session = {event.session_id: event for event in events}
    censored = []
    for session_id, event in last_by_session.items():
        minutes = (snapshot_end - event.ts).total_seconds() / 60
        censored.append(
            {
                "session_id": session_id,
                "agent_class": event.agent_class,
                "minutes": minutes,
                "status": session_meta[session_id]["status"],
            }
        )

    report: dict[str, object] = {
        "source": {
            **source_counts,
            "db": str(db_path),
            "logs": len(events),
            "sessions_with_logs": len({event.session_id for event in events}),
            "min_ts": min(event.ts for event in events).isoformat(),
            "max_ts": snapshot_end.isoformat(),
            "span_days": (snapshot_end - min(event.ts for event in events)).total_seconds() / 86400,
            "negative_gaps": negative_primary,
            "filtered_negative_gaps": negative_filtered,
            "duplicate_session_names": {
                name: len(session_ids) for name, session_ids in session_ids_by_name.items() if len(session_ids) > 1
            },
            "right_censored_sessions": len(censored),
            "right_censored_over_60_idle": sum(
                row["minutes"] > TTL_MINUTES and row["status"] != "running" for row in censored
            ),
        },
        "cost_model": {
            "warm_full": 0.20,
            "cold_full": 3.50,
            "postcompact_cold": 0.14,
            "formula": "Pc*(3.50*x - 0.14 - 0.20*x) - Pf*(0.20*x)",
        },
        "primary": {},
        "sensitivity_cache_relevant": {},
        "sensitivity_policy_turn_ended": {},
    }
    for agent_class in ("orchestrator", "worker"):
        report["primary"][agent_class] = group_summary(
            [gap for gap in primary_gaps if gap.agent_class == agent_class]
        )
        report["sensitivity_cache_relevant"][agent_class] = group_summary(
            [gap for gap in filtered_gaps if gap.agent_class == agent_class]
        )
        report["sensitivity_policy_turn_ended"][agent_class] = group_summary(
            [
                gap
                for gap in filtered_gaps
                if gap.agent_class == agent_class and starts_after_completed_turn(gap)
            ]
        )
    return report


def main() -> None:
    args = parse_args()
    report = build_report(args.db)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
