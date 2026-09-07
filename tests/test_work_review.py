from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import json
import uuid

import pytest


@pytest.fixture
def db():
    import app.db as database
    database.init_db()
    return database


def run(db, session='worker', task='1', stable='task-a'):
    return db.task_run_receipt_open(session_id=session, worker_name=session, scope='/scope',
                                    task_id=task, task_stable_id=stable)


def review(session='worker', task='1', output='/report.md'):
    return dict(receipt_id=str(uuid.uuid4()), runtime='codex', reviewer_model='gpt-5.6-luna',
                model_source='direct', session_id=session, worker_name=session, scope='/scope',
                task_id=task, task_source='session_lookup', artifact_path=output,
                mode='implementation', subject_kind='implementation', job_id='', usage_event_id='')


def finish(db, receipt):
    db.review_receipt_finish(receipt['receipt_id'], {'status':'completed',
                           'completed_at':'2026-09-08T00:00:00+00:00', 'return_code':0})


def test_new_assignments_use_advisory_policy_and_legacy_handoff_stays_legacy(db):
    fresh=run(db)
    assert fresh['schema_version']==3
    with db._conn() as c:
        c.execute('UPDATE review_receipts SET schema_version=2 WHERE receipt_id=?',(fresh['receipt_id'],))
    assert run(db)['schema_version']==2
    db.task_run_receipt_finish(session_id='worker',task_id='1',status='interrupted',prompt_template_end='')
    assert run(db,session='replacement')['schema_version']==2
    assert run(db,session='new-task',task='2',stable='task-b')['schema_version']==3


def test_review_budget_survives_output_rename_and_executor_handoff(db):
    from app.work_review import ReviewBudgetError
    run(db)
    for i in range(3):
        receipt=db.review_receipt_reserve(review(output=f'/different-{i}.md'))
        assert receipt['schema_version']==3
        finish(db,receipt)
    db.task_run_receipt_finish(session_id='worker',task_id='1',status='interrupted',prompt_template_end='')
    run(db,session='replacement')
    with pytest.raises(ReviewBudgetError) as error:
        db.review_receipt_reserve(review(session='replacement',output='/new-name.md'))
    assert error.value.code=='review_budget_exhausted'


def test_parallel_requests_allow_only_one_active_review(db):
    from app.work_review import ReviewBudgetError
    run(db)
    barrier=Barrier(2)
    def reserve(i):
        barrier.wait()
        try:
            return db.review_receipt_reserve(review(output=f'/parallel-{i}.md'))['receipt_id']
        except ReviewBudgetError as e:
            return e.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(reserve,[1,2]))
    assert results.count('review_in_progress')==1
    with db._conn() as c:
        assert c.execute("SELECT count(*) FROM review_receipts WHERE subject_kind='implementation'").fetchone()[0]==1


def test_advisory_summary_needs_neither_outcome_nor_attestation(db,tmp_path):
    from app.work_review import summarize_review
    run(db)
    receipt=db.review_receipt_reserve(review())
    finish(db,receipt)
    result=summarize_review(scope='/scope',session_id='worker',task_id='1',
                            worktree=str(tmp_path),worker_head='a'*40)
    assert result['status']=='advisory'
    assert result['required'] is False
    assert result['reviews'][0]['status']=='completed'
    assert result['reviews'][0]['artifact_available'] is False
    assert 'author_outcome' not in result
    assert not list(tmp_path.rglob('review-attestation.json'))


def test_unreviewed_work_has_explicit_advisory_state(db,tmp_path):
    from app.work_review import summarize_review
    run(db)
    summary=summarize_review(scope='/scope',session_id='worker',task_id='1',
                             worktree=str(tmp_path),worker_head='a'*40)
    assert summary['status']=='advisory'
    assert summary['reviews']==[]
    assert summary['review_state']=='not_requested'


def test_legacy_outcome_tool_rejects_new_task_receipts(db,monkeypatch):
    import app.mcp_stdio as mcp
    run(db)
    receipt=db.review_receipt_reserve(review())
    from unittest.mock import AsyncMock
    monkeypatch.setattr(mcp,'_api',AsyncMock(return_value={'id':'worker'}))
    import asyncio
    with pytest.raises(mcp.ApiToolError) as error:
        asyncio.run(mcp.record_review_outcome(receipt['receipt_id'],'accepted'))
    assert error.value.code=='review_outcome_retired'


def test_closed_assignment_cannot_reserve_more_reviews(db):
    from app.work_review import ReviewBudgetError
    run(db)
    db.task_run_receipt_finish(session_id='worker',task_id='1',status='completed',prompt_template_end='')
    with pytest.raises(ReviewBudgetError) as error:
        db.review_receipt_reserve(review())
    assert error.value.code=='review_task_not_active'


def test_startup_adoption_keeps_preexisting_inflight_work_on_legacy_policy(db):
    adopted=db.task_run_receipt_open(session_id='old-worker',worker_name='old-worker',scope='/scope',task_id='7',task_source='legacy_inflight')
    assert adopted['schema_version']==2
