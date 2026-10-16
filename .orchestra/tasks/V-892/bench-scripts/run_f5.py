import json, sys, time, contextlib
from pathlib import Path
import torch, soundfile as sf
torch.set_num_threads(6)
sys.path.insert(0, str(Path(__file__).parent))
from common import texts, Log
from f5_tts.infer.utils_infer import load_model, load_vocoder, preprocess_ref_audio_text, infer_process
from f5_tts.model import DiT
root = Path(__file__).parents[1]
stressed = json.load(open(root / "stressed.json"))
with contextlib.redirect_stdout(sys.stderr):
    from ruaccent import RUAccent
    acc = RUAccent(); acc.load(omograph_model_size="turbo3.1", use_dictionary=True, tiny_mode=False, workdir=str(Path.home()/".local/share/orchestra-tts/ruaccent-model"))
ref_text = acc.process_all(open(root / "ref/ref_m1.txt").read())
CFG = dict(dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4)
models = {
  "f5-misha-v4": (root/"models/f5/misha/F5TTS_v1_Base_v4_winter/model_212000.safetensors", root/"models/f5/misha/F5TTS_v1_Base/vocab.txt"),
  "espeech-rlv2": (root/"models/f5/espeech/espeech_tts_rlv2.pt", root/"models/f5/espeech/vocab.txt"),
}
vocoder = load_vocoder()
out = Path(sys.argv[1]); log = Log("f5", out)
ref_audio, ref_text = preprocess_ref_audio_text(str(root / "ref/ref_m1.wav"), ref_text)
for name, (ckpt, vocab) in models.items():
    t0 = time.time(); model = load_model(DiT, CFG, str(ckpt), vocab_file=str(vocab)); print(name, "load_s", round(time.time()-t0,1), flush=True)
    for pid, _ in texts():
        t = time.time()
        wav, sr, _ = infer_process(ref_audio, ref_text, stressed[pid], model, vocoder, nfe_step=32, speed=1.0)
        dt = time.time() - t
        path = out / f"{name}_ref-m1_{pid}.wav"; sf.write(path, wav, sr)
        log.record(f"{name}/ref-m1", pid, path, dt, True, {"stress_source": "ruaccent+manual"})
