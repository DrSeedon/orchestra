import os, sys, time
from pathlib import Path
os.environ["COQUI_TOS_AGREED"] = "1"
import torch, soundfile as sf
torch.set_num_threads(6)
sys.path.insert(0, str(Path(__file__).parent))
from common import texts, Log
from TTS.api import TTS
root = Path(__file__).parents[1]
t0 = time.time(); tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu"); print("load_s", round(time.time()-t0,1), flush=True)
out = Path(sys.argv[1]); log = Log("xtts", out)
for name, kw in [("ref-m1", {"speaker_wav": str(root / "ref/ref_m1.wav")}), ("damien", {"speaker": "Damien Black"})]:
    for pid, text in texts(plus=False):
        t = time.time(); wav = tts.tts(text=text, language="ru", **kw); dt = time.time() - t
        path = out / f"xtts_{name}_{pid}.wav"; sf.write(path, wav, 24000)
        log.record(name, pid, path, dt, False)
