import json, sys, time
from pathlib import Path
import torch, soundfile as sf
sys.path.insert(0, str(Path(__file__).parent))
from common import texts, Log
torch.set_num_threads(6)
root = Path(__file__).parents[1]
stressed = json.load(open(root / "stressed.json"))
out = Path(sys.argv[1]); log = Log("silero", out)
def load(name):
    imp = torch.package.PackageImporter(str(root / f"models/silero/{name}.pt"))
    return imp.load_pickle("tts_models", "model")
m = load("v5_6_ru")
for spk in ["aidar", "baya", "kseniya", "eugene", "xenia"]:
    for pid, text in texts(plus=True):
        t = time.time()
        audio = m.apply_tts(text=text, speaker=spk, sample_rate=48000, put_accent=True, put_yo=True, put_stress_homo=True, put_yo_homo=True)
        dt = time.time() - t
        path = out / f"silero-v5_6_{spk}_{pid}.wav"; sf.write(path, audio.numpy(), 48000)
        log.record(f"v5_6_ru/{spk}", pid, path, dt, True)
m = load("v5_cis_base")
for spk in ["ru_dmitriy", "ru_igor", "ru_eduard", "ru_ekaterina"]:
    for pid, _ in texts():
        text = stressed[pid]
        t = time.time()
        audio = m.apply_tts(text=text, speaker=spk, sample_rate=48000)
        dt = time.time() - t
        path = out / f"silero-cis_{spk}_{pid}.wav"; sf.write(path, audio.numpy(), 48000)
        log.record(f"v5_cis_base/{spk}", pid, path, dt, True, {"stress_source": "ruaccent"})
