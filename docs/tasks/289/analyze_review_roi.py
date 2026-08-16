#!/usr/bin/env python3
"""Build sanitized, reproducible aggregates for task #289.

The script never emits or persists raw log content. It reads a WAL-safe SQLite
snapshot, extracts only typed fields needed for review accounting, and writes
aggregate JSON. Review prose is reduced to headings/status markers and hashes.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import re
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REVIEW_TOOL = "mcp__orchestra__codex_review"
REVIEW_USAGE_PREFIX = "codex-review:"
REVIEW_NAME_RE = re.compile(r"codex[-_]review", re.I)
TASK_RE = re.compile(r"(?:^|/)docs/tasks/([^/]+)/")
ROUND_RE = re.compile(r"(?im)^##\s+(?:round(?:\s|\()|re-review status\b)")


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def percentile(values: Iterable[float], q: float) -> float | None:
    xs = sorted(float(x) for x in values)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def summary(values: Iterable[float]) -> dict[str, float | int | None]:
    xs = [float(x) for x in values]
    return {
        "n": len(xs),
        "median": statistics.median(xs) if xs else None,
        "p90": percentile(xs, 0.90),
        "mean": statistics.fmean(xs) if xs else None,
        "sum": sum(xs),
    }


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p using the probability-ordering definition."""
    row1, row2, col1 = a + b, c + d, a + c
    total = row1 + row2

    def probability(x: int) -> float:
        return (
            math.comb(col1, x)
            * math.comb(total - col1, row1 - x)
            / math.comb(total, row1)
        )

    lo = max(0, row1 - (total - col1))
    hi = min(row1, col1)
    observed = probability(a)
    return min(1.0, sum(probability(x) for x in range(lo, hi + 1) if probability(x) <= observed + 1e-15))


def phase_for(path: str) -> str:
    name = Path(path).name.lower()
    if "research" in name:
        return "research"
    if "plan" in name:
        return "plan"
    if "impl" in name or "implementation" in name:
        return "impl"
    return "other"


def task_for(path: str, fallback: str = "") -> str:
    match = TASK_RE.search(path)
    return match.group(1) if match else fallback


def parse_tool_args(raw: str) -> dict[str, Any] | None:
    # Orchestra log format is "tool_name: {json}". Never return raw text.
    try:
        value = json.loads(raw.partition(":")[2].strip())
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def counter_dict(counter: collections.Counter[Any]) -> dict[str, int]:
    return {str(key): int(value) for key, value in sorted(counter.items(), key=lambda x: str(x[0]))}


@dataclass
class Invocation:
    log_id: int
    session_id: str
    start: datetime
    output: str
    mode: str
    phase: str
    task: str
    scope_label: str
    cwd: str
    worktree_path: str
    scope: str
    author_runtime: str = "unknown"
    author_model: str = "unknown"
    end: datetime | None = None
    status: str = "unpaired"
    caller_quiescent: bool | None = None
    foreign_turns: int = 0
    usage_cost: float | None = None
    usage_input: int | None = None
    usage_cached: int | None = None
    usage_output: int | None = None

    @property
    def wall_seconds(self) -> float | None:
        if not self.end:
            return None
        return max(0.0, (self.end - self.start).total_seconds())


