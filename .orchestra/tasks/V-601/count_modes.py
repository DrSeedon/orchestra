import ast,json
from pathlib import Path
import tiktoken
p=Path(__file__).parent
enc=tiktoken.get_encoding('o200k_base')
def count(v): return len(enc.encode(json.dumps(v,ensure_ascii=False,separators=(',',':'))))
schemas=json.loads((p/'schemas.json').read_text()); edits=json.loads((p/'proposed-descriptions.json').read_text())
constants={node.targets[0].id:ast.literal_eval(node.value.args[0]) for node in ast.parse(Path('app/mcp_stdio.py').read_text()).body if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in {'READ_ONLY_MCP_TOOLS','REDUCER_MCP_TOOLS'}}
rows=[]
for mode,names in [('full',{t['name'] for t in schemas}),('read-only',constants['READ_ONLY_MCP_TOOLS']),('reducer',constants['REDUCER_MCP_TOOLS'])]:
 selected=[{k:t[k] for k in ('name','description','inputSchema')} for t in schemas if t['name'] in names]
 proposed=[{**t,'description':edits.get(t['name'],t['description'])} for t in selected]
 rows.append(dict(mode=mode,tools=len(selected),before_sum=sum(map(count,selected)),after_sum=sum(map(count,proposed)),before_array=count(selected),after_array=count(proposed)))
harness=[]
for t in schemas:
 x={'type':'function','function':{'name':t['name'],'description':t['description'],'parameters':t['inputSchema']}}
 y={'type':'function','function':{**x['function'],'description':edits.get(t['name'],t['description'])}}
 harness.append({'name':t['name'],'before':count(x),'after':count(y)})
(p/'modes.json').write_text(json.dumps({'modes':rows,'harness':harness},indent=2)+'\n')
print(rows);print('harness',sum(x['before'] for x in harness),sum(x['after'] for x in harness))
