# Context for item-41

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/manager.py b/app/manager.py
index 1af5e76d6..c1887da6b 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -1425,43 +1425,96 @@ class SessionManager:
             parent = worker_session.parent_name if worker_session else None
             orch = parent or self._find_orchestrator_name(scope)
             if not orch:
                 return
             orch_session = next((s for s in self.sessions.values() if s.name == orch), None)
             if not orch_session:
                 return
             summary = "\n".join(last_texts[-3:]) if last_texts else "(no output)"
             ctx = self._context_warning(worker_name)
             sr = f" (stop_reason={stop_reason})" if stop_reason else ""
             outcome = (
                 "Finished without explicit report"
                 if turn_ok
                 else "Turn failed before an explicit report"
             )
             msg = (
                 f"[from:{worker_name}] [auto-report]{sr} {outcome}. "
                 f"Last output:\n{summary}{ctx}"
             )
             logger.info(f"Auto-report: {worker_name} → {orch}")
-            await self.send(orch_session.id, msg)
+            try:
+                await self.send(orch_session.id, msg)
+            except Exception as error:
+                await self._record_undelivered_auto_report(
+                    worker_name, worker_scope or scope, worker_session,
+                    orch_session, error,
+                )
         return _on_worker_idle
 
+    async def _record_undelivered_auto_report(
+        self, worker_name: str, worker_scope: str, worker_session,
+        orch_session, error: Exception,
+    ) -> None:
+        """Автоотчёт не дошёл — оставить след, не зависящий от сломанного канала (#47).
+
+        Автоотчёт существует ровно для того, чтобы ждущий оркестратор не остался без
+        сигнала. Поэтому запись идёт в историю ОБЕИХ сессий: в дашборде видно и со стороны
+        воркера («я отчитался, но не дошло»), и со стороны того, кто ждёт.
+
+        Попытка уведомить оркестратора отдельным сообщением делается, но её исход попадает
+        в ту же запись: тихая попытка была бы тем же дефектом, который мы чиним.
+        Повтора нет — по решению #30 ретраи не вводим.
+        """
+        from app.db import add_log
+        from app.notify import report_undelivered
+
+        detail = f"{type(error).__name__}: {error}"
+        attempt = await report_undelivered(
+            self,
+            scope=worker_scope,
+            worker=worker_name,
+            what="автоотчёт",
+            reason=detail,
+        )
+        # Причина не дублируется: в исходе попытки она чаще всего та же самая, и запись
+        # раздувается вдвое ровно там, где её будет читать человек.
+        if detail in attempt:
+            attempt = attempt.replace(detail, "та же причина")
+        text = (
+            f"[доставка] автоотчёт воркера «{worker_name}» не доставлен "
+            f"оркестратору «{orch_session.name}»: {detail}. "
+            f"Попытка уведомить отдельным сообщением: {attempt}. "
+            f"Автоматического повтора нет — воркер ждёт продолжения."
+        )
+        logger.warning(text)
+        now = datetime.now(timezone.utc)
+        # Сессия воркера может быть уже выгружена — тогда пишем только тому, кто ждёт.
+        for session in (s for s in (worker_session, orch_session) if s is not None):
+            try:
+                await asyncio.to_thread(add_log, session.id, now, "system", text)
+            except Exception as log_error:
+                logger.warning(
+                    "could not record undelivered auto-report for %s: %s: %s",
+                    session.name, type(log_error).__name__, log_error,
+                )
+
     # ── Listings ──
 
     def list_sessions(self, scope: str | None = None) -> list[dict]:
         from app.db import get_last_turn_map
         result = []
         seen = set()
         for s in self.sessions.values():
             if scope is None or s.scope == scope:
                 result.append(s.to_dict())
                 seen.add(s.id)
         for row in get_all_sessions(scope):
             if row["id"] not in seen:
                 result.append(row)
         # Cache-timer metadata is runtime-derived; Codex exposes only an approximate window.
         turn_map = get_last_turn_map()
         for r in result:
             r["last_turn_ts"] = turn_map.get(r["id"])
             r.update(cache_policy_for_runtime(runtime_for_record(r)))
         return result
 
