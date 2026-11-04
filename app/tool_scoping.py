"""Validation shared by pipeline, session admission and MCP dispatch."""

import json
import re


def role_tool_names(names: set[str], role: str) -> set[str]:
    """Schema profiles reduce irrelevant management tools; policy still owns access.

    Unknown/custom roles keep their complete configured tools. Explicit disabled_tools
    and access_mode are applied independently and always take precedence.
    """
    if role in {"reader", "reviewer"}:
        return names & {"read", "read_image", "grep", "glob", "read_tool_result_page", "read_log_result_page",
                        "get_worker_logs", "search_logs", "get_log_context",
                        "get_worker_info", "task_get", "task_list", "send_message", "update_progress"}
    if role == "worker":
        return names - {"list_orchestrators", "spawn_orchestrator", "spawn_worker",
                        "change_worker_model", "compact_worker", "wf_run"}
    return set(names)


def parse_disabled_tools(value) -> list[str]:
    """Accept exact, unqualified Orchestra tool names; reject malformed policy."""
    if isinstance(value, str):
        value = json.loads(value or "[]")
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name)
        for name in value
    ):
        raise ValueError("disabled_tools must be a list of exact Orchestra tool names")
    return sorted(set(value))
