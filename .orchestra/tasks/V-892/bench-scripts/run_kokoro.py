import json, sys, time
from pathlib import Path
import torch, soundfile as sf
torch.set_num_threads(6)
sys.path.insert(0, str(Path(__file__).parent))
from common import texts, Log
from huggingface_hub import snapshot_download
root = Path(__file__).parents[1]
repo = Path(snapshot_download("zaakirio/kokoro-ru", local_dir=str(root / "models/kokoro-ru"),
            allow_patterns=["*.pth", "voices/*.pt", "espeak-data/*", "ru_g2p.py", "kokoro-config.json", "config.json"]))
sys.path.insert(0, str(repo))
from ru_g2p import RuG2P
from kokoro import KModel
stressed = json.load(open(root / "stressed.json"))
g2p = RuG2P()
out = Path(sys.argv[1]); log = Log("kokoro-ru", out)
for ckpt, voices in [("kokoro-ru-v2-base.pth", ["sveta", "masha"]), ("kokoro-ru-v2-dima.pth", ["dima"])]:
    model = KModel(repo_id="zaakirio/kokoro-ru", config=str(repo / "config.json"), model=str(repo / ckpt)).eval()
    for v in voices:
        pack = torch.load(repo / f"voices/{v}.pt", map_location="cpu", weights_only=False)
        for pid, _ in texts():
            t = time.time()
            ipa, oov = g2p.phonemize_accented(stressed[pid])
            with torch.no_grad():
                audio = model(ipa, pack[len(ipa) - 1], 1.0, return_output=True).audio
            dt = time.time() - t
            path = out / f"kokoro-ru_{v}_{pid}.wav"; sf.write(path, audio.cpu().numpy(), 24000)
            log.record(v, pid, path, dt, True, {"stress_source": "ruaccent+manual", "oov": sorted(oov)})
