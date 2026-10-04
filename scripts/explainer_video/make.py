"""Объясняющий ролик: сцена html-motion + озвучка (русская Vosk TTS или английская Kokoro, `--lang en`) → MP4, синхронно по фразам.

    uv run --frozen --project /home/kesha/orchestra python \
        /home/kesha/orchestra/scripts/explainer_video/make.py scene.html --out DIR

Сцена `.py` — Manim вместо html-motion: класс-наследник VoiceScene из manim_voice.py,
тот же договор STEPS; рендерит Manim из ~/.local/share/orchestra-manim.

Озвучка задаёт время, а не наоборот: у каждого шага `STEPS` есть фраза `say`, она
синтезируется первой, и длительность шага становится «вступление + фраза + пауза».
Поэтому смена состояния в начале шага совпадает с началом фразы по построению, а не
подгонкой. Подпись шага на экране — `sub`, если есть (транслитерация в `say` вроде «Дип Инфра»
на экране выглядит странно), иначе сама фраза. Сцена получает длительности через `window.voice?.(STEPS)` — строку сразу
после массива STEPS; без неё ролик не собирается (проверяется).

Результат в DIR: `<имя>.mp4` (1920×1080, H.264 + AAC), `<имя>.timing.json` (когда звучит
каждая фраза), `<имя>-contact.png` (кадры конца шагов для просмотра глазами) и, если
есть DEEPGRAM_API_KEY, `<имя>.check.json` — распознанный текст и сдвиг каждой фразы.

Ключи: --speaker 0..4 (1 — по умолчанию, 0–2 женские, 3 и 4 мужские), --rate 1.15 (темп: речь и паузы между
фразами; 1.0 — темп V-681), --fps 30,
--stills (только озвучка, тайминг и контакт-лист, без видео), --no-check.
Синтез кэшируется по тексту фразы: правка одной фразы пересинтезирует только её,
но первая загрузка модели занимает ~2 мин. Тяжёлое — запускать вне cgroup платформы.
"""
from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
import wave
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
TTS_HOME = Path(os.environ.get("ORCHESTRA_TTS_HOME", Path.home() / ".local/share/orchestra-tts"))
TTS_PYTHON = Path(os.environ.get("ORCHESTRA_TTS_PYTHON", TTS_HOME / "venv/bin/python"))
TTS_MODEL = Path(os.environ.get("ORCHESTRA_TTS_MODEL", TTS_HOME / "vosk-model-tts-ru-0.9-multi"))
# Английский голос — Kokoro-82M (Apache 2.0) через kokoro-onnx (MIT), своё окружение рядом.
TTS_EN_HOME = Path(os.environ.get("ORCHESTRA_TTS_EN_HOME", TTS_HOME / "en"))
TTS_EN_PYTHON = Path(os.environ.get("ORCHESTRA_TTS_EN_PYTHON", TTS_EN_HOME / "venv/bin/python"))
MANIM_HOME = Path(os.environ.get("ORCHESTRA_MANIM_HOME", Path.home() / ".local/share/orchestra-manim"))
MANIM_BIN = MANIM_HOME / "env/bin"
SR = 48000
VIEW = {"width": 1280, "height": 720}
SCALE = 1.5  # 1280×720 CSS-пикселей → кадр 1920×1080
LEAD = 0.35  # фраза вступает чуть позже смены состояния: глаз успевает за ухом
GAP = 0.55  # пауза после фразы до следующего шага
PRE, POST = 0.4, 1.6  # стоп-кадр до начала и после конца
# Vosk TTS падает на латинице и цифрах (KeyError в словаре фонем) — их пишут словами.
NOT_SPEAKABLE = re.compile(r"[A-Za-z0-9]")
# Kokoro читает английский, цифры и названия сам; кириллицу он произнести не может.
NOT_SPEAKABLE_EN = re.compile(r"[А-Яа-яЁё]")

VOICE_JS = """
window.__VOICE = %s;
window.voice = steps => {
  const v = window.__VOICE; if (!v) return;
  steps.forEach((s, i) => { s.d = v.d[i]; s.x = (s.sub ?? s.say).replace(/\\+/g, ""); });
  window.__VOICE_APPLIED = true;
};
"""


def fail(message: str) -> None:
    sys.exit(f"explainer_video: {message}")


