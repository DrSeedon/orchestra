#!/usr/bin/env python3
"""Free-space alarm for the VPS disk, run by a bg cron_command with pattern `DISK_WATCH:`.

01.11.2026 the root disk filled up for a day: uvicorn, the daily backup, worker spawns and
the delivery fallback all hit ENOSPC, and nothing warned beforehand (the only watcher was a
one-shot job). This script prints a `DISK_WATCH:` line only when the level rises (below
crit only after two checks in a row), drops, is still held after its repeat interval, or
recovers, so the cron job stays quiet otherwise. Standard library only: it must keep working when the service, its
database or the project venv are the thing that broke.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

LEVELS = ("ok", "warn", "high", "crit")
DEFAULT_THRESHOLDS = (85, 90, 95)
# A held level is repeated: the warning once a day, the last two more often.
REPEAT_SECONDS = {"warn": 24 * 3600, "high": 6 * 3600, "crit": 3600}
# Usage must fall this many points below a threshold before the level drops back.
HYSTERESIS_PCT = 2
HISTORY_SECONDS = 72 * 3600
# The growth rate needs a sample at least this old; a shorter window is mostly noise
# (the nightly backup alone takes ~10 GB for a few minutes).
RATE_MIN_SPAN_SECONDS = 6 * 3600
RATE_TARGET_SPAN_SECONDS = 24 * 3600
GIB = 1024 ** 3


def measure(path: str) -> dict[str, int]:
    """Same numbers as `df`: Use% = used / (used + available to unprivileged users)."""
    stat = os.statvfs(path)
    total = stat.f_blocks * stat.f_frsize
    used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
    avail = stat.f_bavail * stat.f_frsize
    pct = math.ceil(used * 100 / (used + avail)) if used + avail else 0
    return {"total": total, "used": used, "avail": avail, "pct": pct}


def level_for(pct: int, previous: str, thresholds: tuple[int, ...]) -> str:
    raw = 0
    for index, threshold in enumerate(thresholds, start=1):
        if pct >= threshold:
            raw = index
    held = LEVELS.index(previous) if previous in LEVELS else 0
    # Dropping needs a margin below the held threshold, otherwise 84/85/84 flaps.
    if held > raw and pct >= thresholds[held - 1] - HYSTERESIS_PCT:
        return LEVELS[held]
    return LEVELS[raw]


def growth_per_day(history: list[list[float]], now: float, avail: int) -> float | None:
    """Net loss of free bytes per day against the sample closest to 24 h ago."""
    old = [sample for sample in history if now - sample[0] >= RATE_MIN_SPAN_SECONDS]
    if not old:
        return None
    base_ts, base_avail = min(
        old, key=lambda sample: abs(now - sample[0] - RATE_TARGET_SPAN_SECONDS)
    )
    return (base_avail - avail) * 86400 / (now - base_ts)


def _gib(value: float) -> str:
    return f"{value / GIB:.1f} ГБ"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _read_state(path: Path) -> dict[str, Any]:
    """Only well-typed fields survive: a hand-edited or half-written file must not crash us."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    state: dict[str, Any] = {}
    for key in ("level", "last_raw"):
        if raw.get(key) in LEVELS:
            state[key] = raw[key]
    for key in ("last_alert_at", "saved_at"):
        number = _number(raw.get(key))
        if number is not None:
            state[key] = number
    history = []
    for sample in raw.get("history") or []:
        if isinstance(sample, list) and len(sample) == 2:
            ts, avail = _number(sample[0]), _number(sample[1])
            if ts is not None and avail is not None:
                history.append([ts, avail])
    state["history"] = history
    return state


def _load_state(paths: list[Path]) -> dict[str, Any]:
    states = [_read_state(path) for path in paths]
    return max(states, key=lambda state: state.get("saved_at", -1.0), default={})


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _save_state(paths: list[Path], state: dict[str, Any]) -> str | None:
    """Best effort: the first writable path wins (tmpfs fallback when the disk is full)."""
    errors = []
    for path in paths:
        try:
            _write_state(path, state)
            return None
        except OSError as error:
            errors.append(f"{path}: {type(error).__name__}: {error}")
    return "; ".join(errors) or "no state path"


