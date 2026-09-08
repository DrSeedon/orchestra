from pathlib import Path
import runpy
import uuid
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

pytestmark = pytest.mark.asyncio


@pytest.fixture
def work(tmp_path,monkeypatch):
    import app.db as db
    import app.merge_operations as operations
    import app.acceptance as acceptance
    db.init_db()
    helpers=runpy.run_path(str(Path(__file__).with_name('_work_review_helpers.py')))
    repo,_base=helpers['_repo'](tmp_path)
    for sid,name,role,orch in [('sid','worker','worker',False),('parent','parent','orchestrator',True)]:
        helpers['_save_session'](db,session_id=sid,name=name,scope=str(repo),worktree=str(repo),role=role,is_orchestrator=orch)
    task=db.get_session('sid')['task_id']
    run=db.task_run_receipt_open(session_id='sid',worker_name='worker',scope=str(repo),task_id=task,task_stable_id='stable-work')
    snapshot=lambda sid:{'session_id':sid,'name':'worker','scope':str(repo),'worktree_path':str(repo),
                         'worker_branch':'task-462/worker','worker_head':helpers['_git'](repo,'rev-parse','HEAD'),
                         'base_branch':'main','task_id':task,'needs_switch':False}
    monkeypatch.setattr(operations,'_session_snapshot',snapshot)
    monkeypatch.setattr(operations,'ensure_operation_runner',lambda *_:None)
    monkeypatch.setattr(acceptance,'task_oracle_for_session',lambda *_:{})
    return db,operations,repo,snapshot,run


async def submit(work,**extra):
    _db,operations,repo,snapshot,_run=work
    args=dict(operation_id=str(uuid.uuid4()),name='worker',scope=str(repo),
              expected_head=snapshot('sid')['worker_head'],acceptance_note='Inspected the diff; deterministic checks cover this task. No model review requested.',accepting_actor='parent')
    args.update(extra)
    return await operations.accept_merge_operation(**args)


async def test_no_review_needs_only_one_acceptance_decision(work):
    result,status=await submit(work)
    assert status==202
    assert result['operation_state']=='PENDING'
    assert result['admission']['review']['review_state']=='not_requested'
    assert result['admission']['acceptance_decision']['actor']=='parent'
    assert 'review_coverage' not in result['admission']
    db=work[0]
    with db._conn() as c:
        assert c.execute("SELECT count(*) FROM review_receipts WHERE mode='skip'").fetchone()[0]==0


@pytest.mark.parametrize('extra,code',[
    ({'accepting_actor':''},'MERGE_ACCEPTOR_REQUIRED'),
    ({'expected_head':''},'WORK_ACCEPTANCE_REQUIRED'),
    ({'acceptance_note':''},'WORK_ACCEPTANCE_REQUIRED'),
    ({'expected_head':'f'*40},'WORK_HEAD_CHANGED'),
])
async def test_acceptance_refuses_missing_authority_or_changed_subject(work,extra,code):
    result,status=await submit(work,**extra)
    assert status in [403,409]
    assert result['error']['code']==code
    with work[0]._conn() as c:
        assert c.execute('SELECT count(*) FROM merge_operations').fetchone()[0]==0


async def test_caller_cannot_forge_acceptance_actor_in_http_body(work,monkeypatch):
    from app.routes.merge_operations import create_merge_operation
    from app.mcp_proof import issue_mcp_proof
    import app.auth as auth
    monkeypatch.setattr(auth,'validate_session',lambda *_:False)
    _db,_ops,repo,snapshot,_run=work
    req=dict(operation_id=str(uuid.uuid4()),name='worker',scope=str(repo),expected_head=snapshot('sid')['worker_head'],acceptance_note='Ready',accepting_actor='owner')
    request=Request({'type':'http','headers':[(b'x-orchestra-session-id',b'sid'),(b'x-orchestra-mcp-proof',issue_mcp_proof('sid').encode())]})
    response=await create_merge_operation(req,request)
    assert response.status_code==403
    parent=Request({'type':'http','headers':[(b'x-orchestra-session-id',b'parent'),(b'x-orchestra-mcp-proof',issue_mcp_proof('parent').encode())]})
    response=await create_merge_operation(req,parent)
    assert response.status_code==202


