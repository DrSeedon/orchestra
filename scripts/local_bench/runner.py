"""Reusable local workflow: freeze, prove controls, start parallel arms, seal and score."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from . import isolation, snapshot
from .process import run_process, write_json


def argv(command, config, workspace):
    values = {'{python}': sys.executable, '{config_dir}': config['_config_dir'], '{workspace}': str(workspace), '{response}': str(Path(workspace) / '.bench/response.txt'), '{transcript}': str(Path(workspace) / '.bench/transcript.jsonl')}
    result = []
    for item in command:
        for key, value in values.items():
            item = item.replace(key, value)
        result.append(item)
    return result


def environment(home, tmp):
    return {'PATH': os.defpath, 'HOME': str(home), 'TMPDIR': str(tmp), 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
            'ORCHESTRA_DB_PATH': str(Path(tmp) / 'test.db'), 'ORCHESTRA_TASK_REPOSITORY': str(Path(tmp) / 'test-tasks'),
            'GIT_CONFIG_NOSYSTEM': '1'}


def sandbox_command(config, workspace, home, command, port=0, readonly=False):
    paths = config.get('runtime_paths', [])
    if sys.prefix not in ('/usr', '/usr/local'):
        paths = [*paths, sys.prefix]
    base = isolation.mounts(config['_isolation']['bwrap'], workspace, readonly=readonly, runtime_paths=paths, home=home)
    base += ['--ro-bind', str(Path(isolation.__file__).resolve()), '/bench-network.py']
    return base + ['/usr/bin/python3', '/bench-network.py', str(port), *command]


async def evaluate(config, submitted, frozen_oracle, output, execution=None):
    work = output / 'work'
    output.mkdir(parents=True)
    snapshot.copy_tree(submitted, work)
    snapshot.overlay(work, frozen_oracle)
    context = work / '.bench'; context.mkdir()
    for name in ['response.txt', 'stdout.jsonl']:
        dest = context / ('transcript.jsonl' if name == 'stdout.jsonl' else name)
        original = execution / name if execution else None
        dest.write_bytes(original.read_bytes() if original and original.exists() else b'')
    home = output / 'home'; home.mkdir()
    tmp = output / 'tmp'; tmp.mkdir()
    cmd = argv(config['oracle']['command'], config, '/work' if config['_provider'] else work)
    env = environment('/home/bench' if config['_provider'] else home, '/tmp' if config['_provider'] else tmp)
    if config['_provider']:
        cmd = sandbox_command(config, work, home, cmd, readonly=True)
    result = await run_process(cmd, work, env, output / 'execution', timeout=config['oracle'].get('timeout_seconds', 60), grace=config['grace_seconds'])
    return {'passed': result['returncode'] == 0 and result['completion'] == 'exited', 'process': result}


def provider_command(arm, home, env):
    runtime = arm['runtime']
    binary = shutil.which(runtime)
    if not binary:
        raise RuntimeError(f'{runtime} CLI not found')
    if runtime == 'codex':
        source = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'auth.json'
        target = home / '.codex'; target.mkdir()
        shutil.copyfile(source, target / 'auth.json')
        env['CODEX_HOME'] = '/home/bench/.codex'
        cmd = [binary, '-m', arm['model'], '-s', 'danger-full-access', '-a', 'never', 'exec', '--ephemeral', '--ignore-rules', '--ignore-user-config', '--skip-git-repo-check', '--json', '-c', 'web_search="disabled"']
        if arm.get('effort'):
            cmd += ['-c', f'model_reasoning_effort="{arm["effort"]}"']
        return cmd + ['-']
    credentials = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))) / '.credentials.json'
    token = json.loads(credentials.read_text())['claudeAiOauth']['accessToken']
    env['CLAUDE_CODE_OAUTH_TOKEN'] = token
    env['CLAUDE_CONFIG_DIR'] = '/home/bench/.claude'
    env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'
    (home / '.claude').mkdir()
    (home / '.claude.json').write_text('{"hasCompletedOnboarding":true}')
    # --bare is deliberately absent: it disables subscription OAuth.
    cmd = [binary, '-p', '--model', arm['model'], '--no-session-persistence', '--dangerously-skip-permissions', '--output-format', 'stream-json', '--include-partial-messages', '--verbose', '--setting-sources', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--tools', 'Bash,Read,Write,Edit,Glob,Grep', '--max-budget-usd', str(arm['budget_usd']), '--system-prompt', 'Complete the user task in the isolated workspace. Leave your result on disk.']
    if arm.get('effort'):
        cmd += ['--effort', arm['effort']]
    return cmd


async def trial(config, arm, seed, frozen_oracle, root, start, ready):
    output = root / 'arms' / arm['name']
    output.mkdir(parents=True)
    work = output / 'work'
    home = output / 'home'; home.mkdir(mode=0o700)
    tmp = output / 'tmp'; tmp.mkdir()
    relay = None
    prepared = False
    result = {'name': arm['name'], 'runtime': arm['runtime'], 'model': arm.get('model'), 'oracle_pass': False}
    try:
        snapshot.copy_tree(seed, work)
        git_env = {**environment(home, tmp), 'GIT_AUTHOR_NAME': 'Local benchmark', 'GIT_AUTHOR_EMAIL': 'bench@local.invalid', 'GIT_COMMITTER_NAME': 'Local benchmark', 'GIT_COMMITTER_EMAIL': 'bench@local.invalid'}
        for command in [['git', 'init', '-q', '-b', 'submission'], ['git', 'add', '.'], ['git', 'commit', '-qm', 'Clean benchmark input']]:
            subprocess.run(command, cwd=work, env=git_env, check=True, capture_output=True)
        before = snapshot.inventory(work)
        result['input_sha256'] = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
        env = environment('/home/bench' if config['_provider'] else home, '/tmp' if config['_provider'] else tmp)
        if config['_provider']:
            relay = await isolation.Relay().start()
            env.update({k: f'http://127.0.0.1:{relay.port}' for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy')})
            env['NO_PROXY'] = ''
            native_command = provider_command(arm, home, env)
            version_command = sandbox_command(config, work, home, [native_command[0], '--version'])
            version = subprocess.run(version_command, cwd=work, env=env, capture_output=True, text=True, timeout=15)
            if version.returncode:
                raise RuntimeError(f'CLI version preflight failed: {version.stderr.strip()}')
            result['runtime_version'] = version.stdout.strip()
            cmd = sandbox_command(config, work, home, native_command, relay.port)
        else:
            cmd = argv(arm['command'], config, work)
        prepared = True
        ready.put_nowait((arm['name'], True))
        await start.wait()
        process = await run_process(cmd, work, env, output / 'execution', runtime=arm['runtime'], prompt=config['_prompt'], timeout=config['timeout_seconds'], grace=config['grace_seconds'], budget=arm.get('budget_usd'), prices=arm.get('prices'))
        result['process'] = process
        after = snapshot.inventory(work)
        changed, unexpected = snapshot.changes(before, after, config.get('writable_paths', ['*']))
        result.update({'changed_paths': changed, 'out_of_scope': unexpected, 'submitted_sha256': after})
        (output / 'patch.diff').write_text(snapshot.diff(seed, work, changed))
        oracle = await evaluate(config, work, frozen_oracle, output / 'oracle', output / 'execution')
        result['oracle'] = oracle
        result['oracle_pass'] = oracle['passed'] and not unexpected
    except asyncio.CancelledError:
        result['error'] = 'cancelled; execution receipt retained'
        receipt = output / 'execution/process.json'
        if receipt.exists():
            result['process'] = json.loads(receipt.read_text())
        raise
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        if not prepared:
            ready.put_nowait((arm['name'], False))
        if relay:
            await relay.close()
            write_json(output / 'relay.json', relay.events)
        # Remove only credential copies created by this arm, never the originals.
        credential = home / '.codex' / 'auth.json'
        if credential.exists():
            credential.unlink()
        write_json(output / 'result.json', result)
    return result


def summarize(config, results, prep_seconds, wall_seconds):
    receipts = [r.get('process', {}).get('accounting', {}) for r in results]
    complete = len(results) == len(config['arms']) and all(r.get('status') == 'complete' for r in receipts)
    known = sum(r.get('cost_usd') or 0 for r in receipts)
    observed_values = [r.get('observed_cost_usd', r.get('cost_usd')) for r in receipts]
    observed = sum(v for v in observed_values if v is not None) if any(v is not None for v in observed_values) else None
    prep_cost = config.get('preparation_cost_usd')
    return {'version': 1, 'runner_python_version': sys.version, 'name': config['name'], 'mode': 'provider' if config['_provider'] else 'offline_synthetic',
            'start_policy': 'parallel_after_prepare_barrier',
            'config_sha256': config['_config_sha256'], 'prompt_sha256': hashlib.sha256(config['_prompt'].encode()).hexdigest(),
            'results': results, 'accounting_complete': complete, 'arm_cost_usd': known if complete else None,
            'known_arm_cost_usd': known, 'observed_arm_cost_usd': observed, 'preparation_cost_usd': prep_cost,
            'preparation_cost_note': config.get('preparation_cost_note'),
            'preparation_fraction': prep_cost / (prep_cost + known) if complete and prep_cost is not None and prep_cost + known > 0 else None,
            'preparation_seconds': prep_seconds, 'wall_seconds': wall_seconds,
            'all_pass': len(results) == len(config['arms']) and all(r['oracle_pass'] and r.get('process', {}).get('completion') == 'exited' and r.get('process', {}).get('returncode') == 0 for r in results),
            'over_budget_observed': observed > config['budget_usd'] if config['_provider'] and observed is not None else None}


def markdown(report):
    rows = [f"# {report['name']}", '', f"Mode: **{report['mode']}**. Synthetic fixture prices are not provider charges.", '', '| Arm | Oracle | Completion | Seconds | Cost USD | Accounting |', '|---|---|---|---:|---:|---|']
    for row in report['results']:
        p = row.get('process', {}); a = p.get('accounting', {})
        price = '?' if a.get('cost_usd') is None else f"{a['cost_usd']:.6f}"
        rows.append(f"| {row['name']} | {'PASS' if row['oracle_pass'] else 'FAIL'} | {p.get('completion', row.get('error', '?'))} | {p.get('wall_seconds', 0):.3f} | {price} | {a.get('status', 'missing')} |")
    total = '?' if report['arm_cost_usd'] is None else f"{report['arm_cost_usd']:.6f}"
    fraction = '?' if report['preparation_fraction'] is None else f"{report['preparation_fraction']:.2%}"
    observed = '?' if report['observed_arm_cost_usd'] is None else f"{report['observed_arm_cost_usd']:.6f}"
    rows += ['', f"Closed receipts: {report['known_arm_cost_usd']:.6f}. Observed including partial receipts: {observed} (not a final total). Complete total: {total}.",
             f"Preparation: {report['preparation_seconds']:.3f}s; attributed cost: {report['preparation_cost_usd']}; fraction of preparation + arms: {fraction}.",
             f"Preparation attribution: {report['preparation_cost_note'] or 'not supplied; not assumed zero'}.",
             '', 'Result correctness, process completion and accounting completeness are separate. A deadline snapshot can pass its oracle while billing remains incomplete.', '']
    return '\n'.join(rows)


def validate_runtime_mounts(config, output):
    source = config['source']
    root = Path(source.get('repo', source.get('directory'))).resolve()
    protected = [root / name for name in source['include']]
    protected += [root / name for name in ('.git', '.orchestra', 'TODO.md', 'CHANGELOG.md')]
    protected += [Path(output).resolve()]
    for group in [config['oracle'].get('files', {}), config.get('controls', {}).get('reference_files', {})]:
        for origin in group.values():
            if isinstance(origin, dict):
                protected += [Path(origin['repo']) / '.git', Path(origin['repo']) / origin['path']]
            else:
                protected.append(Path(origin))
    mounts = [Path(p).resolve() for p in ['/usr', '/bin', '/lib', '/lib64', *config.get('runtime_paths', []), sys.prefix]]
    for mount in mounts:
        for hidden in protected:
            hidden = hidden.resolve()
            if hidden.is_relative_to(mount) or mount.is_relative_to(hidden):
                raise ValueError(f'runtime mount exposes benchmark input/reference: {mount}; use dependencies outside protected input paths')


async def run(config, output, allow_provider=False):
    started = time.monotonic()
    if config['_provider']:
        if not allow_provider:
            raise ValueError('provider launch requires explicit --allow-provider; no CLI was started')
        validate_runtime_mounts(config, output)
        config['_isolation'] = isolation.preflight(config.get('runtime_paths', []))
    output = Path(output).resolve()
    if 'directory' in config['source']:
        source_root = Path(config['source']['directory'])
        if any((source_root / path).is_dir() and output.is_relative_to((source_root / path).resolve()) for path in config['source']['include']):
            raise ValueError('output directory must not be inside an included input directory')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    (output / '.gitignore').write_text('*\n')
    seed = output / 'seed'
    manifest = snapshot.build(config['source'], seed)
    write_json(output / 'input.json', manifest)
    (output / 'prompt.txt').write_text(config['_prompt'])
    frozen_oracle = {}
    hidden = output / 'frozen-oracle'; hidden.mkdir()
    for index, (target, source) in enumerate(config['oracle'].get('files', {}).items()):
        dest = hidden / str(index); dest.write_bytes(snapshot.file_bytes(source)); frozen_oracle[target] = str(dest)
    write_json(output / 'oracle-sha256.json', {target: hashlib.sha256(Path(path).read_bytes()).hexdigest() for target, path in frozen_oracle.items()})
    controls = config.get('controls', {})
    control_results = {}
    if controls.get('expect_baseline_failure'):
        control_results['baseline'] = await evaluate(config, seed, frozen_oracle, output / 'baseline-control')
        if control_results['baseline']['passed']:
            write_json(output / 'controls.json', control_results)
            raise ValueError('baseline unexpectedly passes the oracle; arms not launched')
    if controls.get('reference_files'):
        reference = output / 'reference'
        snapshot.copy_tree(seed, reference)
        snapshot.overlay(reference, controls['reference_files'])
        control_results['reference'] = await evaluate(config, reference, frozen_oracle, output / 'reference-control')
        if not control_results['reference']['passed']:
            write_json(output / 'controls.json', control_results)
            raise ValueError('reference fails the oracle; arms not launched')
    write_json(output / 'controls.json', control_results)
    effective = copy.deepcopy({key: value for key, value in config.items() if not key.startswith('_')})
    write_json(output / 'config-effective.json', effective)
    replay = copy.deepcopy(effective)
    replay['source'] = {'directory': str(seed), 'include': config['source']['include']}
    replay['prompt'] = str(output / 'prompt.txt')
    replay['oracle']['files'] = frozen_oracle
    for arm in replay['arms']:
        if arm['runtime'] == 'fixture':
            arm['command'] = [arg.replace('{config_dir}', config['_config_dir']) for arg in arm['command']]
    replay['oracle']['command'] = [arg.replace('{config_dir}', config['_config_dir']) for arg in replay['oracle']['command']]
    if controls.get('reference_files'):
        replay['controls']['reference_files'] = {path: str(output / 'reference' / path) for path in controls['reference_files']}
    replay.pop('preparation_cost_usd', None)
    replay.pop('preparation_cost_note', None)
    write_json(output / 'replay.json', replay)
    prep_seconds = time.monotonic() - started
    start = asyncio.Event()
    ready = asyncio.Queue()
    tasks = [asyncio.create_task(trial(config, arm, seed, frozen_oracle, output, start, ready)) for arm in config['arms']]
    results = []
    try:
        prepared = [await ready.get() for _ in tasks]
        if not all(ok for _, ok in prepared):
            raise RuntimeError('arm preparation failed; no model was launched')
        prep_seconds = time.monotonic() - started
        start.set()
        results = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if not results:
            results = [json.loads(p.read_text()) for p in sorted((output / 'arms').glob('*/result.json'))]
        report = summarize(config, results, prep_seconds, time.monotonic() - started)
        write_json(output / 'report.json', report)
        (output / 'report.md').write_text(markdown(report))
    return report
