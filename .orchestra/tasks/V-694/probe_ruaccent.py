import json
import os
from pathlib import Path
import sys

sys.path.append(
    os.environ.get(
        "ORCHESTRA_TTS_SITE",
        "/home/kesha/.local/share/orchestra-tts/venv/lib/python3.12/site-packages",
    ),
)

from ruaccent import RUAccent
from vosk_tts import Model, Synth

ROOT = Path(__file__).parent
OUT = ROOT / "samples" / "vosk"
MODEL = os.environ["ORCHESTRA_TTS_MODEL"]
accentizer = RUAccent()
accentizer.load(
    omograph_model_size="turbo3.1",
    use_dictionary=True,
    tiny_mode=False,
    device="CPU",
    workdir=str(ROOT / "samples" / "ruaccent-model"),
)
model = Model(model_path=MODEL)
synth = Synth(model)
phrases = json.loads(sys.stdin.read())
rows = []
for item in phrases:
    accented = accentizer.process_all(item["raw"])
    rows.append({"id": item["id"], "input": item["raw"], "ruaccent": accented})
    target = OUT / f"ruaccent-{item['id']:02d}.wav"
    synth.synth(accented, str(target), speaker_id=1, speech_rate=1.15)
    print(f"{item['id']:02d}\t{accented}\t{target.stat().st_size}", flush=True)
(ROOT / "samples" / "ruaccent-output.json").write_text(
    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
)
