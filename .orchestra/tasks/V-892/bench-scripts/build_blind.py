"""Blind set: every model/voice → one file of all five phrases under a random code; key kept apart."""
import json, random, string, subprocess, sys, tempfile
from collections import defaultdict
from pathlib import Path

task = Path(sys.argv[1]).resolve()
samples = task / "samples"
blind = task / "blind"
blind.mkdir(exist_ok=True)
groups = defaultdict(dict)
for f in sorted(samples.glob("*_p[1-5].ogg")):
    stem, pid = f.stem.rsplit("_", 1)
    groups[stem][pid] = f
groups = {k: v for k, v in groups.items() if len(v) == 5}
codes = [a + b for a in string.ascii_uppercase for b in string.ascii_uppercase if a == b] + \
        [a + b for a in string.ascii_uppercase for b in string.ascii_uppercase if a != b]
rng = random.Random(892)
keys = list(groups)
rng.shuffle(keys)
key = {}
with tempfile.TemporaryDirectory() as tmp:
    silence = Path(tmp) / "sil.ogg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.8",
                    "-c:a", "libopus", "-b:a", "40k", str(silence)], check=True)
    for code, stem in zip(codes, keys):
        parts = []
        for pid in ["p1", "p2", "p3", "p4", "p5"]:
            parts += [groups[stem][pid], silence]
        lst = Path(tmp) / f"{code}.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        out = blind / f"{code}.ogg"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-ac", "1", "-c:a", "libopus", "-b:a", "40k", str(out)], check=True)
        key[code] = stem
(task / "blind_key.json").write_text(json.dumps(dict(sorted(key.items())), ensure_ascii=False, indent=1))
print(len(key), "blind files")
