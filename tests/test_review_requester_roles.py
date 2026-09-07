from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role,is_orchestrator', [
    ('orchestrator', False), ('sub-orchestrator', False), ('worker', True),
    ('reducer', False), ('', False),
])
@pytest.mark.parametrize('mode', ['review', 'exec', 'implementation'])
@pytest.mark.parametrize('resume', [False, True])
async def test_non_executor_cannot_start_or_resume_review(monkeypatch, role, is_orchestrator, mode, resume):
    import app.mcp_stdio as mcp
    ApiToolError = mcp.ApiToolError

    api = AsyncMock(return_value={'id': 'caller', 'role': role, 'is_orchestrator': is_orchestrator})
    monkeypatch.setattr(mcp, '_api', api)
    monkeypatch.setattr(mcp, 'ROLE', 'worker')  # Local claims cannot override the live session.
    with pytest.raises(ApiToolError, match='worker or full-cycle') as exc:
        await mcp.codex_review(context='Check this task', mode=mode, resume=resume, target='plan.md')
    assert exc.value.code == 'review_requester_forbidden'
    assert api.await_count == 1  # Refused before readiness, receipts, or a background job.


@pytest.mark.parametrize('role', ['worker', 'full-cycle'])
async def test_executor_reaches_review_validation(monkeypatch, role):
    import app.mcp_stdio as mcp
    ApiToolError = mcp.ApiToolError

    api = AsyncMock(return_value={'id': 'caller', 'role': role, 'cwd': '/unused'})
    monkeypatch.setattr(mcp, '_api', api)
    monkeypatch.setattr(mcp, 'ROLE', 'orchestrator')  # Live role wins over stale process metadata.
    with pytest.raises(ApiToolError, match='target file required') as exc:
        await mcp.codex_review(context='Check this task', mode='exec')
    assert exc.value.code == 'invalid_argument'


@pytest.mark.parametrize('role', ['worker', 'full-cycle'])
async def test_executor_cannot_order_another_workers_review(monkeypatch, role):
    import app.mcp_stdio as mcp
    ApiToolError = mcp.ApiToolError

    api = AsyncMock(return_value={'id': 'caller', 'role': role, 'cwd': '/unused'})
    monkeypatch.setattr(mcp, '_api', api)
    with pytest.raises(ApiToolError) as exc:
        await mcp.codex_review(context='Check their work', mode='implementation', target_worker='other')
    assert exc.value.code == 'review_target_forbidden'
    assert api.await_count == 1
