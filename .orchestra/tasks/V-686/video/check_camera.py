"""Does the camera/frame land before the voice starts the phrase? python check_camera.py SCENE.html OUTDIR

Landing = step start + CAM_POST from the scene (+ the renderer's PRE still); the voice onset is
the measured one from <name>.check.json (planned start + onset offset found by Deepgram).
"""
import json
import re
import sys
from pathlib import Path

scene = Path(sys.argv[1]); out = Path(sys.argv[2]); name = scene.stem
html = scene.read_text()
cam_pre = float(re.search(r"CAM_PRE = ([\d.]+)", html).group(1))
cam_post = float(re.search(r"CAM_POST = ([\d.]+)", html).group(1))
timing = json.loads((out / f"{name}.timing.json").read_text())
check = json.loads((out / f"{name}.check.json").read_text())
rows, worst = [], None
print(f"{'#':>2} {'step':<20} {'move starts':>11} {'lands':>7} {'voice':>7} {'margin':>7}")
for i, (step, phrase) in enumerate(zip(timing["steps"], check["phrases"])):
    start = timing["pre"] + step["step_start"]
    lands = start + cam_post
    voice = phrase["planned_start"] + phrase["onset_offset_s"]
    margin = voice - lands
    worst = margin if worst is None else min(worst, margin)
    rows.append({"step": step["title"], "move_start": round(start - (cam_pre if i else 0), 3),
                 "lands": round(lands, 3), "voice_onset": round(voice, 3), "margin_s": round(margin, 3)})
    print(f"{i + 1:>2} {step['title']:<20} {rows[-1]['move_start']:>11.2f} {lands:>7.2f} {voice:>7.2f} {margin:>+7.2f}")
(out / f"{name}.camera.json").write_text(json.dumps({"worst_margin_s": round(worst, 3), "steps": rows}, indent=1))
print("worst margin", round(worst, 3), "s →", "OK" if worst >= 0 else "LATE")
sys.exit(0 if worst >= 0 else 1)
