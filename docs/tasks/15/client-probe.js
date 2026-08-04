// 1. Открой дашборд, дождись, пока прогрузится чат любого агента. Нажми F12 → вкладка Console.
// 2. Вставь сюда весь этот файл и нажми Enter. Скрипт скажет «ПЕРЕКЛЮЧИСЬ НА ДРУГОЕ ОКНО».
// 3. Сверни браузер ровно на минуту, вернись и пришли строку, начинающуюся на RESULT.
//
// Скрипт только читает: те же GET-запросы, которые дашборд делает сам. Твой чат остаётся
// как был. Всего ~80 секунд, из них минуту он просто ждёт, пока вкладка свёрнута.
// Единственный побочный эффект: если ровно в эти доли секунды агент напишет новое
// сообщение, оно не появится на экране, пока не переключишься на другого агента и обратно.
// В базе оно при этом никуда не денется.
(async () => {
  const R = {ua: navigator.userAgent.slice(0, 80), cores: navigator.hardwareConcurrency,
             mem: navigator.deviceMemory || null, dpr: devicePixelRatio};
  const round = (x) => +x.toFixed(1);

  // ── ЧАСТЬ 1: во сколько раз этот процессор медленнее серверного ──
  const spin = () => { const t = performance.now(); let x = 0;
    for (let i = 0; i < 3e6; i++) x += Math.sqrt(i); return performance.now() - t; };
  spin();
  R.cpuSpinMs = round(Math.min(spin(), spin(), spin()));

  // ── ЧАСТЬ 2: чего стоила загрузка страницы на этом канале ──
  const nav = performance.getEntriesByType('navigation')[0];
  R.nav = nav ? {ttfb: Math.round(nav.responseStart - nav.requestStart),
                 domReady: Math.round(nav.domContentLoadedEventEnd),
                 load: Math.round(nav.loadEventEnd)} : null;
  const res = performance.getEntriesByType('resource');
  const stat = res.filter(r => /\.(js|css)(\?|$)/.test(r.name));
  R.assets = {count: stat.length,
              transfer: stat.reduce((a, r) => a + r.transferSize, 0),
              decoded: stat.reduce((a, r) => a + r.decodedBodySize, 0),
              fromCache: stat.filter(r => r.transferSize === 0).length,
              versioned: stat.filter(r => r.name.includes('?v=')).length,
              maxTtfb: Math.round(Math.max(...stat.map(r => r.responseStart - r.requestStart), 0))};

  // ── ЧАСТЬ 3: сеть и рендер истории (дыра из #8) ──
  const scope = (typeof currentScope !== 'undefined' && currentScope) || null;
  const agent = (typeof selectedAgent !== 'undefined' && selectedAgent) || null;
  R.agent = agent;
  if (agent && scope && typeof addChatEntry === 'function') {
    const q = new URLSearchParams({scope, before_id: String(2 ** 31 - 1), limit: '100'});
    const u = `/api/sessions/${encodeURIComponent(agent)}/logs?${q}`;
    const t0 = performance.now();
    const logs = await (await fetch(u, {cache: 'no-store'})).json();
    R.logsFetchMs = Math.round(performance.now() - t0);
    const e = performance.getEntriesByName(location.origin + u).pop();
    R.logsBytes = e ? {transfer: e.transferSize, decoded: e.decodedBodySize,
                       ttfb: Math.round(e.responseStart - e.requestStart)} : null;
    R.msgs = Array.isArray(logs) ? logs.length : 0;

    if (Array.isArray(logs) && logs.length) {
      // Настоящий чат не трогаем вовсе: переименовываем его и подставляем двойника с
      // id="chat" за экраном. addChatEntry ищет элемент через #chat, поэтому рисует
      // в двойника. Иначе пришлось бы перетирать innerHTML живого чата, а на него
      // ссылаются streamBubble и позиция прочитанного — они бы указывали в никуда.
      const real = document.querySelector('#chat');
      const savedFlag = window.scrollAfterLoad;
      const box = document.createElement('div');
      box.style.cssText = 'position:fixed;left:-99999px;top:0;width:800px;height:600px;overflow:auto';
      document.body.appendChild(box);
      const chat = document.createElement('div');
      chat.id = 'chat';
      chat.style.cssText = 'position:fixed;left:-99999px;top:0;width:800px;height:600px;overflow:auto';
      real.id = 'chat-parked-by-probe';
      real.parentNode.insertBefore(chat, real);
      try {
        window.scrollAfterLoad = false;
        const r0 = performance.now();
        for (const l of logs) { try { addChatEntry(l.type, l.content, l.ts, null, l); } catch (_) {} }
        void chat.scrollHeight;
        R.renderAllMs = Math.round(performance.now() - r0);
        const html = chat.innerHTML;
        R.htmlBytes = new TextEncoder().encode(html).length;
        chat.innerHTML = '';
        const i0 = performance.now(); box.innerHTML = html; void box.scrollHeight;
        R.injectHtmlMs = Math.round(performance.now() - i0);
        const p0 = performance.now();
        for (const l of logs.slice(-20)) { try { addChatEntry(l.type, l.content, l.ts, null, l); } catch (_) {} }
        void chat.scrollHeight;
        R.renderTail20Ms = Math.round(performance.now() - p0);
        const bodies = logs.map(l => String(l.content ?? ''));
        let t = performance.now(); const mds = bodies.map(x => marked.parse(x));
        R.markedMs = Math.round(performance.now() - t);
        t = performance.now(); const safe = mds.map(h => DOMPurify.sanitize(h));
        R.purifyMs = Math.round(performance.now() - t);
        box.innerHTML = safe.join('');
        const blocks = [...box.querySelectorAll('pre code')];
        t = performance.now(); blocks.forEach(b => { try { hljs.highlightElement(b); } catch (_) {} });
        R.hljsMs = Math.round(performance.now() - t); R.codeBlocks = blocks.length;
      } catch (err) { R.renderError = `${err.name}: ${err.message}`; }
      box.remove();
      chat.remove();
      real.id = 'chat';
      window.scrollAfterLoad = savedFlag;
      // Перерисовывать чат тут НЕЛЬЗЯ: зеркало держит последние 20 строк, и перерисовка
      // ужала бы видимую историю с 60 узлов до 11. Настоящий чат всё это время стоял
      // припаркованным и не менялся — его и оставляем.
      R.chatRestored = document.querySelector('#chat') === real && !document.querySelector('#chat-parked-by-probe');
      R.chatNodes = real.children.length;
    }
  } else {
    R.skippedRender = 'чат не открыт или страница не догрузилась';
  }

  // ── ЧАСТЬ 4: цена и потолок локального хранилища ──
  try {
    const db = await new Promise((res, rej) => { const q = indexedDB.open('probe15', 1);
      q.onupgradeneeded = () => q.result.createObjectStore('c');
      q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
    const blob = 'x'.repeat(400 * 1024);
    let t = performance.now();
    await new Promise((res, rej) => { const tx = db.transaction('c', 'readwrite');
      tx.objectStore('c').put(blob, 'k'); tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
    R.idbPut400kMs = round(performance.now() - t);
    t = performance.now();
    await new Promise((res, rej) => { const tx = db.transaction('c', 'readonly');
      const r = tx.objectStore('c').get('k'); r.onsuccess = res; r.onerror = () => rej(r.error); });
    R.idbGet400kMs = round(performance.now() - t);
    db.close(); indexedDB.deleteDatabase('probe15');
    if (navigator.storage?.estimate) { const q = await navigator.storage.estimate();
      R.storageQuotaMB = Math.round(q.quota / 1048576); R.storageUsedMB = round(q.usage / 1048576); }
  } catch (e) { R.idbError = `${e.name}: ${e.message}`; }

  // ── ЧАСТЬ 5: главное. Идут ли таймеры, когда вкладка свёрнута (дыра из #15) ──
  console.log('%c⏱ ПЕРЕКЛЮЧИСЬ НА ДРУГОЕ ОКНО НА МИНУТУ И ВЕРНИСЬ',
              'font-size:16px;font-weight:bold;color:#f59e0b');
  const T0 = performance.now();
  let ticks = 0, last = T0, maxGap = 0, hiddenMs = 0, hidAt = null, switches = 0;
  const onVis = () => {
    if (document.hidden) { hidAt = performance.now(); switches++; }
    else if (hidAt !== null) { hiddenMs += performance.now() - hidAt; hidAt = null; }
  };
  document.addEventListener('visibilitychange', onVis);
  const id = setInterval(() => {
    const now = performance.now();
    maxGap = Math.max(maxGap, now - last); last = now; ticks++;
  }, 3000);
  await new Promise(r => setTimeout(r, 62000));
  clearInterval(id);
  document.removeEventListener('visibilitychange', onVis);
  if (hidAt !== null) hiddenMs += performance.now() - hidAt;

  const elapsed = performance.now() - T0;
  R.hidden = {elapsedMs: Math.round(elapsed), hiddenMs: Math.round(hiddenMs),
              switches, ticks, expectedTicks: Math.round(elapsed / 3000),
              maxGapMs: Math.round(maxGap)};
  R.hiddenVerdict = hiddenMs < 5000
    ? 'НЕ ПРОВЕРЕНО — вкладка не сворачивалась, прогони ещё раз и сверни окно'
    : (maxGap > 15000 ? 'таймеры тормозятся в фоне' : 'таймеры в фоне идут штатно');

  console.log('RESULT ' + JSON.stringify(R));
  return R;
})();
