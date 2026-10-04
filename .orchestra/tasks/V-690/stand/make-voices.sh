#!/usr/bin/env bash
set -euo pipefail

TASK=/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690
OUT=/home/kesha/readme-stand-V690/render/voices
SCENE="$TASK/video/orchestra-tour.html"
MAKE=/home/kesha/orchestra/scripts/explainer_video/make.py
MEDIA="$TASK/media"
mkdir -p "$OUT" "$MEDIA"

for spec in '0 female_0' '1 female_1' '3 male_0' '4 male_1'; do
  read -r id voice <<<"$spec"
  name="orchestra-tour-voskspeaker${id}-${voice}"
  uv run --frozen --project /home/kesha/orchestra python "$MAKE" "$SCENE" \
    --out "$OUT" --speaker "$id" --lang ru --rate 1.25 --fps 30 --jobs 6
  python3 - "$OUT/orchestra-tour.check.json" <<'PY'
import json, sys
c = json.load(open(sys.argv[1]))
print(f"Deepgram min recall={c['recall_min']} onset max={c['onset_offset_max_abs_s']} s")
if c["recall_min"] < 0.85 or c["onset_offset_max_abs_s"] > 0.1:
    raise SystemExit("Deepgram voice check below acceptance threshold")
PY
  cp "$OUT/orchestra-tour-contact.png" "$TASK/video/${name}-contact.png"
  cp "$OUT/orchestra-tour.timing.json" "$TASK/video/${name}.timing.json"
  cp "$OUT/orchestra-tour.check.json" "$TASK/video/${name}.check.json"
  cp "$OUT/orchestra-tour.mp4" "$MEDIA/${name}-telegram.mp4"
  for crf in 27 29 31 33; do
    ffmpeg -v error -y -i "$MEDIA/${name}-telegram.mp4" -map 0:v:0 -map 0:a:0 \
      -c:v libx264 -preset slow -crf "$crf" -pix_fmt yuv420p \
      -c:a aac -b:a 96k -movflags +faststart "$MEDIA/${name}-github.mp4"
    size=$(stat -c %s "$MEDIA/${name}-github.mp4")
    if (( size <= 9500000 )); then break; fi
  done
  if (( size > 9500000 )); then
    echo "$name GitHub copy is $size bytes; target is at most 9500000" >&2
    exit 1
  fi
  printf '%s telegram=%s github=%s crf=%s\n' "$name" \
    "$(stat -c %s "$MEDIA/${name}-telegram.mp4")" "$size" "$crf"
done
