"""Синтез фраз Vosk TTS: JSON-список заданий на stdin → wav-файлы.

Запускается интерпретатором окружения TTS (`ORCHESTRA_TTS_PYTHON`), а не рантаймом
Orchestra: vosk-tts тянет onnxruntime и numpy, которых в рантайме нет.
Задание: {"text", "speaker", "rate", "out"}. Модель грузится один раз (~2 мин).
"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
from vosk_tts import Model, Synth  # noqa: E402

jobs = json.load(sys.stdin)
synth = Synth(Model(model_path=os.environ["ORCHESTRA_TTS_MODEL"]))
for job in jobs:
    tmp = job["out"] + ".part"
    synth.synth(job["text"], tmp, speaker_id=job["speaker"], speech_rate=job["rate"])
    os.replace(tmp, job["out"])
    print(f"tts: {job['out']}", file=sys.stderr, flush=True)
