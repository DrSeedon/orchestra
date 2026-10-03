"""Темп ×1.5: Vosk speech_rate=1.5 против atempo=1.5 поверх rate 1.0 — длительность и распознавание."""
import importlib.util, json, os, subprocess, sys, urllib.request, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("m", ROOT / "scripts/explainer_video/make.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
HERE = Path(__file__).parent
timing = json.loads((ROOT / ".orchestra/tasks/V-681/video/cache-ttl.timing.json").read_text())
steps = [{"t": r["title"], "say": r["say"], "sub": r["sub"], "hold": None} for r in timing["steps"]]
variants = {}
variants["rate1.0"] = m.synthesize(steps, HERE / "cache", 3, 1.0)
variants["rate1.5"] = m.synthesize(steps, HERE / "cache", 3, 1.5)
variants["rate1.25"] = m.synthesize(steps, HERE / "cache", 3, 1.25)
at = []
for c in variants["rate1.0"]:
    o = c.with_name(c.stem + ".atempo.wav")
    if not o.exists():
        m.run("ffmpeg", "-v", "error", "-y", "-i", str(c), "-af", "atempo=1.5", str(o))
    at.append(o)
variants["atempo1.5"] = at
key = os.environ["DEEPGRAM_API_KEY"]
res = {}
for name, clips in variants.items():
    gap = b"\0\0" * int(0.6 * m.SR)
    pcm = bytearray(gap)
    for c in clips:
        with wave.open(str(c)) as w:
            assert w.getframerate() == m.SR, (c, w.getframerate())
            pcm += w.readframes(w.getnframes()) + gap
    out = HERE / f"{name}.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(m.SR); w.writeframes(bytes(pcm))
    req = urllib.request.Request("https://api.deepgram.com/v1/listen?model=nova-2&language=ru&punctuate=true&smart_format=false",
        data=out.read_bytes(), headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"})
    words = json.load(urllib.request.urlopen(req, timeout=120))["results"]["channels"][0]["alternatives"][0]["words"]
    heard = [t for w in words for t in m.tokens(w["word"])]
    by_say = m.align([s["say"] for s in steps], heard); by_sub = m.align([s["sub"] or s["say"] for s in steps], heard)
    rec = [round(max(sum(h is not None for h in a) / len(a), sum(h is not None for h in b) / len(b)), 2) for a, b in zip(by_say, by_sub)]
    secs = round(sum(m.wav_seconds(c) for c in clips), 2)
    res[name] = {"speech_s": secs, "recall": rec, "recall_min": min(rec), "recall_mean": round(sum(rec) / len(rec), 3),
                 "transcript": " ".join(w["word"] for w in words)}
    print(name, secs, rec, flush=True)
(HERE / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