def baseline(tsv_dir: Path) -> dict[str, Any]:
    with (tsv_dir / "reviews-graded.tsv").open(newline="", encoding="utf-8") as fh:
        graded = list(csv.DictReader(fh, delimiter="\t"))
    with (tsv_dir / "codex-review-calls.tsv").open(newline="", encoding="utf-8") as fh:
        calls = list(csv.DictReader(fh, delimiter="\t"))
    with (tsv_dir / "blind-grades-raw.tsv").open(newline="", encoding="utf-8") as fh:
        blind = list(csv.DictReader(fh, delimiter="\t"))

    real_reviews = [row for row in graded if row["is_review"] == "yes"]
    arms: dict[str, Any] = {}
    for arm in ("sol", "claude"):
        rows = [row for row in real_reviews if row["worker_backend"] == arm]
        substantive = [int(row["n_substantive"]) for row in rows]
        arms[arm] = {
            "n": len(rows),
            "zero_substantive": sum(value == 0 for value in substantive),
            "blocking_present": sum(row["max_severity"] == "blocking" for row in rows),
            "median_substantive": statistics.median(substantive),
            "mean_substantive": statistics.fmean(substantive),
        }
    sol, claude = arms["sol"], arms["claude"]
    return {
        "files": {
            "blind_rows": len(blind),
            "graded_rows": len(graded),
            "call_rows": len(calls),
            "distinct_blind_ids": len({row["rid"] for row in blind}),
        },
        "reader_test_contaminants": sum(row["is_review"] != "yes" for row in graded),
        "clean_arms": arms,
        "fisher_zero_substantive_p": fisher_two_sided(
            sol["zero_substantive"],
            sol["n"] - sol["zero_substantive"],
            claude["zero_substantive"],
            claude["n"] - claude["zero_substantive"],
        ),
        "call_modes": counter_dict(collections.Counter("resume" if row["resume"] == "true" else row["mode"] for row in calls)),
        "call_backends": counter_dict(collections.Counter(row["worker_backend"] for row in calls)),
    }


def author_attribution(conn: sqlite3.Connection, session_id: str, start: datetime) -> tuple[str, str]:
    # A review call happens inside a turn; turn_usage is recorded at turn end. The first
    # same-session usage event after the call is therefore preferred, with the latest
    # preceding event as a bounded fallback.
    iso = start.isoformat()
    row = conn.execute(
        """
        SELECT runtime,model,ts FROM turn_usage
        WHERE session_id=? AND event_id NOT LIKE ? AND ts>=?
        ORDER BY ts LIMIT 1
        """,
        (session_id, REVIEW_USAGE_PREFIX + "%", iso),
    ).fetchone()
    if row and (parse_ts(row["ts"]) - start).total_seconds() <= 12 * 3600:
        return row["runtime"] or "unknown", row["model"] or "unknown"
    row = conn.execute(
        """
        SELECT runtime,model FROM turn_usage
        WHERE session_id=? AND event_id NOT LIKE ? AND ts<?
        ORDER BY ts DESC LIMIT 1
        """,
        (session_id, REVIEW_USAGE_PREFIX + "%", iso),
    ).fetchone()
    return (row["runtime"] or "unknown", row["model"] or "unknown") if row else ("unknown", "unknown")


def load_invocations(conn: sqlite3.Connection, cutoff: datetime) -> list[Invocation]:
    rows = conn.execute(
        """
        SELECT l.id,l.session_id,l.ts,l.content,s.scope,s.cwd,s.worktree_path,
               s.task_id
        FROM logs l JOIN sessions s ON s.id=l.session_id
        WHERE l.type='tool' AND l.tool_name=? AND l.ts<=?
        ORDER BY l.ts,l.id
        """,
        (REVIEW_TOOL, cutoff.isoformat()),
    ).fetchall()
    result: list[Invocation] = []
    for row in rows:
        args = parse_tool_args(row["content"])
        if args is None:
            continue
        start = parse_ts(row["ts"])
        assert start is not None
        output = str(args.get("output") or "CODEX_REVIEW.md")
        runtime, model = author_attribution(conn, row["session_id"], start)
        result.append(
            Invocation(
                log_id=int(row["id"]),
                session_id=row["session_id"],
                start=start,
                output=output,
                mode="resume" if args.get("resume") else str(args.get("mode") or "review"),
                phase=phase_for(output),
                task=task_for(output, str(row["task_id"] or "")),
                scope_label=Path(row["scope"]).name,
                cwd=row["cwd"] or "",
                worktree_path=row["worktree_path"] or "",
                scope=row["scope"] or "",
                author_runtime=runtime,
                author_model=model,
            )
        )
    return result


