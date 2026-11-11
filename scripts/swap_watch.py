#!/usr/bin/env python3
"""Quiet swap-pressure check for the existing cron watchdog; no process management."""
from __future__ import annotations
import argparse
import json
import os
import time
from pathlib import Path

GIB = 1024 ** 3
COOLDOWN_SECONDS = 2 * 3600


def check(memory: dict[str, int], previous: dict, now: float) -> tuple[str, dict]:
    used = memory["SwapTotal"] - memory["SwapFree"]
    high = used > 10 * GIB
    available = memory["MemAvailable"]
    last = previous.get("last_alert_at")
    baseline = previous.get("last_alert_swap", previous.get("baseline_swap", used))
    grew = used - baseline > 2 * GIB
    due = last is None or now - last >= COOLDOWN_SECONDS
    state = {**previous, "baseline_swap": baseline}
    if high and (available < 4 * GIB or grew) and due:
        state.update(last_alert_at=now, last_alert_swap=used, baseline_swap=used)
        return f"SWAPHIGH={used // (1024*1024)}MB MemAvailable={available // (1024*1024)}MB", state
    # Lower swap use becomes the baseline for detecting subsequent pressure growth.
    state["baseline_swap"] = min(used, baseline)
    return "", state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path(__file__).resolve().parents[1] / "data/swap-watch.json")
    args = parser.parse_args()
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.strip().split()[0]) * 1024
    try:
        previous = json.loads(args.state.read_text())
    except (OSError, ValueError):
        previous = {}
    message, state = check(memory, previous, time.time())
    args.state.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.state.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, args.state)
    if message:
        print(message)


if __name__ == "__main__":
    main()
