import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.local_bench.accounting import Accounting
from scripts.local_bench.config import read
from scripts.local_bench import isolation, runner, snapshot
from scripts.local_bench.process import run_process

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / 'scripts/local_bench/examples/repair/bench.json'


def config():
    return read(EXAMPLE)


def execute(c, tmp_path):
    return asyncio.run(runner.run(c, tmp_path / 'run'))


def test_parallel_complete_oracle_and_generated_files(tmp_path):
    report = execute(config(), tmp_path)
    assert report['mode'] == 'offline_synthetic'
    assert [r['oracle_pass'] for r in report['results']] == [True, True, False]
    assert len({r['input_sha256'] for r in report['results']}) == 1
    assert all(r['out_of_scope'] == [] for r in report['results'])
    processes = [r['process'] for r in report['results']]
    # Intervals overlap, not a fragile total-duration performance threshold.
    assert max(p['started_unix'] for p in processes) < min(p['started_unix'] + p['wall_seconds'] for p in processes)
    assert report['arm_cost_usd'] == pytest.approx(0.6)
    assert report['accounting_complete'] is True
    assert report['preparation_fraction'] == 0
    assert (tmp_path / 'run/report.md').is_file()
    assert all((tmp_path / 'run/arms' / r['name'] / 'execution/stdout.jsonl').is_file() for r in report['results'])


def test_deadline_captures_closing_usage_before_kill(tmp_path):
    c = config(); c['arms'] = [c['arms'][0]]
    c['arms'][0]['command'][-1] = 'graceful'
    c['timeout_seconds'] = 0.3; c['grace_seconds'] = 0.5
    report = execute(c, tmp_path)
    row = report['results'][0]
    assert row['oracle_pass'] is True
    assert row['process']['completion'] == 'deadline'
    assert row['process']['accounting']['final_received'] is True
    assert row['process']['accounting']['cost_usd'] == 0.2
    assert row['process']['accounting']['usage']['output_tokens'] == 5
    assert report['all_pass'] is False
    assert report['accounting_complete'] is True


def test_hard_kill_preserves_partial_cost_and_reaps(tmp_path):
    c = config(); c['arms'] = [c['arms'][0]]
    c['arms'][0]['command'][-1] = 'uncooperative'
    c['timeout_seconds'] = 0.3; c['grace_seconds'] = 0.1
    report = execute(c, tmp_path)
    row = report['results'][0]; process = row['process']
    assert process['hard_killed'] is True
    assert process['accounting']['status'] == 'partial'
    assert process['accounting']['cost_usd'] is None
    assert process['accounting']['observed_cost_usd'] == 0.1
    assert report['arm_cost_usd'] is None
    assert report['preparation_fraction'] is None
    with pytest.raises(ProcessLookupError):
        os.kill(process['pid'], 0)


def test_no_oracle_weakening_by_submitted_test(tmp_path):
    c = config(); c['arms'] = [c['arms'][0]]
    c['arms'][0]['command'] = ['{python}', '-c', "from pathlib import Path; Path('check.py').write_text('print(123)')"]
    c['writable_paths'] = ['*']
    report = execute(c, tmp_path)
    assert report['results'][0]['oracle_pass'] is False
    assert (tmp_path / 'run/arms/correct-a/oracle/work/check.py').read_text() == Path(c['oracle']['files']['check.py']).read_text()


def test_oracle_failure_blocks_all_arms(tmp_path):
    c = config()
    c['controls']['reference_files']['calc.py'] = str(EXAMPLE.parent / 'source/calc.py')
    with pytest.raises(ValueError, match='reference fails'):
        execute(c, tmp_path)
    assert not (tmp_path / 'run/arms').exists()


def test_unexpected_green_baseline_blocks_all_arms(tmp_path):
    c = config()
    c['oracle']['command'] = ['{python}', '-c', 'pass']
    with pytest.raises(ValueError, match='baseline unexpectedly passes'):
        execute(c, tmp_path)
    assert not (tmp_path / 'run/arms').exists()


