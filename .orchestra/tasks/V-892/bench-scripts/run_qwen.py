import sys, time
from pathlib import Path
import torch, soundfile as sf
torch.set_num_threads(6)
sys.path.insert(0, str(Path(__file__).parent))
from common import texts, Log
from qwen_tts import Qwen3TTSModel
root = Path(__file__).parents[1]
out = Path(sys.argv[1]); log = Log("qwen3-tts", out)
ref_text = open(root / "ref/ref_m1.txt").read()
runs = [("Qwen/Qwen3-TTS-12Hz-0.6B-Base", "0.6b-base", [("ref-m1", None)]),
        ("Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice", "0.6b-cv", [("ryan", "Ryan"), ("serena", "Serena")]),
        ("Qwen/Qwen3-TTS-12Hz-1.7B-Base", "1.7b-base", [("ref-m1", None)])]
for repo, tag, voices in runs:
    t0 = time.time(); model = Qwen3TTSModel.from_pretrained(repo, device_map="cpu", dtype=torch.float32); print(tag, "load_s", round(time.time()-t0,1), flush=True)
    for vname, spk in voices:
        for pid, text in texts(plus=False):
            t = time.time()
            if spk is None:
                wavs, sr = model.generate_voice_clone(text=text, language="Russian", ref_audio=str(root / "ref/ref_m1.wav"), ref_text=ref_text)
            else:
                wavs, sr = model.generate_custom_voice(text=text, language="Russian", speaker=spk)
            dt = time.time() - t
            path = out / f"qwen3-{tag}_{vname}_{pid}.wav"; sf.write(path, wavs[0], sr)
            log.record(f"{tag}/{vname}", pid, path, dt, False)
    del model
