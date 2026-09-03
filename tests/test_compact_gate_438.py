"""Regression coverage for the Claude compact gates in task #438."""

from datetime import datetime, timezone
import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from claude_agent_sdk import SystemMessage

from app.backend_claude import ClaudeBackend
from app import session as session_module
from app.session import AgentSession, _compact_prompt
from app.session_turns import TurnManager, _auto_compact_threshold_pct


def _backend() -> ClaudeBackend:
    return ClaudeBackend(model="claude-sonnet-5[1m]", cwd="/tmp")


def _orchestrator() -> AgentSession:
    return AgentSession(
        id="compact-438",
        name="Orchestra-orchestrator",
        scope="/compact-438",
        cwd="/tmp",
        role="orchestrator",
        model="claude-sonnet-5[1m]",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    "metadata, expected",
    [
        (
            {"trigger": "auto", "pre_tokens": 996_005, "post_tokens": 12_345},
            "CLI auto-compacted (auto): 996,005→12,345 tokens",
        ),
        (
            {"trigger": "manual", "preTokens": 88_000, "postTokens": 4_000},
            "CLI auto-compacted (manual): 88,000→4,000 tokens",
        ),
    ],
)
def test_compact_boundary_accepts_wire_and_legacy_metadata(metadata, expected):
    event = SystemMessage(
        subtype="compact_boundary",
        data={
            "type": "system",
            "subtype": "compact_boundary",
            "compact_metadata" if "pre_tokens" in metadata else "compactMetadata": metadata,
        },
    )

    converted = _backend()._convert(event)

    assert [item.content for item in converted] == [expected]


def _capture_spawn(session: AgentSession):
    spawned = []

    def capture(coro):
        spawned.append(coro)
        coro.close()

    session._spawn_bg = capture
    session._cancel_precompact_timer = MagicMock()
    session._log = MagicMock()
    session._auto_compact = MagicMock()
    async def noop():
        return None

    session._auto_compact.side_effect = lambda **_kwargs: noop()
    return spawned


def test_orchestrator_compacts_at_96_but_not_94():
    session = _orchestrator()
    session._last_context = {"percentage": 96, "max_tokens": 1_000_000}
    spawned = _capture_spawn(session)

    TurnManager(session).schedule_context_compaction(96)

    assert len(spawned) == 1
    session._auto_compact.assert_called_once_with(delay_seconds=0)

    session._auto_compact.reset_mock()
    session._last_context["percentage"] = 94
    TurnManager(session).schedule_context_compaction(94)

    session._auto_compact.assert_not_called()


def test_cli_threshold_lowers_our_threshold():
    session = _orchestrator()
    session._last_context = {
        "percentage": 89,
        "max_tokens": 1_000_000,
        "auto_compact_threshold": 900_000,
    }
    spawned = _capture_spawn(session)

    assert _auto_compact_threshold_pct(session) == 89

    TurnManager(session).schedule_context_compaction(90)

    assert len(spawned) == 1


def test_compact_prompt_requires_all_user_messages_and_raw_transcript_link():
    source = Path(session_module.__file__)
    source_text = source.read_text(encoding="utf-8")

    requirement = next(
        node for node in ast.walk(ast.parse(source_text))
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_COMPACT_USER_MESSAGES_REQUIREMENT"
            for target in node.targets
        )
    )
    required_text = ast.literal_eval(requirement.value)
    prompt = _compact_prompt("Orchestra-orchestrator", "/compact-438")

    assert required_text in prompt
    assert "/api/sessions/Orchestra-orchestrator/logs?scope=/compact-438" in prompt
