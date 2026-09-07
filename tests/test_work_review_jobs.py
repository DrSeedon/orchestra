from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import runpy
import uuid

import pytest
from starlette.requests import Request

pytestmark=pytest.mark.asyncio


@pytest.fixture
def job_env(tmp_path,monkeypatch):
    import app.db as db
    from app.routes import bg
    from app.bg_jobs import bg_manager
    from app.mcp_proof import issue_mcp_proof
    db.init_db()
    helpers=runpy.run_path(str(Path(__file__).with_name('test_review_coverage_gate_462.py')))
    helpers['_save_session'](db,session_id='sid',name='worker',scope='/scope',worktree=str(tmp_path),role='worker',is_orchestrator=False)
    task=db.get_session('sid')['task_id']
    db.task_run_receipt_open(session_id='sid',worker_name='worker',scope='/scope',task_id=task,task_stable_id='stable-job')
    monkeypatch.setattr(bg.manager,'get_by_name',lambda *_:SimpleNamespace(id='sid'))
    started=[]
    monkeypatch.setattr(bg_manager,'_start_task',lambda *args:started.append(args))
    def receipt():
        return dict(receipt_id=str(uuid.uuid4()),runtime='codex',reviewer_model='gpt-5.6-luna',model_source='direct',
            session_id='sid',worker_name='worker',scope='/scope',task_id=task,task_source='session_lookup',
            mode='implementation',subject_kind='implementation',artifact_path=str(tmp_path/'review.md'),job_id='',usage_event_id='')
    request=Request({'type':'http','headers':[(b'x-orchestra-session-id',b'sid'),(b'x-orchestra-mcp-proof',issue_mcp_proof('sid').encode())]})
    return db,bg,receipt,request,started


def args(bg,receipt):
    return bg.BgJobCreateRequest(type='run',config={'command':'true','success_file':receipt['artifact_path']},
        target_name='worker',target_scope='/scope',created_by='worker',receipt_id=receipt['receipt_id'])


async def test_one_receipt_starts_one_job_even_on_parallel_http_replay(job_env):
    db,bg,factory,request,started=job_env
    receipt=db.review_receipt_reserve(factory())
    first,second=await asyncio.gather(bg.bg_job_create(args(bg,receipt),request),bg.bg_job_create(args(bg,receipt),request))
    assert first['id']==second['id']
    assert len(started)==1
    assert started[0][2]['review_advisory'] is True
    assert db.review_receipt_get(receipt['receipt_id'])['job_id']==first['id']


async def test_old_mcp_cannot_start_unbudgeted_review_for_new_task(job_env):
    db,bg,factory,request,started=job_env
    old={**factory(), 'status':'requested'}
    db.review_receipt_create(old)
    response=await bg.bg_job_create(args(bg,old),request)
    assert response.status_code==409
    assert not started


async def test_review_job_rejects_missing_proof_and_changed_replay(job_env):
    db,bg,factory,request,started=job_env
    receipt=db.review_receipt_reserve(factory())
    response=await bg.bg_job_create(args(bg,receipt),Request({'type':'http','headers':[]}))
    assert response.status_code==403 and not started
    await bg.bg_job_create(args(bg,receipt),request)
    changed=args(bg,receipt)
    changed.config['command']='false'
    response=await bg.bg_job_create(changed,request)
    assert response.status_code==409
    assert len(started)==1


async def test_mcp_refuses_old_server_that_would_ignore_expected_head(monkeypatch):
    import app.mcp_stdio as mcp
    api=AsyncMock(return_value={'merge_schema_version':2,'capabilities':['operation-v1','task-lifecycle-v2']})
    monkeypatch.setattr(mcp,'_api',api)
    result=await mcp.merge_worker('worker',expected_head='a'*40,acceptance_note='Inspected')
    assert result.isError
    assert api.await_count==1


async def test_ended_assignment_cannot_be_merged_using_its_old_acceptance(monkeypatch,tmp_path):
    # Snapshot identity includes the task-run, not just a reused display task number.
    import app.db as db
    import app.merge_operations as ops
    db.init_db()
    run=db.task_run_receipt_open(session_id='sid',worker_name='worker',scope='/scope',task_id='1')
    current=dict(name='worker',scope='/scope',worker_branch='task',worker_head='a'*40,base_branch='main',task_id='1',needs_switch=False)
    record=dict(session_id='sid',worker_name='worker',scope='/scope',accepted_worker_branch='task',accepted_worker_head='a'*40,
                accepted_base_branch='main',accepted_task_id='1',accepted_needs_switch=False,
                accepted_admission={'acceptance_decision':{'task_run_id':run['receipt_id']}})
    monkeypatch.setattr(ops,'_session_snapshot',lambda *_:current)
    assert ops._verify_accepted_snapshot(record)[1]==''
    db.task_run_receipt_finish(session_id='sid',task_id='1',status='completed',prompt_template_end='')
    assert 'task_run' in ops._verify_accepted_snapshot(record)[1]


async def test_parent_acceptance_is_limited_to_its_child_and_own_branch(job_env):
    from app.mcp_proof import work_acceptor_principal, issue_mcp_proof
    db,_bg,_factory,_request,_started=job_env
    parent={**db.get_session('sid'),'id':'parent','name':'parent','role':'full-cycle','branch':'parent-work'}
    db.save_session(parent)
    child={**db.get_session('sid'),'parent_id':'parent'}
    request=Request({'type':'http','headers':[(b'x-orchestra-session-id',b'parent'),(b'x-orchestra-mcp-proof',issue_mcp_proof('parent').encode())]})
    assert work_acceptor_principal(request,child,'parent-work')=='parent'
    assert work_acceptor_principal(request,child,'main')==''
    assert work_acceptor_principal(request,{**child,'parent_id':'someone-else'},'parent-work')==''
    assert work_acceptor_principal(request,parent,'parent-work')==''


async def test_receipt_cannot_start_a_new_job_after_assignment_closed(job_env):
    db,bg,factory,request,started=job_env
    receipt=db.review_receipt_reserve(factory())
    db.task_run_receipt_finish(session_id='sid',task_id=receipt['task_id'],status='completed',prompt_template_end='')
    with db._conn() as c:
        c.execute("UPDATE sessions SET task_id='' WHERE id='sid'")
    response=await bg.bg_job_create(args(bg,receipt),request)
    assert response.status_code==409
    assert not started
