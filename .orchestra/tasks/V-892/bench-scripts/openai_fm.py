import base64, json, sys, uuid
from pathlib import Path
from playwright.sync_api import sync_playwright
root = Path(__file__).parents[1]
phr = json.load(open(root / "phrases.json"))
out = root / "out/clients"; out.mkdir(parents=True, exist_ok=True)
voices = sys.argv[1:] or ["onyx"]
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    pg.goto("https://www.openai.fm/", wait_until="networkidle", timeout=90000)
    print("title:", pg.title())
    for v in voices:
        for ph in phr:
            js = """async ([i,v,g]) => { const u = new URL('/api/generate', location.origin);
              u.searchParams.set('input', i); u.searchParams.set('prompt', 'Voice: calm, clear Russian-speaking science lecturer. Pace: steady.');
              u.searchParams.set('voice', v); u.searchParams.set('generation', g);
              const r = await fetch(u); const buf = new Uint8Array(await r.arrayBuffer());
              let s=''; for (const c of buf) s += String.fromCharCode(c); return [r.status, r.headers.get('content-type'), btoa(s)]; }"""
            st, ct, data = pg.evaluate(js, [ph["text"].replace("+", ""), v, str(uuid.uuid4())])
            print(v, ph["id"], st, ct, len(data))
            if st == 200 and "audio" in (ct or ""):
                f = out / f"openai-fm-gpt4o-mini-tts_{v}_{ph['id']}.mp3"; f.write_bytes(base64.b64decode(data))
                with open(out / "clients.jsonl", "a") as log:
                    log.write(json.dumps({"source": "openai-fm-gpt4o-mini-tts", "phrase": ph["id"], "wall_s": None, "file": str(f), "voice": v}, ensure_ascii=False) + "\n")
    b.close()
