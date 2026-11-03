"""Check supplied-copy structure only; this does not replace real pipeline assembly."""
import ast
from pathlib import Path

root = Path.cwd()
prompts = root / '.orchestra/pipelines/default/prompts'
ast.parse((root / 'tests/test_default_pipeline.py').read_text())
print('PASS: changed assembly test source parses')
for tag in ('user-answer-format', 'telegram-formatting'):
    for role in ('orchestrator', 'sub-orchestrator', 'worker', 'full-cycle', 'reducer'):
        lines = (prompts / 'roles' / f'{role}.md').read_text().splitlines()
        expected = int(role == 'orchestrator')
        assert lines.count(f'<{tag}>') == expected, (tag, role)
        assert lines.count(f'</{tag}>') == expected, (tag, role)
    for path in (prompts / 'modules').glob('*.md'):
        assert f'<{tag}>' not in path.read_text(), (tag, path.name)
print('PASS: answer-format and Telegram blocks retain a single top-level owner')
for name in ('orchestration', 'worker-lifecycle', 'communication-style'):
    lines = (prompts / 'modules' / f'{name}.md').read_text().splitlines()
    assert lines.count(f'<{name}>') == 1, name
    assert lines.count(f'</{name}>') == 1, name
print('PASS: changed shared module wrappers remain singular and balanced')
for relative in (
    '.orchestra/tasks/V-1256/tmp/orchestra-test-catalog-6n1ezx3n/projects.yaml',
    '.orchestra/tasks/V-1256/tmp/uv-1263a287bf9d3eb7.lock',
):
    assert not (root / relative).exists(), relative
print('PASS: only the two named generated artifacts were removed')
for name in ('pytest.log', 'instruction-contract.log', 'pipeline-contract.log',
             'contract-status.log', 'static-check.log'):
    path = root / '.orchestra/tasks/V-1256' / name
    assert path.is_file() and path.stat().st_size > 0, name
print('PASS: original failed-check logs and earlier static-check evidence retained')
print('NOT VERIFIED: real pipeline assembly, runtime delivery, contracts or model adherence')
