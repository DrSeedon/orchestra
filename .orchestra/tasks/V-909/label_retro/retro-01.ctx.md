# Context for retro-01

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index 9ce3edc9d..772d8f616 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1,19 +1,84 @@
 name: CI
 on:
   push:
-    branches: [main]
+    branches: [main, 'task-*/**']
   pull_request:
     branches: [main]
 
 jobs:
   test:
     runs-on: ubuntu-latest
+    # Зависший браузерный тест уже дважды держал шард 27+ минут: `--timeout=30` дампит
+    # стек, но не убивает процесс, пока живой `chrome-headless-shell` держит IPC. Потолок
+    # джоба — единственная гарантия, что зависание становится ПАДЕНИЕМ, а не бесконечным
+    # прогоном. 20 минут при самом долгом честном шарде 117 с — запас десятикратный.
+    timeout-minutes: 20
+    strategy:
+      # Нужен состав падений целиком, а не первый упавший шард.
+      fail-fast: false
+      matrix:
+        shard: [0, 1, 2, 3, 4, 5]
     steps:
+      # Часть тестов сравнивает рабочее дерево с `main` и ходит к родительским
+      # коммитам. По умолчанию checkout берёт ОДИН коммит ОДНОЙ ветки, и такой
+      # тест падает не по существу: `git show main:app/static/js/app.js` отвечает
+      # `exit 128`. `fetch-depth: 0` даёт полную историю и все ветки.
       - uses: actions/checkout@v4
+        with:
+          fetch-depth: 0
       - uses: astral-sh/setup-uv@v4
       - run: uv sync --dev
+      # На образе ubuntu-latest ffmpeg не предустановлен, а тест длительности
+      # аудио обязан звать НАСТОЯЩИЙ ffprobe — подменять бинарь значило бы
+      # проверять заглушку вместо разбора контейнера.
+      - run: sudo apt-get update && sudo apt-get install -y ffmpeg
       # `uv sync` ставит пакет playwright, но не бинарники браузеров. Без этого
       # шага все браузерные тесты молча скипались бы, и CI был бы зелёным, ничего
       # про фронт не проверив.
       - run: uv run playwright install --with-deps chromium
