# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy"]
# ///
"""Measure the pauses and speaking rate of a finished voice track (explainer-craft, section 4).

  pace.py out/<name>.voice.wav [--timing out/<name>.timing.json] [--drop 25]

Use the voice-only track `make.py` writes next to the video: a music bed sits only ~15 dB under
the voice and would hide the pauses. Frames are 20 ms with a 10 ms hop. Speech level is the 95th
percentile of frame loudness; a pause is a run of frames at least `--drop` dB below it, 150 ms to 6 s
long and surrounded by speech (longer runs are reported as inserts, not pauses). Bursts under
60 ms inside silence count as silence. With `--timing` it also prints Russian vowels per second.
"""
import json
import re
import subprocess
import sys

import numpy as np

SR, HOP, WIN = 16000, 160, 320


def runs(mask):
    edges = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.where(edges == 1)[0], np.where(edges == -1)[0]))


def analyse(path, drop=25.0):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)
    n = 1 + max(0, (len(x) - WIN) // HOP)
    cs = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    start = HOP * np.arange(n)
    db = 20 * np.log10(np.sqrt((cs[start + WIN] - cs[start]) / WIN + 1e-12))
    silent = db < np.percentile(db, 95) - drop
    for a, b in runs(~silent):
        if (b - a) * HOP / SR < 0.06:
            silent[a:b] = True
    pauses, inserts = [], []
    for a, b in runs(silent):
        if a == 0 or b >= n:
            continue
        length = (b - a) * HOP / SR
        if length >= 6.0:
            inserts.append(length)
        elif length >= 0.15:
            pauses.append(length)
    speech = runs(~silent)
    span = (speech[-1][1] - speech[0][0]) * HOP / SR if speech else 0.0
    return {"talk": span - sum(inserts), "pauses": np.array(pauses), "inserts": len(inserts)}


def main():
    args = sys.argv[1:]
    drop = float(args[args.index("--drop") + 1]) if "--drop" in args else 25.0
    r = analyse(args[0], drop)
    p, talk = r["pauses"], r["talk"]
    if not len(p) or talk <= 0:
        sys.exit("no pauses or no speech found")
    per_min = lambda k: round(k / talk * 60, 1)
    print(f"talk {talk:.1f} s, pauses {len(p)} ({per_min(len(p))}/min), pause share {100 * p.sum() / talk:.0f}%, "
          f"median {np.median(p):.2f} s, p90 {np.percentile(p, 90):.2f} s, longest {p.max():.2f} s")
    print(f">=0.5 s: {per_min((p >= .5).sum())}/min   >=1 s: {per_min((p >= 1).sum())}/min   "
          f">=2 s: {per_min((p >= 2).sum())}/min   inserts without speech: {r['inserts']}")
    if "--timing" in args:
        steps = json.loads(open(args[args.index("--timing") + 1]).read())["steps"]
        vowels = len(re.findall(r"[аеёиоуыэюяАЕЁИОУЫЭЮЯ]", " ".join(s["say"].replace("+", "") for s in steps)))
        print(f"vowels/s: {vowels / talk:.2f} over talk time, {vowels / (talk - p.sum()):.2f} articulating")


if __name__ == "__main__":
    main()