def run(*argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def font_css() -> str:
    ranges = {
        "cyrillic": "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116",
        "latin": "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
                 "U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
    }
    rules = []
    for family, stem, weight in (("Manrope", "manrope", "400 800"), ("JetBrains Mono", "jetbrains-mono", "400 500")):
        for subset, urange in ranges.items():
            data = base64.b64encode((HERE / "fonts" / f"{stem}-{subset}.woff2").read_bytes()).decode()
            rules.append(
                f"@font-face{{font-family:'{family}';font-weight:{weight};"
                f"src:url(data:font/woff2;base64,{data}) format('woff2');unicode-range:{urange}}}"
            )
    return "\n".join(rules)


def open_scene(pw, scene: Path, voice: dict | None):
    browser = pw.chromium.launch()
    page = browser.new_page(viewport=VIEW, device_scale_factor=SCALE)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    if voice is not None:
        page.add_init_script(VOICE_JS % json.dumps(voice, ensure_ascii=False))
    page.goto(scene.resolve().as_uri())
    if errors:
        fail(f"ошибки JS в сцене: {errors}")
    page.add_style_tag(content=font_css() + "\n" + (HERE / "video.css").read_text())
    page.evaluate("document.fonts.ready")
    page.evaluate("P.seek(P.t)")  # перерисовать подписи после смены шрифта и вёрстки
    return browser, page


# ---------- озвучка ----------

def read_steps(scene: Path, lang: str) -> list[dict]:
    with sync_playwright() as pw:
        browser, page = open_scene(pw, scene, None)
        steps = page.evaluate("STEPS.map(s => ({t: s.t, say: s.say || '', sub: s.sub || null, hold: s.hold ?? null}))")
        browser.close()
    return check_steps(steps, lang)


def check_steps(steps: list[dict], lang: str) -> list[dict]:
    for i, step in enumerate(steps, 1):
        if not step["say"].strip():
            fail(f"шаг {i} «{step['t']}» без фразы say")
        if lang == "en":
            if bad := sorted(set(NOT_SPEAKABLE_EN.findall(step["say"]))):
                fail(f"шаг {i}: в say есть {''.join(bad)} — английский голос не читает кириллицу")
        elif bad := sorted(set(NOT_SPEAKABLE.findall(step["say"]))):
            fail(f"шаг {i}: в say есть {''.join(bad)} — латиницу и цифры пиши словами по-русски")
    return steps


MANIM_STEPS_JS = """
import importlib.util, json, sys
sys.path.insert(0, sys.argv[2])
spec = importlib.util.spec_from_file_location("scene", sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
from manim_voice import VoiceScene
found = [c for c in vars(mod).values() if isinstance(c, type) and issubclass(c, VoiceScene) and c.__module__ == "scene"]
if len(found) != 1:
    sys.exit(f"в файле должна быть ровно одна сцена VoiceScene, найдено {[c.__name__ for c in found]}")
print(json.dumps({"cls": found[0].__name__, "steps": [{"t": s["t"], "say": s.get("say", ""), "sub": s.get("sub"),
                  "hold": s.get("hold")} for s in found[0].STEPS]}, ensure_ascii=False))
"""


def manim_steps(scene: Path, lang: str) -> tuple[str, list[dict]]:
    if not (MANIM_BIN / "manim").exists():
        fail(f"нет Manim: {MANIM_BIN}/manim — установка в SKILL explainer-video")
    got = json.loads(run(str(MANIM_BIN / "python"), "-c", MANIM_STEPS_JS, str(scene.resolve()), str(HERE),
                         capture_output=True, text=True).stdout)
    return got["cls"], check_steps(got["steps"], lang)


def mark_stress(steps: list[dict], lang: str, enabled: bool) -> list[dict]:
    if lang != "ru" or not enabled:
        return steps
    if not TTS_PYTHON.exists():
        fail(f"нет окружения TTS: {TTS_PYTHON} — установка в SKILL explainer-video")
    try:
        result = subprocess.run(
            [str(TTS_PYTHON), str(HERE / "tts_worker_stress.py")],
            input=json.dumps([step["say"] for step in steps], ensure_ascii=False),
            capture_output=True, text=True, check=False,
            env={**os.environ, "ORCHESTRA_TTS_HOME": str(TTS_HOME)},
        )
    except OSError as exc:
        fail(f"не удалось запустить RUAccent в {TTS_PYTHON}: {exc}")
    if result.returncode:
        if "RUACCENT_NOT_INSTALLED" in result.stderr:
            fail(f"не установлен RUAccent в {TTS_PYTHON}; установка: uv pip install --python {TTS_PYTHON} "
                 "ruaccent==1.5.8.3 transformers==4.57.1 tokenizers==0.22.2 huggingface-hub==0.36.0")
        fail(f"ошибка RUAccent worker: {result.stderr.strip() or result.returncode}")
    try:
        accented = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"RUAccent worker вернул некорректный JSON: {exc}")
    if not isinstance(accented, list) or len(accented) != len(steps) or not all(isinstance(x, str) for x in accented):
        fail("RUAccent worker вернул неверное число или тип размеченных фраз")
    for step, text in zip(steps, accented, strict=True):
        step["_tts_text"] = text
    return steps


