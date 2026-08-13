"""Read-only usage analytics aggregations."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from statistics import median

from app.db import _conn
from app.models import PROVIDER_METADATA, cache_policy_for_runtime


# One table drives every provider decision here: bucketing rows AND picking the cache window
# for cold-start scoring. Both used to be hand-written binaries ending in `ELSE 'claude'`, so
# a new runtime silently joined the Claude Max pool and was scored against Claude's TTL —
# which would have hidden the whole point of running Grok on a separate quota.
# Explicit runtime ids win. Model prefixes are used only for legacy rows whose
# runtime column is empty; anything else is accounted as unknown.
_PROVIDERS = tuple(PROVIDER_METADATA)
_FALLBACK_PROVIDER = "unknown"


def _provider_case(runtime_col: str, model_col: str) -> str:
    """SQL that buckets a usage row by runtime — one decision, two call sites."""
    runtime_branches = " ".join(
        f"WHEN {runtime_col} = '{provider}' THEN '{provider}'"
        for provider in _PROVIDERS
        if provider != _FALLBACK_PROVIDER
    )
    legacy_branches = " ".join(
        f"WHEN COALESCE({runtime_col}, '') = '' "
        f"AND {model_col} LIKE '{prefix}%' THEN '{provider}'"
        for provider, metadata in PROVIDER_METADATA.items()
        for prefix in metadata.legacy_model_prefixes
    )
    return (
        f"CASE {runtime_branches} {legacy_branches} "
        f"ELSE '{_FALLBACK_PROVIDER}' END"
    )


def _cache_ttl_case() -> tuple[str, tuple[int, ...]]:
    """SQL CASE + bound TTLs for cold-start scoring, in _PROVIDERS order."""
    branches = " ".join(
        f"WHEN provider = '{p}' THEN ?"
        for p in _PROVIDERS
        if p != _FALLBACK_PROVIDER
    )
    ttls = tuple(
        int(cache_policy_for_runtime(p)["cache_ttl_seconds"]) for p in _PROVIDERS
    )
    return f"CASE {branches} ELSE ? END", ttls


_PROVIDER_SQL = _provider_case("COALESCE(s.backend_type, '')", "s.model")
_PROVIDER_SQL_USAGE = _provider_case("u.runtime", "u.model")

_OBSERVED_TURNS_CTE = f"""
WITH observed_turns AS (
    SELECT u.ts,
           u.session_id,
           COALESCE(s.name, u.session_id) AS name,
           COALESCE(NULLIF(u.scope, ''), s.scope, '') AS scope,
           COALESCE(NULLIF(u.model, ''), s.model, 'unknown') AS model,
           {_PROVIDER_SQL_USAGE} AS provider,
           u.cost_usd
    FROM turn_usage u
    LEFT JOIN sessions s ON s.id = u.session_id
    WHERE date(u.ts) >= date('now', ?)

    UNION ALL

    SELECT l.ts,
           s.id AS session_id,
           s.name,
           s.scope,
           s.model,
           {_PROVIDER_SQL} AS provider,
           CAST(SUBSTR(
               l.content,
               INSTR(l.content, '$') + 1,
               INSTR(SUBSTR(l.content, INSTR(l.content, '$') + 1), ' ') - 1
           ) AS REAL) AS cost_usd
    FROM logs l
    JOIN sessions s ON s.id = l.session_id
    WHERE l.type = 'status'
      AND l.content LIKE '%turn ended%'
      AND date(l.ts) >= date('now', ?)
      AND (
          l.event_id = ''
          OR NOT EXISTS (
              SELECT 1 FROM turn_usage u WHERE u.event_id = l.event_id
          )
      )
      AND (
          l.event_id = ''
          OR l.id = (
              SELECT MIN(l2.id) FROM logs l2 WHERE l2.event_id = l.event_id
          )
      )
)
"""


def _hit_pct(comparable: int, cold: int) -> int | None:
    if not comparable:
        return None
    return round((comparable - cold) / comparable * 100)


def _calendar_since(days: int) -> str:
    return f"-{days - 1} days"


def _collector_coverage(
    conn: sqlite3.Connection,
    key: str,
    since: str,
) -> dict:
    row = conn.execute(
        """SELECT value AS started_at,
                  datetime(value) <= datetime('now', 'start of day', ?)
                      AS coverage_complete
           FROM kv
           WHERE key = ?""",
        (since, key),
    ).fetchone()
    return {
        "collector_ready": bool(row and row["started_at"]),
        "collector_started_at": row["started_at"] if row else None,
        "coverage_complete": bool(row and row["coverage_complete"]),
    }


def _daily_usage(conn: sqlite3.Connection, days: int) -> list[dict]:
    since = _calendar_since(days)
    cost_rows = conn.execute(
        _OBSERVED_TURNS_CTE
        + """
        SELECT date(ts) AS day, provider,
               COUNT(*) AS turns,
               COUNT(cost_usd) AS priced_turns,
               ROUND(SUM(cost_usd), 4) AS cost_usd
        FROM observed_turns
        GROUP BY day, provider
        ORDER BY day, provider
        """,
        (since, since),
    ).fetchall()

    ttl_case, ttl_params = _cache_ttl_case()
    cache_rows = conn.execute(
        _OBSERVED_TURNS_CTE
        + f"""
        , turns AS (
            SELECT ts, date(ts) AS day, provider,
                   LAG(ts) OVER (
                       PARTITION BY session_id ORDER BY ts
                   ) AS prev_ts
            FROM observed_turns
        )
        SELECT day, provider,
               COUNT(*) FILTER (WHERE prev_ts IS NOT NULL) AS comparable,
               COUNT(*) FILTER (
                   WHERE prev_ts IS NOT NULL
                     AND (julianday(ts) - julianday(prev_ts)) * 86400 > {ttl_case}
               ) AS cold
        FROM turns
        GROUP BY day, provider
        ORDER BY day, provider
        """,
        (since, since) + ttl_params,
    ).fetchall()

    by_day: dict[str, dict] = {}
    for row in cost_rows:
        day = row["day"]
        provider = row["provider"]
        entry = by_day.setdefault(
            day,
            {
                "day": day,
                "turns": 0,
                "cost_usd": 0.0,
                "priced_turns": 0,
                "unaccounted_turns": 0,
                "cold_starts": 0,
                "cache_hit_pct": None,
                "providers": {},
                "_comparable": 0,
            },
        )
        turns = int(row["turns"] or 0)
        priced_turns = int(row["priced_turns"] or 0)
        unaccounted_turns = turns - priced_turns
        cost = float(row["cost_usd"]) if priced_turns else None
        # Provider ids are runtime ids, so ask the registry instead of branching per
        # provider — a fourth runtime would otherwise inherit Claude's window again.
        policy = cache_policy_for_runtime(provider)
        entry["turns"] += turns
        entry["priced_turns"] += priced_turns
        entry["unaccounted_turns"] += unaccounted_turns
        if cost is not None:
            entry["cost_usd"] += cost
        entry["providers"][provider] = {
            "turns": turns,
            "cost_usd": cost,
            "priced_turns": priced_turns,
            "unaccounted_turns": unaccounted_turns,
            "comparable_turns": 0,
            "cold_starts": 0,
            "cache_hit_pct": None,
            **policy,
        }

    for row in cache_rows:
        entry = by_day.get(row["day"])
        if not entry:
            continue
        provider = row["provider"]
        provider_entry = entry["providers"].get(provider)
        if not provider_entry:
            continue
        comparable = int(row["comparable"] or 0)
        cold = int(row["cold"] or 0)
        provider_entry["comparable_turns"] = comparable
        provider_entry["cold_starts"] = cold
        provider_entry["cache_hit_pct"] = _hit_pct(comparable, cold)
        entry["_comparable"] += comparable
        entry["cold_starts"] += cold

    result = []
    for entry in by_day.values():
        entry["cost_usd"] = (
            round(entry["cost_usd"], 4) if entry["priced_turns"] else None
        )
        entry["cache_hit_pct"] = _hit_pct(
            entry.pop("_comparable"),
            entry["cold_starts"],
        )
        result.append(entry)
    return result


def daily_usage(days: int = 30, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Return legacy daily totals plus provider-aware cache details."""
    days = max(1, min(int(days), 9999))
    if conn is not None:
        return _daily_usage(conn, days)
    with _conn() as owned:
        return _daily_usage(owned, days)


