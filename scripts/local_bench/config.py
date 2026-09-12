"""Small versioned JSON contract; paths are relative to the configuration file."""
import hashlib
import json
import math
from pathlib import Path, PurePosixPath


def relative(value):
    p = PurePosixPath(value)
    if not value or str(p) == '.' or p.is_absolute() or '..' in p.parts or '\\' in value:
        raise ValueError(f'expected safe relative path: {value!r}')
    return str(p)


def read(path):
    path = Path(path).resolve()
    c = json.loads(path.read_text())
    allowed = {'version', 'name', 'source', 'prompt', 'oracle', 'controls', 'arms', 'timeout_seconds', 'grace_seconds', 'budget_usd', 'preparation_cost_usd', 'preparation_cost_note', 'writable_paths', 'runtime_paths'}
    if set(c) - allowed:
        raise ValueError(f'unknown configuration keys: {sorted(set(c)-allowed)}')
    if c.get('version') != 1:
        raise ValueError('version must be 1')
    base = path.parent
    c['_config_dir'] = str(base)
    c['_config_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    c['_prompt'] = (base / c['prompt']).read_text()
    source = c['source']
    if ('directory' in source) == ('repo' in source):
        raise ValueError('source must choose directory or repo+revision')
    key = 'repo' if 'repo' in source else 'directory'
    source[key] = str((base / source[key]).resolve())
    if key == 'repo' and not source.get('revision'):
        raise ValueError('source.repo requires revision')
    for item in source.get('include', []):
        relative(item)
    if not source.get('include'):
        raise ValueError('source.include must explicitly name inputs')
    if not isinstance(c['oracle'].get('command'), list) or not c['oracle']['command']:
        raise ValueError('oracle.command must be a nonempty argv list')
    if not all(isinstance(x, str) for x in c['oracle']['command']):
        raise ValueError('oracle.command argv entries must be strings')
    finite(c['oracle'].get('timeout_seconds', 60), 0.01, 'oracle timeout_seconds')
    for group in [c['oracle'].get('files', {}), c.get('controls', {}).get('reference_files', {})]:
        for target, original in list(group.items()):
            relative(target)
            if isinstance(original, dict):
                if set(original) != {'repo', 'revision', 'path'}:
                    raise ValueError('git overlay requires repo/revision/path')
                relative(original['path'])
                original['repo'] = str((base / original['repo']).resolve())
            else:
                original = (base / original).resolve()
                if not original.is_file():
                    raise ValueError(f'overlay file absent: {original}')
                group[target] = str(original)
    if c.get('controls', {}).get('expect_baseline_failure') and not c.get('controls', {}).get('reference_files'):
        raise ValueError('red baseline control requires reference_files')
    arms = c.get('arms', [])
    names = [a.get('name') for a in arms]
    if not arms or len(set(names)) != len(names):
        raise ValueError('arms must have unique names')
    for arm in arms:
        name = arm['name']
        if not isinstance(name, str) or not name or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for ch in name):
            raise ValueError('unsafe arm name')
        if arm.get('runtime') not in ('fixture', 'codex', 'claude'):
            raise ValueError('runtime must be fixture, codex or claude')
        if arm['runtime'] == 'fixture':
            if not isinstance(arm.get('command'), list) or not arm['command']:
                raise ValueError('fixture command required')
            if not all(isinstance(x, str) for x in arm['command']):
                raise ValueError('fixture command argv entries must be strings')
        elif not arm.get('model'):
            raise ValueError('provider arm requires explicit model')
        if arm.get('prices'):
            if set(arm['prices']) != {'input', 'cached_input', 'cache_write', 'output'}:
                raise ValueError('prices require input/cached_input/cache_write/output per million')
            for value in arm['prices'].values():
                finite(value, 0, 'price')
    modes = {a['runtime'] == 'fixture' for a in arms}
    if len(modes) != 1:
        raise ValueError('do not mix synthetic fixtures and provider arms in one comparison')
    c['_provider'] = not next(iter(modes))
    for key, default, minimum in [('timeout_seconds', 600, 0.01), ('grace_seconds', 15, 0.01), ('budget_usd', 0, 0)]:
        c.setdefault(key, default)
        finite(c[key], minimum, key)
    if c.get('preparation_cost_usd') is not None:
        finite(c['preparation_cost_usd'], 0, 'preparation_cost_usd')
        if not c.get('preparation_cost_note'):
            raise ValueError('preparation_cost_note required for attributed cost')
    if c['_provider']:
        for a in arms:
            finite(a.get('budget_usd', 0), 0.000001, 'arm budget_usd')
        if sum(a['budget_usd'] for a in arms) > c['budget_usd']:
            raise ValueError('sum of reserved arm budgets exceeds run budget')
    c['runtime_paths'] = [str((base / p).resolve()) for p in c.get('runtime_paths', [])]
    return c


def finite(value, minimum, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'{label} must be a finite number >= {minimum}')
