#!/usr/bin/env python3
"""V-767 item 3: fan-out scenarios F1 (facts by schema), F2 (parallel claim check), F3 (reducer).
usage: fan.py gen | fan.py run <model:haiku|luna> <rep> | fan.py score"""
import ast, json, os, random, re, subprocess, sys, time, glob
from concurrent.futures import ThreadPoolExecutor
R = '/home/kesha/orchestra/data/v767'; SRC = R + '/src'
def lines_of(p): return open(p, encoding='utf-8').read().count('\n')
def gen():
    random.seed(767)
    files = sorted(glob.glob(SRC + '/app/*.py'))
    files = [f for f in files if 80 <= lines_of(f) <= 1500 and not f.endswith('__init__.py')]
    pick = random.sample(files, 12)
    items = []
    for f in pick:
        rel = os.path.relpath(f, SRC); t = ast.parse(open(f, encoding='utf-8').read())
        facts = dict(file=rel, lines=lines_of(f),
          functions=sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in t.body),
          classes=sum(isinstance(n, ast.ClassDef) for n in t.body),
          main_guard=any(isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name) and n.test.left.id == '__name__' for n in t.body))
        prompt = (f"Прочитай файл {rel} в текущем каталоге (ничего не изменяй). Верни ОДИН JSON-объект без пояснений со схемой "
          '{"file": str, "lines": int, "functions": int, "classes": int, "main_guard": bool}. '
          "file — путь как дан; lines — число символов перевода строки в файле (как `wc -l`); functions — число функций верхнего уровня модуля "
          "(def и async def прямо в теле модуля, без методов классов и вложенных функций); classes — число классов верхнего уровня; "
          "main_guard — true, если на верхнем уровне есть блок `if __name__ == ...`.")
        items.append(dict(id='F1-' + os.path.basename(f)[:-3], kind='F1', prompt=prompt, oracle=facts))
    # F2: claims "function F in file has parameter P"
    claims = []
    cands = []
    for f in pick:
        t = ast.parse(open(f, encoding='utf-8').read())
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and len(n.args.args) + len(n.args.kwonlyargs) >= 2:
                cands.append((os.path.relpath(f, SRC), n.name, [a.arg for a in n.args.args + n.args.kwonlyargs]))
    random.shuffle(cands); seen = set()
    for rel, fn, params in cands:
        if fn in seen or fn.startswith('__'): continue
        seen.add(fn)
        if len(claims) % 2 == 0:
            p = random.choice([x for x in params if x not in ('self', 'cls')] or params); true = True
        else:
            other = [x for cand in cands for x in cand[2] if x not in params and x not in ('self', 'cls')]
            p = random.choice(other); true = False
        prompt = (f"Проверь утверждение по коду в текущем каталоге (ничего не изменяй): «в файле {rel} есть функция или метод {fn}, "
          f"у которого среди параметров (позиционных или keyword-only) есть `{p}`». Верни ОДИН JSON без пояснений: "
          '{"verdict": true|false, "evidence": "точная строка def из файла, на которой основан вывод, или \\"\\" если функции нет"}.')
        claims.append(dict(id=f'F2-{len(claims):02d}', kind='F2', prompt=prompt, oracle=dict(verdict=true, file=rel, fn=fn)))
        if len(claims) == 12: break
    json.dump(items + claims, open(R + '/fan_items.json', 'w'), indent=1, ensure_ascii=False)
    # F3 reducer on oracle F1 records
    recs = [i['oracle'] for i in items]
    os.makedirs(R + '/fan_f3', exist_ok=True)
    json.dump(recs, open(R + '/fan_f3/records.json', 'w'), ensure_ascii=False)
    top = sorted(recs, key=lambda r: (-r['functions'], r['file']))[:3]
    f3 = dict(total_lines=sum(r['lines'] for r in recs), top3=[r['file'] for r in top],
              with_main_guard=sum(r['main_guard'] for r in recs), mean_lines=round(sum(r['lines'] for r in recs) / len(recs)))
    p3 = ("В файле /home/kesha/orchestra/data/v767/fan_f3/records.json — список из 12 записей {file, lines, functions, classes, main_guard}. "
          "Сведи их (ничего не изменяй) и верни ОДИН JSON без пояснений: "
          '{"total_lines": int (сумма lines), "top3": [3 значения file с наибольшим functions по убыванию; при равенстве — по алфавиту file], '
          '"with_main_guard": int (сколько записей с main_guard=true), "mean_lines": int (среднее lines, округлённое до целого)}.')
    json.dump(items + claims + [dict(id='F3-reduce', kind='F3', prompt=p3, oracle=f3)], open(R + '/fan_items.json', 'w'), indent=1, ensure_ascii=False)
    print(len(items), len(claims), f3)
