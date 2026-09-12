"""Read-only numeric checks for V-559; no message text or identifiers are exported."""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from pathlib import Path


DB = os.environ.get(
    "ORCHESTRA_DB_PATH",
    "/home/kesha/orchestra/data/storage-final-vps-20260908/orchestra.db",
)
OUT = Path(__file__).parent / "evidence"


def epoch(value: str) -> float:
    return dt.datetime.fromisoformat(value).timestamp()


def reset_day(value: str | None) -> str:
    return value[:10] if value else ""


def claude_stable_runs(connection: sqlite3.Connection) -> dict:
    snapshots = []
    query = """
        SELECT ts, seven_day_pct, provider_usage
        FROM usage_snapshots
        WHERE ts >= '2026-09-09'
        ORDER BY ts
    """
    for ts, weekly, provider_usage in connection.execute(query):
        try:
            windows = json.loads(provider_usage)["anthropic"]["windows"]
            reset = reset_day(windows[1].get("resets_at"))
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        snapshots.append((epoch(ts), ts, float(weekly), reset))

    turns = []
    query = """
        SELECT ts, input_tokens, cache_read_tokens, cache_create_tokens, output_tokens
        FROM turn_usage
        WHERE runtime = 'claude' AND ts >= '2026-09-09'
        ORDER BY ts
    """
    for ts, input_tokens, cache_read, cache_create, output in connection.execute(query):
        turns.append((epoch(ts), int(input_tokens), int(cache_read), int(cache_create), int(output)))

    runs = []
    start = 0
    for end in range(1, len(snapshots) + 1):
        split = end == len(snapshots)
        if not split:
            previous = snapshots[end - 1]
            current = snapshots[end]
            split = (
                current[2] != snapshots[start][2]
                or current[3] != snapshots[start][3]
                or current[0] - previous[0] > 380
            )
        if not split:
            continue
        if end - start >= 2:
            first, last = snapshots[start], snapshots[end - 1]
            totals = [0, 0, 0, 0]
            for turn in turns:
                if first[0] < turn[0] <= last[0]:
                    for index, value in enumerate(turn[1:]):
                        totals[index] += value
            runs.append(
                {
                    "start": first[1],
                    "end": last[1],
                    "hours": (last[0] - first[0]) / 3600,
                    "snapshots": end - start,
                    "weekly_pct": first[2],
                    "weekly_reset_day": first[3],
                    "input_tokens": totals[0],
                    "cache_read_tokens": totals[1],
                    "cache_create_tokens": totals[2],
                    "output_tokens": totals[3],
                }
            )
        start = end

    runs.sort(key=lambda row: row["cache_read_tokens"], reverse=True)
    return {
        "database": DB,
        "captured_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_window": "2026-09-09 onward",
        "snapshot_count": len(snapshots),
        "stable_run_count": len(runs),
        "stable_runs": runs[:20],
        "stable_read_total_tokens": sum(row["cache_read_tokens"] for row in runs),
        "stable_run_total_tokens": {
            key: sum(row[key] for row in runs)
            for key in (
                "input_tokens",
                "cache_read_tokens",
                "cache_create_tokens",
                "output_tokens",
            )
        },
    }


# These are API-equivalent USD rates, not the subscription-credit rate card.
API_PRICES = {
    "gpt-5.6-sol": (4.0, 0.4, 20.0),
    "gpt-6-astra": (10.0, 1.0, 50.0),
    "gpt-5.6-terra": (2.0, 0.2, 12.0),
    "gpt-5.6-luna": (0.2, 0.02, 1.2),
    "gpt-5.5": (5.0, 0.5, 30.0),
    "gpt-5.4": (2.5, 0.25, 15.0),
    "gpt-5.4-mini": (0.75, 0.075, 4.5),
}


def codex_summary(connection: sqlite3.Connection) -> dict:
    rows = []
    query = """
        SELECT model, COUNT(*), SUM(input_tokens), SUM(cache_read_tokens),
               SUM(cache_create_tokens), SUM(output_tokens), SUM(cost_usd),
               SUM(cost_unaccounted)
        FROM turn_usage
        WHERE runtime = 'codex'
        GROUP BY model
        ORDER BY model
    """
    for model, count, input_tokens, cached, cache_create, output, recorded, unaccounted in connection.execute(query):
        input_tokens = int(input_tokens or 0)
        cached = int(cached or 0)
        output = int(output or 0)
        recomputed = None
        credits = None
        if model in API_PRICES:
            normal, cached_rate, output_rate = API_PRICES[model]
            recomputed = (
                max(0, input_tokens - cached) * normal
                + cached * cached_rate
                + output * output_rate
            ) / 1_000_000
            credits = recomputed * 25
        rows.append(
            {
                "model": model,
                "turns": int(count),
                "input_tokens": input_tokens,
                "cache_read_tokens_inside_input": cached,
                "cache_create_tokens": int(cache_create or 0),
                "output_tokens": output,
                "cache_share_of_input": cached / input_tokens if input_tokens else None,
                "recorded_cost_usd_sum": recorded,
                "recomputed_current_api_usd": recomputed,
                "recomputed_current_rate_card_credits_at_25_per_usd": credits,
                "unaccounted_rows": int(unaccounted or 0),
            }
        )
    totals = connection.execute(
        """
        SELECT COUNT(*), SUM(input_tokens), SUM(cache_read_tokens),
               SUM(cache_create_tokens), SUM(output_tokens), SUM(cost_usd),
               SUM(cost_unaccounted)
        FROM turn_usage WHERE runtime = 'codex'
        """
    ).fetchone()
    return {
        "database": DB,
        "captured_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rows": rows,
        "all_models": {
            "turns": int(totals[0]),
            "input_tokens": int(totals[1] or 0),
            "cache_read_tokens_inside_input": int(totals[2] or 0),
            "cache_create_tokens": int(totals[3] or 0),
            "output_tokens": int(totals[4] or 0),
            "recorded_cost_usd_sum": totals[5],
            "unaccounted_rows": int(totals[6] or 0),
        },
    }


def main() -> None:
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    (OUT / "claude-stable-runs.json").write_text(
        json.dumps(claude_stable_runs(connection), indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "codex-summary.json").write_text(
        json.dumps(codex_summary(connection), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
