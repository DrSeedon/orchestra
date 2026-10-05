"""Read-only weekly Claude quota profile and threshold comparison for V-721."""
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import csv
import sqlite3
import statistics

from app.db import DB_PATH
from app.quota_gate import line_limit, quota_policy

UTC = timezone.utc
KR = ZoneInfo("Asia/Krasnoyarsk")
POLICY = quota_policy()
NOW = datetime.now(UTC)
SINCE = NOW - timedelta(days=28)
OUT = Path(__file__).parent


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def reset_bucket(value: str) -> datetime:
    timestamp = parse_timestamp(value).timestamp()
    return datetime.fromtimestamp(round(timestamp / 60) * 60, UTC)


def active_seconds(start: datetime, end: datetime) -> float:
    """Scheduled-work comparator: 08:00–23:00 Krasnoyarsk, every day."""
    day = start.astimezone(KR).date()
    last_day = end.astimezone(KR).date()
    total = 0.0
    while day <= last_day:
        work_start = datetime.combine(day, time(8), KR).astimezone(UTC)
        work_end = datetime.combine(day, time(23), KR).astimezone(UTC)
        total += max(0.0, (min(end, work_end) - max(start, work_start)).total_seconds())
        day += timedelta(days=1)
    return total


def baseline_line(moment: datetime, start: datetime, reset: datetime) -> float:
    progress = (moment - start).total_seconds() / (reset - start).total_seconds()
    return min(99.0, line_limit(max(0.0, min(1.0, progress)), "claude", POLICY))


def workhours_line(moment: datetime, start: datetime, reset: datetime) -> float:
    progress = active_seconds(start, moment) / active_seconds(start, reset)
    return min(99.0, line_limit(max(0.0, min(1.0, progress)), "claude", POLICY))


def end_of_night_line(moment: datetime, start: datetime, reset: datetime) -> float:
    local = moment.astimezone(KR)
    target_day = local.date() + (timedelta(days=1) if local.hour >= 8 else timedelta())
    target = datetime.combine(target_day, time(8), KR).astimezone(UTC)
    return baseline_line(min(target, reset), start, reset)


connection = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True, timeout=5)
connection.row_factory = sqlite3.Row
connection.execute("PRAGMA query_only=ON")
snapshots = connection.execute(
    """SELECT ts, seven_day_pct, seven_day_resets_at
       FROM usage_snapshots
       WHERE ts >= ? AND seven_day_pct IS NOT NULL
         AND seven_day_resets_at IS NOT NULL AND seven_day_resets_at != ''
       ORDER BY ts""",
    (SINCE.isoformat(),),
).fetchall()
turns = connection.execute(
    """SELECT ts FROM turn_usage
       WHERE ts >= ? AND runtime='claude' AND quota_seven_day_pct IS NOT NULL
       ORDER BY ts""",
    (SINCE.isoformat(),),
).fetchall()
connection.close()

by_reset = defaultdict(list)
for row in snapshots:
    by_reset[reset_bucket(row["seven_day_resets_at"])].append(
        (parse_timestamp(row["ts"]), float(row["seven_day_pct"]))
    )

cycles = []
negative_intervals = 0
intervals = []
for reset, values in sorted(by_reset.items()):
    values.sort()
    start = reset - timedelta(days=7)
    hourly_delta = [0.0] * 168
    for (a, usage_a), (b, usage_b) in zip(values, values[1:]):
        duration = (b - a).total_seconds()
        if duration <= 0:
            continue
        intervals.append(duration)
        delta = usage_b - usage_a
        if delta < 0:
            negative_intervals += 1
            continue
        cursor = a
        while cursor < b:
            boundary = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            edge = min(boundary, b)
            portion = (edge - cursor).total_seconds()
            hour_index = int((cursor - start).total_seconds() // 3600)
            if 0 <= hour_index < 168:
                hourly_delta[hour_index] += delta * portion / duration
            cursor = edge
    coverage = (values[-1][0] - values[0][0]).total_seconds() / 604800
    first_99 = next((moment for moment, usage in values if usage >= 99), None)
    near_full = coverage >= 0.85 and max(usage for _, usage in values) >= 99 and len(values) > 1000
    cycles.append({
        "reset": reset, "start": start, "values": values,
        "hourly_delta": hourly_delta, "coverage": coverage,
        "near_full": near_full, "first_99": first_99,
    })

profile_cycles = [cycle for cycle in cycles if cycle["near_full"]][-3:]

with (OUT / "weekly-windows.csv").open("w", newline="") as output:
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "reset_kr", "window_start_kr", "sample_count", "first_sample_kr",
        "last_sample_kr", "coverage_days", "first_pct", "last_pct",
        "max_pct", "first_99_kr", "hours_99_before_reset", "profile_window",
    ])
    for cycle in cycles:
        values = cycle["values"]
        first_99 = cycle["first_99"]
        writer.writerow([
            cycle["reset"].astimezone(KR).isoformat(),
            cycle["start"].astimezone(KR).isoformat(), len(values),
            values[0][0].astimezone(KR).isoformat(),
            values[-1][0].astimezone(KR).isoformat(), round(cycle["coverage"] * 7, 2),
            values[0][1], values[-1][1], max(usage for _, usage in values),
            first_99.astimezone(KR).isoformat() if first_99 else "",
            round((cycle["reset"] - first_99).total_seconds() / 3600, 2) if first_99 else "",
            cycle["near_full"],
        ])

