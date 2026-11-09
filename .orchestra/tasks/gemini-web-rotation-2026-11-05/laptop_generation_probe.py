"""Single minimal-generation A/B probe; cookies stay in laptop RAM."""
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[3]
TASK=Path(__file__).resolve().parent
program=r'''
import json,sys,asyncio
p=json.load(sys.stdin)
reader={'__name__':'cookie_source'};exec(p['source'],reader)
cookies=reader['load_session_in_memory']()
w={'__name__':'worker'};exec(p['worker'],w)
async def run():
 try:
  r=await w['generate']({'auth':{'cookies':cookies,'expected_email':p['email'],'authuser_index':0},'model':'gemini-flash','prompt':'Ответь только числом: сколько будет 17 + 25?'})
  print(json.dumps({'laptop_minimal_correct':r['text'].strip()=='42','text_chars':len(r['text']),'answer':r['text'][:150]}))
 except Exception as e: print(json.dumps(w['safe_error'](e)))
asyncio.run(run())
'''
# Read only the authorized email, never copy any auth values into the task file.
get_email="cd /home/kesha/orchestra && .venv/bin/python -c 'from app.gemini_web_auth import read_accounts; print(read_accounts()[0][\"expected_email\"])'"
email=subprocess.run(['ssh','orchestra-vps',get_email],capture_output=True,text=True,check=True).stdout.strip()
payload={'source':(ROOT/'scripts/gemini_web_opera_cookies.py').read_text(),'worker':(ROOT/'app/harness/gemini_web_worker.py').read_text(),'email':email}
r=subprocess.run(['on-remote','--pc-home','.local/share/orchestra-gemini-web-pilot/.venv/bin/python','-c',program],input=json.dumps(payload).encode(),capture_output=True,timeout=220)
try: result=json.loads(r.stdout)
except Exception: result={'failed':True,'phase':'laptop-generation'}
(TASK/'laptop-generation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
