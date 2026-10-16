import sys, time
from pathlib import Path
import torch, soundfile as sf
torch.set_num_threads(6)
sys.path.insert(0, str(Path(__file__).parent))
from common import texts, Log
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
root = Path(__file__).parents[1]
t0 = time.time(); model = ChatterboxMultilingualTTS.from_pretrained(device="cpu"); print("load_s", round(time.time()-t0,1), flush=True)
out = Path(sys.argv[1]); log = Log("chatterbox-mtl", out)
for name, kw in [("ref-m1", {"audio_prompt_path": str(root / "ref/ref_m1.wav")}), ("default", {})]:
    for pid, text in texts(plus=False):
        t = time.time(); wav = model.generate(text, language_id="ru", **kw); dt = time.time() - t
        path = out / f"chatterbox-mtl_{name}_{pid}.wav"; sf.write(path, wav.squeeze(0).numpy(), model.sr)
        log.record(name, pid, path, dt, False)