diff --git a/docs/tasks/47/record-in-dashboard.png b/docs/tasks/47/record-in-dashboard.png
new file mode 100644
index 000000000..822f1ee7c
Binary files /dev/null and b/docs/tasks/47/record-in-dashboard.png differ
diff --git a/docs/tasks/47/report.md b/docs/tasks/47/report.md
new file mode 100644
index 000000000..f41a43006
--- /dev/null
+++ b/docs/tasks/47/report.md
@@ -0,0 +1,100 @@
+# #47 — отчёт: у недоставленного автоотчёта появился след, не зависящий от сломанного канала
+
+## Как это выглядит
+
+Запись (тип `system`, в истории ОБЕИХ сессий — воркера и оркестратора):
+
+```
+[доставка] автоотчёт воркера «worker» не доставлен оркестратору «boss»: RuntimeError:
+auto-switch failed: branch 'adhoc-1785700000-1/boss' already exists (HEAD ac25033a,
+last commit 2026-08-04T06:43:09+02:00) — refusing to adopt someone else's history;
+a fresh branch was expected. Попытка уведомить отдельным сообщением: уведомить boss
+не удалось: та же причина. Автоматического повтора нет — воркер ждёт продолжения.
+```
+
+Причина не дублируется: в исходе попытки она чаще всего та же самая, и без сжатия запись
+раздувалась вдвое ровно там, где её читает человек.
+
+## Глазами в дашборде — и одно наблюдение, которого я не ждал
+
+`docs/tasks/47/screenshot-record.py` — живой :8888, `app.js` из ветки, ответ
+`/api/logs/sync` из копии живой БД плюс синтетическая строка. Скриншот:
+`docs/tasks/47/record-in-dashboard.png`.
+
+Строка в чате есть и читается целиком (проверено не глазами, а счётчиком: 24 узла
+содержат её текст). **Но выглядит она как обычный ответ агента** — тот же светлый блок, без
+иконки и без цвета, в отличие от соседних `tool`/`Bash`, у которых есть заголовок и рамка.
+Человек, листающий чат, отличит её только по тексту `[доставка]`.
+
+Тип `system` не имеет отдельной ветки в `addChatEntry` (`app/static/js/app.js:3393`) и
+падает в общий путь текста. Это касается и записи из #30. Фронтенд — не моя территория,
+поэтому НЕ трогал: если решишь, что предупреждение о недоставке должно выделяться, это
+задача фронтенду (там уже есть готовые ветки `warning` и `status` с оформлением).
+
+## Что сделано
+
+`app/manager.py`: `_on_worker_idle` больше не отпускает исключение доставки в вызывающий
+`_do_report` — при отказе зовётся `_record_undelivered_auto_report()`, который
+1. **A (дешёвая попытка)** — `report_undelivered` из #30: причина недоставки бывает
+   временной, тогда уведомление дойдёт;
+2. **B (основа)** — пишет запись в историю воркера И оркестратора; исход попытки A входит
+   в текст записи, иначе попытка была бы тем же тихим дефектом, который мы чиним;
+3. повтора нет — по решению #30.
+
+Сессия воркера может быть уже выгружена — тогда запись уходит только тому, кто ждёт.
+
+| файл | ± |
+|---|---|
+| `app/manager.py` | +45 |
+| `tests/test_auto_report_undelivered.py` | +130 (новый) |
+| `docs/tasks/47/screenshot-record.py` | +80 (новый) |
+
+## Проверки
+
+```
+tests/test_auto_report_undelivered.py                     4 passed  (3 прогона подряд)
+tests/test_manager.py + test_undelivered.py + test_limit_wake.py   166 passed
+```
+
+Мутация — откатом файла через `git show HEAD^:app/manager.py > app/manager.py`
+(`git checkout` не набирал вовсе, помню вчерашнее):
+```
+3 failed, 1 passed
+```
+Красными стали ровно те три, что проверяют запись и однократность попытки; четвёртый
+(«удачная доставка следа не оставляет») зелёный по обе стороны — он и должен быть таким.
+
+Живой сценарий, а не юнит: настоящий репозиторий, у ОРКЕСТРАТОРА занято имя будущей ветки,
+воркер уходит в idle и отчитывается — то есть отказ рождается там же, где родился бы в бою.
+
+## Ответ на твой вопрос про сценарий «оркестратор не проснётся вообще»
+
+Такой сценарий **есть, и он ровно этот**. Запись типа `system` в истории сессии попадает
+в дашборд, но **не попадает в контекст агента**: `get_logs` читается в `session.py:1519`
+только для `_build_runtime_handoff`, и там берутся исключительно строки типов
+`user_message` и `text` — `system` отфильтровывается. То есть ждущий оркестратор
+из этой записи НЕ узнает ничего; узнает человек в дашборде.
+
+Значит из твоей логики выбора B верна вторая половина (запись переживает сломанный канал),
+а первая — «на своём следующем ходу он её прочитает» — не подтверждается кодом. Реально до
+ждущего оркестратора доходит только успешная попытка A. Если A не прошла и человек в
+дашборд не смотрит — оркестратор продолжает ждать.
+
+**Не чиню, как договаривались.** Если решишь закрывать — это или C (TG-зеркало, другой
+канал, дёргает человека), или доставка записи в контекст оркестратора при следующей
+успешной доставке (очередь недоставленного). Второе выглядит дешевле и точнее, но это уже
+не «минимальный объём», а новая механика с собственными краями.
+
+## Вердикта Codex нет
+
+Codex недоступен до 08.08. Самокритика:
+
+1. **Проверен один класс причины** — принимающая сторона не может принять. Если `send()`
+   падает по причине на стороне отправителя, запись всё равно появится, но текст попытки A
+   будет другим; этот случай я не прогонял.
+2. **Скриншот снят на синтетической строке**, вставленной в ответ `/api/logs/sync`, а не на
+   строке, реально дописанной в живую БД: писать в живую БД ради картинки я не стал.
+   Форма записи в обоих случаях одна и та же (одна и та же строка), но путь до дашборда
+   проверен подменённым ответом, а не полным циклом.
+3. **Двойная запись** (в обе истории) при массовой недоставке даст двойной шум. Считаю
+   приемлемым, потому что недоставка редка по построению, но замера частоты у меня нет.
diff --git a/docs/tasks/47/research.md b/docs/tasks/47/research.md
new file mode 100644
index 000000000..050349f98
--- /dev/null
+++ b/docs/tasks/47/research.md
@@ -0,0 +1,96 @@
+# #47 — исследование: недоставленный автоотчёт и почему предложенный минимальный фикс не сработает
+
+## Вопрос
+
+- **Контекст**: автоотчёт существует ровно для того, чтобы молчаливый воркер не оставил
+  оркестратора ждать сигнала, который никогда не придёт (`session_turns.py:174`, докстринг).
+  При недоставке автоотчёта ломается именно это.
+- **Проверяемое утверждение** (объём, предложенный оркестратором): достаточно позвать
+  `report_undelivered` из #30 в существующем `except` — адресат известен.
+- **Измеримый исход**: узнает ли кто-нибудь ЖИВОЙ о недоставке после такой правки.
+
+## Гипотеза и её фальсификатор
+
+**H1 — `report_undelivered` здесь работает так же, как в #30.**
+*Фальсификатор*: адресат уведомления совпадает с адресатом упавшего сообщения, и канал тот же —
+тогда уведомление уйдёт по уже сломанному пути.
+**Итог: H1 ОПРОВЕРГНУТА замером.**
+
+## Замер (живой стенд: настоящий репозиторий, оркестратор, которому не доставить)
+
+```
+A1 автоотчёт: RuntimeError: auto-switch failed: branch 'adhoc-1785700000-1/boss' already
+   exists (HEAD 8fd18d5c…, last commit 2026-08-04T06:38:18+02:00) — refusing to adopt…
+A1 в журнале: ['Auto-report: worker → boss']
+
+A2 report_undelivered вернул: уведомить boss не удалось: RuntimeError: auto-switch failed:
+   branch 'adhoc-1785700000-1/boss' already exists (…)
+A2 в журнале: ['undelivered автоотчёт for worker: уведомить boss не удалось: RuntimeError…']
+```
+
+**Что это значит.** Адресат автоотчёта — родитель воркера (`manager.py:1425`:
+`orch = parent or self._find_orchestrator_name(scope)`). Адресат уведомления в
+`report_undelivered` — оркестратор того же scope, то есть **тот же самый агент**. Канал —
+тот же `manager.send()`. Поэтому в основном сценарии недоставки (принимающая сторона не может
+принять) уведомление падает ровно так же, и результат правки — вторая строка в журнале
+вместо первой. Живой человек по-прежнему не узнаёт ничего.
+
+Рекурсии при этом нет: `notify.report_undelivered` ловит своё исключение и возвращает исход
+строкой, второго уведомления не порождает (`A2` это подтверждает — ровно одна запись).
+
+## Что известно про сам путь
+
+- `fire_auto_report` (`session_turns.py:168`) запускает `_do_report()`, внутри —
+  `except Exception: logger.error("Auto-report failed for …")` (`:201`). Исключение
+  наружу не всплывает, задача имеет владельца (`s._auto_report_task`) — «бесследной тишины»
+  нет, но и адресата у факта тоже нет.
+- `_did_report` (`session.py:974`) ставится, только когда воркер сам позвал `send_message`.
+  Недоставка автоотчёта на него не влияет — ложного «уже отчитался» не возникает.
+  Это единственное, что в этом механизме сегодня работает как надо.
+
+## Варианты для плана (решение — оркестратора)
+
+| вариант | зависит от сломанного канала | кто узнает |
+|---|---|---|
+| A. позвать `report_undelivered` (предложенный минимум) | **да** | никто, если причина в самом адресате |
+| B. запись в историю ОБЕИХ сессий (`add_log`, как в #30 T1) | нет | человек в дашборде; переживает рестарт |
+| C. зеркало в TG-топик оркестратора (`_mirror_*` — другой канал) | нет | человек в Telegram |
+| D. ретрай | — | отвергнуто политикой #30 |
+
+Моя рекомендация: **B как основа + A как дешёвая попытка** (причина недоставки бывает и
+временной, тогда уведомление дойдёт), C — если оркестратор захочет, чтобы человека дёргали
+в Telegram. D не делаем.
+
+## Затронутые файлы
+
+| файл | что там |
+|---|---|
+| `app/session_turns.py:191-204` | `_do_report` и его `except` — единственная точка правки |
+| `app/notify.py` | `report_undelivered` — переиспользуется как есть |
+| `app/db.py` `add_log` | запись факта в историю сессии |
+| `app/manager.py:1425-1445` | вывод адресата, менять не нужно |
+
+## Риски и края
+
+1. **Запись в историю оркестратора** появится в его чате в дашборде — это ровно то место,
+   где человек ищет входящие отчёты, но формально это строка не от агента, а от платформы;
+   тип `system` для этого и существует (в #30 уже так сделано).
+2. **Двойная запись** (в историю воркера и оркестратора) удваивает шум при массовой недоставке.
+   Считаю приемлемым: недоставка редка по построению.
+3. Правка лежит в общем рантайме на пути завершения хода; ревью Codex недоступно до 08.08.
+
+## Чего я НЕ проверял
+
+- Прогонял ОДИН класс причины (принимающая сторона не может принять). Если `send()` падает
+  по причине на стороне отправителя, картина может отличаться — не мерил.
+- Не проверял поведение при недоступном TG-зеркале (вариант C) — если его выберем, это
+  надо мерить отдельно.
+- Не смотрел, как недоставленный автоотчёт выглядит в дашборде сегодня (есть ли там хоть
+  какой-то признак) — смотрел только код и журнал.
+
+## Вердикта Codex нет
+
+Codex недоступен до 08.08. Самокритика: вывод «уведомление уйдёт по сломанному пути»
+доказан для случая, когда принимать не может сам адресат. Это самый вероятный случай, но
+не единственный, и полностью бесполезным вариант A назвать нельзя — поэтому и предлагаю
+его как дешёвую добавку, а не как замену.
diff --git a/docs/tasks/47/screenshot-record.py b/docs/tasks/47/screenshot-record.py
new file mode 100644
index 000000000..1aa9a8a2d
--- /dev/null
+++ b/docs/tasks/47/screenshot-record.py
@@ -0,0 +1,81 @@
+"""#47 — посмотреть ГЛАЗАМИ, как запись о недоставке выглядит в дашборде.
+
+Живой :8888, app.js подменяется версией из ветки, ответ /api/logs/sync берётся из копии
+живой БД и дополняется одной синтетической строкой типа `system` — той самой, которую
+пишет `_record_undelivered_auto_report`. Скриншот кладётся рядом.
+
+Запуск: uv run python docs/tasks/47/screenshot-record.py
+"""
+import asyncio, json, pathlib, subprocess, sys
+
+from playwright.async_api import async_playwright
+
+ROOT = pathlib.Path(__file__).resolve().parents[3]
+APP_JS = ROOT / "app/static/js/app.js"
+DB_COPY = pathlib.Path("/tmp/live_copy.db")
+OUT = pathlib.Path(__file__).resolve().parent / "record-in-dashboard.png"
+BASE = "http://127.0.0.1:8888"
+
+ENV = {}
+for line in open("/home/kesha/orchestra/.env"):
+    if "=" in line and not line.strip().startswith("#"):
+        k, v = line.split("=", 1)
+        ENV[k.strip()] = v.strip()
+
+if not DB_COPY.exists():
+    subprocess.run(["sqlite3", "/home/kesha/orchestra/data/orchestra.db",
+                    f".backup {DB_COPY}"], check=True)
+sys.path.insert(0, str(ROOT))
+import app.db as _db                                     # noqa: E402
+_db.DB_PATH = DB_COPY
+from app.db import get_logs_sync                         # noqa: E402
+
+RECORD = (
+    "[доставка] автоотчёт воркера «worker» не доставлен оркестратору «boss»: "
+    "RuntimeError: auto-switch failed: branch 'adhoc-1785700000-1/boss' already exists "
+    "(HEAD ac25033a, last commit 2026-08-04T06:43:09+02:00) — refusing to adopt someone "
+    "else's history; a fresh branch was expected. Попытка уведомить отдельным сообщением: "
+    "уведомить boss не удалось: та же причина. Автоматического повтора нет — воркер ждёт "
+    "продолжения."
+)
+
+
+async def main():
+    data = get_logs_sync(after_id=0, tail=20, cap=16384)
+    target = data["logs"][-1]["session_id"]
+    agent = next((s for s in data["live_sessions"] if s["id"] == target), None)
+    data["logs"].append({
+        "id": data["max_log_id"] + 1, "session_id": target,
+        "ts": "2026-08-04T06:43:09+00:00", "type": "system", "content": RECORD,
+    })
+    data["max_log_id"] += 1
+
+    async with async_playwright() as p:
+        br = await p.chromium.launch(args=["--no-sandbox"])
+        ctx = await br.new_context(
+            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"},
+            viewport={"width": 1400, "height": 900})
+        page = await ctx.new_page()
+        await page.route("**/static/js/app.js*",
+                         lambda r: r.fulfill(status=200, content_type="text/javascript",
+                                             body=APP_JS.read_text()))
+        await page.route("**/api/logs/sync*",
+                         lambda r: r.fulfill(status=200, content_type="application/json",
+                                             body=json.dumps(data, ensure_ascii=False)))
+        await page.goto(BASE, wait_until="load")
+        await page.wait_for_function("typeof _showChatFor === 'function'")
+        await page.wait_for_timeout(4000)
+        if agent:
+            await page.evaluate("(a) => selectAgent(a.name)", agent)
+        await page.wait_for_timeout(2500)
+        found = await page.evaluate(
+            "() => [...document.querySelectorAll('#chat *')]"
+            ".filter(e => e.textContent.includes('[доставка] автоотчёт')).length")
+        print(f"  строка найдена в чате: {found > 0} (узлов с ней: {found})")
+        await page.locator("#chat").screenshot(path=str(OUT))
+        print(f"  скриншот: {OUT}")
+        await br.close()
+    return 0 if found else 1
+
+
+sys.exit(asyncio.run(main()))
diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index bfda7462b..4b25a7a32 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -127,26 +127,34 @@ squash не создаёт коммита, и `git log -1 main` показыва
 
 `def f(limit=LOCK_WAIT_LIMIT_SECONDS)` вычисляется при определении функции — `monkeypatch.setattr(mod, "LOCK_WAIT_LIMIT_SECONDS", 0.3)` молча не действует, и тест уходит в реальные 25 с
 или проходит не тем путём. Константу, которую собираются подменять, читать В ТЕЛЕ
 (`limit = CONST if limit is None else limit`). Поймал в #27 только потому, что тест проверял
 ПОВЕДЕНИЕ (пришёл ли 409), а не факт вызова.
 
 ## `git checkout -- <файл>` при грязном дереве стирает СВОЮ работу
 
 Откатывал мутацию — стёр незакоммиченные правки в том же файле (#30, `manager.py`:
 импорт и две замены). Правило знал, но применил его к слову «мутация», а не к слову
 «checkout». Формулировка, которая срабатывает раньше: **пока в дереве есть незакоммиченное,
 `git checkout -- <файл>` не набирать вообще**; для отката файла — только
 `git show <commit>:<файл> > <файл>`, а вернуть — тем же способом из своего коммита.
 
 ## Файл тестов внезапно висит минутами → гоняй с `--timeout=30`
 
 `tests/test_api.py` перестал укладываться в 8 минут: чужой стаб разошёлся с сигнатурой
 (`backfill_scope(session_name=...)` из #28), и тест ждал вечно. Без `--timeout` это
 выглядит как «мои правки всё сломали». Сначала timeout, потом паника.
 
+## Запись в `logs` видит ДАШБОРД, а не агент
+
+`add_log(..., type="system")` не попадает в контекст агента: `get_logs` читается
+(`session.py:1519`) только для `_build_runtime_handoff`, и там берутся ТОЛЬКО типы
+`user_message` и `text`. Поэтому «оставим строку в его истории, на следующем ходу прочитает» —
+неверно: прочитает человек в дашборде. До самого агента доходит только доставленное
+сообщение. Проверять это перед тем, как обещать «агент узнает».
+
 ## Живая БД для замеров объёмов
 
 `sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro", uri=True)` — читать
 можно свободно, сервер не мешает. Перцентили длины `logs.content` объясняют больше, чем
 средние: у нас p50=222 Б при max=651 КБ, и 16 сообщений держат 67 % объёма таблицы.
 Любой бюджет на историю считать **в байтах**, не в числе сообщений.
diff --git a/tests/test_auto_report_undelivered.py b/tests/test_auto_report_undelivered.py
new file mode 100644
index 000000000..26f42e3c9
--- /dev/null
+++ b/tests/test_auto_report_undelivered.py
@@ -0,0 +1,145 @@
+"""#47 — недоставленный автоотчёт оставляет след, не зависящий от сломанного канала.
+
+Стенд живой: настоящий репозиторий, настоящий отказ авто-switch у ОРКЕСТРАТОРА (то есть
+принять он не может), воркер уходит в idle и отчитывается.
+"""
+import logging
+import subprocess
+import uuid
+from datetime import datetime, timezone
+from unittest.mock import patch
+
+import pytest
+
+
+@pytest.fixture
+def env(tmp_path, monkeypatch):
+    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
+    wt_root = tmp_path / "worktrees"
+    wt_root.mkdir()
+    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
+    from app.db import init_db, save_session
+
+    init_db()
+    repo = tmp_path / "repo"
+    repo.mkdir()
+    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
+    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True)
+    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
+    (repo / "README.md").write_text("# test")
+    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
+    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
+    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)
+
+    from app.workspace import create_worktree
+
+    def row(sid, name, worktree, branch, *, orch=False, needs_switch=0, parent=""):
+        return {
+            "id": sid, "name": name, "scope": str(repo), "cwd": str(repo),
+            "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
+            "session_id": None, "cost_usd": 0.0, "worktree_path": worktree,
+            "branch": branch, "base_branch": "main", "is_orchestrator": orch, "color": "",
+            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
+            "task_id": "", "needs_switch": needs_switch, "parent_name": parent,
+        }
+
+    boss_wt = create_worktree(str(repo), "boss", "47", base_branch="main")
+    stolen = "adhoc-1785700000-1/boss"
+    subprocess.run(["git", "branch", stolen, "main"], cwd=repo, capture_output=True, check=True)
+    save_session(row("boss-1", "boss", boss_wt.path, boss_wt.branch, orch=True, needs_switch=1))
+
+    worker_wt = create_worktree(str(repo), "worker", "48", base_branch="main")
+    worker_id = str(uuid.uuid4())
+    save_session(row(worker_id, "worker", worker_wt.path, worker_wt.branch, parent="boss"))
+
+    import app.manager as mgr
+
+    monkeypatch.setattr(mgr, "next_adhoc_branch", lambda _n: stolen)
+    return {"repo": str(repo), "worker_id": worker_id, "boss_id": "boss-1"}
+
+
+async def _report(env):
+    from app.main import manager
+
+    manager.sessions.clear()
+    await manager.ensure_loaded_any("boss")
+    await manager.ensure_loaded_any("worker")
+    callback = manager._make_idle_callback(env["repo"])
+    await callback("worker", env["repo"], ["последний вывод воркера"], "", True)
+    return manager
+
+
+def _delivery_rows(session_id):
+    from app.db import get_logs
+
+    return [r for r in get_logs(session_id, limit=50)
+            if "[доставка]" in (r["content"] or "")]
+
+
+@pytest.mark.asyncio
+async def test_both_histories_get_the_record_and_no_exception_escapes(env, caplog):
+    from tests.conftest import make_backend_mock
+
+    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
+        with caplog.at_level(logging.WARNING):
+            await _report(env)  # исключение наружу не всплывает — иначе тест упадёт здесь
+
+    worker_rows = _delivery_rows(env["worker_id"])
+    boss_rows = _delivery_rows(env["boss_id"])
+    print("\nВ ИСТОРИИ ОРКЕСТРАТОРА:\n   ", boss_rows[0]["content"] if boss_rows else "НЕТ")
+    assert worker_rows and boss_rows, "след обязан быть в обеих историях"
+    assert worker_rows[0]["content"] == boss_rows[0]["content"]
+    assert worker_rows[0]["type"] == "system"
+
+
+@pytest.mark.asyncio
+async def test_record_names_both_sides_reason_and_outcome_of_the_attempt(env):
+    from tests.conftest import make_backend_mock
+
+    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
+        await _report(env)
+
+    text = _delivery_rows(env["boss_id"])[0]["content"]
+    assert "автоотчёт воркера «worker»" in text and "«boss»" in text
+    # исход попытки уведомить обязан быть виден: тихая попытка — тот же дефект
+    assert "Попытка уведомить отдельным сообщением:" in text
+    assert "уведомить boss не удалось" in text
+    assert "Автоматического повтора нет" in text
+    assert "RuntimeError" in text
+
+
+@pytest.mark.asyncio
+async def test_successful_auto_report_leaves_no_record(env, monkeypatch):
+    from tests.conftest import make_backend_mock
+
+    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
+        from app.main import manager
+
+        manager.sessions.clear()
+        await manager.ensure_loaded_any("boss")
+        await manager.ensure_loaded_any("worker")
+
+        async def ok(*_a, **_k):
+            return None
+
+        monkeypatch.setattr(manager, "send", ok)
+        callback = manager._make_idle_callback(env["repo"])
+        await callback("worker", env["repo"], ["вывод"], "", True)
+
+    assert not _delivery_rows(env["boss_id"]), "удачная доставка не должна оставлять след"
+
+
+@pytest.mark.asyncio
+async def test_attempt_does_not_recurse(env, caplog):
+    """Уведомление о недоставке не порождает уведомления о недоставке уведомления."""
+    from tests.conftest import make_backend_mock
+
+    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
+        with caplog.at_level(logging.WARNING):
+            await _report(env)
+
+    attempts = [r.getMessage() for r in caplog.records
+                if "undelivered автоотчёт" in r.getMessage()]
+    print("\nПОПЫТОК УВЕДОМИТЬ:", len(attempts))
+    assert len(attempts) == 1, f"ожидалась одна попытка, было {len(attempts)}"
+    assert len(_delivery_rows(env["boss_id"])) == 1


## Later history of the touched files on main (after this commit)

90 later commits touch these paths; the first 40 (oldest first):
6c677554d 2026-08-04 #47: #47: чистка личной памяти — сгруппировано по поводу обращения, дубли слиты
180f78bd4 2026-08-04 #54: #54: sessions.id не может быть пустым — схема, триггер, гард в коде, громкий ноль строк, 400 в bg_create
0d3975b02 2026-08-04 #56: #56: исследование — репорт пишется в стор и на этом всё; адресат вычислим, семь старых разобраны
10d1a858b 2026-08-04 #61: #61: исследование — конфликт только когда база доработала те же строки; критерий из git недоступен
ef9c8057b 2026-08-04 #62: #62: фаза 1 — рабочие копии сносит pytest в главном чекауте, воспроизведено
750d0d0b2 2026-08-04 #50: #50: исследование — точка врезки в send() измерена, очередь обязана быть durable
7a6f0ab75 2026-08-04 #69: #69: репозиторий воркера от git, слаг от repo root; strategy=parent через границу репо
84d58f6a0 2026-08-04 #52: #52: исследование — N-1 конфликт по построению, правило не выполняется 0 из 8, материал уже есть в отчётах
6c279201d 2026-08-04 #65: #65: system_prompt и last_summary убраны из списка сессий — 54.3 → 4.5 КБ по проводу
262b38b5b 2026-08-04 #71: #71: исследование — 92.8% провода даёт одно поле, второй вызов от нулевого дросселя
6f97d535a 2026-08-04 #78, #80: #78: исследование — оценка подтверждена своим замером, но retention логов не существует, а копировать надо не файл
9f777f912 2026-08-04 Squashed commits: - #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте - #82: план — env чинится пересборкой, сохранённые ссылки предпочитают id, 4 тикета - #82: T1 — bg-джобы будят по неизменяемому id, а не по имени - WIP #82: T2 наполовину — в session.py есть флаг _identity_stale и его гашение на границе хода; НЕ сделано: manager.refresh_identity (пересборка mcp_servers) и вызов из rename_session, весь T3, T4 - #82: T2 — переименование пересобирает MCP-идентичность, перезапуск на границе хода - #82: T3 — держатель тест-лока по неизменяемому id, дети переименованного родителя - #82: T4 — живой прогон переименования, отчёт и личная память
991b246c7 2026-08-06 #137: #137: разбор Prime Agent — заявка 30.2→95.5 разложена по первоисточникам, механика по коду, что применимо к Orchestra
beb777cb4 2026-08-06 Squashed commits: - #160: исследование — graceful shutdown затирает 'running', пробуждение не срабатывает - #160: сохранить признак прерванности через graceful-рестарт - #160: тесты пробуждения после рестарта, отчёт, личная память
36de7dd94 2026-08-06 #167: #167: ошибка обязана назвать себя — один владелец вместо четырёх копий
647452c1c 2026-08-08 #168: #168: research centralized weekly quota gate
afc99e2de 2026-08-10 #173: #173: fix prompt P0 defects
05e9a8062 2026-08-11 #174: #174: import DB history into Claude
6b2249c59 2026-08-12 #214: #214: эффорт по модели — карта модель→ступень в манифесте
6dac7dcbf 2026-08-12 #220: #220: план фазы 2 — T1 пересборка промпта, T2/T3 дренаж, красные тесты тикетов
9b1b48b54 2026-08-12 #219: #219 T1b: красные тесты проводки — два гейта, killed-токен, девять неприкосновенных путей
d986be3c1 2026-08-12 #193: #193: add red subrepo memory regression test
9fc4534e5 2026-08-12 #231: #231: предрегистрация эксперимента (стенд, критерий, все четыре исхода) — ДО спавна плеч
a01a4b2aa 2026-08-13 #230: #230: план фазы 2 + красные оракулы T1-T5 (заглушки, 8 failed)
7cb9b324e 2026-08-13 #230: #230: три находки независимой проверки — гейт на futures, оракул по leftover, start_time до сброса
5c346ffd5 2026-08-13 #227: #227: enforce worker model policy at spawn
59ee1b11c 2026-08-13 #227: #227: gate Opus by Claude weekly pace
d485e1c52 2026-08-13 #258: #258: research safe orphan process identity
017ca19c0 2026-08-13 #237: #237: research seamless active-turn restart
01f4794e2 2026-08-14 #200: #200: one CLI path encoder in app.manager.enc_cli_dir
077a795c7 2026-08-14 #281: #281: bind orchestrator HTTP privilege to a per-MCP proof
3cfeb617a 2026-08-16 #297: #297: suppress silent marker auto-report
1e020d60e 2026-08-17 #311: #311: freeze durable delivery RED oracles
9a1e2d108 2026-08-17 #314: #314: freeze enforcement and analytics RED oracles
b604ef449 2026-08-17 #305: #305: serialize managed Codex cold starts
3c037bdb8 2026-08-18 #290: cross-runtime handoff + канареечный скип по продовому предикату (scratch/290, вердикт #328)
1fe3cf1d7 2026-08-18 #329: один владелец логики пулов — квотная арифметика вырезана из манифеста, блок выключен до рестарта
b643c67e3 2026-08-19 #230: горячее применение правок и живучесть ходов при рестарте
0707d9257 2026-08-19 #343: одно правило допуска по квоте, прежние квотные системы вырезаны
dc09cc236 2026-08-22 Squashed commits: - #366: research + plan + 22 red tests (model catalog, two-level availability) - #366: plan review section + behavioral red reasons (no external reviewer: quota) - #366: T1 — kv_set/kv_delete writers + two-level availability flags (overlay, read-through kv) - #366: T2 — OpenRouter catalog fetch/normalize/kv-cache + registration re-applied inside every registry rebuild - #366: T3 — two-level enforcement: /api/models dashboard filter, agents gate in _create_session_locked, change-model via=dashboard|mcp, bounded unknown-model error; CONTRACT CHANGE: derived views are now a superset of SELECTABLE_MODEL_SPECS (test_derived_views_carry_exactly_the_declared_specs rewritten as subset assertions) - WIP #366: T4 catalog HTTP API written (GET/POST/PATCH /api/models/catalog*), tests not yet run; TODO: run test_catalog_api.py, mutation, T5 frontend+Playwright probe, T6 - #366: T4 — /api/models/catalog GET(union registry+cache)/refresh POST/flags PATCH; dropped counter surfaced; mutation: PATCH-echo-without-persist caught - #366: T5 — catalog modal screen: search/free/tools/image filters, two toggles per model, refresh button; picker untouched - #366: T5 — live Playwright probe evidence (probe-catalog.png): worktree js/css substituted on :8888, catalog modal renders 18 models / 36 toggles, search filters, clone-frozen screenshot - #366: T6 — live-agent shoulders: resume surface intact after both flags off, new spawn rejected with actionable message, switch-away allowed; mutation: message without screen name caught - #366: report + personal memory - #366: изоляция тестов — снимок и восстановление реестра моделей между тестами; kv-чтение флагов/кеша fail-soft при отсутствии таблицы - #366: route surface snapshot — +/api/models/catalog{,/refresh,/flags} (intentional new public endpoints)

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 6c677554d #47: #47: чистка личной памяти — сгруппировано по поводу обращения, дубли слиты

diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index 4b25a7a32..ae88d97ea 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -1,160 +1,81 @@
 # feat-instant — личная память
 
-## Замеры фронта через Playwright на живом :8888
-
-- **Авторизация только заголовком.** `new_context(extra_http_headers={"Authorization":
-  f"Bearer {INTERNAL_TOKEN}"})` — работает и для документа, и для `fetch()` изнутри страницы.
-  Логин формой (`/login`, поля `username`/`password`) в Playwright у меня не прилипал:
-  страница грузилась, а любой `/api/*` из неё отвечал 401. Не тратить на это ходы.
-- **Не звать `await response.body()` на SSE.** У `/api/sessions/*/stream` тело не кончается
-  никогда — `page.on("response")` + `body()` вешает скрипт намертво (у меня job висел 4 минуты
-  и умер по таймауту). Фильтровать по `content-type: text/event-stream` до чтения тела.
-- **Байты SSE на проводе** считать сырым TLS-сокетом с `settimeout(1.5)`: пауза в приёме =
-  бурст истории кончился. `curl` тут не годится, он не завершится сам.
-  Для чистого числа брать **простаивающего** агента — у `running` в счёт попадают живые события.
-- Правки JS в своей ветке живой :8888 НЕ видит (статика отдаётся из основного чекаута) —
-  подменять через `page.route('**/static/js/app.js*', ...)`, шаблон только со звёздочкой
-  (см. ниже). Это же записано в docs/tasks/2/report.md.
-
-## Асинхронный фронт: один зелёный прогон ничего не значит
-
-Прогоняй проверку 3-4 раза подряд. В #8 два дефекта вылезли только на повторе:
-- фоновый `refreshSessions` раз в 3 с содержит `if (!eventSource) connectSSE()` — пока своя
-  асинхронная загрузка держит `eventSource = null`, опрос успевает открыть ВТОРОЙ поток с
-  `after_id=0`. Первый прогон 12/12, следующий — 3 красных;
-- проверка, сверявшая значение с моей же подделкой, краснела от гонки с тем же опросом.
-  Проверять надо ПОВЕДЕНИЕ (переоткрылся ли поток), а не подставленное значение.
-
-## `tool_result` не создаёт своего узла в чате
-
-Он вливается в строку инструмента выше, а `data-chat-log-id` там принадлежит другой строке
-(`Math.max` по всем слитым id). Любая пометка «на узел сообщения» для `tool_result` молча
-не сработает: в #8 получилось 1 пометка на 6 строк, и это выглядело как «почти работает».
-Прежде чем вешать что-то на узел — проверь замером, что узел вообще существует.
-
-## Настоящие клиентские цифры — из журнала, а не из своего браузера
-
-Доступа к машине юзера нет, но его поведение полностью видно с сервера:
-- `journalctl -u orchestra -o short-precise` — тайминги старта по строкам лога; разница
-  между соседними строками показывает, какой шаг `lifespan` съел время;
-- `/var/log/nginx/access.log` — что и когда запрашивал ЕГО браузер, включая коды и паузы.
-  Тишина в access.log при открытой странице = его клиент перестал слать запросы.
-В #15 это дало «клиент не замечает возврат сервера 1.7–159 с» — цифру, которой не получить
-никаким прогоном на сервере.
-
-## Опыты с обрывом соединения: убивать процесс, а не звать shutdown()
-
-`ThreadingHTTPServer.shutdown()` перестаёт принимать НОВЫЕ соединения, но уже открытый
-SSE-поток продолжает жить в своём потоке. В #15 первый заход показал `onerror: 0 раз` у
-обеих схем — падения просто не было, а выглядело как «поток пережил рестарт». Рвёт только
-`subprocess.Popen(...)` + `kill()`.
-
-## Скрытую вкладку в headless не сымитировать
-
-`bring_to_front()` на другой странице не делает первую скрытой: `document.hidden` остаётся
-`false`. CDP `Page.setWebLifecycleState: frozen` принимается без ошибки, но
-`visibilityState` не меняется и таймеры идут штатно. Поведение фоновых вкладок здесь
-проверить нельзя — либо на машине юзера, либо помечать UNCERTAIN.
-
-## Перехват статики: после #9 URL версионный, шаблон без `*` мимо
-
-`page.route("**/static/js/app.js")` **больше не матчит** — статика едет как
-`/static/js/app.js?v=<mtime>`. Перехват тихо не срабатывает, страница берёт файл из `main`,
-и прогон зеленеет на чужом коде. Всегда `"**/static/js/app.js*"`.
-Страховка, которая это ловит: первым делом ждать символ, которого в `main` нет —
-`wait_for_function("typeof <новая функция> === 'function'")`. В #15 только он и вскрыл
-дыру, которая к тому моменту жила в шести скриптах сутки.
-
-## Зелёный перехват доказывать мутацией, а не зелёным прогоном
-
-Когда файл ветки совпадает с тем, что отдаёт сервер (после мержа — всегда), неприменившийся
-стаб выглядит ровно как применившийся. Единственная улика — намеренно сломанный стаб:
-скрипт ОБЯЗАН покраснеть. Готовый харнесс: `docs/tasks/8/mutation-check.py` (мутант кладётся
-рядом со скриптами — у них `ROOT = parents[3]` — и удаляется после прогона).
-Мутация должна падать сама, если её якорь исчез из `app.js`, иначе она протухнет молча.
-
-## Вакуумно зелёные проверки: `all([]) == True`
-
-📝 RULE: Когда проверка агрегирует собранное на лету (`all(...)`/`any(...)` по списку из DOM,
-файлов, логов) → первым делом гард на непустоту списка, иначе пустой сбор печатает зелёное,
-ничего не проверив.
-
-
-Любая проверка вида `all(... for x in собранное)` печатает `OK`, когда собранное пусто.
-В #8 пустой список агентов дал три зелёных проверки при полностью пустом прогоне; красным
-его сделал только случайный `max()` на пустом списке. Перед циклом — `wait_for_selector`
-и явный выход, если элементов меньше ожидаемого.
-
-## Тайминги фронта на этой машине судить только при load average ≤ 5
-
-Здесь живут агенты и uvicorn: при load 6.5–8 headless-chrome голодает по CPU, и одно и то же
-переключение даёт 64 мс или 1555 мс при НУЛЕ сетевых запросов (сервер в это время отвечает
-за 5–130 мс). Порог времени без гарда по `os.getloadavg()[0]` — генератор случайных красных.
-Печатать значение, но не судить: `check_perf` в `docs/tasks/8/verify-switch.py`.
-Оттуда же: ждать надо ФАКТА (переоткрытый поток, ненулевой `#chat`, `data:image` в DOM),
-а не фиксированной паузы — под нагрузкой любая пауза мала.
-
-## Общая `/tmp/live_copy.db` — путь абсолютный, наличие таблицы проверять
-
-Копию живой БД делят три скрипта. Путь через `ROOT.parents[N]` из worktree промахивается
-(`/home/kesha/orchestra/orchestra/data/...`), а после промаха на диске остаётся ПУСТОЙ файл
-копии — следующий прогон молча идёт на нём и падает `no such table: logs` посреди страницы.
-Писать `/home/kesha/orchestra/data/orchestra.db` буквально и пересоздавать копию, если в ней
-нет таблицы `logs`.
-
-## HTTP-заголовки — latin-1, тестовые значения только ASCII
-
-Кириллица в заголовке доезжает до клиента mojibake, сравнение падает, и это выглядит как
-дефект кода. В #15 на этом покраснела проверка баннера версии.
-
-## Шаблон с новым Jinja-глобалом кладёт прод в окне мержа-рестарта
-
-`{{ build_id() }}` в процессе, который этой функции ещё не знает, даёт `UndefinedError` →
-`/` отдаёт 500, то есть дашборда нет целиком, пока человек не перезапустит сервис.
-Любой новый глобал в шаблоне писать как `{{ x() if x is defined else '' }}` и покрывать
-тестом. Проверять прямым рендером `Environment().from_string(...)`, а не рассуждением.
-
-## Тесты мержа: пустой коммит доказывает ноль
-
-`git commit --allow-empty` в тесте squash-мержа — зелёное на пустом месте: сливать нечего,
-squash не создаёт коммита, и `git log -1 main` показывает `init`. Коммит в тесте обязан
-менять файл. Там же: сообщение воркера уезжает в ТЕЛО squash-коммита (`%b`), не в тему,
-а ветка воркера после мержа переставляется — сравнивать HEAD надо с записанным ДО мержа.
-Общая точка моков мержа — `_prepare_detached_merge` в `tests/test_api.py` (там же живут
-выдуманные пути вроде `/wt`, на которых настоящий git падает).
-
-## Константа в СИГНАТУРЕ не подменяется monkeypatch'ем
-
-`def f(limit=LOCK_WAIT_LIMIT_SECONDS)` вычисляется при определении функции — `monkeypatch.setattr(mod, "LOCK_WAIT_LIMIT_SECONDS", 0.3)` молча не действует, и тест уходит в реальные 25 с
-или проходит не тем путём. Константу, которую собираются подменять, читать В ТЕЛЕ
-(`limit = CONST if limit is None else limit`). Поймал в #27 только потому, что тест проверял
-ПОВЕДЕНИЕ (пришёл ли 409), а не факт вызова.
-
-## `git checkout -- <файл>` при грязном дереве стирает СВОЮ работу
-
-Откатывал мутацию — стёр незакоммиченные правки в том же файле (#30, `manager.py`:
-импорт и две замены). Правило знал, но применил его к слову «мутация», а не к слову
-«checkout». Формулировка, которая срабатывает раньше: **пока в дереве есть незакоммиченное,
-`git checkout -- <файл>` не набирать вообще**; для отката файла — только
-`git show <commit>:<файл> > <файл>`, а вернуть — тем же способом из своего коммита.
-
-## Файл тестов внезапно висит минутами → гоняй с `--timeout=30`
-
-`tests/test_api.py` перестал укладываться в 8 минут: чужой стаб разошёлся с сигнатурой
### 180f78bd4 #54: #54: sessions.id не может быть пустым — схема, триггер, гард в коде, громкий ноль строк, 400 в bg_create

diff --git a/app/manager.py b/app/manager.py
index c1887da6b..e57598566 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -1162,11 +1162,20 @@ class SessionManager:
         else:
             from app.db import _conn
             sets = ", ".join(f"{k}=?" for k in fields)
             vals = [int(v) if isinstance(v, bool) else v for v in fields.values()]
             with _conn() as c:
-                c.execute(f"UPDATE sessions SET {sets} WHERE id=?", (*vals, found.id))
+                cur = c.execute(
+                    f"UPDATE sessions SET {sets} WHERE id=?", (*vals, found.id),
+                )
+                if cur.rowcount == 0:
+                    # Молчаливый ноль здесь означал бы, что поля «сохранены» только
+                    # в памяти вызывающего, а в БД их нет (#54).
+                    logger.warning(
+                        "UPDATE sessions changed 0 rows: fields %s for id=%r not persisted",
+                        list(fields), found.id,
+                    )
         return found
 
     async def persist_lifecycle(
         self,
         session: AgentSession,
diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index ae88d97ea..56f3f8ffd 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -44,10 +44,18 @@
 - **Скрытую вкладку в headless не сымитировать**: ни `bring_to_front()`, ни CDP
   `setWebLifecycleState: frozen` не меняют `visibilityState`. Либо машина юзера, либо UNCERTAIN.
 - **Обрыв соединения — только `Popen` + `kill()`.** `ThreadingHTTPServer.shutdown()`
   оставляет открытый SSE живым, и это выглядит как «поток пережил рестарт».
 
+## Баг-репорт = две разные части, и протухают они по-разному
+
+«В коде дыра» проверяется кодом и живёт долго. «В базе такая строка» проверяется базой и
+мертво уже через сутки. В #54 схемная дыра подтвердилась замером, а описанная строка
+исчезла за двое суток — и на ней стояла вся срочность. Сначала `SELECT` по текущему
+состоянию, потом планирование, и **отрицательный результат сообщать сразу**: он снимает
+чужие ложные доводы (у оркестратора это был довод про рестарт).
+
 ## Факты про этот проект, на которые я уже опирался
 
 - **Запись в `logs` видит ДАШБОРД, а не агент.** `get_logs` читается только для
   `_build_runtime_handoff` (`session.py:1519`) и берёт ТОЛЬКО `user_message` и `text`;
   `system` отфильтровывается. «Оставим строку в его истории — прочитает на следующем ходу»
### 0d3975b02 #56: #56: исследование — репорт пишется в стор и на этом всё; адресат вычислим, семь старых разобраны

diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index 56f3f8ffd..d23966955 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -52,10 +52,18 @@
 мертво уже через сутки. В #54 схемная дыра подтвердилась замером, а описанная строка
 исчезла за двое суток — и на ней стояла вся срочность. Сначала `SELECT` по текущему
 состоянию, потом планирование, и **отрицательный результат сообщать сразу**: он снимает
 чужие ложные доводы (у оркестратора это был довод про рестарт).
 
+## «Живая проверка» на неразвёрнутом коде — это половина проверки
+
+`app/routes/` живёт в памяти systemd до рестарта, поэтому мой новый роут на живом сервере
+не исполняется. Подать настоящий запрос можно (он ляжет в стор), а увидеть новое поведение —
+нет. Говорить это ПРЯМО и называть, какая половина проверена: в #56 подача живая, приём —
+сквозным прогоном. `app/mcp_stdio.py` при этом подхватывается сразу — асимметрия видна
+только если про неё помнить.
+
 ## Факты про этот проект, на которые я уже опирался
 
 - **Запись в `logs` видит ДАШБОРД, а не агент.** `get_logs` читается только для
   `_build_runtime_handoff` (`session.py:1519`) и берёт ТОЛЬКО `user_message` и `text`;
   `system` отфильтровывается. «Оставим строку в его истории — прочитает на следующем ходу»
### 10d1a858b #61: #61: исследование — конфликт только когда база доработала те же строки; критерий из git недоступен

diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index d23966955..3ede954ef 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -60,10 +60,24 @@
 не исполняется. Подать настоящий запрос можно (он ляжет в стор), а увидеть новое поведение —
 нет. Говорить это ПРЯМО и называть, какая половина проверена: в #56 подача живая, приём —
 сквозным прогоном. `app/mcp_stdio.py` при этом подхватывается сразу — асимметрия видна
 только если про неё помнить.
 
+## После сквош-мержа git НЕ может доказать, что работа в базе
+
+Предка сквош не сохраняет (`--is-ancestor` → нет), а сравнение деревьев
+(`branch_content_status`) даёт `conflict`, как только база правит те же строки — то есть
+врёт ровно в том случае, который ломается. Доказательство брать из своей записи:
+`merge_operations` (`state='SUCCEEDED' AND commit_point='REACHED'`, `accepted_worker_branch`
++ голова). Готовый хелпер — `db.find_merge_proof()`; он же учитывает, что при
+`BENIGN_ADVANCE` из #17 слитая голова отличается от принятой.
+
+## `UV_CACHE_DIR` на этом VPS — `/home/kesha/.cache/uv`
+
+`/mnt/data` тут нет (это путь с ноутбука), а `/tmp` — часть корневого раздела, не tmpfs
+(`findmnt /tmp` пусто, 254 ГБ свободно). Кеш всё равно держать на своём диске, а не в `/tmp`.
+
 ## Факты про этот проект, на которые я уже опирался
 
 - **Запись в `logs` видит ДАШБОРД, а не агент.** `get_logs` читается только для
   `_build_runtime_handoff` (`session.py:1519`) и берёт ТОЛЬКО `user_message` и `text`;
   `system` отфильтровывается. «Оставим строку в его истории — прочитает на следующем ходу»
### ef9c8057b #62: #62: фаза 1 — рабочие копии сносит pytest в главном чекауте, воспроизведено

diff --git a/app/manager.py b/app/manager.py
index e57598566..7639f832e 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -408,10 +408,17 @@ class SessionManager:
 
     def start_background_tasks(self) -> None:
         # log retention REMOVED by owner decision: agent history is research data. The old
         # `_periodic_db_cleanup` dropped logs older than 7 days every 6h, silently destroying
         # every transcript past a week while `sessions` rows survived since May. Never restore
+        # Never under pytest: every TestClient(app) enters lifespan, and a test that points
+        # app.db at a temporary database while WORKTREE_ROOT still points at the real
+        # checkout deletes every clean working copy of every project (docs/tasks/62 —
+        # reproduced: one green `pytest tests/test_build_signal.py` erased both decoys).
+        if "pytest" in sys.modules:
+            logger.warning("worktree cleanup task not started: running under pytest")
+            return
         if not getattr(self, '_wt_cleanup_task', None) or self._wt_cleanup_task.done():
             self._wt_cleanup_task = asyncio.create_task(self._periodic_worktree_cleanup())
 
     @staticmethod
     def _ownership_prompt(owned_dirs: list[str]) -> str:
### 750d0d0b2 #50: #50: исследование — точка врезки в send() измерена, очередь обязана быть durable

diff --git a/app/manager.py b/app/manager.py
index 7639f832e..a009a7f5d 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -103,10 +103,24 @@ async def wait_for_session_lock(lock, *, what: str, worker: str, limit: float |
         yield waited
     finally:
         lock.release()
 
 
+def _auto_report_key(worker_session, worker_name: str) -> str:
+    """Ключ дедупликации автоотчёта (#50).
+
+    Стабильного id хода в системе нет: `_turn_gen` — счётчик в памяти сессии, он
+    обнуляется рестартом. Поэтому ключ строится из id сессии и номера хода, а когда
+    сессия недоступна — из имени и времени, и это ВИДНО в самом ключе (`notrack`).
+    Два быстрых автоотчёта тогда дадут две записи; это лучше, чем невидимо склеить
+    два разных события в одно.
+    """
+    if worker_session is not None:
+        return f"autoreport:{worker_session.id}:{getattr(worker_session, '_turn_gen', 0)}"
+    return f"autoreport:{worker_name}:notrack:{datetime.now(timezone.utc).isoformat()}"
+
+
 def next_adhoc_branch(worker_name: str) -> str:
     """Имя ветки для авто-переключения перед доставкой сообщения.
 
     Секунды эпохи БЕЗ усечения. Прежняя форма `str(int(time.time()))[-6:]` замыкала
     пространство имён каждые 10**6 с = 11.57 суток, а ветки `adhoc-*` не удаляются —
@@ -1489,10 +1503,11 @@ class SessionManager:
             self,
             scope=worker_scope,
             worker=worker_name,
             what="автоотчёт",
             reason=detail,
+            dedupe_key=_auto_report_key(worker_session, worker_name),
         )
         # Причина не дублируется: в исходе попытки она чаще всего та же самая, и запись
         # раздувается вдвое ровно там, где её будет читать человек.
         if detail in attempt:
             attempt = attempt.replace(detail, "та же причина")
diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index 3ede954ef..393b9b842 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -105,7 +105,13 @@
   выдуманные пути (`/wt`), на которых настоящий git падает.
 - **`/tmp/live_copy.db` делят три скрипта #8**: путь писать абсолютным
   (`/home/kesha/orchestra/data/orchestra.db`) и пересоздавать копию, если в ней нет таблицы
   `logs` — после промаха остаётся ПУСТОЙ файл, и прогон падает посреди страницы.
 - **Тестовые значения в HTTP-заголовках — только ASCII**: кириллица доезжает mojibake.
+- **Сессия, начавшая ход, вешает TEARDOWN**: мок `events()` ждёт вечно, слушающая задача
+  живёт после теста, и прогон висит МИНУТАМИ при зелёном тесте («1 passed, 1 error»).
+  В уборке фикстуры — `await session.stop()`, потом отмена задач.
+- **`make_backend_mock()` это `AsyncMock`**: любой `getattr(backend, "флаг", False)`
+  истинен. Из-за `resume_failed` сессия уходила в ветку восстановления транскрипта и молча
+  затирала `runtime_handoff`. Флаги, которые читает код, ставить в моке ЯВНО.
 - **Файл тестов внезапно висит минутами → `--timeout=30`.** Обычно чужой стаб разошёлся с
   сигнатурой, а выглядит как «мои правки всё сломали». Сначала timeout, потом паника.
### 7a6f0ab75 #69: #69: репозиторий воркера от git, слаг от repo root; strategy=parent через границу репо

diff --git a/app/manager.py b/app/manager.py
index a009a7f5d..58bb7b3e4 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -26,10 +26,11 @@ from app.prompting import (
 _TASK_BRANCH_RE = re.compile(r"^(?:task-|[A-Z]{2,5}-)(\d+)/")
 from app.workspace import (
     create_worktree, discard_prepared_worktree, remove_worktree,
     parse_owned_dirs, dirs_overlap,
     validate_repo_root, resolve_base_branch as resolve_git_base_branch,
+    repo_root,
 )
 from app.models import (
     CONTEXT_LIMITS,
     available_models_block,
     backend_for_model,
@@ -405,10 +406,25 @@ def _make_mcp_config(name: str, scope: str, role: str = "worker",
                 continue
             cfg[k] = v
     return cfg
 
 
+def _crosses_repo_boundary(parent_dir: str, child_repo: str) -> bool:
+    """Родитель и ребёнок в РАЗНЫХ репозиториях? Спрашиваем git, а не сравниваем пути.
+
+    Каталог `seedon/site` лежит внутри `seedon`, но это другой репозиторий; префиксное
+    сравнение путей ответило бы «тот же» (#69). Не смогли определить — считаем, что
+    граница НЕ пересечена: тогда исходная ошибка о ненайденной ветке уйдёт наверх как есть,
+    без выдуманного объяснения.
+    """
+    try:
+        return repo_root(parent_dir) != repo_root(child_repo)
+    except Exception as exc:
+        logger.warning("не смог сравнить репозитории '%s' и '%s': %s", parent_dir, child_repo, exc)
+        return False
+
+
 class SessionManager:
     def __init__(self):
         self.sessions: dict[str, AgentSession] = {}
         self._session_locks: dict[str, asyncio.Lock] = {}
         self._spawn_locks: dict[tuple[str, str], asyncio.Lock] = {}
@@ -1268,21 +1284,39 @@ class SessionManager:
         except FileNotFoundError:
             rr = None
         if rr is None or rr.base_branch_strategy == "main":
             return resolve_git_base_branch(repo_path)
         parent_branch = ""
+        parent_dir = ""
         if parent_name:
             ps = self.get_by_name(parent_name, scope)
             if ps is not None:
                 parent_branch = ps.branch or ""
+                parent_dir = ps.worktree_path or ps.cwd or ""
         if not parent_branch:
             logger.warning(
                 "base_branch_strategy=parent, но у родителя '%s' нет ветки — "
                 "resolving repository mainline",
                 parent_name)
             return resolve_git_base_branch(repo_path)
-        return resolve_git_base_branch(repo_path, parent_branch)
+        try:
+            return resolve_git_base_branch(repo_path, parent_branch)
+        except ValueError:
+            # Ветка родителя может жить в ДРУГОМ репозитории: в одном scope их бывает
+            # несколько (у seedon `site/` и `infra/` — свои git root'ы со своими origin).
+            # «Ответвись от родителя» через границу репозитория не значит ничего — там
+            # другая история. Берём mainline репозитория РЕБЁНКА, но громко: молчаливая
+            # подмена базы хуже отказа. Если репозиторий ТОТ ЖЕ, отсутствие ветки —
+            # настоящая ошибка, и она летит дальше (#69).
+            if parent_dir and _crosses_repo_boundary(parent_dir, repo_path):
+                logger.warning(
+                    "base_branch_strategy=parent: ветка '%s' родителя '%s' живёт в другом "
+                    "репозитории (%s), воркер спавнится в %s — база взята из mainline его "
+                    "репозитория",
+                    parent_branch, parent_name, parent_dir, repo_path)
+                return resolve_git_base_branch(repo_path)
+            raise
 
     @staticmethod
     def _role_is_orchestrator(pipeline: str, role: str) -> bool:
         """R1: is_orchestrator из kind манифеста; fallback на frozenset апстрима.
 
### 84d58f6a0 #52: #52: исследование — N-1 конфликт по построению, правило не выполняется 0 из 8, материал уже есть в отчётах

diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index 393b9b842..82b9025ea 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -12,10 +12,16 @@
   `git show <commit>:<файл> > <файл>`, возврат — тем же способом из своего коммита.
 - **Сервис `orchestra` не рестартую.** Замеры, требующие рестарта, — через оркестратора.
 
 ## Доказательства: чем зелёное отличается от проверенного
 
+- **Свежий `git init` даёт `master`, а не `main`.** `git checkout main` тихо падает, ветки
+  ложатся в одну цепочку, и стенд показывает «конфликтов нет» там, где их не могло быть.
+  В стенде — `git branch -M main` сразу после init, и проверять предпосылку, а не вывод.
+- **«Успешно» в выводе скрипта — не доказательство.** Мой же `--seed` печатал «отсечка
+  проставлена», пока узкий regex не матчил метку: сообщение было, эффекта нет. Проверять
+  СЛЕДУЮЩЕЙ командой, а не сообщением об успехе.
 - **Мутация — единственная улика.** Когда файл ветки совпадает с тем, что отдаёт сервер
   (после мержа — всегда), неприменившийся стаб выглядит как применившийся. Ломай нарочно:
   проверка ОБЯЗАНА покраснеть. Харнесс для браузерных прогонов — `docs/tasks/8/mutation-check.py`;
   для кода — откат файла через `git show`. Мутация должна падать сама, если её якорь исчез.
 - **`all([]) == True`.** Проверка, агрегирующая собранное на лету (DOM, файлы, логи), при