async def test_negative_review_and_subsequent_fix_are_visible_not_a_signature_gate(work):
    from app.work_review import summarize_review
    import subprocess
    db,_ops,repo,snapshot,_run=work
    previous=snapshot('sid')['worker_head']
    receipt=db.review_receipt_reserve(dict(receipt_id=str(uuid.uuid4()),runtime='codex',reviewer_model='gpt-5.6-luna',
        model_source='direct',session_id='sid',worker_name='worker',scope=str(repo),task_id=_run['task_id'],task_source='session_lookup',
        artifact_path=str(repo/'review.md'),mode='implementation',subject_kind='implementation',worker_head=previous,job_id='',usage_event_id=''))
    db.review_receipt_finish(receipt['receipt_id'],{'status':'completed','completed_at':'2026-09-08T00:00:00+00:00','verdict_value':'Incorrect','return_code':0})
    (repo/'app/widget.py').write_text('VALUE = 2\n')
    subprocess.run(['git','add','app/widget.py'],cwd=repo,check=True)
    subprocess.run(['git','commit','-qm','Fix after review'],cwd=repo,check=True)
    result,status=await submit(work)
    assert status==202
    evidence=result['admission']['review']
    assert evidence['reviewed_head']==previous
    assert evidence['changed_after_review']==['app/widget.py']
    assert evidence['worker_head']==snapshot('sid')['worker_head']
    assert not list(repo.rglob('review-attestation.json'))


async def test_legacy_task_uses_same_advisory_acceptance(work):
    db,_ops,_repo,_snapshot,run=work
    with db._conn() as c:
        c.execute('UPDATE review_receipts SET schema_version=2 WHERE receipt_id=?',(run['receipt_id'],))
    result,status=await submit(work)
    assert status==202
    assert result['admission']['review']['required'] is False


async def test_changed_head_after_acceptance_is_still_rejected(work,monkeypatch):
    _db,ops,_repo,snapshot,_run=work
    result,status=await submit(work)
    assert status==202
    record=ops.get_operation_record(result['operation_id'])
    monkeypatch.setattr(ops,'_session_snapshot',lambda sid:{**snapshot(sid),'worker_head':'f'*40})
    _current,error=ops._verify_accepted_snapshot(record)
    assert 'worker_head' in error


async def test_identical_acceptance_replays_same_operation_and_changed_note_does_not(work):
    operation=str(uuid.uuid4())
    first,_=await submit(work,operation_id=operation)
    again,status=await submit(work,operation_id=operation)
    assert status==202 and first['operation_id']==again['operation_id']
    conflict,status=await submit(work,operation_id=operation,acceptance_note='Another decision')
    assert status==409
    assert conflict['error']['code']=='IDEMPOTENCY_CONFLICT'


async def test_failed_acceptance_still_blocks_new_work_without_review(work,monkeypatch):
    import app.acceptance as acceptance
    from app.routes import sessions
    _db,ops,_repo,_snapshot,_run=work
    monkeypatch.setattr(acceptance,'task_oracle_for_session',lambda *_:{'command':'python -c "raise SystemExit(1)"'})
    executor=AsyncMock(side_effect=AssertionError('merge must not execute'))
    monkeypatch.setattr(sessions,'execute_merge_session',executor)
    result,status=await submit(work)
    assert status==202
    await ops._run_operation(result['operation_id'])
    final=ops.get_operation_result(result['operation_id'])
    assert final['operation_state']=='FAILED'
    assert final['acceptance']['status']=='failed'
    executor.assert_not_awaited()


