"""Authorized live API checks. Session/CSRF cookies remain in RAM, no raw provider diagnostics."""
import collections
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path('/home/kesha/orchestra')
TASK = ROOT / '.orchestra/tasks/gemini-web-rotation-2026-11-05'
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
from app.auth import create_session, create_csrf_token
user = os.environ.get('DASHBOARD_USER', '')
HEADERS = {'Cookie': 'session=' + create_session(user), 'X-CSRF-Token': create_csrf_token(user), 'Content-Type': 'application/json'}
SCOPE = '/home/kesha/orchestra'
NAME = 'gemini-web-check-1793881789'

def api(path, data=None):
    request = urllib.request.Request('http://127.0.0.1:8888' + path, headers=HEADERS,
        data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(request, timeout=30) as r:
        return json.load(r)

def snapshot():
    sessions = api('/api/sessions')
    def pid(unit):
        return int(subprocess.check_output(['systemctl', 'show', unit, '-p', 'MainPID', '--value']).strip())
    return {'orchestra_pid': pid('orchestra.service'), 'telegram_bot_api_pid': pid('telegram-bot-api.service'),
            'cut_names': [s['name'] for s in sessions if s['status'] in ('running', 'thinking')],
            'interrupted_names': [s['name'] for s in sessions if s['status'] == 'interrupted']}

def check(prompt, expected, require_tool=False):
    path = '/api/sessions/' + NAME + '?' + urllib.parse.urlencode({'scope':SCOPE})
    current = api(path)
    if current['status'] != 'idle' or current['model'] != 'gemini-web/gemini-flash':
        return {'success':False,'reason':'target_not_idle_flash','status':current['status']}
    with sqlite3.connect('file:' + str(ROOT/'data/orchestra.db') + '?mode=ro', uri=True) as db:
        after = db.execute('SELECT COALESCE(MAX(id),0) FROM logs').fetchone()[0]
    accepted = api('/api/sessions/' + NAME + '/send', {'scope':SCOPE,'message':prompt})
    deadline = time.monotonic() + 750
    rows=[]
    while time.monotonic() < deadline:
        time.sleep(2)
        current = api(path)
        with sqlite3.connect('file:' + str(ROOT/'data/orchestra.db') + '?mode=ro', uri=True) as db:
            db.row_factory=sqlite3.Row
            rows=[dict(r) for r in db.execute('SELECT id,type,content,tool_name,tool_is_error FROM logs WHERE session_id=? AND id>? ORDER BY id',(current['id'],after))]
        if current['status'] not in ('running','thinking') and any(r['type'] in ('text','text_delta','assistant','error','turn_end') for r in rows):
            break
    types=dict(collections.Counter(r['type'] for r in rows))
    text=''.join(r['content'] or '' for r in rows if r['type'] in ('text','text_delta','assistant'))
    errors=sum(r['type']=='error' for r in rows)
    tool_rows=[r for r in rows if 'tool' in r['type']]
    tool_executed=any(r.get('tool_name') in ('read', 'read_file') and not r.get('tool_is_error') for r in tool_rows)
    result={'accepted':bool(accepted.get('ok')), 'status':current['status'], 'error_count':errors,
            'types':types,'answer_contains_expected':expected in text, 'tool_executed':tool_executed,
            'provider_account':current.get('provider_account'), 'after_id':after,
            'success':current['status']=='idle' and errors==0 and expected in text and (tool_executed or not require_tool)}
    # Only the public test answer is retained, never provider diagnostics or arbitrary prior content.
    if len(text)<500: result['answer']=text
    return result

def main():
    if '--before' in sys.argv:
        result=snapshot();(TASK/'service-before.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return
    result={'before':snapshot()}
    result['arithmetic']=check('Ответь только числом: сколько будет 17 + 25?', '42')
    (TASK/'live-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['arithmetic'],ensure_ascii=False),flush=True)
    if True:
        # README first line is nonempty and makes verification unambiguous.
        expected=(ROOT/'README.md').read_text().splitlines()[0]
        result['tools']=check('Вызови доступный инструмент read (аналог read_file) с path=/home/kesha/orchestra/README.md, offset=1, limit=3. После получения результата верни первую строку файла. Выполни настоящий вызов инструмента, ничего не меняй.',expected,True)
        print(json.dumps(result['tools'],ensure_ascii=False),flush=True)
    usage=api('/api/usage').get('gemini_web')
    sessions=api('/api/sessions?'+urllib.parse.urlencode({'scope':SCOPE}))
    result['usage']=usage
    result['session_accounts']=[{k:s.get(k) for k in ('name','model','provider_account','status')} for s in sessions if s.get('provider')=='gemini-web']
    result['after']=snapshot()
    result['success']=bool(result['arithmetic']['success'] and result.get('tools',{}).get('success') and usage and usage['total']==3)
    (TASK/'live-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'success':result['success'],'usage':usage,'after':result['after']},ensure_ascii=False))
if __name__=='__main__':main()
