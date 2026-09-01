"""Harness turn accounting and mid-turn steering (audit 01.09).

Two independent defects of app/backend_harness.py, one test each:

1. turn_end carried the backend's LIFETIME token counters as the turn's AggregateUsage
   ("billed totals ... in one runtime turn", app/usage_contract.py). Turn N's turn_usage
   row then held the sum of turns 1..N and session totals grew quadratically. Both other
   runtimes report a per-turn value; CodexBackend does it with an explicit _usage_baseline.
2. Steering queued after a round's drain point — the final round of a turn, or a turn that
   is aborting — never reached the model: the loop returned without draining and the next
   turn's events() destroyed the queue, while session.py had already marked the durable
   delivery SUBMITTED. Delivery alone is not enough (round 2 review): a leftover written
   before this turn's message must not land behind it in the recency slot, unlabelled.
"""

import pytest

from app.backend_harness import HarnessBackend
from app.harness.loop import CARRIED_OVER_PREFIX, AgentLoop

MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


class _FakeStore:
    session_id = "harness-audit0901"


class _FakeLoop:
    """Stand-in for AgentLoop: events() only reads these attributes after run()."""

    def __init__(self, round_usages: list[dict], raise_exc: Exception | None = None):
        self.round_usages = round_usages
        self.last_usage = round_usages[-1] if round_usages else {}
        self.ok = True
        self.stop_reason = "end_turn"
        self.error_detail = ""
        self.truncated_dropped = 0
        self.new_messages: list[dict] = []
        self._raise = raise_exc

    async def run(self, user_msg: str):
        if self._raise is not None:
            raise self._raise
        return
        yield  # noqa: unreachable — makes this an async generator


def _backend(tmp_path) -> HarnessBackend:
    backend = HarnessBackend(model=MODEL, cwd=str(tmp_path))
    backend._llm = object()      # connect() not needed for these paths
    backend._mcp = object()
    backend._store = _FakeStore()
    return backend


async def _turn(backend: HarnessBackend, message: str) -> list:
    await backend.send(message)
    return [ev async for ev in backend.events()]


@pytest.mark.asyncio
async def test_turn_end_reports_this_turns_tokens_not_the_session_total(
    tmp_path, monkeypatch,
) -> None:
    backend = _backend(tmp_path)
    loops = [
        _FakeLoop([{"prompt_tokens": 50000, "completion_tokens": 1000, "cost": 0}]),
        _FakeLoop([{"prompt_tokens": 50000, "completion_tokens": 1000, "cost": 0}]),
        _FakeLoop([{"prompt_tokens": 50000, "completion_tokens": 1000, "cost": 0}],
                  raise_exc=RuntimeError("provider hung up")),
    ]
    monkeypatch.setattr("app.backend_harness.AgentLoop",
                        lambda **_kwargs: loops.pop(0))

    first = (await _turn(backend, "turn one"))[-1]
    second = (await _turn(backend, "turn two"))[-1]
    third = (await _turn(backend, "turn three"))[-1]

    assert first.metadata["input_tokens"] == 50000
    assert second.metadata["input_tokens"] == 50000, (
        "turn 2 reported the session's cumulative prompt tokens, not its own"
    )
    assert second.metadata["output_tokens"] == 1000
    assert second.usage.aggregate.input_tokens == 50000
    assert third.metadata["input_tokens"] == 50000, (
        "the error turn_end reported cumulative tokens too"
    )
    assert third.metadata["ok"] is False


@pytest.mark.asyncio
async def test_steering_past_the_drain_point_reaches_the_model(
    tmp_path, monkeypatch,
) -> None:
    backend = _backend(tmp_path)
    seen: list[list[dict]] = []

    async def fake_round(self, assistant_msg):
        seen.append([dict(m) for m in self.history])
        if len(seen) == 1:
            # Arrives while the model streams the FINAL answer of the turn: send() sees an
            # active turn and queues past this round's drain point.
            await backend.send("correction: the spec changed")
        assistant_msg["content"] = "done"
        return
        yield  # noqa: unreachable — makes this an async generator

    monkeypatch.setattr(AgentLoop, "_one_round", fake_round)
    monkeypatch.setattr(AgentLoop, "_fit_context", lambda self: True)

    await _turn(backend, "original task")

    assert any(m.get("content") == "correction: the spec changed"
               for snapshot in seen for m in snapshot), (
        "steering queued after the last drain point never reached the model"
    )

    # A turn that ended (abort/cancel) with undrained steering leaves it queued; the next
    # turn must deliver it, not destroy it.
    backend._injected = ["leftover: use the new endpoint"]
    await _turn(backend, "next task")

    assert any("leftover: use the new endpoint" in str(m.get("content"))
               for snapshot in seen for m in snapshot), (
        "steering left over from the previous turn was cleared instead of delivered"
    )


@pytest.mark.asyncio
async def test_carried_over_steering_lands_before_the_new_message_and_is_labelled(
    tmp_path, monkeypatch,
) -> None:
    """A leftover predates this turn's message: delivering it LAST hands the strongest
    recency slot to the stale instruction, and unlabelled it reads as the newest word."""
    backend = _backend(tmp_path)
    seen: list[list[dict]] = []

    async def fake_round(self, assistant_msg):
        seen.append([dict(m) for m in self.history])
        assistant_msg["content"] = "done"
        return
        yield  # noqa: unreachable — makes this an async generator

    monkeypatch.setattr(AgentLoop, "_one_round", fake_round)
    monkeypatch.setattr(AgentLoop, "_fit_context", lambda self: True)

    backend._injected = ["STALE steering from the aborted turn"]
    await _turn(backend, "NEW operator instruction")

    users = [str(m["content"]) for m in seen[0] if m.get("role") == "user"]
    assert users == [
        CARRIED_OVER_PREFIX + "STALE steering from the aborted turn",
        "NEW operator instruction",
    ], f"carried-over steering in the wrong position or unlabelled: {users}"