def test_different_question_uses_only_configuration(tmp_path):
    source = tmp_path / 'source'; source.mkdir(); (source / 'input.txt').write_text('c\na\nb\n')
    oracle = tmp_path / 'oracle.py'; oracle.write_text("from pathlib import Path\nassert Path('answer.txt').read_text() == 'a,b,c'\n")
    prompt = tmp_path / 'prompt.txt'; prompt.write_text('Sort input lines and write comma-separated answer.txt.')
    raw = {'version': 1, 'name': 'Sorting question', 'source': {'directory': 'source', 'include': ['input.txt']}, 'prompt': 'prompt.txt',
           'oracle': {'command': ['{python}', 'oracle.py'], 'files': {'oracle.py': 'oracle.py'}}, 'writable_paths': ['answer.txt'],
           'arms': [{'name': 'sorter', 'runtime': 'fixture', 'command': ['{python}', '-c', "from pathlib import Path; import json; Path('answer.txt').write_text(','.join(sorted(Path('input.txt').read_text().splitlines()))); print(json.dumps({'type':'bench.result','cost_usd':0}))"]}]}
    path = tmp_path / 'bench.json'; path.write_text(json.dumps(raw))
    report = execute(read(path), tmp_path)
    assert report['all_pass'] is True
    assert report['preparation_cost_usd'] is None  # Missing attribution is not zero.
    assert report['preparation_fraction'] is None


def test_provider_requires_consent_and_namespace_before_cli(tmp_path, monkeypatch):
    c = config(); c['_provider'] = True
    c['arms'] = [{'name': 'x', 'runtime': 'claude', 'model': 'example', 'budget_usd': 1}]
    called = []
    monkeypatch.setattr(runner, 'provider_command', lambda *args: called.append(True))
    with pytest.raises(ValueError, match='allow-provider'):
        execute(c, tmp_path)
    def denied(*args):
        raise RuntimeError('приватный /tmp недоступен: запрещены непривилегированные user namespaces')
    monkeypatch.setattr(isolation, 'preflight', denied)
    with pytest.raises(RuntimeError, match='user namespaces'):
        asyncio.run(runner.run(c, tmp_path / 'other', allow_provider=True))
    assert called == []
    assert not (tmp_path / 'other').exists()


def test_claude_subscription_command_never_bare(tmp_path, monkeypatch):
    creds = tmp_path / 'credentials'; creds.mkdir()
    (creds / '.credentials.json').write_text(json.dumps({'claudeAiOauth': {'accessToken': 'synthetic-test-token'}}))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(creds))
    monkeypatch.setattr(runner.shutil, 'which', lambda _: '/usr/bin/claude')
    home = tmp_path / 'home'; home.mkdir(); env = {}
    cmd = runner.provider_command({'runtime': 'claude', 'model': 'test', 'budget_usd': 1}, home, env)
    assert '--bare' not in cmd
    assert '--include-partial-messages' in cmd
    assert env['CLAUDE_CODE_OAUTH_TOKEN'] == 'synthetic-test-token'
    assert 'ANTHROPIC_API_KEY' not in env


def test_snapshot_cannot_follow_symlinks_or_answer_history(tmp_path):
    source = tmp_path / 'source'; source.mkdir(); secret = tmp_path / 'secret'; secret.write_text('hidden')
    (source / 'alias').symlink_to(secret)
    with pytest.raises(ValueError, match='symlink'):
        snapshot.build({'directory': str(source), 'include': ['alias']}, tmp_path / 'dest')
    (source / '.orchestra').mkdir()
    with pytest.raises(ValueError, match='forbidden'):
        snapshot.build({'directory': str(source), 'include': ['.orchestra']}, tmp_path / 'dest2')


def test_rogue_submission_symlink_is_rejected_before_oracle(tmp_path):
    c = config(); c['arms'] = [c['arms'][0]]
    c['arms'][0]['command'] = ['{python}', '-c', "from pathlib import Path; Path('escape').symlink_to('/etc/passwd')"]
    report = execute(c, tmp_path)
    assert 'symlink' in report['results'][0]['error']
    assert not (tmp_path / 'run/arms/correct-a/oracle').exists()


