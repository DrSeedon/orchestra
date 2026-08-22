"""Mid-turn steering for the harness runtime.

A correction that arrives while the loop is running must reach the model on its NEXT
round, not after the whole turn. Before this, `send()` raised and session.py fell back
to the pending queue — up to MAX_TOOL_ROUNDS rounds of work done against stale
instructions.
"""

import asyncio

import pytest

from app.backend_harness import HarnessBackend
from app.harness.loop import AgentLoop
from app.runtime_registry import get_runtime


def test_runtime_declares_mid_turn_inject():
    assert get_runtime("harness").capabilities.mid_turn_inject is True


def test_send_during_active_turn_queues_instead_of_raising():
    b = HarnessBackend(model="stealth/ox-alpha", cwd="/tmp")
    b._llm = object()          # connect() not needed: send() only checks it is set
    b._turn_active = True

    asyncio.run(b.send("stop what you are doing, the spec changed"))

    assert b._injected == ["stop what you are doing, the spec changed"]


def test_drain_hands_over_once_and_forgets():
    b = HarnessBackend(model="stealth/ox-alpha", cwd="/tmp")
    b._injected = ["first", "second"]

    assert b._drain_injected() == ["first", "second"]
    assert b._drain_injected() == []      # a second round must not replay them


@pytest.mark.asyncio
async def test_injected_message_enters_history_before_the_next_round():
    """The loop appends steering as a user message at the TOP of a round — after the
    previous round's tool results are already in place, so the request stays well-formed."""
    history: list[dict] = []
    rounds: list[list[dict]] = []
    queue = [["the spec changed: keep claude models too"]]

    loop = AgentLoop(
        llm=None, mcp=None, cwd="/tmp", history=history, tool_schemas=[],
        max_context=100000, drain_injected=lambda: queue.pop(0) if queue else [],
    )

    async def fake_round(assistant_msg):
        rounds.append(list(history))          # snapshot of what the model would have seen
        assistant_msg["content"] = "done"
        return
        yield  # noqa: unreachable — makes this an async generator

    loop._one_round = fake_round
    loop._fit_context = lambda: True

    async for _ in loop.run("original task"):
        pass

    assert rounds, "the loop never entered a round"
    assert rounds[0][-1] == {"role": "user",
                             "content": "the spec changed: keep claude models too"}
    assert rounds[0][0] == {"role": "user", "content": "original task"}


@pytest.mark.asyncio
async def test_no_injection_leaves_history_untouched():
    """Negative control: without steering the loop must not invent a user message."""
    history: list[dict] = []
    seen: list[list[dict]] = []

    loop = AgentLoop(
        llm=None, mcp=None, cwd="/tmp", history=history, tool_schemas=[],
        max_context=100000,
    )

    async def fake_round(assistant_msg):
        seen.append(list(history))
        assistant_msg["content"] = "done"
        return
        yield  # noqa: unreachable

    loop._one_round = fake_round
    loop._fit_context = lambda: True

    async for _ in loop.run("original task"):
        pass

    assert seen[0] == [{"role": "user", "content": "original task"}]
