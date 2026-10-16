import json, os, sys, time, contextlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-tts/scripts/video_artifact")
from common import texts, Log
from tts_worker_stress import stress_text
home = Path.home() / ".local/share/orchestra-tts"
with contextlib.redirect_stdout(sys.stderr):
    from ruaccent import RUAccent
    acc = RUAccent(); acc.load(omograph_model_size="turbo3.1", use_dictionary=True, tiny_mode=False, device="CPU", workdir=str(home / "ruaccent-model"))
stressed = [(pid, stress_text(t, acc)) for pid, t in texts(plus=True)]
json.dump(dict(stressed), open(Path(__file__).parents[1] / "stressed.json", "w"), ensure_ascii=False, indent=1)
from vosk_tts import Model, Synth
synth = Synth(Model(model_path=str(home / "vosk-model-tts-ru-0.9-multi")))
out = Path(sys.argv[1]); log = Log("vosk", out)
for spk in range(5):
    for pid, text in stressed:
        path = out / f"vosk_spk{spk}_{pid}.wav"
        t = time.time(); synth.synth(text, str(path), speaker_id=spk, speech_rate=1.0); dt = time.time() - t
        log.record(f"spk{spk}", pid, path, dt, True)
