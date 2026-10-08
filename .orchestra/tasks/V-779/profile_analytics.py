from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("database")
parser.add_argument("days", nargs="+", type=int)
args = parser.parse_args()
os.environ["ORCHESTRA_DB_PATH"] = args.database
sys.path.insert(0, str(Path.cwd()))

import app.db as db
import app.usage_analytics as analytics
build_usage_analytics = analytics.build_usage_analytics

original_conn = db._conn
query_samples: list[tuple[float, str]] = []


def _label(sql: str) -> str:
    normalized = re.sub(r"\s+", " ", sql.strip())
    return normalized[:180]


def traced_conn(*args, **kwargs):
    conn = original_conn(*args, **kwargs)
    previous = {"started": None, "label": ""}

    def trace(sql: str) -> None:
        now = time.perf_counter()
        if previous["started"] is not None:
            query_samples.append((now - previous["started"], previous["label"]))
        previous["started"] = now
        previous["label"] = _label(sql)

    conn.set_trace_callback(trace)
    return conn


db._conn = traced_conn
analytics._conn = traced_conn
for helper in (
    "_daily_usage", "_agent_rows", "_model_rows", "_model_speed_analytics",
    "_task_summary", "_lifetime_summary", "_reliability", "_retention",
):
    original = getattr(analytics, helper)

    def timed(*args, _name=helper, _original=original, **kwargs):
        started = time.perf_counter()
        result = _original(*args, **kwargs)
        print(f"helper={_name} seconds={time.perf_counter() - started:.3f}", flush=True)
        return result

    setattr(analytics, helper, timed)

for days in args.days:
    query_samples.clear()
    started = time.perf_counter()
    payload = build_usage_analytics(days=days)
    elapsed = time.perf_counter() - started
    print(f"days={days} total_seconds={elapsed:.3f} daily={len(payload['daily'])} agents={len(payload['agents'])} models={len(payload['models'])} lifetime_agents={payload['summary']['lifetime']['agents']} speed_points={len(payload['model_speeds']['series'])}")
    for seconds, query in sorted(query_samples, reverse=True)[:10]:
        print(f"query_seconds~={seconds:.3f} sql={query}")

started = time.perf_counter()
last_turns = db.get_last_turn_map()
print(f"get_last_turn_map_seconds={time.perf_counter() - started:.3f} sessions={len(last_turns)}")

started = time.perf_counter()
db.get_stats()
print(f"get_stats_seconds={time.perf_counter() - started:.3f}")
