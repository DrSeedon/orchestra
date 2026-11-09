"""Explicit authorized Opera import/probe; credentials only in captured pipes and RAM."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
TASK = Path(__file__).resolve().parent
NAMES = ('__Secure-1PSID','__Secure-1PSIDTS','SID','HSID','SSID','APISID','SAPISID',
         '__Secure-1PAPISID','__Secure-3PAPISID','__Secure-3PSID','__Secure-3PSIDTS',
         'SIDCC','__Secure-1PSIDCC','__Secure-3PSIDCC','LSID','__Host-1PLSID','__Host-3PLSID')
VPS = r'''
import asyncio,json,re,sys
from curl_cffi.requests import AsyncSession
from gemini_webapi.constants import Headers
from loguru import logger
logger.remove()
p=json.load(sys.stdin)
sys.path.insert(0,'/home/kesha/orchestra')
from app.gemini_web_auth import read_accounts,write_auth
accounts=read_accounts()
async def run():
 results=[]
 for mode in ('stored-pair','fresh-full','fresh-full-no-ts','fresh-full-stale-ts'):
  cookies=dict(accounts[0]['cookies'] if mode=='stored-pair' else p['cookies'])
  if mode=='fresh-full-no-ts': cookies.pop('__Secure-1PSIDTS',None)
  if mode=='fresh-full-stale-ts': cookies['__Secure-1PSIDTS']=accounts[0]['cookies'].get('__Secure-1PSIDTS','stale')
  async with AsyncSession(impersonate='chrome',timeout=20) as client:
   for name,value in cookies.items(): client.cookies.set(name,value,domain='.google.com',secure=True)
   r=await client.get('https://gemini.google.com/u/0/app')
   match=re.search(r'"oPEP7c"\s*:\s*("(?:\\.|[^"\\])*")',r.text)
   principal=json.loads(match.group(1)) if match else ''
   entry={'mode':mode,'status':r.status_code,'principal_present':bool(principal),'owner_match':principal in [a['expected_email'] for a in accounts]}
   r=await client.post('https://accounts.google.com/RotateCookies',headers=Headers.ROTATE_COOKIES.value,data='[000,"-0000000000000000000"]')
   entry.update(rotate_status=r.status_code,ts_received=any(c.name=='__Secure-1PSIDTS' for c in r.cookies.jar))
   results.append(entry)
 if p.get('install'):
  for a in accounts: a['cookies']=p['cookies']
  write_auth({'accounts':accounts})
 return {'variants':results,'cookie_names':sorted(p['cookies']),'installed':bool(p.get('install'))}
try: print(json.dumps(asyncio.run(run())))
except Exception as e: print(json.dumps({'failed':True,'type':type(e).__name__}));sys.exit(1)
'''
LAPTOP = r'''
import json,sys,subprocess
p=json.load(sys.stdin)
ns={'__name__':'reader'}
exec(p['reader'],ns)
cookies=ns['load_session_in_memory']()
result=subprocess.run(['ssh','-T','-o','BatchMode=yes','kesha@158.220.127.161',
 'cd /home/kesha/orchestra && data/gemini-web-pilot/.venv/bin/python -c '+__import__('shlex').quote(p['vps'])],
 input=json.dumps({'cookies':cookies,'install':p['install']}).encode(),capture_output=True,timeout=180)
try: print(json.dumps(json.loads(result.stdout)))
except Exception: print(json.dumps({'failed':True,'phase':'vps-output'}));sys.exit(1)
'''
def main():
 reader=(ROOT/'.orchestra/tasks/antigravity-laptop-2026-11-05/gemini-web-pilot.py').read_text()
 reader=reader.replace('COOKIE_NAMES = ("__Secure-1PSID", "__Secure-1PSIDTS")','COOKIE_NAMES = '+repr(NAMES))
 reader=reader.replace('"WHERE host_key=\'.google.com\' AND name IN (?,?)", COOKIE_NAMES,','"WHERE host_key=\'.google.com\' AND name IN (" + ",".join("?" for _ in COOKIE_NAMES) + ")", COOKIE_NAMES,')
 reader=reader.replace('for name in COOKIE_NAMES):','for name in ("__Secure-1PSID",)):')
 result=subprocess.run(['on-remote','--pc-home','.local/share/orchestra-gemini-web-pilot/.venv/bin/python','-c',LAPTOP],input=json.dumps({'reader':reader,'vps':VPS,'install':'--install' in __import__('sys').argv}).encode(),capture_output=True,timeout=210)
 try: summary=json.loads(result.stdout)
 except Exception: summary={'failed':True,'phase':'laptop-output'}
 (TASK/'cookie-probe.json').write_text(json.dumps(summary,indent=2)+'\n')
 print(json.dumps(summary))
if __name__=='__main__':main()
