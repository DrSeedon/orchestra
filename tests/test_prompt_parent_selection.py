import pytest
from unittest.mock import MagicMock


def test_shared_project_prompt_uses_actual_parent_and_preserves_overlay(monkeypatch):
    from app.manager import SessionManager
    monkeypatch.setattr('app.manager.ROLE_SYSTEM_PROMPT', lambda *a: 'Owner {orchestrator_name}; worker {worker_name}')
    monkeypatch.setattr('app.manager.refresh_worker_memory', lambda prompt, *a, **kw: prompt)
    manager = SessionManager()
    manager._find_orchestrator_name = MagicMock(return_value='wrong-parent')
    for parent in ['orchestrator-A', 'orchestrator-B']:
        prompt, overlay = manager.assemble_prompt(
            pipeline='default', role='worker', scope='/same-project', is_orch=False,
            name='child', owned_dirs=[], branch='task-42/child',
            stored_overlay='\nIndividual instructions', old_prompt='', parent_name=parent,
        )
        assert f'Owner {parent}' in prompt
        assert 'Individual instructions' in prompt
        assert 'wrong-parent' not in prompt
    manager._find_orchestrator_name.assert_not_called()


def test_connection_failure_does_not_look_like_healthy_attachment():
    from app.session import AgentSession
    s = AgentSession(id='s', name='s', cwd='/repo', scope='/repo')
    s._runtime_error = 'thread already has an active writer'
    info = s.to_dict()
    assert info['runtime_connection'] == 'failed'
    assert info['runtime_error'] == 'thread already has an active writer'


def test_ambiguous_project_parent_is_not_selected_by_iteration_order():
    import pytest
    from types import SimpleNamespace
    from app.manager import SessionManager
    manager = SessionManager()
    manager.sessions = {name: SimpleNamespace(name=name, is_orchestrator=True, scope='/repo')
                        for name in ['A', 'B']}
    with pytest.raises(ValueError, match='specify'):
        manager._find_orchestrator_name('/repo')


@pytest.mark.asyncio
async def test_failed_owned_backend_is_not_reused_for_new_submission():
    import pytest
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.session import AgentSession
    s = AgentSession(id='s', name='s', cwd='/repo', scope='/repo')
    s._runtime_error = 'thread already has an active writer'
    backend = SimpleNamespace(send=AsyncMock(), has_owned_processes=True)
    s._backend = backend
    with pytest.raises(RuntimeError, match='reconnect this CLI'):
        await s._ensure_backend()
    assert s._backend is backend
    backend.send.assert_not_awaited()
