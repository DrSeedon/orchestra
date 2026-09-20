import ast,json,re
from pathlib import Path
p=Path(__file__).parent
refs=json.loads((p/'references.json').read_text())
for name,entry in refs.items():
    entry['test_functions']=[]
    for f in entry['tests']:
        if not f['path'].endswith('.py'): continue
        src=Path(f['path']).read_text(); tree=ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                segment=ast.get_source_segment(src,node) or ''
                if re.search(r'(?<![a-zA-Z0-9_])'+name+r'(?![a-zA-Z0-9_])',segment) or 'mcp__orchestra__'+name in segment:
                    entry['test_functions'].append(f[ 'path']+'::'+node.name)
(p/'references.json').write_text(json.dumps(refs,ensure_ascii=False,indent=2)+'\n')
