"""rows.json → table.md: one line per model/voice with the columns the V-892 assignment asks for."""
import json, statistics, sys
from collections import defaultdict
from pathlib import Path

task = Path(sys.argv[1])
rows = json.load(open(task / "rows.json"))
# (license, runs on our CPU, peak RSS of the whole run, takes '+' stress marks); licenses from the HF API tags 16.10.2026
META = {
    "tera": ("не объявлена (TeraSpace/TeraTTSv2)", "да", "2,4 ГБ", "да"),
    "tera-teacher-space": ("не объявлена", "HF Space, CPU", "—", "да"),
    "vosk": ("Apache 2.0", "да", "4,0 ГБ (с RUAccent)", "да"),
    "silero/v5_6_ru": ("CC-NC-BY (некоммерческая)", "да", "0,77 ГБ", "да, есть и автоударение"),
    "silero/v5_cis_base": ("MIT", "да", "0,77 ГБ", "да, обязателен на каждом слове"),
    "piper": ("MIT (rhasspy/piper-voices), датасет голоса не указан", "да", "0,48 ГБ", "нет (eSpeak G2P)"),
    "edge-azure": ("сервис Microsoft, неофициальный доступ", "облако", "—", "нет"),
    "xtts": ("Coqui Public Model License (некоммерческая)", "да", "4,3 ГБ", "нет"),
    "kokoro-ru": ("OpenRAIL (zaakirio/kokoro-ru)", "да", "4,3 ГБ (с RUAccent)", "получал текст с '+', влияние не проверено"),
    "qwen3-tts": ("Apache 2.0", "да", "12,5 ГБ (весь прогон трёх моделей)", "нет"),
    "qwen3-1.7b-space": ("Apache 2.0", "HF ZeroGPU Space", "—", "нет"),
    "f5/f5-misha-v4": ("CC-BY-NC 4.0 (Misha24-10/F5-TTS_RUSSIAN)", "да", "8,6 ГБ (вместе с ESpeech)", "да"),
    "f5/espeech-rlv2": ("Apache 2.0 по метке, происхождение весов не указано", "да", "8,6 ГБ (вместе с F5)", "да"),
    "cosyvoice3": ("Apache 2.0", "да", "8,7 ГБ", "нет"),
    "chatterbox-mtl": ("MIT, водяной знак PerTh в каждом файле", "да", "6,9 ГБ", "нет"),
    "fish-s2-pro": ("Fish Audio Research License (некоммерческая)", "да, очень медленно", "19,9 ГБ", "нет"),
    "outetts-1.0/1b": ("CC-BY-NC-SA 4.0", "да", "8,6 ГБ (весь прогон 1B и 0.6B)", "нет"),
    "outetts-1.0/0.6b": ("Apache 2.0", "да", "8,6 ГБ (тот же прогон)", "нет"),
}

def meta(model, voice):
    for k in (f"{model}/{voice.split('/')[0]}", model):
        if k in META:
            return META[k]
    return ("?", "?", "?", "?")

def fmt(x, nd=2):
    return "—" if x is None else f"{x:.{nd}f}".replace(".", ",")

groups = defaultdict(list)
for r in rows:
    groups[(r["model"], r["voice"])].append(r)
lines = ["| Модель | Голос | Лицензия | Наш CPU | RTF (мин–макс) | Пик памяти | Ударение `+` | Recall p1…p5 | Recall средн. | Numeric средн. |",
         "|---|---|---|---|---|---|---|---|---|---|"]
for (model, voice), rs in sorted(groups.items()):
    rs.sort(key=lambda r: r["phrase"])
    lic, cpu, rss, plus = meta(model, voice)
    rtfs = [r["rtf"] for r in rs if r.get("rtf")]
    rtf = f"{fmt(min(rtfs))}–{fmt(max(rtfs))}" if rtfs else "—"
    rec = [r["recall"] for r in rs if r.get("recall") is not None]
    num = [r["numeric_recall"] for r in rs if r.get("numeric_recall") is not None]
    per = " / ".join(fmt(r.get("recall")) for r in rs)
    lines.append(f"| {model} | {voice} | {lic} | {cpu} | {rtf} | {rss} | {plus} | {per} | "
                 f"{fmt(statistics.mean(rec)) if rec else '—'} | {fmt(statistics.mean(num)) if num else '—'} |")
(task / "table.md").write_text("\n".join(lines) + "\n")
print(len(groups), "groups")
