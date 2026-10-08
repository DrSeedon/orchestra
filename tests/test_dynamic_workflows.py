"""Prevent lost workflow routing, wrong-project edits and obsolete MCP dispatch."""
import asyncio
import json
import shlex
import subprocess
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
    fake_install = tmp_path / 'install'
    (fake_install / 'app').mkdir(parents=True)
    monkeypatch.setattr(mcp_stdio, '__file__', str(fake_install / 'app' / 'mcp_stdio.py'))
    repo_path = _git_repo(tmp_path / 'repo')
    large_prompt = 'context ' * 9000
    response = await mcp_stdio.dynamic_workflow(
        stages=[{
            'prompt': large_prompt + 'persona={item}',
            'items': [{'id': 1, 'profile': 'first'}, {'id': 2, 'profile': 'second'}],
            'schema': {'type': 'object'},
        }],
        mode='stages', budget_usd=1, max_calls=2, max_concurrency=2,
        task_id='V-720', repo=str(repo_path),
    )
    assert 'queued' in response
    body = captured['body']
    assert captured['method'] == 'POST' and captured['path'] == '/api/bg/jobs'
    assert body['type'] == 'run'
    assert body['target_name'] == 'test-orchestrator'
    assert body['target_scope'] == 'test-scope'
    assert body['config']['cwd'] == str(repo_path.resolve())
    assert body['config']['success_file'].endswith('/manifest.json')
    assert body['config']['success_pattern'] == r'"complete"\s*:\s*true'
    args = shlex.split(body['config']['command'])
    assert args[:3] == ['env', 'ORCHESTRA_TASK_ID=V-720', 'ORCHESTRA_SCOPE=test-scope']
    assert '--spec' in args and '--run-id' in args and '--repo' in args
    assert args[args.index('--repo') + 1] == str(repo_path.resolve())
    assert args[args.index('--base-commit') + 1] == subprocess.run(
        ['git', 'rev-parse', 'HEAD'], cwd=repo_path, capture_output=True,
        text=True, check=True,
    ).stdout.strip()
    assert '--tasks-b64' not in args and large_prompt not in body['config']['command']
    spec_path = Path(args[args.index('--spec') + 1])
    assert spec_path.stat().st_size > 64 * 1024
    spec = json.loads(spec_path.read_text())
    assert spec['mode'] == 'stages' and len(spec['stages'][0]['tasks']) == 2
    assert spec['stages'][0]['tasks'] == [
        {'prompt': large_prompt + 'persona={"id": 1, "profile": "first"}', 'model': 'gpt-6-luna', 'schema': {'type': 'object'}, 'label': 'Stage 1 · Task 1'},
        {'prompt': large_prompt + 'persona={"id": 2, "profile": "second"}', 'model': 'gpt-6-luna', 'schema': {'type': 'object'}, 'label': 'Stage 1 · Task 2'},
    ]
    assert spec['dashboard']['task_id'] == 'V-720'
    assert spec['dashboard']['budget_usd'] == 1
    assert spec['dashboard']['max_calls'] == 2
    assert spec['dashboard']['max_concurrency'] == 2


@pytest.mark.asyncio
async def test_dynamic_workflow_resolves_haiku_alias(tmp_path, monkeypatch):
    captured = {}

    async def fake_api(_method, _path, **kwargs):
        captured.update(kwargs['json'])
        return {'id': 'bg-haiku'}

    fake_install = tmp_path / 'install'
    (fake_install / 'app').mkdir(parents=True)
    monkeypatch.setattr(mcp_stdio, '__file__', str(fake_install / 'app' / 'mcp_stdio.py'))
    monkeypatch.setattr(mcp_stdio, '_api', fake_api)
    response = await mcp_stdio.dynamic_workflow(
        budget_usd=1, max_calls=1, max_concurrency=1, task_id='V-766',
        repo=str(_git_repo(tmp_path / 'repo')), tasks=[{'prompt': 'extract facts', 'model': 'haiku'}],
    )
    assert 'queued' in response
    args = shlex.split(captured['config']['command'])
    spec = json.loads(Path(args[args.index('--spec') + 1]).read_text())
    assert spec['tasks'][0]['model'] == 'claude-haiku-5-5'