def _provider_rollup(daily: list[dict]) -> dict:
    providers: dict[str, dict] = {}
    for day in daily:
        for provider, values in day["providers"].items():
            item = providers.setdefault(
                provider,
                {
                    "turns": 0,
                    "cost_usd": 0.0,
                    "priced_turns": 0,
                    "unaccounted_turns": 0,
                    "comparable_turns": 0,
                    "cold_starts": 0,
                    "cache_hit_pct": None,
                    "cache_ttl_seconds": values["cache_ttl_seconds"],
                    "cache_ttl_approximate": values["cache_ttl_approximate"],
                },
            )
            item["turns"] += values["turns"]
            item["priced_turns"] += values["priced_turns"]
            item["unaccounted_turns"] += values["unaccounted_turns"]
            if values["cost_usd"] is not None:
                item["cost_usd"] += values["cost_usd"]
            item["comparable_turns"] += values["comparable_turns"]
            item["cold_starts"] += values["cold_starts"]
    for item in providers.values():
        item["cost_usd"] = (
            round(item["cost_usd"], 4) if item["priced_turns"] else None
        )
        item["cache_hit_pct"] = _hit_pct(
            item["comparable_turns"],
            item["cold_starts"],
        )
    return providers


def _agent_rows(conn: sqlite3.Connection, since: str) -> list[dict]:
    rows = conn.execute(
        _OBSERVED_TURNS_CTE
        + """
        SELECT session_id AS id, name, scope, model, provider,
               COUNT(*) AS turns,
               COUNT(cost_usd) AS priced_turns,
               ROUND(SUM(cost_usd), 4) AS cost_usd,
               MAX(ts) AS last_turn
        FROM observed_turns
        GROUP BY session_id, name, scope, model, provider
        ORDER BY cost_usd DESC
        """,
        (since, since),
    ).fetchall()
    agents = []
    comparable_costs = []
    for row in rows:
        turns = int(row["turns"] or 0)
        priced_turns = int(row["priced_turns"] or 0)
        unaccounted_turns = turns - priced_turns
        cost = float(row["cost_usd"]) if priced_turns else None
        cost_per_priced_turn = (
            round(cost / priced_turns, 4) if priced_turns else None
        )
        cost_per_turn = (
            cost_per_priced_turn if turns and not unaccounted_turns else None
        )
        if priced_turns >= 2:
            comparable_costs.append(cost_per_priced_turn)
        agents.append(
            {
                "id": row["id"],
                "name": row["name"],
                "scope": row["scope"],
                "model": row["model"],
                "provider": row["provider"],
                "turns": turns,
                "cost_usd": cost,
                "priced_turns": priced_turns,
                "unaccounted_turns": unaccounted_turns,
                "cost_per_turn": cost_per_turn,
                "cost_per_priced_turn": cost_per_priced_turn,
                "last_turn": row["last_turn"],
                "anomaly": False,
            }
        )
    fleet_median = median(comparable_costs) if comparable_costs else None
    if fleet_median is not None:
        for agent in agents:
            agent["anomaly"] = (
                agent["priced_turns"] >= 2
                and agent["cost_per_priced_turn"] >= 4 * fleet_median
            )
    return agents


