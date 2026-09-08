"""Reinstate the old persistence filter in memory, without editing app files."""

import pytest
from app.harness.loop import AgentLoop

original_run = AgentLoop.run


async def mutated_run(self, user_msg):
    async for event in original_run(self, user_msg):
        yield event
    self.new_messages[:] = [
        message for message in self.new_messages
        if not str(message.get("content", "")).startswith("[round guard]")
    ]


AgentLoop.run = mutated_run
raise SystemExit(pytest.main([
    "-q",
    "tests/test_harness_tools.py::test_t3_model_authored_round_guard_prefix_survives_history_cleanup",
]))
