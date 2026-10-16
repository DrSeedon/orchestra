import sys, time, wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import texts, Log
from piper import PiperVoice
root = Path(__file__).parents[1]
out = Path(sys.argv[1]); log = Log("piper", out)
for v in ["denis", "dmitri", "irina", "ruslan"]:
    voice = PiperVoice.load(str(root / f"models/piper/ru_RU-{v}-medium.onnx"))
    for pid, text in texts(plus=False):
        path = out / f"piper_{v}_{pid}.wav"
        t = time.time()
        with wave.open(str(path), "wb") as w:
            voice.synthesize_wav(text, w)
        log.record(v, pid, path, time.time() - t, False)
