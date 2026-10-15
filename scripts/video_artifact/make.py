"""Объясняющий ролик: анимированная HTML-сцена или Manim + локальная озвучка → MP4, синхронно по фразам.

    uv run --frozen --project /home/kesha/orchestra python \
        /home/kesha/orchestra/scripts/video_artifact/make.py scene.html --out DIR

Сцена `.py` — Manim вместо HTML-анимации: класс-наследник VoiceScene из manim_voice.py,
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

Ключи: --speaker 0..4 (1 — по умолчанию, 0–2 женские, 3 и 4 мужские), --rate 1.0 (темп: речь и паузы между
фразами; 1.0 — темп V-681), --fps 30,
--stills (только озвучка, тайминг и контакт-лист, без видео), --stress-only (только разметка
ударений RUAccent: `<имя>.stress.txt` и вывод по фразам, без синтеза), --no-check.
Синтез кэшируется по тексту фразы: правка одной фразы пересинтезирует только её,
но первая загрузка модели занимает ~2 мин. Тяжёлое — запускать вне cgroup платформы.
"""
from __future__ import annotations

import argparse
import base64
import difflib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import unicodedata
import wave
from contextlib import contextmanager
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from multiprocessing import get_context
from pathlib import Path

from playwright.sync_api import sync_playwright
from video_text import UnsupportedVoskSymbol, normalize_vosk_text

HERE = Path(__file__).resolve().parent
SOUND_HOME = Path.home() / ".local/share/orchestra-sfx"
SOUND_SCRIPTS = HERE / "sound"
UV_BIN = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
TTS_HOME = Path(os.environ.get("ORCHESTRA_TTS_HOME", Path.home() / ".local/share/orchestra-tts"))
TTS_PYTHON = Path(os.environ.get("ORCHESTRA_TTS_PYTHON", TTS_HOME / "venv/bin/python"))
TTS_MODEL = Path(os.environ.get("ORCHESTRA_TTS_MODEL", TTS_HOME / "vosk-model-tts-ru-0.9-multi"))
TTS_TERA_HOME = Path(os.environ.get("ORCHESTRA_TERA_HOME", TTS_HOME / "tera"))
TTS_TERA_PYTHON = Path(os.environ.get("ORCHESTRA_TERA_PYTHON", TTS_TERA_HOME / "venv/bin/python"))
TERA_REVISION = "f05ea799094571a3553904a555df3834fb0b963b"
TERA_SNAPSHOT = TTS_TERA_HOME / "hub/models--TeraSpace--TeraTTSv2/snapshots" / TERA_REVISION
TERA_INDEXER = TERA_SNAPSHOT / "unicode_indexer.json"
# Английский голос — Kokoro-82M (Apache 2.0) через kokoro-onnx (MIT), своё окружение рядом.
TTS_EN_HOME = Path(os.environ.get("ORCHESTRA_TTS_EN_HOME", TTS_HOME / "en"))
TTS_EN_PYTHON = Path(os.environ.get("ORCHESTRA_TTS_EN_PYTHON", TTS_EN_HOME / "venv/bin/python"))
MANIM_HOME = Path(os.environ.get("ORCHESTRA_MANIM_HOME", Path.home() / ".local/share/orchestra-manim"))
MANIM_BIN = MANIM_HOME / "env/bin"
BUILD_LOCK_PATH = Path.home() / ".cache/orchestra-video-artifact/build.lock"
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
RUSSIAN_NUMERAL_WORDS = set("ноль один одна одно одни два две три четыре пять шесть семь восемь девять десять "
                            "одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать "
                            "семнадцать восемнадцать девятнадцать двадцать тридцать сорок пятьдесят "
                            "шестьдесят семьдесят восемьдесят девяносто сто двести триста четыреста "
                            "пятьсот шестьсот семьсот восемьсот девятьсот тысяча тысячи тысяч миллион "
                            "миллиона миллионов миллиард миллиарда миллиардов".split())

VOICE_JS = """
window.__VOICE = %s;
window.voice = steps => {
  const v = window.__VOICE; if (!v) return;
  steps.forEach((s, i) => { s.d = v.d[i]; s.x = s.sub ?? s.say.replace(/\\+/g, ""); });
  window.__VOICE_APPLIED = true;
};
"""


def fail(message: str) -> None:
    sys.exit(f"video_artifact: {message}")


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
        steps = page.evaluate("STEPS.map(s => ({t: s.t, say: s.say || '', sub: s.sub || null, hold: s.hold ?? null, d: s.d, events: s.events || []}))")
        browser.close()
    return steps


@lru_cache(maxsize=4)
def _tera_character_table(indexer: str) -> list[int]:
    if not Path(indexer).is_file():
        fail(f"нет локальных файлов TeraTTS {TERA_REVISION}; установка описана в SKILL video-artifact")
    table = json.loads(Path(indexer).read_text())
    if len(table) != 65_536:
        fail(f"некорректный словарь символов TeraTTS: {indexer}")
    return table


