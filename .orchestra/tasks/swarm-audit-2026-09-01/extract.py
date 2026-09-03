import json, os, glob, re, collections

D = '/home/maxim/.claude/projects/-mnt-data-Projects-Python-orchestra/bd702267-a0db-42f2-8808-b0d43e37ced3/subagents/workflows/wf_4dacb762-819'
prompts, res = {}, {}
for fn in glob.glob(os.path.join(D, 'agent-*.jsonl')):
    aid = os.path.basename(fn)[6:-6]
    with open(fn) as f:
        first = f.readline()
    try:
        c = json.loads(first)['message']['content']
    except Exception:
        c = ''
    prompts[aid] = c if isinstance(c, str) else str(c)
for line in open(os.path.join(D, 'journal.jsonl')):
    r = json.loads(line)
    if r.get('type') == 'result':
        res[r['agentId']] = r.get('result')

findings = []
for aid, p in prompts.items():
    if not p.startswith('You are a senior reviewer'):
        continue
    m = re.search(r'Focus files: (.+)', p)
    focus = m.group(1).strip() if m else '?'
    out = res.get(aid)
    if not isinstance(out, dict):
        continue
    for f in out.get('findings', []):
        f['focus'] = focus
        findings.append(f)

verdicts = collections.defaultdict(list)
for aid, p in prompts.items():
    if not p.startswith('Adversarially verify'):
        continue
    mloc = re.search(r'Location: (\S+):(\d+)', p)
    if not mloc:
        continue
    key = f"{mloc.group(1)}:{mloc.group(2)}"
    is_tie = 'tiebreaker' in p
    out = res.get(aid)
    verdicts[key].append({'done': isinstance(out, dict), 'refuted': out.get('refuted') if isinstance(out, dict) else None,
                          'reason': (out.get('reason') if isinstance(out, dict) else None), 'tie': is_tie})

json.dump({'findings': findings, 'verdicts': verdicts}, open('/tmp/claude-1000/audit/data.json', 'w'), ensure_ascii=False, indent=1)

print(f"findings: {len(findings)}  keys with verdicts: {len(verdicts)}")
print()
for f in sorted(findings, key=lambda x: (x['severity'], x['file'])):
    k = f"{f['file']}:{f['line']}"
    vs = verdicts.get(k, [])
    done = [v for v in vs if v['done']]
    if not done:
        st = f"UNVERIFIED (quota, {len(vs)} launched)"
    else:
        ref = sum(1 for v in done if v['refuted'])
        tie = [v for v in done if v['tie']]
        if tie:
            st = "CONFIRMED(tie)" if not tie[0]['refuted'] else "refuted(tie)"
        elif len(done) == 2 and ref == 0:
            st = "CONFIRMED"
        elif ref == len(done):
            st = "refuted"
        else:
            st = f"SPLIT {len(done)-ref}/{len(done)} ok, tie missing"
    print(f"[{f['severity']}] {st:32s} {k}")
    print(f"      {f['title'][:150]}")
