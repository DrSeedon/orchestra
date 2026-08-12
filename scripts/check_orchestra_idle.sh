#!/bin/bash
# Печатает ALL_IDLE, когда в scope /home/kesha/orchestra нет воркеров в статусе
# running/waiting (сам оркестратор не считается). Иначе печатает список занятых.
curl -s -H "Authorization: Bearer $INTERNAL_TOKEN" "http://127.0.0.1:8888/api/sessions" \
| python3 -c "
import sys, json
rows = json.load(sys.stdin)
busy = [r['name'] for r in rows
        if r.get('scope') == '/home/kesha/orchestra'
        and r.get('status') in ('running', 'waiting')
        and r.get('name') != 'Orchestra-orchestrator']
print('ALL_IDLE' if not busy else 'BUSY: ' + ', '.join(sorted(busy)))
"