def tera_unsupported_characters(text: str) -> list[str]:
    table = _tera_character_table(str(TERA_INDEXER))
    unsupported = set()
    for char in text:
        if "0" <= char <= "9":
            continue
        normalized = unicodedata.normalize("NFKD", char)
        if not normalized or any(ord(part) >= len(table) or table[ord(part)] < 0 for part in normalized):
            unsupported.add(char)
    return sorted(unsupported)


def check_steps(steps: list[dict], lang: str, engine: str | None = "vosk") -> list[dict]:
    for i, step in enumerate(steps, 1):
        silent = not step["say"].strip()
        if silent and (step.get("hold") is None or float(step["hold"]) <= 0):
            fail(f"шаг {i} «{step['t']}» без фразы say")
        if silent:
            continue
        pause_markers = re.findall(r"\[(\d+(?:\.\d+)?)\]", step["say"])
        if pause_markers and engine != "tera":
            fail(f"шаг {i}: явные паузы `[секунды]` поддерживает только TeraTTS")
        for marker in pause_markers:
            if not 0.05 <= float(marker) <= 10:
                fail(f"шаг {i}: пауза [{marker}] должна быть от 0.05 до 10 секунд")
        spoken_text = re.sub(r"\[(?:\d+(?:\.\d+)?)\]", "", step["say"])
        if lang == "en":
            if bad := sorted(set(NOT_SPEAKABLE_EN.findall(spoken_text))):
                fail(f"шаг {i}: в say есть {''.join(bad)} — английский голос не читает кириллицу")
        elif engine == "vosk" and (bad := sorted(set(NOT_SPEAKABLE.findall(spoken_text)))):
            fail(f"шаг {i}: в say есть {''.join(bad)} — латиницу и цифры пиши словами по-русски")
        elif lang == "ru" and engine == "vosk":
            try:
                normalize_vosk_text(spoken_text)
            except UnsupportedVoskSymbol as exc:
                fail(f"шаг {i}: символ {exc.symbol!r} не поддержан русским Vosk TTS; замени или убери его")
        elif lang == "ru" and engine == "tera":
            if bad := sorted(set(NOT_SPEAKABLE.findall(spoken_text))):
                fail(f"шаг {i}: в say есть {''.join(bad)} — числа пиши словами с нужным падежом, латиницу произноси по-русски")
            if bad := tera_unsupported_characters(spoken_text):
                fail(f"шаг {i}: символ {bad[0]!r} не поддержан русским TeraTTS")
    return steps


def repeated_numeral_run(text: str) -> int:
    longest = current = 0
    for word in re.findall(r"[А-Яа-яЁё0-9]+", text.lower()):
        if word.isdigit() or word in RUSSIAN_NUMERAL_WORDS:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def warn_numeral_runs(steps: list[dict]) -> None:
    for i, step in enumerate(steps, 1):
        count = repeated_numeral_run(step["say"])
        if count > 2:
            print(f"предупреждение: шаг {i} — подряд {count} числительных; проверь, можно ли часть показать на экране",
                  file=sys.stderr, flush=True)


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
                  "hold": s.get("hold"), "events": s.get("events", [])} for s in found[0].STEPS]}, ensure_ascii=False))
