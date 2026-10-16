import json, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import texts, Log
root = Path(__file__).parents[1]; fs = root / "src/fish-speech"; ck = root / "models/s2-pro"
out = Path(sys.argv[1]).resolve(); log = Log("fish-s2-pro", out)
ref_text = open(root / "ref/ref_m1.txt").read()
for pid, text in texts(plus=False):
    wav = out / f"fish-s2-pro_ref-m1_{pid}.wav"
    t = time.time()
    r = subprocess.run([str(root / "venvs/fish/bin/python"), "fish_speech/models/text2semantic/inference.py", "--checkpoint-path", str(ck),
                        "--device", "cpu", "--prompt-audio", str(root / "ref/ref_m1.wav"), "--prompt-text", ref_text,
                        "--text", text, "--output", str(wav), "--output-dir", str(out / "work")], cwd=fs, capture_output=True, text=True)
    dt = time.time() - t
    print(r.stdout[-1500:], r.stderr[-3000:], flush=True)
    if r.returncode or not wav.exists():
        print("FAILED", pid, r.returncode, flush=True); break
    log.record("ref-m1", pid, wav, dt, False, {"includes_model_load": True})
