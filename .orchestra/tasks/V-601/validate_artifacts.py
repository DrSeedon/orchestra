import ast,json,re,subprocess
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.secret_mask import mask_secrets
from app import mcp_stdio
p=Path(__file__).parent
schemas=json.loads((p/'schemas.json').read_text()); decisions=json.loads((p/'decisions.json').read_text()); tokens=json.loads((p/'tokens.json').read_text()); proposed=json.loads((p/'proposed-descriptions.json').read_text())
assert len(schemas)==len(decisions)==45
assert {x['name'] for x in schemas}==set(decisions)
assert len(proposed)==10
assert sum(x['saved'] for x in tokens['changes'])==tokens['saved']==1463
text=(p/'tools-redesign.md').read_text()
assert text.count('| **переработать** |')==11
assert text.count('| **оставить как есть** |')==34
missing=[f for f in sorted(set(re.findall(r'(?:app|tests)/[A-Za-z0-9_/.-]+\.(?:py|json|js)',text))) if not Path(f).exists()]
assert not missing,missing
for file in p.iterdir():
    if file.suffix in {'.md','.py','.json','.log'}:
        content=file.read_text()
        assert mask_secrets(content)==content, f'secret-shaped content requires inspection: {file}'
for file in p.glob('*.py'): ast.parse(file.read_text())
assert Path(mcp_stdio.__file__).resolve() == Path('app/mcp_stdio.py').resolve()
print('import:',mcp_stdio.__file__)
print('45 tools; 34 unchanged + 11 rework; 10 description replacements; saving 1463')
print('local referenced paths exist; secret-shape scan clean; task scripts parse')
print('Only task artifacts may differ:')
print(subprocess.check_output(['git','status','--short'],text=True).rstrip())
