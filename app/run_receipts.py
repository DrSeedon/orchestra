"""Read-time task-run trace assembled from existing source tables."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import _conn


def _utc_iso(value: str | None) -> str:
    if value:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def build_task_run_trace(receipt_id: str, *, as_of: str | None = None) -> dict:
    """Return one run plus derived usage/log/review/merge facts, without storing copies."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM review_receipts WHERE receipt_id=? "
            "AND subject_kind='task_run'",
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise LookupError("task-run receipt not found")
        run = dict(row)
        live = run["completed_at"] is None
        effective_end = _utc_iso(as_of) if live else str(run["completed_at"])
        start = str(run["requested_at"])
        key = (run["session_id"], run["scope"], run["task_id"], start, effective_end)

        usage_rows = conn.execute(
            "SELECT runtime,model,ok,cost_usd,cost_unaccounted,input_tokens,output_tokens,"
            "cache_read_tokens,cache_create_tokens FROM turn_usage "
            "WHERE session_id=? AND scope=? AND task_id=? AND ts>=? AND ts<=? "
            "ORDER BY ts",
            key,
        ).fetchall()
        model_rows = conn.execute(
            "SELECT runtime,model,COUNT(*) AS turns FROM turn_usage "
            "WHERE session_id=? AND scope=? AND task_id=? AND ts>=? AND ts<=? "
            "GROUP BY runtime,model ORDER BY runtime,model",
            key,
        ).fetchall()
        tool_rows = conn.execute(
            "SELECT COALESCE(tool_name,'') AS tool_name,COUNT(*) AS calls FROM logs "
            "WHERE session_id=? AND ts>=? AND ts<=? AND type='tool' "
            "GROUP BY COALESCE(tool_name,'') ORDER BY calls DESC,tool_name",
            (run["session_id"], start, effective_end),
        ).fetchall()
        message_rows = conn.execute(
            "SELECT origin,COUNT(*) AS messages FROM logs "
            "WHERE session_id=? AND ts>=? AND ts<=? AND type='user_message' "
            "GROUP BY origin",
            (run["session_id"], start, effective_end),
        ).fetchall()
        reviews = [
            dict(item) for item in conn.execute(
                "SELECT receipt_id,requested_at,completed_at,status,coverage_outcome,"
                "verdict_present,verdict_value,author_outcome,outcome_evidence_ref "
                "FROM review_receipts WHERE subject_kind!='task_run' "
                "AND session_id=? AND scope=? AND task_id=? "
                "AND requested_at>=? AND requested_at<=? ORDER BY requested_at",
                key,
            ).fetchall()
        ]
        terminal = None
        gaps: list[str] = []
        operation_id = str(run["terminal_operation_id"] or "")
        if operation_id:
            operation = conn.execute(
                "SELECT result_json,finalization_json FROM merge_operations "
                "WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if operation is None:
                gaps.append("terminal_operation_missing")
            else:
                result = json.loads(operation["result_json"] or "{}")
                finalization = json.loads(operation["finalization_json"] or "{}")
                git = result.get("git") if isinstance(result.get("git"), dict) else {}
                terminal = {
                    "operation_id": operation_id,
                    "target_before": str(
                        git.get("target_before") or finalization.get("target_before") or ""
                    ),
                    "target_after": str(
                        git.get("target_after") or finalization.get("target_after") or ""
                    ),
                }
        if run["task_source"] == "legacy_inflight":
            gaps.append("acceptance_before_receipt")
        if not run["task_snapshot_ref"] and run["task_source"] != "legacy_inflight":
            gaps.append("task_snapshot_missing")
        origins = {item["origin"]: int(item["messages"]) for item in message_rows}
        cost_unaccounted = any(
            bool(item["cost_unaccounted"]) or item["cost_usd"] is None
            for item in usage_rows
        )
        if cost_unaccounted:
            gaps.append("usage_cost_unaccounted")
        usage = {
            "turns": len(usage_rows),
            "failed_turns": sum(1 for item in usage_rows if not item["ok"]),
            "cost_usd": (
                None
                if cost_unaccounted
                else round(sum(float(item["cost_usd"] or 0) for item in usage_rows), 6)
            ),
            "input_tokens": sum(int(item["input_tokens"]) for item in usage_rows),
            "output_tokens": sum(int(item["output_tokens"]) for item in usage_rows),
            "cache_read_tokens": sum(int(item["cache_read_tokens"]) for item in usage_rows),
            "cache_create_tokens": sum(int(item["cache_create_tokens"]) for item in usage_rows),
            "models": [dict(item) for item in model_rows],
        }
        run_view = {
            key: run[key] for key in (
                "receipt_id", "session_id", "worker_name", "scope", "task_id",
                "task_source", "task_stable_id", "task_snapshot_ref",
                "prompt_template_start", "prompt_template_end", "requested_at",
                "completed_at", "status", "failure_code", "terminal_operation_id",
            )
        }
        run_view.update(live=live, effective_end=effective_end)
        return {
            "run": run_view,
            "usage": usage,
            "tools": [dict(item) for item in tool_rows],
            "messages": {
                "direct_user": origins.get("user", 0),
                "agent": origins.get("agent", 0),
                "background_task": origins.get("background_task", 0),
                "other": sum(
                    count for origin, count in origins.items()
                    if origin not in {"user", "agent", "background_task"}
                ),
            },
            "reviews": reviews,
            "terminal_operation": terminal,
            "gaps": gaps,
            "references": {
                "logs": {"session_id": run["session_id"], "start": start, "end": effective_end},
                "turn_usage": {
                    "session_id": run["session_id"], "scope": run["scope"],
                    "task_id": run["task_id"], "start": start, "end": effective_end,
                },
            },
        }