def test_no_run_directory_overwrite(tmp_path):
    (tmp_path / 'run').mkdir(); (tmp_path / 'run/proof').write_text('keep')
    with pytest.raises(FileExistsError):
        execute(config(), tmp_path)
    assert (tmp_path / 'run/proof').read_text() == 'keep'


def test_namespace_diagnostic_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, 'bwrap_path', lambda: '/fake/bwrap')
    monkeypatch.setattr(isolation.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1, '', 'bwrap: setting up uid map: Permission denied'))
    with pytest.raises(RuntimeError) as raised:
        isolation.preflight()
    text = str(raised.value)
    assert 'приватный /tmp недоступен' in text
    assert 'user namespaces' in text and 'apparmor_restrict_unprivileged_userns' in text
    assert 'решение владельца' in text and 'другую машину' in text


def test_bwrap_uses_private_tmp_and_proc_and_no_host_home(tmp_path):
    cmd = isolation.mounts('/bwrap', tmp_path / 'work', home=tmp_path / 'home')
    assert ['--tmpfs', '/tmp'] == cmd[cmd.index('--tmpfs'):cmd.index('--tmpfs') + 2]
    assert '--unshare-pid' in cmd and '--unshare-user' in cmd
    assert '--proc' in cmd
    assert ['--bind', '/home', '/home'] not in [cmd[i:i+3] for i in range(len(cmd))]


def test_codex_accounting_does_not_double_cache():
    ledger = Accounting('codex', {'input': 10, 'cached_input': 1, 'cache_write': 20, 'output': 30})
    ledger.feed({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 80, 'output_tokens': 10}})
    assert ledger.receipt()['cost_usd'] == pytest.approx((20*10+80+10*30)/1e6)


def test_claude_incomplete_usage_is_not_final_cost():
    ledger = Accounting('claude')
    row = {'type': 'assistant', 'message': {'id': 'a', 'usage': {'input_tokens': 2, 'cache_read_input_tokens': 100, 'output_tokens': 1}}}
    ledger.feed(row); ledger.feed(row)
    assert ledger.receipt()['usage']['input_tokens'] == 2
    assert ledger.receipt()['status'] == 'partial'
    assert ledger.receipt()['cost_usd'] is None
    ledger.feed({'type': 'result', 'total_cost_usd': 1.25, 'usage': {'input_tokens': 2, 'output_tokens': 20}})
    assert ledger.receipt()['cost_usd'] == 1.25
    assert ledger.receipt()['status'] == 'complete'


def test_accounting_rejects_invalid_and_unpriced_is_unknown():
    ledger = Accounting('fixture'); ledger.feed({'type': 'bench.result', 'cost_usd': -1})
    assert ledger.receipt()['cost_usd'] is None
    assert ledger.receipt()['errors']
    ledger = Accounting('codex'); ledger.feed({'type': 'turn.completed', 'usage': {'input_tokens': 5}})
    assert ledger.receipt()['status'] == 'unpriced'
    assert ledger.receipt()['cost_usd'] is None


def test_preparation_fraction_requires_complete_attribution():
    c = config(); c['arms'] = [c['arms'][0]]; c['preparation_cost_usd'] = 6
    result = {'name': 'x', 'oracle_pass': True, 'process': {'completion': 'exited', 'returncode': 0, 'accounting': {'status': 'complete', 'cost_usd': 2}}}
    assert runner.summarize(c, [result], 1, 2)['preparation_fraction'] == 0.75
    result['process']['accounting']['status'] = 'partial'
    assert runner.summarize(c, [result], 1, 2)['preparation_fraction'] is None


def test_git_overlay_is_pinned(tmp_path):
    repo = tmp_path / 'repo'; repo.mkdir()
    def git(*cmd):
        return subprocess.check_output(['git', *cmd], cwd=repo, env={**os.environ, 'GIT_AUTHOR_NAME': 'test', 'GIT_AUTHOR_EMAIL': 'test@local', 'GIT_COMMITTER_NAME': 'test', 'GIT_COMMITTER_EMAIL': 'test@local'}, text=True).strip()
    git('init', '-q'); (repo / 'oracle.py').write_text('pinned'); git('add', '.'); git('commit', '-qm', 'oracle')
    revision = git('rev-parse', 'HEAD'); (repo / 'oracle.py').write_text('changed')
    assert snapshot.file_bytes({'repo': str(repo), 'revision': revision, 'path': 'oracle.py'}) == b'pinned'


