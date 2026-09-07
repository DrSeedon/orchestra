"""Validation shared by pipeline, session admission and MCP dispatch."""

import json
import re


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
