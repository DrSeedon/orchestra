#!/usr/bin/env bash
set -euo pipefail

cd /home/kesha/orchestra/worktrees/home-kesha-orchestra/research-ru-stress
/home/kesha/orchestra/.venv/bin/python scripts/explainer_video/make.py \
  .orchestra/tasks/V-696/orchestra-tour.html \
  --out .orchestra/tasks/V-696/video --speaker 1 --rate 1.15 --jobs 6

python - <<'PY'
import json

check = json.load(open(".orchestra/tasks/V-696/video/orchestra-tour.check.json"))
print(f"Deepgram min recall={check['recall_min']} onset max={check['onset_offset_max_abs_s']} s")
if check["recall_min"] < 0.85 or check["onset_offset_max_abs_s"] > 0.1:
    raise SystemExit("Deepgram voice check below acceptance threshold")
PY

MEDIA=.orchestra/tasks/V-696/media
mkdir -p "$MEDIA"
cp .orchestra/tasks/V-696/video/orchestra-tour.mp4 \
  "$MEDIA/orchestra-tour-voskspeaker1-female_1-ruaccent-telegram.mp4"
for crf in 27 29 31 33; do
  ffmpeg -v error -y -i "$MEDIA/orchestra-tour-voskspeaker1-female_1-ruaccent-telegram.mp4" \
    -map 0:v:0 -map 0:a:0 -c:v libx264 -preset slow -crf "$crf" -pix_fmt yuv420p \
    -c:a aac -b:a 96k -movflags +faststart \
    "$MEDIA/orchestra-tour-voskspeaker1-female_1-ruaccent-github.mp4"
  size=$(stat -c %s "$MEDIA/orchestra-tour-voskspeaker1-female_1-ruaccent-github.mp4")
  if (( size <= 9500000 )); then break; fi
done
if (( size > 9500000 )); then
  echo "GitHub copy exceeds 9,500,000 bytes: $size" >&2
  exit 1
fi

/home/kesha/orchestra/.venv/bin/python .orchestra/tasks/V-696/compare_stress.py \
  .orchestra/tasks/V-690/video/orchestra-tour.html \
  .orchestra/tasks/V-696/stress-differences.json
printf 'telegram=%s github=%s crf=%s\n' \
  "$(stat -c %s "$MEDIA/orchestra-tour-voskspeaker1-female_1-ruaccent-telegram.mp4")" \
  "$size" "$crf"
