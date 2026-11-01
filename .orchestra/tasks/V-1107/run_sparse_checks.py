"""Explicit sparse-copy fallback, NOT a replacement for the repository test run.

Run with the broker uv and --noconftest: app.events/openrouter_counter and most
global fixture dependencies are absent from this copy. No production code under
test is stubbed: tools, loop, llm, images and mcp load from this workspace.
"""

import os
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

events = ModuleType("app.events")


class AgentEvent:
    def __init__(self, type, content="", metadata=None):
        self.type = type
        self.content = content
        self.metadata = metadata


events.AgentEvent = AgentEvent
sys.modules["app.events"] = events
sys.modules["app.openrouter_counter"] = ModuleType("app.openrouter_counter")

import pytest  # noqa: E402

if os.environ.get("V1107_RESTORE_OLD_BEHAVIOR") == "1":
    from app.harness import loop, tools

    def old_cap(text):
        cap = int(os.environ.get("HARNESS_OUTPUT_CAP") or tools.OUTPUT_CAP)
        if len(text) > cap:
            return (text[:cap] + f"\n... (truncated, {len(text) - cap} more chars; "
                    "narrow it with head, tail, grep or read offset/limit)")
        return text

    tools._cap = old_cap
    loop._is_context_overflow = lambda error: False

raise SystemExit(pytest.main([
    "--noconftest", "-o", "addopts=", "-q", "--tb=short",
    "tests/test_harness_cap_overflow_1107.py", *sys.argv[1:],
]))
