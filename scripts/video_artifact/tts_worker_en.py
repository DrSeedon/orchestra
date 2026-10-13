"""English voice-over with Kokoro-82M (kokoro-onnx): JSON job list on stdin → wav files.

Runs in its own venv (`ORCHESTRA_TTS_EN_PYTHON`): kokoro-onnx pulls onnxruntime and
espeak-ng phonemizer data that the Orchestra runtime does not carry.
Job: {"text", "voice", "rate", "out"}. Model loads once (~5 s).
"""
import json
import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")
import soundfile as sf  # noqa: E402
from kokoro_onnx import Kokoro  # noqa: E402

home = os.environ["ORCHESTRA_TTS_EN_HOME"]
kokoro = Kokoro(os.path.join(home, "kokoro-v1.0.onnx"), os.path.join(home, "voices-v1.0.bin"))
jobs = json.load(sys.stdin)
def synthesize(job):
    samples, rate = kokoro.create(job["text"], voice=job["voice"], speed=job["rate"], lang="en-us")
    tmp = job["out"] + ".part"
    sf.write(tmp, samples, rate, format="WAV")
    os.replace(tmp, job["out"])
    return job["index"]

with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
    futures = [pool.submit(synthesize, job) for job in jobs]
    for future in as_completed(futures):
        print(json.dumps({"index": future.result()}), flush=True)