def _model_rows(conn: sqlite3.Connection, since: str) -> list[dict]:
    rows = conn.execute(
        _OBSERVED_TURNS_CTE
        + """
        SELECT model, provider,
               COUNT(*) AS turns,
               COUNT(cost_usd) AS priced_turns,
               ROUND(SUM(cost_usd), 4) AS cost_usd
        FROM observed_turns
        GROUP BY model, provider
        ORDER BY cost_usd DESC
        """,
        (since, since),
    ).fetchall()
    total = sum(
        float(row["cost_usd"])
        for row in rows
        if int(row["priced_turns"] or 0)
    )
    models = []
    for row in rows:
        turns = int(row["turns"] or 0)
        priced_turns = int(row["priced_turns"] or 0)
        cost = float(row["cost_usd"]) if priced_turns else None
        models.append({
            "model": row["model"],
            "provider": row["provider"],
            "turns": turns,
            "priced_turns": priced_turns,
            "unaccounted_turns": turns - priced_turns,
            "cost_usd": cost,
            "cost_share_pct": (
                round(cost / total * 100, 1)
                if cost is not None and total else
                0.0 if cost is not None else None
            ),
        })
    return models


def _task_summary(conn: sqlite3.Connection, since: str) -> dict:
    completed = conn.execute(
        """SELECT COUNT(*) FROM tm_tasks
           WHERE status IN ('done', 'paid')
             AND date(completed_at) >= date('now', ?)""",
        (since,),
    ).fetchone()[0]
    linked = conn.execute(
        """
        WITH linked_tasks AS (
            SELECT t.id,
                   t.created_at,
                   SUM(u.cost_usd) AS cost_usd,
                   COUNT(*) AS turns,
                   COUNT(u.cost_usd) AS priced_turns,
                   datetime(t.created_at) >= datetime((
                       SELECT value FROM kv
                       WHERE key = 'turn_usage_collector_started_at'
                   )) AS fully_observed
            FROM tm_tasks t
            JOIN tm_projects p ON p.id = t.project_id
            JOIN turn_usage u
              ON u.scope = p.scope
             AND u.task_id = CAST(t.par_number AS TEXT)
            WHERE t.status IN ('done', 'paid')
              AND date(t.completed_at) >= date('now', ?)
            GROUP BY t.id
        )
        SELECT COUNT(*) AS linked,
               COUNT(*) FILTER (WHERE fully_observed) AS fully_observed,
               COUNT(*) FILTER (
                   WHERE fully_observed AND turns = priced_turns
               ) AS fully_costed,
               SUM(cost_usd) AS cost_usd,
               COALESCE(SUM(turns), 0) AS turns,
               COALESCE(SUM(priced_turns), 0) AS priced_turns
        FROM linked_tasks
        """,
        (since,),
    ).fetchone()
    linked_count = int(linked["linked"] or 0)
    fully_observed = int(linked["fully_observed"] or 0)
    fully_costed = int(linked["fully_costed"] or 0)
    linked_turns = int(linked["turns"] or 0)
    linked_priced_turns = int(linked["priced_turns"] or 0)
    linked_unaccounted_turns = linked_turns - linked_priced_turns
    linked_cost = (
        float(linked["cost_usd"]) if linked_priced_turns else None
    )
    coverage_complete = fully_costed == linked_count
    return {
        "completed_tasks": int(completed or 0),
        "linked_completed_tasks": linked_count,
        "fully_observed_linked_tasks": fully_observed,
        "fully_costed_linked_tasks": fully_costed,
        "linked_priced_turns": linked_priced_turns,
        "linked_unaccounted_turns": linked_unaccounted_turns,
        "task_cost_coverage_complete": coverage_complete,
        "linked_task_cost_usd": (
            round(linked_cost or 0.0, 4) if coverage_complete else None
        ),
        "cost_per_linked_task": (
            round((linked_cost or 0.0) / linked_count, 4)
            if linked_count and coverage_complete else None
        ),
    }


