#!/usr/bin/env bash
set -euo pipefail

VIDEO=$1
TIMING=$2
OUT=$3
WORK=/home/kesha/readme-stand-V690/render/gif
mkdir -p "$WORK"

read -r START END < <(python3 - "$TIMING" <<'PY'
import json, sys
t = json.load(open(sys.argv[1]))
steps = t["steps"]
# Skip the title card and let the task view finish its camera and text fades before frame one.
start = t["pre"] + steps[1]["step_start"] + 0.6
end = t["pre"] + steps[13]["step_start"] + steps[13]["d"]
print(f"{start:.3f} {end:.3f}")
PY
)
DURATION=$(python3 -c 'import sys; print(f"{float(sys.argv[2])-float(sys.argv[1]):.3f}")' "$START" "$END")
FIRST="$WORK/first-frame.png"
LOOP="$WORK/readme-loop.mp4"
ffmpeg -v error -y -ss "$START" -i "$VIDEO" -frames:v 1 "$FIRST"
# Hold one second on the exact first view after the fade so the loop closes without a jump.
ffmpeg -v error -y -i "$VIDEO" -loop 1 -framerate 30 -t 2 -i "$FIRST" \
  -filter_complex "[0:v]trim=start=${START}:end=${END},setpts=PTS-STARTPTS,fps=30,format=yuv420p[base];[1:v]fps=30,format=yuv420p[still];[base][still]xfade=transition=fade:duration=1:offset=$(python3 -c 'import sys; print(f"{float(sys.argv[1])-2:.3f}")' "$DURATION"),format=yuv420p[out]" \
  -map "[out]" -an -c:v libx264 -preset medium -crf 20 -movflags +faststart "$LOOP"

for colors in 128 96 64 48 32; do
  ffmpeg -v error -y -i "$LOOP" \
    -filter_complex "[0:v]fps=10,scale=1000:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=${colors}:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle" \
    -loop 0 "$OUT"
  SIZE=$(stat -c %s "$OUT")
  printf 'colors=%s fps=10 width=1000 bytes=%s\n' "$colors" "$SIZE"
  if (( SIZE < 10000000 )); then exit 0; fi
done
echo "GIF exceeds 10000000 bytes at 32 colors: $SIZE" >&2
exit 1