# Profile uses the three preceding quota weeks only; its turn counts use the same dates.
profile_start = min(cycle["start"] for cycle in profile_cycles)
profile_end = max(cycle["reset"] for cycle in profile_cycles)
hourly_usage = [0.0] * 24
hourly_coverage = [0.0] * 24
for cycle in profile_cycles:
    for (a, usage_a), (b, usage_b) in zip(cycle["values"], cycle["values"][1:]):
        duration = (b - a).total_seconds()
        if duration <= 0 or usage_b < usage_a:
            continue
        cursor = a
        while cursor < b:
            edge = min(cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1), b)
            portion = (edge - cursor).total_seconds()
            local = (cursor + timedelta(seconds=portion / 2)).astimezone(KR)
            hourly_usage[local.hour] += (usage_b - usage_a) * portion / duration
            hourly_coverage[local.hour] += portion / 3600
            cursor = edge

turn_hours = Counter(
    parse_timestamp(row["ts"]).astimezone(KR).hour
    for row in turns
    if profile_start <= parse_timestamp(row["ts"]) < profile_end
)
with (OUT / "hourly-profile.csv").open("w", newline="") as output:
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["hour_kr", "observed_week_pct_change_total", "snapshot_coverage_hours", "claude_turn_rows"])
    for hour in range(24):
        writer.writerow([hour, round(hourly_usage[hour], 5), round(hourly_coverage[hour], 2), turn_hours[hour]])

# Candidate C is a past-only predictor: fit hourly spend from earlier windows, then score the next one.
comparisons = []
for index, cycle in enumerate(profile_cycles):
    reset, start, values = cycle["reset"], cycle["start"], cycle["values"]
    prior_cycles = profile_cycles[:index]
    weights = [
        sum(previous["hourly_delta"][hour] for previous in prior_cycles) / len(prior_cycles)
        for hour in range(168)
    ] if prior_cycles else None
    cumulative = [0.0] if weights is not None else None
    if cumulative is not None:
        total = sum(weights)
        for weight in weights:
            cumulative.append(cumulative[-1] + (weight / total if total else 1 / 168))
    actual_99 = cycle["first_99"]
    variants = {
        "baseline": lambda moment: baseline_line(moment, start, reset),
        "workhours_08_23": lambda moment: workhours_line(moment, start, reset),
        "end_of_nearest_night_08": lambda moment: end_of_night_line(moment, start, reset),
    }
    if cumulative is not None:
        def history_line(moment):
            offset = max(0.0, min(167.999999, (moment - start).total_seconds() / 3600))
            hour = min(len(cumulative) - 2, max(0, int(offset)))
            fraction = offset - hour
            share = cumulative[hour] + (cumulative[hour + 1] - cumulative[hour]) * fraction
            return min(99.0, 10.0 + 89.0 * share)
        variants["prior_hourly_usage_profile"] = history_line
    for name, line in variants.items():
        excess = []
        daytime_delta = []
        for moment, usage in values:
            limit = line(moment)
            if usage > limit:
                excess.append((moment, usage - limit))
            if 8 <= moment.astimezone(KR).hour < 19:
                daytime_delta.append(limit - baseline_line(moment, start, reset))
        first_excess = excess[0][0] if excess else None
        comparisons.append({
            "reset_kr": reset.astimezone(KR).isoformat(),
            "variant": name,
            "mean_day_extra_pp_08_18": round(statistics.mean(daytime_delta), 2) if daytime_delta else "",
            "max_day_extra_pp_08_18": round(max(daytime_delta), 2) if daytime_delta else "",
            "min_day_extra_pp_08_18": round(min(daytime_delta), 2) if daytime_delta else "",
            "snapshot_observations_above_line": len(excess),
            "max_observed_over_line_pp": round(max((delta for _, delta in excess), default=0), 2),
            "first_observed_excess_kr": first_excess.astimezone(KR).isoformat() if first_excess else "",
            "first_observed_99_kr": actual_99.astimezone(KR).isoformat() if actual_99 else "",
            "hours_99_before_reset": round((reset - actual_99).total_seconds() / 3600, 2) if actual_99 else "",
        })