def pair_notifications(conn: sqlite3.Connection, invocations: list[Invocation], cutoff: datetime) -> None:
    rows = conn.execute(
        """
        SELECT id,session_id,ts,content FROM logs
        WHERE type='user_message' AND ts<=?
          AND content LIKE '[Background job%Codex%'
        ORDER BY ts,id
        """,
        (cutoff.isoformat(),),
    ).fetchall()
    notifications: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        raw = row["content"]
        if raw.startswith("[Background job completed]"):
            status = "completed"
        elif raw.startswith("[Background job FAILED]"):
            status = "failed"
        elif raw.startswith("[Background job TIMED OUT]"):
            status = "timed_out"
        else:
            continue
        notifications[row["session_id"]].append(
            {"id": int(row["id"]), "ts": parse_ts(row["ts"]), "raw": raw, "status": status, "used": False}
        )

    for invocation in invocations:
        options = notifications.get(invocation.session_id, [])
        match = next(
            (
                item
                for item in options
                if not item["used"]
                and item["ts"] >= invocation.start
                and invocation.output in item["raw"]
            ),
            None,
        )
        if match is None:
            continue
        match["used"] = True
        invocation.end = match["ts"]
        invocation.status = match["status"]
        activity = conn.execute(
            """
            SELECT COUNT(*) FROM logs
            WHERE session_id=? AND ts>? AND ts<?
              AND type='tool'
            """,
            (invocation.session_id, invocation.start.isoformat(), invocation.end.isoformat()),
        ).fetchone()[0]
        invocation.caller_quiescent = activity == 0
        invocation.foreign_turns = conn.execute(
            """
            SELECT COUNT(*) FROM turn_usage
            WHERE session_id<>? AND ts>? AND ts<?
              AND event_id NOT LIKE ?
            """,
            (
                invocation.session_id,
                invocation.start.isoformat(),
                invocation.end.isoformat(),
                REVIEW_USAGE_PREFIX + "%",
            ),
        ).fetchone()[0]


def pair_usage(conn: sqlite3.Connection, invocations: list[Invocation]) -> None:
    by_session: dict[str, list[sqlite3.Row]] = collections.defaultdict(list)
    for row in conn.execute(
        """
        SELECT session_id,ts,cost_usd,input_tokens,cache_read_tokens,output_tokens
        FROM turn_usage WHERE event_id LIKE ? ORDER BY ts,id
        """,
        (REVIEW_USAGE_PREFIX + "%",),
    ):
        by_session[row["session_id"]].append(row)
    used: set[tuple[str, str]] = set()
    for invocation in invocations:
        end_bound = invocation.end or (invocation.start.replace(microsecond=0))
        candidates = []
        for row in by_session.get(invocation.session_id, []):
            key = (row["session_id"], row["ts"])
            ts = parse_ts(row["ts"])
            if key in used or ts < invocation.start:
                continue
            # Notifications can trail usage persistence slightly; allow 10 minutes.
            if invocation.end and ts > invocation.end.replace(microsecond=0) and (ts - invocation.end).total_seconds() > 600:
                continue
            candidates.append((abs((ts - end_bound).total_seconds()), key, row))
        if not candidates:
            continue
        _, key, row = min(candidates, key=lambda x: x[0])
        used.add(key)
        invocation.usage_cost = float(row["cost_usd"]) if row["cost_usd"] is not None else None
        invocation.usage_input = int(row["input_tokens"] or 0)
        invocation.usage_cached = int(row["cache_read_tokens"] or 0)
        invocation.usage_output = int(row["output_tokens"] or 0)


