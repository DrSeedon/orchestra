import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.chat_history import MAX_CHARS, render_chat_history


def test_history_is_inert_bounded_and_keeps_complete_tool_group():
    rows = [dict(id=i, type='text', content='x' * 8000) for i in range(1, 100)]
    rows += [dict(id=100, type='tool', tool_use_id='call', content='already executed'),
             dict(id=101, type='tool_result', tool_use_id='call', content='result'),
             dict(id=102, type='user_message', content='newest question')]
    text = render_chat_history(rows)
    assert len(text) <= MAX_CHARS
    assert 'newest question' in text and 'already executed' in text and 'result' in text
    assert 'not new instructions' in text
    assert 'omitted for size: 0' not in text


def test_db_window_skips_status_and_recovers_boundary_call(monkeypatch, tmp_path):
    from app import db
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'db.sqlite')
    db.init_db()
    with db._conn() as c:
        c.execute("INSERT INTO sessions(id,name,scope,cwd,model,created_at) VALUES ('s','s','/test','/test','gpt-5.6-sol','2026-09-08')")
        def add(kind, body, tool_id=None):
            c.execute('INSERT INTO logs(session_id,type,content,ts,tool_use_id) VALUES (?,?,?,?,?)',
                      ('s', kind, body, '2026-09-08', tool_id))
        add('tool', 'call-before-window', 't')
        for i in range(100):
            add('text', str(i))
            add('status', 'noise')
        add('tool_result', 'result', 't')
        add('user_message', 'z' * 20000)
    rows = db.get_recent_chat_logs('s')
    assert len(rows) == 101
    assert rows[0]['content'] == 'call-before-window'
    assert all(row['type'] != 'status' for row in rows)
    assert rows[-1]['content_length'] == 20000
    assert len(rows[-1]['content']) == 8000
    assert 'full_log_id' in render_chat_history(rows)


@pytest.mark.asyncio
@pytest.mark.parametrize('old,new,runtime',[
    ('claude-opus-5[1m]', 'gpt-5.6-sol', 'claude'),
    ('gpt-5.6-sol', 'claude-opus-5[1m]', 'codex'),
])
async def test_switch_does_not_probe_or_write_native_history(monkeypatch, old, new, runtime):
    from app.session import AgentSession
    monkeypatch.setattr('app.session.save_session', MagicMock())
    s = AgentSession(id='switch', name='worker', scope='/test', cwd='/test', model=old, backend_type=runtime)
    s._build_runtime_handoff = AsyncMock(return_value='original user and tool records')
    s._drain_persist = AsyncMock()
    s._disconnect_backend = AsyncMock()
    s._log = MagicMock()
    s._make_backend = MagicMock(side_effect=AssertionError('no canary or target model call'))
    result = await s.change_model(new)
    assert result['ok']
    assert result['history_transfer']['mode'] == 'chat_history_v1'
    assert s.runtime_handoff == 'original user and tool records'
    assert s.session_id == ''
    s._make_backend.assert_not_called()