def test_partial_stream_keeps_closed_response_output_without_inventing_final_bill():
    ledger = Accounting('claude')
    ledger.feed({'type': 'stream_event', 'event': {'type': 'message_start', 'message': {'id': 'a', 'usage': {'input_tokens': 4, 'output_tokens': 1}}}})
    ledger.feed({'type': 'stream_event', 'event': {'type': 'message_delta', 'usage': {'output_tokens': 88}}})
    ledger.feed({'type': 'stream_event', 'event': {'type': 'message_stop'}})
    ledger.feed({'type': 'assistant', 'message': {'id': 'a', 'usage': {'input_tokens': 4, 'output_tokens': 1}}})
    receipt = ledger.receipt()
    assert receipt['usage']['output_tokens'] == 88
    assert receipt['usage']['input_tokens'] == 4
    assert receipt['completed_messages'] == 1
    assert receipt['status'] == 'partial' and receipt['cost_usd'] is None


def test_cancellation_leaves_closing_receipt(tmp_path):
    async def scenario():
        work = tmp_path / 'work'; work.mkdir()
        output = tmp_path / 'execution'
        env = runner.environment(tmp_path, tmp_path)
        task = asyncio.create_task(run_process([sys.executable, str(EXAMPLE.parent / 'fixture.py'), 'graceful'], work, env, output, timeout=20, grace=0.5))
        for _ in range(100):
            if (output / 'accounting.json').exists():
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail('fixture never emitted usage')
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        result = json.loads((output / 'process.json').read_text())
        assert result['completion'] == 'cancelled'
        assert result['accounting']['cost_usd'] == 0.2
        with pytest.raises(ProcessLookupError):
            os.kill(result['pid'], 0)
    asyncio.run(scenario())


def test_bad_preparation_does_not_start_other_arms(tmp_path, monkeypatch):
    c = config(); c['arms'] = c['arms'][:2]
    original = runner.argv
    def command(cmd, cfg, workspace):
        if 'correct-b' in str(workspace):
            raise ValueError('deliberate preparation failure')
        return original(cmd, cfg, workspace)
    monkeypatch.setattr(runner, 'argv', command)
    with pytest.raises(RuntimeError, match='preparation failed'):
        execute(c, tmp_path)
    assert not list((tmp_path / 'run/arms').glob('*/execution/stdout.jsonl'))
    assert (tmp_path / 'run/report.json').is_file()


def test_config_rejects_traversal_typos_and_mixed_billing(tmp_path):
    raw = json.loads(EXAMPLE.read_text())
    raw['prompt'] = str(EXAMPLE.parent / 'prompt.txt')
    raw['source']['directory'] = str(EXAMPLE.parent / 'source')
    raw['oracle']['files']['check.py'] = str(EXAMPLE.parent / 'oracle.py')
    raw['controls']['reference_files']['calc.py'] = str(EXAMPLE.parent / 'reference.py')
    file = tmp_path / 'bench.json'
    raw['source']['include'] = ['../hidden']; file.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='relative path'):
        read(file)
    raw['source']['include'] = ['calc.py']; raw['timeot_seconds'] = 5; file.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='unknown configuration'):
        read(file)
    del raw['timeot_seconds']; raw['arms'][0] = {'name': 'real', 'runtime': 'claude', 'model': 'x', 'budget_usd': 1}; file.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='mix synthetic'):
        read(file)


def test_progress_cost_is_not_promoted_when_closing_cost_is_missing():
    ledger = Accounting('fixture')
    ledger.feed({'type': 'bench.usage', 'cost_usd': 0.1})
    ledger.feed({'type': 'bench.result', 'usage': {'output_tokens': 9}})
    assert ledger.receipt()['cost_usd'] is None
    assert ledger.receipt()['status'] == 'unpriced'


