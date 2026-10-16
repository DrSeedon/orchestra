"""Gather all outputs → ogg samples, Deepgram recall (cached), rows.json."""
import json, re, subprocess, urllib.request
from collections import Counter
from pathlib import Path
root = Path(__file__).parents[1]
task = Path("/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-tts/.orchestra/tasks/V-892")
samples = task / "samples"; samples.mkdir(exist_ok=True)
phr = {p["id"]: p["text"] for p in json.load(open(root / "phrases.json"))}
key = next(l.split("=", 1)[1].strip().strip("'\"") for l in open("/home/kesha/orchestra/.env") if l.startswith("DEEPGRAM_API_KEY="))
cache_path = root / "out/dg_cache.json"
cache = json.load(open(cache_path)) if cache_path.exists() else {}
import sys
sys.path.insert(0, "/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-tts/scripts/video_artifact")
import make  # production check scoring: tokens/align/word_scores
def recall(ref, hyp):
    hits = make.align([ref], make.tokens(hyp))[0]
    lex, num, _n = make.word_scores(ref, hits)
    return round(lex, 3), round(num, 3)
def dg(path):
    k = f"{path}:{path.stat().st_mtime_ns}"
    if k not in cache:
        audio = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "mp3", "-"], capture_output=True, check=True).stdout
        req = urllib.request.Request("https://api.deepgram.com/v1/listen?model=nova-2&language=ru&punctuate=true", data=audio,
                                     headers={"Authorization": f"Token {key}", "Content-Type": "audio/mpeg"})
        cache[k] = json.load(urllib.request.urlopen(req, timeout=120))["results"]["channels"][0]["alternatives"][0]["transcript"]
        json.dump(cache, open(cache_path, "w"), ensure_ascii=False)
    return cache[k]
rows = []
for tl in sorted(root.glob("out/*/timing.jsonl")):
    for line in open(tl):
        rows.append(json.loads(line))
cl = root / "out/clients/clients.jsonl"
if cl.exists():
    for line in open(cl):
        d = json.loads(line)
        if "file" in d:
            src, voice = d["source"].split("_", 1)
            rows.append({"model": src, "voice": voice, "phrase": d["phrase"], "file": d["file"], "wall_s": d["wall_s"], "plus_input": False})
seen = {}
for r in rows:
    f = Path(r["file"]) if Path(r["file"]).is_absolute() else root / r["file"]
    seen[(f.name)] = (r, f)
out = []
for name, (r, f) in sorted(seen.items()):
    if not f.exists(): continue
    ogg = samples / (f.stem + ".ogg")
    if not ogg.exists() or ogg.stat().st_mtime < f.stat().st_mtime:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-af", "loudnorm=I=-20:TP=-2", "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "40k", str(ogg)], check=True)
    hyp = dg(f)
    lex, num = recall(phr[r["phrase"]], hyp)
    r = dict(r, sample=ogg.name, transcript=hyp, recall=lex, numeric_recall=num)
    out.append(r)
json.dump(out, open(task / "rows.json", "w"), ensure_ascii=False, indent=1)
print(len(out), "rows")
