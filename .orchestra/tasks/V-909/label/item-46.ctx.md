# Context for item-46

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/docs/tasks/369/bubbles-compact.png b/docs/tasks/369/bubbles-compact.png
index e753f587a..9c033d00e 100644
Binary files a/docs/tasks/369/bubbles-compact.png and b/docs/tasks/369/bubbles-compact.png differ
diff --git a/docs/tasks/369/bubbles-full.png b/docs/tasks/369/bubbles-full.png
index 3215687a1..df33f27ed 100644
Binary files a/docs/tasks/369/bubbles-full.png and b/docs/tasks/369/bubbles-full.png differ
diff --git a/docs/tasks/369/screenshot_bubbles.py b/docs/tasks/369/screenshot_bubbles.py
index c3e49d767..cd0901e0e 100644
--- a/docs/tasks/369/screenshot_bubbles.py
+++ b/docs/tasks/369/screenshot_bubbles.py
@@ -1,92 +1,113 @@
-"""#369: screenshots of harness tool bubbles for the user (live :8888 + route substitution)."""
+"""#369: screenshots of harness tool bubbles for the user (live :8888 + route substitution).
+
+Урок после пустого первого снимка: фоновый код дашборда умеет вычищать чат между
+проверкой и снимком, поэтому порядок такой — инжект → ПОЛОЖИТЕЛЬНАЯ проверка
+(видимость конкретного баббла) → заморозка DOM клоном (его никто не тронет) →
+пост-проверка клона → element.screenshot чата → пиксельная самопроверка файла.
+"""
 
 import os
 import sys
 from pathlib import Path
 
 from dotenv import load_dotenv
 from playwright.sync_api import sync_playwright
 
 ROOT = Path(__file__).resolve().parents[3]
 load_dotenv(ROOT / ".env")
 BASE = "http://127.0.0.1:8888"
 OUT = Path(__file__).parent
 
 
 def source(rel: str) -> str:
     return (ROOT / rel).read_text()
 
 
 CALLS_FULL = [
     ["text", "Готово — прогнал тесты и обновил документацию."],
     ["tool", 'bash: {"command":"uv run pytest -q tests/test_frontend.py\\nls -la app/static/js"}'],
     ["tool_result", "exit_code=0\\n56 passed in 61.51s\\napp.js\\ntool-renderers.js\\nusage.js"],
     ["tool", 'read: {"path":"/home/kesha/orchestra/worktrees/wt/app/static/js/tool-renderers.js","limit":40}'],
     ["tool", 'edit: {"path":"app/ui.py","old":"const a = 1;","new":"const a = 2; // fixed"}'],
     ["tool", 'todo_write: {"todos":[{"content":"проверить рендер бабблов","status":"completed"},{"content":"скриншот для юзера","status":"in_progress"},{"content":"отправить отчёт","status":"pending"}]}'],
     ["tool", 'review: {"focus":"check the diff for regressions before merge"}'],
 ]
 
 CALLS_COMPACT = [
     ["tool", 'bash: {"command":"uv run pytest -q tests/test_frontend.py"}'],
     ["tool", 'read: {"path":"/home/kesha/orchestra/worktrees/wt/app/ui.py","offset":3,"limit":10}'],
     ["tool", 'todo_write: {"todos":[{"content":"рендер бабблов","status":"completed"},{"content":"скриншот","status":"in_progress"}]}'],
     ["tool", 'review: {"focus":"regressions before merge"}'],
 ]
 
 
+def shoot(page, calls, compact: bool, marker_sel: str, out_name: str) -> None:
+    """Инжект + заморозка одним ходом, проверки ДО и ПОСЛЕ заморозки, снимок узла."""
+    page.evaluate("""(args) => {
+        const [calls, compact] = args;
+        const chat = document.querySelector('#chat, #chat-frozen');
+        chat.id = 'chat';
+        selectedAgent = null;
+        if (eventSource) { eventSource.close(); eventSource = null; }
+        window.compactMode = compact;
+        chat.innerHTML = '';
+        for (const [type, content] of calls) {
+            addChatEntry(type, content, null, null, {});
+        }
+        const k = chat.cloneNode(true);
+        k.id = 'chat-frozen';
+        chat.parentNode.replaceChild(k, chat);
+    }""", [calls, compact])
+    # положительный признак отрисовки — уже на замороженном клоне
+    page.locator(f"#chat-frozen {marker_sel}").first.wait_for(state="visible", timeout=10000)
+    page.locator("#chat-frozen").screenshot(path=str(OUT / out_name))
+
+
 def main() -> int:
     with sync_playwright() as p:
         browser = p.chromium.launch()
