#!/usr/bin/env bash
# #189 — базовая линия за сутки, одной командой.
#   bash docs/tasks/189/run_all.sh [день] [снимок] [каталог результата]
# Пачки журнала (участки, разделённые тишиной > 180 с) независимы по очереди доставки,
# поэтому считаются параллельно. Раскладка групп — по длительности, чтобы все шесть
# процессов закончили примерно одновременно; общее время ≈ длительность самой длинной пачки.
set -euo pipefail

DAY="${1:-2026-08-10}"
SNAP="${2:-/tmp/snap189.db}"
OUT="${3:-/tmp/replay189}"
REPO_ARG="${4:-}"   # какое дерево мерить; пусто = дерево этого файла
PY=/home/kesha/orchestra/.venv/bin/python
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$OUT"
rm -f "$OUT"/part-*.json

for GROUP in "4" "9,13" "16,23,8" "14,12,19,7" "17,15,6,22,21,5" "10,0,20,1,18,2,11,3"; do
    "$PY" "$HERE/replay.py" --snapshot "$SNAP" --day "$DAY" --out "$OUT" \
        ${REPO_ARG:+--repo "$REPO_ARG"} \
        --bursts "$GROUP" > "$OUT/log-${GROUP%%,*}.txt" 2>&1 &
done
wait

"$PY" "$HERE/sum_parts.py" "$OUT"
