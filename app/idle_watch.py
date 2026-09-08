"""Recurring, activity-keyed quiescence notifications for an orchestrator's own tree."""
import hashlib
import json
import uuid

from app import db
from app.events import MessageProvenance


def snapshot(target_id: str, manager) -> dict | None:
    with db._conn() as connection:
        connection.execute('BEGIN')
        target = connection.execute('SELECT * FROM sessions WHERE id=?', (target_id,)).fetchone()
        if target is None or target['status'] == 'archived':
            return None
        target = dict(target)
        rows = [dict(row) for row in connection.execute('SELECT * FROM sessions WHERE scope=? ORDER BY id', (target['scope'],))]
        members = {target_id}
        names = {target['name']}
        while True:
            added = [row for row in rows if row['id'] not in members and (
                row.get('parent_id') in members or (not row.get('parent_id') and row.get('parent_name') in names))]
            if not added:
                break
            members.update(row['id'] for row in added)
            names.update(row['name'] for row in added)
        tree = [row for row in rows if row['id'] in members and row['status'] != 'archived']
        for row in tree:
            live = manager.sessions.get(row['id']) if manager is not None else None
            if live is not None:
                if getattr(live, '_compacting', False) or (row['id'] == target_id and getattr(live, '_pending_messages', [])):
                    return None
                row['status'] = getattr(live.status, 'value', live.status)
                if getattr(live, '_adopted_recovery_pending', False):
                    row['status'] = 'recovering'
                pending_report = getattr(live, '_auto_report_task', None)
                if pending_report is not None and not pending_report.done():
                    return None
        root = next((row for row in tree if row['id'] == target_id), None)
        if root is None or root['status'] != 'idle':
            return None
        if any(row['status'] in {'running','starting','interrupted','recovering'} for row in tree):
            return None
        ids = sorted(row['id'] for row in tree)
        marks = ','.join('?' for _ in ids)
        jobs = [dict(row) for row in connection.execute(
            f"SELECT id,status FROM bg_jobs WHERE target_session_id IN ({marks}) AND type!='idle' ORDER BY id", ids)]
        if any(job['status'] in {'active','triggering'} for job in jobs):
            return None
        activity = []
        for row in tree:
            if row['id'] == target_id:
                last = connection.execute(
                    "SELECT COALESCE(MAX(id),0) FROM logs WHERE session_id=? AND type='user_message' "
                    "AND NOT (origin='background_task' AND COALESCE(CASE WHEN json_valid(origin_detail) "
                    "THEN json_extract(origin_detail,'$.subtype') END,'')='idle_watch')", (target_id,)).fetchone()[0]
            else:
                last = connection.execute(
                    "SELECT COALESCE(MAX(id),0) FROM logs WHERE session_id=? "
                    "AND type IN ('user_message','text','tool','tool_result')", (row['id'],)).fetchone()[0]
            activity.append((row['id'], row.get('task_id'), row.get('branch'), row['status'], last))
        digest = hashlib.sha256(json.dumps([sorted(activity),jobs],sort_keys=True).encode()).hexdigest()
        return {'target': target, 'signature': digest,
                'workers': [(row['name'],row['status']) for row in tree if row['id'] != target_id]}


async def check(job_id: str, manager) -> bool:
    from app.message_deliveries import accept_message_delivery
    job = db.bg_get_job(job_id)
    if not job or job['status'] != 'active':
        return False
    config = json.loads(job['config'])
    state = snapshot(job['target_session_id'], manager)
    if state is None or state['signature'] == config.get('last_idle_signature'):
        return False
    target = state['target']
    delivery_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"orchestra:idle:{job_id}:{state['signature']}"))
    generation = (f"session={target['id']}|task={target.get('task_id') or ''}|"
                  f"branch={target.get('branch') or ''}|needs_switch={int(bool(target.get('needs_switch')))}")
    body = ('[Idle watch] Your worker tree has no running workers or other active background jobs. '
            'This is a request to check results, not proof that work succeeded or stalled. '
            'Check missing/failed report deliveries before concluding.\n'
            + job['message'] + '\nWorker states: ' + json.dumps(state['workers'],ensure_ascii=False))
    result, status = await accept_message_delivery(
        delivery_id=delivery_id, source_principal='idle-watch', source_name=job_id,
        source_scope=target['scope'], target_session_id=target['id'], target_name=target['name'],
        target_scope=target['scope'], target_task_id=target.get('task_id') or '', target_generation=generation,
        message=body, rendered_message=body, message_kind='idle_watch',
        provenance=MessageProvenance(origin='background_task',senders=(job_id,),subtype='idle_watch',ref=job_id))
    if status != 202:
        raise RuntimeError(f"idle notification was not accepted: {result}")
    with db._conn() as connection:
        connection.execute("UPDATE bg_jobs SET config=json_set(config,'$.last_idle_signature',?) "
                           "WHERE id=? AND status='active'", (state['signature'],job_id))
    return True
