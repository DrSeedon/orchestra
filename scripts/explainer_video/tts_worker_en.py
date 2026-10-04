"""English voice-over with Kokoro-82M (kokoro-onnx): JSON job list on stdin → wav files.

Runs in its own venv (`ORCHESTRA_TTS_EN_PYTHON`): kokoro-onnx pulls onnxruntime and
espeak-ng phonemizer data that the Orchestra runtime does not carry.
Job: {"text", "voice", "rate", "out"}. Model loads once (~5 s).
"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import soundfile as sf  # noqa: E402
from kokoro_onnx import Kokoro  # noqa: E402

home = os.environ["ORCHESTRA_TTS_EN_HOME"]
kokoro = Kokoro(os.path.join(home, "kokoro-v1.0.onnx"), os.path.join(home, "voices-v1.0.bin"))
for job in json.load(sys.stdin):
    samples, rate = kokoro.create(job["text"], voice=job["voice"], speed=job["rate"], lang="en-us")
    tmp = job["out"] + ".part"
    sf.write(tmp, samples, rate, format="WAV")
    os.replace(tmp, job["out"])
    print(f"tts: {job['out']}", file=sys.stderr, flush=True)