def _lifetime_summary(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """SELECT COUNT(*) AS agents,
                  COUNT(*) FILTER (
                      WHERE status IN ('running', 'starting')
                  ) AS active_agents,
                  COALESCE(SUM(cost_usd), 0) AS cost_usd,
                  COALESCE(SUM(total_turns), 0) AS turns,
                  COALESCE(SUM(total_tool_calls), 0) AS tool_calls
           FROM sessions"""
    ).fetchone()
    return {
        "agents": int(row["agents"] or 0),
        "active_agents": int(row["active_agents"] or 0),
        "cost_usd": round(float(row["cost_usd"] or 0), 4),
        "turns": int(row["turns"] or 0),
        "tool_calls": int(row["tool_calls"] or 0),
    }


def _subagent_buckets(conn: sqlite3.Connection, since: str) -> tuple[dict, dict]:
    """Split the `subagents` table by entity, not by event name.

    The table mixes background Bash tasks (task_type=local_bash) with real
    delegated subagents (local_agent for Claude, codex for Codex). They arrive
    on the same `subagent_start` event, so counting rows overstated delegation
    ~390x on the live DB. Rows with an unknown task_type are reported as
    `unclassified` rather than assumed to be either.
    """
    rows = conn.execute(
        """SELECT task_type, status, COUNT(*) AS count
           FROM subagents
           WHERE date(started_at) >= date('now', ?)
           GROUP BY task_type, status""",
        (since,),
    ).fetchall()

    def _empty() -> dict:
        return {"completed": 0, "failed": 0, "running": 0, "stopped": 0,
                "unclassified": 0, "total": 0}

    subagents, background = _empty(), _empty()
    for row in rows:
        count = int(row["count"] or 0)
        bucket = background if row["task_type"] == "local_bash" else subagents
        if row["task_type"] not in ("local_bash", "local_agent", "codex"):
            bucket["unclassified"] += count
        elif row["status"] in bucket:
            bucket[row["status"]] += count
        bucket["total"] += count
    return subagents, background


