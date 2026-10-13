"""Синтез фраз Vosk TTS: JSON-список заданий на stdin → wav-файлы.

Запускается интерпретатором окружения TTS (`ORCHESTRA_TTS_PYTHON`), а не рантаймом
Orchestra: vosk-tts тянет onnxruntime и numpy, которых в рантайме нет.
Задание: {"index", "text", "speaker", "rate", "out"}. Модель грузится один раз, затем до
четырёх потоков пишут отдельные WAV-файлы; stdout выдаёт индексы по мере готовности.
"""
import json
import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")
from vosk_tts import Model, Synth  # noqa: E402

jobs = json.load(sys.stdin)
synth = Synth(Model(model_path=os.environ["ORCHESTRA_TTS_MODEL"]))
def synthesize(job):
    tmp = job["out"] + ".part"
    synth.synth(job["text"], tmp, speaker_id=job["speaker"], speech_rate=job["rate"])
    os.replace(tmp, job["out"])
    return job["index"]

with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
    futures = [pool.submit(synthesize, job) for job in jobs]
    for future in as_completed(futures):
        print(json.dumps({"index": future.result()}), flush=True)