def test_terminal_billing_is_not_overwritten_by_late_messages():
    ledger = Accounting('claude')
    ledger.feed({'type': 'result', 'total_cost_usd': 1.2, 'usage': {'output_tokens': 99}})
    ledger.feed({'type': 'assistant', 'message': {'id': 'late', 'usage': {'output_tokens': 1}}})
    assert ledger.receipt()['usage']['output_tokens'] == 99


def test_internal_symlink_ancestor_is_also_rejected(tmp_path):
    source = tmp_path / 'source'; source.mkdir(); hidden = source / 'hidden'; hidden.mkdir()
    (hidden / 'answer').write_text('hidden'); (source / 'alias').symlink_to(hidden, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        snapshot.build({'directory': str(source), 'include': ['alias/answer']}, tmp_path / 'out')


def test_diff_does_not_execute_candidate_git_config(tmp_path):
    before = tmp_path / 'before'; after = tmp_path / 'after'; before.mkdir(); after.mkdir()
    (before / 'code.py').write_text('old\n'); (after / 'code.py').write_text('new\n')
    (after / '.git').mkdir(); (after / '.git/config').write_text('[diff]\n external = touch SENTINEL\n')
    output = snapshot.diff(before, after, ['code.py'])
    assert '-old' in output and '+new' in output
    assert not (after / 'SENTINEL').exists()


def test_cli_offline_command_has_expected_exit_and_artifact(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'scripts.local_bench', 'run', str(EXAMPLE), '--output', str(tmp_path / 'cli')], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stderr
    assert str(tmp_path / 'cli/report.md') in result.stdout
    assert json.loads((tmp_path / 'cli/report.json').read_text())['mode'] == 'offline_synthetic'


def test_text_answer_is_available_to_external_oracle_without_source_edits(tmp_path):
    c = config(); c.pop('controls'); c['arms'] = [c['arms'][0]]
    c['arms'][0]['command'] = ['{python}', '-c', "import json; print(json.dumps({'type':'bench.result','response':'forty-two','cost_usd':0}))"]
    c['oracle'] = {'command': ['{python}', '-c', "from pathlib import Path; import sys; assert Path(sys.argv[1]).read_text() == 'forty-two'; assert 'bench.result' in Path(sys.argv[2]).read_text()", '{response}', '{transcript}'], 'files': {}}
    report = execute(c, tmp_path)
    assert report['all_pass'] is True
    assert report['results'][0]['changed_paths'] == []
    assert report['results'][0]['oracle_pass'] is True


def test_runtime_mount_cannot_expose_reference_or_live_repository(tmp_path):
    c = config()
    c['runtime_paths'] = [str(EXAMPLE.parent)]
    with pytest.raises(ValueError, match='mount exposes'):
        runner.validate_runtime_mounts(c, tmp_path)


def test_runtime_dependency_mount_outside_protected_inputs_is_allowed(tmp_path):
    c = config(); deps = tmp_path / 'dependencies'; deps.mkdir()
    c['runtime_paths'] = [str(deps)]
    runner.validate_runtime_mounts(c, tmp_path / 'output')


def test_saved_replay_uses_frozen_inputs_without_rewriting_runner(tmp_path):
    first = tmp_path / 'first'; second = tmp_path / 'second'
    c = config()
    original = asyncio.run(runner.run(c, first))
    replay = read(first / 'replay.json')
    repeated = asyncio.run(runner.run(replay, second))
    assert [r['oracle_pass'] for r in repeated['results']] == [r['oracle_pass'] for r in original['results']]
    assert [r['input_sha256'] for r in repeated['results']] == [r['input_sha256'] for r in original['results']]
    assert repeated['preparation_cost_usd'] is None  # Do not bill the old authoring effort again.


def test_deadline_also_covers_child_that_never_reads_large_stdin(tmp_path):
    async def scenario():
        script = "import signal,time,json; signal.signal(signal.SIGINT, lambda *a: (print(json.dumps({'type':'bench.result','cost_usd':0.2}),flush=True),exit(0))); time.sleep(60)"
        result = await asyncio.wait_for(run_process([sys.executable, '-c', script], tmp_path, runner.environment(tmp_path, tmp_path), tmp_path / 'execution', prompt='x'*2_000_000, timeout=0.3, grace=0.3), timeout=5)
        assert result['completion'] == 'deadline'
        assert result['accounting']['cost_usd'] == 0.2
        assert result['stdin_sent'] is False
    asyncio.run(scenario())


def test_output_inside_copied_input_is_refused_before_recursive_copy(tmp_path):
    c = config(); source = tmp_path / 'source'; source.mkdir(); (source / 'app').mkdir()
    (source / 'app/code.py').write_text('x=1')
    c['source'] = {'directory': str(source), 'include': ['app']}
    with pytest.raises(ValueError, match='inside an included input'):
        asyncio.run(runner.run(c, source / 'app/output'))
    assert not (source / 'app/output').exists()


@pytest.mark.parametrize('runtime', ['claude', 'codex'])
def test_provider_protocol_end_to_end_uses_only_stub_processes(tmp_path, monkeypatch, runtime):
    c = config(); c['_provider'] = True; c['budget_usd'] = 1
    prices = {'input': 1, 'cached_input': 0.1, 'cache_write': 2, 'output': 2}
    c['arms'] = [{'name': 'stub', 'runtime': runtime, 'model': 'not-a-provider-call', 'budget_usd': 1, 'prices': prices}]
    monkeypatch.setattr(isolation, 'preflight', lambda *a: {'bwrap': 'never-executed'})
    monkeypatch.setattr(runner, 'sandbox_command', lambda cfg, work, home, command, *a, **k: command)
    events = [{'type': 'result', 'result': 'fixed', 'total_cost_usd': 0.25, 'usage': {'input_tokens': 10, 'output_tokens': 5}}] if runtime == 'claude' else [
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'fixed'}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 80, 'output_tokens': 10}}]
    code = "from pathlib import Path; import json; Path('calc.py').write_text('def total(values):\\n    return sum(values)\\n'); events=" + repr(events) + "; [print(json.dumps(e),flush=True) for e in events]"
    monkeypatch.setattr(runner, 'provider_command', lambda *a: [sys.executable, '-c', code])
    report = asyncio.run(runner.run(c, tmp_path / 'provider-stub', allow_provider=True))
    assert report['all_pass'] is True
    assert report['accounting_complete'] is True
    assert report['arm_cost_usd'] == pytest.approx(0.25 if runtime == 'claude' else 0.000048)
    assert (tmp_path / 'provider-stub/arms/stub/execution/response.txt').read_text() == 'fixed'


