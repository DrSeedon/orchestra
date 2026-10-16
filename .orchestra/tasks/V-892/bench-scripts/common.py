import json, os, sys, time, wave
from pathlib import Path

PHRASES = json.load(open(Path(__file__).resolve().parents[1] / "phrases.json"))

def texts(plus=True):
    return [(p["id"], p["text"] if plus else p["text"].replace("+", "")) for p in PHRASES]

def wav_seconds(path):
    try:
        import soundfile as sf
        info = sf.info(str(path)); return info.frames / info.samplerate
    except ImportError:
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()

class Log:
    def __init__(self, model, out):
        self.model, self.out = model, Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.f = open(self.out / "timing.jsonl", "a")
    def record(self, voice, pid, path, synth_s, plus, extra=None):
        audio = wav_seconds(path)
        row = {"model": self.model, "voice": voice, "phrase": pid, "file": str(path), "synth_s": round(synth_s, 2),
               "audio_s": round(audio, 2), "rtf": round(synth_s / audio, 3) if audio else None, "plus_input": plus}
        row.update(extra or {})
        self.f.write(json.dumps(row, ensure_ascii=False) + "\n"); self.f.flush()
        print(json.dumps(row, ensure_ascii=False), flush=True)
