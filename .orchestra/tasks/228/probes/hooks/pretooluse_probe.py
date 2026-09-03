#!/usr/bin/env python3
"""Isolated #228 probe: deny background Bash through PreToolUse."""

import json
import sys


payload = json.load(sys.stdin)
tool_input = payload.get("tool_input", {})
is_background = (
    payload.get("hook_event_name") == "PreToolUse"
    and payload.get("tool_name") == "Bash"
    and tool_input.get("run_in_background") is True
)
print(
    "HOOK_CALLED "
    f"event={payload.get('hook_event_name')} "
    f"tool={payload.get('tool_name')} "
    f"run_in_background={tool_input.get('run_in_background')!r}",
    file=sys.stderr,
)
if is_background:
    print("HOOK_DENY background Bash probe", file=sys.stderr)
    raise SystemExit(2)
