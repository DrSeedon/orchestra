"""Schema-only offline MCP: never executes tools or contacts Orchestra."""
import json,pathlib,sys
schemas=json.loads(pathlib.Path(__file__).with_name('local').joinpath('mcp-schemas.json').read_text())
for line in sys.stdin:
 try:r=json.loads(line)
 except ValueError:continue
 if 'id' not in r:continue
 method=r.get('method')
 if method=='initialize':result={'protocolVersion':'2025-03-26','capabilities':{'tools':{}},'serverInfo':{'name':'orchestra','version':'offline-v568'}}
 elif method=='tools/list':result={'tools':schemas}
 elif method in ('resources/list','prompts/list'):result={method.split('/')[0]:[]}
 else:print(json.dumps({'jsonrpc':'2.0','id':r['id'],'error':{'code':-32601,'message':'Offline schema capture: execution unavailable'}}),flush=True);continue
 print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)