def test_codex_cache_write_is_not_charged_as_fresh_input():
    ledger = Accounting('codex', {'input': 10, 'cached_input': 1, 'cache_write': 20, 'output': 30})
    ledger.feed({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 60, 'cache_write_input_tokens': 20, 'output_tokens': 10}})
    assert ledger.receipt()['cost_usd'] == pytest.approx(0.00096)


def test_positive_preflight_probe_executes_under_real_network_filter(tmp_path, monkeypatch):
    import ctypes
    if sys.platform != 'linux' or ctypes.CDLL(None).syscall(444, 0, 0, 1) < 4:
        pytest.skip('Landlock ABI >=4 required for real network-only control')
    try:
        ctypes.CDLL('libseccomp.so.2')
    except OSError:
        pytest.skip('libseccomp required for network control')
    real_run = subprocess.run
    commands = []
    def fake_bwrap(cmd, **kwargs):
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, '', '')
    class Library:
        def syscall(self, *args):
            return 4
    monkeypatch.setattr(isolation, 'bwrap_path', lambda: '/fake/bwrap')
    monkeypatch.setattr(isolation.subprocess, 'run', fake_bwrap)
    monkeypatch.setattr(isolation.C, 'CDLL', lambda *a, **k: Library())
    assert isolation.preflight()['child_proc'] is True
    probe = commands[-1][-1]
    compile(probe, 'namespace-preflight', 'exec')
    # Only the mount setup is simulated; the generated Python and TCP filter execute.
    result = real_run([sys.executable, str(Path(isolation.__file__)), '0', sys.executable, '-c', probe], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
