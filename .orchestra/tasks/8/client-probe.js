/* #8 — клиентский замер. Вставить в DevTools Console на открытом дашборде
   (https://orchestra.seedon.ru), дождаться строки RESULT и прислать её целиком.
   Только чтение: GET-запросы к тем же эндпоинтам, которые дашборд и так дёргает. */
(async () => {
  const R = {ua: navigator.userAgent.slice(0, 80), cores: navigator.hardwareConcurrency,
             mem: navigator.deviceMemory || null, dpr: devicePixelRatio};

  // 1. CPU: во сколько раз этот браузер медленнее эталона (чистый счёт, без сети)
  const spin = () => { const t = performance.now(); let x = 0;
    for (let i = 0; i < 3e6; i++) x += Math.sqrt(i); return performance.now() - t; };
  spin(); R.cpuSpinMs = +Math.min(spin(), spin(), spin()).toFixed(1);

  // 2. Что уже загружено: сколько байт и сколько времени стоила загрузка страницы
  const nav = performance.getEntriesByType('navigation')[0];
  R.nav = nav ? {ttfb: +(nav.responseStart - nav.requestStart).toFixed(0),
                 domReady: +nav.domContentLoadedEventEnd.toFixed(0),
                 load: +nav.loadEventEnd.toFixed(0)} : null;
  const res = performance.getEntriesByType('resource');
  const pick = (re) => res.filter(r => re.test(r.name)).map(r => ({
      n: r.name.split('/').pop().split('?')[0].slice(0, 28),
      transfer: r.transferSize, decoded: r.decodedBodySize,
      ttfb: +(r.responseStart - r.requestStart).toFixed(0), dur: +r.duration.toFixed(0)}));
  R.assets = pick(/\.(js|css)(\?|$)/);
  R.apiSamples = pick(/\/api\/(sessions|stats|models)/).slice(-4);

  // 3. Сеть на истории: тот же агент двумя путями — gzip JSON против несжатого SSE
  const scope = (typeof currentScope !== 'undefined' && currentScope) || null;
  const agent = (typeof selectedAgent !== 'undefined' && selectedAgent) || null;
  R.agent = agent; R.scope = scope;
  if (agent && scope) {
    const q = new URLSearchParams({scope, before_id: String(2 ** 31 - 1), limit: '100'});
    const u = `/api/sessions/${encodeURIComponent(agent)}/logs?${q}`;
    const t0 = performance.now();
    const logs = await (await fetch(u, {cache: 'no-store'})).json();
    R.logsFetchMs = +(performance.now() - t0).toFixed(0);
    const e = performance.getEntriesByName(location.origin + u).pop();
    R.logsBytes = e ? {transfer: e.transferSize, decoded: e.decodedBodySize,
                       ttfb: +(e.responseStart - e.requestStart).toFixed(0)} : null;
    R.msgs = Array.isArray(logs) ? logs.length : 0;

    // 4. Рендер: полный прогон боевого addChatEntry против готового HTML
    if (Array.isArray(logs) && logs.length) {
      const box = document.createElement('div');
      box.style.cssText = 'position:fixed;left:-99999px;top:0;width:800px;height:600px;overflow:auto';
      document.body.appendChild(box);
      const chat = document.querySelector('#chat');
      const stash = chat.innerHTML, saved = window.scrollAfterLoad;
      window.scrollAfterLoad = false;
      chat.innerHTML = '';
      const r0 = performance.now();
      for (const l of logs) { try { addChatEntry(l.type, l.content, l.ts, null, l); } catch (e) {} }
      void chat.scrollHeight;
      R.renderAllMs = +(performance.now() - r0).toFixed(0);
      const html = chat.innerHTML;
      R.htmlBytes = new TextEncoder().encode(html).length;
      chat.innerHTML = '';
      const i0 = performance.now(); box.innerHTML = html; void box.scrollHeight;
      R.injectHtmlMs = +(performance.now() - i0).toFixed(0);
      const t20 = logs.slice(-20);
      const p0 = performance.now();
      for (const l of t20) { try { addChatEntry(l.type, l.content, l.ts, null, l); } catch (e) {} }
      void chat.scrollHeight;
      R.renderTail20Ms = +(performance.now() - p0).toFixed(0);
      const bodies = logs.map(l => String(l.content ?? ''));
      let t = performance.now(); const mds = bodies.map(x => marked.parse(x));
      R.markedMs = +(performance.now() - t).toFixed(0);
      t = performance.now(); const safe = mds.map(h => DOMPurify.sanitize(h));
      R.purifyMs = +(performance.now() - t).toFixed(0);
      box.innerHTML = safe.join('');
      const blocks = [...box.querySelectorAll('pre code')];
      t = performance.now(); blocks.forEach(b => { try { hljs.highlightElement(b); } catch (e) {} });
      R.hljsMs = +(performance.now() - t).toFixed(0); R.codeBlocks = blocks.length;
      box.remove();
      chat.innerHTML = stash; window.scrollAfterLoad = saved;   // вернули как было
    }
  }

  // 5. IndexedDB: цена персистентного хранилища на этой машине
  try {
    const db = await new Promise((res, rej) => { const q = indexedDB.open('m8probe', 1);
      q.onupgradeneeded = () => q.result.createObjectStore('c');
      q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
    const blob = 'x'.repeat(400 * 1024);
    let t = performance.now();
    await new Promise((res, rej) => { const tx = db.transaction('c', 'readwrite');
      tx.objectStore('c').put(blob, 'k'); tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
    R.idbPut400kMs = +(performance.now() - t).toFixed(1);
    t = performance.now();
    await new Promise((res, rej) => { const tx = db.transaction('c', 'readonly');
      const r = tx.objectStore('c').get('k'); r.onsuccess = res; r.onerror = () => rej(r.error); });
    R.idbGet400kMs = +(performance.now() - t).toFixed(1);
    db.close(); indexedDB.deleteDatabase('m8probe');
    if (navigator.storage?.estimate) { const e = await navigator.storage.estimate();
      R.storageQuotaMB = +(e.quota / 1048576).toFixed(0); R.storageUsedMB = +(e.usage / 1048576).toFixed(1); }
  } catch (e) { R.idbError = String(e); }

  console.log('RESULT ' + JSON.stringify(R));
  return R;
})();
