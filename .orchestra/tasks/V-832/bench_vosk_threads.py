import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
tts_home = Path.home() / ".local/share/orchestra-tts"
tts_python = tts_home / "venv/bin/python"
model_path = tts_home / "vosk-model-tts-ru-0.9-multi"

steps = []
for engine in ("html", "manim"):
    path = ROOT / ".orchestra/tasks/V-832/baseline" / engine
    timing_path = next(path.glob("*.timing.json"))
    data = json.loads(timing_path.read_text())
    steps.extend({"say": row["say"]} for row in data["steps"])
texts = [step["say"] for step in steps]

from vosk_tts import Model, Synth

t0 = time.perf_counter()
model = Model(model_path=str(model_path))
synth = Synth(model)
load_s = time.perf_counter() - t0

def make_audio(item):
    index, text = item
    audio = synth.synth_audio(text, speaker_id=1, speech_rate=1.15)
    if audio.size == 0:
        raise RuntimeError(f"empty audio for phrase {index}")
    return index, audio.shape[-1] / 22050

counts = [int(value) for value in os.environ.get("BENCH_WORKERS", "1,2,4").split(",")]
results = {"model_load_s": round(load_s, 3), "phrases": len(texts), "workers": {}}
make_audio((0, texts[0]))  # warm the loaded session; exclude this call from throughput timings
for count in counts:
    start = time.perf_counter()
    if count == 1:
        output = list(map(make_audio, enumerate(texts)))
    else:
        with ThreadPoolExecutor(max_workers=count) as pool:
            output = list(pool.map(make_audio, enumerate(texts)))
    elapsed = time.perf_counter() - start
    output.sort()
    results["workers"][str(count)] = {
        "wall_s": round(elapsed, 3),
        "audio_s": [round(seconds, 3) for _index, seconds in output],
        "order": [index for index, _seconds in output],
    }
print(json.dumps(results, ensure_ascii=False, indent=2))
