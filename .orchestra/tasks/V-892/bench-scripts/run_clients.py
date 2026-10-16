"""Free no-account sources: official HF demo Spaces (GPU, vendor-hosted) and Edge read-aloud."""
import asyncio, json, shutil, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import texts
from gradio_client import Client, handle_file
root = Path(__file__).parents[1]
out = root / "out/clients"; out.mkdir(parents=True, exist_ok=True)
log = open(out / "clients.jsonl", "a")
ref = str(root / "ref/ref_m1.wav"); ref_text = open(root / "ref/ref_m1.txt").read()
which = sys.argv[1:]

def save(src, name, meta):
    dst = out / f"{name}.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), str(dst)], check=True)
    meta.update(file=str(dst)); log.write(json.dumps(meta, ensure_ascii=False) + "\n"); log.flush(); print(meta, flush=True)

def run(tag, fn):
    for pid, text in texts(plus=False):
        if (out / f"{tag}_{pid}.wav").exists():
            continue
        t = time.time()
        try:
            res = fn(text)
            path = res[0] if isinstance(res, (list, tuple)) else res
            if isinstance(path, dict): path = path.get("path") or path.get("name")
            save(path, f"{tag}_{pid}", {"source": tag, "phrase": pid, "wall_s": round(time.time() - t, 1)})
        except Exception as e:
            print(tag, pid, "ERROR", repr(e)[:400], flush=True)
            log.write(json.dumps({"source": tag, "phrase": pid, "error": repr(e)[:400]}, ensure_ascii=False) + "\n")

if "eleven" in which:
    c = Client("elevenlabs/tts", verbose=False)
    for voice, tag in [("Daniel - Steady Broadcaster", "elevenlabs-mv2-space_daniel"), ("Alice - Clear, Engaging Educator", "elevenlabs-mv2-space_alice")]:
        run(tag, lambda t: c.predict(t, voice, fn_index=0))
if "tera" in which:
    c = Client("TeraTTS/TTS", verbose=False)
    run("tera-teacher-space_ru_m1", lambda t: c.predict(f"<ru>{t}</ru>", "ru_m1", "teacher", "full", 1.0, api_name="/synthesize"))
if "qwen" in which:
    c = Client("Qwen/Qwen3-TTS", verbose=False)
    run("qwen3-1.7b-space_ref-m1", lambda t: c.predict(handle_file(ref), ref_text, t, "Russian", False, "1.7B", api_name="/generate_voice_clone"))
    run("qwen3-1.7b-space_design", lambda t: c.predict(t, "Russian", "Спокойный мужской голос лектора, чёткая дикция, ровный темп, научно-популярная подача.", api_name="/generate_voice_design"))
if "cosy" in which:
    c = Client("FunAudioLLM/Fun-CosyVoice3-0.5B", verbose=False)
    run("cosyvoice3-space_ref-m1", lambda t: c.predict(t, "zero_shot", ref_text, handle_file(ref), None, "You are a helpful assistant. 请用广东话表达。<|endofprompt|>", 0, False, api_name="/generate_audio"))
if "edge" in which:
    import edge_tts
    for voice in ["ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural"]:
        tag = f"edge-azure_{voice.split('-')[2].replace('Neural','').lower()}"
        def fn(t, voice=voice):
            p = out / "tmp.mp3"; asyncio.run(edge_tts.Communicate(t, voice).save(str(p))); return str(p)
        run(tag, fn)
