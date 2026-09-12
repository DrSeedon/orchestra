"""Prevent lost workflow routing, wrong-project edits and obsolete MCP dispatch."""
import asyncio
import json
import shlex
import sys
from pathlib import Path

import pytest

from app import mcp_stdio, pipeline
from scripts import wf_run
from tests.test_wf_run import _git_repo, _result


@pytest.mark.asyncio
async def test_removed_tool_is_absent_and_cannot_dispatch():
    retired = 'run' + '_fan'
    assert retired not in {tool.name for tool in await mcp_stdio.mcp.list_tools()}
    result = await mcp_stdio.mcp.call_tool(retired, {})
    assert result.isError


@pytest.mark.parametrize('role', ['orchestrator', 'sub-orchestrator', 'full-cycle'])
def test_workflow_module_reaches_launching_roles(role):
    name = 'dynamic-workflows'
    spec = pipeline.get_role('default', role)
    assert spec.can_spawn
    assert name in spec.modules
    body = pipeline.prompt_path('default', f'modules/{name}.md').read_text().strip()
    assert body in pipeline.build_system_prompt('default', role)


@pytest.mark.parametrize('purpose,escalate', [('work', False), ('verify', False), ('work', True)])
def test_default_dispatch_uses_default_subscription_model(purpose, escalate):
    from app.models import resolve_model
    assert wf_run.WorkflowEngine._candidates(None, purpose, escalate, False) == [resolve_model('luna')]


@pytest.mark.asyncio
async def test_cli_parallel_uses_target_repository_and_resume_preserves_it(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / 'target')
    runner = tmp_path / 'runner'
    runner.mkdir()
    workflow = tmp_path / 'task.py'
    workflow.write_text('result = await parallel([lambda: agent("one"), lambda: agent("two")])')
    monkeypatch.setattr(wf_run, 'ROOT', runner)
    monkeypatch.setattr(sys, 'argv', ['wf_run.py', str(workflow), '--repo', str(repo),
                                    '--run-id', 'target-check', '--budget-usd', '1', '--max-calls', '2'])
    arrived = []
    both = asyncio.Event()

    async def adapter(prompt, *, cwd, **kwargs):
        assert (Path(cwd) / 'seed.txt').read_text() == 'seed\n'
        arrived.append(Path(cwd))
        if len(arrived) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 5)
        (Path(cwd) / 'output.txt').write_text(prompt)
        return _result(prompt)

    async def readiness(model):
        return {'state': 'available'}

    monkeypatch.setattr(wf_run, 'run_adapter', adapter)
    monkeypatch.setattr(wf_run, '_readiness', readiness)
    monkeypatch.setattr(wf_run, 'persist_turn_usage', lambda **kwargs: True)
    assert await wf_run._main() == 0
    manifest = json.loads((runner / 'data/workflow-runs/target-check/manifest.json').read_text())
    assert manifest['complete'] and len(manifest['steps']) == 2
    assert len(set(arrived)) == 2
    assert all(Path(step['workspace_path'], 'output.txt').is_file() for step in manifest['steps'])
    assert not (repo / 'output.txt').exists()
    resume = shlex.split(manifest['resume_command'])
    assert resume[resume.index('--repo') + 1] == str(repo)
