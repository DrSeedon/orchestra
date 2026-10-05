"""Prevent lost workflow routing, wrong-project edits and obsolete MCP dispatch."""
import asyncio
import base64
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


@pytest.mark.asyncio
async def test_dynamic_workflow_tool_builds_durable_run_and_manifest_delivery(tmp_path, monkeypatch):
    captured = {}

    async def fake_api(method, path, **kwargs):
        captured.update(method=method, path=path, body=kwargs['json'])
        return {'id': 'bg-test', 'status': 'active'}

    monkeypatch.setattr(mcp_stdio, '_api', fake_api)
    monkeypatch.setattr(mcp_stdio, 'SCOPE', 'test-scope')
    monkeypatch.setattr(mcp_stdio, 'WORKER_NAME', 'test-orchestrator')
    response = await mcp_stdio.dynamic_workflow(
        tasks=[{'prompt': 'first', 'schema': {'type': 'object'}}, {'prompt': 'second'}],
        mode='parallel', budget_usd=1, max_calls=2, max_concurrency=2,
        task_id='V-720', repo=str(tmp_path),
    )
    assert 'queued' in response
    body = captured['body']
    assert captured['method'] == 'POST' and captured['path'] == '/api/bg/jobs'
    assert body['type'] == 'run'
    assert body['target_name'] == 'test-orchestrator'
    assert body['target_scope'] == 'test-scope'
    assert body['config']['cwd'] == str(tmp_path.resolve())
    assert body['config']['success_file'].endswith('/manifest.json')
    assert body['config']['success_pattern'] == r'"complete"\s*:\s*true'
    args = shlex.split(body['config']['command'])
    assert args[:3] == ['env', 'ORCHESTRA_TASK_ID=V-720', 'ORCHESTRA_SCOPE=test-scope']
    assert '--tasks-b64' in args and '--run-id' in args and '--repo' in args
    spec = json.loads(base64.urlsafe_b64decode(args[args.index('--tasks-b64') + 1]))
    assert spec == {
        'tasks': [
            {'prompt': 'first', 'model': 'gpt-6-luna', 'schema': {'type': 'object'}},
            {'prompt': 'second', 'model': 'gpt-6-luna'},
        ],
        'mode': 'parallel',
    }


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['astra', 'sol', 'gpt-5.6-sol'])
async def test_dynamic_workflow_rejects_platform_blocked_models(model, monkeypatch):
    async def unexpected_api(*_args, **_kwargs):
        pytest.fail('blocked models must not create a background job')

    monkeypatch.setattr(mcp_stdio, '_api', unexpected_api)
    response = await mcp_stdio.dynamic_workflow(
        tasks=[{'prompt': 'work', 'model': model}], mode='parallel',
        budget_usd=1, max_calls=1, max_concurrency=1,
        task_id='V-720', repo=str(Path.cwd()),
    )
    assert 'not allowed' in response


@pytest.mark.asyncio
async def test_inline_workflow_run_writes_manifest_and_completion_summary(tmp_path, monkeypatch, capsys):
    from scripts.wf_adapters import AdapterResult, Usage

    repo = _git_repo(tmp_path / 'target')
    runner = tmp_path / 'runner'
    runner.mkdir()
    monkeypatch.setattr(wf_run, 'ROOT', runner)
    monkeypatch.setattr(sys, 'argv', [
        'wf_run.py', '--tasks-b64', base64.urlsafe_b64encode(json.dumps({
            'tasks': [{'prompt': 'one'}, {'prompt': 'two'}], 'mode': 'parallel',
        }).encode()).decode(), '--repo', str(repo), '--run-id', 'inline-test',
        '--budget-usd', '1', '--max-calls', '2', '--max-concurrency', '2',
    ])
    arrived = []
    both = asyncio.Event()

    async def adapter(prompt, **_kwargs):
        arrived.append(prompt)
        if len(arrived) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 5)
        return AdapterResult(
            text=f'answer {prompt}', runtime='codex', model='gpt-6-luna', ok=True,
            stop_reason='end_turn', cost_usd=0.01, usage=Usage(input_tokens=1, output_tokens=1),
        )

    async def readiness(_model):
        return {'state': 'available'}

    monkeypatch.setattr(wf_run, 'run_adapter', adapter)
    monkeypatch.setattr(wf_run, '_readiness', readiness)
    monkeypatch.setattr(wf_run, 'persist_turn_usage', lambda **_kwargs: True)
    assert await wf_run._main() == 0
    output = capsys.readouterr().out
    manifest = json.loads((runner / 'data/workflow-runs/inline-test/manifest.json').read_text())
    assert manifest['complete'] and len(manifest['steps']) == 2
    assert 'WORKFLOW_SUMMARY run=inline-test successful=2/2 complete=true' in output
    assert 'answer one' in output and 'answer two' in output
    resume = shlex.split(manifest['resume_command'])
    assert '--tasks-b64' in resume and '--resume' in resume


@pytest.mark.asyncio
async def test_inline_chain_passes_each_result_as_structured_input(tmp_path):
    prompts = []

    async def adapter(prompt, **_kwargs):
        prompts.append(prompt)
        return _result(f"result-{len(prompts)}")

    async def readiness(_model):
        return {'state': 'available'}

    engine = wf_run.WorkflowEngine(
        'chain-check', tmp_path, budget_usd=1, max_calls=2,
        adapter=adapter, usage_writer=None, readiness_checker=readiness,
        default_modules=(),
    )
    result = await engine.execute_tasks({
        'mode': 'chain',
        'tasks': [{'prompt': 'first'}, {'prompt': 'second'}],
    })
    assert [item.data for item in result] == ['result-1', 'result-2']
    assert prompts[0] == 'first'
    assert prompts[1].startswith('second\n\nStructured inputs:\n["result-1"]')