-      - run: uv run pytest -q --timeout=30
+      # Полный сьют в ОДИН процесс на этом репозитории не проходит физически:
+      # прогон 33893200040 убит `exit code 137` (OOM) на 81%, тот же RC=137
+      # около 80% воспроизводится локально. Течёт не отдельный тест, а
+      # накопление за прогон, поэтому лечится делением на процессы, а не
+      # правкой тестов. Раскладка — round-robin по отсортированному списку
+      # файлов: детерминирована, не требует отдельного манифеста и не устаревает
+      # при добавлении файла. Замер локальных шардов той же нарезки: пиковый RSS
+      # 218–263 МБ на шард против 16 ГБ у ubuntu-latest, запас ~60×;
+      # `/usr/bin/time -v` ниже печатает это число в каждый прогон, чтобы запас
+      # проверялся, а не помнился.
+      - name: pytest shard ${{ matrix.shard }} of 6
+        run: |
+          mapfile -t files < <(git ls-files 'tests/test_*.py' | sort \
+            | awk -v s='${{ matrix.shard }}' -v n=6 '(NR - 1) % n == s')
+          echo "shard ${{ matrix.shard }}/6: ${#files[@]} files"
+          test "${#files[@]}" -gt 0
+          # `-v` и небуферизованный вывод обязательны: при зависании `-q` не печатает
+          # НИЧЕГО (буфер не сбрасывается), и в логе остаётся только процент. С `-v`
+          # последняя строка называет тест, на котором встали.
+          # `-m "not browser"` — тот же набор, которым блокирует merge-гейт. Браузерные
+          # тесты гоняются отдельной джобой ниже: одно их зависание не должно съедать
+          # потолок шарда и прятать состав СОСЕДЕЙ по нему (07.09 так и вышло —
+          # `test_orchestra_layout_430` не успел отработать за `test_frontend.py`).
+          PYTHONUNBUFFERED=1 /usr/bin/time -v uv run pytest -v -rf --timeout=30 \
+            -m "not live_probe and not browser" "${files[@]}"
+
+  browser:
+    # Браузерные тесты сняты с БЛОКИРУЮЩЕГО набора (решение владельца 07.09: «выносим их
+    # из гейта, не убиваем»), поэтому джоба помечена `continue-on-error` — она остаётся
+    # СИГНАЛОМ, видимым в списке проверок, но не решает судьбу прогона. Гоняются те же
+    # 167 узлов, что снимает с себя merge-гейт: состав закреплён
+    # `tests/test_merge_test_gate.py::test_browser_inventory_is_explicit`.
+    runs-on: ubuntu-latest
+    continue-on-error: true
+    timeout-minutes: 20
+    steps:
+      - uses: actions/checkout@v4
+        with:
+          fetch-depth: 0
+      - uses: astral-sh/setup-uv@v4
+      - run: uv sync --dev
+      - run: uv run playwright install --with-deps chromium
+      - name: pytest browser
+        run: |
+          PYTHONUNBUFFERED=1 /usr/bin/time -v uv run pytest -v -rf --timeout=30 \
+            -m "browser" tests/
diff --git a/app/merge_test_gate.py b/app/merge_test_gate.py
index 762c9b914..4eb81bb63 100644
--- a/app/merge_test_gate.py
+++ b/app/merge_test_gate.py
@@ -200,75 +200,81 @@ def changed_paths(
 
 
 def select_tests(changed: list[str], *, worktree: str) -> list[str]:
     wt = Path(worktree)
     selected: set[str] = set()
     for raw in changed:
         path = raw.replace("\\", "/").lstrip("./")
         if path.startswith("app/routes/") or path in _ROUTE_EXACT:
             if (wt / ROUTE_TEST).is_file():
                 selected.add(ROUTE_TEST)
         if path.startswith("app/") and path.endswith(".py"):
             cand = f"tests/test_{Path(path).stem}.py"
             if (wt / cand).is_file():
                 selected.add(cand)
         if path.startswith("tests/test_") and path.endswith(".py") and (wt / path).is_file():
             selected.add(path)
     return sorted(selected)
 
 
 LIVE_PROBE_MARKER = "live_probe"
+# Браузерные тесты сняты с БЛОКИРУЮЩЕГО набора, но не удалены и не выключены: они гоняются
+# в CI отдельной джобой и вручную (`uv run pytest -m browser tests/`). Решение владельца
+# 07.09 «выносим их из гейта, не убиваем» на числах: 169 браузерных узлов из 4091, а два
+# мержа подряд встали с `TEST_GATE_INCONCLUSIVE` — бюджет кончался внутри `test_frontend.py`
+# при НУЛЕ красных тестов, то есть гейт блокировал чужую работу зависанием, а не находкой.
+BROWSER_MARKER = "browser"
 NO_TESTS_EXIT_CODE = 5  # pytest EXIT_NOTESTSCOLLECTED
 USAGE_ERROR_EXIT_CODE = 4  # pytest EXIT_USAGEERROR
 
 
 def pytest_argv(
     tests: list[str],
     *,
     interpreter: str | None = None,
     per_test_timeout: float | None = None,
 ) -> list[str]:
     # No -x / --exitfirst / --maxfail=1: one red must not hide the rest.
     # `-m "not live_probe"` снимает с гейта пробы, тратящие настоящий ход провайдера: они
     # краснеют от квоты и недоступности, а не от диффа, и блокируют чужие мержи (18.08:
     # codex-проба стояла красной по rate_limit в самом main). Умолчание безопасное — новая
     # проба БЕЗ маркера гоняется гейтом и падает громко; исчезнуть незаметно она не может.
     #
     # `-vv` рядом с `-q` — не косметика, а единственный источник, по которому «набор
     # красный» отличимо от «мы не успели»: pytest печатает вердикт КАЖДОГО теста отдельной
     # строкой сразу по его окончании и успевает это сделать до убийства по таймауту, тогда
     # как `-q` даёт безымянные точки (а при убийстве в фазе сбора — пустой выход вовсе).
     # Замер #336: убитый прогон отдал `test_b_red FAILED` и имя висящего теста, тогда как
     # `-q` на том же прогоне — 0 символов.
     # Арифметика флагов проверена прогоном и неочевидна: `-q` это −1, `-vv` это +2, сумма
     # +1 — тот же режим, что голый `-v`. Писать `-q -v` НЕЛЬЗЯ: сумма 0, снова точки.
     #
     # `--timeout` / `--timeout-method` — потолок на ОДИН узел (см. PER_TEST_TIMEOUT_SECONDS).
     # Флаг стоит только здесь, а не в `[tool.pytest.ini_options]`: ручной прогон и живые пробы
     # ограничивать нечем и незачем, потолок нужен ровно гейту, который держит чужие мержи.
     python = interpreter or sys.executable
     ceiling = PER_TEST_TIMEOUT_SECONDS if per_test_timeout is None else per_test_timeout
     return [
         python, "-m", "pytest", "-q", "-vv",
         f"--timeout={ceiling:g}",
         f"--timeout-method={PER_TEST_TIMEOUT_METHOD}",
-        "-m", f"not {LIVE_PROBE_MARKER}",
+        "-m", f"not {LIVE_PROBE_MARKER} and not {BROWSER_MARKER}",
         *tests,
     ]
 
 
 # `tests/test_x.py::test_name[param] PASSED [ 12%]`.
 # Строка обязана НАЧИНАТЬСЯ с nodeid: тогда строки итоговой сводки (`FAILED tests/x.py::y - ...`)
 # сюда не попадают и провал не считается дважды.
 # Вердикт берётся ПОСЛЕДНИЙ на строке, а не первый: nodeid параметризованного теста содержит
 # произвольный текст, в том числе пробелы и сами эти слова. Замер #336 — на строке
 # `tests/test_a.py::t2[a b PASSED c] FAILED [2%]` нежадный разбор возвращал PASSED, то есть
 # КРАСНЫЙ тест читался как зелёный; это ровно то направление ошибки, которого быть не должно.
 # Требование пробела перед вердиктом отсекает `nodeid[FAILED]` у теста, который ещё идёт.
 _NODEID_RE = re.compile(r"^\S+\.py::\S")
 _VERDICT_RE = re.compile(r"\s(?P<verdict>PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)(?=\s|$)")
 
 
 def _partial_progress(output: str, tests: list[str]) -> dict:
     """Что pytest успел сообщить до убийства по таймауту.
 
     Обе неудачи приходят одним и тем же `TimeoutExpired`, и без разбора этого выхода они
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index b89007be0..3470480b5 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -910,46 +910,50 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
                     source_task_id=source_task_id,
                     target_session_id=target.id,
                     target_name=target.name,
                     target_scope=target.scope,
                     target_task_id=getattr(target, "task_id", "") or "",
                     target_generation=target_generation,
                     message=req.message,
                     rendered_message=rendered,
                     message_kind=req.message_kind,
                     wake=req.wake,
                     provenance=provenance,
                 )
             return JSONResponse(resource, status_code=status_code)
         if req.sender:
             provenance = MessageProvenance(
                 origin="agent", senders=(req.sender,), subtype="http_send",
             )
         else:
             from app.auth import is_auth_enabled, validate_session
 
+            # Человеком считается ТОЛЬКО предъявивший валидную куку. Прежнее
+            # `not is_auth_enabled() or ...` превращало любого безымянного вызывающего в
+            # человека на контуре без `DASHBOARD_USER` — а это штатный путь из README.
+            # Признак «мы не проверяем, кто пришёл» не равен признаку «пришёл владелец»;
+            # происхождение это утверждение об АВТОРСТВЕ, и на таком контуре оно было
+            # ложным. Вызов при этом не отвергается: ветка `origin="unknown"` ниже уже
+            # написана, доставка идёт, теряется только чужая личность.
             operator = bool(
-                not is_auth_enabled()
-                or (
-                    request is not None
-                    and validate_session(request.cookies.get("session", ""))
-                )
+                request is not None
+                and validate_session(request.cookies.get("session", ""))
             )
             provenance = MessageProvenance(
                 origin="user" if operator else "unknown",
                 senders=("user",) if operator else ("unknown",),
                 subtype="http_send",
             )
         # A non-waking delivery must not load or activate the recipient.  The
         # requested scope is the mailbox address supplied by the sender.
         if not req.wake:
             # #231, находка ревью реализации (F3, раунд 2): ящик разгружается в КОНЦЕ
             # хода. У получателя, который прямо сейчас не работает, следующего конца
             # хода может не быть НИКОГДА — и `wake=False` его не создаёт по построению.
             # Поэтому экономия применяется только там, где она вообще возможна: к
             # получателю, про которого мы ЗНАЕМ, что он занят и ход у него кончится.
             # Во всех остальных случаях (не знаем, не загружен, простаивает) — обычная
             # доставка. Корректность дороже экономии; замер §3.6 и берётся с занятых.
             # Оракул на «неизвестный → в ящик» перезаморожен и снят: он предписывал
             # тихую потерю (F3 ревью реализации).
             live = getattr(manager, "sessions", None) or {}
             target = next(
diff --git a/app/session.py b/app/session.py
index 016225bb5..6ae55eb18 100644
--- a/app/session.py
+++ b/app/session.py
@@ -5056,40 +5056,41 @@ class AgentSession:
                 "error_code": "handoff_context_overflow",
                 "history_transfer": {
                     "mode": "blocked",
                     "preflight": {
                         "fits": False,
                         "total_tokens": total_tokens,
                         "target_context_window": target_window,
                     },
                 },
             }
         backend = self._backend
         if backend is not None:
             if (
                 getattr(backend, "active_turn_id", None)
                 or getattr(backend, "_events_active", False)
                 or getattr(backend, "_turn_active", False)
             ):
                 return {
                     "ok": False,
                     "error": f"cannot change {runtime} model while its turn is settling",
+                    "error_code": f"{runtime}_turn_settling",
                 }
             if not callable(getattr(backend, "retarget_model", None)):
                 return {
                     "ok": False,
                     "error": f"{runtime} backend cannot retarget the active session",
                     "error_code": f"{runtime}_in_place_switch_unsupported",
                 }
 
         await self._drain_persist()
         if backend is not None:
             try:
                 retargeted = backend.retarget_model(new_model)
                 if inspect.isawaitable(retargeted):
                     await retargeted
                 backend_session_id = getattr(backend, "session_id", self.session_id)
                 if backend_session_id != self.session_id:
                     raise RuntimeError(
                         "in-place model switch replaced the native session id"
                     )
             except Exception as error:
diff --git a/app/static/css/vendor/tailwind.css b/app/static/css/vendor/tailwind.css
index 38ca5fe1e..5bac9b67c 100644
--- a/app/static/css/vendor/tailwind.css
+++ b/app/static/css/vendor/tailwind.css
@@ -1 +1 @@
-*,:after,:before{--tw-border-spacing-x:0;--tw-border-spacing-y:0;--tw-translate-x:0;--tw-translate-y:0;--tw-rotate:0;--tw-skew-x:0;--tw-skew-y:0;--tw-scale-x:1;--tw-scale-y:1;--tw-pan-x: ;--tw-pan-y: ;--tw-pinch-zoom: ;--tw-scroll-snap-strictness:proximity;--tw-gradient-from-position: ;--tw-gradient-via-position: ;--tw-gradient-to-position: ;--tw-ordinal: ;--tw-slashed-zero: ;--tw-numeric-figure: ;--tw-numeric-spacing: ;--tw-numeric-fraction: ;--tw-ring-inset: ;--tw-ring-offset-width:0px;--tw-ring-offset-color:#fff;--tw-ring-color:rgba(59,130,246,.5);--tw-ring-offset-shadow:0 0 #0000;--tw-ring-shadow:0 0 #0000;--tw-shadow:0 0 #0000;--tw-shadow-colored:0 0 #0000;--tw-blur: ;--tw-brightness: ;--tw-contrast: ;--tw-grayscale: ;--tw-hue-rotate: ;--tw-invert: ;--tw-saturate: ;--tw-sepia: ;--tw-drop-shadow: ;--tw-backdrop-blur: ;--tw-backdrop-brightness: ;--tw-backdrop-contrast: ;--tw-backdrop-grayscale: ;--tw-backdrop-hue-rotate: ;--tw-backdrop-invert: ;--tw-backdrop-opacity: ;--tw-backdrop-saturate: ;--tw-backdrop-sepia: ;--tw-contain-size: ;--tw-contain-layout: ;--tw-contain-paint: ;--tw-contain-style: }::backdrop{--tw-border-spacing-x:0;--tw-border-spacing-y:0;--tw-translate-x:0;--tw-translate-y:0;--tw-rotate:0;--tw-skew-x:0;--tw-skew-y:0;--tw-scale-x:1;--tw-scale-y:1;--tw-pan-x: ;--tw-pan-y: ;--tw-pinch-zoom: ;--tw-scroll-snap-strictness:proximity;--tw-gradient-from-position: ;--tw-gradient-via-position: ;--tw-gradient-to-position: ;--tw-ordinal: ;--tw-slashed-zero: ;--tw-numeric-figure: ;--tw-numeric-spacing: ;--tw-numeric-fraction: ;--tw-ring-inset: ;--tw-ring-offset-width:0px;--tw-ring-offset-color:#fff;--tw-ring-color:rgba(59,130,246,.5);--tw-ring-offset-shadow:0 0 #0000;--tw-ring-shadow:0 0 #0000;--tw-shadow:0 0 #0000;--tw-shadow-colored:0 0 #0000;--tw-blur: ;--tw-brightness: ;--tw-contrast: ;--tw-grayscale: ;--tw-hue-rotate: ;--tw-invert: ;--tw-saturate: ;--tw-sepia: ;--tw-drop-shadow: ;--tw-backdrop-blur: ;--tw-backdrop-brightness: ;--tw-backdrop-contrast: ;--tw-backdrop-grayscale: ;--tw-backdrop-hue-rotate: ;--tw-backdrop-invert: ;--tw-backdrop-opacity: ;--tw-backdrop-saturate: ;--tw-backdrop-sepia: ;--tw-contain-size: ;--tw-contain-layout: ;--tw-contain-paint: ;--tw-contain-style: }/*! tailwindcss v3.4.17 | MIT License | https://tailwindcss.com*/*,:after,:before{box-sizing:border-box;border:0 solid #e5e7eb}:after,:before{--tw-content:""}:host,html{line-height:1.5;-webkit-text-size-adjust:100%;-moz-tab-size:4;-o-tab-size:4;tab-size:4;font-family:Inter,system-ui,-apple-system,sans-serif;font-feature-settings:normal;font-variation-settings:normal;-webkit-tap-highlight-color:transparent}body{margin:0;line-height:inherit}hr{height:0;color:inherit;border-top-width:1px}abbr:where([title]){-webkit-text-decoration:underline dotted;text-decoration:underline dotted}h1,h2,h3,h4,h5,h6{font-size:inherit;font-weight:inherit}a{color:inherit;text-decoration:inherit}b,strong{font-weight:bolder}code,kbd,pre,samp{font-family:JetBrains Mono,Fira Code,ui-monospace,monospace;font-feature-settings:normal;font-variation-settings:normal;font-size:1em}small{font-size:80%}sub,sup{font-size:75%;line-height:0;position:relative;vertical-align:baseline}sub{bottom:-.25em}sup{top:-.5em}table{text-indent:0;border-color:inherit;border-collapse:collapse}button,input,optgroup,select,textarea{font-family:inherit;font-feature-settings:inherit;font-variation-settings:inherit;font-size:100%;font-weight:inherit;line-height:inherit;letter-spacing:inherit;color:inherit;margin:0;padding:0}button,select{text-transform:none}button,input:where([type=button]),input:where([type=reset]),input:where([type=submit]){-webkit-appearance:button;background-color:transparent;background-image:none}:-moz-focusring{outline:auto}:-moz-ui-invalid{box-shadow:none}progress{vertical-align:baseline}::-webkit-inner-spin-button,::-webkit-outer-spin-button{height:auto}[type=search]{-webkit-appearance:textfield;outline-offset:-2px}::-webkit-search-decoration{-webkit-appearance:none}::-webkit-file-upload-button{-webkit-appearance:button;font:inherit}summary{display:list-item}blockquote,dd,dl,figure,h1,h2,h3,h4,h5,h6,hr,p,pre{margin:0}fieldset{margin:0}fieldset,legend{padding:0}menu,ol,ul{list-style:none;margin:0;padding:0}dialog{padding:0}textarea{resize:vertical}input::-moz-placeholder,textarea::-moz-placeholder{opacity:1;color:#9ca3af}input::placeholder,textarea::placeholder{opacity:1;color:#9ca3af}[role=button],button{cursor:pointer}:disabled{cursor:default}audio,canvas,embed,iframe,img,object,svg,video{display:block;vertical-align:middle}img,video{max-width:100%;height:auto}[hidden]:where(:not([hidden=until-found])){display:none}.\!container{width:100%!important}.container{width:100%}@media (min-width:640px){.\!container{max-width:640px!important}.container{max-width:640px}}@media (min-width:768px){.\!container{max-width:768px!important}.container{max-width:768px}}@media (min-width:1024px){.\!container{max-width:1024px!important}.container{max-width:1024px}}@media (min-width:1280px){.\!container{max-width:1280px!important}.container{max-width:1280px}}@media (min-width:1536px){.\!container{max-width:1536px!important}.container{max-width:1536px}}.visible{visibility:visible}.collapse{visibility:collapse}.fixed{position:fixed}.absolute{position:absolute}.relative{position:relative}.inset-0{inset:0}.-right-1{right:-.25rem}.-top-1{top:-.25rem}.right-0{right:0}.top-full{top:100%}.z-50{z-index:50}.mb-1{margin-bottom:.25rem}.mb-2{margin-bottom:.5rem}.mb-3{margin-bottom:.75rem}.mb-4{margin-bottom:1rem}.mb-5{margin-bottom:1.25rem}.ml-16{margin-left:4rem}.ml-3{margin-left:.75rem}.ml-4{margin-left:1rem}.mt-0\.5{margin-top:.125rem}.mt-1{margin-top:.25rem}.mt-2{margin-top:.5rem}.mt-3{margin-top:.75rem}.\!block{display:block!important}.block{display:block}.inline{display:inline}.flex{display:flex}.table{display:table}.grid{display:grid}.hidden{display:none}.h-1{height:.25rem}.h-1\.5{height:.375rem}.h-16{height:4rem}.h-4{height:1rem}.h-full{height:100%}.h-screen{height:100vh}.max-h-48{max-height:12rem}.max-h-\[300px\]{max-height:300px}.max-h-\[80vh\]{max-height:80vh}.max-h-\[85vh\]{max-height:85vh}.min-h-0{min-height:0}.w-1\.5{width:.375rem}.w-4{width:1rem}.w-6{width:1.5rem}.w-\[250px\]{width:250px}.w-\[320px\]{width:320px}.w-\[380px\]{width:380px}.w-\[420px\]{width:420px}.w-\[480px\]{width:480px}.w-\[700px\]{width:700px}.w-\[90vw\]{width:90vw}.w-full{width:100%}.min-w-0{min-width:0}.max-w-3xl{max-width:48rem}.max-w-4xl{max-width:56rem}.max-w-\[70\%\]{max-width:70%}.max-w-\[90vw\]{max-width:90vw}.flex-1{flex:1 1 0%}.shrink-0{flex-shrink:0}.cursor-default{cursor:default}.cursor-pointer{cursor:pointer}.select-none{-webkit-user-select:none;-moz-user-select:none;user-select:none}.resize-none{resize:none}.grid-cols-2{grid-template-columns:repeat(2,minmax(0,1fr))}.flex-col{flex-direction:column}.flex-wrap{flex-wrap:wrap}.items-start{align-items:flex-start}.items-center{align-items:center}.justify-center{justify-content:center}.justify-between{justify-content:space-between}.gap-1{gap:.25rem}.gap-1\.5{gap:.375rem}.gap-2{gap:.5rem}.gap-3{gap:.75rem}.gap-x-4{-moz-column-gap:1rem;column-gap:1rem}.gap-y-1{row-gap:.25rem}.space-y-0\.5>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-top:calc(.125rem*(1 - var(--tw-space-y-reverse)));margin-bottom:calc(.125rem*var(--tw-space-y-reverse))}.space-y-1>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-top:calc(.25rem*(1 - var(--tw-space-y-reverse)));margin-bottom:calc(.25rem*var(--tw-space-y-reverse))}.space-y-1\.5>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-top:calc(.375rem*(1 - var(--tw-space-y-reverse)));margin-bottom:calc(.375rem*var(--tw-space-y-reverse))}.space-y-2>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-top:calc(.5rem*(1 - var(--tw-space-y-reverse)));margin-bottom:calc(.5rem*var(--tw-space-y-reverse))}.space-y-3>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-top:calc(.75rem*(1 - var(--tw-space-y-reverse)));margin-bottom:calc(.75rem*var(--tw-space-y-reverse))}.self-end{align-self:flex-end}.overflow-auto{overflow:auto}.overflow-hidden{overflow:hidden}.overflow-x-auto{overflow-x:auto}.overflow-y-auto{overflow-y:auto}.overflow-x-hidden{overflow-x:hidden}.truncate{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.whitespace-pre-wrap{white-space:pre-wrap}.break-words{overflow-wrap:break-word}.break-all{word-break:break-all}.rounded{border-radius:.25rem}.rounded-2xl{border-radius:1rem}.rounded-full{border-radius:9999px}.rounded-lg{border-radius:.5rem}.rounded-xl{border-radius:.75rem}.border{border-width:1px}.border-b{border-bottom-width:1px}.border-b-2{border-bottom-width:2px}.border-l{border-left-width:1px}.border-l-2{border-left-width:2px}.border-r{border-right-width:1px}.border-t{border-top-width:1px}.border-dashed{border-style:dashed}.border-amber-500\/40{border-color:rgba(245,158,11,.4)}.border-amber-600\/50{border-color:rgba(217,119,6,.5)}.border-indigo-400{--tw-border-opacity:1;border-color:rgb(129 140 248/var(--tw-border-opacity,1))}.border-indigo-500{--tw-border-opacity:1;border-color:rgb(99 102 241/var(--tw-border-opacity,1))}.border-indigo-500\/30{border-color:rgba(99,102,241,.3)}.border-indigo-500\/50{border-color:rgba(99,102,241,.5)}.border-purple-800\/60{border-color:rgba(107,33,168,.6)}.border-red-500\/40{border-color:rgba(239,68,68,.4)}.border-red-900\/50{border-color:rgba(127,29,29,.5)}.border-slate-700{--tw-border-opacity:1;border-color:rgb(51 65 85/var(--tw-border-opacity,1))}.border-slate-700\/30{border-color:rgba(51,65,85,.3)}.border-slate-700\/40{border-color:rgba(51,65,85,.4)}.border-slate-700\/50{border-color:rgba(51,65,85,.5)}.border-slate-800{--tw-border-opacity:1;border-color:rgb(30 41 59/var(--tw-border-opacity,1))}.border-slate-800\/50{border-color:rgba(30,41,59,.5)}.border-slate-800\/70{border-color:rgba(30,41,59,.7)}.border-slate-800\/80{border-color:rgba(30,41,59,.8)}.border-transparent{border-color:transparent}.bg-\[\#0f172a\]{--tw-bg-opacity:1;background-color:rgb(15 23 42/var(--tw-bg-opacity,1))}.bg-amber-400{--tw-bg-opacity:1;background-color:rgb(251 191 36/var(--tw-bg-opacity,1))}.bg-amber-500\/10{background-color:rgba(245,158,11,.1)}.bg-amber-500\/15{background-color:rgba(245,158,11,.15)}.bg-amber-600{--tw-bg-opacity:1;background-color:rgb(217 119 6/var(--tw-bg-opacity,1))}.bg-amber-900\/40{background-color:rgba(120,53,15,.4)}.bg-black\/60{background-color:rgba(0,0,0,.6)}.bg-blue-400{--tw-bg-opacity:1;background-color:rgb(96 165 250/var(--tw-bg-opacity,1))}.bg-emerald-400{--tw-bg-opacity:1;background-color:rgb(52 211 153/var(--tw-bg-opacity,1))}.bg-emerald-600\/30{background-color:rgba(5,150,105,.3)}.bg-indigo-500\/30{background-color:rgba(99,102,241,.3)}.bg-indigo-600{--tw-bg-opacity:1;background-color:rgb(79 70 229/var(--tw-bg-opacity,1))}.bg-indigo-600\/30{background-color:rgba(79,70,229,.3)}.bg-indigo-600\/40{background-color:rgba(79,70,229,.4)}.bg-indigo-900\/30{background-color:rgba(49,46,129,.3)}.bg-indigo-900\/40{background-color:rgba(49,46,129,.4)}.bg-purple-500\/10{background-color:rgba(168,85,247,.1)}.bg-purple-600\/30{background-color:rgba(147,51,234,.3)}.bg-red-400{--tw-bg-opacity:1;background-color:rgb(248 113 113/var(--tw-bg-opacity,1))}.bg-red-500\/15{background-color:rgba(239,68,68,.15)}.bg-red-600{--tw-bg-opacity:1;background-color:rgb(220 38 38/var(--tw-bg-opacity,1))}.bg-red-900{--tw-bg-opacity:1;background-color:rgb(127 29 29/var(--tw-bg-opacity,1))}.bg-red-950\/30{background-color:rgba(69,10,10,.3)}.bg-sky-500\/10{background-color:rgba(14,165,233,.1)}.bg-slate-400{--tw-bg-opacity:1;background-color:rgb(166 179 198/var(--tw-bg-opacity,1))}.bg-slate-500{--tw-bg-opacity:1;background-color:rgb(133 149 171/var(--tw-bg-opacity,1))}.bg-slate-700{--tw-bg-opacity:1;background-color:rgb(51 65 85/var(--tw-bg-opacity,1))}.bg-slate-800{--tw-bg-opacity:1;background-color:rgb(30 41 59/var(--tw-bg-opacity,1))}.bg-slate-800\/40{background-color:rgba(30,41,59,.4)}.bg-slate-800\/50{background-color:rgba(30,41,59,.5)}.bg-slate-800\/60{background-color:rgba(30,41,59,.6)}.bg-slate-900{--tw-bg-opacity:1;background-color:rgb(15 23 42/var(--tw-bg-opacity,1))}.bg-slate-900\/50{background-color:rgba(15,23,42,.5)}.bg-slate-900\/60{background-color:rgba(15,23,42,.6)}.bg-slate-950\/20{background-color:rgba(2,6,23,.2)}.bg-slate-950\/30{background-color:rgba(2,6,23,.3)}.bg-slate-950\/60{background-color:rgba(2,6,23,.6)}.bg-white{--tw-bg-opacity:1;background-color:rgb(255 255 255/var(--tw-bg-opacity,1))}.p-0{padding:0}.p-1{padding:.25rem}.p-2{padding:.5rem}.p-2\.5{padding:.625rem}.p-3{padding:.75rem}.p-4{padding:1rem}.p-6{padding:1.5rem}.px-1{padding-left:.25rem;padding-right:.25rem}.px-1\.5{padding-left:.375rem;padding-right:.375rem}.px-2{padding-left:.5rem;padding-right:.5rem}.px-2\.5{padding-left:.625rem;padding-right:.625rem}.px-3{padding-left:.75rem;padding-right:.75rem}.px-4{padding-left:1rem;padding-right:1rem}.px-5{padding-left:1.25rem;padding-right:1.25rem}.py-0\.5{padding-top:.125rem;padding-bottom:.125rem}.py-1{padding-top:.25rem;padding-bottom:.25rem}.py-1\.5{padding-top:.375rem;padding-bottom:.375rem}.py-2{padding-top:.5rem;padding-bottom:.5rem}.py-3{padding-top:.75rem;padding-bottom:.75rem}.py-6{padding-top:1.5rem;padding-bottom:1.5rem}.py-8{padding-top:2rem;padding-bottom:2rem}.pb-1{padding-bottom:.25rem}.pl-2{padding-left:.5rem}.pt-2{padding-top:.5rem}.text-center{text-align:center}.text-right{text-align:right}.font-mono{font-family:JetBrains Mono,Fira Code,ui-monospace,monospace}.text-\[10px\]{font-size:10px}.text-\[11px\]{font-size:11px}.text-\[9px\]{font-size:9px}.text-lg{font-size:1.125rem;line-height:1.75rem}.text-sm{font-size:.875rem;line-height:1.25rem}.text-xs{font-size:.75rem;line-height:1rem}.font-bold{font-weight:700}.font-medium{font-weight:500}.font-semibold{font-weight:600}.uppercase{text-transform:uppercase}.italic{font-style:italic}.leading-none{line-height:1}.leading-relaxed{line-height:1.625}.tracking-\[0\.16em\]{letter-spacing:.16em}.tracking-tight{letter-spacing:-.025em}.tracking-wider{letter-spacing:.05em}.text-amber-100{--tw-text-opacity:1;color:rgb(254 243 199/var(--tw-text-opacity,1))}.text-amber-200{--tw-text-opacity:1;color:rgb(253 230 138/var(--tw-text-opacity,1))}.text-amber-300{--tw-text-opacity:1;color:rgb(252 211 77/var(--tw-text-opacity,1))}.text-amber-400{--tw-text-opacity:1;color:rgb(251 191 36/var(--tw-text-opacity,1))}.text-amber-400\/60{color:rgba(251,191,36,.6)}.text-amber-400\/70{color:rgba(251,191,36,.7)}.text-cyan-400{--tw-text-opacity:1;color:rgb(34 211 238/var(--tw-text-opacity,1))}.text-emerald-300{--tw-text-opacity:1;color:rgb(110 231 183/var(--tw-text-opacity,1))}.text-emerald-400{--tw-text-opacity:1;color:rgb(52 211 153/var(--tw-text-opacity,1))}.text-fuchsia-400{--tw-text-opacity:1;color:rgb(232 121 249/var(--tw-text-opacity,1))}.text-green-400{--tw-text-opacity:1;color:rgb(74 222 128/var(--tw-text-opacity,1))}.text-indigo-300{--tw-text-opacity:1;color:rgb(165 180 252/var(--tw-text-opacity,1))}.text-indigo-400{--tw-text-opacity:1;color:rgb(129 140 248/var(--tw-text-opacity,1))}.text-purple-200{--tw-text-opacity:1;color:rgb(233 213 255/var(--tw-text-opacity,1))}.text-purple-300{--tw-text-opacity:1;color:rgb(216 180 254/var(--tw-text-opacity,1))}.text-purple-400{--tw-text-opacity:1;color:rgb(192 132 252/var(--tw-text-opacity,1))}.text-red-200{--tw-text-opacity:1;color:rgb(254 202 202/var(--tw-text-opacity,1))}.text-red-300\/70{color:hsla(0,94%,82%,.7)}.text-red-400{--tw-text-opacity:1;color:rgb(248 113 113/var(--tw-text-opacity,1))}.text-sky-300{--tw-text-opacity:1;color:rgb(125 211 252/var(--tw-text-opacity,1))}.text-sky-400{--tw-text-opacity:1;color:rgb(56 189 248/var(--tw-text-opacity,1))}.text-slate-200{--tw-text-opacity:1;color:rgb(226 232 240/var(--tw-text-opacity,1))}.text-slate-300{--tw-text-opacity:1;color:rgb(203 213 225/var(--tw-text-opacity,1))}.text-slate-400{--tw-text-opacity:1;color:rgb(166 179 198/var(--tw-text-opacity,1))}.text-slate-500{--tw-text-opacity:1;color:rgb(133 149 171/var(--tw-text-opacity,1))}.text-slate-600{--tw-text-opacity:1;color:rgb(107 124 147/var(--tw-text-opacity,1))}.text-white{--tw-text-opacity:1;color:rgb(255 255 255/var(--tw-text-opacity,1))}.underline{text-decoration-line:underline}.accent-indigo-500{accent-color:#6366f1}.opacity-40{opacity:.4}.opacity-50{opacity:.5}.opacity-60{opacity:.6}.opacity-70{opacity:.7}.opacity-80{opacity:.8}.outline{outline-style:solid}.ring{--tw-ring-offset-shadow:var(--tw-ring-inset) 0 0 0 var(--tw-ring-offset-width) var(--tw-ring-offset-color);--tw-ring-shadow:var(--tw-ring-inset) 0 0 0 calc(3px + var(--tw-ring-offset-width)) var(--tw-ring-color);box-shadow:var(--tw-ring-offset-shadow),var(--tw-ring-shadow),var(--tw-shadow,0 0 #0000)}.blur{--tw-blur:blur(8px)}.blur,.filter{filter:var(--tw-blur) var(--tw-brightness) var(--tw-contrast) var(--tw-grayscale) var(--tw-hue-rotate) var(--tw-invert) var(--tw-saturate) var(--tw-sepia) var(--tw-drop-shadow)}.backdrop-blur-sm{--tw-backdrop-blur:blur(4px)}.backdrop-blur-sm,.backdrop-filter{-webkit-backdrop-filter:var(--tw-backdrop-blur) var(--tw-backdrop-brightness) var(--tw-backdrop-contrast) var(--tw-backdrop-grayscale) var(--tw-backdrop-hue-rotate) var(--tw-backdrop-invert) var(--tw-backdrop-opacity) var(--tw-backdrop-saturate) var(--tw-backdrop-sepia);backdrop-filter:var(--tw-backdrop-blur) var(--tw-backdrop-brightness) var(--tw-backdrop-contrast) var(--tw-backdrop-grayscale) var(--tw-backdrop-hue-rotate) var(--tw-backdrop-invert) var(--tw-backdrop-opacity) var(--tw-backdrop-saturate) var(--tw-backdrop-sepia)}.transition{transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,opacity,box-shadow,transform,filter,-webkit-backdrop-filter;transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,opacity,box-shadow,transform,filter,backdrop-filter;transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,opacity,box-shadow,transform,filter,backdrop-filter,-webkit-backdrop-filter;transition-timing-function:cubic-bezier(.4,0,.2,1);transition-duration:.15s}.transition-all{transition-property:all;transition-timing-function:cubic-bezier(.4,0,.2,1);transition-duration:.15s}.transition-colors{transition-property:color,background-color,border-color,text-decoration-color,fill,stroke;transition-timing-function:cubic-bezier(.4,0,.2,1);transition-duration:.15s}.\[from\:agent-name\]{from:agent-name}.hover\:border-indigo-500:hover{--tw-border-opacity:1;border-color:rgb(99 102 241/var(--tw-border-opacity,1))}.hover\:bg-amber-500:hover{--tw-bg-opacity:1;background-color:rgb(245 158 11/var(--tw-bg-opacity,1))}.hover\:bg-amber-900\/60:hover{background-color:rgba(120,53,15,.6)}.hover\:bg-emerald-600\/50:hover{background-color:rgba(5,150,105,.5)}.hover\:bg-indigo-500:hover{--tw-bg-opacity:1;background-color:rgb(99 102 241/var(--tw-bg-opacity,1))}.hover\:bg-indigo-600\/50:hover{background-color:rgba(79,70,229,.5)}.hover\:bg-indigo-600\/60:hover{background-color:rgba(79,70,229,.6)}.hover\:bg-purple-600\/50:hover{background-color:rgba(147,51,234,.5)}.hover\:bg-red-800:hover{--tw-bg-opacity:1;background-color:rgb(153 27 27/var(--tw-bg-opacity,1))}.hover\:bg-red-900\/60:hover{background-color:rgba(127,29,29,.6)}.hover\:bg-slate-600:hover{--tw-bg-opacity:1;background-color:rgb(107 124 147/var(--tw-bg-opacity,1))}.hover\:bg-slate-700:hover{--tw-bg-opacity:1;background-color:rgb(51 65 85/var(--tw-bg-opacity,1))}.hover\:bg-slate-700\/50:hover{background-color:rgba(51,65,85,.5)}.hover\:bg-slate-800:hover{--tw-bg-opacity:1;background-color:rgb(30 41 59/var(--tw-bg-opacity,1))}.hover\:bg-slate-800\/30:hover{background-color:rgba(30,41,59,.3)}.hover\:bg-slate-800\/50:hover{background-color:rgba(30,41,59,.5)}.hover\:text-amber-300:hover{--tw-text-opacity:1;color:rgb(252 211 77/var(--tw-text-opacity,1))}.hover\:text-green-300:hover{--tw-text-opacity:1;color:rgb(134 239 172/var(--tw-text-opacity,1))}.hover\:text-indigo-200:hover{--tw-text-opacity:1;color:rgb(199 210 254/var(--tw-text-opacity,1))}.hover\:text-indigo-300:hover{--tw-text-opacity:1;color:rgb(165 180 252/var(--tw-text-opacity,1))}.hover\:text-purple-300:hover{--tw-text-opacity:1;color:rgb(216 180 254/var(--tw-text-opacity,1))}.hover\:text-red-300:hover{--tw-text-opacity:1;color:rgb(252 165 165/var(--tw-text-opacity,1))}.hover\:text-red-400:hover{--tw-text-opacity:1;color:rgb(248 113 113/var(--tw-text-opacity,1))}.hover\:text-slate-200:hover{--tw-text-opacity:1;color:rgb(226 232 240/var(--tw-text-opacity,1))}.hover\:text-slate-300:hover{--tw-text-opacity:1;color:rgb(203 213 225/var(--tw-text-opacity,1))}.hover\:text-white:hover{--tw-text-opacity:1;color:rgb(255 255 255/var(--tw-text-opacity,1))}.hover\:opacity-70:hover{opacity:.7}.focus\:border-indigo-500:focus{--tw-border-opacity:1;border-color:rgb(99 102 241/var(--tw-border-opacity,1))}.focus\:outline-none:focus{outline:2px solid transparent;outline-offset:2px}
\ No newline at end of file
+*,:after,:before{--tw-border-spacing-x:0;--tw-border-spacing-y:0;--tw-translate-x:0;--tw-translate-y:0;--tw-rotate:0;--tw-skew-x:0;--tw-skew-y:0;--tw-scale-x:1;--tw-scale-y:1;--tw-pan-x: ;--tw-pan-y: ;--tw-pinch-zoom: ;--tw-scroll-snap-strictness:proximity;--tw-gradient-from-position: ;--tw-gradient-via-position: ;--tw-gradient-to-position: ;--tw-ordinal: ;--tw-slashed-zero: ;--tw-numeric-figure: ;--tw-numeric-spacing: ;--tw-numeric-fraction: ;--tw-ring-inset: ;--tw-ring-offset-width:0px;--tw-ring-offset-color:#fff;--tw-ring-color:rgba(59,130,246,.5);--tw-ring-offset-shadow:0 0 #0000;--tw-ring-shadow:0 0 #0000;--tw-shadow:0 0 #0000;--tw-shadow-colored:0 0 #0000;--tw-blur: ;--tw-brightness: ;--tw-contrast: ;--tw-grayscale: ;--tw-hue-rotate: ;--tw-invert: ;--tw-saturate: ;--tw-sepia: ;--tw-drop-shadow: ;--tw-backdrop-blur: ;--tw-backdrop-brightness: ;--tw-backdrop-contrast: ;--tw-backdrop-grayscale: ;--tw-backdrop-hue-rotate: ;--tw-backdrop-invert: ;--tw-backdrop-opacity: ;--tw-backdrop-saturate: ;--tw-backdrop-sepia: ;--tw-contain-size: ;--tw-contain-layout: ;--tw-contain-paint: ;--tw-contain-style: }::backdrop{--tw-border-spacing-x:0;--tw-border-spacing-y:0;--tw-translate-x:0;--tw-translate-y:0;--tw-rotate:0;--tw-skew-x:0;--tw-skew-y:0;--tw-scale-x:1;--tw-scale-y:1;--tw-pan-x: ;--tw-pan-y: ;--tw-pinch-zoom: ;--tw-scroll-snap-strictness:proximity;--tw-gradient-from-position: ;--tw-gradient-via-position: ;--tw-gradient-to-position: ;--tw-ordinal: ;--tw-slashed-zero: ;--tw-numeric-figure: ;--tw-numeric-spacing: ;--tw-numeric-fraction: ;--tw-ring-inset: ;--tw-ring-offset-width:0px;--tw-ring-offset-color:#fff;--tw-ring-color:rgba(59,130,246,.5);--tw-ring-offset-shadow:0 0 #0000;--tw-ring-shadow:0 0 #0000;--tw-shadow:0 0 #0000;--tw-shadow-colored:0 0 #0000;--tw-blur: ;--tw-brightness: ;--tw-contrast: ;--tw-grayscale: ;--tw-hue-rotate: ;--tw-invert: ;--tw-saturate: ;--tw-sepia: ;--tw-drop-shadow: ;--tw-backdrop-blur: ;--tw-backdrop-brightness: ;--tw-backdrop-contrast: ;--tw-backdrop-grayscale: ;--tw-backdrop-hue-rotate: ;--tw-backdrop-invert: ;--tw-backdrop-opacity: ;--tw-backdrop-saturate: ;--tw-backdrop-sepia: ;--tw-contain-size: ;--tw-contain-layout: ;--tw-contain-paint: ;--tw-contain-style: }/*! tailwindcss v3.4.17 | MIT License | https://tailwindcss.com*/*,:after,:before{box-sizing:border-box;border:0 solid #e5e7eb}:after,:before{--tw-content:""}:host,html{line-height:1.5;-webkit-text-size-adjust:100%;-moz-tab-size:4;-o-tab-size:4;tab-size:4;font-family:Inter,system-ui,-apple-system,sans-serif;font-feature-settings:normal;font-variation-settings:normal;-webkit-tap-highlight-color:transparent}body{margin:0;line-height:inherit}hr{height:0;color:inherit;border-top-width:1px}abbr:where([title]){-webkit-text-decoration:underline dotted;text-decoration:underline dotted}h1,h2,h3,h4,h5,h6{font-size:inherit;font-weight:inherit}a{color:inherit;text-decoration:inherit}b,strong{font-weight:bolder}code,kbd,pre,samp{font-family:JetBrains Mono,Fira Code,ui-monospace,monospace;font-feature-settings:normal;font-variation-settings:normal;font-size:1em}small{font-size:80%}sub,sup{font-size:75%;line-height:0;position:relative;vertical-align:baseline}sub{bottom:-.25em}sup{top:-.5em}table{text-indent:0;border-color:inherit;border-collapse:collapse}button,input,optgroup,select,textarea{font-family:inherit;font-feature-settings:inherit;font-variation-settings:inherit;font-size:100%;font-weight:inherit;line-height:inherit;letter-spacing:inherit;color:inherit;margin:0;padding:0}button,select{text-transform:none}button,input:where([type=button]),input:where([type=reset]),input:where([type=submit]){-webkit-appearance:button;background-color:transparent;background-image:none}:-moz-focusring{outline:auto}:-moz-ui-invalid{box-shadow:none}progress{vertical-align:baseline}::-webkit-inner-spin-button,::-webkit-outer-spin-button{height:auto}[type=search]{-webkit-appearance:textfield;outline-offset:-2px}::-webkit-search-decoration{-webkit-appearance:none}::-webkit-file-upload-button{-webkit-appearance:button;font:inherit}summary{display:list-item}blockquote,dd,dl,figure,h1,h2,h3,h4,h5,h6,hr,p,pre{margin:0}fieldset{margin:0}fieldset,legend{padding:0}menu,ol,ul{list-style:none;margin:0;padding:0}dialog{padding:0}textarea{resize:vertical}input::-moz-placeholder,textarea::-moz-placeholder{opacity:1;color:#9ca3af}input::placeholder,textarea::placeholder{opacity:1;color:#9ca3af}[role=button],button{cursor:pointer}:disabled{cursor:default}audio,canvas,embed,iframe,img,object,svg,video{display:block;vertical-align:middle}img,video{max-width:100%;height:auto}[hidden]:where(:not([hidden=until-found])){display:none}.\!container{width:100%!important}.container{width:100%}@media (min-width:640px){.\!container{max-width:640px!important}.container{max-width:640px}}@media (min-width:768px){.\!container{max-width:768px!important}.container{max-width:768px}}@media (min-width:1024px){.\!container{max-width:1024px!important}.container{max-width:1024px}}@media (min-width:1280px){.\!container{max-width:1280px!important}.container{max-width:1280px}}@media (min-width:1536px){.\!container{max-width:1536px!important}.container{max-width:1536px}}.visible{visibility:visible}.collapse{visibility:collapse}.fixed{position:fixed}.absolute{position:absolute}.relative{position:relative}.inset-0{inset:0}.-right-1{right:-.25rem}.-top-1{top:-.25rem}.right-0{right:0}.top-full{top:100%}.z-50{z-index:50}.mb-1{margin-bottom:.25rem}.mb-2{margin-bottom:.5rem}.mb-3{margin-bottom:.75rem}.mb-4{margin-bottom:1rem}.mb-5{margin-bottom:1.25rem}.ml-16{margin-left:4rem}.ml-3{margin-left:.75rem}.ml-4{margin-left:1rem}.mr-auto{margin-right:auto}.mt-0\.5{margin-top:.125rem}.mt-1{margin-top:.25rem}.mt-2{margin-top:.5rem}.mt-3{margin-top:.75rem}.\!block{display:block!important}.block{display:block}.inline{display:inline}.flex{display:flex}.table{display:table}.\!grid{display:grid!important}.grid{display:grid}.hidden{display:none}.h-1{height:.25rem}.h-1\.5{height:.375rem}.h-4{height:1rem}.h-full{height:100%}.h-screen{height:100vh}.max-h-48{max-height:12rem}.max-h-\[300px\]{max-height:300px}.max-h-\[80vh\]{max-height:80vh}.max-h-\[85vh\]{max-height:85vh}.min-h-0{min-height:0}.w-1\.5{width:.375rem}.w-4{width:1rem}.w-44{width:11rem}.w-6{width:1.5rem}.w-\[250px\]{width:250px}.w-\[320px\]{width:320px}.w-\[380px\]{width:380px}.w-\[420px\]{width:420px}.w-\[480px\]{width:480px}.w-\[700px\]{width:700px}.w-\[900px\]{width:900px}.w-\[90vw\]{width:90vw}.w-full{width:100%}.min-w-0{min-width:0}.max-w-3xl{max-width:48rem}.max-w-4xl{max-width:56rem}.max-w-\[70\%\]{max-width:70%}.max-w-\[90vw\]{max-width:90vw}.max-w-\[92vw\]{max-width:92vw}.flex-1{flex:1 1 0%}.shrink-0{flex-shrink:0}.grow{flex-grow:1}.cursor-default{cursor:default}.cursor-not-allowed{cursor:not-allowed}.cursor-pointer{cursor:pointer}.select-none{-webkit-user-select:none;-moz-user-select:none;user-select:none}.resize-none{resize:none}.grid-cols-2{grid-template-columns:repeat(2,minmax(0,1fr))}.flex-col{flex-direction:column}.flex-wrap{flex-wrap:wrap}.items-start{align-items:flex-start}.items-center{align-items:center}.justify-center{justify-content:center}.justify-between{justify-content:space-between}.gap-1{gap:.25rem}.gap-1\.5{gap:.375rem}.gap-2{gap:.5rem}.gap-3{gap:.75rem}.gap-x-4{-moz-column-gap:1rem;column-gap:1rem}.gap-y-1{row-gap:.25rem}.space-y-1>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-top:calc(.25rem*(1 - var(--tw-space-y-reverse)));margin-bottom:calc(.25rem*var(--tw-space-y-reverse))}.space-y-1\.5>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-top:calc(.375rem*(1 - var(--tw-space-y-reverse)));margin-bottom:calc(.375rem*var(--tw-space-y-reverse))}.space-y-2>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-top:calc(.5rem*(1 - var(--tw-space-y-reverse)));margin-bottom:calc(.5rem*var(--tw-space-y-reverse))}.space-y-3>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-top:calc(.75rem*(1 - var(--tw-space-y-reverse)));margin-bottom:calc(.75rem*var(--tw-space-y-reverse))}.self-end{align-self:flex-end}.overflow-auto{overflow:auto}.overflow-hidden{overflow:hidden}.overflow-x-auto{overflow-x:auto}.overflow-y-auto{overflow-y:auto}.overflow-x-hidden{overflow-x:hidden}.truncate{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.whitespace-pre-wrap{white-space:pre-wrap}.break-words{overflow-wrap:break-word}.break-all{word-break:break-all}.rounded{border-radius:.25rem}.rounded-2xl{border-radius:1rem}.rounded-full{border-radius:9999px}.rounded-lg{border-radius:.5rem}.rounded-xl{border-radius:.75rem}.border{border-width:1px}.border-b{border-bottom-width:1px}.border-b-2{border-bottom-width:2px}.border-l{border-left-width:1px}.border-l-2{border-left-width:2px}.border-r{border-right-width:1px}.border-t{border-top-width:1px}.border-dashed{border-style:dashed}.border-amber-500\/40{border-color:rgba(245,158,11,.4)}.border-indigo-400{--tw-border-opacity:1;border-color:rgb(129 140 248/var(--tw-border-opacity,1))}.border-indigo-500{--tw-border-opacity:1;border-color:rgb(99 102 241/var(--tw-border-opacity,1))}.border-indigo-500\/30{border-color:rgba(99,102,241,.3)}.border-purple-800\/60{border-color:rgba(107,33,168,.6)}.border-red-900\/50{border-color:rgba(127,29,29,.5)}.border-slate-700{--tw-border-opacity:1;border-color:rgb(51 65 85/var(--tw-border-opacity,1))}.border-slate-700\/30{border-color:rgba(51,65,85,.3)}.border-slate-700\/40{border-color:rgba(51,65,85,.4)}.border-slate-700\/50{border-color:rgba(51,65,85,.5)}.border-slate-800{--tw-border-opacity:1;border-color:rgb(30 41 59/var(--tw-border-opacity,1))}.border-slate-800\/50{border-color:rgba(30,41,59,.5)}.border-slate-800\/70{border-color:rgba(30,41,59,.7)}.border-slate-800\/80{border-color:rgba(30,41,59,.8)}.border-transparent{border-color:transparent}.bg-\[\#0f172a\]{--tw-bg-opacity:1;background-color:rgb(15 23 42/var(--tw-bg-opacity,1))}.bg-amber-400{--tw-bg-opacity:1;background-color:rgb(251 191 36/var(--tw-bg-opacity,1))}.bg-amber-500\/10{background-color:rgba(245,158,11,.1)}.bg-amber-500\/15{background-color:rgba(245,158,11,.15)}.bg-black\/60{background-color:rgba(0,0,0,.6)}.bg-blue-400{--tw-bg-opacity:1;background-color:rgb(96 165 250/var(--tw-bg-opacity,1))}.bg-emerald-400{--tw-bg-opacity:1;background-color:rgb(52 211 153/var(--tw-bg-opacity,1))}.bg-emerald-600\/30{background-color:rgba(5,150,105,.3)}.bg-indigo-600{--tw-bg-opacity:1;background-color:rgb(79 70 229/var(--tw-bg-opacity,1))}.bg-indigo-600\/30{background-color:rgba(79,70,229,.3)}.bg-indigo-600\/40{background-color:rgba(79,70,229,.4)}.bg-indigo-900\/30{background-color:rgba(49,46,129,.3)}.bg-purple-500\/10{background-color:rgba(168,85,247,.1)}.bg-purple-600\/30{background-color:rgba(147,51,234,.3)}.bg-red-400{--tw-bg-opacity:1;background-color:rgb(248 113 113/var(--tw-bg-opacity,1))}.bg-red-600{--tw-bg-opacity:1;background-color:rgb(220 38 38/var(--tw-bg-opacity,1))}.bg-red-900{--tw-bg-opacity:1;background-color:rgb(127 29 29/var(--tw-bg-opacity,1))}.bg-red-950\/30{background-color:rgba(69,10,10,.3)}.bg-sky-500\/10{background-color:rgba(14,165,233,.1)}.bg-slate-400{--tw-bg-opacity:1;background-color:rgb(166 179 198/var(--tw-bg-opacity,1))}.bg-slate-500{--tw-bg-opacity:1;background-color:rgb(133 149 171/var(--tw-bg-opacity,1))}.bg-slate-700{--tw-bg-opacity:1;background-color:rgb(51 65 85/var(--tw-bg-opacity,1))}.bg-slate-800{--tw-bg-opacity:1;background-color:rgb(30 41 59/var(--tw-bg-opacity,1))}.bg-slate-800\/40{background-color:rgba(30,41,59,.4)}.bg-slate-800\/50{background-color:rgba(30,41,59,.5)}.bg-slate-800\/60{background-color:rgba(30,41,59,.6)}.bg-slate-900{--tw-bg-opacity:1;background-color:rgb(15 23 42/var(--tw-bg-opacity,1))}.bg-slate-900\/50{background-color:rgba(15,23,42,.5)}.bg-slate-900\/60{background-color:rgba(15,23,42,.6)}.bg-slate-950\/20{background-color:rgba(2,6,23,.2)}.bg-slate-950\/30{background-color:rgba(2,6,23,.3)}.bg-slate-950\/60{background-color:rgba(2,6,23,.6)}.bg-white{--tw-bg-opacity:1;background-color:rgb(255 255 255/var(--tw-bg-opacity,1))}.p-0{padding:0}.p-1{padding:.25rem}.p-2{padding:.5rem}.p-2\.5{padding:.625rem}.p-3{padding:.75rem}.p-4{padding:1rem}.p-6{padding:1.5rem}.px-1{padding-left:.25rem;padding-right:.25rem}.px-1\.5{padding-left:.375rem;padding-right:.375rem}.px-2{padding-left:.5rem;padding-right:.5rem}.px-2\.5{padding-left:.625rem;padding-right:.625rem}.px-3{padding-left:.75rem;padding-right:.75rem}.px-4{padding-left:1rem;padding-right:1rem}.px-5{padding-left:1.25rem;padding-right:1.25rem}.py-0\.5{padding-top:.125rem;padding-bottom:.125rem}.py-1{padding-top:.25rem;padding-bottom:.25rem}.py-1\.5{padding-top:.375rem;padding-bottom:.375rem}.py-2{padding-top:.5rem;padding-bottom:.5rem}.py-3{padding-top:.75rem;padding-bottom:.75rem}.py-6{padding-top:1.5rem;padding-bottom:1.5rem}.py-8{padding-top:2rem;padding-bottom:2rem}.pb-1{padding-bottom:.25rem}.pl-2{padding-left:.5rem}.pr-1{padding-right:.25rem}.pt-2{padding-top:.5rem}.text-center{text-align:center}.text-right{text-align:right}.font-mono{font-family:JetBrains Mono,Fira Code,ui-monospace,monospace}.text-\[10px\]{font-size:10px}.text-\[11px\]{font-size:11px}.text-\[9px\]{font-size:9px}.text-lg{font-size:1.125rem;line-height:1.75rem}.text-sm{font-size:.875rem;line-height:1.25rem}.text-xs{font-size:.75rem;line-height:1rem}.font-bold{font-weight:700}.font-medium{font-weight:500}.font-semibold{font-weight:600}.uppercase{text-transform:uppercase}.lowercase{text-transform:lowercase}.italic{font-style:italic}.leading-none{line-height:1}.leading-relaxed{line-height:1.625}.tracking-\[0\.16em\]{letter-spacing:.16em}.tracking-tight{letter-spacing:-.025em}.tracking-wider{letter-spacing:.05em}.text-amber-100{--tw-text-opacity:1;color:rgb(254 243 199/var(--tw-text-opacity,1))}.text-amber-200{--tw-text-opacity:1;color:rgb(253 230 138/var(--tw-text-opacity,1))}.text-amber-300{--tw-text-opacity:1;color:rgb(252 211 77/var(--tw-text-opacity,1))}.text-amber-400{--tw-text-opacity:1;color:rgb(251 191 36/var(--tw-text-opacity,1))}.text-amber-400\/70{color:rgba(251,191,36,.7)}.text-cyan-400{--tw-text-opacity:1;color:rgb(34 211 238/var(--tw-text-opacity,1))}.text-emerald-300{--tw-text-opacity:1;color:rgb(110 231 183/var(--tw-text-opacity,1))}.text-emerald-400{--tw-text-opacity:1;color:rgb(52 211 153/var(--tw-text-opacity,1))}.text-fuchsia-400{--tw-text-opacity:1;color:rgb(232 121 249/var(--tw-text-opacity,1))}.text-green-400{--tw-text-opacity:1;color:rgb(74 222 128/var(--tw-text-opacity,1))}.text-indigo-300{--tw-text-opacity:1;color:rgb(165 180 252/var(--tw-text-opacity,1))}.text-indigo-400{--tw-text-opacity:1;color:rgb(129 140 248/var(--tw-text-opacity,1))}.text-purple-200{--tw-text-opacity:1;color:rgb(233 213 255/var(--tw-text-opacity,1))}.text-purple-300{--tw-text-opacity:1;color:rgb(216 180 254/var(--tw-text-opacity,1))}.text-purple-400{--tw-text-opacity:1;color:rgb(192 132 252/var(--tw-text-opacity,1))}.text-red-400{--tw-text-opacity:1;color:rgb(248 113 113/var(--tw-text-opacity,1))}.text-sky-300{--tw-text-opacity:1;color:rgb(125 211 252/var(--tw-text-opacity,1))}.text-sky-400{--tw-text-opacity:1;color:rgb(56 189 248/var(--tw-text-opacity,1))}.text-slate-200{--tw-text-opacity:1;color:rgb(226 232 240/var(--tw-text-opacity,1))}.text-slate-300{--tw-text-opacity:1;color:rgb(203 213 225/var(--tw-text-opacity,1))}.text-slate-400{--tw-text-opacity:1;color:rgb(166 179 198/var(--tw-text-opacity,1))}.text-slate-500{--tw-text-opacity:1;color:rgb(133 149 171/var(--tw-text-opacity,1))}.text-slate-600{--tw-text-opacity:1;color:rgb(107 124 147/var(--tw-text-opacity,1))}.text-white{--tw-text-opacity:1;color:rgb(255 255 255/var(--tw-text-opacity,1))}.underline{text-decoration-line:underline}.line-through{text-decoration-line:line-through}.accent-indigo-500{accent-color:#6366f1}.opacity-40{opacity:.4}.opacity-50{opacity:.5}.opacity-60{opacity:.6}.opacity-70{opacity:.7}.opacity-80{opacity:.8}.outline{outline-style:solid}.ring{--tw-ring-offset-shadow:var(--tw-ring-inset) 0 0 0 var(--tw-ring-offset-width) var(--tw-ring-offset-color);--tw-ring-shadow:var(--tw-ring-inset) 0 0 0 calc(3px + var(--tw-ring-offset-width)) var(--tw-ring-color);box-shadow:var(--tw-ring-offset-shadow),var(--tw-ring-shadow),var(--tw-shadow,0 0 #0000)}.blur{--tw-blur:blur(8px)}.blur,.filter{filter:var(--tw-blur) var(--tw-brightness) var(--tw-contrast) var(--tw-grayscale) var(--tw-hue-rotate) var(--tw-invert) var(--tw-saturate) var(--tw-sepia) var(--tw-drop-shadow)}.backdrop-blur-sm{--tw-backdrop-blur:blur(4px)}.backdrop-blur-sm,.backdrop-filter{-webkit-backdrop-filter:var(--tw-backdrop-blur) var(--tw-backdrop-brightness) var(--tw-backdrop-contrast) var(--tw-backdrop-grayscale) var(--tw-backdrop-hue-rotate) var(--tw-backdrop-invert) var(--tw-backdrop-opacity) var(--tw-backdrop-saturate) var(--tw-backdrop-sepia);backdrop-filter:var(--tw-backdrop-blur) var(--tw-backdrop-brightness) var(--tw-backdrop-contrast) var(--tw-backdrop-grayscale) var(--tw-backdrop-hue-rotate) var(--tw-backdrop-invert) var(--tw-backdrop-opacity) var(--tw-backdrop-saturate) var(--tw-backdrop-sepia)}.transition{transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,opacity,box-shadow,transform,filter,-webkit-backdrop-filter;transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,opacity,box-shadow,transform,filter,backdrop-filter;transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,opacity,box-shadow,transform,filter,backdrop-filter,-webkit-backdrop-filter;transition-timing-function:cubic-bezier(.4,0,.2,1);transition-duration:.15s}.transition-all{transition-property:all;transition-timing-function:cubic-bezier(.4,0,.2,1);transition-duration:.15s}.transition-colors{transition-property:color,background-color,border-color,text-decoration-color,fill,stroke;transition-timing-function:cubic-bezier(.4,0,.2,1);transition-duration:.15s}.hover\:border-indigo-500:hover{--tw-border-opacity:1;border-color:rgb(99 102 241/var(--tw-border-opacity,1))}.hover\:bg-amber-900\/60:hover{background-color:rgba(120,53,15,.6)}.hover\:bg-emerald-600\/50:hover{background-color:rgba(5,150,105,.5)}.hover\:bg-indigo-500:hover{--tw-bg-opacity:1;background-color:rgb(99 102 241/var(--tw-bg-opacity,1))}.hover\:bg-indigo-600\/50:hover{background-color:rgba(79,70,229,.5)}.hover\:bg-indigo-600\/60:hover{background-color:rgba(79,70,229,.6)}.hover\:bg-purple-600\/50:hover{background-color:rgba(147,51,234,.5)}.hover\:bg-red-800:hover{--tw-bg-opacity:1;background-color:rgb(153 27 27/var(--tw-bg-opacity,1))}.hover\:bg-red-900\/60:hover{background-color:rgba(127,29,29,.6)}.hover\:bg-slate-700:hover{--tw-bg-opacity:1;background-color:rgb(51 65 85/var(--tw-bg-opacity,1))}.hover\:bg-slate-800:hover{--tw-bg-opacity:1;background-color:rgb(30 41 59/var(--tw-bg-opacity,1))}.hover\:bg-slate-800\/30:hover{background-color:rgba(30,41,59,.3)}.hover\:bg-slate-800\/50:hover{background-color:rgba(30,41,59,.5)}.hover\:bg-slate-800\/60:hover{background-color:rgba(30,41,59,.6)}.hover\:text-amber-300:hover{--tw-text-opacity:1;color:rgb(252 211 77/var(--tw-text-opacity,1))}.hover\:text-green-300:hover{--tw-text-opacity:1;color:rgb(134 239 172/var(--tw-text-opacity,1))}.hover\:text-indigo-200:hover{--tw-text-opacity:1;color:rgb(199 210 254/var(--tw-text-opacity,1))}.hover\:text-indigo-300:hover{--tw-text-opacity:1;color:rgb(165 180 252/var(--tw-text-opacity,1))}.hover\:text-purple-300:hover{--tw-text-opacity:1;color:rgb(216 180 254/var(--tw-text-opacity,1))}.hover\:text-red-300:hover{--tw-text-opacity:1;color:rgb(252 165 165/var(--tw-text-opacity,1))}.hover\:text-red-400:hover{--tw-text-opacity:1;color:rgb(248 113 113/var(--tw-text-opacity,1))}.hover\:text-slate-200:hover{--tw-text-opacity:1;color:rgb(226 232 240/var(--tw-text-opacity,1))}.hover\:text-slate-300:hover{--tw-text-opacity:1;color:rgb(203 213 225/var(--tw-text-opacity,1))}.hover\:text-white:hover{--tw-text-opacity:1;color:rgb(255 255 255/var(--tw-text-opacity,1))}.hover\:opacity-70:hover{opacity:.7}.focus\:border-indigo-500:focus{--tw-border-opacity:1;border-color:rgb(99 102 241/var(--tw-border-opacity,1))}.focus\:outline-none:focus{outline:2px solid transparent;outline-offset:2px}
\ No newline at end of file
diff --git a/pyproject.toml b/pyproject.toml
index 6ef0f0e34..279c6e568 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -55,22 +55,23 @@ dev = [
 # Ставить дату НОВЕЕ лока нельзя — следующий `uv lock` тогда разом обновит ~40 пакетов
 # (проверено: uvicorn 0.48 → 0.52.1, aiogram 3.28.2 → 3.30.0). Двигать эту дату — значит
 # осознанно обновлять зависимости: меняешь дату, гоняешь `uv lock`, гоняешь тесты, коммитишь
 # лок и дату ОДНИМ коммитом.
 exclude-newer = "2026-07-09T10:16:55.018333899Z"
 
 [tool.pytest.ini_options]
 # Живые пробы сняты со ВСЯКОГО прогона, а не только с команды merge-gate (#328 закрыл
 # лишь гейт). Плоский `uv run pytest -q` собирал их обратно и вис до упора на исчерпанной
 # квоте Codex: замер #336 — прогон убит по общему таймауту с EXIT=124 на 78%, окно потеряно
 # молча. Защита, действующая только когда запускающий помнит про флаг, в автоматике не
 # исполняется. CLI перебивает эту строку, а не складывается с ней (`-m` — одно значение,
 # побеждает последнее): `pytest -m live_probe tests/` собирает 3 пробы из 3214, обычный
 # прогон — 3211 из 3214, ровно столько же, сколько командой гейта.
 addopts = ["-m", "not live_probe"]
 testpaths = ["tests"]
 norecursedirs = ["worktrees", ".venv", "data", "docs"]
 markers = [
     "needs_two_users: требует беспарольного sudo — владение файлами не моделируется заглушками",
     "needs_model: требует эмбеддер (orchestra[rag]) — индексация и поиск не моделируются заглушками",
+    "browser: поднимает НАСТОЯЩИЙ Chromium через Playwright. Снят с блокирующего набора merge-гейта (`-m \"not live_probe and not browser\"`), но продолжает гоняться в CI отдельной джобой и вручную: `uv run pytest -m browser tests/`. Маркер ставится автоматически по факту запроса браузерной фикстуры (`tests/conftest.py`), списком файлов не задаётся. Состав закреплён `test_browser_inventory_is_explicit`",
     "live_probe: тратит настоящий ход провайдера (поднимает CLI, шлёт запрос). Краснеет от квоты и капризов провайдера, а не от диффа, поэтому merge-gate его не гоняет — запускать вручную `uv run pytest -m live_probe tests/`. Новую такую пробу заводить только вместе с записью в test_live_probe_inventory_is_explicit",
 ]
diff --git a/scripts/check_kb_contract.py b/scripts/check_kb_contract.py
index 80df3b0b0..3a870ad53 100755
--- a/scripts/check_kb_contract.py
+++ b/scripts/check_kb_contract.py
@@ -4,40 +4,43 @@
 A structured fact declares a stable key in the TAIL of its bullet — `` · ключ `fact:<key>` `` —
 not at the head. #523 retired the head form on the owner's decision: a record that opens with a
 machine key is not read by a human, and the key is only needed when another record or code
 points at it. Bullets without a key are plain prose and stay grandfathered, exactly as
 non-`fact:` bullets always were.
 """
 
 from __future__ import annotations
 
 import argparse
 import re
 import subprocess
 import sys
 from dataclasses import dataclass
 from pathlib import Path
 
 
 FACT_KEY_FIELD = " · ключ `fact:"
 FACT_RE = re.compile(r"^- (.*?) · ключ `fact:([^`]+)`(?: \([^)]*\))?\s*$")
 KEY_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
+# LEGACY_PATH_FIXTURE: the old spelling below is DATA this regex must keep matching, not a
+# live path of ours. Without the marker `scripts/check_orchestra_paths.py` counts it as a
+# surviving pre-migration path and the layout guard fails on its own gate.
 # A pointer into our own task artifacts; `docs/tasks/…` is the pre-migration spelling of the
 # same thing, so both are gated. Anything else in a record (upstream repositories, absolute
 # host paths, synthetic file names in a scratch experiment) is not ours to keep openable.
 TASK_PATH_RE = re.compile(r"""(?<![\w/])(?:\.orchestra|docs)/tasks/[^\s,;·)\]`'"]*[./][^\s,;·)\]`'"]+""")
 # `· открыть:` is the single field that says how to open a path missing from the working tree.
 # Only this field grants coverage: `→` and `git show` occur all over the KB as ordinary prose,
 # and a record must not close its own pointer by accident. Items are separated by `; `, so a
 # reason may not contain one; every form names the missing path, so coverage is per path.
 OPEN_FIELD_RE = re.compile(r" · открыть: (.*)$")
 SNAPSHOT_RE = re.compile(r"\A`git show ([0-9a-f]{40}):([^`]+)`\Z")
 MOVED_RE = re.compile(r"\A(\S+) → `([^`]+)`\Z")
 ABSENT_RE = re.compile(r"\A(\S+) — нет в репозитории:(.*)\Z")
 HUNK_RE = re.compile(
     r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
 )
 ANCHOR_RE = re.compile(r"`[^`]+`|«[^»]+»")
 VALID_SECTIONS = {"Established", "Rejected", "Historical observations"}
 VALID_RELATIONS = {
     "depends_on",
     "explains",
diff --git a/scripts/verify_orchestra_move.py b/scripts/verify_orchestra_move.py
index df1723a17..9ec2a8252 100644
--- a/scripts/verify_orchestra_move.py
+++ b/scripts/verify_orchestra_move.py
@@ -80,66 +80,114 @@ def blob_contents(root: Path, blobs: list[str]) -> dict[str, bytes]:
         capture_output=True,
         check=True,
     ).stdout
     result = {}
     offset = 0
     for expected in ordered:
         end_header = output.index(b"\n", offset)
         blob, object_type, raw_size = output[offset:end_header].decode().split()
         size = int(raw_size)
         start = end_header + 1
         end = start + size
         if (blob, object_type) != (expected, "blob") or output[end:end + 1] != b"\n":
             raise ValueError(f"invalid batch response for {expected}")
         result[blob] = output[start:end]
         offset = end + 1
     if offset != len(output):
         raise ValueError("trailing batch bytes")
     return result
 
 
-def verify(root: Path, before_ref: str, after_ref: str) -> dict:
-    sources = [prefix.rstrip("/") for prefix in PREFIXES] + sorted(FILES)
-    before = tree(root, before_ref, sources)
+# Переезд шёл ТРЕМЯ коммитами, а не одним и не двумя. Проверено по коммитам, которые
+# УДАЛИЛИ исходный путь (`git log main --diff-filter=D -- <источник>`):
+#   498c0d14 — `docs/kb`, `docs/archive`
+#   4f97f176 — `docs/tasks`
+#   f8e00522 — остальные 15 отображений (`pipelines/`, `docs/workers`, `docs/research`,
+#              `docs/reviews`, `docs/artifacts`, `docs/experiments`, `docs/tg-media`
+#              и все одиночные файлы)
+# Одна пара ссылок на всё поэтому недостижима в принципе: на паре одного переезда цели
+# остальных ещё не существуют, а пара, растянутая на все три, включает посторонние правки
+# между ними, и sha256 честно расходятся. Отсюда контракт: пара ссылок задаётся НА КАЖДЫЙ
+# переезд отдельно, вместе с корнем исходных путей, который этот переезд трогал.
+
+
+def verify_move(root: Path, source_root: str, before_ref: str, after_ref: str) -> dict:
+    before = tree(root, before_ref, [source_root])
+    if not before:
+        raise ValueError(f"{source_root!r} is empty at {before_ref!r} — wrong ref pair")
     after = tree(root, after_ref, [".orchestra"])
     contents = blob_contents(root, [blob for _, blob in before.values()])
     mismatches = []
     for old_path, (old_mode, old_blob) in before.items():
         new_path = destination(old_path)
         observed = after.get(new_path)
         if observed != (old_mode, old_blob):
-            mismatches.append(
-                {"old": old_path, "new": new_path, "expected": [old_mode, old_blob], "observed": observed}
-            )
+            # Два РАЗНЫХ дефекта, и путать их нельзя: `missing` означает, что отображение
+            # путей не сработало (файл не доехал), `content` — что доехал, но с другими
+            # байтами. Первое — всегда поломка переезда. Второе законно ровно там, где
+            # переезд по замыслу правил содержимое: `pipelines/` переехал вместе с заменой
+            # ссылок `docs/` → `.orchestra/` внутри самих промптов (16 файлов из 24,
+            # похожесть 83–99% по `git diff -M`).
+            mismatches.append({
+                "kind": "missing" if observed is None else "content",
+                "old": old_path, "new": new_path,
+                "expected": [old_mode, old_blob], "observed": observed,
+            })
             continue
         data = contents[old_blob]
         # Compute every requested field from the immutable source blob; blob equality proves after parity.
         _ = (len(data), data.count(b"\n"), hashlib.sha256(data).hexdigest())
-    prompt = git(
-        root,
-        "show",
-        f"{after_ref}:.orchestra/pipelines/default/prompts/roles/orchestrator.md",
-    )
     return {
+        "source_root": source_root,
         "before_ref": before_ref,
         "after_ref": after_ref,
         "checked_files": len(before),
-        "fields": FIELDS,
+        "missing": sum(1 for item in mismatches if item["kind"] == "missing"),
+        "content": sum(1 for item in mismatches if item["kind"] == "content"),
         "mismatches": mismatches,
-        "artifact_reading_count": prompt.count("artifact-reading"),
+    }
+
+
+def verify(root: Path, moves: list[tuple[str, str, str]]) -> dict:
+    results = [verify_move(root, *move) for move in moves]
+    flat = [
+        {"move": item["source_root"], **entry}
+        for item in results
+        for entry in item["mismatches"]
+    ]
+    # Промпт лежит под `.orchestra/pipelines/`, поэтому читается по ссылке ИМЕННО того
+    # переезда, который его туда перенёс. На ссылках остальных переездов пути ещё нет.
+    prompt_refs = [item["after_ref"] for item in results if item["source_root"].startswith("pipelines")]
+    artifact_reading_count = None
+    if prompt_refs:
+        prompt = git(
+            root,
+            "show",
+            f"{prompt_refs[0]}:.orchestra/pipelines/default/prompts/roles/orchestrator.md",
+        )
+        artifact_reading_count = prompt.count("artifact-reading")
+    return {
+        "moves": results,
+        "checked_files": sum(item["checked_files"] for item in results),
+        "fields": FIELDS,
+        "mismatches": flat,
+        "artifact_reading_count": artifact_reading_count,
     }
 
 
 def main() -> int:
     parser = argparse.ArgumentParser()
     parser.add_argument("--root", type=Path, required=True)
-    parser.add_argument("--before-ref", required=True)
-    parser.add_argument("--after-ref", required=True)
+    parser.add_argument(
+        "--move", nargs=3, action="append", required=True,
+        metavar=("SOURCE_ROOT", "BEFORE_REF", "AFTER_REF"),
+        help="один переезд: корень исходных путей и пара ссылок вокруг него",
+    )
     parser.add_argument("--json", action="store_true")
     args = parser.parse_args()
-    result = verify(args.root.resolve(), args.before_ref, args.after_ref)
+    result = verify(args.root.resolve(), [tuple(move) for move in args.move])
     print(json.dumps(result, ensure_ascii=False, sort_keys=True))
     return 0 if not result["mismatches"] else 1
 
 
 if __name__ == "__main__":
     raise SystemExit(main())
diff --git a/tests/conftest.py b/tests/conftest.py
index aeeb3d3c4..7e5dc9cf4 100644
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -264,24 +264,71 @@ def launch_browser(browser_type_launch_args, browser_type, connect_options):
     if connect_options:
         # Удалённый браузер — этот путь не покрыт: fail loud вместо тихого расхождения
         # с поведением pytest-playwright.
         raise NotImplementedError(
             "connect_options не поддержан модульной фикстурой browser (tests/conftest.py)"
         )
 
     def launch(**kwargs):
         return browser_type.launch(**{**browser_type_launch_args, **kwargs})
 
     return launch
 
 
 @pytest.fixture(scope="module")
 def browser(launch_browser):
     instance = launch_browser()
     yield instance
     instance.close()
 
 
+@pytest.fixture
+def codex_bin_stub(tmp_path, monkeypatch):
+    """Исполняемый файл-заглушка вместо настоящего Codex CLI.
+
+    Тесты, которым нужен ПУТЬ к codex (сборка shell-команды, опознание чужого процесса
+    по argv), на машине без Codex падали не по своему предмету: `codex не найден: ни
+    CODEX_BIN в окружении, ни codex в PATH` и `FileNotFoundError: configured executable
+    was not found`. На GitHub-раннере это 13 падений из 57 — там проприетарного бинаря
+    нет и быть не может. Заглушка — настоящий исполняемый файл, поэтому проверяется
+    ВЕСЬ путь разрешения (`shutil.which`, `_normalise_executable`, `Path.resolve`), а не
+    обходится монкипатчем самой функции разрешения.
+    """
+    stub = tmp_path / "codex"
+    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
+    stub.chmod(0o755)
+    monkeypatch.setenv("CODEX_BIN", str(stub))
+    import app.backend_codex as backend_codex
+
+    monkeypatch.setattr(backend_codex, "CODEX_BIN", str(stub))
+    return stub
+
+
 @pytest.fixture(autouse=True)
 def _isolated_managed_cli_home(tmp_path, monkeypatch):
     """Session removal must never touch the running agents' CLI homes in tests."""
     monkeypatch.setattr("app.backend_codex._CODEX_HOME_ROOT", tmp_path / "codex-home")
+
+
+# Браузерные тесты снимаются с БЛОКИРУЮЩЕГО набора merge-гейта, но продолжают гоняться.
+# Основание — замер оркестратора 07.09: их 95 из 2410 (4% сьюта), файл `test_frontend.py`
+# правился 146 раз и лишь в 24 случаях вместе с настоящим фиксом фронта, то есть в пяти
+# случаях из шести чинили сам тест. При этом ловят они ровно те дефекты, на которые
+# владелец жалуется лично (метка полосы, сырая карточка ревью, телеметрия в чате), —
+# поэтому удалять нельзя. А держать в гейте нельзя тем более: два мержа подряд встали с
+# `TEST_GATE_INCONCLUSIVE`, оба раза бюджет кончился внутри `test_frontend.py` при НУЛЕ
+# красных тестов.
+# Маркер ставится по ФАКТУ запроса браузерной фикстуры, а не списком файлов: список
+# устаревает молча, а фикстура — то самое, что делает тест браузерным.
+# `context` СЮДА НЕ ВХОДИТ намеренно: у pytest-playwright так называется браузерный
+# контекст, но имя слишком общее — параметризованный `context` в
+# `test_codex_review_rejects_missing_project_context_before_any_api_call` (обычная строка)
+# ловился как браузерный и уносил два небраузерных узла из блокирующего набора.
+_BROWSER_FIXTURES = frozenset({
+    "browser", "dashboard_browser", "page", "browser_context",
+})
+
+
+def pytest_collection_modifyitems(config, items):
+    for item in items:
+        if _BROWSER_FIXTURES & set(getattr(item, "fixturenames", ())):
+            item.add_marker("browser")
diff --git a/tests/test_codex_bin_resolution.py b/tests/test_codex_bin_resolution.py
index 27ca07eb4..63042b546 100644
--- a/tests/test_codex_bin_resolution.py
+++ b/tests/test_codex_bin_resolution.py
@@ -5,40 +5,52 @@
 происходит, когда бинарника нет.
 """
 import asyncio
 
 import pytest
 
 
 def _review_text(result):
     if isinstance(result, str):
         return result
     return "\n".join(block.text for block in result.content if block.type == "text")
 
 
 @pytest.fixture
 def mcp(monkeypatch):
     from app import mcp_stdio
     monkeypatch.delenv("CODEX_BIN", raising=False)
     async def available(_model):
         return None
     monkeypatch.setattr(mcp_stdio, "_quota_refusal", available)
+    # #488 сделал загрузку project-context обязательной, и она ходит в git по `cwd`
+    # (`_review_repository_root`, `app/mcp_stdio.py:3616`). Предмет ЭТОГО файла —
+    # разрешение пути к бинарю; без заглушки тест падал бы на чужом шве
+    # (`fatal: not a git repository`) и про путь не проверял бы ничего.
+    monkeypatch.setattr(
+        mcp_stdio,
+        "_load_review_project_context",
+        lambda *_args, **_kwargs: (
+            "PROJECT CONTEXT (test-owned):\n- Scale: codex-bin fixture",
+            {"status": "loaded", "warning": ""},
+        ),
+    )
     return mcp_stdio
 
 
 def test_env_override_wins(mcp, monkeypatch):
     monkeypatch.setenv("CODEX_BIN", "/opt/codex/bin/codex")
     monkeypatch.setattr(mcp.shutil, "which", lambda _: "/usr/bin/codex")
     assert mcp._codex_bin() == "/opt/codex/bin/codex"
 
 
 def test_falls_back_to_path_lookup(mcp, monkeypatch):
     monkeypatch.setattr(mcp.shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
     assert mcp._codex_bin() == "/usr/bin/codex"
 
 
 def test_missing_binary_returns_empty_not_stale_laptop_path(mcp, monkeypatch):
     """Пусто, а не выдуманный путь: несуществующий путь уехал бы в shell и вернулся exit 127."""
     monkeypatch.setattr(mcp.shutil, "which", lambda _: None)
     assert mcp._codex_bin() == ""
 
 
@@ -46,51 +58,56 @@ def test_blank_env_does_not_shadow_path(mcp, monkeypatch):
     """CODEX_BIN='' в .env — частый случай; он не должен маскировать рабочий which."""
     monkeypatch.setenv("CODEX_BIN", "   ")
     monkeypatch.setattr(mcp.shutil, "which", lambda _: "/usr/bin/codex")
     assert mcp._codex_bin() == "/usr/bin/codex"
 
 
 def test_hardcoded_constant_is_gone(mcp):
     """Регресс на саму мину: модульной константы с чужим путём больше нет.
     (Упоминание пути в комментарии-объяснении допустимо — важно, что его не исполняют.)"""
     assert not hasattr(mcp, "_CODEX_BIN")
 
 
 def test_resolution_never_invents_a_path(mcp):
     """Разрешение возвращает либо СУЩЕСТВУЮЩИЙ файл, либо пусто. Фантомный путь — ровно то,
     из-за чего полгода отдавался exit 127 вместо диагноза."""
     import os
     got = mcp._codex_bin()
     assert got == "" or os.path.exists(got), f"разрешён несуществующий путь: {got!r}"
 
 
-def test_missing_binary_gives_actionable_text_instead_of_exit_127(mcp, monkeypatch):
+def test_missing_binary_gives_actionable_text_instead_of_exit_127(mcp, monkeypatch, tmp_path):
     """Главное требование задачи: вместо `/bin/sh: ...: not found` (exit 127) — текст,
-    из которого видно, что чинить."""
+    из которого видно, что чинить.
+
+    Путь берётся из `tmp_path`, а не прибит к `/home/kesha/orchestra`: на раннере такого
+    каталога нет, и тест падал `fatal: cannot change to ...` — то есть проверял машину,
+    а не текст ошибки.
+    """
     monkeypatch.setattr(mcp.shutil, "which", lambda _: None)
     monkeypatch.setattr(mcp, "WORKER_NAME", "perf")
-    monkeypatch.setattr(mcp, "SCOPE", "/home/kesha/orchestra")
+    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
 
     async def fake_api(method, path, **kwargs):
         assert method == "GET"
         assert path == "/api/sessions/perf"
-        return {"id": "test-session", "worktree_path": "/home/kesha/orchestra"}
+        return {"id": "test-session", "worktree_path": str(tmp_path)}
 
     monkeypatch.setattr(mcp, "_api", fake_api)
 
     out = asyncio.run(mcp.codex_review(
         context="PROJECT CONTEXT: test fixture", target="", output="CODEX_REVIEW.md",
     ))
     out = _review_text(out)
 
     assert "codex не найден" in out
     assert "CODEX_BIN" in out and "which codex" in out
     assert "127" not in out
 
 
 def test_resolved_binary_reaches_the_shell_command(mcp, monkeypatch, tmp_path):
     """Позитивный случай: в команду уходит именно разрешённый путь, а не константа."""
     started = {}
 
     async def fake_api(method, path, **kwargs):
         if method == "GET":
             return {"id": "test-session", "worktree_path": str(tmp_path)}
diff --git a/tests/test_codex_review_sandbox.py b/tests/test_codex_review_sandbox.py
index bcb4d4625..58851fb2a 100644
--- a/tests/test_codex_review_sandbox.py
+++ b/tests/test_codex_review_sandbox.py
@@ -65,41 +65,41 @@ def _fake_api(tmp_path, captured):
                 "worktree_path": str(tmp_path),
             }
         captured.update(kwargs["json"])
         return {"id": "bg-test"}
 
     return fake_api
 
 
 def _prepare_usage_db(tmp_path, monkeypatch):
     import app.db as db
 
     path = tmp_path / "usage.db"
     monkeypatch.setattr(db, "DB_PATH", path)
     monkeypatch.setenv("ORCHESTRA_DB_PATH", str(path))
     db.init_db()
 
 
 @pytest.mark.parametrize("mode", ["exec", "review"])
 @pytest.mark.parametrize("resume", [False, True])
 def test_codex_review_disables_unusable_namespace_sandbox(
-    tmp_path, monkeypatch, mode, resume,
+    tmp_path, monkeypatch, mode, resume, codex_bin_stub,
 ):
     import app.mcp_stdio as mcp
 
     if resume:
         (tmp_path / "codex_sessions.json").write_text(json.dumps({
             "sessions": {"review": {"uuid": "019f0000-0000-7000-8000-000000000001"}},
         }))
     captured = {}
     monkeypatch.setattr(mcp, "_api", _fake_api(tmp_path, captured))
     monkeypatch.setattr(mcp, "WORKER_NAME", "sandbox-test")
     monkeypatch.setattr(mcp.time, "time", lambda: 2_000_000_001)
 
     asyncio.run(mcp.codex_review(
         context=PROJECT_CONTEXT, target="artifact.txt",
         output="review.md", mode=mode, resume=resume, model=REVIEW_MODEL,
     ))
 
     command = captured["config"]["command"]
     # This file's subject is the sandbox flags; the model assert is only here to pin that
     # every CLI invocation the command builds (one fresh, or resume + stale-session