def _reliability(conn: sqlite3.Connection, since: str, tasks: dict) -> dict:
    subagents, background_tasks = _subagent_buckets(conn, since)

    voice = conn.execute(
        """SELECT COUNT(*) AS entries,
                  COALESCE(SUM(duration_sec), 0) AS duration_sec,
                  COALESCE(SUM(cost_usd), 0) AS cost_usd
           FROM voice_costs
           WHERE date(ts) >= date('now', ?)""",
        (since,),
    ).fetchone()
    tool_error_rows = conn.execute(
        """SELECT e.runtime, e.tool_name, COUNT(*) AS error_count,
                  MAX(e.ts) AS last_seen,
                  (
                      SELECT recent.error_text
                      FROM tool_errors recent
                      WHERE recent.runtime = e.runtime
                        AND recent.tool_name = e.tool_name
                        AND date(recent.ts) >= date('now', ?)
                      ORDER BY recent.ts DESC, recent.id DESC
                      LIMIT 1
                  ) AS last_error
           FROM tool_errors e
           WHERE date(e.ts) >= date('now', ?)
           GROUP BY e.runtime, e.tool_name
           ORDER BY error_count DESC, e.tool_name ASC""",
        (since, since),
    ).fetchall()
    tool_error_count = conn.execute(
        """SELECT COUNT(*) FROM tool_errors
           WHERE date(ts) >= date('now', ?)""",
        (since,),
    ).fetchone()[0]
    turn_usage = conn.execute(
        """SELECT COUNT(*) AS recorded_rows,
                  COUNT(cost_usd) AS priced_rows,
                  COUNT(*) - COUNT(cost_usd) AS unaccounted_rows,
                  MIN(ts) AS observed_from
           FROM turn_usage
           WHERE date(ts) >= date('now', ?)""",
        (since,),
    ).fetchone()
    tool_error_coverage = _collector_coverage(
        conn,
        "tool_error_collector_started_at",
        since,
    )
    turn_usage_coverage = _collector_coverage(
        conn,
        "turn_usage_collector_started_at",
        since,
    )
    return {
        "subagents": subagents,
        "background_tasks": background_tasks,
        "voice": {
            "entries": int(voice["entries"] or 0),
            "duration_sec": round(float(voice["duration_sec"] or 0), 1),
            "cost_usd": round(float(voice["cost_usd"] or 0), 4),
        },
        "task_linkage": {
            "linked": tasks["linked_completed_tasks"],
            "total": tasks["completed_tasks"],
        },
        "tool_errors": {
            **tool_error_coverage,
            "recorded_rows": int(tool_error_count or 0),
            "items": [
                {
                    "runtime": row["runtime"],
                    "tool_name": row["tool_name"],
                    "count": int(row["error_count"] or 0),
                    "last_error": row["last_error"],
                    "last_seen": row["last_seen"],
                }
                for row in tool_error_rows
            ],
        },
        "turn_usage": {
            **turn_usage_coverage,
            "recorded_rows": int(turn_usage["recorded_rows"] or 0),
            "priced_rows": int(turn_usage["priced_rows"] or 0),
            "unaccounted_rows": int(turn_usage["unaccounted_rows"] or 0),
            "observed_from": turn_usage["observed_from"],
            "historical_rows_unknown": not turn_usage_coverage[
                "coverage_complete"
            ],
        },
    }


