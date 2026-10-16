import os, sys
from pathlib import Path
sys.path.insert(0, "/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-tts/scripts/video_artifact")
import tts_worker_tera as w
snap = Path.home() / ".local/share/orchestra-tts/tera/hub/models--TeraSpace--TeraTTSv2/snapshots" / w.REVISION
os.environ["HF_MODULES_CACHE"] = str(snap.parents[3] / "modules")
from transformers import AutoModel
model = AutoModel.from_pretrained(str(snap), trust_remote_code=True, local_files_only=True, provider="CPUExecutionProvider", threads=6, diffusion_model="distilled", russian_stress=True)
w.patch_wordwise_stress(model)
text = "Начнём с биологии. Нейрон принимает сигналы через дендриты, копит заряд в ядре, а потом отправляет импульс по аксону."
model.save_wav(Path(sys.argv[1]), w.render_phrase(model, {"text": text, "voice": "ru_m1", "rate": 1.0, "index": 0}))
open(Path(sys.argv[1]).with_suffix(".txt"), "w").write(text)
