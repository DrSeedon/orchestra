"""A disabled tool must never reach its handler; allowed calls must still execute."""
import json

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from app import mcp_stdio as m
from app.manager import SessionManager, _make_mcp_config
from app.pipeline import RoleSpec
from app.tool_scoping import parse_disabled_tools


@pytest.mark.parametrize('role,blocked', [('orchestrator', True), ('sub-orchestrator', True), ('full-cycle', False)])
@pytest.mark.asyncio
async def test_role_dispatch_both_arms(monkeypatch, role, blocked):
    env = _make_mcp_config('probe', '', role)['orchestra']['env']
    monkeypatch.setattr(m, 'DISABLED_TOOLS', json.loads(env['ORCHESTRA_DISABLED_TOOLS']))
    server = m.OrchestraMCP('probe')
    calls = []

    @server.tool(name='run_fan')
    async def sentinel() -> str:
        calls.append(True)
        return 'executed'

    handler = server._mcp_server.request_handlers[CallToolRequest]
    result = (await handler(CallToolRequest(params=CallToolRequestParams(name='run_fan', arguments={})))).root
    assert result.isError == blocked
    assert bool(calls) != blocked
    if blocked:
        assert result.structuredContent['error']['code'] == 'tool_disabled'
    else:
        assert result.structuredContent['result'] == 'executed'


@pytest.mark.asyncio
async def test_worker_policy_and_stable_catalog(monkeypatch):
    server = m.OrchestraMCP('probe')
    calls = []

    @server.tool(name='search_memory')
    async def sentinel() -> str:
        calls.append(True)
        return 'executed'

    before = await server.list_tools()
    monkeypatch.setattr(m, 'DISABLED_TOOLS', ['search_memory'])
    denied = await server.call_tool('search_memory', {})
    assert denied.isError and calls == []
    monkeypatch.setattr(m, 'DISABLED_TOOLS', [])
    assert not (await server.call_tool('search_memory', {})).isError
    assert calls == [True]
    assert await server.list_tools() == before


def test_role_and_worker_union():
    for role in ('orchestrator', 'sub-orchestrator', 'full-cycle', 'worker'):
        env = _make_mcp_config('probe', '', role, disabled_tools=['get_worker_info'])['orchestra']['env']
        denied = json.loads(env['ORCHESTRA_DISABLED_TOOLS'])
        assert 'get_worker_info' in denied
        assert ('run_fan' in denied) == (role in ('orchestrator', 'sub-orchestrator'))


@pytest.mark.parametrize('value', [{}, [''], ['mcp__orchestra__run_fan '], [1], 'not json'])
def test_invalid_policy_fails_closed(value):
    with pytest.raises(ValueError):
        parse_disabled_tools(value)
    with pytest.raises(ValueError):
        RoleSpec(kind='worker', label='test', disabled_tools=value)


def test_persistence_and_old_rows(tmp_path):
    from app import db
    from app.session import AgentSession
    db.init_db()
    session = AgentSession(id='scoped', name='scoped', scope=str(tmp_path), cwd=str(tmp_path),
                           model='gpt-5.6-luna', disabled_tools=['get_worker_info'])
    db.save_session(session._to_db_dict())
    row = db.get_session(session.id)
    restored = SessionManager._hydrate_row(row)
    assert restored.disabled_tools == ['get_worker_info']
    assert restored.to_dict()['disabled_tools'] == ['get_worker_info']
    row.pop('disabled_tools')
    assert SessionManager._hydrate_row(row).disabled_tools == []
    db.init_db()
    assert json.loads(db.get_session(session.id)['disabled_tools']) == ['get_worker_info']


@pytest.mark.asyncio
async def test_spawn_forwards_worker_policy(monkeypatch):
    class Captured(Exception):
        pass

    async def capture(method, path, **kwargs):
        assert method == 'POST' and path == '/api/sessions'
        assert kwargs['json']['disabled_tools'] == ['run_fan']
        raise Captured

    monkeypatch.setattr(m, '_api', capture)
    with pytest.raises(Captured):
        await m.spawn_worker('probe', 'task', '/unused', model='gpt5.6luna', disabled_tools=['run_fan'])


def test_real_stdio_worker_stand():
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / '.orchestra/tasks/532/live_probe.py')], cwd=root,
        env={**os.environ, 'PYTHONPATH': str(root)}, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_database_migrates_worker_policy(tmp_path):
    from app import db
    from app.session import AgentSession
    db.init_db()
    session = AgentSession(id='legacy-scoped', name='legacy-scoped', scope=str(tmp_path),
                           cwd=str(tmp_path), model='gpt-5.6-luna')
    db.save_session(session._to_db_dict())
    with db._conn() as conn:
        conn.execute('ALTER TABLE sessions DROP COLUMN disabled_tools')
    db.init_db()
    assert json.loads(db.get_session(session.id)['disabled_tools']) == []
