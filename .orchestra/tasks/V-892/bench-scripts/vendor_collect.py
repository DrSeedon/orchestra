import json, subprocess
from pathlib import Path
root = Path(__file__).parents[1]; v = root / "vendor"
dst = Path("/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-tts/.orchestra/tasks/V-892/samples/vendor"); dst.mkdir(parents=True, exist_ok=True)
items = []
el = {json.loads(l)["file"]: json.loads(l) for l in open(v / "elevenlabs/dg.jsonl")}
urls = open(v / "elevenlabs/urls.txt").read().split()
for f, d in el.items():
    if d["language"] == "ru":
        n = int(f.split("_")[1].split(".")[0])
        items.append(("elevenlabs", f"preview{n:02d}", v / "elevenlabs" / f, urls[n - 1], "голосовая библиотека ElevenLabs, страница /text-to-speech/russian; модель не указана"))
mm_urls = open(v / "minimax/urls.txt").read().split()
for i, u in enumerate(mm_urls):
    items.append(("minimax", f"voice{i:02d}", v / f"minimax/mm_{i}.mp3", u, "minimax.io/audio/text-to-speech/russian; модель не указана"))
for n in ["boris", "marfa", "natasha", "sasha", "sergey", "taras"]:
    items.append(("salutespeech", n, v / f"sber/sber_{n}-hq.mp3", "", "developers.sber.ru, голоса синтеза, hq"))
for f in sorted((v / "google").glob("google_*.wav")):
    items.append(("google", f.stem.removeprefix("google_"), f, "", "docs.cloud.google.com list-voices-and-types, ru-RU"))
for m in json.load(open(v / "fish_ru/picked.json")):
    items.append(("fish-audio", m["name"], v / f"fish_ru/fish_{m['name']}.mp3", f"https://fish.audio/m/{m['id']}", f"публичный голос «{m['title']}», образец по умолчанию; текст: {m['text']}"))
rows = []
for vendor, voice, src, url, note in items:
    ogg = dst / f"vendor_{vendor}_{voice}.ogg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", "loudnorm=I=-20:TP=-2", "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "40k", str(ogg)], check=True)
    rows.append({"vendor": vendor, "voice": voice, "sample": f"vendor/{ogg.name}", "source_url": url, "note": note})
json.dump(rows, open(dst.parent.parent / "vendor_rows.json", "w"), ensure_ascii=False, indent=1)
print(len(rows))