def synthesize(steps: list[dict], cache: Path, speaker: int, rate: float, voice: str = "") -> list[Path]:
    """Каждая фраза → wav 48 кГц моно без тишины по краям (кэш по тексту и голосу).

    `voice` — имя голоса Kokoro: английская озвучка вместо русской Vosk."""
    cache.mkdir(parents=True, exist_ok=True)
    trimmed, jobs = [], []
    for step in steps:
        engine = f"kokoro-v1.0|{voice}" if voice else f"{speaker}|{TTS_MODEL.name}"
        text = step.get("_tts_text", step["say"])
        key = hashlib.sha1(f"{text}|{rate}|{engine}".encode()).hexdigest()[:16]
        raw, cut = cache / f"{key}.raw.wav", cache / f"{key}.wav"
        trimmed.append(cut)
        if not cut.exists() and not raw.exists():
            jobs.append({"text": text, "speaker": speaker, "voice": voice, "rate": rate, "out": str(raw)})
    if jobs and voice:
        if not TTS_EN_PYTHON.exists() or not (TTS_EN_HOME / "kokoro-v1.0.onnx").exists():
            fail(f"нет английского TTS: {TTS_EN_PYTHON} и {TTS_EN_HOME}/kokoro-v1.0.onnx — установка в SKILL explainer-video")
        print(f"синтез {len(jobs)} фраз (Kokoro, {voice})…", flush=True)
        run(str(TTS_EN_PYTHON), str(HERE / "tts_worker_en.py"), input=json.dumps(jobs).encode(),
            env={**os.environ, "ORCHESTRA_TTS_EN_HOME": str(TTS_EN_HOME)})
    elif jobs:
        if not TTS_PYTHON.exists() or not (TTS_MODEL / "model.onnx").exists():
            fail(f"нет окружения TTS: {TTS_PYTHON} и {TTS_MODEL}/model.onnx — установка в SKILL explainer-video")
        print(f"синтез {len(jobs)} фраз (загрузка модели ~2 мин)…", flush=True)
        run(str(TTS_PYTHON), str(HERE / "tts_worker.py"), input=json.dumps(jobs).encode(),
            env={**os.environ, "ORCHESTRA_TTS_MODEL": str(TTS_MODEL)})
    edge = "silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.03"
    for cut in trimmed:
        if not cut.exists():
            raw = cut.with_suffix(".raw.wav")
            run("ffmpeg", "-v", "error", "-y", "-i", str(raw),
                "-af", f"{edge},areverse,{edge},areverse", "-ar", str(SR), "-ac", "1",
                "-c:a", "pcm_s16le", str(cut))
    return trimmed


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def plan(steps: list[dict], clips: list[Path], rate: float) -> dict:
    rows, at = [], 0.0
    for step, clip in zip(steps, clips, strict=True):
        length = wav_seconds(clip)
        # Паузы ускоряются вместе с речью, иначе при rate 1.5 ролик короче лишь в 1.4 раза;
        # hold — время досмотреть итог, его темп не трогает.
        lead = LEAD / rate
        d = round(lead + length + (step["hold"] if step["hold"] is not None else GAP / rate), 3)
        rows.append({"title": step["t"], "say": step["say"], "sub": step["sub"], "step_start": round(at, 3),
                     "phrase_start": round(at + lead, 3), "phrase_end": round(at + lead + length, 3), "d": d})
        at += d
    return {"steps": rows, "T": round(at, 3), "pre": PRE, "post": POST}


