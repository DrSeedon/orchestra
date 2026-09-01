#!/usr/bin/env python3
"""Read-only accounting of the three Claude Workflow runs studied in #427."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


WORKFLOWS = (
    "wf_0ac5aab5-12d",
    "wf_4dacb762-819",
    "wf_d609dd9a-f8a",
)
USAGE_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)
# API-equivalent prices current in app/models.py on 2026-09-01. Cache read/create
# are charged below at 0.1x/1.25x input, matching app/backend_claude.py.
CLAUDE_PRICES = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
}


def phase_from_prompt(workflow: str, prompt: str) -> str:
    if workflow == "wf_0ac5aab5-12d":
        if prompt.startswith('Design "Dynamic Workflows'):
            return "Design"
        if prompt.startswith("You are the risk/cost critic"):
            return "Stress"
        return "Map"
    if workflow == "wf_4dacb762-819":
        if prompt.startswith("You are a senior reviewer"):
            return "Find"
        if prompt.startswith("Completeness critic"):
            return "Critic"
        return "Verify"
    if prompt.startswith("Read ") or prompt.startswith("Adversarially verify"):
        return "Verify"
    if prompt.startswith("You are fixing confirmed defects"):
        return "Fix"
    if prompt.startswith("Adversarially review") or "adversarial review" in prompt[:800].lower():
        return "Review"
    return "Unknown"


def usage_sum(usages: list[dict]) -> dict[str, int]:
    return {
        key: sum(int(usage.get(key) or 0) for usage in usages)
        for key in USAGE_KEYS
    }


def claude_cost(model: str, usage: dict[str, int]) -> float:
    prices = CLAUDE_PRICES.get(model)
    if prices is None:
        return 0.0
    input_price, output_price = prices
    return (
        usage["input_tokens"] * input_price
        + usage["cache_creation_input_tokens"] * input_price * 1.25
        + usage["cache_read_input_tokens"] * input_price * 0.1
        + usage["output_tokens"] * output_price
    ) / 1_000_000


def read_rows(path: Path, cutoff: datetime | None = None) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            row = json.loads(line)
            timestamp = row.get("timestamp")
            if cutoff is not None and timestamp:
                observed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                if observed > cutoff:
                    continue
            rows.append(row)
    return rows


def analyze_agent(
    workflow: str,
    path: Path,
    terminal_ids: set[str],
    cutoff: datetime | None,
) -> dict:
    rows = read_rows(path, cutoff)
    if not rows:
        raise ValueError(f"agent has no rows at cutoff: {path}")
    prompt = str((rows[0].get("message") or {}).get("content") or "")
    request_usages: dict[str, dict] = {}
    request_seen: dict[str, list[dict]] = defaultdict(list)
    raw_usages: list[dict] = []
    model = ""
    structured_calls = 0
    structured_success = 0
    structured_errors = 0
    schema_error_seen = False
    schema_error_recovered = False
    attachments = {}

    for row in rows:
        attachment = row.get("attachment") or {}
        if attachment.get("type") == "deferred_tools_delta":
            attachments["deferred_tools"] = len(attachment.get("addedNames") or [])
        elif attachment.get("type") == "skill_listing":
            attachments["skills"] = attachment.get("skillCount")
            attachments["skill_listing_chars"] = len(attachment.get("content") or "")

        message = row.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use" and block.get("name") == "StructuredOutput":
                    structured_calls += 1
                elif block.get("type") == "tool_result":
                    text = str(block.get("content") or "")
                    if text == "Structured output provided successfully":
                        structured_success += 1
                        if schema_error_seen:
                            schema_error_recovered = True
                    elif text.startswith("Output does not match required schema:"):
                        structured_errors += 1
                        schema_error_seen = True

        if row.get("type") != "assistant":
            continue
        usage = message.get("usage")
        current_model = str(message.get("model") or "")
        if not isinstance(usage, dict) or current_model not in CLAUDE_PRICES:
            continue
        model = model or current_model
        raw_usages.append(usage)
        request_id = str(row.get("requestId") or "")
        if request_id:
            # A single provider response is split into multiple assistant rows.
            # The final row has the terminal output count; context fields stay fixed.
            request_seen[request_id].append(usage)
            request_usages[request_id] = usage

    context_variations = 0
    for usages in request_seen.values():
        signatures = {
            tuple(int(usage.get(key) or 0) for key in USAGE_KEYS[:3])
            for usage in usages
        }
        if len(signatures) != 1:
            context_variations += 1

    unique_usages = list(request_usages.values())
    raw = usage_sum(raw_usages)
    unique = usage_sum(unique_usages)
    first = usage_sum(unique_usages[:1])
    later = usage_sum(unique_usages[1:])
    agent_id = path.stem.removeprefix("agent-")
    return {
        "agent_id": agent_id,
        "phase": phase_from_prompt(workflow, prompt),
        "model": model,
        "terminal": agent_id in terminal_ids,
        "first_timestamp": rows[0].get("timestamp"),
        "last_timestamp": rows[-1].get("timestamp"),
        "raw_assistant_records": len(raw_usages),
        "unique_request_ids": len(unique_usages),
        "request_context_variations": context_variations,
        "raw_usage": raw,
        "unique_usage": unique,
        "raw_cost_usd": claude_cost(model, raw),
        "unique_cost_usd": claude_cost(model, unique),
        "first_request_usage": first,
        "later_request_usage": later,
        "structured_output": {
            "calls": structured_calls,
            "success": structured_success,
            "schema_errors": structured_errors,
            "error_seen": schema_error_seen,
            "error_then_success": schema_error_recovered,
        },
        "attachments": attachments,
    }


def cache_share(usage: dict[str, int]) -> float | None:
    denominator = (
        usage["cache_creation_input_tokens"]
        + usage["cache_read_input_tokens"]
    )
    if denominator == 0:
        return None
    return usage["cache_read_input_tokens"] / denominator


def combine_agents(agents: list[dict]) -> dict:
    raw_usage = usage_sum([agent["raw_usage"] for agent in agents])
    unique_usage = usage_sum([agent["unique_usage"] for agent in agents])
    first_usage = usage_sum([agent["first_request_usage"] for agent in agents])
    later_usage = usage_sum([agent["later_request_usage"] for agent in agents])
    structured = {
        key: sum(agent["structured_output"][key] for agent in agents)
        for key in ("calls", "success", "schema_errors")
    }
    structured["agents_with_schema_error"] = sum(
        bool(agent["structured_output"]["error_seen"]) for agent in agents
    )
    structured["agents_recovered_after_schema_error"] = sum(
        bool(agent["structured_output"]["error_then_success"]) for agent in agents
    )
    return {
        "agents": len(agents),
        "terminal_agents": sum(bool(agent["terminal"]) for agent in agents),
        "raw_assistant_records": sum(agent["raw_assistant_records"] for agent in agents),
        "unique_request_ids": sum(agent["unique_request_ids"] for agent in agents),
        "request_context_variations": sum(
            agent["request_context_variations"] for agent in agents
        ),
        "raw_usage": raw_usage,
        "unique_usage": unique_usage,
        "raw_cost_usd": sum(agent["raw_cost_usd"] for agent in agents),
        "unique_cost_usd": sum(agent["unique_cost_usd"] for agent in agents),
        "first_request_usage": first_usage,
        "first_request_cache_read_share": cache_share(first_usage),
        "later_request_usage": later_usage,
        "later_request_cache_read_share": cache_share(later_usage),
        "structured_output": structured,
    }


def analyze_workflow(root: Path, workflow: str, cutoff: datetime | None) -> dict:
    directory = root / "subagents" / "workflows" / workflow
    journal = read_rows(directory / "journal.jsonl")
    started_ids = {
        str(row.get("agentId")) for row in journal if row.get("type") == "started"
    }
    terminal_ids = {
        str(row.get("agentId")) for row in journal if row.get("type") == "result"
    }
    paths = []
    for path in sorted(directory.glob("agent-*.jsonl")):
        first = json.loads(path.open(encoding="utf-8", errors="replace").readline())
        timestamp = first.get("timestamp")
        if cutoff is not None and timestamp:
            observed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if observed > cutoff:
                continue
        paths.append(path)
    agents = [analyze_agent(workflow, path, terminal_ids, cutoff) for path in paths]
    if cutoff is not None and workflow == "wf_d609dd9a-f8a":
        # Every call in this script has a schema. The accepted StructuredOutput receipt
        # is timestamped in the agent transcript; journal entries are not timestamped.
        for agent in agents:
            agent["terminal"] = bool(agent["structured_output"]["success"])
        started_ids = {agent["agent_id"] for agent in agents}
        terminal_ids = {
            agent["agent_id"] for agent in agents if agent["terminal"]
        }
    phases = {}
    for phase in sorted({agent["phase"] for agent in agents}):
        phases[phase] = combine_agents(
            [agent for agent in agents if agent["phase"] == phase]
        )
    attachment_signatures = Counter(
        json.dumps(agent["attachments"], sort_keys=True) for agent in agents
    )
    result = combine_agents(agents)
    state_summary = None
    state_path = root / "workflows" / f"{workflow}.json"
    if cutoff is None and state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        progress = [
            row
            for row in state.get("workflowProgress", [])
            if row.get("type") == "workflow_agent"
        ]
        progress_ids = {str(row.get("agentId") or "") for row in progress}
        state_summary = {
            "status": state.get("status"),
            "timestamp": state.get("timestamp"),
            "agent_count": state.get("agentCount"),
            "progress_agents": len(progress),
            "progress_done": sum(row.get("state") == "done" for row in progress),
            "orphan_transcript_agents": sorted(
                agent["agent_id"]
                for agent in agents
                if agent["agent_id"] not in progress_ids
            ),
        }
    result.update(
        {
            "journal_started": len(started_ids),
            "journal_results": len(terminal_ids),
            "unfinished_or_unjournaled": len(started_ids - terminal_ids),
            "attachment_signatures": dict(attachment_signatures),
            "phases": phases,
            "completed_state": state_summary,
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-session-root",
        type=Path,
        default=(
            Path.home()
            / ".claude/projects/-mnt-data-Projects-Python-orchestra"
            / "bd702267-a0db-42f2-8808-b0d43e37ced3"
        ),
    )
    parser.add_argument(
        "--cutoff-utc",
        help="Include only agent rows at or before this ISO-8601 UTC timestamp",
    )
    args = parser.parse_args()
    cutoff = None
    if args.cutoff_utc:
        cutoff = datetime.fromisoformat(args.cutoff_utc.replace("Z", "+00:00"))
        if cutoff.tzinfo is None:
            raise SystemExit("--cutoff-utc must include an explicit UTC offset")
    result = {
        "snapshot_utc": (cutoff or datetime.now(timezone.utc)).isoformat(),
        "method": (
            "raw_assistant_records reproduces the task-card counter; unique_request_ids "
            "deduplicates split transcript rows by requestId and keeps the last usage snapshot"
        ),
        "workflows": {
            workflow: analyze_workflow(args.project_session_root, workflow, cutoff)
            for workflow in WORKFLOWS
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
