# Context for item-24

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index f497c203c..70da73ee4 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1433,65 +1433,70 @@ function _showDropHint(input) {
     input.classList.add('border-indigo-400');
 }
 
 function _showChatDropError(message) {
     const existing = $('#chat-drop-error');
     if (!message) {
         existing?.remove();
         return;
     }
     const error = existing || document.createElement('div');
     if (!existing) {
         error.id = 'chat-drop-error';
         error.className = 'text-xs text-red-400 px-1 pb-1';
         error.setAttribute('role', 'alert');
         const inputRow = $('#chat-input').parentElement;
         inputRow.parentElement.insertBefore(error, inputRow);
     }
     error.textContent = message;
 }
 
-function _appendDroppedPath(input, path, url) {
-    // Присваивание value уводит каретку в конец — юзер в этот момент печатает,
-    // поэтому позицию возвращаем на место
-    const {selectionStart, selectionEnd} = input;
-    const focused = document.activeElement === input;
-    input.value += (input.value ? '\n' : '') + path;
+function _insertPathAtCaret(input, path, url) {
+    // Путь встаёт туда, где каретка (заменяя выделение): юзер в этот момент печатает,
+    // и дописывание в конец уводило бы его текст ЗА путь
+    const start = input.selectionStart ?? input.value.length;
+    const end = input.selectionEnd ?? start;
+    const before = input.value.slice(0, start);
+    const after = input.value.slice(end);
+    const prefix = before && !before.endsWith('\n') ? '\n' : '';
+    const suffix = after && !after.startsWith('\n') ? '\n' : '';
+    input.value = before + prefix + path + suffix + after;
+    const caret = before.length + prefix.length + path.length;
     input.focus();
-    if (focused) input.setSelectionRange(selectionStart, selectionEnd);
+    input.setSelectionRange(caret, caret);
     pastedImages.push(url);
     showImagePreview(url, path);
 }
 
 async function _handleChatDrop(input, dataTransfer) {
     _showChatDropError('');
     const files = [...(dataTransfer?.files || [])];
     if (files.length) {
         for (const file of files) await _trackUpload(_uploadToChat(file, file.name));
         input.focus();
         return;
     }
     const path = dataTransfer?.getData('text/plain');
     if (!path) return;
     const url = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(path)
         ? `/api/files/raw?path=${encodeURIComponent(path)}` : path;
-    _appendDroppedPath(input, path, url);
+    _insertPathAtCaret(input, path, url);
 }
 
 function _hasDropType(dataTransfer, type) {
     return [...(dataTransfer?.types || [])].includes(type);
 }
 
 function _isChatDrop(dataTransfer) {
     return _hasDropType(dataTransfer, 'Files') || _hasDropType(dataTransfer, 'text/plain');
 }
 
 function initChatDrop() {
     document.addEventListener('dragenter', (e) => {
         const input = e.target.closest?.('#chat-input');
         if (!input || !_isChatDrop(e.dataTransfer)) return;
         _dropDragCounter++;
         _showDropHint(input);
     });
     document.addEventListener('dragleave', (e) => {
         if (!e.target.closest?.('#chat-input')) return;
         _dropDragCounter--;
@@ -2607,41 +2612,41 @@ function _trackUpload(promise) {
 }
 
 // Одна дорога для paste и drop: ошибку показываем строкой над полем ввода,
 // путь ДОПИСЫВАЕМ в textarea и только после ответа сервера. Трогать input.value
 // во время загрузки нельзя — юзер в это время печатает, и его текст пропадёт.
 async function _uploadToChat(file, filename) {
     const promise = (async () => {
         const formData = new FormData();
         formData.append('file', file, filename);
         // Без таймаута зависший аплоад навсегда запер бы отправку в sendChat
         const resp = await fetch('/api/upload', { method: 'POST', body: formData,
                                                   signal: AbortSignal.timeout(60000) });
         const data = resp.headers.get('content-type')?.includes('application/json')
             ? await resp.json() : {};
         if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
         if (!data.path) throw new Error('server returned no file path');
         return data;
     })();
     try {
         const data = await promise;
-        _appendDroppedPath($('#chat-input'), data.path, data.url || data.path);
+        _insertPathAtCaret($('#chat-input'), data.path, data.url || data.path);
         return data;
     } catch (error) {
         // У TimeoutError и сетевых ошибок message бывает пустой — печатаем и класс.
         // Дописываем к уже показанной ошибке: при дропе пачки файлов упасть может не один
         const detail = `${filename}: ${error.name}: ${error.message}`;
         const shown = $('#chat-drop-error')?.textContent;
         _showChatDropError(shown ? `${shown}; ${detail}` : `Upload failed — ${detail}`);
         return null;
     }
 }
 
 // Аплоад с машины юзера идёт на 53-82 КБ/с (замер оттуда же): типичный retina-скриншот
 // 667 КБ ползёт 12 с, и это упирается в канал, а не в сервер — единственный способ
 // ускорить — отправить меньше байтов. WebP q=0.9 даёт 354 КБ (1.9×) при PSNR 38.6 дБ:
 // на кропе 1:1 текст неотличим от оригинала. Цифры — docs/tasks/5/report.md.
 // Только для вставки из буфера: дропнутый файл юзер выбрал сам, его формат не наш.
 const _COMPRESS_MIN_BYTES = 100 * 1024;  // мельче — экономия секунды не стоит работы CPU
 
 async function _compressScreenshot(file) {
     if (file.size < _COMPRESS_MIN_BYTES) return {blob: file, ext: 'png'};
@@ -5774,47 +5779,43 @@ function _createFileItem(f, container) {
             if (expanded && children.children.length === 0) {
                 await loadFileTree(f.path, children);
             }
             children.classList.toggle('hidden', !expanded);
             item.textContent = `${expanded ? '📂' : '📁'} ${f.name}`;
             _saveExpandedFolder(f.path, expanded);
         });
         const wrapper = document.createElement('div');
         wrapper.appendChild(item);
         wrapper.appendChild(children);
         return wrapper;
     } else {
         item.textContent = `${getFileIcon(f.name, false)} ${f.name}`;
         item.style.position = 'relative';
         const sendBtn = document.createElement('span');
         sendBtn.textContent = '➜';
         sendBtn.title = 'Send path to chat';
         sendBtn.style.cssText = 'position:absolute;right:4px;top:1px;opacity:0;cursor:pointer;font-size:11px;color:#818cf8;transition:opacity 0.15s';
         sendBtn.addEventListener('click', (e) => {
             e.stopPropagation();
-            const input = $('#chat-input');
-            input.value += (input.value ? '\n' : '') + f.path;
-            input.focus();
             const url = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(f.path)
                 ? `/api/files/raw?path=${encodeURIComponent(f.path)}` : f.path;
-            pastedImages.push(url);
-            showImagePreview(url, f.path);
+            _insertPathAtCaret($('#chat-input'), f.path, url);
         });
         item.appendChild(sendBtn);
         item.addEventListener('mouseenter', () => sendBtn.style.opacity = '1');
         item.addEventListener('mouseleave', () => sendBtn.style.opacity = '0');
         item.addEventListener('click', () => openFilePreview(f.path));
         return item;
     }
 }
 
 async function _refreshContainer(container, dirPath) {
     try {
         const files = await api(`/api/files?path=${encodeURIComponent(dirPath)}`);
         const newPaths = new Set(files.map(f => f.path));
         const existing = new Map();
         for (const child of [...container.children]) {
             const p = child.dataset?.path || child.querySelector?.('[data-path]')?.dataset?.path;
             if (p) existing.set(p, child); else child.remove();
         }
         for (const [p, el] of existing) {
             if (!newPaths.has(p)) el.remove();
diff --git a/docs/tasks/94/caret-insert.png b/docs/tasks/94/caret-insert.png
new file mode 100644
index 000000000..bbdee5298
Binary files /dev/null and b/docs/tasks/94/caret-insert.png differ
diff --git a/docs/tasks/94/report.md b/docs/tasks/94/report.md
new file mode 100644
index 000000000..dde1007c0
--- /dev/null
+++ b/docs/tasks/94/report.md
@@ -0,0 +1,56 @@
+# #94 — путь картинки вставляется в позицию каретки
+
+Жалоба юзера: «когда вставляю картинку надо чтобы до курсора вставлялась а не перед».
+
+## Что было
+
+`_appendDroppedPath` (`app/static/js/app.js:1453`) дописывал путь в КОНЕЦ (`input.value += …`)
+и возвращал каретку на прежнее место. Юзер печатал в начале строки → продолжал печатать
+ПЕРЕД путём, а путь болтался хвостом. Та же строка была продублирована в обработчике
+кнопки ➜ файлового дерева (`:5795`).
+
+## Что стало
+
+`_insertPathAtCaret(input, path, url)` — один владелец на все три входа (drop, аплоад из
+буфера, кнопка ➜). Путь режет значение по выделению: `before + '\n'? + path + '\n'? + after`,
+разделитель добавляется только если сосед с этой стороны непустой и сам не перевод строки —
+поэтому путь не слипается ни с текстом, ни сам с собой при дропе пачки файлов. Каретка
+встаёт сразу ЗА путём (перед нижним разделителем), фокус в поле.
+
+Кнопка ➜ перестала быть копией: она теперь считает `url` и зовёт ту же функцию.
+
+## Проверка (живой :8888, Playwright, `docs/tasks/94/verify-caret.py`)
+
+`app.js` подменён файлом из worktree через `page.route`, счётчик срабатываний напечатан
+(`app.js=1`), факт применения — `typeof _insertPathAtCaret = function`. `/api/upload`
+перехвачен, чтобы не писать мусор в `data/uploads/` живого сервера.
+
+| кейс | было в поле | стало |
+|---|---|---|
+| каретка в СЕРЕДИНЕ | `посмотри сюда`, caret 9 | `посмотри \n<path>\nсюда`, caret 52 = сразу за путём |
+| дописал «ещё» после вставки | — | `посмотри \n<path>ещё\nсюда` — продолжение ПОСЛЕ пути |
+| поле ПУСТОЕ | `` | `<path>` (как раньше) |
+| каретка в КОНЦЕ | `хвост`, caret 5 | `хвост\n<path>` (регресса нет) |
+| ВЫДЕЛЕНИЕ | `убери это слово`, 6..9 | `убери \n<path>\n слово` |
+| кнопка ➜ в дереве | `файл тут`, caret 5 | `файл \n/home/kesha/orchestra/.dockerignore\nтут` |
+
+13/13 проверок зелёные, ошибок в консоли ноль. Скриншот — `caret-insert.png`.
+
+**Мутация:** возврат строки к `input.value += (input.value ? '\n' : '') + path` роняет
+6 из 13 проверок живого прогона и новый pytest (`tests/test_frontend.py:442`); откат мутации —
+обратной точечной заменой.
+
+## Регресс-тест
+
+`tests/test_frontend.py::test_dropped_path_lands_at_caret_not_at_end` — вырезает
+`_insertPathAtCaret` из `app.js` и гоняет на настоящем `<textarea>` четыре кейса. Синхронный,
+без аплоада → без гонок. Существующий `test_chat_drop_handles_files_tree_paths_and_upload_errors`
+остаётся зелёным (его падение 1 из 3 — известный wall-clock флак, `docs/tasks/17/report.md`).
+
+## Проверенный edge, который выглядел риском
+
+Восстановление черновика при переключении агента (`app.js:510`) кладёт текст в поле
+программно, без фокуса. Спека HTML требует ставить каретку в КОНЕЦ при присваивании `value` —
+проверено на живой странице: `value.length = 24, selectionStart = 24, focused = false`.
+Значит «черновик восстановлен, юзер жмёт ➜» даёт путь в конце, ровно как до правки; вставки
+в начало чужого текста не будет.
diff --git a/docs/tasks/94/verify-caret.py b/docs/tasks/94/verify-caret.py
new file mode 100644
index 000000000..78933f5bf
--- /dev/null
+++ b/docs/tasks/94/verify-caret.py
@@ -0,0 +1,157 @@
+#!/usr/bin/env python3
+"""#94 — путь картинки встаёт в позицию каретки, а не в конец поля.
+
+Живой :8888 отдаёт статику из ОСНОВНОГО чекаута, поэтому `app.js` подменяем на файл
+из worktree через `page.route` и печатаем СЧЁТЧИК срабатываний: без него неработающий
+перехват дал бы зелёную проверку прода вместо моей правки. Факт применения — `typeof
+_insertPathAtCaret` в рантайме.
+
+`/api/upload` тоже перехвачен: путь возвращаем сами, чтобы не писать мусор в
+`data/uploads/` живого сервера. После вставки допечатываем «ещё» — так видно, что
+юзер продолжает писать ПОСЛЕ пути, а не перед ним (в этом и была жалоба).
+
+Запуск:  python3 docs/tasks/94/verify-caret.py
+"""
+import json
+
+from playwright.sync_api import sync_playwright
+
+WT = "/home/kesha/orchestra/worktrees/home-kesha-orchestra/frontend"
+BASE = "http://127.0.0.1:8888"
+APP_JS = open(f"{WT}/app/static/js/app.js", encoding="utf-8").read()
+
+env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env")
+           if "=" in l and not l.startswith("#"))
+USER, PWD = env["DASHBOARD_USER"].strip(), env["DASHBOARD_PASSWORD"].strip()
+
+hits = {"app_js": 0, "upload": 0}
+READ_INPUT = """() => {
+    const i = document.querySelector('#chat-input');
+    return {value: i.value, start: i.selectionStart, end: i.selectionEnd,
+            focused: document.activeElement === i};
+}"""
+UPLOADED = "/home/kesha/orchestra/data/uploads/pic.png"
+
+
+def run_case(page, title, before_text, caret, select_to=None, type_after=True):
+    """Ставит текст и каретку/выделение, дропает файл, возвращает состояние поля."""
+    page.evaluate(
+        """([text, start, end]) => {
+            const i = document.querySelector('#chat-input');
+            i.value = text; i.focus(); i.setSelectionRange(start, end);
+        }""",
+        [before_text, caret, select_to if select_to is not None else caret],
+    )
+    # настоящий drop с файлом — тот же путь, что у вставки из буфера (_uploadToChat)
+    page.evaluate("""() => {
+        const i = document.querySelector('#chat-input');
+        const dt = new DataTransfer();
+        dt.items.add(new File([new Uint8Array([137,80,78,71])], 'pic.png', {type: 'image/png'}));
+        i.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
+    }""")
+    page.wait_for_function(
+        "() => document.querySelector('#chat-input').value.includes('pic.png')", timeout=15000)
+    state = page.evaluate(READ_INPUT)
+    print(f"\n--- {title}")
+    print(f"  было:  {before_text!r}  каретка {caret}"
+          + (f"..{select_to}" if select_to is not None else ""))
+    print(f"  стало: {state['value']!r}")
+    print(f"  selectionStart={state['start']} end={state['end']} focused={state['focused']}")
+    if type_after:
+        page.keyboard.type("ещё")
+        state["typed"] = page.evaluate(READ_INPUT)["value"]
+        print(f"  дописал 'ещё': {state['typed']!r}")
+    return state
+
+
+def main():
+    with sync_playwright() as p:
+        browser = p.chromium.launch()
+        page = browser.new_page(viewport={"width": 1500, "height": 950})
+        errors = []
+        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
+
+        def sub_js(route):
+            hits["app_js"] += 1
+            route.fulfill(status=200, content_type="application/javascript; charset=utf-8",
+                          body=APP_JS)
+
+        def sub_upload(route):
+            hits["upload"] += 1
+            route.fulfill(status=200, content_type="application/json",
+                          body=json.dumps({"path": UPLOADED, "url": "/static/favicon.ico"}))
+
+        page.route("**/static/js/app.js*", sub_js)
+        page.route("**/api/upload", sub_upload)
+
+        page.goto(f"{BASE}/", wait_until="domcontentloaded")
+        page.fill('input[name="username"]', USER)
+        page.fill('input[name="password"]', PWD)
+        page.click('button[type="submit"]')
+        page.wait_for_selector("#chat-input", timeout=20000)
+
+        applied = page.evaluate("() => typeof _insertPathAtCaret")
+        print(f"перехват app.js сработал раз: {hits['app_js']}; "
+              f"typeof _insertPathAtCaret = {applied}")
+        assert applied == "function", "подмена не применилась — дальше мерили бы прод"
+
+        results = {}
+        results["середина"] = run_case(page, "каретка в СЕРЕДИНЕ", "посмотри сюда", 9)
+        results["пусто"] = run_case(page, "поле ПУСТОЕ", "", 0, type_after=False)
+        results["конец"] = run_case(page, "каретка в КОНЦЕ", "хвост", 5)
+        results["выделение"] = run_case(page, "ВЫДЕЛЕНИЕ заменяется", "убери это слово",
+                                        6, 9, type_after=False)
+
+        # второй путь вставки — кнопка ➜ в файловом дереве (было продублировано, теперь общее)
+        page.wait_for_selector("#file-tree span[title='Send path to chat']", timeout=20000)
+        page.evaluate("""() => {
+            const i = document.querySelector('#chat-input');
+            i.value = 'файл тут'; i.focus(); i.setSelectionRange(5, 5);
+        }""")
+        btn = page.locator("#file-tree span[title='Send path to chat']").first
+        btn.hover()
+        btn.click()
+        tree_state = page.evaluate(READ_INPUT)
+        print(f"\n--- кнопка ➜ в дереве; было 'файл тут' каретка 5")
+        print(f"  стало: {tree_state['value']!r}  selectionStart={tree_state['start']}")
+
+        page.screenshot(path=f"{WT}/docs/tasks/94/caret-insert.png")
+
+        print(f"\nперехватов: app.js={hits['app_js']}, /api/upload={hits['upload']}")
+        print(f"ошибок в консоли: {errors or 'нет'}")
+
+        # --- приёмка ---
+        checks = []
+        for name, r in results.items():
+            pos = r["value"].find(UPLOADED)
+            checks.append((f"[{name}] каретка сразу после пути",
+                           pos >= 0 and r["start"] == pos + len(UPLOADED)
+                           and r["end"] == r["start"]))
+        mid = results["середина"]
+        checks.append(("путь ПЕРЕД хвостом, не в конце", mid["value"].startswith("посмотри")
+                       and mid["value"].rstrip().endswith("сюда")))
+        checks.append(("путь не слипся с соседями",
+                       f"\n{UPLOADED}\n" in mid["value"]))
+        checks.append(("продолжение печатается ПОСЛЕ пути, не перед",
+                       mid["typed"] == f"посмотри \n{UPLOADED}ещё\nсюда"))
+        checks.append(("пустое поле — только путь", results["пусто"]["value"] == UPLOADED))
+        checks.append(("каретка в конце — как раньше (регресса нет)",
+                       results["конец"]["value"] == f"хвост\n{UPLOADED}"))
+        sel = results["выделение"]
+        checks.append(("выделение заменено", sel["value"] == f"убери \n{UPLOADED}\n слово"))
+        checks.append(("фокус в поле", all(r["focused"] for r in results.values())))
+        tpath = tree_state["value"][5:].split("\n")[1]
+        checks.append(("кнопка ➜ вставила в каретку",
+                       tree_state["value"] == f"файл \n{tpath}\nтут"
+                       and tree_state["start"] == 5 + 1 + len(tpath)))
+        checks.append(("нет ошибок в консоли", not errors))
+
+        print()
+        for name, ok in checks:
+            print(f"  {'OK  ' if ok else 'FAIL'} {name}")
+        print("\nИТОГ:", "всё зелёное" if all(ok for _, ok in checks) else "ЕСТЬ ПАДЕНИЯ")
+        browser.close()
+
+
+if __name__ == "__main__":
+    main()
diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index c9bcf3432..607a640c6 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -26,36 +26,36 @@
 - `opts.signal || AbortSignal.timeout(...)` — ловушка: свой signal вызывающего МОЛЧА отменяет таймаут, и зависший ответ висит вечно. Комбинировать через `AbortSignal.any([opts.signal, timeout])`, а свой бюджет давать параметром (`timeoutMs`), а не собственным signal — одна ручка вместо двух.
 - Проверяя «залип ли цикл опроса», нельзя смотреть на флаг занятости (`refreshInProgress`): он одинаков у залипшего захода и у нового. Считать ЧИСЛО ПОПЫТОК запроса — оно различает исходы.
 - **Браузерный scroll anchoring шлёт НАСТОЯЩЕЕ событие `scroll`.** Когда содержимое над вьюпортом меняет высоту, браузер сам подкручивает `scrollTop` (замер: высота +1326 px, позиция уехала +328 без единой нашей записи). Отличить это от юзера по позиции или дельте нельзя — событие подлинное. Значит «юзер ушёл вверх» определять ТОЛЬКО по вводу (`wheel`, `touchmove`, `keydown`, `pointerdown`, плюс пересчёт на `pointerup`/`touchend`), а не по геометрии в обработчике `scroll`. `overflow-anchor: none` не лечение: в сценарии «читаю выше» автоякорь работает на нас, выключишь — разменяешь один рывок на другой.
 - Как только логика завязана на ввод юзера, зонд обязан слать НАСТОЯЩИЙ ввод: `page.mouse.wheel` вместо `chat.scrollTop = 150`. Программная запись перестаёт что-либо проверять — и зелёный прогон означает лишь, что код игнорирует то, чего в жизни не бывает.
 - Красный тест ≠ сломанный код: `test_chat_drop_handles_files_tree_paths_and_upload_errors` упал один раз на гонке аплоада и прошёл 3/3 подряд. Симметрично правилу про зелёное на асинхронном коде — прогони трижды, прежде чем чинить чужой тест.
 - **`page.route` выключает HTTP-кеш браузера целиком.** Это мой основной способ проверки ветки, и он даёт достоверными ЧИСЛО ЗАПРОСОВ и ПОВЕДЕНИЕ, но не байты статики и не тайминги: статика перекачивается в каждом заходе, подменённый файл едет несжатым. Мерить время до первого экрана под перехватом бессмысленно — просить замер после мержа, без подмены. Байты API при этом честные: динамические ответы не кешируются.
 - Любую цифру запросов писать ВМЕСТЕ С ОКНОМ замера («от логина до 9-й секунды»): в дашборде круг опроса идёт раз в 3 с, и на 10-секундном окне то же самое даёт 28 запросов вместо 23. Без окна два верных замера выглядят как противоречие.
 - Кеш браузера мерить только по `transferSize` из Resource Timing: событие `response` в Playwright приходит и на попадание в кеш, по числу запросов кажется, что кеш не работает. `transferSize=0` — сеть не тронута, `0 < transferSize < encodedBodySize` — 304.
 - Клиентский CPU (кодирование картинок и т.п.) на этом VPS мерить нельзя: при LA 11–19 одна и та же операция даёт 405 мс и 13.7 с. Ловить спокойный момент бесполезно — либо считать по МП из чистого замера, либо просить прогон на машине юзера. В отчёте так и писать: «не измерено», а не подставлять цифру с перегруженной машины.
 - Путь файла задан в задании → `git check-ignore -v <путь>` ДО начала работы, не на коммите. Стоит секунду на старте против потерянного хода в конце: `artifacts/` лежит в `.gitignore` (строка 18, security-коммит `0c9105f` скопом с `docs/proxy-*.md`), и готовый артефакт пришлось переносить в `docs/tasks/<id>/`. Туда же класть артефакты по умолчанию — один task = один каталог. *(на триаже у оркестратора, метит в CLAUDE.md)*
 - «Сообщения теряются», а счётчики дропов по нулям → смотри счётчик СХЛОПЫВАНИЯ, не потерь: в `tg_bridge` тулы делили `telemetry_key=(thread_id, orch_name)`, и `current.call_factory = factory` молча затирал текст предыдущего вызова (рос `telemetry_coalesced`, а `telemetry_dropped=0`). Потеря без дропа = перезапись по ключу.
 - Правишь доставку в TG — помни жёсткий потолок: **20 сообщений / 60 с** на группу (`_TG_GROUP_WINDOW_MAX`). Любое «пусть каждое событие едет своим сообщением» упирается в `rate slot unavailable`; лечится батчингом тел в одно сообщение, а не уникальными ключами. Проверять замером с `_tg_delivery_snapshot` до/после, а не логикой.
 - Меришь прод снаружи → всегда `curl --noproxy '*'` / браузер с `--no-proxy-server` (в окружении живёт `HTTPS_PROXY`, даёт +300 мс), и ОБЯЗАТЕЛЬНО контрольный хост (`cachefly.cachefly.net/1mb.test`, `seedon.ru`). Без контроля не отличишь «канал юзера плохой» от «путь до нашего VPS рвётся»: замер #142 показал 1 МБ за 0.55 с с cachefly и обрыв на 16 КБ с нашего VPS — вывод «интернет виноват» был бы ложным.
 - Свойства прода (gzip, кеш, заголовки) на локальном `127.0.0.1:8888` НЕ проверяются: сжатие делает nginx на VPS, `StaticFiles` в `app/main.py:87` отдаёт голым. Гипотезу «у нас нет gzip» я так и не подтвердил — на проде он был.
 - A/B на СЕТЕВОЙ метрике: сперва сними базу ДВАЖДЫ с паузой, потом ставь правку, потом СНИМИ правку и повтори. Односторонний тест врёт: в #143 база сама плавала 7/8 → 2/8 → 11/16 без единой правки, и любой «эффект» фикса утонул бы в этом разбросе. Правило общее для всего, что зависит от внешней среды.
 - Красивое совпадение чисел ≠ причина. `ssl_buffer_size` дефолт 16 КБ и обрыв ровно на 16384 — совпало идеально, а виноват был потерянный ретрансмит. Проверка, которая закрыла вопрос за один вызов: воспроизвести НА САМОМ сервере (`curl -k https://127.0.0.1 -H 'Host: ...'`) — локально целиком 5/5, значит ни nginx, ни TLS не режут. Делать это ДО правок конфига.
 - Копируешь соседний nginx-блок под свою задачу — сверь ДВА места: (1) апстрим по HTTPS требует `proxy_ssl_server_name on` + `proxy_ssl_name`, иначе рукопожатие уходит без SNI и апстрим отдаёт дефолтный виртуалхост; (2) `Connection "upgrade"` копировать НЕЛЬЗЯ, если проксируешь SSE — это обычный GET, нужен `Connection ""` + `proxy_buffering off` + длинный `proxy_read_timeout`. Оба места в #146 были в соседнем рабочем блоке в неподходящем для нас виде.
 - Прокси/зеркало проверяется живым потоком, а не первой пачкой: `curl -sN ... &after_id=<огромный>` должен ВИСЕТЬ 30 с с `code=200`, не закрываясь. Первые события приходят даже при сломанной буферизации — доказательство именно в том, что соединение держится и отдаёт инкрементально.
 - Прежде чем кешировать/переиспользовать куски чата — вспомни, что часть узлов ещё НЕ строки лога: черновик стрима (`streamBubble`), локальное эхо (`localMessages`), отложенный финал (`_streamDeferredFinal`). Их строка придёт позже с id > lastId → дубль, а если строку уже прочитали, выкинешь узел → потеря. Логика в `_stashChatDom`.
 - Проверяешь что-то про ЦВЕТ агента — бери сообщение ОТ ВОРКЕРА: у оркестраторов `color=""` (`app/manager.py:621`), их подпись серая всегда, и правильный фикс выглядит как «не работает» (потерял на этом прогон в #68). Палитра к тому же переиспользуется — `#818cf8` сейчас у пятерых живых агентов, так что «цвета совпали» само по себе ничего не доказывает: сверяй с полем `color` из `/api/sessions`.
-- Гонку «данные пришли позже, чем отрисовали» воспроизводить не задержкой, а ВЫРЕЗАНИЕМ поля из ответа на первые N секунд (`route.fetch()` → `s.pop("color")` → `fulfill`): страница живёт нормально, окно управляемое, и `time.sleep` в обработчике route не блокирует остальные перехваты.
+- Гонку «данные пришли позже, чем отрисовали» воспроизводить не задержкой, а ВЫРЕЗАНИЕМ поля из ответа на первые N секунд (`route.fetch()` → `s.pop("color")` → `fulfill`): страница живёт нормально, окно управляемое, и `time.sleep` в обработчике route не блокирует остальные перехваты. НО в sync-API он блокирует мои же `page.keyboard.type`/`evaluate` — они ждут того же питоновского потока. Сценарий «юзер печатает, ПОКА летит запрос» так не собрать: ввод приезжает после fulfill, и получается обратный порядок (#94, полчаса на ложные FAIL). Проверять состояние ДО и ПОСЛЕ ответа отдельными шагами, а не пытаться попасть в окно.
 - Добавил в шаблон/JS НОВЫЙ класс Tailwind → `bash scripts/build-tailwind.sh` (собранный `app/static/css/vendor/tailwind.css` коммитится). Play-CDN больше нет с #64: класса нет в сборке — стиля нет вообще, а элемент при этом отрисуется. Страж — `tests/test_tailwind_css.py`.
 - Любой временный элемент интерфейса, который снимается «успехом», надо привязывать к КОНКРЕТНОМУ пути/сущности: круг опроса раз в 3 с гонит десяток успешных мелких запросов и стирает сообщение за миллисекунды. В #70 баннер об оборванном `/api/sessions` не доживал до конца 12-секундного окна — снимался ответом соседнего эндпоинта.
 - Режешь размер ответа — сперва пережми ЖИВОЙ ответ вариантами (выброс поля, потолок content, срез строк) и напечатай вклад каждого куска: в #72 это за один прогон показало, что 114 из 123 КБ — тела сообщений, и сэкономило день на правках полей. Локальный `gzip -6` НЕ равен проводу: nginx жмёт слабее, коэффициент ×1.18 (123.1 локально против 145.5 по проводу на одном ответе) — приводить к проводу или мерить через домен.
 - Порцию сетевого ответа ограничивать И строками, И БАЙТАМИ: 25 строк лога в разных чатах дают от 5.2 до 46.6 КБ, размер сообщения гуляет на три порядка. И прогонять оценку по ВСЕМ сессиям живой БД, а не по пяти знакомым: хвост (`seo-cro` 1261.9 КБ на страницу) виден только в полном прогоне.
 - Убираешь предзагрузку/кеш, который наполнял зеркало, — найди ВСЕХ, кто на него молча опирался: строки из `_fetchHistory` в зеркало не писались, потому что свежий кусок привозила холодная синхронизация. Признак дыры: данные старше watermark, которые инкремент не принесёт никогда.
 - Мутация НЕ покраснела ≠ код верен: у функции с fallback'ом (основной признак + запасной) ломаешь первую ветку, а тесты держатся на второй и остаются зелёными. В #153 так прошла подмена `"type=local_bash" in content` → `if False`, потому что все фикстуры ловились запасной проверкой по форме id. Значит на КАЖДЫЙ признак нужен случай, где остальные признаки помочь не могут; иначе мутация проверяет не то, что кажется.
 - Таблица БД и `logs` расходятся по заполненности одного и того же поля: в `subagents` `task_type` был непустым у всех 3284 строк, а в `logs` у части `subagent_end` он пуст. Классификатор, проверенный по таблице, на логах молча промахивается — прогоняй его по РЕАЛЬНЫМ строкам того источника, из которого он будет читать.
 - Считая «сколько строк попадает в окно», бери окно ИЗ КОДА (`_calendar_since(7)` = `-6 days`, сегодня включительно), а не пиши `-7 days` от руки: получишь расхождение 1612 против 1542 и полчаса на поиск несуществующего бага в своей же правке.
 - Мутация покраснела — прочитай, ПОЧЕМУ. В #154 подмена `AbortSignal.any` на `opts.signal || timeout` роняла тест через 32 с сообщением «Execution context was destroyed» вместо «таймаут съеден»: тест ждал вечно висящий запрос. Красный по негодной причине бесполезен в бою — на зависание нужен СВОЙ потолок (`Promise.race` с маркером `HUNG`), тогда мутация печатает диагноз, а не смерть контекста.
 - Красный тест приколочен к ДОСЛОВНОМУ argv/тексту/имени вызова → сперва `git log -S"<строка>"` и вопрос «поведение изменилось или только форма?»; если форма — переписать тест на ПОВЕДЕНЧЕСКИЙ, не подгонять строку. Подгонка дешевле на один ход и оставляет тест таким же хрупким до следующего рефакторинга. Замер #154: тест требовал `AbortSignal.timeout(30000)` внутри `_sparkFetch`, а #58 перевёл бюджет в параметр `api(url, {timeoutMs})` — поведение сохранилось, красным был только матчер. *(на триаже у оркестратора, метит в CLAUDE.md, парой к правилу про мутацию с fallback)*
 - `test_frontend.py::test_chat_drop_handles_files_tree_paths_and_upload_errors` (и `test_tg_bridge.py::TestTgSendSafe::test_serializes_concurrent_group_sends`) — ИЗВЕСТНЫЕ флаки по wall-clock, разобраны в `docs/tasks/17/report.md`. Упали одиночно при LA > 5 → повторить прогон 3 раза и посмотреть туда, а не искать причину в своей правке.
 - Меряешь «худший ответ» по журналу — иди по ВСЕЙ истории сессии, а не по последней сотне строк: жирные строки лежат где угодно, юзер доходит до них кнопкой «ещё». На снимке 04.08 блоб seo-cro на 651 КБ уже выпал из последних 100, и «до» выглядело бы как безобидные 8.8 КБ.
 - Про сжатие: base64 не сжимается вообще. Бюджет ответа в СЫРЫХ байтах для такого содержимого почти равен размеру по проводу — 24 КБ сырых дали 19 КБ gzip. Если нужен потолок по проводу, бюджет ставить примерно равным ему, а не рассчитывать на ×4.
 - Время на этом VPS мерить БРАУЗЕРНЫМИ часами, а не хостовым секундомером: при LA 8 хостовой дал ветке 6.25 с против 4.30 у main — шум больше эффекта и с обратным знаком. Рабочий приём: `page.add_init_script` с обёрткой над `fetch` (start/end по `performance.now()`) + опрос раз в 30 мс для отметки первого экрана, 3 прогона и медиана. Отметку перед чтением ДОЖИДАТЬСЯ (`wait_for_function`), иначе тик не успевает и замер молча теряется. `MutationObserver.observe(document.documentElement)` в init-скрипте падает — DOM ещё не создан, поэтому опрос.
 - Обрезанный `tool_result` рисуется СВОИМ узлом-плашкой (`🖼 [Image result]` + маркер), а загруженный целиком вливается в карточку инструмента и своего узла с `data-chat-log-id` НЕ создаёт. Зонд, который ищет узел по id после «загрузить целиком», вернёт `None` и это выглядит как провал — картинки считать по всему `#chat` (`img`, `naturalWidth`), а не по узлу.
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 9668864db..b7cf07714 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -396,40 +396,74 @@ def test_orchestrator_unread_tracks_own_turn_only(dashboard_browser: Browser):
         _unreadTabs.add('/foreign');
         _syncUnreadDot(tab, '/foreign');
         _syncUnreadDot(tab, '/foreign');
         const afterAdd = tab.querySelectorAll('.tab-unread').length;
         _unreadTabs.delete('/foreign');
         _syncUnreadDot(tab, '/foreign');
         const afterDelete = tab.querySelectorAll('.tab-unread').length;
         return {workerFinished, orchestratorFinished, before, afterAdd, afterDelete};
     }""")
     page.close()
 
     assert result == {
         "workerFinished": False,
         "orchestratorFinished": True,
         "before": 0,
         "afterAdd": 1,
         "afterDelete": 0,
     }
 
 
+def test_dropped_path_lands_at_caret_not_at_end(dashboard_browser: Browser):
+    """#94: юзер печатал в середине — путь обязан встать туда, а не в конец."""
+    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
+    insert_code = "function _insertPathAtCaret" + source.split(
+        "function _insertPathAtCaret", 1,
+    )[1].split("\nasync function _handleChatDrop", 1)[0]
+
+    page = dashboard_browser.new_page()
+    page.set_content('<textarea id="chat-input"></textarea>')
+    page.add_script_tag(content=f"""
+        let pastedImages = [];
+        function showImagePreview() {{}}
+        {insert_code}
+        window.insert = (text, start, end) => {{
+            const i = document.querySelector('#chat-input');
+            i.value = text; i.focus(); i.setSelectionRange(start, end ?? start);
+            _insertPathAtCaret(i, '/tmp/pic.png', '/tmp/pic.png');
+            return {{value: i.value, start: i.selectionStart, end: i.selectionEnd}};
+        }};
+    """)
+    middle = page.evaluate("() => insert('посмотри сюда', 9)")
+    selection = page.evaluate("() => insert('убери это слово', 6, 9)")
+    empty = page.evaluate("() => insert('', 0)")
+    tail = page.evaluate("() => insert('хвост', 5)")
+    page.close()
+
+    assert middle["value"] == "посмотри \n/tmp/pic.png\nсюда"
+    # каретка сразу после пути — юзер дописывает ПОСЛЕ него, а не перед
+    assert middle["start"] == middle["end"] == len("посмотри \n/tmp/pic.png")
+    assert selection["value"] == "убери \n/tmp/pic.png\n слово"
+    assert empty["value"] == "/tmp/pic.png"
+    assert tail["value"] == "хвост\n/tmp/pic.png"
+
+
 def test_chat_drop_handles_files_tree_paths_and_upload_errors(
     dashboard_browser: Browser,
 ):
     source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
     assert "function initChatDrop()" in source
     assert source.index("initChatDrop();") < source.index("loadOrchestrators();")
     assert "fileDropReady" not in source
     drop_code = "let _dropDragCounter = 0;" + source.split(
         "let _dropDragCounter = 0;", 1,
     )[1].split("function initTabContextMenu", 1)[0]
     # Срез содержит ВЫЗОВЫ _trackUpload/_uploadToChat, а их определения лежат
     # ниже по файлу — страница падала на "_trackUpload is not defined".
     # Берём настоящий блок загрузки, а не заглушки: заглушка спрятала бы
     # регрессию внутри него.
     upload_helpers = "const _pendingUploads = new Set();" + source.split(
         "const _pendingUploads = new Set();", 1,
     )[1].split("const _COMPRESS_MIN_BYTES", 1)[0]
     drop_code = upload_helpers + drop_code
 
     page = dashboard_browser.new_page()


## Later history of the touched files on main (after this commit)

155 later commits touch these paths; the first 40 (oldest first):
e137badbc 2026-08-05 #105, #94: #105: доказано, что флак test_chat_drop_ не от #94 — база 3/9 красных, main 1/9
b42fcfd52 2026-08-05 Squashed commits: - #107: тест дропа ждёт условие (пути/ошибки по каждому файлу), а не фиксированные 100 мс - #107: отчёт — приёмка 10/10 зелёных и две мутации - #107: личная память — флак вычеркнут, приём ожидания по условию
07ddbf6ce 2026-08-06 #124: #124: порядок аргументов light-dark в скилле html-artifacts — светлое первым
1d3e31366 2026-08-06 #136: #136: просмотр .json форматирует текст файла, не пересобирает разобранный объект
ce54d49a6 2026-08-07 #145: #145: браузерные тесты логинятся кредами из окружения вместо скипа по auth
e25ca71e4 2026-08-07 #150: #150: null в five_hour_pct/seven_day_pct — дыра в графике, а не ноль
ad423c58f 2026-08-11 #185: #185: add chat event timeline navigation
6c501b822 2026-08-11 #174: WIP #174: add native history canary and diagnose Claude collector
8b0735950 2026-08-12 #212: #212: restore truncated Read images from full log
21ead017a 2026-08-13 #245: #245: add dashboard voice input
ba10d0dcb 2026-08-13 #163: #163: keep usage controls visible on narrow desktops
d894fc6e4 2026-08-13 #259: #259: audit dashboard clarity and propose UX
173f2d863 2026-08-13 #260: #260: correlate parallel tool results by id
3c5fa59a2 2026-08-13 #260: #260: pair tool results without exact id and adopt late calls
74f2b6b6d 2026-08-13 #241: #241: highlight notify_user calls and make them navigable
244bcb093 2026-08-13 #268: уведомление браузера о зове оркестратора
85c8254d7 2026-08-13 #270: #270: дашборд показывает перезапуск Orchestra и возвращается сам
b261bb185 2026-08-13 #270: #270: отказ рестарта рисуется как notification, не error
42dc9aa62 2026-08-14 #266: #266: make load-more append history without trimming new cards
ad6f5d69f 2026-08-14 #274: #274: три макета картинки /limits в HTML (фаза 1)
b55465f9a 2026-08-14 #51: #51: render system chat entries as warnings, not agent replies
083c83426 2026-08-14 feat: кнопка очистки сессии агента (обнуляет session_id, worktree не трогает)
cbc3eca2b 2026-08-14 Merge remote-tracking branch 'origin/main'
6e7fcc230 2026-08-14 #197: #197: pin orch tabs test to fixture, not live header
740d749a2 2026-08-14 #242, #278: #242: recount live-state tests — 70 DB_PATH sites in 56 files
4f0c87aa3 2026-08-14 #282: #282: wait for notify card and reconnect, not a 5s sleep
5e11d8772 2026-08-16 fix: stabilize Grok session replay and chat finalization
fc191b4fe 2026-08-16 #295: #295: hide silent turn marker in dashboard
e25a6b178 2026-08-16 #301: #301: visibility-aware dashboard polling
b739cec2a 2026-08-17 #307: WIP #307: add russian task tool labels and focused frontend tests
a497a12fa 2026-08-17 #312: #312: restore system chat dashboard helper seam
3c037bdb8 2026-08-18 #290: cross-runtime handoff + канареечный скип по продовому предикату (scratch/290, вердикт #328)
98add51ec 2026-08-19 #344, #343: #344: линии допуска по квоте на дашборде, снос прежних квотных панелей
3d6d4121e 2026-08-19 #344: #344: вердикт панели квот считается одним владельцем — сводка не расходится с телом
e91247c9c 2026-08-19 #353: #353: unify quota panel and add traces
a44feb4bb 2026-08-19 #356: #356: route usage bars to quota release status
24d6308d4 2026-08-20 #197: #197: кеш последнего успешного ответа, джиттер ретраев, негативный кеш провайдера
b68ace219 2026-08-20 #202: бабл веб-поиска показывает запрос и результат
5165bcc02 2026-08-21 чат открывается на последних сообщениях и не ждёт зеркало
5e7163191 2026-08-21 чат держится низа всю начальную загрузку

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### e137badbc #105, #94: #105: доказано, что флак test_chat_drop_ не от #94 — база 3/9 красных, main 1/9

diff --git a/docs/tasks/94/report.md b/docs/tasks/94/report.md
index dde1007c0..5b7ef222c 100644
--- a/docs/tasks/94/report.md
+++ b/docs/tasks/94/report.md
@@ -45,10 +45,15 @@
 `tests/test_frontend.py::test_dropped_path_lands_at_caret_not_at_end` — вырезает
 `_insertPathAtCaret` из `app.js` и гоняет на настоящем `<textarea>` четыре кейса. Синхронный,
 без аплоада → без гонок. Существующий `test_chat_drop_handles_files_tree_paths_and_upload_errors`
 остаётся зелёным (его падение 1 из 3 — известный wall-clock флак, `docs/tasks/17/report.md`).
 
+**Проверено (#105), что этот флак не мой:** в скретч-worktree, чередуя прогоны, база `c7febc4`
+(main ДО #94) дала 3 красных из 9, текущий main `5408ef5` — 1 из 9, при LA 5.0–5.9. Падение на
+базе той же формы, что и на моей ветке: `assert '/tmp/ok.txt' == '/tmp/ok.txt\n/tmp/tail.txt'` —
+из пачки файлов теряется путь ПОЗДНЕГО аплоада, потому что тест ждёт фиксированные 100 мс.
+
 ## Проверенный edge, который выглядел риском
 
 Восстановление черновика при переключении агента (`app.js:510`) кладёт текст в поле
 программно, без фокуса. Спека HTML требует ставить каретку в КОНЕЦ при присваивании `value` —
 проверено на живой странице: `value.length = 24, selectionStart = 24, focused = false`.
diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index 607a640c6..4fc5ff7cd 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -52,10 +52,10 @@
 - Мутация НЕ покраснела ≠ код верен: у функции с fallback'ом (основной признак + запасной) ломаешь первую ветку, а тесты держатся на второй и остаются зелёными. В #153 так прошла подмена `"type=local_bash" in content` → `if False`, потому что все фикстуры ловились запасной проверкой по форме id. Значит на КАЖДЫЙ признак нужен случай, где остальные признаки помочь не могут; иначе мутация проверяет не то, что кажется.
 - Таблица БД и `logs` расходятся по заполненности одного и того же поля: в `subagents` `task_type` был непустым у всех 3284 строк, а в `logs` у части `subagent_end` он пуст. Классификатор, проверенный по таблице, на логах молча промахивается — прогоняй его по РЕАЛЬНЫМ строкам того источника, из которого он будет читать.
 - Считая «сколько строк попадает в окно», бери окно ИЗ КОДА (`_calendar_since(7)` = `-6 days`, сегодня включительно), а не пиши `-7 days` от руки: получишь расхождение 1612 против 1542 и полчаса на поиск несуществующего бага в своей же правке.
 - Мутация покраснела — прочитай, ПОЧЕМУ. В #154 подмена `AbortSignal.any` на `opts.signal || timeout` роняла тест через 32 с сообщением «Execution context was destroyed» вместо «таймаут съеден»: тест ждал вечно висящий запрос. Красный по негодной причине бесполезен в бою — на зависание нужен СВОЙ потолок (`Promise.race` с маркером `HUNG`), тогда мутация печатает диагноз, а не смерть контекста.
 - Красный тест приколочен к ДОСЛОВНОМУ argv/тексту/имени вызова → сперва `git log -S"<строка>"` и вопрос «поведение изменилось или только форма?»; если форма — переписать тест на ПОВЕДЕНЧЕСКИЙ, не подгонять строку. Подгонка дешевле на один ход и оставляет тест таким же хрупким до следующего рефакторинга. Замер #154: тест требовал `AbortSignal.timeout(30000)` внутри `_sparkFetch`, а #58 перевёл бюджет в параметр `api(url, {timeoutMs})` — поведение сохранилось, красным был только матчер. *(на триаже у оркестратора, метит в CLAUDE.md, парой к правилу про мутацию с fallback)*
-- `test_frontend.py::test_chat_drop_handles_files_tree_paths_and_upload_errors` (и `test_tg_bridge.py::TestTgSendSafe::test_serializes_concurrent_group_sends`) — ИЗВЕСТНЫЕ флаки по wall-clock, разобраны в `docs/tasks/17/report.md`. Упали одиночно при LA > 5 → повторить прогон 3 раза и посмотреть туда, а не искать причину в своей правке.
+- `test_frontend.py::test_chat_drop_handles_files_tree_paths_and_upload_errors` (и `test_tg_bridge.py::TestTgSendSafe::test_serializes_concurrent_group_sends`) — ИЗВЕСТНЫЕ флаки по wall-clock, разобраны в `docs/tasks/17/report.md`. Упали одиночно при LA > 5 → повторить прогон 3 раза и посмотреть туда, а не искать причину в своей правке. Доказывать «красное не моё» надо ЧЕРЕДУЯ прогоны base/main в двух скретч-worktree на явных SHA (`git worktree add --detach /tmp/wt-base <sha>`, гонять венвом `/home/kesha/orchestra/.venv/bin/python -m pytest`): серия за серией меряет ещё и разную нагрузку машины, а чередование даёт обеим одну. #105: база 3 красных из 9, main 1 из 9, форма падения одна — «из пачки файлов потерян путь позднего аплоада».
 - Меряешь «худший ответ» по журналу — иди по ВСЕЙ истории сессии, а не по последней сотне строк: жирные строки лежат где угодно, юзер доходит до них кнопкой «ещё». На снимке 04.08 блоб seo-cro на 651 КБ уже выпал из последних 100, и «до» выглядело бы как безобидные 8.8 КБ.
 - Про сжатие: base64 не сжимается вообще. Бюджет ответа в СЫРЫХ байтах для такого содержимого почти равен размеру по проводу — 24 КБ сырых дали 19 КБ gzip. Если нужен потолок по проводу, бюджет ставить примерно равным ему, а не рассчитывать на ×4.
 - Время на этом VPS мерить БРАУЗЕРНЫМИ часами, а не хостовым секундомером: при LA 8 хостовой дал ветке 6.25 с против 4.30 у main — шум больше эффекта и с обратным знаком. Рабочий приём: `page.add_init_script` с обёрткой над `fetch` (start/end по `performance.now()`) + опрос раз в 30 мс для отметки первого экрана, 3 прогона и медиана. Отметку перед чтением ДОЖИДАТЬСЯ (`wait_for_function`), иначе тик не успевает и замер молча теряется. `MutationObserver.observe(document.documentElement)` в init-скрипте падает — DOM ещё не создан, поэтому опрос.
 - Обрезанный `tool_result` рисуется СВОИМ узлом-плашкой (`🖼 [Image result]` + маркер), а загруженный целиком вливается в карточку инструмента и своего узла с `data-chat-log-id` НЕ создаёт. Зонд, который ищет узел по id после «загрузить целиком», вернёт `None` и это выглядит как провал — картинки считать по всему `#chat` (`img`, `naturalWidth`), а не по узлу.
### b42fcfd52 Squashed commits: - #107: тест дропа ждёт условие (пути/ошибки по каждому файлу), а не фиксированные 100 мс - #107: отчёт — приёмка 10/10 зелёных и две мутации - #107: личная память — флак вычеркнут, приём ожидания по условию

diff --git a/docs/tasks/94/report.md b/docs/tasks/94/report.md
index 5b7ef222c..e9c3a68a3 100644
--- a/docs/tasks/94/report.md
+++ b/docs/tasks/94/report.md
@@ -57,5 +57,23 @@
 Восстановление черновика при переключении агента (`app.js:510`) кладёт текст в поле
 программно, без фокуса. Спека HTML требует ставить каретку в КОНЕЦ при присваивании `value` —
 проверено на живой странице: `value.length = 24, selectionStart = 24, focused = false`.
 Значит «черновик восстановлен, юзер жмёт ➜» даёт путь в конце, ровно как до правки; вставки
 в начало чужого текста не будет.
+
+
+## #107 — флак убран
+
+Причина была в обвязке: `testDrop` ждал фиксированные 100 мс, а аплоады идут ПОСЛЕДОВАТЕЛЬНО,
+и поздний под нагрузкой не успевал. Теперь ждём УСЛОВИЕ: каждый файл из пачки либо дал путь
+в поле, либо назван в строке ошибки; дедлайн 10 с оставлен страховкой от зависания и ничего
+не меряет. Продуктовый код не тронут — он доказанно ни при чём (#105).
+
+Приёмка: **10 прогонов подряд, 10 зелёных** при LA 4.64 → 6.82 (раньше краснел примерно
+1 из 3 при LA 5–6). Тест не разучился краснеть — две мутации в js:
+- убрать разделитель (`prefix = ''`) → `assert '/tmp/first.txt/tmp/second.txt' == '/tmp/first.txt\n/tmp/second.txt'`;
+- грузить только первый файл пачки (`files.slice(0, 1)`) → `assert '/tmp/first.txt' == '/tmp/first.txt\n/tmp/second.txt'`,
+  то есть потерянный поздний путь по-прежнему ловится, а не проглатывается ожиданием.
+
+Фиксированные ожидания того же класса, оставшиеся в файле (не чинил, отдельное решение):
+`tests/test_frontend.py:621` — `page.wait_for_timeout(2000)` в `test_no_js_errors`, копит
+ошибки консоли ровно 2 с.
diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index 4fc5ff7cd..db51dc870 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -52,10 +52,11 @@
 - Мутация НЕ покраснела ≠ код верен: у функции с fallback'ом (основной признак + запасной) ломаешь первую ветку, а тесты держатся на второй и остаются зелёными. В #153 так прошла подмена `"type=local_bash" in content` → `if False`, потому что все фикстуры ловились запасной проверкой по форме id. Значит на КАЖДЫЙ признак нужен случай, где остальные признаки помочь не могут; иначе мутация проверяет не то, что кажется.
 - Таблица БД и `logs` расходятся по заполненности одного и того же поля: в `subagents` `task_type` был непустым у всех 3284 строк, а в `logs` у части `subagent_end` он пуст. Классификатор, проверенный по таблице, на логах молча промахивается — прогоняй его по РЕАЛЬНЫМ строкам того источника, из которого он будет читать.
 - Считая «сколько строк попадает в окно», бери окно ИЗ КОДА (`_calendar_since(7)` = `-6 days`, сегодня включительно), а не пиши `-7 days` от руки: получишь расхождение 1612 против 1542 и полчаса на поиск несуществующего бага в своей же правке.
 - Мутация покраснела — прочитай, ПОЧЕМУ. В #154 подмена `AbortSignal.any` на `opts.signal || timeout` роняла тест через 32 с сообщением «Execution context was destroyed» вместо «таймаут съеден»: тест ждал вечно висящий запрос. Красный по негодной причине бесполезен в бою — на зависание нужен СВОЙ потолок (`Promise.race` с маркером `HUNG`), тогда мутация печатает диагноз, а не смерть контекста.
 - Красный тест приколочен к ДОСЛОВНОМУ argv/тексту/имени вызова → сперва `git log -S"<строка>"` и вопрос «поведение изменилось или только форма?»; если форма — переписать тест на ПОВЕДЕНЧЕСКИЙ, не подгонять строку. Подгонка дешевле на один ход и оставляет тест таким же хрупким до следующего рефакторинга. Замер #154: тест требовал `AbortSignal.timeout(30000)` внутри `_sparkFetch`, а #58 перевёл бюджет в параметр `api(url, {timeoutMs})` — поведение сохранилось, красным был только матчер. *(на триаже у оркестратора, метит в CLAUDE.md, парой к правилу про мутацию с fallback)*
-- `test_frontend.py::test_chat_drop_handles_files_tree_paths_and_upload_errors` (и `test_tg_bridge.py::TestTgSendSafe::test_serializes_concurrent_group_sends`) — ИЗВЕСТНЫЕ флаки по wall-clock, разобраны в `docs/tasks/17/report.md`. Упали одиночно при LA > 5 → повторить прогон 3 раза и посмотреть туда, а не искать причину в своей правке. Доказывать «красное не моё» надо ЧЕРЕДУЯ прогоны base/main в двух скретч-worktree на явных SHA (`git worktree add --detach /tmp/wt-base <sha>`, гонять венвом `/home/kesha/orchestra/.venv/bin/python -m pytest`): серия за серией меряет ещё и разную нагрузку машины, а чередование даёт обеим одну. #105: база 3 красных из 9, main 1 из 9, форма падения одна — «из пачки файлов потерян путь позднего аплоада».
+- `test_tg_bridge.py::TestTgSendSafe::test_serializes_concurrent_group_sends` — ИЗВЕСТНЫЙ флак по wall-clock (`docs/tasks/17/report.md`). Упал одиночно при LA > 5 → повторить прогон 3 раза и посмотреть туда, а не искать причину в своей правке. `test_frontend.py::test_chat_drop_...` из этого списка ВЫЧЕРКНУТ: починен в #107 — ждал 100 мс, теперь ждёт условие «каждый файл дал путь ИЛИ назван в ошибке», 10/10 зелёных при LA до 6.8.
+- Чинишь флак «не дождались» — условие писать как «каждый ожидаемый элемент дал СВОЙ наблюдаемый исход» (путь в поле ИЛИ имя в строке ошибки), а не «внутренняя очередь пуста»: очередь пуста и ДО старта, и между двумя последовательными аплоадами. Дедлайн оставлять, но только как страховку от зависания. Проверять двумя мутациями: сломать сборку данных (тест обязан упасть сразу) И убрать поздний элемент (тест обязан упасть по дедлайну) — вторая доказывает, что ожидание не проглатывает потерю. Доказывать «красное не моё» надо ЧЕРЕДУЯ прогоны base/main в двух скретч-worktree на явных SHA (`git worktree add --detach /tmp/wt-base <sha>`, гонять венвом `/home/kesha/orchestra/.venv/bin/python -m pytest`): серия за серией меряет ещё и разную нагрузку машины, а чередование даёт обеим одну. #105: база 3 красных из 9, main 1 из 9, форма падения одна — «из пачки файлов потерян путь позднего аплоада».
 - Меряешь «худший ответ» по журналу — иди по ВСЕЙ истории сессии, а не по последней сотне строк: жирные строки лежат где угодно, юзер доходит до них кнопкой «ещё». На снимке 04.08 блоб seo-cro на 651 КБ уже выпал из последних 100, и «до» выглядело бы как безобидные 8.8 КБ.
 - Про сжатие: base64 не сжимается вообще. Бюджет ответа в СЫРЫХ байтах для такого содержимого почти равен размеру по проводу — 24 КБ сырых дали 19 КБ gzip. Если нужен потолок по проводу, бюджет ставить примерно равным ему, а не рассчитывать на ×4.
 - Время на этом VPS мерить БРАУЗЕРНЫМИ часами, а не хостовым секундомером: при LA 8 хостовой дал ветке 6.25 с против 4.30 у main — шум больше эффекта и с обратным знаком. Рабочий приём: `page.add_init_script` с обёрткой над `fetch` (start/end по `performance.now()`) + опрос раз в 30 мс для отметки первого экрана, 3 прогона и медиана. Отметку перед чтением ДОЖИДАТЬСЯ (`wait_for_function`), иначе тик не успевает и замер молча теряется. `MutationObserver.observe(document.documentElement)` в init-скрипте падает — DOM ещё не создан, поэтому опрос.
 - Обрезанный `tool_result` рисуется СВОИМ узлом-плашкой (`🖼 [Image result]` + маркер), а загруженный целиком вливается в карточку инструмента и своего узла с `data-chat-log-id` НЕ создаёт. Зонд, который ищет узел по id после «загрузить целиком», вернёт `None` и это выглядит как провал — картинки считать по всему `#chat` (`img`, `naturalWidth`), а не по узлу.
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index b7cf07714..7707da609 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -522,11 +522,21 @@ def test_chat_drop_handles_files_tree_paths_and_upload_errors(
             const drop = new DragEvent(
                 'drop',
                 {{bubbles: true, cancelable: true, dataTransfer: dt}},
             );
             input.dispatchEvent(drop);
-            await new Promise(resolve => setTimeout(resolve, 100));
+            // Аплоады идут ПОСЛЕДОВАТЕЛЬНО, и фиксированные 100 мс под нагрузкой
+            // не покрывали поздний — тест терял его путь (#105: 3 красных из 9 ещё
+            // до #94). Ждём УСЛОВИЕ: каждый файл либо дал путь, либо назван в ошибке.
+            // Дедлайн — только страховка от зависания, не мерка скорости.
+            const settled = () => names.every(name =>
+                input.value.includes(`/tmp/${{name}}`)
+                || ($('#chat-drop-error')?.textContent || '').includes(name));
+            const deadline = Date.now() + 10000;
+            while (!settled() && Date.now() < deadline) {{
+                await new Promise(resolve => setTimeout(resolve, 10));
+            }}
             return {{
                 value: input.value,
                 hinted,
                 overPrevented: over.defaultPrevented,
                 dropPrevented: drop.defaultPrevented,
### 07ddbf6ce #124: #124: порядок аргументов light-dark в скилле html-artifacts — светлое первым

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index db51dc870..de088a5c4 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -58,5 +58,6 @@
 - Чинишь флак «не дождались» — условие писать как «каждый ожидаемый элемент дал СВОЙ наблюдаемый исход» (путь в поле ИЛИ имя в строке ошибки), а не «внутренняя очередь пуста»: очередь пуста и ДО старта, и между двумя последовательными аплоадами. Дедлайн оставлять, но только как страховку от зависания. Проверять двумя мутациями: сломать сборку данных (тест обязан упасть сразу) И убрать поздний элемент (тест обязан упасть по дедлайну) — вторая доказывает, что ожидание не проглатывает потерю. Доказывать «красное не моё» надо ЧЕРЕДУЯ прогоны base/main в двух скретч-worktree на явных SHA (`git worktree add --detach /tmp/wt-base <sha>`, гонять венвом `/home/kesha/orchestra/.venv/bin/python -m pytest`): серия за серией меряет ещё и разную нагрузку машины, а чередование даёт обеим одну. #105: база 3 красных из 9, main 1 из 9, форма падения одна — «из пачки файлов потерян путь позднего аплоада».
 - Меряешь «худший ответ» по журналу — иди по ВСЕЙ истории сессии, а не по последней сотне строк: жирные строки лежат где угодно, юзер доходит до них кнопкой «ещё». На снимке 04.08 блоб seo-cro на 651 КБ уже выпал из последних 100, и «до» выглядело бы как безобидные 8.8 КБ.
 - Про сжатие: base64 не сжимается вообще. Бюджет ответа в СЫРЫХ байтах для такого содержимого почти равен размеру по проводу — 24 КБ сырых дали 19 КБ gzip. Если нужен потолок по проводу, бюджет ставить примерно равным ему, а не рассчитывать на ×4.
 - Время на этом VPS мерить БРАУЗЕРНЫМИ часами, а не хостовым секундомером: при LA 8 хостовой дал ветке 6.25 с против 4.30 у main — шум больше эффекта и с обратным знаком. Рабочий приём: `page.add_init_script` с обёрткой над `fetch` (start/end по `performance.now()`) + опрос раз в 30 мс для отметки первого экрана, 3 прогона и медиана. Отметку перед чтением ДОЖИДАТЬСЯ (`wait_for_function`), иначе тик не успевает и замер молча теряется. `MutationObserver.observe(document.documentElement)` в init-скрипте падает — DOM ещё не создан, поэтому опрос.
 - Обрезанный `tool_result` рисуется СВОИМ узлом-плашкой (`🖼 [Image result]` + маркер), а загруженный целиком вливается в карточку инструмента и своего узла с `data-chat-log-id` НЕ создаёт. Зонд, который ищет узел по id после «загрузить целиком», вернёт `None` и это выглядит как провал — картинки считать по всему `#chat` (`img`, `naturalWidth`), а не по узлу.
+- `light-dark(<светлое>, <тёмное>)` — ПЕРВЫЙ аргумент для СВЕТЛОЙ схемы (MDN: «used when color-scheme is light or if no preference is set»). Проверяется за один прогон: `browser.new_page(color_scheme="light"|"dark")` + `getComputedStyle(...).backgroundColor`. Перепутанный порядок не падает и не подсвечивается — артефакт просто рисуется наоборот (#124).
### 1d3e31366 #136: #136: просмотр .json форматирует текст файла, не пересобирает разобранный объект

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 70da73ee4..7d80ea508 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1081,11 +1081,11 @@ async function openFilePreview(path) {
                 }
                 html += '</tbody></table>';
                 contentEl.innerHTML = html;
             } else if (ext === 'json') {
                 let pretty = raw;
-                try { pretty = JSON.stringify(JSON.parse(raw), null, 2); } catch {}
+                try { JSON.parse(raw); pretty = _prettyJsonText(raw); } catch {}
                 contentEl.className = 'flex-1 text-xs p-4';
                 contentEl.style.cssText = 'overflow-y:auto;overflow-x:hidden;max-height:calc(80vh - 48px)';
                 const pre = document.createElement('pre');
                 pre.style.cssText = 'margin:0;background:transparent;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word';
                 const code = document.createElement('code');
diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index de088a5c4..b62d8295d 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -59,5 +59,6 @@
 - Меряешь «худший ответ» по журналу — иди по ВСЕЙ истории сессии, а не по последней сотне строк: жирные строки лежат где угодно, юзер доходит до них кнопкой «ещё». На снимке 04.08 блоб seo-cro на 651 КБ уже выпал из последних 100, и «до» выглядело бы как безобидные 8.8 КБ.
 - Про сжатие: base64 не сжимается вообще. Бюджет ответа в СЫРЫХ байтах для такого содержимого почти равен размеру по проводу — 24 КБ сырых дали 19 КБ gzip. Если нужен потолок по проводу, бюджет ставить примерно равным ему, а не рассчитывать на ×4.
 - Время на этом VPS мерить БРАУЗЕРНЫМИ часами, а не хостовым секундомером: при LA 8 хостовой дал ветке 6.25 с против 4.30 у main — шум больше эффекта и с обратным знаком. Рабочий приём: `page.add_init_script` с обёрткой над `fetch` (start/end по `performance.now()`) + опрос раз в 30 мс для отметки первого экрана, 3 прогона и медиана. Отметку перед чтением ДОЖИДАТЬСЯ (`wait_for_function`), иначе тик не успевает и замер молча теряется. `MutationObserver.observe(document.documentElement)` в init-скрипте падает — DOM ещё не создан, поэтому опрос.
 - Обрезанный `tool_result` рисуется СВОИМ узлом-плашкой (`🖼 [Image result]` + маркер), а загруженный целиком вливается в карточку инструмента и своего узла с `data-chat-log-id` НЕ создаёт. Зонд, который ищет узел по id после «загрузить целиком», вернёт `None` и это выглядит как провал — картинки считать по всему `#chat` (`img`, `naturalWidth`), а не по узлу.
 - `light-dark(<светлое>, <тёмное>)` — ПЕРВЫЙ аргумент для СВЕТЛОЙ схемы (MDN: «used when color-scheme is light or if no preference is set»). Проверяется за один прогон: `browser.new_page(color_scheme="light"|"dark")` + `getComputedStyle(...).backgroundColor`. Перепутанный порядок не падает и не подсвечивается — артефакт просто рисуется наоборот (#124).
+- Любой круг `JSON.parse` → `JSON.stringify` теряет целые больше 2^53 (`…147` → `…200`) и нормализует литералы (`1.0` → `1`, `A` → `A`). Если задача — ПОКАЗАТЬ файл, форматируй ТЕКСТ (`_prettyJsonText` в `utils.js`: сканер с учётом строк и экранирования), а `JSON.parse` оставляй только проверкой валидности. Замер #136: на 171 json репозитория раскладка не изменилась ни в одном, разошлись 46 — и все ровно на литерале числа.
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 7707da609..7b3ec6401 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -411,10 +411,35 @@ def test_orchestrator_unread_tracks_own_turn_only(dashboard_browser: Browser):
         "afterAdd": 1,
         "afterDelete": 0,
     }
 
 
+def test_json_preview_keeps_long_numbers_verbatim(dashboard_browser: Browser):
+    """#136: просмотр .json не должен округлять целые больше 2^53."""
+    utils = (Path(__file__).parent.parent / "app/static/js/utils.js").read_text()
+    pretty = "function _prettyJsonText" + utils.split(
+        "function _prettyJsonText", 1,
+    )[1].split("\nmarked.setOptions", 1)[0]
+    app = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
+    # просмотрщик обязан звать форматтер текста, а не пересобирать разобранный объект
+    assert "pretty = _prettyJsonText(raw)" in app
+    assert "JSON.stringify(JSON.parse(raw)" not in app
+
+    raw = '{"id": 1917704623170653147, "a": [1.0, {}, []], "s": "\\"x\\""}'
+    page = dashboard_browser.new_page()
+    page.set_content("<div></div>")
+    page.add_script_tag(content=pretty)
+    shown = page.evaluate("raw => _prettyJsonText(raw)", raw)
+    page.close()
+
+    assert "1917704623170653147" in shown
+    assert shown == (
+        '{\n  "id": 1917704623170653147,\n  "a": [\n    1.0,\n    {},\n    []\n  ],'
+        '\n  "s": "\\"x\\""\n}'
+    )
+
+
 def test_dropped_path_lands_at_caret_not_at_end(dashboard_browser: Browser):
     """#94: юзер печатал в середине — путь обязан встать туда, а не в конец."""
     source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
     insert_code = "function _insertPathAtCaret" + source.split(
         "function _insertPathAtCaret", 1,
### ce54d49a6 #145: #145: браузерные тесты логинятся кредами из окружения вместо скипа по auth

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index b62d8295d..de8f458f7 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -60,5 +60,7 @@
 - Про сжатие: base64 не сжимается вообще. Бюджет ответа в СЫРЫХ байтах для такого содержимого почти равен размеру по проводу — 24 КБ сырых дали 19 КБ gzip. Если нужен потолок по проводу, бюджет ставить примерно равным ему, а не рассчитывать на ×4.
 - Время на этом VPS мерить БРАУЗЕРНЫМИ часами, а не хостовым секундомером: при LA 8 хостовой дал ветке 6.25 с против 4.30 у main — шум больше эффекта и с обратным знаком. Рабочий приём: `page.add_init_script` с обёрткой над `fetch` (start/end по `performance.now()`) + опрос раз в 30 мс для отметки первого экрана, 3 прогона и медиана. Отметку перед чтением ДОЖИДАТЬСЯ (`wait_for_function`), иначе тик не успевает и замер молча теряется. `MutationObserver.observe(document.documentElement)` в init-скрипте падает — DOM ещё не создан, поэтому опрос.
 - Обрезанный `tool_result` рисуется СВОИМ узлом-плашкой (`🖼 [Image result]` + маркер), а загруженный целиком вливается в карточку инструмента и своего узла с `data-chat-log-id` НЕ создаёт. Зонд, который ищет узел по id после «загрузить целиком», вернёт `None` и это выглядит как провал — картинки считать по всему `#chat` (`img`, `naturalWidth`), а не по узлу.
 - `light-dark(<светлое>, <тёмное>)` — ПЕРВЫЙ аргумент для СВЕТЛОЙ схемы (MDN: «used when color-scheme is light or if no preference is set»). Проверяется за один прогон: `browser.new_page(color_scheme="light"|"dark")` + `getComputedStyle(...).backgroundColor`. Перепутанный порядок не падает и не подсвечивается — артефакт просто рисуется наоборот (#124).
 - Любой круг `JSON.parse` → `JSON.stringify` теряет целые больше 2^53 (`…147` → `…200`) и нормализует литералы (`1.0` → `1`, `A` → `A`). Если задача — ПОКАЗАТЬ файл, форматируй ТЕКСТ (`_prettyJsonText` в `utils.js`: сканер с учётом строк и экранирования), а `JSON.parse` оставляй только проверкой валидности. Замер #136: на 171 json репозитория раскладка не изменилась ни в одном, разошлись 46 — и все ровно на литерале числа.
+- Браузерные тесты в `tests/test_frontend.py` бьют по ЖИВОМУ :8888 и логинятся сами: креды снимаются в `_ENV_DASHBOARD_AUTH` НА ИМПОРТЕ модуля, потому что автоюзная `_hermetic_dashboard_env` (`tests/conftest.py:44`) стирает `DASHBOARD_*` из `os.environ` и глушит `load_dotenv` ради герметичности внутрипроцессных тестов. Читать креды внутри теста бесполезно — увидишь пустоту и решишь, что их нет в окружении (#145, потерянный прогон). Запасной источник — `dotenv_values()`, он не мутирует окружение.
+- Тест «не исполняется ли он вхолостую» проверяется мутацией НЕ его ассерта, а его предусловия: сломал логин → 16 тестов из скипов стали 8 failed + 8 errors. Мутация ассерта доказывает только, что строка сравнения жива.
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 7b3ec6401..e49b6103c 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -4,10 +4,11 @@ Requires: Orchestra running on localhost:8888 (no auth).
 Run: pytest tests/test_frontend.py -v
 """
 
 import os
 import re
+import subprocess
 from pathlib import Path
 
 import pytest
 from playwright.sync_api import Browser, Page, expect, sync_playwright
 
@@ -57,33 +58,62 @@ async def test_raw_non_html_response_has_no_artifact_csp(tmp_path, monkeypatch):
     response = await system.get_file_raw(str(target))
 
     assert "content-security-policy" not in response.headers
 
 
+# Снимок ДО автоюзной `_hermetic_dashboard_env` (tests/conftest.py:44): она стирает
+# DASHBOARD_* из os.environ, чтобы ВНУТРИПРОЦЕССНЫЕ тесты не подцепили auth хозяина
+# машины. Здесь задача обратная — залогиниться на ВНЕШНЕМ сервере, поэтому креды
+# читаем на импорте модуля, до фикстур. В коде их нет, только имена переменных.
+_ENV_DASHBOARD_AUTH = (os.environ.get("DASHBOARD_USER"),
+                       os.environ.get("DASHBOARD_PASSWORD"))
+
+
+def _dashboard_credentials():
+    """Логин/пароль из окружения; ручной прогон без юнита — из `.env` рядом."""
+    user, password = _ENV_DASHBOARD_AUTH
+    if password:
+        return user, password
+    try:
+        from dotenv import dotenv_values   # не трогает os.environ, в отличие от load_dotenv
+    except ImportError:
+        return None, None
+    values = dotenv_values()
+    return values.get("DASHBOARD_USER"), values.get("DASHBOARD_PASSWORD")
+
+
 def _goto_dashboard_or_skip(page: Page):
-    """Открыть развёрнутый дашборд или пропустить тест, назвав причину.
+    """Открыть развёрнутый дашборд, при живом auth — залогиниться.
 
-    Эти проверки требуют РАЗВЁРНУТОГО дашборда без auth (см. докстринг модуля),
-    и до сих пор они об этом молчали: на CI по ``BASE`` нет никого → ERROR на
-    setup, у владельца там живой сервис с включённым auth → отдаётся страница
-    логина. Отсюда красный CI с 9 июня — со дня появления этих тестов.
+    Раньше включённый auth означал скип: на боевой машине он включён всегда,
+    и 16 браузерных проверок печатались зелёными, ничего не проверив (#145).
+    Логинимся кредами из окружения; их нет — скип с этой причиной, а не с общей.
 
     Поднять инстанс прямо здесь нельзя: ``app.db.DB_PATH`` вычисляется на
     импорте модуля, поэтому в общем прогоне такой сервер работал бы по БОЕВОЙ
     базе. Адрес стенда задаётся через ``ORCHESTRA_TEST_BASE``.
     """
     try:
         resp = page.goto(BASE, wait_until="domcontentloaded")
     except Exception as exc:
         pytest.skip(f"дашборд на {BASE} недоступен ({type(exc).__name__}); "
-                    "укажи ORCHESTRA_TEST_BASE на развёрнутый стенд без auth")
+                    "укажи ORCHESTRA_TEST_BASE на развёрнутый стенд")
     if resp is None or resp.status != 200:
         status = "нет ответа" if resp is None else f"HTTP {resp.status}"
         pytest.skip(f"дашборд на {BASE} ответил {status}")
     if page.locator("#agent-list").count() == 0:
-        pytest.skip(f"на {BASE} нет #agent-list — вероятно включён auth и отдаётся "
-                    "страница логина; этим тестам нужен стенд без auth")
+        if page.locator('input[name="password"]').count() == 0:
+            pytest.skip(f"на {BASE} нет ни #agent-list, ни формы логина — "
+                        "по этому адресу отвечает не дашборд")
+        user, password = _dashboard_credentials()
+        if not user or not password:
+            pytest.skip(f"на {BASE} включён auth, а DASHBOARD_USER/DASHBOARD_PASSWORD "
+                        "нет в окружении — экспортируй их или положи рядом .env")
+        page.fill('input[name="username"]', user)
+        page.fill('input[name="password"]', password)
+        page.click('button[type="submit"]')
+        page.wait_for_selector("#agent-list", timeout=20000)
     return resp
 
 
 @pytest.fixture(scope="module")
 def dashboard_browser():
@@ -119,10 +149,19 @@ def dashboard_page(dashboard_browser: Browser):
     expect(page.locator("#agent-list")).to_be_visible()
     yield page
     page.close()
 
 
+def _repo_scope():
+    """Scope сервера — путь РЕПОЗИТОРИЯ, а не рабочей копии: из worktree они разные."""
+    common = subprocess.run(
+        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
+        cwd=Path(__file__).parent, capture_output=True, text=True, check=True,
+    ).stdout.strip()
+    return str(Path(common).parent)
+
+
 def test_dashboard_loads(dashboard_page: Page):
     expect(dashboard_page).to_have_title("🎼 Orchestra")
 
 
 def test_sidebar_agents_visible(dashboard_page: Page):
@@ -783,29 +822,34 @@ def test_task_card_uses_real_long_description_and_shared_expandable_body(
         + source.split("const _TASK_PRIORITY_META", 1)[1].split(
             "// Central renderer", 1,
         )[0]
     )
     api_page = dashboard_browser.new_page()
-    # Тянет РЕАЛЬНУЮ задачу с развёрнутого сервера, да ещё по пути ноутбука.
-    # Держится на трёх внешних условиях сразу: сервис поднят, auth выключен,
-    # задача 112 существует именно в этом scope. Нет их — это не провал кода.
-    try:
-        response = api_page.request.get(
-            f"{BASE}/api/tm/tasks/112",
-            params={"scope": "/mnt/data/Projects/Python/orchestra"},
-        )
-    except Exception as exc:
-        api_page.close()
-        pytest.skip(f"API на {BASE} недоступен ({type(exc).__name__})")
-    if response.status != 200:
+    # Нужен РЕАЛЬНЫЙ длинный текст, а не выдуманный. Раньше тест держался на
+    # задаче 112 в scope ноутбука — на другой машине её нет никогда. Берём любую
+    # длинную из scope этого репозитория, залогинившись как обычный юзер.
+    _goto_dashboard_or_skip(api_page)   # заодно кладёт cookie сессии в контекст
+    scope = _repo_scope()
+    listing = api_page.request.get(f"{BASE}/api/tm/tasks", params={"scope": scope})
+    if listing.status != 200:
         api_page.close()
-        pytest.skip(f"{BASE}/api/tm/tasks/112 ответил HTTP {response.status} "
-                    "(нужен стенд без auth с этой задачей)")
-    task = response.json()
### e25ca71e4 #150: #150: null в five_hour_pct/seven_day_pct — дыра в графике, а не ноль

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index de8f458f7..301bd1364 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -62,5 +62,6 @@
 - Обрезанный `tool_result` рисуется СВОИМ узлом-плашкой (`🖼 [Image result]` + маркер), а загруженный целиком вливается в карточку инструмента и своего узла с `data-chat-log-id` НЕ создаёт. Зонд, который ищет узел по id после «загрузить целиком», вернёт `None` и это выглядит как провал — картинки считать по всему `#chat` (`img`, `naturalWidth`), а не по узлу.
 - `light-dark(<светлое>, <тёмное>)` — ПЕРВЫЙ аргумент для СВЕТЛОЙ схемы (MDN: «used when color-scheme is light or if no preference is set»). Проверяется за один прогон: `browser.new_page(color_scheme="light"|"dark")` + `getComputedStyle(...).backgroundColor`. Перепутанный порядок не падает и не подсвечивается — артефакт просто рисуется наоборот (#124).
 - Любой круг `JSON.parse` → `JSON.stringify` теряет целые больше 2^53 (`…147` → `…200`) и нормализует литералы (`1.0` → `1`, `A` → `A`). Если задача — ПОКАЗАТЬ файл, форматируй ТЕКСТ (`_prettyJsonText` в `utils.js`: сканер с учётом строк и экранирования), а `JSON.parse` оставляй только проверкой валидности. Замер #136: на 171 json репозитория раскладка не изменилась ни в одном, разошлись 46 — и все ровно на литерале числа.
 - Браузерные тесты в `tests/test_frontend.py` бьют по ЖИВОМУ :8888 и логинятся сами: креды снимаются в `_ENV_DASHBOARD_AUTH` НА ИМПОРТЕ модуля, потому что автоюзная `_hermetic_dashboard_env` (`tests/conftest.py:44`) стирает `DASHBOARD_*` из `os.environ` и глушит `load_dotenv` ради герметичности внутрипроцессных тестов. Читать креды внутри теста бесполезно — увидишь пустоту и решишь, что их нет в окружении (#145, потерянный прогон). Запасной источник — `dotenv_values()`, он не мутирует окружение.
 - Тест «не исполняется ли он вхолостую» проверяется мутацией НЕ его ассерта, а его предусловия: сломал логин → 16 тестов из скипов стали 8 failed + 8 errors. Мутация ассерта доказывает только, что строка сравнения жива.
+- Сравнивать ДВА рендера спарклайна целиком нельзя: метка сброса (`resets_at`) считается от `Date.now()` в момент прогона, и одинаковые по смыслу картинки расходятся на доли пикселя (`x1="179.0156"` против `178.86`). Сравнивать только линии данных: `re.findall(r'points="([^"]+)" fill="none" stroke="#38bdf8"', html)`. Точки самих данных стабильны — их x считается от диапазона ряда, а не от часов.
### ad423c58f #185: #185: add chat event timeline navigation

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 7d80ea508..b667c35ec 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -192,14 +192,122 @@ function _keepPinnedIfFollowing() {
 
 function _scrollChatToBottom(behavior = 'auto') {
     const chat = $('#chat');
     if (!chat) return;
     _chatHasNewBelow = false;
+    _chatFollow = true;
     chat.scrollTo({top: chat.scrollHeight, behavior});
     _syncChatJumpButton();
 }
 
+let _chatTimelineObserver = null;
+let _chatTimelineUserCount = 0;
+
+function _chatTimelineKind(type, node) {
+    if (type === 'user_message') return node.dataset.from ? 'worker' : 'user';
+    if (type === 'tool' || type === 'tool_result') return 'tool';
+    if (type === 'error') return 'error';
+    if (type.includes('subagent') || type.includes('background')) return 'worker';
+    if (type === 'system' || type === 'notification' || type === 'status') return 'status';
+    return 'agent';
+}
+
+function _tagChatTimelineNode(node, type, ts) {
+    if (!node || node.dataset.chatNavKind) return;
+    const kind = _chatTimelineKind(type, node);
+    const labels = {user: 'Моё сообщение', worker: 'Сообщение воркера', tool: 'Инструмент',
+                    error: 'Ошибка', status: 'Статус', agent: 'Ответ агента'};
+    let time = '';
+    if (ts) {
+        const date = new Date(ts);
+        if (!Number.isNaN(date.getTime())) time = `, ${date.toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'})}`;
+    }
+    node.dataset.chatNavKind = kind;
+    node.dataset.chatNavLabel = `${labels[kind]}${time}`;
+}
+
+function _addChatTimelineMarker(node) {
+    const track = $('#chat-timeline-track');
+    if (!track || !node?.dataset.chatNavKind || node._chatTimelineMarker) return;
+    const marker = document.createElement('button');
+    const kind = node.dataset.chatNavKind;
+    marker.type = 'button';
+    marker.className = `chat-timeline-marker is-${kind}`;
+    marker.title = node.dataset.chatNavLabel;
+    marker.setAttribute('aria-label', node.dataset.chatNavLabel);
+    marker.addEventListener('click', () => _jumpChatTimelineNode(node, marker));
+
+    let previous = node.previousElementSibling;
+    while (previous && !previous._chatTimelineMarker) previous = previous.previousElementSibling;
+    if (previous?._chatTimelineMarker) {
+        track.insertBefore(marker, previous._chatTimelineMarker.nextSibling);
+    } else {
+        track.prepend(marker);
+    }
+    node._chatTimelineMarker = marker;
+    if (kind === 'user') _chatTimelineUserCount++;
+}
+
+function _removeChatTimelineMarker(node) {
+    const marker = node?._chatTimelineMarker;
+    if (!marker) return;
+    if (node.dataset.chatNavKind === 'user') _chatTimelineUserCount--;
+    marker.remove();
+    node._chatTimelineMarker = null;
+}
+
+function _syncChatTimelineControls() {
+    const count = $('#chat-user-count');
+    const disabled = _chatTimelineUserCount === 0;
+    if (count) count.textContent = `Я ${_chatTimelineUserCount}`;
+    for (const id of ['#chat-user-prev', '#chat-user-next']) {
+        const button = $(id);
+        if (button) button.disabled = disabled;
+    }
+}
+
+function _jumpChatTimelineNode(node, marker) {
+    if (!node?.isConnected) return;
+    clearTimeout(window._scrollResetTimer);
+    scrollAfterLoad = false;
+    _pendingChatRestore = null;
+    _chatFollow = false;
+    $('#chat-timeline-track')?.querySelector('.is-active')?.classList.remove('is-active');
+    marker?.classList.add('is-active');
+    node.scrollIntoView({block: 'center', behavior: 'smooth'});
+    _syncChatJumpButton();
+}
+
+function _jumpChatTimelineUser(direction) {
+    const markers = [...document.querySelectorAll('#chat-timeline-track .is-user')];
+    if (!markers.length) return;
+    const active = markers.findIndex(marker => marker.classList.contains('is-active'));
+    const index = active < 0
+        ? (direction < 0 ? markers.length - 1 : 0)
+        : (active + direction + markers.length) % markers.length;
+    const marker = markers[index];
+    const node = [...$('#chat').children].find(child => child._chatTimelineMarker === marker);
+    _jumpChatTimelineNode(node, marker);
+}
+
+function initChatTimeline() {
+    const chat = $('#chat');
+    if (!chat || _chatTimelineObserver) return;
+    for (const node of chat.children) _addChatTimelineMarker(node);
+    _syncChatTimelineControls();
+    _chatTimelineObserver = new MutationObserver(records => {
+        for (const record of records) {
+            for (const node of record.removedNodes) if (node.nodeType === Node.ELEMENT_NODE) _removeChatTimelineMarker(node);
+            for (const node of record.addedNodes) if (node.nodeType === Node.ELEMENT_NODE) _addChatTimelineMarker(node);
+        }
+        _syncChatTimelineControls();
+    });
+    _chatTimelineObserver.observe(chat, {childList: true});
+    $('#chat-user-prev')?.addEventListener('click', () => _jumpChatTimelineUser(-1));
+    $('#chat-user-next')?.addEventListener('click', () => _jumpChatTimelineUser(1));
+}
+
 function _prepareChatAnchorRestore(hasUnread) {
     clearTimeout(window._scrollResetTimer);
     const key = _chatPositionKey();
     const afterId = hasUnread ? _chatReadReceipt(key) : null;
     _pendingChatRestore = afterId ? {key, afterId} : null;
@@ -578,10 +686,11 @@ document.addEventListener('DOMContentLoaded', () => {
     $('#browse-btn')?.addEventListener('click', showProjectPicker);
     initTabContextMenu();
     initHiddenTabsBtn();
     initChatDrop();
     initChatPositionMemory();
+    initChatTimeline();
     $('#restart-btn').addEventListener('click', restartServer);
     // Client modal (available with auth)
     const clientBtn = document.getElementById('client-btn');
     if (clientBtn) clientBtn.addEventListener('click', openClientModal);
     const clientClose = document.getElementById('client-modal-close');
@@ -3499,10 +3608,11 @@ function addChatEntry(type, content, ts, anchor, payload) {
     }
     if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
     const chat = $('#chat');
     let _insertedBeforeStream = false;
     const _insert = (el) => {
+        _tagChatTimelineNode(el, type, ts);
         _stampChatLogNode(el, payload);
         if (payload && payload.trunc) _attachTruncNotice(el, payload, type, ts);
### 6c501b822 #174: WIP #174: add native history canary and diagnose Claude collector

diff --git a/app/static/js/app.js b/app/static/js/app.js
index b667c35ec..67a34e7fe 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2153,10 +2153,38 @@ function _updateProxyStatus(connected) {
     } else {
         el.textContent = '🔴';
         el.title = 'Proxy offline — no models available';
     }
 }
+
+function _historyTransferMessage(transfer) {
+    if (!transfer || !transfer.mode) return null;
+    if (transfer.mode === 'summary') {
+        return {
+            type: 'warning',
+            text: `native history import unavailable: ${transfer.reason || 'unknown reason'}; summary fallback active`,
+        };
+    }
+    if (transfer.mode !== 'native') return null;
+    return {
+        type: 'status',
+        text: `history imported to ${transfer.runtime} ${transfer.version}: ` +
+            `users=${transfer.users}, assistants=${transfer.assistants}, ` +
+            `tools=${transfer.tool_calls}/${transfer.tool_results}, ` +
+            `tool chars detailed=${transfer.tool_detailed_chars}, truncated=${transfer.truncated}, ` +
+            `secrets redacted=${transfer.secrets_redacted}, reasoning omitted=${transfer.reasoning_omitted}`,
+    };
+}
+
+function _showHistoryTransfer(transfer) {
+    const rendered = _historyTransferMessage(transfer);
+    if (!rendered) return;
+    const chat = $('#chat');
+    if (chat && Array.from(chat.children).some(node => node.textContent.includes(rendered.text))) return;
+    addChatEntry(rendered.type, rendered.text);
+}
+
 async function _showModelPicker(agentName, currentModel, anchor) {
     const existing = document.getElementById('model-picker-dd');
     if (existing) { existing.remove(); return; }
     await _ensureModels();
     if (!_MODELS.length) { console.warn('No models available for picker'); return; }
@@ -2177,10 +2205,11 @@ async function _showModelPicker(agentName, currentModel, anchor) {
                 dd.remove();
                 try {
                     const resp = await api(`/api/sessions/${agentName}/change-model`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ model: m.id, scope: currentScope }) });
                     if (resp && !resp.error) {
                         $('#ai-model').textContent = m.id;
+                        _showHistoryTransfer(resp.history_transfer);
                         loadSessions();
                     }
                 } catch (e) { console.warn('Change model failed:', e); }
             });
         }
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index dd094d44b..53bf9c68e 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -31,10 +31,24 @@ def test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox():
     assert "openBtn.href = rawUrl;" in html_branch
     assert set(match.group(1).split()) == {"allow-scripts"}
     assert "allow-same-origin" not in match.group(1)
 
 
+def test_model_picker_surfaces_native_history_result_and_fallback():
+    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
+    helper = source.split("function _historyTransferMessage", 1)[1].split(
+        "async function _showModelPicker", 1,
+    )[0]
+    picker = source.split("async function _showModelPicker", 1)[1].split(
+        "function updateAgentInfo", 1,
+    )[0]
+
+    assert "reasoning omitted=${transfer.reasoning_omitted}" in helper
+    assert "summary fallback active" in helper
+    assert "_showHistoryTransfer(resp.history_transfer);" in picker
+
+
 @pytest.mark.asyncio
 @pytest.mark.parametrize("suffix", [".html", ".HTM"])
 async def test_raw_html_response_has_sandbox_csp(tmp_path, monkeypatch, suffix):
     from app.routes import system
 