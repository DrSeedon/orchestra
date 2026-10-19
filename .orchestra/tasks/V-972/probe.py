"""Deterministic composition checks; no provider, HTTP, database or source writes."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path.cwd()))
import app
from app.pipeline import build_system_prompt, load_pipeline, resolve_role, validate_spawn
from app.kb_index import kb_index_block
from app.project_catalog import own_catalog_path
import yaml

root = Path.cwd()
out = root / '.orchestra/tasks/V-972/raw'
print('app=', app.__file__)
print('revision=', subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
cfg = load_pipeline('default')
for name in cfg.roles:
    role = resolve_role(cfg, name)
    prompt = build_system_prompt('default', name)
    (out / f'assembled-{name}.txt').write_text(prompt)
    print(json.dumps({'role': name, 'layers': role.prompt_layers, 'modules': role.modules,
        'skills': role.skills, 'can_spawn': role.can_spawn,
        'markers': {marker: prompt.find(marker) for marker in [
            '<platform>', '<role>', '<git-workflow>', '<orchestration>',
            '<worker-lifecycle>', '<report-format>', '<user-values>']},
        'bytes': len(prompt.encode()), 'sha256': hashlib.sha256(prompt.encode()).hexdigest()}, ensure_ascii=False))
print('KB index:')
print(kb_index_block(str(root)))
print('catalog source for a separate scope:', own_catalog_path('/example/project'))
for parent in ['orchestrator', 'sub-orchestrator', 'full-cycle']:
    try:
        validate_spawn('default', parent, 'sub-orchestrator')
    except ValueError as error:
        print('validate_spawn:', parent, '-> sub-orchestrator:', type(error).__name__, str(error))
for path in ['.codex/skills/html-artifacts/SKILL.md',
             '.codex/skills/html-artifacts/references/animation.md']:
    result = subprocess.run(['awk', '/^```html motion-template/{f=1;next} f&&/^```/{exit} f', path],
                            text=True, capture_output=True)
    print('awk scaffold:', path, 'exit=', result.returncode, 'lines=', len(result.stdout.splitlines()),
          'bytes=', len(result.stdout.encode()), 'stderr=', repr(result.stderr))

# Execute only the extracted pure ownership helper and loaded in-memory update
# branch. Importing/running a service manager is unnecessary and out of scope.
tree = ast.parse((root / 'app/manager.py').read_text())
ownership = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'ownership_block')
method = next(n for c in tree.body if isinstance(c, ast.ClassDef) for n in c.body
              if isinstance(n, ast.FunctionDef) and n.name == 'update_session_fields')
ns = {'OWNERSHIP_MARKER': '\n\n## Directory ownership\n', 'AgentSession': object}
exec(compile(ast.Module(body=[ownership, method], type_ignores=[]), 'app/manager.py (extracted)', 'exec'), ns)
print('ownership_block:', repr(ns['ownership_block'](['app'])))
session = SimpleNamespace(loaded=True, prompt_overlay='prior overlay',
                          system_prompt='old complete prompt', _current_prompt='old complete prompt', _persist=lambda: None)
manager = SimpleNamespace(_UPDATABLE_FIELDS={'description', 'system_prompt', 'tg_topic'},
                          get_by_name=lambda name, scope: session)
ns['update_session_fields'](manager, 'fake', 'local', system_prompt='Expertise: asyncio')
print('loaded update_session_fields:', json.dumps({k: getattr(session, k) for k in
      ['prompt_overlay', 'system_prompt', '_current_prompt']}))

print('Global references and installed copies:')
paths = [Path.home()/'.claude/skills/html-artifacts/SKILL.md',
         Path.home()/'.claude/skills/video-artifact/SKILL.md',
         Path.home()/'.claude/skills/vps-orchestra/SKILL.md',
         Path.home()/'.agents/skills/laptop-access/SKILL.md',
         Path.home()/'.claude/skills/laptop-access/SKILL.md']
for path in paths:
    print(path, 'exists=', path.is_file())
    if path.is_file():
        data = path.read_bytes()
        (out / ('global-' + str(path.relative_to(Path.home())).replace('/', '__') + '.txt')).write_bytes(data)
        print('sha256=', hashlib.sha256(data).hexdigest(), 'lines=', len(data.splitlines()))
for name in ['html-artifacts', 'video-artifact', 'laptop-access']:
    installed = root/f'.codex/skills/{name}/SKILL.md'
    canonical = root/f'.orchestra/pipelines/default/prompts/skills/{name}.md'
    print(name, 'installed=', installed.is_file(), 'same=', installed.is_file() and installed.read_bytes() == canonical.read_bytes())

rules = yaml.safe_load((root/'.orchestra/temp-rules.yaml').read_text())['rules']
at = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
for rule in rules:
    print('temp rule:', rule['id'], 'targets=', rule['targets'], 'mode=', rule['mode'],
          'active at', at.isoformat(), '=', rule['mode'] != 'expires' or datetime.fromisoformat(rule['expires_at']) > at)
print('Repository drift:')
result = subprocess.run(['git', 'diff', '--stat', 'HEAD', 'main', '--',
    '.orchestra/pipelines/default/prompts', '.orchestra/pipelines/default/pipeline.yaml',
    '.orchestra/temp-rules.yaml', 'AGENTS.md', 'app/prompting.py', 'app/manager.py',
    'app/kb_index.py', 'app/mcp_stdio.py'], text=True, capture_output=True)
print('exit=', result.returncode, 'stdout=', repr(result.stdout), 'stderr=', repr(result.stderr))
