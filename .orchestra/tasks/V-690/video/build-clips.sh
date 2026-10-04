#!/bin/bash
# Cut the stand screencast (stand/clips.py) into per-clip JPEG sequences the scene plays on a canvas.
#   build-clips.sh RECDIR   → video/clips/<name>/0001.jpg … and video/clips/clips.js
# Frames are not committed (≈150 MB); RECDIR/full.mp4 is the source of truth for a rebuild.
set -e
REC=$1; HERE=$(cd "$(dirname "$0")" && pwd); FPS=25
cd "$REC"
[ -f full.mp4 ] || ffmpeg -v error -y -f concat -safe 0 -i frames.txt -vf "fps=$FPS,format=yuv420p" \
  -c:v libx264 -preset slow -crf 14 full.mp4
mkdir -p "$HERE/clips"
python3 -c "import json;[print(k,*v) for k,v in json.load(open('marks.json')).items()]" | while read -r name a b; do
  mkdir -p "$HERE/clips/$name"; find "$HERE/clips/$name" -name "*.jpg" -delete
  ffmpeg -nostdin -v error -y -ss "$a" -to "$b" -i full.mp4 -q:v 3 "$HERE/clips/$name/%04d.jpg"
done
# Index + cursor track per clip (time from the clip's first frame, page CSS px, click flag).
python3 - "$HERE/clips" <<'PY'
import json, os, sys
d = sys.argv[1]; marks = json.load(open("marks.json")); track = json.load(open("cursor.json"))
clips = {}
for name, (a, b) in marks.items():
    pts = [[round(t - a, 3), x, y, c] for t, x, y, c in track if a - 1 <= t <= b]
    clips[name] = {"n": len(os.listdir(f"{d}/{name}")), "fps": 25, "cursor": pts}
open(f"{d}/clips.js", "w").write("const CLIPS = " + json.dumps(clips) + ";\n")
print({k: (v["n"], len(v["cursor"])) for k, v in clips.items()})
PY