-        page = browser.new_page(viewport={"width": 900, "height": 1000})
+        page = browser.new_page(viewport={"width": 1500, "height": 1000})
         for rel, ctype in [
             ("app/static/js/tool-renderers.js", "application/javascript"),
             ("app/static/js/app.js", "application/javascript"),
             ("app/static/css/style.css", "text/css"),
         ]:
             pattern = f"**/static/{rel.split('app/static/')[1]}*"
             body, ct = source(rel), ctype
 
             def serve(route, _request, b=body, c=ct):
                 route.fulfill(status=200, content_type=c, body=b)
 
             page.route(pattern, serve)
         page.goto(BASE, wait_until="domcontentloaded")
         if page.locator('input[name="password"]').count():
             page.fill('input[name="username"]', os.environ["DASHBOARD_USER"])
             page.fill('input[name="password"]', os.environ["DASHBOARD_PASSWORD"])
             page.click('button[type="submit"]')
         page.wait_for_selector("#agent-list", timeout=20000)
+        # Гейт: подменённый код жив (символа в main нет)
         page.wait_for_function("() => typeof HARNESS_TOOL_ALIASES !== 'undefined'",
                                timeout=10000)
-        page.evaluate("""(calls) => {
-            selectedAgent = null;
-            if (eventSource) { eventSource.close(); eventSource = null; }
-            window.compactMode = false;
-            const chat = document.querySelector('#chat');
-            chat.innerHTML = '';
-            for (const [type, content] of calls) {
-                addChatEntry(type, content, null, null, {});
-            }
-        }""", CALLS_FULL)
-        page.evaluate("() => { const c = document.querySelector('#chat'); c.scrollTop = c.scrollHeight; }")
-        page.wait_for_timeout(400)
-        page.screenshot(path=str(OUT / "bubbles-full.png"), full_page=False)
-
-        page.evaluate("""(calls) => {
-            window.compactMode = true;
-            const chat = document.querySelector('#chat');
-            chat.innerHTML = '';
-            for (const [type, content] of calls) {
-                addChatEntry(type, content, null, null, {});
-            }
-        }""", CALLS_COMPACT)
-        page.wait_for_timeout(300)
-        page.screenshot(path=str(OUT / "bubbles-compact.png"), full_page=False)
+
+        shoot(page, CALLS_FULL, False, "[data-is-bash]", "bubbles-full.png")
+        shoot(page, CALLS_COMPACT, True, '[data-tool-raw="Bash"]', "bubbles-compact.png")
         browser.close()
-    print("saved:", OUT / "bubbles-full.png", OUT / "bubbles-compact.png")
-    return 0
+
+    # Скриншот — артефакт: проверяем пиксели, а не верим в ожидаемое.
+    from PIL import Image
+    ok = True
+    for name in ("bubbles-full.png", "bubbles-compact.png"):
+        im = Image.open(OUT / name).convert("RGB")
+        colors = im.getcolors(maxcolors=1_000_000)
+        n_colors = len(colors)
+        top = max(colors, key=lambda c: c[0])[0]
+        non_bg = 1 - top / (im.width * im.height)
+        good = im.height > 200 and n_colors >= 500 and non_bg >= 0.05
+        ok &= good
+        print(f"{name}: {im.width}x{im.height}, colors={n_colors}, "
+              f"non-background={non_bg:.1%} -> {'OK' if good else 'BLANK?'}")
+    return 0 if ok else 1
 
 
 if __name__ == "__main__":
     sys.exit(main())