async def test_new_mcp_review_does_not_require_verdict_heading_or_coverage_hash(work,monkeypatch):
    import app.mcp_stdio as mcp
    db,_ops,repo,_snapshot,run=work
    captured={}
    async def api(method,path,**kwargs):
        if method=='GET':
            return {'id':'sid','role':'worker','work_review_version':3,'task_id':run['task_id'],
                    'worktree_path':str(repo),'base_branch':'main'}
        captured.update(kwargs['json'])
        return {'id':'fake-review-job'}
    monkeypatch.setattr(mcp,'_api',api)
    monkeypatch.setattr(mcp,'WORKER_NAME','worker')
    monkeypatch.setattr(mcp,'SCOPE',str(repo))
    monkeypatch.setattr(mcp,'_quota_refusal',AsyncMock(return_value=None))
    monkeypatch.setattr(mcp,'_codex_bin',lambda:'/usr/bin/true')
    monkeypatch.setattr(mcp,'_load_review_project_context',lambda *a,**k:('test context',{'status':'loaded','warning':''}))
    await mcp.codex_review(context='Review the task result',mode='implementation',output='review.md')
    assert '--require-verdict' not in captured['config']['command']
    assert captured['config']['success_pattern']==''
    receipt=db.review_receipt_get(captured['receipt_id'])
    assert receipt['schema_version']==3
    assert 'production_snapshot_sha256' not in receipt


async def test_new_size_skip_creates_no_receipt(work,monkeypatch):
    import app.mcp_stdio as mcp
    db,_ops,repo,_snapshot,run=work
    api=AsyncMock(return_value={'id':'sid','role':'worker','work_review_version':3,'task_id':run['task_id'],
                                'worktree_path':str(repo),'base_branch':'main'})
    monkeypatch.setattr(mcp,'_api',api)
    monkeypatch.setattr(mcp,'WORKER_NAME','worker')
    monkeypatch.setattr(mcp,'SCOPE',str(repo))
    result=await mcp.codex_review(context='Small work with deterministic checks',mode='implementation',required=False)
    assert result.structuredContent['result']['receipt_id']==''
    assert api.await_count==1
    with db._conn() as c:
        assert c.execute("SELECT count(*) FROM review_receipts WHERE subject_kind!='task_run'").fetchone()[0]==0


@pytest.mark.parametrize('explicit_acceptance',[False,True])
async def test_commit_during_idle_wait_cannot_replace_explicitly_accepted_head(tmp_path,monkeypatch,explicit_acceptance):
    from tests.test_task_tracker_integration import _commit_file,_init_db,_make_git_scope,_prepare_merge,_save_worker
    import app.routes.sessions as route
    import app.workspace as workspace
    from app import tm
    import subprocess
    _init_db()
    repo=_make_git_scope(monkeypatch,tmp_path)
    scope=str(repo)
    with tm._conn() as c:
        tm.ensure_project(c,'project',scope=scope)
        task=tm.create_task(c,'project','Pinned work',par_number=42,status='in_progress')
        c.execute('UPDATE tm_tasks SET worker_session_id=? WHERE id=?',('pinned-worker',task['id']))
    tree=workspace.create_worktree(scope,'pinned-worker',task_id='42')
    head=_commit_file(tree.path,'work.py','#42: result shown to parent')
    before=subprocess.check_output(['git','rev-parse','main'],cwd=repo,text=True).strip()
    _save_worker(session_id='pinned-worker',task_id='42',scope=scope,worktree_path=tree.path,branch=tree.branch)
    classify_head_drift = workspace.classify_head_drift
    worker=_prepare_merge(monkeypatch,session_id='pinned-worker',scope=scope)
    monkeypatch.setattr(workspace, 'classify_head_drift', classify_head_drift)
    async def advance(_worker):
        _commit_file(tree.path,'late.py','#42: change after acceptance')
        return True
    monkeypatch.setattr(route,'_wait_for_merge_idle',advance)
    req={'scope':scope,'task_outcome':'continue','merge_schema_version':2}
    if explicit_acceptance:
        req['expected_head']=head
    result=await route.execute_merge_session(session_id=worker.id,expected_name=worker.name,
        expected_scope=scope,expected_branch=worker.branch,expected_head=head,req=req)
    if explicit_acceptance:
        assert result['ok'] is False
        assert result['commit_point']=='not_reached'
        assert subprocess.check_output(['git','rev-parse','main'],cwd=repo,text=True).strip()==before
    else:
        assert result['ok'] is True,str(result)