diff --git a/tests/test_compact_gate_438.py b/tests/test_compact_gate_438.py
index 3e42cb145..cd2f52ead 100644
--- a/tests/test_compact_gate_438.py
+++ b/tests/test_compact_gate_438.py
@@ -59,40 +59,57 @@ def test_compact_boundary_accepts_wire_and_legacy_metadata(metadata, expected):
 
 
 def _capture_spawn(session: AgentSession):
     spawned = []
 
     def capture(coro):
         spawned.append(coro)
         coro.close()
 
     session._spawn_bg = capture
     session._cancel_precompact_timer = MagicMock()
     session._log = MagicMock()
     session._auto_compact = MagicMock()
     async def noop():
         return None
 
     session._auto_compact.side_effect = lambda **_kwargs: noop()
     return spawned
 
 
+
+@pytest.fixture(autouse=True)
+def auto_compact_window_always_open(monkeypatch):
+    """Окно автокомпакта пинуется на все сутки — иначе тест меряет ЧАСЫ, а не порог.
+
+    `_auto_compact_window_blocked` (`app/session.py:691`) для оркестратора спрашивает
+    `_auto_compact_window_state`, а тот считает окно от НАСТОЯЩИХ часов и
+    `AUTO_COMPACT_WINDOW_START/END`. Поэтому «оркестратор компактится на 96%» проходило
+    или падало в зависимости от времени суток: на CI совпадало с разрешённым окном,
+    локально — нет. Зелёный по совпадению хуже красного, он даёт ложную уверенность.
+    Здесь окно открыто всегда, и проверяется ровно ПОРОГ — обе его стороны.
+    """
+    monkeypatch.setenv("AUTO_COMPACT_ENABLED", "1")
+    monkeypatch.setenv("AUTO_COMPACT_WINDOW_START", "00:00")
+    monkeypatch.setenv("AUTO_COMPACT_WINDOW_END", "23:59")
+    monkeypatch.setenv("AUTO_COMPACT_TIMEZONE", "UTC")
+
 def test_orchestrator_compacts_at_96_but_not_94():
     session = _orchestrator()
     session._last_context = {"percentage": 96, "max_tokens": 1_000_000}
     spawned = _capture_spawn(session)
 
     TurnManager(session).schedule_context_compaction(96)
 
     assert len(spawned) == 1
     session._auto_compact.assert_called_once_with(delay_seconds=0)
 
     session._auto_compact.reset_mock()
     session._last_context["percentage"] = 94
     TurnManager(session).schedule_context_compaction(94)
 
     session._auto_compact.assert_not_called()
 
 
 def test_cli_threshold_lowers_our_threshold():
     session = _orchestrator()
     session._last_context = {
diff --git a/tests/test_fan_barrier_gates.py b/tests/test_fan_barrier_gates.py
index 8dc49b8ac..bab155116 100644
--- a/tests/test_fan_barrier_gates.py
+++ b/tests/test_fan_barrier_gates.py
@@ -29,50 +29,54 @@ def fanned(tmp_path, monkeypatch):
     return fb
 
 
 class _FakeSession:
     loaded = False
     worktree_path = None
 
     def __init__(self, name, sid="sid-parent"):
         self.id = sid
         self.name = name
         self.scope = "/repo"
         self.parent_name = "parent"
         self.last_task_sender = None
 
 
 class _SpyManager:
     """Считает пробуждения. Ровно то, за что платят $0.87 (#219) и
     $0.900241/$0.756113 (#223, независимая репликация)."""
     def __init__(self):
         self.sent = []
+        self.provenances = []
+        self.provenances = []
 
     async def ensure_loaded(self, name, scope=None):
         return _FakeSession(name)
 
     async def ensure_loaded_any(self, name):
         return _FakeSession(name)
 
     async def send(self, session_id, msg, *, provenance):
         assert provenance.senders
         self.sent.append((session_id, msg))
+        self.provenances.append(provenance)
+        self.provenances.append(provenance)
 
     def _context_warning(self, sender):
         return ""
 
 
 @pytest.fixture
 def spy(monkeypatch):
     m = _SpyManager()
     monkeypatch.setattr("app.routes.sessions.manager", m)
     return m
 
 
 def _send(sender, message="report", kind=None):
     from app.routes.sessions import send_message, SendRequest
     payload = {"message": message, "scope": "/repo", "sender": sender}
     if kind is not None:
         payload["message_kind"] = kind
     return asyncio.run(send_message("parent", SendRequest(**payload)))
 
 
@@ -164,46 +168,57 @@ def test_kill_path_produces_killed_token(fanned, monkeypatch):
     mgr.sessions = {"sid-c2": _FakeSession("c2", "sid-c2")}
 
     class _NoJobs:
         async def cancel_by_session(self, _sid):
             return None
 
     monkeypatch.setattr("app.bg_jobs.bg_manager", _NoJobs(), raising=False)
     monkeypatch.setattr("app.manager.archive_session", lambda _sid: None)
     asyncio.run(SessionManager.remove(mgr, "sid-c2"))
 
     m = fb.manifest("F")
     assert {x["child"]: x["state"] for x in m["members"]}["c2"] == "killed", (
         "реальный путь удаления не породил терминальный токен"
     )
     assert m["complete"] is True
 
 
 # --- AC-9: девять путей, которые барьер трогать НЕ ДОЛЖЕН ------------------
 
 def test_message_without_sender_is_never_buffered(fanned, spy):
-    """Internal caller без sender не получает человеческое происхождение."""
+    """Internal caller без sender не получает человеческое происхождение.
+
+    Проверяется ПРОИСХОЖДЕНИЕ, а не отказ. Отвергать безымянный вызов незачем — это
+    сломало бы локальную разработку без авторизации, где безымянный `curl` обычное дело;
+    достаточно не выдавать ему чужую личность. Дефект, который здесь сторожится:
+    `operator = not is_auth_enabled() or <валидная кука>` (`app/routes/sessions.py:929`)
+    делал человеком ЛЮБОГО безымянного вызывающего на контуре без `DASHBOARD_USER` —
+    штатном пути из README. «Мы не проверяем, кто пришёл» не равно «пришёл владелец».
+    """
     response = _send(None)
-    assert getattr(response, "status_code", None) == 403, (
-        "неаутентифицированный internal caller был принят за человека"
+    assert getattr(response, "status_code", None) != 403, response
+    assert spy.provenances, "доставка не дошла до менеджера — провенанс не с чего читать"
+    provenance = spy.provenances[-1]
+    assert provenance.origin == "unknown", (
+        f"неаутентифицированный internal caller был принят за человека: {provenance}"
     )
-    assert spy.sent == [], "неподтверждённый user origin доехал до доставки"
+    assert provenance.senders == ("unknown",), provenance
 
 
 def test_authenticated_operator_without_sender_still_delivers(fanned, spy, monkeypatch):
     from types import SimpleNamespace
     from app.routes.sessions import SendRequest, send_message
 
     monkeypatch.setattr("app.auth.validate_session", lambda _cookie: True)
     request = SimpleNamespace(headers={}, cookies={"session": "operator-cookie"})
     response = asyncio.run(send_message(
         "parent",
         SendRequest(message="human input", scope="/repo", sender=""),
         request=request,
     ))
     assert response.get("ok") is True
     assert len(spy.sent) == 1
     assert spy.sent[0][1].endswith("human input")
 
 
 def test_background_job_failure_reaches_a_buffered_child(fanned):
     """`bg_jobs` доставляет `[Background job FAILED]` САМОМУ ребёнку, а не
diff --git a/tests/test_fan_report_delivery.py b/tests/test_fan_report_delivery.py
index fef7c7a71..4e5f2d041 100644
--- a/tests/test_fan_report_delivery.py
+++ b/tests/test_fan_report_delivery.py
@@ -22,97 +22,129 @@ def db(tmp_path, monkeypatch):
     import app.db as _db
     _db.init_db()
     return _db
 
 
 class _FakeSession:
     loaded = False
     worktree_path = None
 
     def __init__(self, name, sid=None):
         self.id = sid or f"sid-{name}"
         self.name = name
         self.scope = "/repo"
         self.parent_name = "parent"
         self.last_task_sender = None
 
 
 class _SpyManager:
     def __init__(self):
         self.sent = []
+        self.provenances = []
 
     async def ensure_loaded(self, name, scope=None):
         return _FakeSession(name)
 
     async def ensure_loaded_any(self, name):
         return _FakeSession(name)
 
-    async def send(self, session_id, msg):
+    async def send(self, session_id, msg, *, provenance=None, **kwargs):
+        # `provenance` — обязательный параметр боевого `manager.send` (#433). Двойник
+        # без него ронял доставку уже ПОСЛЕ барьера: `send_message failed for parent:
+        # _SpyManager.send() got an unexpected keyword argument 'provenance'`.
         self.sent.append((session_id, msg))
+        self.provenances.append(provenance)
 
     def _context_warning(self, sender):
         return ""
 
 
 @pytest.fixture
-def spy(monkeypatch):
+def spy(monkeypatch, db):
     m = _SpyManager()
     monkeypatch.setattr("app.routes.sessions.manager", m)
     monkeypatch.setattr("app.deps.manager", m)
+    # Роут `send_message` при непустом `sender` требует ДОЛГОВЕЧНОЙ привязки сессии
+    # (`app/routes/sessions.py:969-971`) и иначе отвечает
+    # `409 {"error":"durable session binding is required"}`. Двойник сессии строки в БД
+    # не создаёт, поэтому оба теста файла падали ещё до барьера: пробуждений 0,
+    # `report_path` пустой. Гейт не обходим — создаём настоящие строки, как в проде.
+    import app.db as db_module
+    from datetime import datetime, timezone
+    for name in ("parent", "c1", "c2"):
+        db_module.save_session({
+            "id": f"sid-{name}", "name": name, "scope": "/repo", "cwd": "/tmp",
+            "model": "claude-sonnet-5[1m]", "system_prompt": "test", "status": "idle",
+            "session_id": None, "cost_usd": 0.0, "worktree_path": "/tmp",
+            "branch": "b", "is_orchestrator": False, "color": "#818cf8",
+            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
+            "parent_name": "" if name == "parent" else "parent",
+            # У получателя обязан быть `task_id`: сообщение С ОТПРАВИТЕЛЕМ безадресному
+            # агенту роут считает НАЗНАЧЕНИЕМ задачи и пускает только его родителя
+            # (`app/routes/sessions.py:972-976`, `403 only the durable parent may assign
+            # a task`). Родитель веера в проде ведёт свою задачу, поэтому это не обход
+            # гейта, а недостающая часть настоящего состояния.
+            "task_id": "275",
+        })
     return m
 
 
 def _open_fan(children):
     import app.fan_barrier as fb
     fb.open_fan(
         fan_id="F275",
         parent_name="parent",
         scope="/repo",
         children=list(children),
         deadline_seconds=3600,
     )
     return fb
 
 
 def _send(sender, message):
     from app.routes.sessions import SendRequest, send_message
     return asyncio.run(send_message("parent", SendRequest(
         message=message, scope="/repo", sender=sender, message_kind="done",
     )))
 
 
 class _SilentChild:
     is_orchestrator = False
     _did_report = False
     _manually_interrupted = False
     _pending_messages = False
     _compacting = False
     _last_turn_ok = True
     _last_stop_reason = "end_turn"
     _auto_report_task = None
     parent_name = "parent"
     last_task_sender = "parent"
 
     def __init__(self, name, turn_logs):
         self.name = name
         self.scope = "/repo"
         self._turn_logs = list(turn_logs)
+        # Молчаливый путь берёт текст ИМЕННО отсюда (`app/session_turns.py:277`,
+        # `final_text = getattr(s, "_last_text_output", None)`), а не из `_turn_logs`.
+        # Двойник, задававший только `_turn_logs`, оставлял `summary=None`, и манифест
+        # получался «ОТЧЁТА НЕТ» — то есть тест мерил собственную неполноту.
+        self._last_text_output = turn_logs[-1] if turn_logs else None
 
     async def on_idle(self, *a):
         return None
 
 
 def _silent(name, turn_logs):
     from app.session_turns import TurnManager
     child = _SilentChild(name, turn_logs)
 
     async def _go():
         TurnManager(child).fire_auto_report()
         if child._auto_report_task is not None:
             await child._auto_report_task
 
     asyncio.run(_go())
     return child
 
 
 def _member(fb, child):
     return next(m for m in fb.manifest("F275")["members"] if m["child"] == child)
diff --git a/tests/test_fd_adopt.py b/tests/test_fd_adopt.py
index 45429339d..07bfe50bd 100644
--- a/tests/test_fd_adopt.py
+++ b/tests/test_fd_adopt.py
@@ -474,41 +474,41 @@ async def test_impl_failed_handover_does_not_leave_quiescing_stuck_on():
             "a refused handover must not leave the backend in the quiescing state — "
             "its real death would then be silent")
 
         # and the proof that silence is what was at stake: with the flag clear, the reader's
         # finally still tells the truth
         late = asyncio.get_running_loop().create_future()
         backend._pending_requests[11] = late
         backend._reader_task = asyncio.create_task(backend._read_stdout())
         await asyncio.sleep(0.05)
         os.close(cli_out_w)  # the CLI dies for real -> EOF
         await asyncio.wait_for(backend._reader_task, timeout=5)
         assert late.done(), "a REAL death must complete pending requests, not stay silent"
     finally:
         for fd in (cli_out_w, cli_in_r):
             try:
                 os.close(fd)
             except OSError:
                 pass
 
 
-def test_t1_unknown_start_time_refuses_to_signal(monkeypatch, tmp_path):
+def test_t1_unknown_start_time_refuses_to_signal(monkeypatch, tmp_path, codex_bin_stub):
     """Заход 4, note 2: an unrecorded start time must NOT be re-measured at adopt time — that
     describes whoever holds the pid NOW. Unknown identity means refuse, and an orphan surviving
     beats killing a stranger."""
     from app import backend_jsonrpc
 
     numeric_kills = []
     pidfd_signals = []
     monkeypatch.setattr(
         backend_jsonrpc.os, "kill", lambda pid, sig: numeric_kills.append(pid)
     )
     monkeypatch.setattr(
         backend_jsonrpc.os, "pidfd_open", lambda pid, flags=0: 91_110,
         raising=False,
     )
     monkeypatch.setattr(
         backend_jsonrpc.signal,
         "pidfd_send_signal",
         lambda pidfd, sig, *args, **kwargs: pidfd_signals.append((pidfd, sig)),
         raising=False,
     )
@@ -523,41 +523,41 @@ def test_t1_unknown_start_time_refuses_to_signal(monkeypatch, tmp_path):
 
     def fake_open(path, *a, **kw):
         if str(path).endswith("/cmdline"):
             return real_open(tmp_path / "cmdline", *a, **kw)
         return real_open(path, *a, **kw)
 
     from app.backend_codex import CODEX_BIN
     codex_path = backend_jsonrpc._normalise_executable(CODEX_BIN)
     (tmp_path / "cmdline").write_bytes(
         b"node\0" + os.fsencode(codex_path) + b"\0app-server\0--stdio\0"
     )
     monkeypatch.setattr("builtins.open", fake_open)
 
     backend_jsonrpc.terminate_cli_process(4242, "Codex app-server", 0)
     assert numeric_kills == []
     assert pidfd_signals == [], (
         "with no recorded start time the identity is unproven — do not signal"
     )
 
 
-def test_t1_helper_uses_pidfd_and_refuses_a_reused_pid(monkeypatch, tmp_path):
+def test_t1_helper_uses_pidfd_and_refuses_a_reused_pid(monkeypatch, tmp_path, codex_bin_stub):
     """Round-2 finding: pid alone is not an identity. A reused number must not be signalled."""
     from app import backend_jsonrpc
 
     numeric_kills = []
     pidfd_signals = []
     closed_pidfds = []
     monkeypatch.setattr(
         backend_jsonrpc.os, "kill", lambda pid, sig: numeric_kills.append(pid)
     )
     monkeypatch.setattr(
         backend_jsonrpc.os, "pidfd_open", lambda pid, flags=0: 91_111,
         raising=False,
     )
     monkeypatch.setattr(
         backend_jsonrpc.signal,
         "pidfd_send_signal",
         lambda pidfd, sig, *args, **kwargs: pidfd_signals.append((pidfd, sig)),
         raising=False,
     )
     real_close = backend_jsonrpc.os.close
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index e3e426d3d..09629af46 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -1544,40 +1544,58 @@ def test_send_file_single_keeps_existing_rendering(
         );
     }""")
 
     card = page.locator('[data-tool-raw-name="mcp__orchestra__send_file"]')
     expect(card.locator(".flex.items-center")).to_have_text("✅ Sent to TG")
     expect(card.locator(".sf-file-list")).to_have_count(0)
     expect(card.locator("button").filter(has_text="Download")).to_have_count(1)
     expect(card.locator(".sf-actions")).to_have_count(0)
     page.close()
 
 
 def _open_tool_correlation_page(
     browser: Browser,
     compact_mode: bool,
     source_path: Path | None = None,
 ) -> Page:
     page = browser.new_page()
     _route_frontend_sources(page, source_path)
     _goto_dashboard(page)
     page.wait_for_function("() => typeof addChatEntry === 'function'")
+    # ОСТАНОВИТЬ опрос, а не ждать случайной тишины. Начальная загрузка дашборда идёт
+    # асинхронно и сама переписывает `#chat`: вкинутые раньше записи её `refreshAll`
+    # затирает уже после вставки, и тест видит пустой чат (`счётчик='🔔 0'`, карточек
+    # нет) — 3 падения из 6 прогонов подряд при 15 с в одиночку.
+    # Гасим тем же механизмом, что и прод: скрытая вкладка не опрашивает
+    # (`_pollCanRun`, `app/static/js/app.js`). Ожидание ПОСЛЕ этого гарантированно
+    # сходится. Прежняя версия ждала `!refreshInProgress && _pollInFlight.size === 0`
+    # без остановки опроса — на раннере это условие не наступало вовсе, ожидание
+    # выедало свой бюджет и роняло 11 тестов, которые до правки проходили.
+    page.evaluate("""() => {
+        Object.defineProperty(document, 'hidden', {configurable: true, value: true});
+        document.dispatchEvent(new Event('visibilitychange'));
+    }""")
+    page.wait_for_function(
+        """() => !_pollCanRun() && !refreshInProgress
+            && _pollTimers.size === 0 && _pollInFlight.size === 0""",
+        timeout=10000,
+    )
     page.evaluate("""compactMode => {
         selectedAgent = null;
         if (eventSource) {
             eventSource.close();
             eventSource = null;
         }
         window.compactMode = compactMode;
         document.querySelector('#chat').innerHTML = '';
     }""", compact_mode)
     return page
 
 
 @pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
 def test_parallel_tool_results_follow_tool_use_id_in_both_renderers(
     dashboard_browser: Browser,
     compact_mode: bool,
 ):
     source_override = os.environ.get("ORCHESTRA_TOOL_CORRELATION_SOURCE")
     source_path = Path(source_override) if source_override else None
     page = _open_tool_correlation_page(dashboard_browser, compact_mode, source_path)
@@ -1721,51 +1739,66 @@ def test_notify_user_call_is_highlighted_and_navigable_from_the_timeline(
     page.evaluate(
         """reason => {
         // Рядом идёт обычная пара вызов/результат: подсветка не должна её задеть.
         addChatEntry('tool', 'Bash: {"command":"echo NEIGHBOUR"}', null, null,
             {id:33001, tool_use_id:'toolu_neighbour'});
         addChatEntry('tool_result', 'NEIGHBOUR-RESULT', null, null,
             {id:33002, tool_use_id:'toolu_neighbour'});
         addChatEntry(
             'tool',
             `mcp__orchestra__notify_user: ${JSON.stringify({reason})}`,
             '2026-08-13T12:00:00+00:00',
             null,
             {id:33003, tool_use_id:'toolu_notify241'},
         );
     }""",
         reason,
     )
     # Свой потолок с диагнозом: без него пропажа зова из списка падает молчаливым
     # 30-секундным таймаутом и не говорит, ЧТО именно сломалось.
     try:
+        # Ждать надо ОБА признака. Счётчик в списке зовов и карточка в чате рисуются
+        # разными путями, поэтому «счётчик уже 🔔 1» НЕ означает «карточка в DOM».
+        # Под нагрузкой карточка отстаёт, `chat.querySelector(...)` отдаёт null, и
+        # следующий `getComputedStyle(card)` падает
+        # `TypeError: Failed to execute 'getComputedStyle' on 'Window': parameter 1 is
+        # not of type 'Element'` — то есть тест ронял сам себя гонкой, а не ловил дефект.
+        # В одиночку он проходил за 15.5 с и потому выглядел исправным.
         page.wait_for_function(
-            "() => document.querySelector('#chat-notify-count')?.textContent === '🔔 1'",
+            """() => document.querySelector('#chat-notify-count')?.textContent === '🔔 1'
+                && document.querySelector('#chat [data-tool-use-id="toolu_notify241"]')
+                && document.querySelector('#chat [data-tool-use-id="toolu_neighbour"]')
+                && document.querySelector('#chat-timeline-track .is-notify')""",
             timeout=5000,
         )
     except PlaywrightTimeout:
         actual = page.evaluate(
-            "() => [document.querySelector('#chat-notify-count')?.textContent,"
-            " document.querySelectorAll('#chat-timeline-track .is-notify').length]"
+            """() => [document.querySelector('#chat-notify-count')?.textContent,
+                document.querySelectorAll('#chat-timeline-track .is-notify').length,
+                !!document.querySelector('#chat [data-tool-use-id="toolu_notify241"]'),
+                !!document.querySelector('#chat [data-tool-use-id="toolu_neighbour"]')]"""
         )
         page.close()
-        pytest.fail(f"зов не попал в список: счётчик={actual[0]!r}, меток={actual[1]}")
+        pytest.fail(
+            f"зов не попал в список: счётчик={actual[0]!r}, меток={actual[1]}, "
+            f"карточка зова={actual[2]}, карточка соседа={actual[3]}"
+        )
 
     state = page.evaluate("""() => {
         const chat = document.querySelector('#chat');
         const card = chat.querySelector('[data-tool-use-id="toolu_notify241"]');
         const neighbour = chat.querySelector('[data-tool-use-id="toolu_neighbour"]');
         const marker = document.querySelector('#chat-timeline-track .is-notify');
         const nav = document.querySelector('#chat-notify-nav');
         const styles = getComputedStyle(card);
         return {
             cardHighlighted: card.classList.contains('chat-notify-user'),
             cardBorder: styles.borderLeftColor,
             cardText: card.innerText,
             navKind: card.dataset.chatNavKind,
             navLabel: card.dataset.chatNavLabel,
             markers: document.querySelectorAll('#chat-timeline-track .is-notify').length,
             markerTitle: marker?.title || '',
             navHidden: nav.classList.contains('hidden'),
             navDisabled: document.querySelector('#chat-notify-next').disabled,
             neighbourText: neighbour.innerText,
             neighbourHighlighted: neighbour.classList.contains('chat-notify-user'),
@@ -2535,136 +2568,124 @@ def test_dashboard_polling_resume_refreshes_status_after_hidden(
             "() => document.querySelector('[data-session-id=\"fe-orch-id\"]')?.innerText.includes('idle')",
             timeout=8000,
         )
         page.evaluate("""() => {
             Object.defineProperty(document, 'hidden', {configurable: true, value: true});
             document.dispatchEvent(new Event('visibilitychange'));
         }""")
         status["value"] = "running"
         page.evaluate("""() => {
             Object.defineProperty(document, 'hidden', {configurable: true, value: false});
             document.dispatchEvent(new Event('visibilitychange'));
         }""")
         page.wait_for_function(
             "() => document.querySelector('[data-session-id=\"fe-orch-id\"]')?.innerText.includes('running')",
             timeout=8000,
         )
     finally:
         page.close()
 
 
-def test_dashboard_polling_equivalent_twelve_minutes_before_after(
+def test_hidden_dashboard_stops_polling_and_resumes_when_visible(
     dashboard_browser: Browser,
-    tmp_path: Path,
 ):
-    """Use a 100x clock to compare a quiescent hidden window on main and this branch."""
-    branch_source = Path(__file__).parent.parent / "app/static/js/app.js"
-    main_source = tmp_path / "main-app.js"
-    main_source.write_text(
-        subprocess.check_output(
-            ["git", "show", "main:app/static/js/app.js"], text=True,
-        )
-    )
-    main_chat_source = subprocess.check_output(
-        ["git", "show", "main:app/static/js/chat.js"], text=True,
-    )
+    """Скрытая вкладка не опрашивает сервер, видимая опрашивает.
+
+    Прежняя версия (`test_dashboard_polling_equivalent_twelve_minutes_before_after`)
+    сравнивала ветку с `main` по числу запросов за 12 симулированных минут на 100-кратных
+    часах. Как замер она негодна (#197: `before_total` гулял 1456–2242 на НЕИЗМЕННОМ коде,
+    регрессия объявлялась 2 раза из 3), а как тест — неисполнима в CI: локально 29.50 с
+    при `--timeout=30`, на раннере выходила за бюджет, и pytest-timeout срабатывал посреди
+    живого Playwright, оставляя `chrome-headless-shell` и вешая шард целиком на 27+ минут.
+    Здесь от неё осталось ЗАЩИЩАЕМОЕ свойство без временнóго утверждения: механизм опроса
+    выключается при скрытой вкладке и включается обратно. Ожидания событийные
+    (`wait_for_function`), фиксированных пауз нет вовсе.
+    """
+    page = dashboard_browser.new_page()
+    counts: dict[str, int] = {}
+    polling_paths = {"/api/models", "/api/sessions", "/api/stats", "/api/orchestrators"}
+
+    def api_route(route):
+        path = route.request.url.split("?", 1)[0].split("/api", 1)[-1]
+        path = "/api" + path
+        if path in polling_paths:
+            counts[path] = counts.get(path, 0) + 1
+        if path.endswith("/stream"):
+            route.fulfill(status=200, content_type="text/event-stream", body="")
+            return
+        if path == "/api/orchestrators":
+            payload = [{"id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope"}]
+        elif path == "/api/sessions":
+            payload = [{"id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope",
+                        "status": "idle", "model": "claude-opus-5[1m]"}]
+        elif path == "/api/stats":
+            payload = {"active": 0, "total_sessions": 1, "total_cost_usd": 0}
+        elif path == "/api/models":
+            payload = {"models": [], "proxy_connected": False}
+        elif path.endswith("/logs"):
+            payload = []
+        else:
+            payload = []
+        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
 
-    def measure(source_path: Path) -> dict[str, int]:
-        page = dashboard_browser.new_page()
+    try:
         page.add_init_script("""
-            const realTimeout = window.setTimeout.bind(window);
-            const realInterval = window.setInterval.bind(window);
-            const scale = 0.01;
-            window.setTimeout = (fn, ms, ...args) => realTimeout(fn, Math.max(1, ms * scale), ...args);
-            window.setInterval = (fn, ms, ...args) => realInterval(fn, Math.max(1, ms * scale), ...args);
             window.EventSource = class StableEventSource {
                 constructor(url) { this.url = url; this.readyState = 1; }
                 close() { this.readyState = 2; }
             };
         """)
-        _route_frontend_sources(page, source_path)
-        if source_path == main_source:
-            page.route(
-                "**/static/js/chat.js*",
-                lambda route: route.fulfill(
-                    status=200,
-                    content_type="application/javascript",
-                    body=main_chat_source,
-                ),
-            )
-        counts: dict[str, int] = {}
-        polling_paths = {
-            "/api/models",
-            "/api/logs/sync",
-            "/api/sessions",
-            "/api/stats",
-            "/api/orchestrators",
-        }
-
-        def api_route(route):
-            path = route.request.url.split("?", 1)[0].split("/api", 1)[-1]
-            path = "/api" + path
-            if path in polling_paths or path.endswith("/context"):
-                counts[path] = counts.get(path, 0) + 1
-            if path.endswith("/stream"):
-                route.fulfill(status=200, content_type="text/event-stream", body="")
-                return
-            if path.endswith("/logs"):
-                payload = []
-            elif path == "/api/orchestrators":
-                payload = [{"id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope"}]
-            elif path == "/api/sessions":
-                payload = [{"id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope", "status": "idle", "model": "claude-opus-5[1m]"}]
-            elif path == "/api/stats":
-                payload = {"active": 0, "total_sessions": 1, "total_cost_usd": 0}
-            elif path == "/api/models":
-                payload = {"models": [], "proxy_connected": False}
-            elif path == "/api/logs/sync":
-                payload = {"logs": [], "max_log_id": 0, "live_sessions": []}
-            elif path.endswith("/context"):
-                payload = {"percentage": 0, "total_tokens": 0, "max_tokens": 1}
-            elif path == "/api/usage":
-                payload = {}
-            else:
-                payload = []
-            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
-
+        _route_frontend_sources(page)
         page.route(re.compile(r"/api/"), api_route)
         _goto_dashboard(page)
         page.wait_for_function("() => selectedAgent === 'fe-orch'", timeout=8000)
-        page.evaluate("() => { Object.defineProperty(document, 'hidden', {configurable: true, value: true}); document.dispatchEvent(new Event('visibilitychange')); }")
-        page.wait_for_function("""() => document.hidden && !_pollCanRun()
-            && !refreshInProgress && _pollTimers.size === 0 && _pollInFlight.size === 0
+
+        # Положительный контроль ДО скрытия: счётчик считает, опрос идёт. Без него
+        # «ноль запросов у скрытой вкладки» проходил бы и на мёртвой странице.
+        page.wait_for_function(
+            "() => _pollCanRun() && _pollTimers.size > 0", timeout=8000,
+        )
+        assert sum(counts.values()) > 0, counts
+
+        page.evaluate("""() => {
+            Object.defineProperty(document, 'hidden', {configurable: true, value: true});
+            document.dispatchEvent(new Event('visibilitychange'));
+        }""")
+        page.wait_for_function("""() => !_pollCanRun() && !refreshInProgress
+            && _pollTimers.size === 0 && _pollInFlight.size === 0
         """, timeout=8000)
+        assert page.evaluate("() => _pollCanRun()") is False
+        assert page.evaluate("() => _pollTimers.size") == 0
+        assert page.evaluate("() => _pollInFlight.size") == 0
+
         counts.clear()
-        page.wait_for_timeout(7200)
-        result = dict(counts)
+        page.evaluate("""() => {
+            Object.defineProperty(document, 'hidden', {configurable: true, value: false});
+            document.dispatchEvent(new Event('visibilitychange'));
+        }""")
+        # Опрос обязан ВЕРНУТЬСЯ — иначе проверка выше зелена на сломанной странице,
+        # где опрос не работает вообще. Ожидание событийное, а не по часам.
+        page.wait_for_function(
+            "() => _pollCanRun() && _pollTimers.size > 0", timeout=8000,
+        )
+    finally:
         page.close()
-        return result
-
-    before = measure(main_source)
-    after = measure(branch_source)
-    before_total = sum(before.values())
-    after_total = sum(after.values())
-    print(f"#301 equivalent 12m before_total={before_total} after_total={after_total} before={before} after={after}")
-    assert before_total == 0, before
-    assert after_total == 0, after
 
 
 def _open_notify_stream_page(
     browser: Browser,
     permission: str,
     history_rows: list[dict],
     stream_pages: list[list[dict]],
     history_status: int = 200,
     stable_sse: bool = False,
 ) -> tuple[Page, list[int]]:
     """Гоняем НАСТОЯЩИЙ путь: история → `_renderHistory` → `connectSSE` → onmessage.
 
     Прямой вызов `_maybeNotifyCall` читался бы как покрытие и им не был: мутация
     «убрать проводку в поток» осталась бы зелёной.
     """
     page = browser.new_page()
     if stable_sse:
         page.add_init_script("""
             window.EventSource = class StableEventSource {
                 constructor(url) { this.url = url; this.readyState = 1; }
diff --git a/tests/test_handoff_effect_classification.py b/tests/test_handoff_effect_classification.py
index cd8112795..5c9527362 100644
--- a/tests/test_handoff_effect_classification.py
+++ b/tests/test_handoff_effect_classification.py
@@ -220,56 +220,118 @@ async def test_prepare_refuses_a_call_that_may_still_be_running_and_names_it(
         ("text", "starting", None, None),


## Later history of the touched files on main (after this commit)

151 later commits touch these paths; the first 40 (oldest first):
55b4b737f 2026-09-07 Restrict model review to executors and preserve approved design experiments
13e9b2601 2026-09-07 #526, #527: research formal prompts, decoding costs and Orchestra control seams
067679f36 2026-09-07 #515, #432, #523, #520, #526: CI шардируется на 6 процессов — полный сьют в один процесс убивает OOM
5f8894ec9 2026-09-07 #532: enforce role and persistent worker tool exclusions at MCP dispatch
264daeb75 2026-09-07 Separate runtime control from model prose and preserve review results
ad5d17664 2026-09-07 Merge VPS main with laptop runtime-control fixes
036026b11 2026-09-07 #535: apply quota policy changes without restart
d55d3f6b5 2026-09-07 #534: WIP #534: preserve browser resource and pipe diagnostics
4fcc9d8a5 2026-09-07 Merge remote-tracking branch 'origin/main'
148d85437 2026-09-07 Isolate quota and browser fixtures across CI test order
25a7e6ed7 2026-09-07 Introduce advisory review and one pinned acceptance for new task assignments
bb115dcac 2026-09-07 Merge branch 'main' into codex/simplify-review
2d1f79126 2026-09-07 Merge completed VPS quota and browser fixes with isolated CI fixtures
8a3c8ad73 2026-09-07 Merge branch 'main' into codex/simplify-review
fe507ac6e 2026-09-08 Namespace VPS tasks and simplify runtime chat transfer and worker notes
4f87cecca 2026-09-08 #536: WIP #536: preserve writer conflict detection and regression coverage
715f0fc9f 2026-09-08 Merge remote-tracking branch 'origin/main' into codex/local-workflow
ae30028d3 2026-09-08 Remove unreachable cross-runtime canary pipeline and retired rule API
0eaae5904 2026-09-08 #537: persist CLI identity when publishing surviving pipes
f5713f4df 2026-09-08 Retire legacy review gates and fix adopted Codex writer release
98574f427 2026-09-08 Replace duplicate task stores with private Git and one versioned SQLite projection
59fe32bc4 2026-09-08 Merge remote-tracking branch 'origin/main' into codex/retire-legacy-review
fc0d5143d 2026-09-08 Merge current main into storage simplification
fa1b13558 2026-09-08 V-538: #V-538: preserve MCP proof across live config rebuilds
477484245 2026-09-08 Merge origin/main
5f7e72c50 2026-09-08 Add reusable idle watches and label dashboard message channel
d9ce293fa 2026-09-08 Integrate current main before storage cutover
9a1735f16 2026-09-09 Simplify agent knowledge and retire mandatory memory paperwork
3208ceeda 2026-09-09 Consolidate reusable lessons and remove historical checkout clutter
e6da7e30a 2026-09-10 #537: stop runtime trees with Orchestra and remove live adoption
bec4f3781 2026-09-11 merge gate: список путей берётся без детектора переименований (37с → 0.026с, чинит отказ merge_worker)
52f7c97d2 2026-09-11 тесты: гасить квотные env оператора до импорта и чинить снапшот маршрутов — гейт мержа блокировал чужие ветки
084a989ed 2026-09-11 V-546: жёсткий стоп квотного гейта стал свойством полосы (sol 95%, luna 99%)
4444697fd 2026-09-12 V-547: состояние квотного гейта видно на панели — состав полос в rule и индикатор
156683d4a 2026-09-12 V-556: add dashboard after-turn queue
b15940ba5 2026-09-12 V-562: preserve steered messages after failed turns
6a6c9e9bd 2026-09-13 V-564: render send_chart results in dashboard
0c3c0fcb0 2026-09-15 V-575: про ветку воркера при мерже спрашивают git, а не вторую запись платформы
d86cef6a1 2026-09-16 #V-578: кнопка временного снятия квотного гейта с автоистечением
a8d2e20ad 2026-09-17 V-582: #V-582: харнес-маршруты из живого каталога, допуск по данным провайдера

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 55b4b737f Restrict model review to executors and preserve approved design experiments

diff --git a/tests/test_codex_bin_resolution.py b/tests/test_codex_bin_resolution.py
index 27ca07eb4..a5df2258f 100644
--- a/tests/test_codex_bin_resolution.py
+++ b/tests/test_codex_bin_resolution.py
@@ -71,11 +71,11 @@ def test_missing_binary_gives_actionable_text_instead_of_exit_127(mcp, monkeypat
     monkeypatch.setattr(mcp, "SCOPE", "/home/kesha/orchestra")
 
     async def fake_api(method, path, **kwargs):
         assert method == "GET"
         assert path == "/api/sessions/perf"
-        return {"id": "test-session", "worktree_path": "/home/kesha/orchestra"}
+        return {"role": "worker", "id": "test-session", "worktree_path": "/home/kesha/orchestra"}
 
     monkeypatch.setattr(mcp, "_api", fake_api)
 
     out = asyncio.run(mcp.codex_review(
         context="PROJECT CONTEXT: test fixture", target="", output="CODEX_REVIEW.md",
@@ -91,11 +91,11 @@ def test_resolved_binary_reaches_the_shell_command(mcp, monkeypatch, tmp_path):
     """Позитивный случай: в команду уходит именно разрешённый путь, а не константа."""
     started = {}
 
     async def fake_api(method, path, **kwargs):
         if method == "GET":
-            return {"id": "test-session", "worktree_path": str(tmp_path)}
+            return {"role": "worker", "id": "test-session", "worktree_path": str(tmp_path)}
         assert method == "POST"
         assert path == "/api/bg/jobs"
         started["command"] = kwargs["json"]["config"]["command"]
         return {"id": "bg-test"}
 
diff --git a/tests/test_codex_review_sandbox.py b/tests/test_codex_review_sandbox.py
index bcb4d4625..369fdfe22 100644
--- a/tests/test_codex_review_sandbox.py
+++ b/tests/test_codex_review_sandbox.py
@@ -59,10 +59,11 @@ def _fake_api(tmp_path, captured):
                 "valid_until": 2_000_000_300, "alternatives": [],
                 "reason": "test",
             }
         if method == "GET":
             return {
+                "role": "worker",
                 "id": "sandbox-requester", "cwd": str(tmp_path),
                 "worktree_path": str(tmp_path),
             }
         captured.update(kwargs["json"])
         return {"id": "bg-test"}
diff --git a/tests/test_mcp_codex_review.py b/tests/test_mcp_codex_review.py
index 251b73505..5bd81aaad 100644
--- a/tests/test_mcp_codex_review.py
+++ b/tests/test_mcp_codex_review.py
@@ -56,22 +56,24 @@ def readiness_response():
     }
 
 
 @pytest.mark.asyncio
 @pytest.mark.parametrize("mode", ["exec", "review"])
+@pytest.mark.parametrize("role", ["worker", "full-cycle"])
 async def test_codex_review_uses_caller_context_and_declares_success_contract(
-    tmp_path, monkeypatch, mode,
+    tmp_path, monkeypatch, mode, role,
 ):
     import app.mcp_stdio as mcp
 
     captured = {}
 
     async def fake_api(method, path, **kwargs):
         if path == "/api/usage/readiness":
             return readiness_response()
         if method == "GET":
             return {
+                "role": role,
                 "cwd": str(tmp_path), "worktree_path": str(tmp_path),
                 "scope": str(tmp_path), "task_id": "215", "id": "requester-id",
             }
         captured.update(kwargs["json"])
         return {"id": "bg-test"}
@@ -145,10 +147,11 @@ async def test_codex_review_explicit_model_overrides_default_and_readiness(
         if path == "/api/usage/readiness":
             readiness_params.append(kwargs.get("params"))
             return readiness_response()
         if method == "GET":
             return {
+                "role": "worker",
                 "cwd": str(tmp_path), "worktree_path": str(tmp_path),
                 "scope": str(tmp_path), "task_id": "215", "id": "requester-id",
             }
         captured.update(kwargs["json"])
         return {"id": "bg-test"}
@@ -193,10 +196,11 @@ async def test_codex_review_resume_command_passes_usage_arguments(
     async def fake_api(method, path, **kwargs):
         if path == "/api/usage/readiness":
             return readiness_response()
         if method == "GET":
             return {
+                "role": "worker",
                 "cwd": str(tmp_path), "worktree_path": str(tmp_path),
                 "scope": str(tmp_path), "task_id": "215", "id": "requester-id",
             }
         captured.update(kwargs["json"])
         return {"id": "bg-test"}
@@ -331,10 +335,11 @@ printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":100,"cached_inpu
     async def api(method, path, **kwargs):
         if path == "/api/usage/readiness":
             return readiness_response()
         if method == "GET":
             return {
+                "role": "worker",
                 "id": Session.id, "cwd": str(tmp_path),
                 "worktree_path": str(tmp_path), "task_id": "215",
             }
         request = bg_route.BgJobCreateRequest(**kwargs["json"])
         created.update(kwargs["json"])
@@ -378,10 +383,11 @@ async def test_t1_385_codex_review_success_returns_exact_deferred_control_proven
     async def fake_api(method, path, **kwargs):
         if path == "/api/usage/readiness":
             return readiness_response()
         if method == "GET":
             return {
+                "role": "worker",
                 "cwd": str(tmp_path), "worktree_path": str(tmp_path),
                 "scope": str(tmp_path), "task_id": "385", "id": "requester-id",
             }
         return {"id": "bg-review-385"}
 
@@ -425,10 +431,11 @@ async def test_t1_385_codex_review_creation_failure_has_no_deferred_control(
     async def fake_api(method, path, **kwargs):
         if path == "/api/usage/readiness":
             return readiness_response()
         if method == "GET":
             return {
+                "role": "worker",
                 "cwd": str(tmp_path), "worktree_path": str(tmp_path),
                 "scope": str(tmp_path), "task_id": "385", "id": "requester-id",
             }
         return {"error": "job creation refused"}
 
diff --git a/tests/test_mcp_quota_gate.py b/tests/test_mcp_quota_gate.py
index 05c7efa11..2a103cbdb 100644
--- a/tests/test_mcp_quota_gate.py
+++ b/tests/test_mcp_quota_gate.py
@@ -67,10 +67,11 @@ def api(monkeypatch, tmp_path):
         if path == "/api/bg/jobs":
             return {"id": "bg-test"}
         if path.endswith("/change-model"):
             return {"changed": True, "old_model": "claude-opus-5[1m]", "model": "gpt-5.6-sol"}
         return {
+            "role": "worker",
             "id": "gate-requester", "cwd": str(tmp_path),
### 13e9b2601 #526, #527: research formal prompts, decoding costs and Orchestra control seams

diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index e3e426d3d..a38a07c59 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -2138,10 +2138,36 @@ def test_chat_transient_state_has_one_complete_reset_owner(
         "lastFinal": "",
         "thinking": True,
     }
 
 
+def test_user_message_stays_before_agent_entries_arriving_during_stream(
+    dashboard_browser: Browser,
+):
+    """#527: a user bubble must not be stranded below later stream records."""
+    page = _open_chat_snapshot_page(dashboard_browser)
+    page.wait_for_timeout(2000)
+    page.evaluate("""() => {
+        resetChatTransientState();
+        document.querySelector('#chat').replaceChildren();
+        addChatEntry('stream', 'AGENT-STREAMING');
+        pendingUserMsgs = ['USER-DURING-STREAM'];
+        showPendingBubble();
+    }""")
+    page.evaluate("""() => addChatEntry('status', 'AGENT-AFTER-USER')""")
+
+    order = page.evaluate("""() => [...document.querySelector('#chat').children].map(node => ({
+        kind: node.classList.contains('chat-user') ? 'user'
+            : node.classList.contains('streaming') ? 'stream' : 'agent',
+        text: node.textContent,
+    }))""")
+    assert [entry["kind"] for entry in order] == ["user", "agent", "stream"], order
+    assert order[0]["text"].startswith("USER-DURING-STREAM")
+    assert "AGENT-AFTER-USER" in order[1]["text"]
+    page.close()
+
+
 _NOTIFY_AGENT = "notify-268-probe"
 _NOTIFY_SESSION = "sess-268"
 _SILENT_TURN_MARKER = "[[ORCHESTRA:SILENT_TURN]]"
 
 
### 067679f36 #515, #432, #523, #520, #526: CI шардируется на 6 процессов — полный сьют в один процесс убивает OOM

diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index 9ce3edc9d..772d8f616 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1,19 +1,84 @@
 name: CI
 on:
   push:
-    branches: [main]
+    branches: [main, 'task-*/**']
   pull_request:
     branches: [main]
 
 jobs:
   test:
     runs-on: ubuntu-latest
+    # Зависший браузерный тест уже дважды держал шард 27+ минут: `--timeout=30` дампит
+    # стек, но не убивает процесс, пока живой `chrome-headless-shell` держит IPC. Потолок
+    # джоба — единственная гарантия, что зависание становится ПАДЕНИЕМ, а не бесконечным
+    # прогоном. 20 минут при самом долгом честном шарде 117 с — запас десятикратный.
+    timeout-minutes: 20
+    strategy:
+      # Нужен состав падений целиком, а не первый упавший шард.
+      fail-fast: false
+      matrix:
+        shard: [0, 1, 2, 3, 4, 5]
     steps:
+      # Часть тестов сравнивает рабочее дерево с `main` и ходит к родительским
+      # коммитам. По умолчанию checkout берёт ОДИН коммит ОДНОЙ ветки, и такой
+      # тест падает не по существу: `git show main:app/static/js/app.js` отвечает
+      # `exit 128`. `fetch-depth: 0` даёт полную историю и все ветки.
       - uses: actions/checkout@v4
+        with:
+          fetch-depth: 0
       - uses: astral-sh/setup-uv@v4
       - run: uv sync --dev
+      # На образе ubuntu-latest ffmpeg не предустановлен, а тест длительности
+      # аудио обязан звать НАСТОЯЩИЙ ffprobe — подменять бинарь значило бы
+      # проверять заглушку вместо разбора контейнера.
+      - run: sudo apt-get update && sudo apt-get install -y ffmpeg
       # `uv sync` ставит пакет playwright, но не бинарники браузеров. Без этого
       # шага все браузерные тесты молча скипались бы, и CI был бы зелёным, ничего
       # про фронт не проверив.
       - run: uv run playwright install --with-deps chromium
-      - run: uv run pytest -q --timeout=30
+      # Полный сьют в ОДИН процесс на этом репозитории не проходит физически:
+      # прогон 33893200040 убит `exit code 137` (OOM) на 81%, тот же RC=137
+      # около 80% воспроизводится локально. Течёт не отдельный тест, а
+      # накопление за прогон, поэтому лечится делением на процессы, а не
+      # правкой тестов. Раскладка — round-robin по отсортированному списку
+      # файлов: детерминирована, не требует отдельного манифеста и не устаревает
+      # при добавлении файла. Замер локальных шардов той же нарезки: пиковый RSS
+      # 218–263 МБ на шард против 16 ГБ у ubuntu-latest, запас ~60×;
+      # `/usr/bin/time -v` ниже печатает это число в каждый прогон, чтобы запас
+      # проверялся, а не помнился.
+      - name: pytest shard ${{ matrix.shard }} of 6
+        run: |
+          mapfile -t files < <(git ls-files 'tests/test_*.py' | sort \
+            | awk -v s='${{ matrix.shard }}' -v n=6 '(NR - 1) % n == s')
+          echo "shard ${{ matrix.shard }}/6: ${#files[@]} files"
+          test "${#files[@]}" -gt 0
+          # `-v` и небуферизованный вывод обязательны: при зависании `-q` не печатает
+          # НИЧЕГО (буфер не сбрасывается), и в логе остаётся только процент. С `-v`
+          # последняя строка называет тест, на котором встали.
+          # `-m "not browser"` — тот же набор, которым блокирует merge-гейт. Браузерные
+          # тесты гоняются отдельной джобой ниже: одно их зависание не должно съедать
+          # потолок шарда и прятать состав СОСЕДЕЙ по нему (07.09 так и вышло —
+          # `test_orchestra_layout_430` не успел отработать за `test_frontend.py`).
+          PYTHONUNBUFFERED=1 /usr/bin/time -v uv run pytest -v -rf --timeout=30 \
+            -m "not live_probe and not browser" "${files[@]}"
+
+  browser:
+    # Браузерные тесты сняты с БЛОКИРУЮЩЕГО набора (решение владельца 07.09: «выносим их
+    # из гейта, не убиваем»), поэтому джоба помечена `continue-on-error` — она остаётся
+    # СИГНАЛОМ, видимым в списке проверок, но не решает судьбу прогона. Гоняются те же
+    # 167 узлов, что снимает с себя merge-гейт: состав закреплён
+    # `tests/test_merge_test_gate.py::test_browser_inventory_is_explicit`.
+    runs-on: ubuntu-latest
+    continue-on-error: true
+    timeout-minutes: 20
+    steps:
+      - uses: actions/checkout@v4
+        with:
+          fetch-depth: 0
+      - uses: astral-sh/setup-uv@v4
+      - run: uv sync --dev
+      - run: uv run playwright install --with-deps chromium
+      - name: pytest browser
+        run: |
+          PYTHONUNBUFFERED=1 /usr/bin/time -v uv run pytest -v -rf --timeout=30 \
+            -m "browser" tests/
diff --git a/app/merge_test_gate.py b/app/merge_test_gate.py
index 762c9b914..4eb81bb63 100644
--- a/app/merge_test_gate.py
+++ b/app/merge_test_gate.py
@@ -215,10 +215,16 @@ def select_tests(changed: list[str], *, worktree: str) -> list[str]:
             selected.add(path)
     return sorted(selected)
 
 
 LIVE_PROBE_MARKER = "live_probe"
+# Браузерные тесты сняты с БЛОКИРУЮЩЕГО набора, но не удалены и не выключены: они гоняются
+# в CI отдельной джобой и вручную (`uv run pytest -m browser tests/`). Решение владельца
+# 07.09 «выносим их из гейта, не убиваем» на числах: 169 браузерных узлов из 4091, а два
+# мержа подряд встали с `TEST_GATE_INCONCLUSIVE` — бюджет кончался внутри `test_frontend.py`
+# при НУЛЕ красных тестов, то есть гейт блокировал чужую работу зависанием, а не находкой.
+BROWSER_MARKER = "browser"
 NO_TESTS_EXIT_CODE = 5  # pytest EXIT_NOTESTSCOLLECTED
 USAGE_ERROR_EXIT_CODE = 4  # pytest EXIT_USAGEERROR
 
 
 def pytest_argv(
@@ -249,11 +255,11 @@ def pytest_argv(
     ceiling = PER_TEST_TIMEOUT_SECONDS if per_test_timeout is None else per_test_timeout
     return [
         python, "-m", "pytest", "-q", "-vv",
         f"--timeout={ceiling:g}",
         f"--timeout-method={PER_TEST_TIMEOUT_METHOD}",
-        "-m", f"not {LIVE_PROBE_MARKER}",
+        "-m", f"not {LIVE_PROBE_MARKER} and not {BROWSER_MARKER}",
         *tests,
     ]
 
 
 # `tests/test_x.py::test_name[param] PASSED [ 12%]`.
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index b89007be0..3470480b5 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -925,16 +925,20 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
                 origin="agent", senders=(req.sender,), subtype="http_send",
             )
         else:
             from app.auth import is_auth_enabled, validate_session
 
+            # Человеком считается ТОЛЬКО предъявивший валидную куку. Прежнее
+            # `not is_auth_enabled() or ...` превращало любого безымянного вызывающего в
+            # человека на контуре без `DASHBOARD_USER` — а это штатный путь из README.
+            # Признак «мы не проверяем, кто пришёл» не равен признаку «пришёл владелец»;
+            # происхождение это утверждение об АВТОРСТВЕ, и на таком контуре оно было
+            # ложным. Вызов при этом не отвергается: ветка `origin="unknown"` ниже уже
+            # написана, доставка идёт, теряется только чужая личность.
             operator = bool(
-                not is_auth_enabled()
-                or (
-                    request is not None
-                    and validate_session(request.cookies.get("session", ""))
-                )
### 5f8894ec9 #532: enforce role and persistent worker tool exclusions at MCP dispatch

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 3470480b5..b5e4accd1 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -142,10 +142,11 @@ class CreateSessionRequest(BaseModel):
     base_branch: str = ""
     parent_name: str = ""
     mcp_servers: dict = {}
     pipeline: str = ""
     profile: str = ""
+    disabled_tools: list[str] = []
     owned_dirs: list[str] = []
     tg_topic: bool = False
     planned_initial_turn: bool = False
     initial_task_title: str = ""
     model_policy_override_reason: str = ""
@@ -284,10 +285,11 @@ async def create_session(req: CreateSessionRequest):
             task_id=req.task_id,
             description=req.description,
             base_branch=req.base_branch,
             parent_name=req.parent_name,
             mcp_servers=req.mcp_servers,
+            disabled_tools=req.disabled_tools,
             pipeline=req.pipeline,
             profile=req.profile,
             owned_dirs=req.owned_dirs,
             tg_topic=req.tg_topic,
             planned_initial_turn=req.planned_initial_turn,
diff --git a/app/session.py b/app/session.py
index 6ae55eb18..4937bb907 100644
--- a/app/session.py
+++ b/app/session.py
@@ -514,10 +514,11 @@ class AgentSession:
     pipeline: str = ""
     profile: str = ""
     _is_orchestrator: bool | None = field(default=None, repr=False)
     color: str = ""
     mcp_servers: dict = field(default_factory=dict, repr=False)
+    disabled_tools: list[str] = field(default_factory=list)
     mcp_servers_custom: dict = field(default_factory=dict, repr=False)
     on_error: Optional[callable] = field(default=None, repr=False)
     backend_type: str = "claude"
     effort: str | None = None
     runtime_handoff: str = ""
@@ -5368,10 +5369,11 @@ class AgentSession:
             "total_cache_read_tokens": self.total_cache_read_tokens,
             "total_cache_create_tokens": self.total_cache_create_tokens,
             "total_tool_calls": self.total_tool_calls,
             "template_hash": self._template_hash,
             "mcp_servers_custom": json.dumps(self.mcp_servers_custom) if self.mcp_servers_custom else "",
+            "disabled_tools": json.dumps(self.disabled_tools),
             "owned_dirs": json.dumps(self.owned_dirs) if self.owned_dirs else "",
             "tg_topic": int(self.tg_topic),
             "session_id_history": json.dumps(self.session_id_history) if self.session_id_history else "[]",
         }
 
@@ -5421,10 +5423,11 @@ class AgentSession:
             "runtime": self.backend_type,
             "provider": get_model_spec(self.model).provider,
             "hibernated": self._hibernated,
             "task_id": self.task_id,
             "description": self.description,
+            "disabled_tools": self.disabled_tools,
             "owned_dirs": self.owned_dirs,
             "tg_topic": self.tg_topic,
             "system_prompt": self.system_prompt[:500] if self.system_prompt else "",
             "total_turns": self.total_turns,
             "total_input_tokens": self.total_input_tokens,
### 264daeb75 Separate runtime control from model prose and preserve review results

diff --git a/app/session.py b/app/session.py
index 016225bb5..279372279 100644
--- a/app/session.py
+++ b/app/session.py
@@ -241,103 +241,10 @@ def _refuse_if_draining(session: "AgentSession") -> None:
             f"[{session.name}] Orchestra перезапускается: идёт дренаж, новый ход не "
             f"начинается. Повтори через минуту."
         )
 
 
-def _subscription_limit_kind(text: str) -> str | None:
-    """Classify the canonical non-transient subscription-limit messages."""
-    lowered = text.lower()
-    if "monthly spend limit" in lowered:
-        return "monthly"
-    if any(marker in lowered for marker in (
-        "session limit",
-        "hit your session",
-        "hit your usage limit",
-        "usage limit",
-        "subscription limit — ждём сброса квоты",
-        "weekly usage limit",
-        "weekly limit",
-    )):
-        return "timed"
-    return None
-
-
-def _is_terminal_subscription_limit(text: str) -> bool:
-    """Known non-transient subscription limits that must never enter server retry."""
-    return _subscription_limit_kind(text) is not None
-
-
-# Провайдер бракует ФОРМУЛИРОВКУ до модели, а наружу отдаёт тот же безликий
-# `invalid_request`, что и «плохой параметр» — по коду эти случаи неразличимы.
-# Fail-open: не совпало → ведём себя как раньше; ложно принять обычную ошибку за
-# фильтр хуже, чем не распознать фильтр.
-_SAFEGUARD_MARKER = "safeguards flagged this message"
-# Отказ печатает CLI, и он ВСЕГДА начинается с этого префикса, занимая всё событие целиком.
-# Одной фразы-маркера мало: агент, объясняющий инцидент, цитирует её в своём обычном ответе —
-# так и вышло 07.08 в 16:27:01, когда УСПЕШНЫЙ ход (`end_turn`) был принят за отказ и сессии
-# срезали историю. Признак берём из тела: чужая цитата стоит внутри текста, а не открывает его.
-_SAFEGUARD_PREFIX = "api error:"
-_REQUEST_ID_RE = re.compile(r"\breq_[A-Za-z0-9]+")
-
-
-def _is_safeguard_refusal(text: str) -> bool:
-    """Отказ фильтра провайдера на формулировку запроса (#155, ужесточён в #161)."""
-    lowered = text.lstrip().lower()
-    return lowered.startswith(_SAFEGUARD_PREFIX) and _SAFEGUARD_MARKER in lowered
-
-
-def safeguard_request_id(text: str) -> str:
-    """`Request ID` из отказа — единственное, что из него можно безопасно цитировать."""
-    match = _REQUEST_ID_RE.search(text)
-    return match.group(0) if match else ""
-
-
-def safeguard_guidance(request_id: str, dump_path: str) -> str:
-    """Что агенту делать дальше. Признаки проверяемые — агент применяет их к своему тексту.
-
-    ТЕЛА ЗАБРАКОВАННОГО ТЕКСТА ЗДЕСЬ НЕТ И БЫТЬ НЕ ДОЛЖНО. Объяснение едет в контекст
-    следующего хода, поэтому вклеенная цитата травит его заново: агент отвечает, цитируя
-    её, и следующий ход снова срезается. Замер #161 — ровно эта петля у seedon. Наружу
-    только класс отказа, три признака, `Request ID` и ссылка на форму; полный текст лежит
-    файлом, и путь к нему безопасен, а содержимое — нет.
-
-    Основание для признаков — два прошедших хода на формально той же теме (поиск утёкшего
-    секрета `git log -S` по всем ревизиям трёх СВОИХ репозиториев, чтение доки GitHub про
-    удаление чувствительных данных): тема «секреты и доступ» фильтр не роняет, роняет залог
-    и чужая собственность.
-    """
-    tail = f"Request ID: {request_id}\n" if request_id else ""
-    where = f"Полный текст отказа (в контекст не втягивать): {dump_path}\n" if dump_path else ""
-    return (
-        "🛡 Фильтр провайдера забраковал ФОРМУЛИРОВКУ запроса — до модели он не дошёл. "
-        "Смена Claude-модели не поможет: фильтр общий для семейства.\n"
-        "Переформулируй, проверив три признака по своему тексту:\n"
-        "1. система СВОЯ, а не чужая («наши репозитории», «наш сайт»);\n"
-        "2. глагол «убедиться / проверить», а не «получить доступ / обойти»;\n"
-        "3. в задании нет фразы, которая читается как инструкция к действию над защитой.\n"
-        "Не цитируй забракованную формулировку — цитата вернёт отказ.\n"
-        "Не помогло — смени рантайм на не-Anthropic.\n"
-        "Форма исключения: https://claude.com/form/cyber-use-case\n"
-        + tail + where
-    )
-
-
-def store_safeguard_refusal(session_name: str, text: str) -> str:
-    """Сложить сырой отказ ВНЕ рабочего дерева и вернуть путь.
-
-    Не в `.orchestra/tasks/`: auto-written storage must not share the Git working tree with
-    Git-lifecycle — так `report_bug` пачкал чекаут и блокировал все мержи (#114). Адрес тот же,
-    что у инбокса баг-репортов.
-    """
-    directory = Path.home() / ".local/state/orchestra/safeguard-refusals"
-    directory.mkdir(parents=True, exist_ok=True)
-    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
-    path = directory / f"{stamp}-{session_name}.txt"
-    path.write_text(text, encoding="utf-8")
-    return str(path)
-
-
 def _claude_subscription_limit_active() -> bool:
     try:
         from app.routes.system import _usage_cache
         usage = _usage_cache.get("data") or {}
     except Exception:
@@ -610,11 +517,10 @@ class AgentSession:
     _spawn_git_common_dir: str = field(default="", repr=False)
     _auto_continue_count: int = field(default=0, repr=False)
     _rate_limit_retries: int = field(default=0, repr=False)
     _server_error_retries: int = field(default=0, repr=False)
     _session_limit_hit: bool = field(default=False, repr=False)
-    _safeguard_refusal: str = field(default="", repr=False)
     _manually_interrupted: bool = field(default=False, repr=False)
     _precompact_timer_task: asyncio.Task | None = field(default=None, repr=False)
     _precompact_timer: dict | None = field(default=None, repr=False)
     # Одна строка в журнал на сессию: решение принимается каждый ход, а причина не меняется.
     _auto_compact_off_logged: bool = field(default=False, repr=False)
@@ -1311,10 +1217,11 @@ class AgentSession:
             # Recheck after admission too: Stop or a newer turn can win while
             # this sender is outside the lock waiting for quota data.
             if retry_generation is not None and (
                 retry_generation != (self._turn_gen, self._turn_start_cancel_gen)
                 or self._manually_interrupted
+                or (self._session_limit_hit and provenance.subtype in {"rate_limit_retry", "server_error_retry"})
                 or (self.status != AgentStatus.IDLE
                     and not (provenance.subtype in {"turn_limit_continue", "runtime_reconnect"}
                              and self.status == AgentStatus.RUNNING))
                 or self._compacting
             ):
@@ -1369,11 +1276,10 @@ class AgentSession:
             if provenance.subtype not in {"rate_limit_retry", "server_error_retry", "runtime_reconnect"}:
                 self._rate_limit_retries = 0
                 self._server_error_retries = 0
             if provenance.subtype != "server_error_retry":
                 self._session_limit_hit = False
-            self._safeguard_refusal = ""
 
             self._note_next_precompact_activity()
             capabilities = get_runtime(self.backend_type).capabilities
             if self._compacting:
                 if delivery is not None and allow_running_delivery:
@@ -2499,21 +2405,19 @@ class AgentSession:
                                      "content": event.content[:2000], "subagent_id": sub_id})
             return
         if event.type == "text":
### ad5d17664 Merge VPS main with laptop runtime-control fixes

diff --cc tests/test_codex_bin_resolution.py
index a5df2258f,63042b546..04e3edf18
--- a/tests/test_codex_bin_resolution.py
+++ b/tests/test_codex_bin_resolution.py
@@@ -61,21 -73,26 +73,26 @@@ def test_resolution_never_invents_a_pat
      import os
      got = mcp._codex_bin()
      assert got == "" or os.path.exists(got), f"разрешён несуществующий путь: {got!r}"
  
  
- def test_missing_binary_gives_actionable_text_instead_of_exit_127(mcp, monkeypatch):
+ def test_missing_binary_gives_actionable_text_instead_of_exit_127(mcp, monkeypatch, tmp_path):
      """Главное требование задачи: вместо `/bin/sh: ...: not found` (exit 127) — текст,
-     из которого видно, что чинить."""
+     из которого видно, что чинить.
+ 
+     Путь берётся из `tmp_path`, а не прибит к `/home/kesha/orchestra`: на раннере такого
+     каталога нет, и тест падал `fatal: cannot change to ...` — то есть проверял машину,
+     а не текст ошибки.
+     """
      monkeypatch.setattr(mcp.shutil, "which", lambda _: None)
      monkeypatch.setattr(mcp, "WORKER_NAME", "perf")
-     monkeypatch.setattr(mcp, "SCOPE", "/home/kesha/orchestra")
+     monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
  
      async def fake_api(method, path, **kwargs):
          assert method == "GET"
          assert path == "/api/sessions/perf"
-         return {"role": "worker", "id": "test-session", "worktree_path": "/home/kesha/orchestra"}
 -        return {"id": "test-session", "worktree_path": str(tmp_path)}
++        return {"role": "worker", "id": "test-session", "worktree_path": str(tmp_path)}
  
      monkeypatch.setattr(mcp, "_api", fake_api)
  
      out = asyncio.run(mcp.codex_review(
          context="PROJECT CONTEXT: test fixture", target="", output="CODEX_REVIEW.md",
diff --cc tests/test_codex_review_sandbox.py
index acec54c55,58851fb2a..951ca9ee9
--- a/tests/test_codex_review_sandbox.py
+++ b/tests/test_codex_review_sandbox.py
@@@ -112,12 -111,11 +112,12 @@@ def test_codex_review_disables_unusable
      assert "-s danger-full-access -a never exec" in command
      assert "workspace-write" not in command
      assert "--full-auto" not in command
  
  
- @pytest.mark.parametrize('outcome,rc', [('completed', 0), ('failed', 70), ('incomplete', 70)])
 -def test_codex_review_rejects_blind_verdict_from_successful_process(tmp_path, monkeypatch):
++@pytest.mark.parametrize('outcome,rc', [('completed', 0), ('russian', 0), ('failed', 70), ('incomplete', 70)])
 +def test_codex_review_uses_runtime_and_explicit_result(tmp_path, monkeypatch, outcome, rc):
      import app.mcp_stdio as mcp
  
      _prepare_usage_db(tmp_path, monkeypatch)
      fake_codex = tmp_path / "fake-codex"
      fake_codex.write_text("""#!/bin/sh
@@@ -133,16 -131,10 +133,18 @@@ printf '%s\\n' '## Summary' 'Unable to 
  printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"blind-thread\"}'
  printf '%s\\n' '{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":100,\"cached_input_tokens\":60,\"output_tokens\":20}}'
  printf '%s\\n' '{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"Unable to review: bwrap: setting up uid map: Permission denied\"}}'
  exit 0
  """)
 +    script = fake_codex.read_text()
 +    if outcome == 'failed':
 +        script = script.replace('"type":"turn.completed"', '"type":"turn.failed"')
++    if outcome == 'russian':
++        script = script.replace('## Verdict', '## Вердикт')
 +    if outcome == 'incomplete':
 +        script = script.replace("'PASS'", "'INCOMPLETE'")
 +    fake_codex.write_text(script)
      os.chmod(fake_codex, 0o755)
  
      captured = {}
      monkeypatch.setattr(mcp, "_api", _fake_api(tmp_path, captured))
      monkeypatch.setattr(mcp, "_codex_bin", lambda: str(fake_codex))
@@@ -156,30 -148,33 +158,32 @@@
      result = subprocess.run(
          ["dash", "-c", captured["config"]["command"]],
          capture_output=True, text=True,
      )
  
 -    assert result.returncode == 70
 -    assert "could not execute workspace commands" in result.stderr
 +    assert result.returncode == rc
      review = (tmp_path / "review.md").read_text()
      assert "Unable to review: bwrap: setting up uid map: Permission denied" in review
 -    assert "Execution guard failed" in review
 -
 -
 -def test_codex_review_failure_check_skips_scalar_jsonl_rows(tmp_path):
 -    import app.mcp_stdio as mcp
 -
 +    assert "Execution guard failed" not in review
 +    from app.db import review_receipt_get
 +    receipt = review_receipt_get(captured["receipt_id"])
-     assert receipt["status"] == ("completed" if outcome == "completed" else "failed")
++    assert receipt["status"] == ("completed" if outcome in {"completed", "russian"} else "failed")
 +    assert receipt["return_code"] == 0
 +    assert receipt["failure_code"] == {
-         "completed": "", "failed": "execution_guard", "incomplete": "review_result_missing",
++        "completed": "", "russian": "", "failed": "execution_guard", "incomplete": "review_result_missing",
 +    }[outcome]
 +    assert receipt["artifact_exists"] == 1
++    import re
++    assert re.search(captured["config"]["success_pattern"], review)
 +
 +
 +
 +def test_codex_review_failure_check_rejects_scalar_jsonl_rows(tmp_path):
 +    from app.codex_review_artifact import review_execution_error
      jsonl = tmp_path / "review.jsonl"
 -    jsonl.write_text(
 -        '[]\n'
 -        '{"type":"item.completed","item":{"type":"agent_message",'
 -        '"text":"Unable to review: bwrap: permission denied"}}\n'
 -    )
 -
 -    result = subprocess.run([
 -        mcp.sys.executable, "-c", mcp._CODEX_EXECUTION_FAILURE_JSONL_CHECK,
 -        str(jsonl), mcp._CODEX_EXECUTION_FAILURE_PATTERN,
 -    ], capture_output=True, text=True)
 -
 -    assert result.returncode == 0
 +    jsonl.write_text('[]\n')
 +    assert review_execution_error(jsonl) == "invalid runtime event"
  
  
  def test_codex_review_ignores_failure_marker_in_command_output(tmp_path, monkeypatch):
      import app.mcp_stdio as mcp
  
diff --cc tests/test_merge_test_gate.py
index 189f2cba4,6bb8efa73..e29743665
--- a/tests/test_merge_test_gate.py
+++ b/tests/test_merge_test_gate.py
@@@ -632,10 -642,54 +642,54 @@@ def test_live_probe_inventory_is_explic
          "инвентарь живых проб разошёлся с заявленным; добавляешь пробу — впиши её сюда "
          f"и в докстринг её файла. Найдено: {found}"
      )
  
  
+ def test_browser_inventory_is_explicit():
+     """Состав снятого с гейта ВИДЕН и проверяем, а не спрятан в неявном исключении.
+ 
+     Браузерные тесты не блокируют merge-гейт (`-m "not live_probe and not browser"`), но
+     продолжают гоняться. Значит их состав обязан быть заявленным: маркер ставится
+     автоматически по факту запроса браузерной фикстуры (`tests/conftest.py`), и если он
+     начнёт цеплять лишнее или потеряет файл — тест краснеет и заставляет объяснить.
+     Проверяется РАСКЛАДКА ПО ФАЙЛАМ, а не список имён: имена тестов меняются свободно,
+     а вот «браузерных узлов стало вдвое больше» или «целый файл ушёл из-под гейта» —
### 036026b11 #535: apply quota policy changes without restart

diff --git a/tests/conftest.py b/tests/conftest.py
index e61a630ac..26c2322c2 100644
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -149,12 +149,21 @@ def _hermetic_dashboard_env(monkeypatch):
     окружения, хуже красного — он не воспроизводится.
 
     Нужен включённый auth внутри теста — выставь переменные своим ``monkeypatch.setenv``.
     """
     import dotenv
+    import app.quota_gate as quota_gate
 
     monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
+    # Keep ordinary tests independent from an operator's checkout-level `.env`;
+    # tests that exercise live loading replace this path explicitly.
+    monkeypatch.setattr(
+        quota_gate,
+        "_DOTENV_PATH",
+        quota_gate.Path(__file__).with_name(".missing-quota-dotenv"),
+    )
+    quota_gate._dotenv_loaded = False
     for key in (
         "DASHBOARD_USER",
         "DASHBOARD_PASSWORD",
         "OWNER_MODE",
         "ARTIFACT_PUBLIC_LINKS_ENABLED",
@@ -163,10 +172,16 @@ def _hermetic_dashboard_env(monkeypatch):
         "ARTIFACT_DEFAULT_TTL_SECONDS",
         "ARTIFACT_MAX_TTL_SECONDS",
         "ARTIFACT_MAX_BYTES",
         "STATE_DIRECTORY",
         "XDG_STATE_HOME",
+        "QUOTA_HARD_STOP_PCT",
+        "QUOTA_TOLERANCE_START_PP",
+        "QUOTA_TOLERANCE_END_PP",
+        "QUOTA_CURVE_EXPONENT",
+        "QUOTA_GATED_LANES",
+        "QUOTA_CURVED_LANES",
     ):
         monkeypatch.delenv(key, raising=False)
 
 
 @pytest.fixture(autouse=True)
### d55d3f6b5 #534: WIP #534: preserve browser resource and pipe diagnostics

diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 3d96ddf7e..a763b4cda 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -9,10 +9,11 @@ import base64
 import json
 import os
 import re
 import socket
 import subprocess
+import tempfile
 import sys
 import time
 import urllib.error
 import urllib.request
 from urllib.parse import quote
@@ -135,11 +136,12 @@ def _free_port() -> int:
 
 def _dashboard_output_tail(proc: subprocess.Popen) -> str:
     if proc.stdout is None:
         return "<stdout unavailable>"
     try:
-        os.set_blocking(proc.stdout.fileno(), False)
+        proc.stdout.seek(0, os.SEEK_END)
+        proc.stdout.seek(max(0, proc.stdout.tell() - 4000))
         output = proc.stdout.read() or b""
     except (BlockingIOError, OSError, ValueError) as exc:
         return f"<stdout unreadable: {type(exc).__name__}: {exc}>"
     return output.decode("utf-8", "replace")[-4000:] or "<empty>"
 
@@ -185,21 +187,28 @@ def _start_dashboard_server(db_path: Path) -> tuple[subprocess.Popen, str]:
     env["DASHBOARD_PASSWORD"] = ""
     env["OWNER_MODE"] = ""
     env["SSH_TUNNELS"] = ""
     port = _free_port()
     root = Path(__file__).resolve().parent.parent
-    proc = subprocess.Popen(
-        [
-            sys.executable, "-m", "uvicorn", "app.main:app",
-            "--host", "127.0.0.1", "--port", str(port),
-            "--log-level", "warning",
-        ],
-        cwd=str(root),
-        env=env,
-        stdout=subprocess.PIPE,
-        stderr=subprocess.STDOUT,
-    )
+    # A pipe fills across tests and blocks the server event loop on logging.
+    output = tempfile.TemporaryFile(dir=db_path.parent)
+    try:
+        proc = subprocess.Popen(
+            [
+                sys.executable, "-m", "uvicorn", "app.main:app",
+                "--host", "127.0.0.1", "--port", str(port),
+                "--log-level", "warning",
+            ],
+            cwd=str(root),
+            env=env,
+            stdout=output,
+            stderr=subprocess.STDOUT,
+        )
+    except BaseException:
+        output.close()
+        raise
+    proc.stdout = output
     origin = f"http://127.0.0.1:{port}"
     started = time.monotonic()
     deadline = started + _DASHBOARD_START_TIMEOUT_S
     last = "no attempt"
     while time.monotonic() < deadline:
diff --git a/tests/test_merge_test_gate.py b/tests/test_merge_test_gate.py
index 6bb8efa73..2d1d8c346 100644
--- a/tests/test_merge_test_gate.py
+++ b/tests/test_merge_test_gate.py
@@ -658,11 +658,13 @@ def test_browser_inventory_is_explicit():
     import subprocess
     import sys
 
     root = Path(__file__).resolve().parent.parent
     expected = {
-    "tests/test_frontend.py": 104,
+    # Collection includes the voice-input test explicitly skipped since #365;
+    # 104 passing tests plus that retained node make 105, regardless of execution.
+    "tests/test_frontend.py": 105,
     "tests/test_t344_quota_lines_browser.py": 17,
     "tests/test_usage_analytics_frontend.py": 14,
     "tests/test_usage_history_frontend.py": 11,
     "tests/test_grok_usage_frontend.py": 11,
     "tests/test_antigravity_usage_frontend.py": 6,