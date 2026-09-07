from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('role', ['orchestrator', 'sub-orchestrator', 'worker', 'full-cycle', 'reducer'])
@pytest.mark.parametrize('home', ['.claude', '.codex'])
def test_every_role_receives_the_same_native_html_skill(tmp_path, role, home):
    from app.pipeline import get_role
    from app.prompting import inject_skills_to_worktree_report

    repo = tmp_path / 'project'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    spec = get_role('default', role)
    assert 'html-artifacts' in spec.skills
    assert 'eli5' not in spec.skills
    result = inject_skills_to_worktree_report(list(spec.skills), str(repo), home)
    assert result.written > 0
    source = Path(__file__).parents[1] / '.orchestra/pipelines/default/prompts/skills/html-artifacts.md'
    assert (repo / home / 'skills/html-artifacts/SKILL.md').read_bytes() == source.read_bytes()
    assert not (repo / home / 'skills/eli5/SKILL.md').exists()
    assert not subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'])