diff --git a/docs/workers/feat-harness-bubbles.md b/docs/workers/feat-harness-bubbles.md
index 512d8966e..eeaee4f2a 100644
--- a/docs/workers/feat-harness-bubbles.md
+++ b/docs/workers/feat-harness-bubbles.md
@@ -4,20 +4,29 @@
 - Установленный playwright вызывает route-handler как `handler(route, request)` —
   лямбда с одним параметром `route` и default-args после него молча съест Request
   в `body=` → `TypeError: Object of type Request is not JSON serializable`.
   Пиши `def serve(route, _request, ...)`. Готовый рабочий шаблон:
   `docs/tasks/369/verify_bubbles.py` (логин из .env, подмена app.js/tool-renderers.js/
   style.css, гейт на символ, которого нет в main).
 - Живой дашборд имеет РЕАЛЬНЫЙ SSE-трафик: инжекть и ассерть DOM одним
   `page.evaluate`, иначе ассерты между Python-вызовами гоняют с чужими вставками.
 - `page.evaluate(fn_str)(arg)` не работает — аргумент передаётся вторым параметром
   `page.evaluate(fn_str, arg)`.
 
 ## Тесты
 - `tests/test_frontend.py` флейкает на текущей машине ПОСЛЕ ~25-31 теста: fixture-
   сервер перестаёт отвечать, дальше все F по таймауту goto. Воспроизводится и на
   чистом main (проверено #369) → это окружение/нагрузка, не твой диф. Изоляция
   падающего теста проходит. Не лечи по первому взгляду — сравни с main.
 
 ## Разное
 - Скриншоты/картинки через read недоступны (binary) — работай от текстового
   описания задачи.
+
+## Скриншоты как артефакты (#369, поймал оркестратор)
+- Скриншот открывают ДО того, как описали словами. Я описал ожидаемое, а файл был
+  пустой — оркестратор поймал простым просмотром. Пиксельная самопроверка
+  (кол-во цветов, доля не-фона) — минимальный честный прокси, если глазами нельзя.
+- Живой дашборд вычищает #chat между вызовами evaluate (reconnect/history-sync).
+  Рабочий приём: инжект → позитивная проверка видимости конкретного баббла →
+  `cloneNode(true)` чата с заменой узла (заморозка) → пост-проверка клона →
+  `locator.screenshot()` самого чата. Готовый скрипт: docs/tasks/369/screenshot_bubbles.py.


## Later history of the touched files on main (after this commit)

1 later commits touch these paths; the first 40 (oldest first):
498c0d149 2026-09-03 Orchestra: migrate project state to .orchestra

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 498c0d149 Orchestra: migrate project state to .orchestra

diff --git a/docs/tasks/369/bubbles-compact.png b/docs/tasks/369/bubbles-compact.png
deleted file mode 100644
index 9c033d00e..000000000
Binary files a/docs/tasks/369/bubbles-compact.png and /dev/null differ
diff --git a/docs/tasks/369/bubbles-full.png b/docs/tasks/369/bubbles-full.png
deleted file mode 100644
index df33f27ed..000000000
Binary files a/docs/tasks/369/bubbles-full.png and /dev/null differ
diff --git a/docs/tasks/369/screenshot_bubbles.py b/docs/tasks/369/screenshot_bubbles.py
deleted file mode 100644
index cd0901e0e..000000000
--- a/docs/tasks/369/screenshot_bubbles.py
+++ /dev/null
@@ -1,113 +0,0 @@
-"""#369: screenshots of harness tool bubbles for the user (live :8888 + route substitution).
-
-Урок после пустого первого снимка: фоновый код дашборда умеет вычищать чат между
-проверкой и снимком, поэтому порядок такой — инжект → ПОЛОЖИТЕЛЬНАЯ проверка
-(видимость конкретного баббла) → заморозка DOM клоном (его никто не тронет) →
-пост-проверка клона → element.screenshot чата → пиксельная самопроверка файла.
-"""
-
-import os
-import sys
-from pathlib import Path
-
-from dotenv import load_dotenv
-from playwright.sync_api import sync_playwright
-
-ROOT = Path(__file__).resolve().parents[3]
-load_dotenv(ROOT / ".env")
-BASE = "http://127.0.0.1:8888"
-OUT = Path(__file__).parent
-
-
-def source(rel: str) -> str:
-    return (ROOT / rel).read_text()
-
-
-CALLS_FULL = [
-    ["text", "Готово — прогнал тесты и обновил документацию."],
-    ["tool", 'bash: {"command":"uv run pytest -q tests/test_frontend.py\\nls -la app/static/js"}'],
-    ["tool_result", "exit_code=0\\n56 passed in 61.51s\\napp.js\\ntool-renderers.js\\nusage.js"],
-    ["tool", 'read: {"path":"/home/kesha/orchestra/worktrees/wt/app/static/js/tool-renderers.js","limit":40}'],
-    ["tool", 'edit: {"path":"app/ui.py","old":"const a = 1;","new":"const a = 2; // fixed"}'],
-    ["tool", 'todo_write: {"todos":[{"content":"проверить рендер бабблов","status":"completed"},{"content":"скриншот для юзера","status":"in_progress"},{"content":"отправить отчёт","status":"pending"}]}'],
-    ["tool", 'review: {"focus":"check the diff for regressions before merge"}'],
-]
-
-CALLS_COMPACT = [
-    ["tool", 'bash: {"command":"uv run pytest -q tests/test_frontend.py"}'],
-    ["tool", 'read: {"path":"/home/kesha/orchestra/worktrees/wt/app/ui.py","offset":3,"limit":10}'],
-    ["tool", 'todo_write: {"todos":[{"content":"рендер бабблов","status":"completed"},{"content":"скриншот","status":"in_progress"}]}'],
-    ["tool", 'review: {"focus":"regressions before merge"}'],
-]
-
-
-def shoot(page, calls, compact: bool, marker_sel: str, out_name: str) -> None:
-    """Инжект + заморозка одним ходом, проверки ДО и ПОСЛЕ заморозки, снимок узла."""
-    page.evaluate("""(args) => {
-        const [calls, compact] = args;
-        const chat = document.querySelector('#chat, #chat-frozen');
-        chat.id = 'chat';
-        selectedAgent = null;
-        if (eventSource) { eventSource.close(); eventSource = null; }
-        window.compactMode = compact;
-        chat.innerHTML = '';
-        for (const [type, content] of calls) {
-            addChatEntry(type, content, null, null, {});
-        }
-        const k = chat.cloneNode(true);
-        k.id = 'chat-frozen';
-        chat.parentNode.replaceChild(k, chat);
-    }""", [calls, compact])
-    # положительный признак отрисовки — уже на замороженном клоне
-    page.locator(f"#chat-frozen {marker_sel}").first.wait_for(state="visible", timeout=10000)
-    page.locator("#chat-frozen").screenshot(path=str(OUT / out_name))
-
-
-def main() -> int:
-    with sync_playwright() as p:
-        browser = p.chromium.launch()
-        page = browser.new_page(viewport={"width": 1500, "height": 1000})
-        for rel, ctype in [
-            ("app/static/js/tool-renderers.js", "application/javascript"),
-            ("app/static/js/app.js", "application/javascript"),
-            ("app/static/css/style.css", "text/css"),
-        ]:
-            pattern = f"**/static/{rel.split('app/static/')[1]}*"
-            body, ct = source(rel), ctype
-
-            def serve(route, _request, b=body, c=ct):
-                route.fulfill(status=200, content_type=c, body=b)
-
-            page.route(pattern, serve)
-        page.goto(BASE, wait_until="domcontentloaded")
-        if page.locator('input[name="password"]').count():
-            page.fill('input[name="username"]', os.environ["DASHBOARD_USER"])
-            page.fill('input[name="password"]', os.environ["DASHBOARD_PASSWORD"])
-            page.click('button[type="submit"]')
-        page.wait_for_selector("#agent-list", timeout=20000)
-        # Гейт: подменённый код жив (символа в main нет)
-        page.wait_for_function("() => typeof HARNESS_TOOL_ALIASES !== 'undefined'",
-                               timeout=10000)
-
-        shoot(page, CALLS_FULL, False, "[data-is-bash]", "bubbles-full.png")
-        shoot(page, CALLS_COMPACT, True, '[data-tool-raw="Bash"]', "bubbles-compact.png")
-        browser.close()
-
-    # Скриншот — артефакт: проверяем пиксели, а не верим в ожидаемое.
-    from PIL import Image
-    ok = True
-    for name in ("bubbles-full.png", "bubbles-compact.png"):
-        im = Image.open(OUT / name).convert("RGB")
-        colors = im.getcolors(maxcolors=1_000_000)
-        n_colors = len(colors)
-        top = max(colors, key=lambda c: c[0])[0]
-        non_bg = 1 - top / (im.width * im.height)
-        good = im.height > 200 and n_colors >= 500 and non_bg >= 0.05
-        ok &= good
-        print(f"{name}: {im.width}x{im.height}, colors={n_colors}, "
-              f"non-background={non_bg:.1%} -> {'OK' if good else 'BLANK?'}")
-    return 0 if ok else 1
-
-
-if __name__ == "__main__":
-    sys.exit(main())
diff --git a/docs/workers/feat-harness-bubbles.md b/docs/workers/feat-harness-bubbles.md
deleted file mode 100644
index eeaee4f2a..000000000
--- a/docs/workers/feat-harness-bubbles.md
+++ /dev/null
@@ -1,32 +0,0 @@
-# feat-harness-bubbles — personal notes
-
-## Playwright в этом проекте (live :8888)
-- Установленный playwright вызывает route-handler как `handler(route, request)` —
-  лямбда с одним параметром `route` и default-args после него молча съест Request
-  в `body=` → `TypeError: Object of type Request is not JSON serializable`.
-  Пиши `def serve(route, _request, ...)`. Готовый рабочий шаблон:
-  `docs/tasks/369/verify_bubbles.py` (логин из .env, подмена app.js/tool-renderers.js/
-  style.css, гейт на символ, которого нет в main).
-- Живой дашборд имеет РЕАЛЬНЫЙ SSE-трафик: инжекть и ассерть DOM одним
-  `page.evaluate`, иначе ассерты между Python-вызовами гоняют с чужими вставками.
-- `page.evaluate(fn_str)(arg)` не работает — аргумент передаётся вторым параметром
-  `page.evaluate(fn_str, arg)`.
-
-## Тесты