with (OUT / "scenario-comparison.csv").open("w", newline="") as output:
    writer = csv.DictWriter(output, fieldnames=list(comparisons[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(comparisons)

current = next(cycle for cycle in cycles if cycle["reset"].astimezone(KR).date().isoformat() == "2026-10-06")
weights = [sum(cycle["hourly_delta"][hour] for cycle in profile_cycles) / len(profile_cycles) for hour in range(168)]
total = sum(weights)
cumulative = [0.0]
for weight in weights:
    cumulative.append(cumulative[-1] + (weight / total if total else 1 / 168))
with (OUT / "current-example.csv").open("w", newline="") as output:
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["time_kr", "observed_at_kr", "observed_pct", "progress", "tolerance_pp", "baseline_pct", "workhours_pct", "end_of_night_pct", "historical_profile_pct"])
    for hour in (10, 11):
        moment = datetime(2026, 10, 5, hour, tzinfo=KR).astimezone(UTC)
        observed_at, observed_usage = min(current["values"], key=lambda item: abs((item[0] - moment).total_seconds()))
        offset = min(167.999999, (moment - current["start"]).total_seconds() / 3600)
        slot = min(len(cumulative) - 2, max(0, int(offset))); fraction = offset - slot
        share = cumulative[slot] + (cumulative[slot + 1] - cumulative[slot]) * fraction
        progress = (moment - current["start"]).total_seconds() / (current["reset"] - current["start"]).total_seconds()
        writer.writerow([
            moment.astimezone(KR).isoformat(), observed_at.astimezone(KR).isoformat(), observed_usage,
            round(progress, 6), round(10 - 9 * progress, 3), round(baseline_line(moment, current["start"], current["reset"]), 3),
            round(workhours_line(moment, current["start"], current["reset"]), 3),
            round(end_of_night_line(moment, current["start"], current["reset"]), 3),
            round(min(99, 10 + 89 * share), 3),
        ])

print(f"database={DB_PATH} mode=ro query_only=on")
print(f"period_utc={SINCE.isoformat()}..{NOW.isoformat()} snapshot_rows={len(snapshots)} turn_rows={len(turns)} reset_buckets={len(cycles)}")
print(f"profile_windows={len(profile_cycles)} profile_period_kr={profile_start.astimezone(KR).isoformat()}..{profile_end.astimezone(KR).isoformat()}")
print(f"night_usage_00_07={sum(hourly_usage[:8]):.2f}pp/{sum(hourly_usage):.2f}pp ({100*sum(hourly_usage[:8])/sum(hourly_usage):.1f}%)")
print(f"night_turns_00_07={sum(turn_hours[h] for h in range(8))}/{sum(turn_hours.values())} ({100*sum(turn_hours[h] for h in range(8))/sum(turn_hours.values()):.1f}%)")
print(f"day_usage_08_18={sum(hourly_usage[8:19]):.2f}pp ({100*sum(hourly_usage[8:19])/sum(hourly_usage):.1f}%) day_turns_08_18={sum(turn_hours[h] for h in range(8,19))}/{sum(turn_hours.values())}")
print(f"negative_delta_intervals={negative_intervals} gap_median_min={statistics.median(intervals)/60:.2f} gap_p95_min={statistics.quantiles(intervals,n=20)[18]/60:.2f} gaps_over_15m={sum(gap>900 for gap in intervals)}")
for row in comparisons:
    print(row)
print(f"outputs={OUT}/hourly-profile.csv,{OUT}/weekly-windows.csv,{OUT}/scenario-comparison.csv,{OUT}/current-example.csv")
