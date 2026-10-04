import json
import os
from pathlib import Path
import sys
import wave

from vosk_tts import Model, Synth

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
phrases = json.loads(sys.stdin.read())
jobs = [
    {"id": row["id"], "variant": variant, "text": row[key]}
    for row in phrases
    for variant, key in (("control", "raw"), ("manual-plus", "manual"))
]
model = Model(model_path=os.environ["ORCHESTRA_TTS_MODEL"])
synth = Synth(model)
for item in jobs:
    target = OUT / f"{item['variant']}-{item['id']:02d}.wav"
    synth.synth(item["text"], str(target), speaker_id=1, speech_rate=1.15)
    print(f"{item['variant']} {item['id']:02d} {target.stat().st_size} bytes", file=sys.stderr, flush=True)
