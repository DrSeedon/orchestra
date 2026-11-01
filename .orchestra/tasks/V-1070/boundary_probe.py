"""Offline request construction probe. No stream(), HTTP, DB or CLI is invoked."""
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys

TASK=Path(__file__).resolve().parent
ROOT=TASK.parents[2]
sys.path.insert(0,str(ROOT))
import app
from app.harness import llm
from PIL import Image

samples=TASK/'samples'
client=llm.OpenRouterClient('unused-offline-placeholder','synthetic/vision:free',
    input_modalities=('text','image'),attachments_root=samples,workspace_root=samples)
original_reader=llm.read_image
reads=[]
def observe(*args,**kwargs):
    result=original_reader(*args,**kwargs)
    reads.append(result[0].name)
    return result
llm.read_image=observe
photo=samples/'01-terminal.png'
history=[{'role':'user','content':f'[photo: {photo}] inspect'}]
summaries=[]
for round_no in (1,2):
    prepared=client._prepare_messages(history)
    uri=prepared[0]['content'][1]['image_url']['url']
    data=base64.b64decode(uri.split(',',1)[1])
    with Image.open(BytesIO(data)) as im:
        summaries.append({'round':round_no,'image_count':1,'pixels':list(im.size),
            'byte_identical':data==photo.read_bytes(),'detail_sent':'detail' in prepared[0]['content'][1]['image_url']})
    history.extend([{'role':'assistant','content':'description'},{'role':'user','content':'follow up'}])
bare=[{'role':'user','content':str(photo)}]
print('app:',app.__file__)
print('two rounds:',json.dumps(summaries))
print('disk reads:',reads)
print('bare dashboard path stays text:',client._prepare_messages(bare)==bare)
textonly=llm.OpenRouterClient('unused-offline-placeholder','synthetic/text:free',input_modalities=('text',),attachments_root=samples)
print('text-only tagged path stays text:',textonly._prepare_messages(history)==history)
missing=[{'role':'user','content':f'[photo: {samples / "missing.png"}]'}]
try: client._prepare_messages(missing)
except ValueError as exc: print('missing original:',type(exc).__name__,'image file unavailable' in str(exc))
workspace=[{'role':'assistant','content':None,'tool_calls':[{'id':'local-image','function':{'name':'read_image'}}]},
    {'role':'tool','tool_call_id':'local-image','content':'[workspace image: 01-terminal.png]'}]
for round_no in (1,2):
    prepared=client._prepare_messages(workspace)
    print('workspace round',round_no,'images',sum(part.get('type')=='image_url' for m in prepared if isinstance(m.get('content'),list) for part in m['content']))
print('total disk reads:',reads)
assert all(s['byte_identical'] and s['pixels']==[1280,720] and not s['detail_sent'] for s in summaries)
assert reads.count('01-terminal.png')==4
assert client._prepare_messages(bare)==bare
print('PASS: 2 tagged and 2 workspace history replays reread full original bytes; no network')

# Public catalog snapshot: these are offered routes, not our private enablement.
raw=json.loads((TASK/'sources/public-catalog.json').read_text())
paid={'deepseek/deepseek-v4.1-flash','deepseek/deepseek-v4.1-flash-1017','z-ai/glm-5.3','z-ai/glm-5.3-flash'}
rows=[]
for model in raw['data']:
    mid=model['id'];arch=model.get('architecture') or {};params=model.get('supported_parameters') or []
    modalities=arch.get('input_modalities') or []
    if not (mid.endswith(':free') or mid in paid): continue
    if 'text' not in modalities or 'text' not in (arch.get('output_modalities') or []) or 'tools' not in params: continue
    rows.append({'id':mid,'image_input':'image' in modalities,'detail_parameter':'image_detail' in params or 'detail' in params})
(TASK/'public-routes.json').write_text(json.dumps(rows,indent=2))
print('PUBLIC ELIGIBLE',len(rows),'vision',sum(x['image_input'] for x in rows))
for row in rows: print(json.dumps(row))
