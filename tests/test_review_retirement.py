from pathlib import Path
import json
import sqlite3


def test_retired_review_tool_and_routes_are_absent():
    from app.mcp_stdio import mcp
    from app.routes.merge_operations import router
    assert 'record_review_outcome' not in {tool.name for tool in mcp._tool_manager.list_tools()}
    assert not any(route.path.endswith(('/review-skip','/review-subject')) for route in router.routes)


def test_old_review_data_survives_upgrade_without_remaining_in_new_schema(tmp_path, monkeypatch):
    from app import db
    path=tmp_path/'old.sqlite'
    monkeypatch.setattr(db,'DB_PATH',path)
    db.init_db()
    with sqlite3.connect(path) as connection:
        for field in ('author_outcome','outcome_source','outcome_evidence_ref'):
            connection.execute(f"ALTER TABLE review_receipts ADD COLUMN {field} TEXT DEFAULT ''")
        connection.execute("INSERT INTO review_receipts(receipt_id,runtime,reviewer_model,model_source,session_id,worker_name,scope,task_id,task_source,artifact_path,mode,job_id,usage_event_id,requested_at,status,author_outcome,outcome_source,outcome_evidence_ref) VALUES ('old','codex','model','direct','s','worker','/scope','1','session_lookup','','skip','','','2026-09-08','completed','disputed','direct','historical evidence')")
    monkeypatch.setattr(db,'DB_PATH',path)
    db.init_db()
    with db._conn() as connection:
        old=connection.execute("SELECT author_outcome,outcome_evidence_ref FROM review_receipts WHERE receipt_id='old'").fetchone()
    assert tuple(old)==('disputed','historical evidence')
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'fresh.sqlite')
    db.init_db()
    with db._conn() as connection:
        fields={row[1] for row in connection.execute('PRAGMA table_info(review_receipts)')}
    assert not fields & {'author_outcome','coverage_outcome','production_snapshot_sha256'}


def test_private_markdown_export_does_not_modify_source_db(tmp_path, monkeypatch):
    from app import db
    from scripts.archive_review_history import archive
    path=tmp_path/'db.sqlite'
    monkeypatch.setattr(db,'DB_PATH',path)
    db.init_db()
    db.task_run_receipt_open(session_id='s',worker_name='w',scope='/scope',task_id='1')
    before=path.read_bytes()
    target,count=archive(path)
    assert target.parent==path.parent/'archive'
    assert count==1
    text=target.read_text()
    records=json.loads(text.split('```json\n')[1].split('\n```')[0])
    assert records[0]['task_id']=='1'
    assert path.read_bytes()==before
