"""V-1152: mechanical assembly checks for the delegation prompt owners.

These tests check which modules reach which roles, that each owner arrives once and that the
assembled text is static; they deliberately do not assert on rule wording.
"""
import re

import pytest

from app import pipeline

OWNERS = ('model-routing', 'orchestration', 'worker-lifecycle', 'report-format')
PROMPTS = pipeline.PIPELINES_DIR / 'default' / 'prompts'


def _roles():
    return pipeline.load_pipeline('default').roles


@pytest.mark.parametrize('role', sorted(_roles()))
def test_each_owner_body_reaches_exactly_the_roles_that_declare_it(role):
    declared = set(pipeline.resolve_role(pipeline.load_pipeline('default'), role).modules)
    prompt = pipeline.build_system_prompt('default', role)
    for owner in OWNERS:
        body = (PROMPTS / 'modules' / f'{owner}.md').read_text(encoding='utf-8').strip()
        # A kept tag with an emptied or lost body must fail: compare the whole current file.
        assert body, owner
        assert prompt.count(body) == (1 if owner in declared else 0), (role, owner)
        assert len(re.findall(rf'^<{owner}>$', prompt, flags=re.M)) == (1 if owner in declared else 0)


def test_routing_owners_reach_orchestrators_and_reports_reach_workers():
    manifest = pipeline.load_pipeline('default')
    for role in ('worker', 'reducer'):
        modules = set(pipeline.resolve_role(manifest, role).modules)
        assert not modules & {'model-routing', 'orchestration', 'worker-lifecycle'}
    for role in ('orchestrator', 'sub-orchestrator'):
        modules = set(pipeline.resolve_role(manifest, role).modules)
        assert {'model-routing', 'orchestration', 'worker-lifecycle'} <= modules
    assert 'report-format' in pipeline.resolve_role(manifest, 'worker').modules


@pytest.mark.parametrize('role', sorted(_roles()))
def test_assembly_is_static_and_carries_no_worker_memory(role):
    first = pipeline.build_system_prompt('default', role)
    assert first == pipeline.build_system_prompt('default', role)
    from app.prompting import strip_worker_memory
    assert strip_worker_memory(first) == first


@pytest.mark.parametrize('path', [
    'modules/model-routing.md', 'modules/orchestration.md', 'modules/worker-lifecycle.md',
    'modules/report-format.md', 'roles/orchestrator.md', 'roles/sub-orchestrator.md',
])
def test_changed_prompt_owners_are_english(path):
    assert not re.search('[Ѐ-ӿ]', (PROMPTS / path).read_text(encoding='utf-8'))