@pytest.mark.asyncio
async def test_dynamic_workflow_accepts_linked_worktree_and_pins_its_head(tmp_path, monkeypatch):
    captured = {}

    async def fake_api(_method, _path, **kwargs):
        captured.update(kwargs['json'])
        return {'id': 'bg-linked'}

    repo = _git_repo(tmp_path / 'repo')
    linked = tmp_path / 'worker-checkout'
    subprocess.run(
        ['git', 'worktree', 'add', '-b', 'caller-branch', str(linked)],
        cwd=repo, capture_output=True, check=True,
    )
    (linked / 'commit.txt').write_text('caller branch commit\n')
    subprocess.run(['git', 'add', 'commit.txt'], cwd=linked, capture_output=True, check=True)
    subprocess.run(
        ['git', 'commit', '-m', 'caller branch commit'], cwd=linked,
        capture_output=True, check=True,
    )
    head = subprocess.run(
        ['git', 'rev-parse', 'HEAD'], cwd=linked, capture_output=True,
        text=True, check=True,
    ).stdout.strip()
    fake_install = tmp_path / 'install'
    (fake_install / 'app').mkdir(parents=True)
    monkeypatch.setattr(mcp_stdio, '__file__', str(fake_install / 'app' / 'mcp_stdio.py'))
    monkeypatch.setattr(mcp_stdio, '_api', fake_api)

    response = await mcp_stdio.dynamic_workflow(
        budget_usd=1, max_calls=1, max_concurrency=1, task_id='V-780',
        repo=str(linked), tasks=[{'prompt': 'inspect current code'}],
    )

    assert 'queued' in response
    args = shlex.split(captured['config']['command'])
    assert args[args.index('--repo') + 1] == str(repo.resolve())
    assert args[args.index('--base-commit') + 1] == head


@pytest.mark.asyncio
async def test_dynamic_workflow_rejects_external_git_dir_before_queueing(tmp_path, monkeypatch):
    async def unexpected_api(*_args, **_kwargs):
        pytest.fail('unsupported git-dir must be rejected before queueing')

    repo = tmp_path / 'separate-git-dir'
    subprocess.run(
        ['git', 'init', '--separate-git-dir', str(tmp_path / 'external.git'), str(repo)],
        capture_output=True, check=True,
    )
    monkeypatch.setattr(mcp_stdio, '_api', unexpected_api)
    response = await mcp_stdio.dynamic_workflow(
        budget_usd=1, max_calls=1, max_concurrency=1, task_id='V-780',
        repo=str(repo), tasks=[{'prompt': 'inspect'}],
    )
    assert 'separate gitfile repositories' in response


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['parallel', 'chain'])
async def test_dynamic_workflow_keeps_legacy_task_modes(mode, tmp_path, monkeypatch):
    captured = {}

    async def fake_api(_method, _path, **kwargs):
        captured.update(kwargs['json'])
        return {'id': 'bg-legacy'}

    fake_install = tmp_path / 'install'
    (fake_install / 'app').mkdir(parents=True)
    monkeypatch.setattr(mcp_stdio, '__file__', str(fake_install / 'app' / 'mcp_stdio.py'))
    monkeypatch.setattr(mcp_stdio, '_api', fake_api)
    response = await mcp_stdio.dynamic_workflow(
        budget_usd=1, max_calls=2, max_concurrency=2, task_id='V-738', repo=str(_git_repo(tmp_path / 'repo')),
        tasks=[{'prompt': 'legacy task'}], mode=mode,
    )
    assert 'queued' in response
    args = shlex.split(captured['config']['command'])
    spec = json.loads(Path(args[args.index('--spec') + 1]).read_text())
    assert spec['tasks'] == [{'prompt': 'legacy task', 'model': 'gpt-6-luna', 'label': 'Task 1'}]
    assert spec['mode'] == mode
    assert spec['dashboard']['task_id'] == 'V-738'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('model', 'expected_error'),
    [('astra', 'not allowed'), ('sol', 'not allowed'), ('gpt-5.6-sol', 'unknown model')],
)
async def test_dynamic_workflow_rejects_platform_blocked_models(model, expected_error, monkeypatch):
    async def unexpected_api(*_args, **_kwargs):
        pytest.fail('blocked models must not create a background job')

    monkeypatch.setattr(mcp_stdio, '_api', unexpected_api)
    response = await mcp_stdio.dynamic_workflow(
        tasks=[{'prompt': 'work', 'model': model}], mode='parallel',
        budget_usd=1, max_calls=1, max_concurrency=1,
        task_id='V-720', repo=str(Path.cwd()),
    )
    assert expected_error in response


