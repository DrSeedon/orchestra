"""Stable prompt prefix, worker tool profile and the 09.11.2026 model stack."""

import os

from app import models
from app.manager import ROLE_SYSTEM_PROMPT, _identity_last
from app.pipeline import get_role, resolve_effort
from app.prompting import safe_format_prompt
from app.tool_scoping import _ORCHESTRATOR_ONLY_TOOLS, role_tool_names


def _worker_prompt(name: str, branch: str) -> str:
    return safe_format_prompt(
        ROLE_SYSTEM_PROMPT("default", "worker"),
        worker_name=name, orchestrator_name="orch", scope="/s", branch=branch,
    )


def test_identity_is_the_last_layer_of_a_worker_prompt():
    for role in ("worker", "full-cycle"):
        prompt = ROLE_SYSTEM_PROMPT("default", role)
        assert prompt.startswith("<platform>")
        assert prompt.count("<identity>") == 1
        assert prompt.rstrip().endswith("</identity>")


def test_two_workers_share_everything_before_their_identity():
    first = _worker_prompt("alpha", "task-1/alpha")
    second = _worker_prompt("beta", "task-2/beta")
    shared = os.path.commonprefix([first, second])

    assert shared.endswith("<identity>\n- Worker name: ")
    assert len(shared) > 0.9 * len(first)


def test_identity_move_keeps_every_other_section_once():
    raw = "<role>\nR\n</role>\n\n<identity>\n- Worker name: x\n</identity>\n\n<boundaries>\nB\n</boundaries>"
    moved = _identity_last(raw)

    assert moved == "<role>\nR\n</role>\n\n<boundaries>\nB\n</boundaries>\n\n<identity>\n- Worker name: x\n</identity>"
    assert _identity_last("<role>\nno identity\n</role>") == "<role>\nno identity\n</role>"


def test_orchestrator_prompt_is_unchanged_by_the_identity_move():
    prompt = ROLE_SYSTEM_PROMPT("default", "orchestrator")
    assert "<identity>" not in prompt and prompt.startswith("<platform>")


def test_ordinary_worker_profile_hides_orchestrator_tools_but_full_cycle_keeps_them():
    names = set(_ORCHESTRATOR_ONLY_TOOLS) | {"read", "task_get", "send_message", "update_progress"}

    assert role_tool_names(names, "worker") == {"read", "task_get", "send_message", "update_progress"}
    # full-cycle has can_spawn in the manifest: it delegates, so it keeps the management tools.
    assert role_tool_names(names, "full-cycle") == names
    assert role_tool_names(names, "orchestrator") == names


def test_owner_stack_efforts_resolve_in_every_spawning_and_working_role():
    for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
        policy = get_role("default", role).effort
        assert resolve_effort(policy, "hub-claude-opus-5-5", "hub") == "xhigh", role
        assert resolve_effort(policy, "claude-opus-5-5[1m]", "claude") == "xhigh", role
        assert resolve_effort(policy, "hub-claude-sonnet-5-5", "hub") == "high", role
        assert resolve_effort(policy, "claude-sonnet-5-5[1m]", "claude") == "high", role
        assert resolve_effort(policy, "hub-gemini-4-argon", "hub") == "medium", role
    assert resolve_effort(get_role("default", "specialist").effort, "hub-gemini-4-argon", "hub") == "medium"


def test_context_windows_follow_the_owner_decision():
    assert models.get_model_spec("free/auto:free").context_length == 131072
    for raw in ("gemini-4-argon-high", "gemini-4-argon-medium", "gemini-4-argon-low",
                "claude-opus-4-6-thinking"):
        assert models.get_model_spec(f"antigravity/{raw}").context_length == 1_000_000
    assert models.get_model_spec("antigravity/gemini-3.6-flash-low").context_length == 128_000


def test_hub_opus_is_admitted_and_haiku_stays_closed():
    models.ensure_hub_worker_allowed("hubopus")
    models.ensure_hub_worker_allowed("hub-claude-opus-5-5")
    try:
        models.ensure_hub_worker_allowed("hub-claude-haiku-5-5")
    except ValueError as error:
        assert models.HUB_SOL_ONLY_RULE in str(error) and "hubopus" in str(error)
    else:
        raise AssertionError("hub haiku must stay closed")
