"""V-1025: pipeline effort survives the hub boundary; all hub calls are fake."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.backend_hub import HubBackend
from app import hub_workspace as hw
from app.pipeline import get_role, resolve_effort


def capabilities():
    def model(name, option, values):
        return {"id": name, "options": [{"id": option, "type": "select",
                "options": [{"id": v} for v in values]}]}
    return {"providers": [
        {"providerInstanceId": "codex", "models": [
            model("gpt-6.1-sol", "reasoningEffort", ["low", "medium", "high", "ultra"]),
            model("gpt-6-luna", "reasoningEffort", ["low", "medium", "high"])]},
        {"providerInstanceId": "claudeAgent", "models": [
            model("claude-opus-5-5", "effort", ["low", "medium", "high"])]}]}


class Hub:
    def __init__(self):
        self.calls = []
        self.catalog = capabilities()

    async def tool_call(self, name, args):
        self.calls.append((name, args))
        if name == "orchestrator_capabilities":
            return self.catalog
        return {"threadId": "thread", "runId": "run"}


def setup(effort="high", **kwargs):
    backend = HubBackend("hub-gpt-6.1-sol", ".", effort=effort, **kwargs)
    hub = Hub()
    backend._mc = hub
    state = hw.WorkspaceState("workspace", ".", "/synthetic/copy", project_id="project")
    state.save = lambda: None
    backend._state = state
    backend._ssh = SimpleNamespace(assert_file_policy=AsyncMock())
    return backend, hub, state


@pytest.mark.asyncio
async def test_launch_carries_effort():
    backend, hub, state = setup()
    assert await backend._start(hub, state, "task") == "run"
    assert hub.calls[-1] == ("t3_thread_launch", {
        "title": "workspace", "projectId": "project", "message": "task", "runtimeMode": "full-access",
        "modelSelection": {"instanceId": "codex", "model": "gpt-6.1-sol",
                           "options": {"reasoningEffort": "high"}}})


@pytest.mark.asyncio
async def test_configure_carries_effort_and_reuses_catalog():
    backend, hub, state = setup()
    await backend._start(hub, state, "task")
    await backend.retarget_model("hub-gpt-6-luna")
    assert hub.calls[-1] == ("t3_thread_configure", {"threadId": "thread", "modelSelection": {
        "instanceId": "codex", "model": "gpt-6-luna", "options": {"reasoningEffort": "high"}}})
    assert sum(name == "orchestrator_capabilities" for name, _ in hub.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("configure", [False, True])
async def test_unknown_effort_refused_before_mutation(configure):
    backend, hub, state = setup("bogus")
    state.thread_id = "thread" if configure else ""
    with pytest.raises(ValueError, match="bogus.*allowed values: low, medium, high, ultra"):
        if configure:
            await backend.retarget_model("hub-gpt-6.1-sol")
        else:
            await backend._start(hub, state, "task")
    assert [name for name, _ in hub.calls] == ["orchestrator_capabilities"]
    assert state.thread_id == ("thread" if configure else "")


@pytest.mark.asyncio
async def test_value_is_validated_against_target_model():
    backend, hub, state = setup("ultra")
    await backend._start(hub, state, "task")
    with pytest.raises(ValueError, match="gpt-6-luna.*ultra.*allowed values: low, medium, high$"):
        await backend.retarget_model("hub-gpt-6-luna")
    assert backend.model == "hub-gpt-6.1-sol" and state.thread_id == "thread"


@pytest.mark.asyncio
async def test_missing_advertised_option_is_an_error():
    backend, hub, state = setup()
    hub.catalog["providers"] = []
    with pytest.raises(ValueError, match="allowed values: \\(none advertised\\)"):
        await backend._start(hub, state, "task")
    assert len(hub.calls) == 1


@pytest.mark.asyncio
async def test_no_effort_omits_options_on_launch_and_configure():
    backend, hub, state = setup(None)
    await backend._start(hub, state, "task")
    await backend.retarget_model("hub-gpt-6-luna")
    assert [name for name, _ in hub.calls] == ["t3_thread_launch", "t3_thread_configure"]
    assert all("options" not in args["modelSelection"] for _, args in hub.calls)


@pytest.mark.asyncio
async def test_retarget_resolves_target_policy_and_claude_option():
    backend, hub, state = setup(pipeline="default", role="worker")
    await backend._start(hub, state, "task")
    await backend.retarget_model("hub-claude-opus-5-5")
    assert hub.calls[-1][1]["modelSelection"]["options"] == {"effort": "medium"}
    assert backend._effort == "medium"
    await backend.retarget_model("hub-gpt-6.1-sol")
    assert hub.calls[-1][1]["modelSelection"]["options"] == {"reasoningEffort": "high"}


@pytest.mark.parametrize("role,opus", [("orchestrator", "high"), ("worker", "medium")])
def test_hub_policy_matches_native_claude(role, opus):
    policy = get_role("default", role).effort
    assert resolve_effort(policy, "hub-gpt-6.1-sol", "hub") == "high"
    for hub, native, expected in [
        ("hub-claude-opus-5-5", "claude-opus-5-5[1m]", opus),
        ("hub-claude-sonnet-5-5", "claude-sonnet-5-5[1m]", "medium"),
        ("hub-claude-haiku-5-5", "claude-haiku-5-5", "low")]:
        assert resolve_effort(policy, hub, "hub") == resolve_effort(policy, native, "claude") == expected


@pytest.mark.asyncio
async def test_resumed_thread_receives_current_effort_before_send():
    backend, hub, state = setup("medium")
    state.thread_id = "thread"
    await backend._start(hub, state, "next turn")
    assert [name for name, _ in hub.calls] == [
        "orchestrator_capabilities", "t3_thread_configure", "t3_thread_send"]
    assert hub.calls[1][1]["modelSelection"]["options"] == {"reasoningEffort": "medium"}


@pytest.mark.asyncio
async def test_no_effort_no_thread_retarget_needs_no_connection():
    backend = HubBackend("hub-gpt-6.1-sol", ".")
    await backend.retarget_model("hub-gpt-6-luna")
    assert backend.model == "hub-gpt-6-luna" and backend._mc is None


def test_factory_keeps_effort_and_policy_context():
    from app.runtime_registry import BackendBuildContext, build_backend

    backend = build_backend("hub", BackendBuildContext(
        model="hub-gpt-6.1-sol", provider="openai", cwd=".", system_prompt="",
        resume_session_id=None, mcp_servers={}, is_orchestrator=False, scope=".",
        pipeline="default", role="worker", profile="", effort="high", context_limit=256000))
    assert backend._effort == "high"
    assert (backend._pipeline, backend._role) == ("default", "worker")