def voice_track(timing: dict, clips: list[Path], out: Path) -> None:
    """Фразы раскладываются по своим местам в тишине; шаги не перекрываются, поэтому без микширования."""
    total = round((PRE + timing["T"] + POST) * SR)
    pcm = bytearray(total * 2)
    for row, clip in zip(timing["steps"], clips, strict=True):
        with wave.open(str(clip)) as w:
            data = w.readframes(w.getnframes())
        at = round((PRE + row["phrase_start"]) * SR) * 2
        pcm[at:at + len(data)] = data[: len(pcm) - at]
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(pcm))


# ---------- кадры ----------

def render(scene: Path, timing: dict, out: Path, name: str, fps: int, video: bool, jobs: int) -> None:
    voice = {"d": [row["d"] for row in timing["steps"]]}
    frames_dir = out / "frames" / name
    frames_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser, page = open_scene(pw, scene, voice)
        applied = page.evaluate("[window.__VOICE_APPLIED === true, P.T, STEPS.map(s => s.d)]")
        if not applied[0] or abs(applied[1] - timing["T"]) > 1e-6:
            fail("сцена не приняла длительности озвучки: после `const STEPS = [...]` нужна строка "
                 "`window.voice?.(STEPS);` до кода плеера")
        stills = []
        for i, row in enumerate(timing["steps"]):
            t = row["step_start"] + row["d"] - 0.05
            page.evaluate(f"P.seek({t})")
            path = frames_dir / f"step{i + 1:02d}.png"
            page.screenshot(path=str(path))
            stills.append(path)
        tile = f"tile=3x{(len(stills) + 2) // 3}"
        run("ffmpeg", "-v", "error", "-y", "-pattern_type", "glob", "-i", str(frames_dir / "step*.png"),
            "-vf", f"scale=640:-1,{tile}", "-frames:v", "1", str(out / f"{name}-contact.png"))
        browser.close()
    if not video:
        return
    # Кадр — чистая функция t, поэтому куски ролика снимаются параллельно и склеиваются без
    # швов. Снимок 1920×1080 стоит ~0.35 с: в один поток 70-секундный ролик писался 25 мин.
    total = round((PRE + timing["T"] + POST) * fps)
    times = [min(max(k / fps - PRE, 0.0), timing["T"]) for k in range(total)]
    size = -(-total // jobs)
    parts = [(scene, voice, times[i:i + size], str(out / f".{name}.part{n:02d}.mp4"), fps)
             for n, i in enumerate(range(0, total, size))]
    with ProcessPoolExecutor(len(parts), mp_context=get_context("spawn")) as pool:
        list(pool.map(render_part, parts))
    listing = out / f".{name}.parts.txt"
    listing.write_text("".join(f"file '{Path(part[3]).name}'\n" for part in parts))
    run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", str(out / f"{name}.video.mp4"))
    for part in parts:
        Path(part[3]).unlink()
    listing.unlink()


def render_part(args) -> None:
    scene, voice, times, path, fps = args
    ff = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-f", "image2pipe", "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", path],
        stdin=subprocess.PIPE)
    with sync_playwright() as pw:
        browser, page = open_scene(pw, scene, voice)
        last_t, shot = None, b""
        for t in times:
            if t != last_t:
                page.evaluate(f"P.seek({t})")
                shot = page.screenshot(type="png", animations="allow")
                last_t = t
            ff.stdin.write(shot)
        browser.close()
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError(f"ffmpeg не собрал кусок {path}")


def render_manim(scene: Path, cls: str, timing: dict, out: Path, name: str, fps: int, video: bool) -> None:
    """Manim сам пишет MP4; длительности шагов получает через EXPLAINER_VOICE (см. manim_voice.py).
    --stills тоже рендерит, но в 480p: кадр Manim нельзя снять без проигрыша сцены до него."""
    media = out / ".manim"
    quality = ["-r", "1920,1080", "--fps", str(fps)] if video else ["-ql"]
    voice = {"d": [row["d"] for row in timing["steps"]], "pre": PRE, "post": POST}
    run(str(MANIM_BIN / "manim"), "render", *quality, "--media_dir", str(media), "-o", name,
        str(scene.resolve()), cls,
        env={**os.environ, "EXPLAINER_VOICE": json.dumps(voice), "PYTHONPATH": str(HERE),
             "PATH": f"{MANIM_BIN}:{os.environ['PATH']}"})
    rendered = max(media.glob(f"videos/**/{name}.mp4"), key=lambda p: p.stat().st_mtime)
    frames_dir = out / "frames" / name
    frames_dir.mkdir(parents=True, exist_ok=True)
    for i, row in enumerate(timing["steps"]):
        t = PRE + row["step_start"] + row["d"] - 0.1
        run("ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(rendered), "-frames:v", "1",
            str(frames_dir / f"step{i + 1:02d}.png"))
    tile = f"tile=3x{(len(timing['steps']) + 2) // 3}"
    run("ffmpeg", "-v", "error", "-y", "-pattern_type", "glob", "-i", str(frames_dir / "step*.png"),
        "-vf", f"scale=640:-1,{tile}", "-frames:v", "1", str(out / f"{name}-contact.png"))
    if video:
        rendered.replace(out / f"{name}.video.mp4")


