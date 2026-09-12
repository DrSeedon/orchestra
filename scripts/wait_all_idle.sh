#!/bin/bash
# Печатает ALL_IDLE, когда НИ ОДИН агент платформы не выполняет ход.
# Смотрит всех, а не только потомков одного оркестратора: рестарт обрывает чужие
# проекты так же, как свои. Занятым считается running или waiting.
TOKEN=$(grep -oP '(?<=^INTERNAL_TOKEN=).*' /home/kesha/orchestra/.env)
BUSY=$(curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8888/api/sessions \
  | python3 -c "
import sys, json
try:
    rows = json.load(sys.stdin)
except Exception:
    print('UNKNOWN'); raise SystemExit
busy = [r['name'] for r in rows if r.get('status') in ('running', 'waiting')]
print(','.join(busy) if busy else 'NONE')
")
if [ "$BUSY" = "NONE" ]; then
  echo "ALL_IDLE: ни один агент не выполняет ход"
elif [ "$BUSY" = "UNKNOWN" ]; then
  echo "не смог прочитать список сессий"
else
  echo "заняты: $BUSY"
fi