def _retention(
    conn: sqlite3.Connection,
    since: str,
    days: int,
    now: datetime,
) -> dict:
    retained = conn.execute(
        """SELECT MIN(ts) AS first_ts, MAX(ts) AS last_ts
           FROM logs
           WHERE type = 'status' AND content LIKE '%turn ended%'"""
    ).fetchone()
    observed = conn.execute(
        """SELECT MIN(ts) AS first_ts, MAX(ts) AS last_ts
           FROM logs
           WHERE type = 'status'
             AND content LIKE '%turn ended%'
             AND date(ts) >= date('now', ?)""",
        (since,),
    ).fetchone()
    requested_from = (now - timedelta(days=days - 1)).date()
    retained_from = retained["first_ts"]
    complete = bool(
        retained_from
        and datetime.fromisoformat(retained_from).date() <= requested_from
    )
    return {
        "requested_from": requested_from.isoformat(),
        "observed_from": observed["first_ts"],
        "observed_to": observed["last_ts"],
        "retained_from": retained_from,
        "complete": complete,
    }


def build_usage_analytics(
    days: int = 7,
    capacity: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """Build one coherent analytics snapshot inside a SQLite read transaction."""
    days = max(1, min(int(days), 9999))
    since = _calendar_since(days)
    now = now or datetime.now(timezone.utc)
    with _conn() as conn:
        conn.execute("BEGIN")
        try:
            daily = _daily_usage(conn, days)
            providers = _provider_rollup(daily)
            agents = _agent_rows(conn, since)
            models = _model_rows(conn, since)
            tasks = _task_summary(conn, since)
            lifetime = _lifetime_summary(conn)
            reliability = _reliability(conn, since, tasks)
            period = _retention(conn, since, days, now)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    agent_turns = sum(provider["turns"] for provider in providers.values())
    priced_turns = sum(
        provider["priced_turns"] for provider in providers.values()
    )
    unaccounted_turns = agent_turns - priced_turns
    observed_cost = (
        round(
            sum(
                provider["cost_usd"]
                for provider in providers.values()
                if provider["cost_usd"] is not None
            ),
            4,
        )
        if priced_turns else None if agent_turns else 0.0
    )
    return {
        "generated_at": now.isoformat(),
        "period": {"days": days, **period},
        "capacity": capacity or {},
        "summary": {
            "observed_cost_usd": observed_cost,
            "agent_turns": agent_turns,
            "priced_turns": priced_turns,
            "unaccounted_turns": unaccounted_turns,
            **tasks,
            "lifetime": lifetime,
        },
        "providers": providers,
        "daily": daily,
        "agents": agents,
        "models": models,
        "reliability": reliability,
    }