"""


def manim_steps(scene: Path, lang: str) -> tuple[str, list[dict]]:
    if not (MANIM_BIN / "manim").exists():
        fail(f"нет Manim: {MANIM_BIN}/manim — установка в SKILL video-artifact")
    got = json.loads(run(str(MANIM_BIN / "python"), "-c", MANIM_STEPS_JS, str(scene.resolve()), str(HERE),
                         capture_output=True, text=True,
                         env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}).stdout)
    return got["cls"], got["steps"]


def mark_stress(steps: list[dict], lang: str, enabled: bool, engine: str = "vosk") -> list[dict]:
    if lang != "ru" or engine != "vosk" or not enabled:
        return steps
    if not TTS_PYTHON.exists():
        fail(f"нет окружения TTS: {TTS_PYTHON} — установка в SKILL video-artifact")
    try:
        result = subprocess.run(
            [str(TTS_PYTHON), str(HERE / "tts_worker_stress.py")],
            input=json.dumps([normalize_vosk_text(step["say"]) for step in steps], ensure_ascii=False),
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


def tera_stress(steps: list[dict], enabled: bool) -> list[dict]:
    if not TTS_TERA_PYTHON.exists() or not TERA_SNAPSHOT.is_dir():
        fail(f"нет локальной TeraTTS {TERA_REVISION}; установка описана в SKILL video-artifact")
    result = subprocess.run(
        [str(TTS_TERA_PYTHON), str(HERE / "tts_worker_tera.py")],
        input=json.dumps({"action": "normalize", "texts": [step["say"] for step in steps],
                          "russian_stress": enabled}, ensure_ascii=False),
        capture_output=True, text=True, check=False,
        env={**os.environ, "ORCHESTRA_TERA_SNAPSHOT": str(TERA_SNAPSHOT)},
    )
    if result.returncode:
        fail(f"ошибка нормализации TeraTTS: {result.stderr.strip() or result.returncode}")
    try:
        normalized = json.loads(result.stdout)["normalized"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        fail(f"TeraTTS worker вернул некорректный результат нормализации: {exc}")
    if len(normalized) != len(steps) or not all(isinstance(text, str) for text in normalized):
        fail("TeraTTS worker вернул неверное число нормализованных фраз")
    for step, text in zip(steps, normalized, strict=True):
        step["_tts_text"] = re.sub(r"</?ru>", "", text)
    return steps


def drain_ordered(ready: dict[int, Path], next_index: int) -> tuple[list[tuple[int, Path]], int]:
    released = []
    while next_index in ready:
        released.append((next_index, ready.pop(next_index)))
        next_index += 1
    return released, next_index


def trim_clip(raw: Path, cut: Path) -> None:
    edge = "silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.03"
    run("ffmpeg", "-v", "error", "-y", "-i", str(raw),
        "-af", f"{edge},areverse,{edge},areverse", "-ar", str(SR), "-ac", "1",
        "-c:a", "pcm_s16le", str(cut))


def synthesize(steps: list[dict], cache: Path, speaker: int, rate: float, voice: str = "",
               on_ready=None, engine: str = "vosk", stress: bool = True) -> list[Path]:
    """Each phrase becomes a trimmed 48 kHz mono WAV, cached by text, engine and voice.

    `voice` selects the Kokoro or Tera voice; Vosk uses `speaker`."""
    cache.mkdir(parents=True, exist_ok=True)
    if engine == "vosk" and voice:
        engine = "kokoro"
    trimmed, jobs, ready, job_indices, job_by_index, queued = [], [], {}, {}, {}, {}
    for i, step in enumerate(steps):
        if engine == "tera":
            engine_key = f"tera|{TERA_REVISION}|{voice or 'ru_m1'}|stress={int(stress)}|audio-v2"
            text = step["say"]
        elif engine == "kokoro":
            engine_key = f"kokoro-v1.0|{voice}"
            text = step["say"]
        else:
            engine_key = f"vosk|{speaker}|{TTS_MODEL.name}"
            text = step.get("_tts_text", step["say"])
            text = normalize_vosk_text(text)
        key = hashlib.sha1(f"{text}|{rate}|{engine_key}".encode()).hexdigest()[:16]
        raw, cut = cache / f"{key}.raw.wav", cache / f"{key}.wav"
        trimmed.append(cut)
        if not text.strip():
            with wave.open(str(cut), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(SR)
                output.writeframes(b"")
            ready[i] = cut
            continue
        if cut.exists():
            ready[i] = cut
        elif raw.exists():
            trim_clip(raw, cut)
            ready[i] = cut
        elif raw in queued:
            job_indices[queued[raw]].append(i)
        else:
            job = {"index": i, "text": text, "speaker": speaker, "voice": voice,
                   "rate": rate, "out": str(raw)}
            if engine == "tera":
                job.update(engine="tera", voice=voice or "ru_m1", stress=stress)
            jobs.append(job)
            job_indices[i] = [i]
            job_by_index[i] = job
            queued[raw] = i

    next_index = 0
    released, next_index = drain_ordered(ready, next_index)
    if on_ready:
        for i, path in released:
            on_ready(i, path)

    def accept(index: int) -> None:
        raw = Path(job_by_index[index]["out"])
        indices = job_indices[index]
        cut = trimmed[indices[0]]
        trim_clip(raw, cut)
        ready.update({i: cut for i in indices})
        nonlocal next_index
        released, next_index = drain_ordered(ready, next_index)
        if on_ready:
            for i, path in released:
                on_ready(i, path)

    if jobs and engine == "kokoro":
        if not TTS_EN_PYTHON.exists() or not (TTS_EN_HOME / "kokoro-v1.0.onnx").exists():
            fail(f"нет английского TTS: {TTS_EN_PYTHON} и {TTS_EN_HOME}/kokoro-v1.0.onnx — установка в SKILL video-artifact")
        worker = TTS_EN_PYTHON, HERE / "tts_worker_en.py", {**os.environ, "ORCHESTRA_TTS_EN_HOME": str(TTS_EN_HOME)}
    elif jobs and engine == "tera":
        if not TTS_TERA_PYTHON.exists() or not TERA_SNAPSHOT.is_dir():
            fail(f"нет локальной TeraTTS {TERA_REVISION}; установка описана в SKILL video-artifact")
        worker = TTS_TERA_PYTHON, HERE / "tts_worker_tera.py", {
            **os.environ, "ORCHESTRA_TERA_SNAPSHOT": str(TERA_SNAPSHOT)}
    elif jobs:
        if not TTS_PYTHON.exists() or not (TTS_MODEL / "model.onnx").exists():
            fail(f"нет окружения TTS: {TTS_PYTHON} и {TTS_MODEL}/model.onnx — установка в SKILL video-artifact")
        worker = TTS_PYTHON, HERE / "tts_worker.py", {**os.environ, "ORCHESTRA_TTS_MODEL": str(TTS_MODEL)}
    else:
        worker = None
    if worker:
        if engine == "tera":
            print(f"синтез {len(jobs)} фраз (TeraTTS {TERA_REVISION[:8]}, {voice or 'ru_m1'}, один CPU sampler)…", flush=True)
        elif voice:
            print(f"синтез {len(jobs)} фраз (Kokoro, {voice})…", flush=True)
        else:
            print(f"синтез {len(jobs)} фраз (загрузка Vosk)…", flush=True)
        if on_ready is None:
            run(str(worker[0]), str(worker[1]), input=json.dumps(jobs, ensure_ascii=False).encode(),
                stdout=subprocess.DEVNULL, env=worker[2])
            for job in jobs:
                trim_clip(Path(job["out"]), trimmed[job["index"]])
        else:
            proc = subprocess.Popen([str(worker[0]), str(worker[1])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    text=True, env=worker[2])
            assert proc.stdin and proc.stdout
            proc.stdin.write(json.dumps(jobs, ensure_ascii=False))
            proc.stdin.close()
            try:
                for line in proc.stdout:
                    event = json.loads(line)
                    accept(int(event["index"]))
                if proc.wait():
                    fail(f"ошибка TTS worker: {proc.returncode}")
            except BaseException:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
                raise
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
        lead = LEAD / rate if step["say"].strip() else 0
        d = round(lead + length + (step["hold"] if step["hold"] is not None else GAP / rate), 3)
        rows.append({"title": step["t"], "say": step["say"], "sub": step["sub"], "step_start": round(at, 3),
                     "phrase_start": round(at + lead, 3), "phrase_end": round(at + lead + length, 3), "d": d,
                     "events": step.get("events", [])})
        at += d
    return {"steps": rows, "T": round(at, 3), "pre": PRE, "post": POST}


def sound_cues(timing: dict, fps: int, voice: Path, music: Path, kit: Path = SOUND_HOME) -> dict:
    """Place declared scene events on the already planned step timeline."""
    cues = []
    for step_no, row in enumerate(timing["steps"], 1):
        for event_no, event in enumerate(row.get("events", []), 1):
            if not isinstance(event, dict) or not event.get("sound"):
                fail(f"шаг {step_no}, событие {event_no}: нужен объект events с полем sound")
            offset = float(event.get("at", row["d"] / 2))
            if not 0 <= offset <= row["d"]:
                fail(f"шаг {step_no}, событие {event_no}: at должен быть внутри шага (0…{row['d']:.3f} с)")
            at = round(PRE + row["step_start"] + offset, 4)
            cue = {"id": event.get("id", f"step{step_no:02d}-event{event_no:02d}"),
                   "t": at, "frame": round(at * fps), "sound": event["sound"],
                   "weight": event.get("weight", "support"), "align": event.get("align", "peak")}
            for key in ("visual", "pan", "pitch", "note", "build", "stop_before"):
                if key in event:
                    cue[key] = event[key]
            cues.append(cue)
    if not cues:
        return {}
    return {"fps": fps, "duration_s": round(PRE + timing["T"] + POST, 3),
            "energy": "calm", "lufs": -18, "kit": str(kit),
            "music": {"file": str(music.resolve()), "start_s": 0, "loop": True, "fade_out_s": 1.0},
            "voice": [{"file": str(voice.resolve()), "start_s": 0}], "cues": cues}


def sound_mix(out: Path, name: str, sheet: dict) -> None:
    if not sheet:
        return
    audio = out / f"{name}.sound"
    audio.mkdir(parents=True, exist_ok=True)
    cues_path = audio / "cues.json"
    cues_path.write_text(json.dumps(sheet, ensure_ascii=False, indent=1))
    run(UV_BIN, "run", "--script", str(SOUND_SCRIPTS / "mix.py"), str(cues_path), "--out", str(audio))


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


class HTMLRenderPipeline:
    def __init__(self, scene: Path, steps: list[dict], out: Path, name: str, fps: int, jobs: int, rate: float):
        self.scene, self.steps, self.out, self.name, self.fps = scene, steps, out, name, fps
        self.rate = rate
        self.pool = ProcessPoolExecutor(max_workers=jobs, mp_context=get_context("spawn"))
        self.parts = []
        self.started = time.monotonic()
        self.rendered = 0

    def step_ready(self, index: int, clips: list[Path]) -> None:
        prefix = plan(self.steps[:index + 1], clips[:index + 1], self.rate)
        row = prefix["steps"][index]
        voice_durations = [item["d"] for item in prefix["steps"]]
        voice_durations.extend(float(step.get("d") or 1.0) for step in self.steps[index + 1:])
        first = 0 if index == 0 else round((PRE + row["step_start"]) * self.fps)
        last = round((PRE + row["step_start"] + row["d"] + (POST if index == len(self.steps) - 1 else 0)) * self.fps)
        times = [min(max(frame / self.fps - PRE, 0.0), prefix["T"]) for frame in range(first, last)]
        part = self.out / f".{self.name}.step{index:04d}.mp4"
        future = self.pool.submit(render_part, (self.scene, {"d": voice_durations}, times, str(part), self.fps))
        future.add_done_callback(self.render_done)
        self.parts.append((part, future))

    def render_done(self, _future) -> None:
        self.rendered += 1
        elapsed = time.monotonic() - self.started
        eta = elapsed / self.rendered * (len(self.steps) - self.rendered)
        print(f"кадры HTML: {self.rendered}/{len(self.steps)}, осталось ~{eta:.0f} с", flush=True)

    def finish(self) -> None:
        try:
            if self.parts:
                for _part, future in self.parts:
                    future.result()
                listing = self.out / f".{self.name}.parts.txt"
                listing.write_text("".join(f"file '{part.name}'\n" for part, _future in self.parts))
                run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(self.out / f"{self.name}.video.mp4"))
                for part, _future in self.parts:
                    part.unlink()
                listing.unlink()
        finally:
            self.pool.shutdown(wait=True)


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
    """Manim сам пишет MP4; длительности шагов получает через VIDEO_ARTIFACT_VOICE (см. manim_voice.py).
    --stills тоже рендерит, но в 480p: кадр Manim нельзя снять без проигрыша сцены до него."""
    media = out / ".manim"
    quality = ["-r", "1920,1080", "--fps", str(fps)] if video else ["-ql"]
    voice = {"d": [row["d"] for row in timing["steps"]], "pre": PRE, "post": POST}
    run(str(MANIM_BIN / "manim"), "render", *quality, "--media_dir", str(media), "-o", name,
        str(scene.resolve()), cls,
        env={**os.environ, "VIDEO_ARTIFACT_VOICE": json.dumps(voice), "PYTHONPATH": str(HERE),
             "PYTHONDONTWRITEBYTECODE": "1",
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


def preview_manim(scene: Path, cls: str, out: Path, name: str, first_step: int, last_step: int) -> Path:
    from manim_timing import analyze, selected_range

    analysis = analyze(scene.read_text(), cls)
    if not analysis["complete"]:
        fail("быстрый предпросмотр требует статически индексируемых self.play/run_time; запусти обычную сборку")
    try:
        selected_range(analysis, first_step - 1, last_step - 1)
    except ValueError as exc:
        fail(str(exc))
    media = out / ".preview-manim"
    out_dir = out / f".preview-renders-{first_step}-{last_step}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for step_no in range(first_step, last_step + 1):
        start, end = selected_range(analysis, step_no - 1, step_no - 1)
        run(str(MANIM_BIN / "manim"), "render", "-ql", "-n", f"{start},{end}",
            "--media_dir", str(media), "-o", f"{name}-step{step_no:02d}",
            str(scene.resolve()), cls,
            env={**os.environ, "PYTHONPATH": str(HERE), "PYTHONDONTWRITEBYTECODE": "1", "VIDEO_ARTIFACT_PREVIEW": "1",
                 "PATH": f"{MANIM_BIN}:{os.environ['PATH']}"})
        rendered = max(media.glob(f"videos/**/{name}-step{step_no:02d}.mp4"), key=lambda p: p.stat().st_mtime)
        run("ffmpeg", "-v", "error", "-y", "-sseof", "-1", "-i", str(rendered), "-vf", "reverse", "-frames:v", "1",
            str(out_dir / f"step{step_no:02d}.png"))
    tile = f"tile={min(3, last_step - first_step + 1)}x{(last_step - first_step + 3) // 3}"
    contact = out / f"{name}-preview-contact.png"
    run("ffmpeg", "-v", "error", "-y", "-pattern_type", "glob", "-i", str(out_dir / "step*.png"),
        "-vf", f"scale=640:-1,{tile}", "-frames:v", "1", str(contact))
    print(f"черновик шагов {first_step}–{last_step}: {contact}", flush=True)
    return contact


def preview_html(scene: Path, steps: list[dict], out: Path, name: str, first_step: int, last_step: int) -> Path:
    durations = [float(step.get("d") or 1.0) for step in steps]
    voice = {"d": durations}
    frames = out / f".preview-renders-{first_step}-{last_step}"
    frames.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser, page = open_scene(pw, scene, voice)
        applied = page.evaluate("[window.__VOICE_APPLIED === true, P.T]")
        if not applied[0]:
            fail("сцена не принимает быстрый предпросмотр: нужна строка `window.voice?.(STEPS);` после STEPS")
        at = 0.0
        selected = []
        for index, duration in enumerate(durations):
            if first_step - 1 <= index <= last_step - 1:
                page.evaluate(f"P.seek({at + duration - 0.05})")
                frame = frames / f"step{index + 1:02d}.png"
                page.screenshot(path=str(frame))
                selected.append(frame)
            at += duration
        browser.close()
    tile = f"tile={min(3, len(selected))}x{(len(selected) + 2) // 3}"
    contact = out / f"{name}-preview-contact.png"
    run("ffmpeg", "-v", "error", "-y", "-pattern_type", "glob", "-i", str(frames / "step*.png"),
        "-vf", f"scale=640:-1,{tile}", "-frames:v", "1", str(contact))
    print(f"черновик шагов {first_step}–{last_step}: {contact}", flush=True)
    return contact


def manim_timing_check(scene: Path, cls: str, timing: dict, out: Path, name: str) -> dict:
    from manim_timing import analyze, check

    analysis = analyze(scene.read_text(), cls)
    report = check(analysis, [row["d"] for row in timing["steps"]])
    if not report["complete"]:
        print("статическая проверка таймингов неприменима; запускаю Manim --dry_run", flush=True)
        voice = {"d": [row["d"] for row in timing["steps"]], "pre": PRE, "post": POST}
        run(str(MANIM_BIN / "manim"), "render", "-ql", "--dry_run", "--media_dir", str(out / ".timing-manim"),
            "-o", f"{name}-timing", str(scene.resolve()), cls,
            env={**os.environ, "VIDEO_ARTIFACT_VOICE": json.dumps(voice), "PYTHONPATH": str(HERE),
                 "PYTHONDONTWRITEBYTECODE": "1", "PATH": f"{MANIM_BIN}:{os.environ['PATH']}"})
        report = {"complete": False, "fallback": "manim --dry_run", "overruns": []}
    elif report["overruns"]:
        fail("тайминг превышен в шагах: " + ", ".join(str(i + 1) for i in report["overruns"]))
    (out / f"{name}.timing-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"проверка таймингов: {'Manim --dry_run' if report.get('fallback') else 'статически'}, "
          f"{len(timing['steps'])} шагов", flush=True)
    return report


@contextmanager
def build_lock(path: Path, build: str, on_wait=print):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.seek(0)
            try:
                owner = json.loads(lock.read())
            except (json.JSONDecodeError, OSError):
                owner = {"build": "unknown"}
            on_wait(f"жду сборку {owner.get('build', 'unknown')} (pid {owner.get('pid', '?')})")
            fcntl.flock(lock, fcntl.LOCK_EX)
        lock.seek(0)
        lock.truncate()
        json.dump({"pid": os.getpid(), "build": build, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, lock)
        lock.flush()
        try:
            yield
        finally:
            lock.seek(0)
            lock.truncate()
            lock.flush()


def mux(out: Path, name: str, sound: bool = False) -> Path:
    mp4 = out / f"{name}.mp4"
    if sound:
        run("ffmpeg", "-v", "error", "-y", "-i", str(out / f"{name}.video.mp4"), "-i",
            str(out / f"{name}.sound" / "mix.wav"), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", str(mp4))
        (out / f"{name}.video.mp4").unlink()
        return mp4
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
    raw = re.findall(r"[a-zа-я0-9]+", text)
    units = {"ноль": 0, "один": 1, "одна": 1, "одно": 1, "одну": 1, "одного": 1, "одной": 1,
             "два": 2, "две": 2, "двух": 2,
             "три": 3, "четыре": 4, "четырех": 4, "пять": 5, "шесть": 6, "семь": 7,
             "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12,
             "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16,
             "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19}
    tens = {"двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
            "семьдесят": 70, "восемьдесят": 80, "девяносто": 90}
    hundreds = {"сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
                "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900}
    english_units = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                     "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                     "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
                     "seventeen": 17, "eighteen": 18, "nineteen": 19}
    english_tens = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
                    "seventy": 70, "eighty": 80, "ninety": 90}
    normalized, index = [], 0
    while index < len(raw):
        word = raw[index]
        if raw[index:index + 4] in (["две", "с", "половиной", "тысячи"],
                                   ["две", "с", "половиной", "тысяч"]):
            normalized.append("2500"); index += 4; continue
        if word in english_units or word in english_tens or word in ("hundred", "thousand"):
            total = group = 0
            while index < len(raw):
                word = raw[index]
                if word in english_units:
                    group += english_units[word]
                elif word in english_tens:
                    group += english_tens[word]
                elif word == "and" and index > 0:
                    index += 1
                    continue
                elif word == "hundred":
                    group = max(group, 1) * 100
                elif word == "thousand":
                    total += max(group, 1) * 1000
                    group = 0
                else:
                    break
                index += 1
            normalized.append(str(total + group)); continue
        if word not in units and word not in tens and word not in hundreds:
            normalized.append(word[:5]); index += 1; continue
        total = group = 0
        start = index
        while index < len(raw):
            word = raw[index]
            if word in hundreds:
                group += hundreds[word]
            elif word in tens:
                group += tens[word]
            elif word in units:
                group += units[word]
            elif word in ("тысяча", "тысячи", "тысяч") and index > start:
                total += max(group, 1) * 1000
                group = 0
            else:
                break
            index += 1
        normalized.append(str(total + group))
    return normalized


def align(phrases: list[str], heard: list[str]) -> list[list[int | None]]:
    """Для каждого слова каждой фразы — индекс распознанного слова или None."""
    planned = [(i, w) for i, phrase in enumerate(phrases) for w in tokens(phrase)]
    match: dict[int, int] = {}
    matcher = difflib.SequenceMatcher(None, [w for _i, w in planned], heard, autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            match[block.a + k] = block.b + k
    return [[match.get(k) for k, (i, _w) in enumerate(planned) if i == n] for n in range(len(phrases))]


def word_scores(phrase: str, hits: list[int | None]) -> tuple[float, float, int]:
    """Keep lexical recall strict while reporting numerals separately when speech recognition omits them."""
    words = tokens(phrase)
    numeric = [index for index, word in enumerate(words) if word.isdigit()]
    lexical = [index for index, word in enumerate(words) if not word.isdigit()]
    lexical_recall = sum(hits[index] is not None for index in lexical) / len(lexical) if lexical else 1.0
    numeric_recall = sum(hits[index] is not None for index in numeric) / len(numeric) if numeric else 1.0
    return lexical_recall, numeric_recall, len(numeric)


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
        say_score = word_scores(row["say"], say_hits)
        sub_score = word_scores(row["sub"] or row["say"], sub_hits)
        hits, score = (say_hits, say_score) if say_score[:2] >= sub_score[:2] else (sub_hits, sub_score)
        first = next((h for h in (say_hits[0], sub_hits[0]) if h is not None), None)
        start = words[heard_words[first][1]]["start"] if first is not None else None
        # Первое слово записи Deepgram иногда ставит на 0.0 при тишине перед ним: это не сдвиг.
        if start == 0.0:
            start = None
        rows.append({
            "say": row["say"],
            "heard": " ".join(dict.fromkeys(words[heard_words[h][1]]["word"] for h in hits if h is not None)),
            "recall": round(score[0], 2),
            "numeric_recall": round(score[1], 2),
            "numeric_total": score[2],
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


def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--speaker", type=int, default=1)
    ap.add_argument("--tts-engine", choices=["tera", "vosk"], default="tera",
                    help="русская озвучка: локальная TeraTTSv2 по умолчанию или Vosk")
    ap.add_argument("--lang", choices=["ru", "en"], default="ru",
                    help="en — английская озвучка Kokoro")
    ap.add_argument("--voice", choices=["m1", "m5", "f1", "f2", "af_heart", "am_michael"],
                    help="Tera: m1 (default), m5, f1, f2; Kokoro: af_heart (default), am_michael")
    ap.add_argument("--rate", type=float, default=1.0)
    ap.add_argument("--no-stress", action="store_true", help="отключить автоматическую разметку русского ударения")
    ap.add_argument("--stress-only", action="store_true",
                    help="показать нормализованные фразы и ударения без генерации WAV")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--music", type=Path, help="CC0 или собственная фоновая дорожка; обязателен, если в STEPS заданы events")
    ap.add_argument("--jobs", type=int, default=max(1, min(6, (os.cpu_count() or 2) - 2)),
                    help="параллельных Chromium при записи")
    ap.add_argument("--stills", action="store_true", help="без видео: тайминг и контакт-лист")
    preview = ap.add_mutually_exclusive_group()
    preview.add_argument("--preview-step", type=int, help="быстрый стоп-кадр шага без TTS")
    preview.add_argument("--preview-range", help="быстрый контакт-лист шагов, например 5:8")
    ap.add_argument("--timing-only", action="store_true", help="проверить длительности фраз и анимаций без рендера")
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
    steps = check_steps(steps, args.lang, engine=None)
    warn_numeral_runs(steps)
    print("stage 1/4: scene and speech plan", flush=True)
    if args.preview_step or args.preview_range:
        if args.preview_step:
            first_step = last_step = args.preview_step
        else:
            match = re.fullmatch(r"(\d+):(\d+)", args.preview_range)
            if not match:
                fail("--preview-range задаётся как начало:конец, например 5:8")
            first_step, last_step = map(int, match.groups())
        if first_step < 1 or last_step < first_step or last_step > len(steps):
            fail(f"диапазон предпросмотра должен быть в пределах 1…{len(steps)}")
        if manim:
            preview_manim(args.scene, cls, out, name, first_step, last_step)
        else:
            preview_html(args.scene, steps, out, name, first_step, last_step)
        return
    steps = check_steps(steps, args.lang, args.tts_engine)
    if args.stress_only:
        if args.lang == "ru" and args.tts_engine == "tera":
            steps = tera_stress(steps, enabled=not args.no_stress)
        else:
            steps = mark_stress(steps, args.lang, enabled=not args.no_stress, engine=args.tts_engine)
        marked = [step.get("_tts_text", step["say"]) for step in steps]
        (out / f"{name}.stress.txt").write_text("\n".join(marked) + "\n")
        for i, text in enumerate(marked, 1):
            print(f"  {i:2d}. {text}")
        return
    if args.lang == "ru" and args.tts_engine == "vosk":
        steps = mark_stress(steps, args.lang, enabled=not args.no_stress, engine="vosk")
    has_events = any(step.get("events") for step in steps)
    if has_events and not args.music:
        fail("в STEPS заданы звуковые events: укажи фоновую CC0-дорожку через --music")
    if has_events and not args.music.is_file():
        fail(f"не найдена фоновая дорожка: {args.music}")
    pipeline = None
    if not manim and not args.stills and not args.check_only:
        pipeline = HTMLRenderPipeline(args.scene, steps, out, name, args.fps, args.jobs, args.rate)
    rendered_clips = []
    speech_started = time.monotonic()

    def render_ready(index: int, clip: Path) -> None:
        if index != len(rendered_clips):
            raise RuntimeError(f"неупорядоченный результат синтеза: ожидался шаг {len(rendered_clips)}, получен {index}")
        rendered_clips.append(clip)
        elapsed = time.monotonic() - speech_started
        eta = elapsed / len(rendered_clips) * (len(steps) - len(rendered_clips))
        print(f"озвучка: {len(rendered_clips)}/{len(steps)}, осталось ~{eta:.0f} с", flush=True)
        if pipeline:
            pipeline.step_ready(index, rendered_clips)

    if args.lang == "en":
        engine = "kokoro"
        voice = args.voice or "af_heart"
        if voice not in {"af_heart", "am_michael"}:
            fail("для --lang en выбери Kokoro voice: af_heart или am_michael")
    elif args.tts_engine == "tera":
        engine = "tera"
        tera_voice = args.voice or "m1"
        if tera_voice not in {"m1", "m5", "f1", "f2"}:
            fail("для русской Tera выбери --voice m1, m5, f1 или f2")
        voice = f"ru_{tera_voice}"
    else:
        engine = "vosk"
        if args.voice is not None:
            fail("Vosk выбирает голос через --speaker, параметр --voice предназначен для Tera/Kokoro")
        voice = ""
    clips = synthesize(steps, out / ".tts-cache", args.speaker, args.rate,
                       voice=voice, on_ready=render_ready, engine=engine, stress=not args.no_stress)
    timing = plan(steps, clips, args.rate)
    if manim:
        manim_timing_check(args.scene, cls, timing, out, name)
    print("stage 2/4: timing plan ready", flush=True)
    if pipeline:
        pipeline.finish()
    sheet = sound_cues(timing, args.fps, out / f"{name}.voice.wav", args.music) if has_events else {}
    (out / f"{name}.timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1))
    for row in timing["steps"]:
        print(f"  {row['phrase_start']:6.2f}–{row['phrase_end']:6.2f}  шаг {row['d']:5.2f} с  {row['say']}")
    print(f"длина ролика {PRE + timing['T'] + POST:.1f} с")
    if args.timing_only:
        print("тайминг проверен; рендер пропущен", flush=True)
        return
    if not args.check_only:
        print("stage 3/4: rendering frames", flush=True)
        voice_track(timing, clips, out / f"{name}.voice.wav")
        if manim:
            render_manim(args.scene, cls, timing, out, name, args.fps, video=not args.stills)
        elif pipeline:
            render(args.scene, timing, out, name, args.fps, video=False, jobs=args.jobs)
        else:
            render(args.scene, timing, out, name, args.fps, video=not args.stills, jobs=args.jobs)
        print(out / f"{name}-contact.png")
        if args.stills:
            return
        print("stage 4/4: mix, mux, and checks", flush=True)
        sound_mix(out, name, sheet)
        mp4 = mux(out, name, sound=bool(sheet))
        print(mp4, f"{mp4.stat().st_size / 1e6:.1f} МБ")
    if sheet:
        if args.check_only and not (out / f"{name}.sound" / "mix-report.json").exists():
            fail("для звукового --check-only нужны прежние mix-report.json и stems в <out>/<имя>.sound/")
        run(UV_BIN, "run", "--script", str(SOUND_SCRIPTS / "qa.py"), str(out / f"{name}.mp4"), "--audio", str(out / f"{name}.sound"))
    key = os.environ.get("DEEPGRAM_API_KEY")
    if args.no_check or not key:
        print("проверка распознаванием пропущена" + ("" if key else ": нет DEEPGRAM_API_KEY"))
        return
    report = check(out, name, timing, key, args.lang)
    for r in report["phrases"]:
        print(f"  recall {r['recall']:.2f}  сдвиг слова {r['offset_s']}  звука {r['onset_offset_s']}  {r['say']}\n      слышно: {r['heard']}")
    print(f"минимальная дословность {report['recall_min']}, наибольший сдвиг: первого слова "
          f"{report['offset_max_abs_s']} с, начала звука {report['onset_offset_max_abs_s']} с")


def main() -> None:
    scene = next((Path(arg) for arg in sys.argv[1:] if not arg.startswith("-")), Path("scene"))
    with build_lock(BUILD_LOCK_PATH, scene.stem):
        _main()


if __name__ == "__main__":
    main()
