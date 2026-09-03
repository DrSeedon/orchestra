#!/usr/bin/env bash
# Полный прогон 20+20. Гейт по квоте — ВНУТРИ команды, а не в памяти запускающего:
# скрипт сам отказывается стартовать при 5h >= 60%.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PY=/home/kesha/orchestra/.venv/bin/python
N="${AB_N:-20}"

USE=$(curl -s -H "Authorization: Bearer $(grep '^INTERNAL_TOKEN=' /home/kesha/orchestra/.env | cut -d= -f2-)" \
      http://127.0.0.1:8888/api/usage \
      | $PY -c "import json,sys; print(json.load(sys.stdin)['anthropic']['five_hour']['utilization'])")
echo "5h = $USE%"
$PY -c "import sys; sys.exit(0 if float('$USE') < 60 else 1)" || {
  echo "ГЕЙТ: 5h >= 60% — не стартую."; exit 3; }

OUT="$HERE/results.tsv"
: > "$OUT"
for arm in a b; do
  for n in $(seq 1 "$N"); do
    "$HERE/harness.sh" "$arm" "$n" | tee -a "$OUT"
  done
done
echo "готово → $OUT"
