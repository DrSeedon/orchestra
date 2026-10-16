import sys, time
from pathlib import Path
root = Path(__file__).parents[1]
sys.path.insert(0, str(root / "src/CosyVoice")); sys.path.insert(0, str(root / "src/CosyVoice/third_party/Matcha-TTS"))
sys.path.insert(0, str(Path(__file__).parent))
import torch, soundfile as sf
torch.set_num_threads(6)
from common import texts, Log
from huggingface_hub import snapshot_download
mdir = root / "models/cosy3"
snapshot_download("FunAudioLLM/Fun-CosyVoice3-0.5B-2512", local_dir=str(mdir),
                  ignore_patterns=["*.batch.onnx", "flow.decoder.estimator.fp32.onnx", "llm.rl.pt", "asset/*"])
from cosyvoice.cli.cosyvoice import AutoModel
t0 = time.time(); cv = AutoModel(model_dir=str(mdir)); print("load_s", round(time.time()-t0,1), flush=True)
prompt = "You are a helpful assistant.<|endofprompt|>" + open(root / "ref/ref_m1.txt").read()
out = Path(sys.argv[1]); log = Log("cosyvoice3", out)
for pid, text in texts(plus=False):
    t = time.time()
    chunks = [j["tts_speech"] for j in cv.inference_zero_shot(text, prompt, str(root / "ref/ref_m1_16k.wav"), stream=False)]
    dt = time.time() - t
    wav = torch.cat(chunks, dim=1).squeeze(0).numpy()
    path = out / f"cosyvoice3_ref-m1_{pid}.wav"; sf.write(path, wav, cv.sample_rate)
    log.record("ref-m1", pid, path, dt, False)