@pytest.mark.parametrize('value,success',[(42,True),(41,False)])
async def test_complete_new_work_path_runs_checks_then_merges_only_passing_result(tmp_path,monkeypatch,value,success):
    from tests.test_task_tracker_integration import _init_db,_make_git_scope,_prepare_merge,_save_worker
    import app.db as db
    import app.merge_operations as ops
    import app.workspace as workspace
    from app import tm
    import subprocess
    import sys
    _init_db()
    repo=_make_git_scope(monkeypatch,tmp_path)
    scope=str(repo)
    command=f'{sys.executable} -B -c "import work; assert work.VALUE == 42"'
    with tm._conn() as c:
        tm.ensure_project(c,'project',scope=scope)
        task=tm.create_task(c,'project','Return 42',par_number=42,status='in_progress',acceptance_command=command)
        c.execute('UPDATE tm_tasks SET worker_session_id=? WHERE id=?',('new-work',task['id']))
    tree=workspace.create_worktree(scope,'new-work',task_id='42')
    Path(tree.path,'work.py').write_text(f'VALUE = {value}\n')
    subprocess.run(['git','add','work.py'],cwd=tree.path,check=True)
    subprocess.run(['git','commit','-qm','#42: deliver work'],cwd=tree.path,check=True)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree.path,text=True).strip()
    _save_worker(session_id='new-work',task_id='42',scope=scope,worktree_path=tree.path,branch=tree.branch)
    _prepare_merge(monkeypatch,session_id='new-work',scope=scope)
    db.task_run_receipt_open(session_id='new-work',worker_name='new-work',scope=scope,task_id='42',task_stable_id='new-work-stable')
    monkeypatch.setattr(ops,'ensure_operation_runner',lambda *_:None)
    result,status=await ops.accept_merge_operation(operation_id=str(uuid.uuid4()),name='new-work',scope=scope,
        expected_head=head,acceptance_note='Acceptance command covers the result; no model review needed.',accepting_actor='owner',
        task_outcome='complete',merge_schema_version=2)
    assert status==202,result
    await ops._run_operation(result['operation_id'])
    final=ops.get_operation_result(result['operation_id'])
    assert final['operation_state']==('SUCCEEDED' if success else 'FAILED'),final
    exists=subprocess.run(['git','show','main:work.py'],cwd=repo,capture_output=True,text=True)
    assert (exists.returncode==0)==success
    with db._conn() as c:
        assert c.execute("SELECT count(*) FROM review_receipts WHERE mode IN ('skip','implementation')").fetchone()[0]==0
    assert not list(Path(tree.path).rglob('review-attestation.json'))


async def test_retired_review_metadata_cannot_block_an_already_accepted_operation(work,monkeypatch):
    import json
    from app.routes import sessions
    db,ops,_repo,_snapshot,_run=work
    result,status=await submit(work)
    assert status==202
    operation_id=result['operation_id']
    record=ops.get_operation_record(operation_id)
    admission=record['accepted_admission']
    admission.pop('acceptance_decision')
    admission.pop('review',None)
    admission['review_coverage']={'status':'blocked','reason':'review_missing'}
    with db._conn() as c:
        c.execute('UPDATE merge_operations SET accepted_admission_json=? WHERE operation_id=?',
                  (json.dumps(admission),operation_id))
    executor=AsyncMock(side_effect=RuntimeError('executor reached; stop before Git'))
    monkeypatch.setattr(sessions,'execute_merge_session',executor)
    await ops._run_operation(operation_id)
    executor.assert_awaited_once()