@pytest.mark.asyncio
async def test_inline_workflow_run_writes_manifest_and_completion_summary(tmp_path, monkeypatch, capsys):
    from scripts.wf_adapters import AdapterResult, Usage

    repo = _git_repo(tmp_path / 'target')
    runner = tmp_path / 'runner'
    runner.mkdir()
    spec_path = runner / 'data/workflow-runs/inline-test/request.json'
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(json.dumps({
        'tasks': [{'prompt': 'one'}, {'prompt': 'two'}], 'mode': 'parallel',
    }))
    monkeypatch.setattr(wf_run, 'ROOT', runner)
    monkeypatch.setattr(sys, 'argv', [
        'wf_run.py', '--spec', str(spec_path), '--repo', str(repo), '--run-id', 'inline-test',
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
    assert resume[resume.index('--spec') + 1] == str(spec_path)
    assert '--resume' in resume


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


@pytest.mark.asyncio
async def test_stages_give_every_next_stage_task_all_previous_results(tmp_path):
    prompts = []

    async def adapter(prompt, **_kwargs):
        prompts.append(prompt)
        return _result(f"result-{len(prompts)}")

    async def readiness(_model):
        return {'state': 'available'}

    engine = wf_run.WorkflowEngine(
        'all-inputs-check', tmp_path, budget_usd=1, max_calls=4,
        adapter=adapter, usage_writer=None, readiness_checker=readiness,
        default_modules=(),
    )
    result = await engine.execute_stages([
        {'tasks': [
            {'prompt': 'first', 'label': 'Stage 1 · Task 1'},
            {'prompt': 'second', 'label': 'Stage 1 · Task 2'},
        ]},
        {'tasks': [
            {'prompt': 'third', 'label': 'Stage 2 · Task 1'},
            {'prompt': 'fourth', 'label': 'Stage 2 · Task 2'},
        ]},
    ])
    assert len(result) == 2 and len(result[0]) == len(result[1]) == 2
    assert [step['label'] for step in engine.write_manifest()['steps']] == [
        'Stage 1 · Task 1', 'Stage 1 · Task 2', 'Stage 2 · Task 1', 'Stage 2 · Task 2',
    ]
    assert prompts[2].startswith('third\n\nStructured inputs:\n["result-1", "result-2"]')
    assert prompts[3].startswith('fourth\n\nStructured inputs:\n["result-1", "result-2"]')


@pytest.mark.asyncio
async def test_stage_budget_is_global_and_resume_replays_prior_stage(tmp_path):
    prompts = []

    async def adapter(prompt, **_kwargs):
        prompts.append(prompt)
        return _result(f"result-{len(prompts)}", cost=1.1 if len(prompts) == 1 else 0.01)

    async def readiness(_model):
        return {'state': 'available'}

    stages = [
        {'tasks': [{'prompt': 'first'}]},
        {'tasks': [{'prompt': 'second'}]},
    ]
    first = wf_run.WorkflowEngine(
        'stage-budget', tmp_path, budget_usd=1, max_calls=2,
        adapter=adapter, usage_writer=None, readiness_checker=readiness,
        default_modules=(),
    )
    partial = await first.execute_stages(stages)
    assert partial[0][0].data == 'result-1' and partial[1] == [None]
    assert first.write_manifest()['partial_reason'] == 'budget'
    assert prompts == ['first']

    resumed = wf_run.WorkflowEngine(
        'stage-budget', tmp_path, budget_usd=2, max_calls=2,
        adapter=adapter, usage_writer=None, readiness_checker=readiness,
        default_modules=(),
    )
    complete = await resumed.execute_stages(stages)
    assert [item[0].data for item in complete] == ['result-1', 'result-2']
    assert prompts[0] == 'first'
    assert prompts[1].startswith('second\n\nStructured inputs:\n["result-1"]')
