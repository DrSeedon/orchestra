"""Build the local, mixed-language voice samples with the explainer-video renderer."""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parent
SCENE = TASK / "voice-samples.html"
OUT = TASK
MAKE_FILE = Path(os.environ.get("EXPLAINER_MAKE", ""))
if not MAKE_FILE.is_file():
    raise SystemExit("EXPLAINER_MAKE must point to the V-686 make.py with Kokoro support")
spec = importlib.util.spec_from_file_location("explainer_make", MAKE_FILE)
make = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = make
spec.loader.exec_module(make)


def scene_steps():
    with make.sync_playwright() as pw:
        browser, page = make.open_scene(pw, SCENE, None)
        steps = page.evaluate("STEPS.map(s => ({...s, d: undefined}))")
        browser.close()
    if len(steps) != 8:
        raise RuntimeError(f"expected 8 sample steps, got {len(steps)}")
    return steps


def synthesize(steps):
    cache = OUT / ".tts-cache"
    cache.mkdir(exist_ok=True)
    jobs_ru, jobs_en = [], []
    clips = []
    for i, step in enumerate(steps, 1):
        raw = cache / f"sample-{i:02d}.raw.wav"
        cut = cache / f"sample-{i:02d}.wav"
        clips.append(cut)
        if cut.exists() or raw.exists():
            continue
        job = {"text": step["say"], "rate": 1.25, "out": str(raw)}
        if step["lang"] == "ru":
            job["speaker"] = step["speaker"]
            jobs_ru.append(job)
        else:
            job["voice"] = step["voice"]
            jobs_en.append(job)
    if jobs_ru:
        make.run(str(make.TTS_PYTHON), str(make.HERE / "tts_worker.py"),
                 input=json.dumps(jobs_ru, ensure_ascii=False).encode(),
                 env={**os.environ, "ORCHESTRA_TTS_MODEL": str(make.TTS_MODEL)})
    if jobs_en:
        make.run(str(make.TTS_EN_PYTHON), str(make.HERE / "tts_worker_en.py"),
                 input=json.dumps(jobs_en, ensure_ascii=False).encode(),
                 env={**os.environ, "ORCHESTRA_TTS_EN_HOME": str(make.TTS_EN_HOME)})
    edge = "silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.03"
    for src, dst in zip((cache / f"sample-{i:02d}.raw.wav" for i in range(1, 9)), clips):
        if dst.exists():
            continue
        make.run("ffmpeg", "-v", "error", "-y", "-i", str(src),
                 "-af", f"{edge},areverse,{edge},areverse", "-ar", str(make.SR), "-ac", "1",
                 "-c:a", "pcm_s16le", str(dst))
    return clips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", action="store_true", help="synthesize, time, and render contact sheet only")
    args = ap.parse_args()
    steps = scene_steps()
    print("voices: " + ", ".join(s["voice_id"] for s in steps), flush=True)
    clips = synthesize(steps)
    timing = make.plan(steps, clips, 1.25)
    (OUT / "voice-samples.timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1))
    make.voice_track(timing, clips, OUT / "voice-samples.voice.wav")
    make.render(SCENE, timing, OUT, "voice-samples", fps=30, video=not args.stills, jobs=6)
    if args.stills:
        return
    mp4 = make.mux(OUT, "voice-samples")
    print(f"MP4: {mp4} ({mp4.stat().st_size / 1e6:.1f} MB)", flush=True)
    print(f"duration: {make.PRE + timing['T'] + make.POST:.1f}s", flush=True)


if __name__ == "__main__":
    main()
