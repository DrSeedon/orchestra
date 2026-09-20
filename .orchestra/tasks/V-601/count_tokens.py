"""Offline size proxy; no provider calls, app changes, or dependency changes."""
import json
from pathlib import Path
import tiktoken
p = Path(__file__).parent
enc = tiktoken.get_encoding('o200k_base')
def count(x):
    return len(enc.encode(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, separators=(',', ':'))))
rows=[]
for t in json.loads((p/'schemas.json').read_text()):
    projection={k:t[k] for k in ('name','description','inputSchema')}
    rows.append(dict(name=t['name'], description=count(t['description']), input_schema=count(t['inputSchema']), input_total=count(projection), wire_total=count(t)))
out={'tokenizer':f'tiktoken {tiktoken.__version__} o200k_base','serialization':'ensure_ascii=False,separators=(comma,colon)','tools':rows,'input_total':sum(r['input_total'] for r in rows),'wire_total':sum(r['wire_total'] for r in rows)}
if (p/'proposed-descriptions.json').exists():
    edits=json.loads((p/'proposed-descriptions.json').read_text())
    deltas=[]
    for t in json.loads((p/'schemas.json').read_text()):
        if t['name'] in edits:
            old={k:t[k] for k in ('name','description','inputSchema')}
            new={**old,'description':edits[t['name']]}
            deltas.append(dict(name=t['name'],before=count(old),after=count(new),saved=count(old)-count(new)))
    out['changes']=deltas
    out['saved']=sum(r['saved'] for r in deltas)
(p/'tokens.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(out,ensure_ascii=False))
