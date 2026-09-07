"""Read-only source probes; no server, provider, or live DB imports."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

def source_function(path, name):
    source = ROOT / path
    tree = ast.parse(source.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace[name]

classify = source_function('app/session.py', '_subscription_limit_kind')
for text in ['The session limit parser needs a regression test.', 'Weekly usage limit reached', 'The task is complete.']:
    print(json.dumps({'text': text, 'limit_kind': classify(text)}, ensure_ascii=False))

# Extract the exact production regex, rather than reproducing it by hand.
tree = ast.parse((ROOT / 'app/codex_review_artifact.py').read_text())
function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_record_terminal_receipt')
call = next(n for n in ast.walk(function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'search')
pattern = ast.literal_eval(call.args[0])
for text in ['## Verdict\nNo verdict was reached.', '## Вердикт\nAPPROVED', '## Verdict\nAPPROVED']:
    match = re.search(pattern, text)
    print(json.dumps({'artifact': text, 'verdict_present': bool(match), 'verdict_value': ' '.join(match.group(1).split()) if match else ''}, ensure_ascii=False))
print('source_root=' + str(ROOT))
print('scope=classifier and artifact parser only; no end-to-end merge or live runtime claim')
