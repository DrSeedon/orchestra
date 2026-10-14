import ast
import csv
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

OUT=Path(__file__).resolve().parent
rows=[r for r in csv.DictReader((OUT/'sleep_calls_7d.csv').open()) if r['sleep_kind']=='python_embedded']
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON')
out=[]
for row in rows:
    rec=c.execute('SELECT content FROM logs WHERE id=?',(int(row['call_id']),)).fetchone()
    try:payload=json.loads(rec['content'][rec['content'].index('{'):]) if rec else {}
    except (ValueError,json.JSONDecodeError):payload={}
    command=str(payload.get('command') or '')
    match=re.search(r'python(?:3)?\s+-\s*<<[\'\"]?(\w+)[\'\"]?',command)
    heredoc=bool(match)
    calls=[];parse_ok=False
    if match:
        label=match.group(1);start=match.end()
        end=re.search(r'\n'+re.escape(label)+r'(?=\s|$)',command[start:])
        source=command[start:start+end.start()] if end else command[start:]
        try:
            tree=ast.parse(source);parse_ok=True
            for node in ast.walk(tree):
                if not isinstance(node,ast.Call):continue
                fn=node.func
                name=(f'{fn.value.id}.{fn.attr}' if isinstance(fn,ast.Attribute) and isinstance(fn.value,ast.Name) else fn.id if isinstance(fn,ast.Name) else '')
                if name.endswith('.sleep') or name=='sleep':
                    args=[]
                    for arg in node.args:
                        try:args.append(ast.literal_eval(arg))
                        except Exception:args.append('?')
                    calls.append({'line':node.lineno,'name':name,'args':args})
        except SyntaxError:pass
    if calls:kind='executed_python_sleep_call'
    elif heredoc and parse_ok:kind='python_heredoc_no_executed_sleep_call'
    elif heredoc:kind='unparsed_python_heredoc'
    elif any(x in command for x in ('cat >','open(','write_text','write(')):kind='sleep_mentioned_while_writing_source'
    else:kind='embedded_sleep_reference_unclassified'
    out.append({'call_id':row['call_id'],'session_id':row['session_id'],'session_name':row['session_name'],'runtime':row['runtime'],'call_ts':row['call_ts'],'tool_duration_s':row['tool_duration_s'],'kind':kind,'sleep_calls_ast':json.dumps(calls,separators=(',',':')),'command_sanitized':row['command_sanitized']})
with (OUT/'embedded_sleep_analysis.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(out[0]) if out else []);w.writeheader();w.writerows(out)
counts=Counter(r['kind'] for r in out)
print('candidates',len(out),'kinds',dict(counts))
for r in out:
    if r['kind']=='executed_python_sleep_call':print(r['session_name'],r['call_ts'],r['tool_duration_s'],r['sleep_calls_ast'],r['command_sanitized'][:180])
c.close()