def top_consumers(dirs: list[str], budget_seconds: float, limit: int) -> list[str]:
    """Largest direct children of `dirs` by allocated bytes, within a time budget."""
    sizes: list[tuple[int, str]] = []
    deadline = time.monotonic() + budget_seconds
    for directory in dirs:
        left = deadline - time.monotonic()
        if left <= 1:
            sizes.append((-1, f"{directory}: не измерено, кончилось время"))
            continue
        try:
            done = subprocess.run(
                ["nice", "-n", "15", "ionice", "-c3", "du", "-x", "-B1", "-d1", directory],
                capture_output=True, text=True, timeout=left,
            )
        except (OSError, subprocess.TimeoutExpired):
            sizes.append((-1, f"{directory}: не измерено, du не уложился"))
            continue
        for line in done.stdout.splitlines():
            size, _, path = line.partition("\t")
            if path and path != directory and size.isdigit():
                sizes.append((int(size), path))
    measured = sorted((item for item in sizes if item[0] >= 0), reverse=True)[:limit]
    notes = [text for size, text in sizes if size < 0]
    return [f"  {_gib(size)} {path}" for size, path in measured] + [f"  {n}" for n in notes]


def check(args: argparse.Namespace, now: float | None = None) -> tuple[list[str], dict]:
    now = time.time() if now is None else now
    state_paths = [Path(args.state)] + ([Path(args.fallback_state)] if args.fallback_state else [])
    state = _load_state(state_paths)
    disk = measure(args.path)
    thresholds = tuple(args.thresholds)
    previous = state.get("level", "ok")
    raw = level_for(disk["pct"], previous, thresholds)
    previous_rank, raw_rank = LEVELS.index(previous), LEVELS.index(raw)
    # A rise below crit must be seen twice: the nightly backup alone takes ~10 GB for a
    # few minutes and would otherwise wake everybody at 03:00 for nothing.
    if raw_rank > previous_rank and raw != "crit":
        confirmed = LEVELS.index(state.get("last_raw", "ok"))
        rank = max(previous_rank, min(raw_rank, confirmed))
    else:
        rank = raw_rank
    level = LEVELS[rank]

    history = [sample for sample in state.get("history", []) if now - sample[0] <= HISTORY_SECONDS]
    rate = growth_per_day(history, now, disk["avail"])
    history.append([now, disk["avail"]])

    last_alert = state.get("last_alert_at", 0.0)
    if rank > previous_rank:
        reason = "rise"
    elif rank and rank == previous_rank and now - last_alert >= REPEAT_SECONDS[level]:
        reason = "repeat"
    elif not rank and previous_rank:
        reason = "recovered"
    elif rank < previous_rank:
        reason = "lowered"
    else:
        reason = ""

    lines: list[str] = []
    if reason:
        where = (
            f"диск {args.path}: занято {disk['pct']}%, "
            f"свободно {_gib(disk['avail'])} из {_gib(disk['total'])}"
        )
        if reason == "recovered":
            lines.append(f"DISK_WATCH: уровень=ok, {where}: снова ниже {thresholds[0]}%")
        elif reason == "lowered":
            lines.append(f"DISK_WATCH: уровень снизился до {level}, {where}")
        else:
            bound = thresholds[rank - 1]
            text = f"DISK_WATCH: уровень={level} (порог {bound}%), {where}"
            if rate is not None and rate > 0:
                text += f"; за сутки свободного места меньше на {_gib(rate)}"
                text += f", при таком темпе диск заполнится примерно через {disk['avail'] / rate:.1f} сут"
            elif rate is not None:
                text += f"; за сутки свободного места больше на {_gib(-rate)}"
            lines.append(text)
            if args.top_dir:
                consumers = top_consumers(args.top_dir, args.top_seconds, args.top_limit)
                if consumers:
                    lines.append("Крупнее всего:")
                    lines.extend(consumers)
        last_alert = now

    new_state = {
        "level": level, "last_raw": raw, "last_alert_at": last_alert,
        "history": history, "saved_at": now,
    }
    error = _save_state(state_paths, new_state)
    if error and lines:
        lines.append(f"(состояние сторожа не записано: {error})")
    return lines, new_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default="/")
    parser.add_argument(
        "--state", default=str(Path(__file__).resolve().parents[1] / "data" / "disk_watch.json"),
    )
    parser.add_argument(
        "--fallback-state", default=f"/dev/shm/orchestra-disk-watch-{os.getuid()}.json",
        help="used when --state cannot be written (a full disk); empty to disable",
    )
    parser.add_argument(
        "--thresholds", type=int, nargs=3, default=list(DEFAULT_THRESHOLDS),
        metavar=("WARN", "HIGH", "CRIT"),
    )
    parser.add_argument("--top-dir", action="append", default=[])
    parser.add_argument("--top-seconds", type=float, default=240)
    parser.add_argument("--top-limit", type=int, default=12)
    args = parser.parse_args(argv)
    if not (0 < args.thresholds[0] < args.thresholds[1] < args.thresholds[2] <= 100):
        parser.error("thresholds must be increasing percentages")
    try:
        lines, _state = check(args)
    except Exception as error:  # a crashed watcher must stay loud, like error_watch
        print(f"DISK_WATCH: сторож диска упал: {type(error).__name__}: {error}")
        return 1
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