def mux(out: Path, name: str) -> Path:
    mp4 = out / f"{name}.mp4"
    run("ffmpeg", "-v", "error", "-y", "-i", str(out / f"{name}.video.mp4"), "-i", str(out / f"{name}.voice.wav"),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000", "-ac", "2", "-c:a", "aac", "-b:a", "160k",
        "-shortest", "-movflags", "+faststart", str(mp4))
    (out / f"{name}.video.mp4").unlink()
    return mp4


# ---------- проверка распознаванием ----------

def tokens(text: str) -> list[str]:
    """Слова для сверки с распознанным: регистр, ё/э → е, «7 680» → «7680», граница
    кириллицы и латиницы — граница слова (Deepgram склеивает «иstreamlake»). Сравнение по
    первым 5 знакам гасит падежи («кеша»/«кешу»)."""
    text = text.lower().replace("+", "").replace("ё", "е").replace("э", "е")
    text = re.sub(r"(?<=\d) (?=\d{3}\b)", "", text)
    text = re.sub(r"(?<=[а-я])(?=[a-z0-9])|(?<=[a-z0-9])(?=[а-я])", " ", text)
    return [w[:5] for w in re.findall(r"[a-zа-я0-9]+", text)]


def align(phrases: list[str], heard: list[str]) -> list[list[int | None]]:
    """Для каждого слова каждой фразы — индекс распознанного слова или None."""
    planned = [(i, w) for i, phrase in enumerate(phrases) for w in tokens(phrase)]
    match: dict[int, int] = {}
    matcher = difflib.SequenceMatcher(None, [w for _i, w in planned], heard, autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            match[block.a + k] = block.b + k
    return [[match.get(k) for k, (i, _w) in enumerate(planned) if i == n] for n in range(len(phrases))]


def voice_onsets(mp4: Path) -> list[float]:
    """Где в итоговом MP4 (после AAC и loudnorm) кончается тишина — фактические начала фраз."""
    log = run("ffmpeg", "-v", "info", "-i", str(mp4), "-vn", "-af", "silencedetect=noise=-40dB:d=0.25",
              "-f", "null", "-", capture_output=True, text=True).stderr
    return [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]


def check(out: Path, name: str, timing: dict, key: str, lang: str = "ru") -> dict:
    """Deepgram nova-2 по итоговому MP4: дословность каждой фразы и сдвиг её начала от плана."""
    audio = run("ffmpeg", "-v", "error", "-i", str(out / f"{name}.mp4"), "-vn", "-ac", "1", "-ar", "16000",
                "-f", "wav", "-", capture_output=True).stdout
    request = urllib.request.Request(
        f"https://api.deepgram.com/v1/listen?model=nova-2&language={lang}&punctuate=true&smart_format=false",
        data=audio, headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"})
    with urllib.request.urlopen(request, timeout=120) as response:
        words = json.load(response)["results"]["channels"][0]["alternatives"][0]["words"]
    # Deepgram пишет числа цифрами, а латинские названия — латиницей, поэтому фраза
    # сверяется дважды: как произнесена (`say`) и как написана на экране (`sub`).
    heard_words = []  # распознанное слово → его индекс в words (слово может дробиться)
    for n, w in enumerate(words):
        heard_words += [(t, n) for t in tokens(w["word"])]
    heard = [t for t, _n in heard_words]
    by_say = align([row["say"] for row in timing["steps"]], heard)
    by_sub = align([row["sub"] or row["say"] for row in timing["steps"]], heard)
    onsets = voice_onsets(out / f"{name}.mp4")
    rows = []
    for row, say_hits, sub_hits in zip(timing["steps"], by_say, by_sub, strict=True):
        recall = lambda hits: sum(h is not None for h in hits) / len(hits)  # noqa: E731
        hits = max(say_hits, sub_hits, key=recall)
        first = next((h for h in (say_hits[0], sub_hits[0]) if h is not None), None)
        start = words[heard_words[first][1]]["start"] if first is not None else None
        # Первое слово записи Deepgram иногда ставит на 0.0 при тишине перед ним: это не сдвиг.
        if start == 0.0:
            start = None
        rows.append({
            "say": row["say"],
            "heard": " ".join(dict.fromkeys(words[heard_words[h][1]]["word"] for h in hits if h is not None)),
            "recall": round(recall(hits), 2),
            "planned_start": round(PRE + row["phrase_start"], 2),
            "heard_start": start,
            "offset_s": round(start - (PRE + row["phrase_start"]), 2) if start is not None else None,
            "onset_offset_s": min((round(o - (PRE + row["phrase_start"]), 2) for o in onsets), key=abs, default=None),
        })
    offsets = [abs(r["offset_s"]) for r in rows if r["offset_s"] is not None]
    onset_offsets = [abs(r["onset_offset_s"]) for r in rows if r["onset_offset_s"] is not None]
    report = {
        "transcript": " ".join(w["word"] for w in words),
        "recall_min": min(r["recall"] for r in rows),
        "offset_max_abs_s": max(offsets) if offsets else None,
        "onset_offset_max_abs_s": max(onset_offsets) if onset_offsets else None,
        "phrases": rows,
        "words": [[w["word"], w["start"], w["end"]] for w in words],
    }
    (out / f"{name}.check.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--speaker", type=int, default=1)
    ap.add_argument("--lang", choices=["ru", "en"], default="ru",
                    help="en — английская озвучка Kokoro вместо русской Vosk")
    ap.add_argument("--voice", default="af_heart", help="голос Kokoro для --lang en (am_michael — мужской)")
    ap.add_argument("--rate", type=float, default=1.15)
    ap.add_argument("--no-stress", action="store_true", help="не запускать автоматическую разметку ударений RUAccent")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--jobs", type=int, default=max(1, min(6, (os.cpu_count() or 2) - 2)),
                    help="параллельных Chromium при записи")
    ap.add_argument("--stills", action="store_true", help="без видео: тайминг и контакт-лист")
    ap.add_argument("--no-check", action="store_true")
    ap.add_argument("--check-only", action="store_true", help="только проверить готовый MP4")
    args = ap.parse_args()
    out, name = args.out, args.scene.stem
    out.mkdir(parents=True, exist_ok=True)

    manim = args.scene.suffix == ".py"
    if manim:
        cls, steps = manim_steps(args.scene, args.lang)
    else:
        steps = read_steps(args.scene, args.lang)
    steps = mark_stress(steps, args.lang, enabled=not args.no_stress)
    clips = synthesize(steps, out / ".tts-cache", args.speaker, args.rate,
                       voice=args.voice if args.lang == "en" else "")
    timing = plan(steps, clips, args.rate)
    (out / f"{name}.timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1))
    for row in timing["steps"]:
        print(f"  {row['phrase_start']:6.2f}–{row['phrase_end']:6.2f}  шаг {row['d']:5.2f} с  {row['say']}")
    print(f"длина ролика {PRE + timing['T'] + POST:.1f} с")
    if not args.check_only:
        voice_track(timing, clips, out / f"{name}.voice.wav")
        if manim:
            render_manim(args.scene, cls, timing, out, name, args.fps, video=not args.stills)
        else:
            render(args.scene, timing, out, name, args.fps, video=not args.stills, jobs=args.jobs)
        print(out / f"{name}-contact.png")
        if args.stills:
            return
        mp4 = mux(out, name)
        print(mp4, f"{mp4.stat().st_size / 1e6:.1f} МБ")
    key = os.environ.get("DEEPGRAM_API_KEY")
    if args.no_check or not key:
        print("проверка распознаванием пропущена" + ("" if key else ": нет DEEPGRAM_API_KEY"))
        return
    report = check(out, name, timing, key, args.lang)
    for r in report["phrases"]:
        print(f"  recall {r['recall']:.2f}  сдвиг слова {r['offset_s']}  звука {r['onset_offset_s']}  {r['say']}\n      слышно: {r['heard']}")
    print(f"минимальная дословность {report['recall_min']}, наибольший сдвиг: первого слова "
          f"{report['offset_max_abs_s']} с, начала звука {report['onset_offset_max_abs_s']} с")


if __name__ == "__main__":
    main()
