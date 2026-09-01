import json, html

findings = json.load(open('/tmp/claude-1000/audit/annotated.json'))

def bucket(st):
    for k, v in (('ПОДТВЕРЖДЁН', 'confirmed'), ('СПОРНЫЙ', 'split'),
                 ('НЕ ПРОВЕРЕН', 'unverified'), ('ОТКЛОНЁН', 'refuted')):
        if st.startswith(k):
            return v
    return 'unverified'

rows = []
for f in findings:
    rows.append({
        'sev': f['severity'],
        'loc': f"{f['file']}:{f['line']}",
        'title': f['title'],
        'status': f['status'],
        'bucket': bucket(f['status']),
        'desc': f['description'],
        'fail': f['failure_scenario'],
    })
order = {'confirmed': 0, 'split': 1, 'unverified': 2, 'refuted': 3}
rows.sort(key=lambda r: (order[r['bucket']], r['sev'], r['loc']))

DATA = json.dumps(rows, ensure_ascii=False)

page = open('/tmp/claude-1000/audit/template.html').read()
open('/tmp/claude-1000/audit/audit.html', 'w').write(page.replace('__DATA__', DATA))
print('rows', len(rows))
