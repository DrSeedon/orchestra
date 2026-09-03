"""#8 — измерение стоимости рендера vs восстановления готового HTML.
Живой :8888, headless chromium, реальные логи реальных агентов, реальный addChatEntry.
Ничего не пишет на сервер: только GET + рендер в своей вкладке.
"""
import asyncio, json, os, sys
from playwright.async_api import async_playwright

ENV = {}
for line in open("/home/kesha/orchestra/.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip()

BASE = "http://127.0.0.1:8888"

MEASURE = r"""
async ({name, scope, limit}) => {
  const q = new URLSearchParams({scope, before_id: String(2**31-1), limit: String(limit)});
  const t0 = performance.now();
  const resp = await fetch(`/api/sessions/${encodeURIComponent(name)}/logs?${q}`);
  const body = await resp.text();
  const logs = JSON.parse(body);
  if (!Array.isArray(logs)) return {error: resp.status + ' ' + body.slice(0, 300)};
  const tFetch = performance.now() - t0;
  const chat = document.querySelector('#chat');
  const raw = new TextEncoder().encode(JSON.stringify(logs)).length;

  // --- 1. полный рендер через боевой addChatEntry ---
  chat.innerHTML = '';
  window.scrollAfterLoad = false;
  const r0 = performance.now();
  for (const l of logs) { try { addChatEntry(l.type, l.content, l.ts, null, l); } catch(e) {} }
  void chat.scrollHeight;                 // форсим раскладку, как и в inject-ветке
  const tRender = performance.now() - r0;
  const nodes = chat.children.length;

  // --- 2. сериализация отрисованного ---
  const s0 = performance.now();
  const html = chat.innerHTML;
  const tSerialize = performance.now() - s0;
  const htmlBytes = new TextEncoder().encode(html).length;

  // --- 3. восстановление из готового HTML ---
  chat.innerHTML = '';
  await new Promise(r => requestAnimationFrame(r));
  const i0 = performance.now();
  chat.innerHTML = html;
  const tInject = performance.now() - i0;
  const nodes2 = chat.children.length;
  // время до реальной раскладки (forced layout) — innerHTML сам по себе ленив
  const l0 = performance.now();
  const h = chat.scrollHeight;
  const tLayout = performance.now() - l0;

  // --- 4. рендер только хвоста (20 последних) ---
  chat.innerHTML = '';
  const tail = logs.slice(-20);
  const p0 = performance.now();
  for (const l of tail) { try { addChatEntry(l.type, l.content, l.ts, null, l); } catch(e) {} }
  void chat.scrollHeight;
  const tTail = performance.now() - p0;

  // --- 4b. из чего состоит рендер: marked / DOMPurify / hljs на тех же текстах ---
  const texts = logs.filter(l => l.type === 'text' || l.type === 'user_message').map(l => String(l.content));
  const bodies = logs.map(l => String(l.content));
  let mk = 0, pf = 0, hl = 0;
  const m0 = performance.now(); const mds = bodies.map(t => marked.parse(t)); mk = performance.now() - m0;
  const f0 = performance.now(); const safe = mds.map(h => DOMPurify.sanitize(h)); pf = performance.now() - f0;
  const probe = document.createElement('div'); probe.innerHTML = safe.join('');
  const blocks = [...probe.querySelectorAll('pre code')];
  const g0 = performance.now(); blocks.forEach(b => { try { hljs.highlightElement(b); } catch(e) {} }); hl = performance.now() - g0;

  // --- 5. IndexedDB запись/чтение готового HTML ---
  const db = await new Promise((res, rej) => {
    const rq = indexedDB.open('m8', 1);
    rq.onupgradeneeded = () => rq.result.createObjectStore('c');
    rq.onsuccess = () => res(rq.result); rq.onerror = () => rej(rq.error);
  });
  const put = async (val) => { const t = performance.now(); await new Promise((res, rej) => {
      const tx = db.transaction('c', 'readwrite'); tx.objectStore('c').put(val, 'k');
      tx.oncomplete = res; tx.onerror = () => rej(tx.error); }); return performance.now() - t; };
  const get = async () => { const t = performance.now(); const v = await new Promise((res, rej) => {
      const tx = db.transaction('c', 'readonly'); const r = tx.objectStore('c').get('k');
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); }); return [performance.now() - t, v]; };
  const tIdbPutHtml = await put(html);
  const [tIdbGetHtml] = await get();
  const tIdbPutJson = await put(logs);          // structured clone, без JSON.stringify
  const [tIdbGetJson] = await get();

  chat.innerHTML = '';
  return {name, msgs: logs.length, raw, htmlBytes, nodes, nodes2,
          tFetch, tRender, tSerialize, tInject, tLayout, tTail,
          tMarked: mk, tPurify: pf, tHljs: hl, codeBlocks: blocks.length, textMsgs: texts.length,
          tIdbPutHtml, tIdbGetHtml, tIdbPutJson, tIdbGetJson};
}
"""


async def main():
    agents = json.loads(sys.argv[1])
    out = []
    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await br.new_context(
            viewport={"width": 1600, "height": 1000},
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"})
        page = await ctx.new_page()
        page.on("console", lambda m: None)
        await page.goto(BASE)
        await page.wait_for_function("typeof addChatEntry === 'function'", timeout=30000)
        await page.wait_for_timeout(3000)
        for a in agents:
            for rep in range(3):
                r = await page.evaluate(MEASURE, a)
                r["rep"] = rep
                out.append(r)
        await br.close()
    print(json.dumps(out, ensure_ascii=False))


asyncio.run(main())