def call(model, item, out):
    t0 = time.time()
    if model == 'haiku':
        r = subprocess.run(['claude', '-p', '--model', 'claude-haiku-5-5', '--effort', 'low', '--output-format', 'json', '--permission-mode', 'bypassPermissions', '--', item['prompt']],
                           cwd=SRC, capture_output=True, text=True, timeout=900)
        try:
            j = json.loads(r.stdout); text = j['result']; cost = j['total_cost_usd']
        except Exception: text, cost = r.stdout[-500:], None
    else:
        r = subprocess.run(['codex', 'exec', '-m', 'gpt-6-luna', '--dangerously-bypass-approvals-and-sandbox', '--skip-git-repo-check', '--json', item['prompt']],
                           cwd=SRC, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        ev = [json.loads(l) for l in r.stdout.splitlines() if l.startswith('{')]
        msgs = [e['item']['text'] for e in ev if e.get('type') == 'item.completed' and e['item'].get('type') == 'agent_message']
        us = [e['usage'] for e in ev if e.get('type') == 'turn.completed']
        text = msgs[-1] if msgs else ''
        u = us[-1] if us else None
        cost = ((u['input_tokens'] - u['cached_input_tokens']) * 0.10 + u['cached_input_tokens'] * 0.01 + u['output_tokens'] * 0.50) / 1e6 if u else None
    json.dump(dict(id=item['id'], text=text, cost=cost, sec=time.time() - t0), open(out, 'w'), ensure_ascii=False)
def run(model, rep):
    items = json.load(open(R + '/fan_items.json')); d = f'{R}/fan/{model}-{rep}'; os.makedirs(d, exist_ok=True)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda it: call(model, it, f"{d}/{it['id']}.json"), items))
def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    try: return json.loads(m.group(0))
    except Exception: return None
def score():
    items = {i['id']: i for i in json.load(open(R + '/fan_items.json'))}
    res = {}
    for d in sorted(glob.glob(R + '/fan/*')):
        tag = os.path.basename(d); ok = {'F1': [], 'F2': [], 'F3': []}; cost = {'F1': 0, 'F2': 0, 'F3': 0}; sec = {'F1': [], 'F2': [], 'F3': []}
        for f in glob.glob(d + '/*.json'):
            r = json.load(open(f)); it = items[r['id']]; k = it['kind']; o = parse(r['text']); g = it['oracle']; good = False
            if o:
                if k == 'F1': good = all(o.get(x) == g[x] for x in ('file', 'lines', 'functions', 'classes', 'main_guard'))
                elif k == 'F2':
                    good = o.get('verdict') is g['verdict']
                    if good and g['verdict']:
                        good = bool(re.search(r'def\s+' + re.escape(g['fn']) + r'\b', o.get('evidence') or ''))
                else: good = all(o.get(x) == g[x] for x in g)
            ok[k].append(good); cost[k] += r['cost'] or 0; sec[k].append(r['sec'])
        res[tag] = {k: dict(ok=sum(v), n=len(v), usd=round(cost[k], 4), med_sec=round(sorted(sec[k])[len(sec[k]) // 2], 1) if sec[k] else None) for k, v in ok.items()}
    json.dump(res, open(R + '/fan_score.json', 'w'), indent=1); print(json.dumps(res, indent=1))
if __name__ == '__main__':
    {'gen': lambda: gen(), 'run': lambda: run(sys.argv[2], sys.argv[3]), 'score': lambda: score()}[sys.argv[1]]()
