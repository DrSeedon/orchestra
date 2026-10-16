import os, sys, time
from pathlib import Path
sys.path.insert(0, "/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-tts/scripts/video_artifact")
sys.path.insert(0, str(Path(__file__).parent))
from common import texts, Log
import tts_worker_tera as w
snap = Path.home() / ".local/share/orchestra-tts/tera/hub/models--TeraSpace--TeraTTSv2/snapshots" / w.REVISION
os.environ["HF_MODULES_CACHE"] = str(snap.parents[3] / "modules")
from transformers import AutoModel
t0 = time.time()
model = AutoModel.from_pretrained(str(snap), trust_remote_code=True, local_files_only=True, provider="CPUExecutionProvider",
                                  threads=6, diffusion_model="distilled", russian_stress=True)
w.patch_wordwise_stress(model)
print("load_s", round(time.time() - t0, 1), flush=True)
out = Path(sys.argv[1]); log = Log("tera", out)
for voice in ["ru_m1", "ru_m5", "ru_f1", "ru_f2"]:
    for i, (pid, text) in enumerate(texts(plus=True)):
        t = time.time()
        audio = w.render_phrase(model, {"text": text, "voice": voice, "rate": 1.0, "index": i})
        dt = time.time() - t
        path = out / f"tera_{voice}_{pid}.wav"
        model.save_wav(path, audio)
        log.record(voice, pid, path, dt, True)
