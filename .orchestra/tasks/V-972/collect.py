"""Read-only source capture for V-972; writes only this task's evidence."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path.cwd()
OUT = ROOT / '.orchestra/tasks/V-972/raw'
OUT.mkdir(exist_ok=True)
sources = sorted((ROOT / '.orchestra/pipelines/default/prompts').rglob('*'))
sources = [p for p in sources if p.is_file()]
sources += [ROOT / p for p in ['AGENTS.md', '.orchestra/pipelines/default/pipeline.yaml',
    '.orchestra/temp-rules.yaml', 'app/prompting.py', 'app/pipeline.py', 'app/manager.py',
    'app/temp_rules.py', 'app/kb_index.py', 'app/mcp_stdio.py', 'app/harness/prompts.py',
    'app/rules_link.py', '.orchestra/kb/README.md']]
inventory = []
for p in sources:
    data = p.read_bytes()
    rel = str(p.relative_to(ROOT))
    inventory.append({'path': rel, 'lines': len(data.splitlines()), 'bytes': len(data),
                      'sha256': hashlib.sha256(data).hexdigest()})
    # Full code snapshots remain reachable at the recorded revision; capture the
    # instruction library and generated-source owners with line numbers locally.
    (OUT / (rel.replace('/', '__') + '.txt')).write_text(
        '\n'.join(f'{i:5}\t{line}' for i, line in enumerate(data.decode().splitlines(), 1)) + '\n')
(OUT / 'inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n')
tree = ast.parse((ROOT / 'app/mcp_stdio.py').read_text())
descriptions = []
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and
        isinstance(d.func.value, ast.Name) and d.func.value.id == 'mcp' and d.func.attr == 'tool'
        for d in node.decorator_list
    ):
        doc = node.body[0]
        descriptions.append({'name': node.name, 'line': node.lineno,
                             'description_line': doc.lineno, 'description': ast.get_docstring(node)})
(OUT / 'tool-descriptions.json').write_text(json.dumps(descriptions, ensure_ascii=False, indent=2) + '\n')
with (OUT / 'commands.txt').open('w') as out:
    for cmd in [['git', 'rev-parse', 'HEAD'], ['git', 'status', '--short'],
                ['git', 'remote', '-v'], ['git', 'rev-parse', '--git-common-dir'],
                ['id'], ['stat', '-c', '%U:%G %a %n', '.', 'AGENTS.md'],
                ['rg', '-n', '^User=|^Group=', 'deploy/orchestra.service', 'deploy/orchestra.service.template'],
                ['rg', '--files', 'app'],
                ['rg', '--files', '--hidden', str(Path.home()/'.claude/skills'),
                 str(Path.home()/'.agents/skills'), '-g', 'SKILL.md']]:
        result = subprocess.run(cmd, text=True, capture_output=True)
        out.write(f'$ {json.dumps(cmd)}\nEXIT={result.returncode}\nSTDOUT:\n{result.stdout}STDERR:\n{result.stderr}\n')
print(f'captured {len(inventory)} sources, {len(descriptions)} MCP tool descriptions')
