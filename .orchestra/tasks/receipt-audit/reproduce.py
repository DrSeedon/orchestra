"""Bounded receipt audit. Temporary SQLite/git only; no provider or live-service calls."""
from pathlib import Path
import asyncio
import hashlib
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).parent


def main():
    import app.db as db
    import app.mcp_stdio as mcp
    from app.codex_review_artifact import finalize_review_artifact
    from app.review_coverage import coverage_decision, production_snapshot

    helpers = runpy.run_path(str(ROOT/'tests/test_review_authorship_493.py'))
    result = {'source_head': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'imported_module':mcp.__file__, 'isolation':'temporary SQLite and git, no model calls'}
    with tempfile.TemporaryDirectory(prefix='receipt-probe-',dir=HERE) as temporary:
        scratch=Path(temporary)
        db.DB_PATH=scratch/'probe.db'
        os.environ['ORCHESTRA_DB_PATH']=str(db.DB_PATH)
        db.init_db()
        repo,base,head=helpers['_repo'](scratch)
        snapshot=production_snapshot(str(repo),target_sha=base,worker_head=head)
        output=scratch/'bare-review.md'
        rid='review-receipt:'+str(uuid.uuid4())
        receipt=helpers['_receipt'](
            receipt_id=rid,scope=str(repo),artifact_path=str(output),
            requested_by_session_id='session-493',requested_by_worker='author-493',
            author_outcome='unknown',outcome_source='unknown',status='requested',completed_at=None,
            coverage_outcome='unknown',**{k:v for k,v in snapshot.items() if k not in ['production_paths','production_path_heads']})
        db.review_receipt_create(receipt)
        text='## Verdict\n\nAPPROVED\n'
        round_file=scratch/'bare.round';round_file.write_text(text)
        jsonl=scratch/'bare.jsonl'
        jsonl.write_text('\n'.join(json.dumps(x) for x in [
            {'type':'thread.started','thread_id':'audit-thread'},
            {'type':'item.completed','item':{'type':'agent_message','text':text}},
            {'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':4}}
        ]))
        finalize_review_artifact(output=output,round_file=round_file,sessions_file=scratch/'sessions.json',
            slug='bare',jsonl_file=jsonl,resume=False,require_verdict=True,receipt_id=rid,
            receipt_round=1,usage_event_id='codex-review:audit',usage_session_id='session-493',
            usage_scope=str(repo),usage_task_id='493',usage_model='gpt-5.6-luna')
        saved=db.review_receipt_get(rid)
        db.review_receipt_set_outcome(rid,'accepted')
        decision=coverage_decision(scope=str(repo),session_id='session-493',task_id='493',
            active=True,worktree=str(repo),**{k:v for k,v in snapshot.items() if k in [
            'target_sha','worker_head','production_paths','production_snapshot_sha256',
            'production_diff_sha256','production_path_heads']})
        result['bare_verdict']={'input':text,'tool_events':0,'artifact_quote':False,
            'execution_failure_guard_matches':bool(re.search(mcp._CODEX_EXECUTION_FAILURE_PATTERN,text,re.I)),
            'coverage_outcome':saved['coverage_outcome'],'verdict_present':saved['verdict_present'],
            'merge_coverage_status':decision['status']}
        assert decision['status']=='satisfied'
        round_file.write_text('APPROVED\n')
        try:
            finalize_review_artifact(output=scratch/'control.md',round_file=round_file,
                sessions_file=scratch/'control-sessions.json',slug='control',jsonl_file=jsonl,
                resume=False,require_verdict=True)
        except ValueError as e:
            result['bare_verdict']['control_without_heading']=str(e)
        else:
            raise AssertionError('missing heading was not rejected')

        rounds=[]
        for i in range(5):
            row=helpers['_receipt'](artifact_path=str(scratch/'same.md'),status='requested',completed_at=None,
                author_outcome='unknown',scope=str(repo))
            saved_round=db.review_receipt_reserve(row)
            rounds.append(saved_round['round'])
        fresh=db.review_receipt_reserve(helpers['_receipt'](artifact_path=str(scratch/'renamed.md'),
            status='requested',completed_at=None,author_outcome='unknown',scope=str(repo)))
        result['round_counter']={'same_subject_allocated_rounds':rounds,'new_output_round':fresh['round'],
                                'all_five_still_requested':True}
        assert rounds==[1,2,3,4,5] and fresh['round']==1

        cross=helpers['_receipt'](artifact_path=str(scratch/'cross-review.md'),scope=str(repo),
            requested_by_session_id='orchestrator',requested_by_worker='orchestrator',
            **{k:v for k,v in snapshot.items() if k not in ['production_paths','production_path_heads']})
        db.review_receipt_create(cross)
        original_api=mcp._api
        refusals={}
        try:
            for caller in ['session-493','orchestrator']:
                async def fake_api(*args,**kwargs):
                    return {'id':caller,'task_id':'493','worktree_path':str(repo),'base_branch':'main'}
                mcp._api=fake_api
                try:
                    asyncio.run(mcp.record_review_outcome(receipt_id=cross['receipt_id'],
                        outcome='attested',closed_findings=['app/widget.py:1']))
                except mcp.ApiToolError as e:
                    refusals[caller]=e.code
                else:
                    raise AssertionError('cross-owner attestation unexpectedly accepted')
        finally:
            mcp._api=original_api
        result['cross_owner_attestation']=refusals

        size=mcp._implementation_review_size_decision(str(repo),base,head,required=False)
        control=mcp._implementation_review_size_decision(str(repo),base,head,required=True)
        result['size_gate']={'paths':snapshot['production_paths'],'required_false':size,'required_true':control['status']}
        assert size['status']=='skip' and control['status']=='review'

        from app.review_coverage import review_findings, production_paths
        standard='### [P1] Validate permission\n**File:** `app/widget.py:1`\n\n## Verdict\nIncorrect\n'
        conventional='blocking: app/widget.py:1 — Validate permission\n\n## Verdict\nIncorrect\n'
        result['finding_format']={'priority_format':review_findings(standard),'conventional':review_findings(conventional)}
        assert result['finding_format']['priority_format']==[]
        assert result['finding_format']['conventional']==['app/widget.py:1']
        result['production_scope']={p:production_paths([p]) for p in [
            'app/auth.py','scripts/check.py','.orchestra/pipelines/default/pipeline.yaml',
            '.orchestra/pipelines/default/prompts/skills/codex-debate.md','pyproject.toml','tests/conftest.py']}

    (HERE/'reproduction-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
