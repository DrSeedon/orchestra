import pytest
from app import db, tm
from app.memory_search import search


def test_source_markdown_is_immediately_searchable_and_scoped(tmp_path):
    db.init_db()
    first, second = tmp_path / 'first', tmp_path / 'second'
    for root in (first, second):
        (root / '.orchestra/kb').mkdir(parents=True)
        (root / '.orchestra/kb/note.md').write_text('Needle '+root.name)
        with db._conn() as connection:
            tm.ensure_project(connection, root.name, scope=str(root))
    assert [r['content'] for r in search(str(first), 'Needle')] == ['Needle first']
    assert len(search(str(first), 'Needle', cross_project=True)) == 2
    (first / '.orchestra/kb/note.md').write_text('Changed needle')
    assert search(str(first), 'Changed')[0]['content'] == 'Changed needle'
    with pytest.raises(ValueError):
        search('/unregistered', 'Needle')
    (first / '.orchestra/kb/secret.md').symlink_to(second / '.orchestra/kb/note.md')
    assert len(search(str(first), 'needle')) == 1


def test_log_search_uses_typed_authors_and_unicode_casefold(tmp_path):
    from datetime import datetime, timezone
    from app.events import MessageProvenance
    from tests.test_task_tracker_integration import _save_worker
    db.init_db()
    with db._conn() as connection:
        tm.ensure_project(connection, 'project', scope=str(tmp_path))
    _save_worker(session_id='memory-worker', task_id='', scope=str(tmp_path), worktree_path=str(tmp_path))
    now = datetime.now(timezone.utc)
    db.add_log('memory-worker', now, 'user_message', 'ЗАДАЧА пользователя',
               provenance=MessageProvenance(origin='user', senders=('user',)))
    db.add_log('memory-worker', now, 'user_message', 'ЗАДАЧА работника',
               provenance=MessageProvenance(origin='agent', senders=('worker',)))
    hits = search(str(tmp_path), 'задача', kinds=['agent_msg'])
    assert len(hits) == 1 and hits[0]['author'] == 'worker'
    assert hits[0]['kind'] == 'agent_msg' and hits[0]['content'] == 'ЗАДАЧА работника'