def resolve_artifact(invocation: Invocation) -> Path | None:
    output = Path(invocation.output)
    candidates: list[Path] = [output] if output.is_absolute() else []
    if not output.is_absolute():
        for base in (invocation.worktree_path, invocation.cwd, invocation.scope):
            if base:
                candidates.append(Path(base) / output)
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def split_rounds(text: str) -> list[str]:
    starts = [match.start() for match in ROUND_RE.finditer(text)]
    if not starts:
        return [text]
    parts = [text[: starts[0]]]
    parts.extend(text[starts[i] : starts[i + 1]] for i in range(len(starts) - 1))
    parts.append(text[starts[-1] :])
    return [part for part in parts if part.strip()]


def count_findings(text: str) -> collections.Counter[str]:
    counts: collections.Counter[str] = collections.Counter()
    for severity in ("blocking", "suggestion", "question", "nit"):
        patterns = (
            rf"(?im)^\s*(?:[-*]\s*)?\[{severity}\]\s+",
            rf"(?im)^\s*(?:[-*]\s*)?\*{{0,2}}{severity}\*{{0,2}}(?:\([^)]*\))?\s*[:—-]",
            rf"(?im)^\s*#{3,4}\s+{severity}\b",
        )
        counts[severity] = sum(len(re.findall(pattern, text)) for pattern in patterns)
    # Numbered lists under a dedicated severity heading are common. Add their
    # numbered items only when no prefixed item of that severity was found.
    for severity in ("blocking", "suggestion"):
        if counts[severity]:
            continue
        match = re.search(
            rf"(?ims)^#{2,4}\s+{severity}\b.*?\n(.*?)(?=^#{2,4}\s+|\Z)", text
        )
        if match:
            counts[severity] = len(re.findall(r"(?m)^\s*\d+\.\s+", match.group(1)))
    return counts


def artifact_grade(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    rounds = split_rounds(text)
    first = count_findings(rounds[0])
    all_findings = count_findings(text)
    final_verdicts = re.findall(r"(?ims)^##\s+Verdict\b\s*(.*?)(?=^##\s+|\Z)", text)
    final_verdict = final_verdicts[-1].strip().lower() if final_verdicts else ""
    if re.search(r"\b(approved|approve|ack|no blockers|no blocking)\b", final_verdict) and not re.search(
        r"\b(not approved|changes requested|blocking.*remain|no-go|reject)\b", final_verdict
    ):
        verdict_class = "approved"
    elif re.search(r"\b(changes requested|blocking.*remain|not approved|no-go|reject)\b", final_verdict):
        verdict_class = "changes_requested"
    elif final_verdict:
        verdict_class = "other"
    else:
        verdict_class = "missing"

    follow_up = "\n".join(rounds[1:])
    status_prefix = r"(?im)^\s*(?:(?:[-*]|\d+[.)])\s*)?(?:\*{0,2})"
    status_counts = {
        "fixed_or_resolved": len(re.findall(status_prefix + r"(?:fixed|resolved|accepted|ack(?:nowledged)?)\b", follow_up)),
        "rejected_or_not_problem": len(re.findall(status_prefix + r"(?:rejected|not a problem|refuted|withdrawn)\b", follow_up)),
        "still_open": len(re.findall(status_prefix + r"(?:still open|still broken|blocking findings remain)\b", follow_up)),
    }
    return {
        "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
        "bytes": len(text.encode("utf-8", errors="replace")),
        "rounds": len(rounds),
        "first_findings": counter_dict(first),
        "all_findings": counter_dict(all_findings),
        "final_verdict": verdict_class,
        "resolution_markers": status_counts,
    }


def artifact_census(repo_roots: Iterable[Path], cutoff: datetime) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in repo_roots:
        task_root = root / "docs" / "tasks"
        if not task_root.is_dir():
            continue
        for path in task_root.rglob("*.md"):
            if not REVIEW_NAME_RE.search(path.name):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            # Files modified after the frozen DB cutoff are excluded.
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified > cutoff:
                continue
            grade = artifact_grade(path)
            records.append(
                {
                    "repo": root.resolve().name,
                    "phase": phase_for(path.name),
                    "task": path.parent.name,
                    **grade,
                }
            )
    finding_totals: collections.Counter[str] = collections.Counter()
    resolution_totals: collections.Counter[str] = collections.Counter()
    for record in records:
        finding_totals.update(record["first_findings"])
        resolution_totals.update(record["resolution_markers"])
    return {
        "artifacts": len(records),
        "distinct_hashes": len({record["sha256"] for record in records}),
        "by_repo": counter_dict(collections.Counter(record["repo"] for record in records)),
        "by_phase": counter_dict(collections.Counter(record["phase"] for record in records)),
        "by_final_verdict": counter_dict(collections.Counter(record["final_verdict"] for record in records)),
        "by_round_count": counter_dict(collections.Counter(record["rounds"] for record in records)),
        "initial_finding_markers": counter_dict(finding_totals),
        "resolution_markers": counter_dict(resolution_totals),
        "zero_actionable_marker_artifacts": sum(
            record["first_findings"].get("blocking", 0) + record["first_findings"].get("suggestion", 0) == 0
            for record in records
        ),
    }


def provider_window(provider_usage: str) -> dict[str, Any] | None:
    try:
        codex = (json.loads(provider_usage).get("codex") or {})
    except (json.JSONDecodeError, AttributeError):
        return None
    windows = codex.get("windows")
    if not isinstance(windows, list) or not windows or not isinstance(windows[0], dict):
        return None
    value = windows[0]
    utilization = value.get("utilization")
    if isinstance(utilization, bool) or not isinstance(utilization, (int, float)):
        return None
    return {"utilization": float(utilization), "resets_at": value.get("resets_at")}


def latest_quota_segment(
    conn: sqlite3.Connection, cutoff: datetime
) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT ts,provider_usage FROM usage_snapshots
        WHERE ts<=? AND provider_usage LIKE '%codex%'
        ORDER BY ts
        """,
        (cutoff.isoformat(),),
    ).fetchall()
    parsed = [(parse_ts(row["ts"]), provider_window(row["provider_usage"])) for row in rows]
    parsed = [(ts, value) for ts, value in parsed if ts and value]
    if not parsed:
        return None
    start_index = 0
    for index in range(1, len(parsed)):
        previous, current = parsed[index - 1][1], parsed[index][1]
        # A falling utilization is an observed reset/new window. Small
        # resets_at jitter is deliberately ignored.
        if current["utilization"] < previous["utilization"]:
            start_index = index
    segment = parsed[start_index:]
    start, end = segment[0][0], segment[-1][0]

    def totals(where: str) -> sqlite3.Row:
        return conn.execute(
            f"""
            SELECT COUNT(*) n,SUM(cost_usd) cost,SUM(input_tokens) input,
                   SUM(cache_read_tokens) cached,SUM(output_tokens) output
            FROM turn_usage WHERE {where} AND ts>=? AND ts<=?
            """,
            (start.isoformat(), cutoff.isoformat()),
        ).fetchone()

    all_codex, reviews = totals("runtime='codex'"), totals("event_id LIKE 'codex-review:%'")
    cost_share = float(reviews["cost"] or 0) / float(all_codex["cost"] or 1)
    delta = segment[-1][1]["utilization"] - segment[0][1]["utilization"]
    return {
        "start": start.isoformat(),
        "last_snapshot": end.isoformat(),
        "first_utilization": segment[0][1]["utilization"],
        "last_utilization": segment[-1][1]["utilization"],
        "integer_point_delta": delta,
        "codex_turns": int(all_codex["n"] or 0),
        "review_turns": int(reviews["n"] or 0),
        "codex_cost_usd": float(all_codex["cost"] or 0),
        "review_cost_usd": float(reviews["cost"] or 0),
        "review_cost_share": cost_share,
        "quota_point_allocation_proxy": delta * cost_share,
        "caveat": "Integer provider delta is global. The point allocation is proportional-cost accounting, not causal attribution.",
    }


def task_cycle_stats(
    conn: sqlite3.Connection,
    invocations: list[Invocation],
    cutoff: datetime,
) -> dict[str, Any]:
    project_aliases = {
        row["id"]: {row["id"], row["name"], Path(row["scope"] or row["id"]).name}
        for row in conn.execute("SELECT id,name,scope FROM tm_projects")
    }
    by_key: dict[tuple[str, int], list[Invocation]] = collections.defaultdict(list)
    for invocation in invocations:
        if invocation.task.isdigit() and invocation.end:
            by_key[(invocation.scope_label.lower(), int(invocation.task))].append(invocation)

    shares: list[float] = []
    matched = 0
    for task in conn.execute(
        """
        SELECT project_id,par_number,created_at,completed_at FROM tm_tasks
        WHERE completed_at IS NOT NULL
        """
    ):
        labels = {str(value).lower() for value in project_aliases.get(task["project_id"], {task["project_id"]})}
        calls = []
        for label in labels:
            calls.extend(by_key.get((label, int(task["par_number"])), []))
        if not calls:
            continue
        created, completed = parse_ts(task["created_at"]), parse_ts(task["completed_at"])
        if not created or not completed or completed <= created or completed > cutoff:
            continue
        in_cycle = [call for call in calls if call.start >= created and call.end and call.end <= completed]
        if not in_cycle:
            continue
        intervals = sorted((call.start, call.end) for call in in_cycle if call.end)
        merged: list[list[datetime]] = []
        for start, end in intervals:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            elif end > merged[-1][1]:
                merged[-1][1] = end
        review_seconds = sum((end - start).total_seconds() for start, end in merged)
        cycle_seconds = (completed - created).total_seconds()
        shares.append(review_seconds / cycle_seconds)
        matched += 1
    return {
        "matched_completed_tasks": matched,
        "review_wall_share": summary(shares),
        "note": "Task cycle is tracker created_at→completed_at; review intervals are unioned. This is a task-path upper bound, not synchronous HTTP/user delay.",
    }


def live_cohort(conn: sqlite3.Connection, cutoff: datetime) -> tuple[dict[str, Any], list[Invocation]]:
    invocations = load_invocations(conn, cutoff)
    pair_notifications(conn, invocations, cutoff)
    pair_usage(conn, invocations)
    completed = [item for item in invocations if item.status == "completed" and item.wall_seconds is not None]
    all_paired = [item for item in invocations if item.wall_seconds is not None]
    usage = [item for item in invocations if item.usage_cost is not None]
    usage_start = min((item.start for item in usage), default=None)

    codex_totals = None
    quota = None
    if usage_start:
        row = conn.execute(
            """
            SELECT COUNT(*) n,SUM(cost_usd) cost,SUM(input_tokens) input,
                   SUM(cache_read_tokens) cached,SUM(output_tokens) output
            FROM turn_usage WHERE runtime='codex' AND ts>=? AND ts<=?
            """,
            (usage_start.isoformat(), cutoff.isoformat()),
        ).fetchone()
        review_cost = sum(item.usage_cost or 0 for item in usage)
        codex_totals = {
            "window_start": usage_start.isoformat(),
            "turns": int(row["n"] or 0),
            "cost_usd": float(row["cost"] or 0),
            "review_cost_share": review_cost / float(row["cost"] or 1),
            "review_turn_share": len(usage) / int(row["n"] or 1),
        }
        snapshots = conn.execute(
            """
            SELECT ts,provider_usage FROM usage_snapshots
            WHERE ts>=? AND ts<=? AND provider_usage LIKE '%codex%'
            ORDER BY ts
            """,
            (usage_start.isoformat(), cutoff.isoformat()),
        ).fetchall()
        parsed = [(parse_ts(row["ts"]), provider_window(row["provider_usage"])) for row in snapshots]
        parsed = [(ts, value) for ts, value in parsed if value]
        if parsed:
            resets = {value.get("resets_at") for _, value in parsed}
            quota = {
                "first": parsed[0][1]["utilization"],
                "last": parsed[-1][1]["utilization"],
                "integer_point_delta": parsed[-1][1]["utilization"] - parsed[0][1]["utilization"],
                "reset_values": len(resets),
                "attribution": "Global integer provider counter; cannot causally allocate to reviews. Cost share above is the accounting proxy.",
            }

    artifacts: dict[tuple[str, str], dict[str, Any]] = {}
    for invocation in invocations:
        key = (invocation.scope, invocation.output)
        if key in artifacts:
            continue
        path = resolve_artifact(invocation)
        artifacts[key] = artifact_grade(path) if path else {"missing": True}

    initial_findings: collections.Counter[str] = collections.Counter()
    resolution_markers: collections.Counter[str] = collections.Counter()
    for artifact in artifacts.values():
        initial_findings.update(artifact.get("first_findings", {}))
        resolution_markers.update(artifact.get("resolution_markers", {}))
    resolved_grades = [artifact for artifact in artifacts.values() if not artifact.get("missing")]
    zero_actionable_marker_artifacts = sum(
        artifact.get("first_findings", {}).get("blocking", 0)
        + artifact.get("first_findings", {}).get("suggestion", 0)
        == 0
        for artifact in resolved_grades
    )
    accepted = resolution_markers["fixed_or_resolved"]
    total_wall_minutes = sum(item.wall_seconds or 0 for item in completed) / 60
    total_cost = sum(item.usage_cost or 0 for item in usage)

    phase_metrics: dict[str, Any] = {}
    for phase in ("research", "plan", "impl", "other"):
        items = [item for item in invocations if item.phase == phase]
        done = [item for item in items if item.status == "completed" and item.wall_seconds is not None]
        paid = [item for item in items if item.usage_cost is not None]
        phase_metrics[phase] = {
            "invocations": len(items),
            "completed": len(done),
            "failed_or_timeout": sum(item.status in {"failed", "timed_out"} for item in items),
            "wall_seconds": summary(item.wall_seconds for item in done if item.wall_seconds is not None),
            "cost_usd": summary(item.usage_cost for item in paid if item.usage_cost is not None),
        }

    author_metrics: dict[str, Any] = {}
    for model in sorted({item.author_model for item in invocations}):
        items = [item for item in invocations if item.author_model == model]
        done = [item for item in items if item.status == "completed" and item.wall_seconds is not None]
        author_metrics[model] = {
            "invocations": len(items),
            "completed": len(done),
            "failed_or_timeout": sum(item.status in {"failed", "timed_out"} for item in items),
            "wall_seconds": summary(item.wall_seconds for item in done if item.wall_seconds is not None),
        }

    result = {
        "cutoff": cutoff.isoformat(),
        "invocations": len(invocations),
        "paired": len(all_paired),
        "status": counter_dict(collections.Counter(item.status for item in invocations)),
        "mode": counter_dict(collections.Counter(item.mode for item in invocations)),
        "phase": counter_dict(collections.Counter(item.phase for item in invocations)),
        "phase_metrics": phase_metrics,
        "scope": counter_dict(collections.Counter(item.scope_label for item in invocations)),
        "author_runtime": counter_dict(collections.Counter(item.author_runtime for item in invocations)),
        "author_model": counter_dict(collections.Counter(item.author_model for item in invocations)),
        "reviewer_model": {"gpt-5.6-sol": len(invocations)},
        "author_model_metrics": author_metrics,
        "wall_seconds_completed": summary(item.wall_seconds for item in completed if item.wall_seconds is not None),
        "wall_seconds_all_paired": summary(item.wall_seconds for item in all_paired if item.wall_seconds is not None),
        "caller_quiescent": counter_dict(collections.Counter(str(item.caller_quiescent) for item in all_paired)),
        "reviews_with_foreign_turn_overlap": sum(item.foreign_turns > 0 for item in all_paired),
        "foreign_turns_during_reviews": sum(item.foreign_turns for item in all_paired),
        "unique_artifact_paths": len(artifacts),
        "resolved_artifacts": sum(not value.get("missing") for value in artifacts.values()),
        "initial_finding_markers": counter_dict(initial_findings),
        "resolution_markers": counter_dict(resolution_markers),
        "artifact_rounds": counter_dict(collections.Counter(
            artifact.get("rounds", 0) for artifact in resolved_grades
        )),
        "zero_actionable_marker_artifacts": {
            "count": zero_actionable_marker_artifacts,
            "denominator": len(resolved_grades),
            "rate": zero_actionable_marker_artifacts / len(resolved_grades) if resolved_grades else None,
            "caveat": "Syntactic marker proxy only; not a ground-truth zero-value judgment.",
        },
        "attributed_usage": {
            "reviews": len(usage),
            "cost_usd": summary(item.usage_cost for item in usage if item.usage_cost is not None),
            "input_tokens": summary(item.usage_input for item in usage if item.usage_input is not None),
            "cached_input_tokens": summary(item.usage_cached for item in usage if item.usage_cached is not None),
            "output_tokens": summary(item.usage_output for item in usage if item.usage_output is not None),
            "cache_ratio": (
                sum(item.usage_cached or 0 for item in usage) / sum(item.usage_input or 0 for item in usage)
                if sum(item.usage_input or 0 for item in usage)
                else None
            ),
        },
        "yield_proxy": {
            "accepted_or_fixed_markers": accepted,
            "per_completed_review_turn": accepted / len(completed) if completed else None,
            "per_review_wall_minute": accepted / total_wall_minutes if total_wall_minutes else None,
            "per_api_equivalent_dollar": accepted / total_cost if total_cost else None,
            "caveat": "Resolution markers are syntactic author/reviewer follow-through, not independent truth grading.",
        },
        "codex_accounting_window": codex_totals,
        "quota_window": quota,
        "latest_quota_segment": latest_quota_segment(conn, cutoff),
        "task_cycles": task_cycle_stats(conn, invocations, cutoff),
    }
    return result, invocations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    args = parser.parse_args()

    cutoff = parse_ts(args.cutoff)
    if cutoff is None:
        raise SystemExit("invalid cutoff")
    with sqlite3.connect(f"file:{args.db}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        live, invocations = live_cohort(conn, cutoff)
        scopes = sorted({Path(item.scope) for item in invocations if Path(item.scope).is_dir()})
        # The current worktree represents Orchestra; skip the main checkout of
        # that same repository to avoid counting every artifact twice.
        roots = [args.repo_root]
        roots.extend(scope for scope in scopes if scope.resolve().name != "orchestra")
        evidence = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": {
                "sha256": hashlib.sha256(args.db.read_bytes()).hexdigest(),
                "bytes": args.db.stat().st_size,
                "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
                "cutoff": args.cutoff,
            },
            "baseline_2026_07_25": baseline(args.baseline),
            "live_db_retained_window": live,
            "available_artifact_census": artifact_census(roots, cutoff),
            "method_limits": [
                "The live logs table is retention-limited; invocations before its minimum timestamp are not reconstructed from DB.",
                "Filesystem artifact census includes available current repository trees, not deleted/unmerged files.",
                "Finding and resolution counts are syntax markers; quality/false positives require blinded ground truth.",
                "Task cycle uses tracker timestamps and is an upper bound on critical-path share, not synchronous user delay.",
            ],
        }
    args.out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "cutoff": args.cutoff,
        "invocations": live["invocations"],
        "paired": live["paired"],
        "resolved_artifacts": live["resolved_artifacts"],
        "artifact_census": evidence["available_artifact_census"]["artifacts"],
        "integrity_check": evidence["snapshot"]["integrity_check"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
