# Context for item-11

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/CHANGELOG.md b/CHANGELOG.md
index dedbbc6b0..a2d2792da 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,31 +1,34 @@
 # Changelog
 
 > **Two environments merged, 04.08.2026.** Before this date, the laptop and VPS maintained
 > their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Removed
 - **Скилл `vps-deploy` убран из продукта** (`prompts/skills/vps-deploy.md`, `pipeline.yaml` у оркестратора). Решение владельца 29.09: это было единственное место поставки с упоминанием хостинга, а перезапуск Orchestra и так инициирует только владелец.
 
+### Fixed
+- **Инструменты AUDIT/FINAL больше не попадают в обычную ленту как сиротские результаты** (`AgentSession.compact`, `_agentic_audit_summary`, V-672). Черновик, AUDIT и FINAL записывают отдельные `compact_event` с общей принадлежностью и ID вызовов; дашборд собирает их в свёрнутый блок с результатами, итоговой сводкой и доступной статистикой. Telegram-мост пропускает эти служебные события. Ограничение объёма истории оставляет событие валидным JSON, показывает отметку и даёт загрузить полный текст, не меняя запись в БД. Триггер: после запуска компакта seedon-orchestrator записал 34 `tool_result` без ID и ни одного парного `tool`.
+
 ### Changed
 - **Плавное движение в каркасе `html-motion`** (`prompts/skills/html-motion.md`, V-668). Владелец посмотрел примеры V-665: «не плавно нихуя, надо плавнее, как Apple». Каркас переписан так, что плавность обеспечивает он сам, а формат `STEPS` не изменился. У каждого атрибута теперь свой список отрезков. Движение по умолчанию идёт по пружине с критическим затуханием, а не по квадратичному in-out. Если атрибут меняется в соседних шагах в одну сторону, стык склеивается монотонным кубическим сплайном (Фрич–Батленд), и объект проходит границу шага без остановки: курсор графика раньше вставал на 4 границах из 6, теперь ни на одной. Цвет, `opacity` и `text` меняются за 0.5 с. Текст сменяется наплывом через клон-призрак: старый уходит раньше, чем проявляется новый. Появление идёт с лёгким сдвигом и масштабом. Подпись шага и подсветка главы тоже меняются наплывом и вычисляются из `t`, поэтому пауза и перемотка по-прежнему дают тот же кадр до пикселя (добавлена проверка середины наплыва: 0 px). ⏮ ⏭ и ←/→ доезжают до цели за 0.4 с. Панель получила круглые кнопки с SVG-иконками, анимацию нажатия, превращение пуска в паузу и ползунок с заливкой. Примеры перерисованы: токен идёт невидимыми путями через центры узлов, за узлами, поэтому исчезли 2 видимых телепорта. Точка графика едет по линии, а не ступеньками по целым процентам. Видео пишется покадрово через `P.seek(k/60)` при 60 к/с. Экранная запись Playwright давала 25 к/с с повторёнными кадрами, отсюда большая часть рывков в роликах V-665. Все числа — в `.orchestra/tasks/V-668/report.md`.
 - **Known tradeoff:** каркас вырос с ~2.3 до ~4.3 тыс. токенов (o200k). Его копируют командой `awk`, а не пишут, при этом скрипт сцены в примерах изменился на −3% и +8%. Элементу с анимируемым `text`/`opacity` больше нельзя давать собственный `transform`: каркас двигает его через CSS `transform`.
 
 ### Added
 - **Скилл `html-motion`: анимированные объяснения по шагам с плеером** (`prompts/skills/html-motion.md`, `defaults.skills`, V-665). Скилл содержит готовый каркас одного HTML-файла: кадр — чистая функция времени, сцена задаётся декларативным массивом `STEPS` (`set`/`w`/`along`) с пояснением к каждому шагу. Плеер умеет пуск/паузу, шаги, ползунок, скорость, клавиши, главы, reduced motion и ссылку `#t=`, а для проверки открыт `window.P`. На одной и той же сцене четыре техники сравнивались по токенам, офлайну и совпадению кадров: у выбранной сцена стоит 668 токенов против 741–893 у остальных, а кадр на паузе совпадает с кадром при перемотке до пикселя. В Web Animations API найдены две ловушки: асинхронный `pause()` и `play()`, который перематывает завершённую анимацию в 0 (1684 px расхождения в конце). GSAP с CDN не работает офлайн. Каркас вынесен в отдельный скилл, потому что тело `html-artifacts` упирается в потолок 16000 байт, а в воркеры копируется только `SKILL.md`. `base.md` называет `html-motion` спутником `html-artifacts`. Примеры, кадры и MP4 — в `.orchestra/tasks/V-665/`.
 - **Sonnet 5.5 (1M) становится единственным Sonnet в выборе** (`app/models.py`, V-658). `sonnet`, `sonnet5.5` и прежние Sonnet 5/4.x id направляются в `claude-sonnet-5-5[1m]`; при восстановлении сессии `Manager` канонизирует сохранённый id до создания backend. Старый Sonnet 5 пропадает из списка, а окно 1M и цены $2/$10 за миллион соответствуют новой модели. Запуск со старым `claude-sonnet-5[1m]` теперь возобновляется на 5.5.
 - **Временная шкала квот пула** (`QuotaPanel`, `build_quota_map`, V-652). Над прежним графиком добавлена 168-часовая шкала ±84 ч с центром в моменте снимка, часовыми/дневными метками Красноярска и ночной подсветкой 00:00–08:00. Пороги и равномерный расход повторяются от границ циклов квоты; исторические точки из `usage_snapshots` включают сбросы и не продолжаются в будущее. Старый график сохранён ниже без изменения SVG.
 - **Read-only детектор повторяющихся ошибок** (`app.error_watch`, V-647). Команда для расписания читает ошибки unit-журнала и строки `logs` через SQLite `mode=ro`, обезличивает динамические значения, отсеивает квотные/лимитные отказы, штатный listener `IDLE`/`WAITING` и парные записи двух logger handlers, затем дедуплицирует новые превышения порога. Подтверждённый listener exit во время `RUNNING` сигналится с порогом 1. Реестр рядом с БД связывает сигнатуру с задачей, коммитом и временем запуска для post-fix наблюдения; включение `cron_command` описано в отчёте V-647. Детектор не меняет код и не создаёт задач.
 
 ### Fixed
 - **Проверка сводки сжатия (V-650) откатывалась на черновик при любом предупреждении о лимите** (`AgentSession._agentic_audit_summary`). Claude присылает `provider_limit` со статусом `allowed_warning` на каждом ходу, если недельный лимит выше 75%, а проход AUDIT считал его отказом. Первое боевое сжатие (cog-second-brain, 28.09 11:12 UTC) ушло на черновик за 22 с. Теперь проходы прерывает только `rejected`, как и ход черновика.
 - **Временная шкала квот показывает фактическую историю** (`QuotaPanel._qlTimelineSvg`, V-654). `timeline.points[].resets_at` менялся между снимками, но график принимал каждый вариант за отдельный сброс и перекрывал линии расхода пороговыми зигзагами. Циклы порогов теперь строятся по текущему `window.resets_at` и длительности окна, а история отдельно соединяет реальные снимки и текущую точку. На шкале есть двухчасовые засечки; подписи времени идут через 4 часа, а границы ночи 00:00 и 08:00 всегда подписаны днём недели.
 - **Ожидающий таймер предкомпакта отменяется при удалении воркера** (`Manager.remove`, `AgentSession._cancel_precompact_timer`, V-653). Раньше убитый Codex-воркер оставлял таймер на 25 минут; он запускал нативное сжатие уже после архивации и удаления worktree, затем завершался `FileNotFoundError`. Удаление отменяет таймер до срабатывания.
 - **`cron_command` сообщает о таймауте цели задания** (`BgJobManager._fire_cron_command`, V-653). Таймаут 600 секунд сохраняется в `last_output` и доставляет цели job id, команду, лимит и подсказку проверить запуск; повторные таймауты не дублируют сообщение до успешного запуска. Это исправляет молчаливый простой cron-сборщика seedon. Заменяет прежнее ограничение из V-647: таймаут теперь будит цель.
 - **Миграция V-576 восстанавливает отсутствующую `attention_events`** (`_migrate_database`, V-653). Существующие базы v2→v3 создают таблицу с `IF NOT EXISTS`; старт v3 также чинит базу, где таблицу удалили или она отсутствовала, включая ручное создание без дубликатов. Триггер: `notify_user` падал с `no such table: attention_events` на VPS и ноутбуке.
 - **`cron_command` убивал команду через 30 с молча** (`_CRON_COMMAND_TIMEOUT_SECONDS` в `app/bg_jobs.py` 30 → 600, лимит назван в описании `bg_create`). Сборщик закупок seedon 4 дня не собирал ничего, error watch Orchestra (`app.error_watch scan`, ~59 с на базе 2.2 ГБ) не отрабатывал ни разу за последние 12 ч: в `last_output` только `[command timed out after 30 seconds]`, цель не будилась. Запуски идут последовательно, поэтому длинный лимит не создаёт наложений. Таймаутное уведомление добавлено в V-653.
 - **Ложная тревога «silent death» больше не пишется на штатный конец хода** (`AgentSession._on_task_done`, V-648).
   Предупреждение `listen task exited without exception (silent death)` печаталось при любом нормальном выходе
   слушателя: конец потока после `turn_end` и подавленная отмена перед сжатием. За 20–27.09 — 475 событий, из них
diff --git a/app/db.py b/app/db.py
index 361152b9c..c82316986 100644
--- a/app/db.py
+++ b/app/db.py
@@ -1360,40 +1360,69 @@ def _project_image_generation_result(row: dict, cap: int) -> dict | None:
     row["content"] = encoded
     row["projection"] = "image_generation"
     row["source_bytes"] = len(source.encode())
     row.pop("trunc", None)
     return row
 
 
 def _cap_content(row: dict, cap: int) -> dict:
     """Обрезать content до cap БАЙТ (не символов) и пометить обрезку.
 
     Байты, а не символы: бюджет клиентского зеркала считается в байтах, а кириллица
     в UTF-8 даёт 2 байта на символ — по символам потолок уехал бы вдвое. Срез может
     разрубить символ пополам, поэтому errors="ignore".
     """
     projected = _project_image_generation_result(row, cap)
     if projected is not None:
         return projected
     raw = (row.get("content") or "").encode()
     if len(raw) <= cap:
         return row
+    if row.get("type") == "compact_event":
+        try:
+            event = json.loads(raw)
+        except (json.JSONDecodeError, UnicodeDecodeError):
+            event = None
+        content_field = (
+            "content" if isinstance(event, dict) and isinstance(event.get("content"), str)
+            else "summary" if isinstance(event, dict) and isinstance(event.get("summary"), str)
+            else ""
+        )
+        if isinstance(event, dict) and content_field:
+            source = event[content_field].encode()
+            event["content_truncated_bytes"] = len(source)
+            keep = max(
+                0,
+                cap - len(json.dumps({**event, content_field: ""}, ensure_ascii=False).encode()) - 8,
+            )
+            while True:
+                event[content_field] = source[:keep].decode(errors="ignore") + "…"
+                encoded = json.dumps(event, ensure_ascii=False).encode()
+                if len(encoded) <= cap or keep == 0:
+                    break
+                keep //= 2
+            event["content_truncated_bytes"] = max(
+                0, len(source) - len(event[content_field].encode()),
+            )
+            encoded = json.dumps(event, ensure_ascii=False).encode()
+            row["content"] = encoded.decode()
+            return row
     row["content"] = raw[:cap].decode(errors="ignore")
     row["trunc"] = len(raw)  # исходная длина в байтах — её показывает кнопка «загрузить целиком»
     return row
 
 
 def get_logs_sync(after_id: int = 0, tail: int = 20, cap: int = 16384) -> dict:
     """Журнал всех сессий всех проектов одним ответом — для зеркала в браузере.
 
     after_id == 0 — холодный старт: последние ``tail`` строк на каждую сессию.
     ``tail == 0`` — только карта сессий и отметка, без единой строки журнала: зеркало
     наполняется тем, что юзер реально открыл (#72). Раньше клиент просил tail=20 на все
     сессии и получал 145 КБ по проводу ради строк, из которых рисовалось ~5%.
     after_id > 0  — инкремент: всё, что появилось после этой отметки.
 
     ``live_sessions`` — полный список сессий БЕЗ фильтров, по ``{id, name, scope}``.
     Логи висят на sessions(id) с ON DELETE CASCADE (и foreign_keys=ON), поэтому
     удалённая сессия уносит свой журнал, и клиент обязан это повторить. Отсюда же
     требование к вызывающему: пустой список означает сбой, а не «сессий нет» — по нему
     нельзя вычищать зеркало.
 
diff --git a/app/session.py b/app/session.py
index ba200dc69..2133d5448 100644
--- a/app/session.py
+++ b/app/session.py
@@ -2697,171 +2697,234 @@ class AgentSession:
         except QuotaGateError:
             raise
         except Exception as exc:
             detail = err_text(exc)
             self._log("error", f"native Codex compact failed: {detail}")
             return {
                 "ok": False,
                 "mode": "native",
                 "error": detail,
                 "before_pct": before_pct,
                 "thread_id": self.session_id,
             }
         finally:
             self._compacting = False
             if self._pending_messages:
                 self._spawn_bg(self._flush_pending())
             elif self.status == AgentStatus.IDLE:
                 self._hibernate.schedule()
             self._wake_durable_message_deliveries()
 
-    async def _agentic_audit_summary(self, draft: str, stop_gen: int, backend) -> str:
+    def _log_compact_event(self, compact_id: str, **event) -> None:
+        tool_use_id = str(event.get("tool_use_id") or "")
+        content = event.pop("content", None)
+        if content is not None:
+            event["content"] = content
+        self._log(
+            "compact_event",
+            json.dumps(event, ensure_ascii=False),
+            event_id=compact_id,
+            tool_use_id=tool_use_id or None,
+            tool_name=str(event.get("tool_name") or "") or None,
+            tool_is_error=bool(event.get("is_error")) if event.get("kind") == "tool_result" else None,
+        )
+
+    async def _agentic_audit_summary(
+        self, draft: str, stop_gen: int, backend, compact_id: str,
+    ) -> tuple[str, bool, float]:
         """Run AUDIT and FINAL as subsequent turns in the draft's Claude session."""
         if self.backend_type != "claude" or not agentic_compact.enabled():
-            return draft
+            return draft, False, 0.0
         started = time.monotonic()
         cost = 0.0
         directory = None
         events = backend.events().__aiter__()
 
-        async def run_pass(prompt: str, deadline: float) -> None:
+        async def run_pass(phase: str, prompt: str, deadline: float) -> None:
             nonlocal cost
             if self._turn_start_cancel_gen != stop_gen:
                 raise RuntimeError("stopped")
+            pass_started = time.monotonic()
+            pass_cost = cost
+            self._log_compact_event(compact_id, action="step_start", phase=phase)
             await backend.send(prompt)
             end_event = None
             next_event = None
             while end_event is None:
                 if self._turn_start_cancel_gen != stop_gen:
                     await backend.interrupt()
                     if next_event is not None:
                         next_event.cancel()
                         await asyncio.gather(next_event, return_exceptions=True)
                     raise RuntimeError("stopped")
                 remaining = deadline - time.monotonic()
                 if remaining <= 0:
                     await backend.interrupt()
                     if next_event is not None:
                         next_event.cancel()
                         await asyncio.gather(next_event, return_exceptions=True)
                     raise TimeoutError("timeout")
                 if next_event is None:
                     next_event = asyncio.create_task(events.__anext__())
                 done, _ = await asyncio.wait({next_event}, timeout=min(1, remaining))
                 if not done:
                     continue
                 event = next_event.result()
                 next_event = None
                 if event.type == "turn_end":
                     end_event = event
                     self._cost.apply_turn_result(event.metadata, event.usage)
                     cost += self._turn_cost
                 elif event.type in {"tool", "tool_result"}:
-                    self._log(event.type, event.content)
+                    self._log_compact_event(
+                        compact_id,
+                        action="tool",
+                        phase=phase,
+                        kind=event.type,
+                        content=event.content,
+                        tool_use_id=event.metadata.get("tool_use_id", ""),
+                        tool_name=event.metadata.get("tool_name", ""),
+                        is_error=bool(event.metadata.get("is_error")),
+                    )
                 elif event.type == "error":
                     raise RuntimeError(event.content or "provider error during compact audit")
                 elif event.type == "provider_limit":
                     self._handle_event(event)
                     if event.metadata.get("status") == "rejected":
                         raise RuntimeError("provider limit during compact audit")
             if end_event.metadata.get("ok") is not True:
                 raise RuntimeError("compact audit turn failed")
+            self._log_compact_event(
+                compact_id,
+                action="step_done",
+                phase=phase,
+                seconds=round(time.monotonic() - pass_started, 1),
+                **({"cost_usd": round(cost - pass_cost, 6)} if cost > pass_cost else {}),
+            )
 
         try:
             sandbox_root = agentic_compact.sandbox_root()
             sandbox_root.mkdir(parents=True, exist_ok=True)
             directory = Path(tempfile.mkdtemp(prefix="compact-", dir=sandbox_root))
             journal_dir = await agentic_compact.prepare_journal(self.id, directory)
             summary_path = directory / "summary.md"
             summary_path.write_text(draft)
             deadline = started + float(os.getenv("AGENTIC_COMPACT_TIMEOUT", "900"))
-            for prompt in (
-                agentic_compact.audit_prompt(journal_dir, summary_path),
-                agentic_compact.final_prompt(journal_dir, summary_path),
+            current_phase = "audit"
+            for phase, prompt in (
+                ("audit", agentic_compact.audit_prompt(journal_dir, summary_path)),
+                ("final", agentic_compact.final_prompt(journal_dir, summary_path)),
             ):
-                await run_pass(prompt, deadline)
+                current_phase = phase
+                await run_pass(phase, prompt, deadline)
             result = summary_path.read_text().strip() if summary_path.exists() else ""
             if not result:
                 raise RuntimeError("audit produced empty summary")
             if len(result) > agentic_compact.max_chars():
                 raise RuntimeError(
                     f"audit summary too long ({len(result)} > {agentic_compact.max_chars()} chars)"
                 )
             self._log("status", f"agentic compact context summary (replaced):\n{draft}")
             self._log(
                 "status",
                 f"agentic compact audit: summary {len(draft)} → {len(result)} chars, "
                 f"${cost:.2f}, {time.monotonic() - started:.0f}s",
             )
-            return result
+            return result, False, cost
         except Exception as error:
             reason = f"{type(error).__name__}: {error}"[:400]
+            self._log_compact_event(
+                compact_id,
+                action="step_failed",
+                phase=locals().get("current_phase", "audit"),
+                error=reason,
+                **({"cost_usd": round(cost, 6)} if cost else {}),
+            )
             self._log(
                 "status",
                 f"agentic compact audit skipped, original summary kept: {reason} "
                 f"(${cost:.2f}, {time.monotonic() - started:.0f}s)",
             )
-            return draft
+            return draft, True, cost
         finally:
             if directory is not None:
                 shutil.rmtree(directory, ignore_errors=True)
 
     async def compact(self) -> dict:
         if self.backend_type == "codex":
             return await self._compact_codex_context()
 
         # #106 Q6: hot_state_ledger bundle. Bounded promotion replaces the old
         # unconditional CLAUDE.md/TODO.md/BUGS.md presave, which drove 218
         # unrelated writes across 63 measured outputs (candidate: 0).
         COMPACT_PROMPT = _compact_prompt(self.name, self.scope)
         PREAMBLE = (
             "[PREVIOUS CONTEXT SUMMARY — context was compacted]\n\n{summary}\n\n"
             "[END OF SUMMARY]\n{tail}[CONTINUE NATURALLY]\n\n"
         )
         COMPACT_MAX_RETRIES = 3
         COMPACT_RETRY_DELAY = 30
 
         if self._compacting:
             return {"ok": False, "error": "compact already in progress"}
         if self.status == AgentStatus.RUNNING:
             return {"ok": False, "error": "cannot compact while agent is running"}
         if self.backend_type == "claude" and _claude_subscription_limit_active():
             error = "Claude subscription limit active; compact postponed until quota reset"
             self._log("error", error)
             return {"ok": False, "error": error}
         try:
             permit = await self._compaction_permit(reserve=True)
         except QuotaGateError:
             raise
         except RuntimeError as error:
             return {"ok": False, "error": str(error)}
         compact_stop_gen = permit[2]
         self._session_limit_hit = False
         before_pct = self._last_context.get("percentage", 0)
         pre_tokens = self._last_context.get("total_tokens", 0) or 0
         max_tokens = self._last_context.get("max_tokens", 0) or 0
         pre_compact_session_id = self.session_id
+        compact_id = str(uuid.uuid4())
+        compact_started = time.monotonic()
+        compact_cost = 0.0
+        self._log_compact_event(
+            compact_id,
+            action="start",
+            status="running",
+            before_pct=before_pct,
+            pre_tokens=pre_tokens,
+        )
         self._log("status", f"compact started (context {before_pct}%, pre_session={pre_compact_session_id})")
 
         def abort_compact(error: str, *, flush_pending: bool = True) -> dict:
             self.session_id = pre_compact_session_id
             self._compacting = False
+            self._log_compact_event(
+                compact_id,
+                action="finish",
+                status="rolled_back",
+                error=error[:400],
+                before_pct=before_pct,
+                seconds=round(time.monotonic() - compact_started, 1),
+                **({"cost_usd": round(compact_cost, 6)} if compact_cost else {}),
+            )
             if flush_pending and self._pending_messages:
                 self._spawn_bg(self._flush_pending())
             if self._compact_ack_event is None:
                 self._wake_durable_message_deliveries()
             return {"ok": False, "error": error, "before_pct": before_pct}
 
         if self._listen_task and not self._listen_task.done():
             self._listen_task.cancel()
             try:
                 await self._listen_task
             except asyncio.CancelledError:
                 pass
             except Exception as e:
                 logger.warning(f"[{self.name}] listen task failed during compact: {e}")
 
         summary = ""
         last_error = ""
         for attempt in range(1, COMPACT_MAX_RETRIES + 1):
             if attempt > 1:
                 if self._turn_start_cancel_gen != compact_stop_gen:
@@ -2881,51 +2944,61 @@ class AgentSession:
             backend = self._backend
             need_connect = self._backend is None
             try:
                 if need_connect and self.history_import_source == CLAUDE_HISTORY_SOURCE:
                     backend = await self._ensure_backend(activate=False)
                     need_connect = False
                 elif backend is None:
                     backend = self._make_backend()
 
                 async def start_summary_turn():
                     if need_connect:
                         await backend.connect()
                         self._backend = backend
                     await backend.send(COMPACT_PROMPT)
 
                 await self._run_compaction_start(permit, start_summary_turn)
                 async for event in backend.events():
                     if event.type == "text":
                         summary_parts.append(event.content)
                     elif event.type in {"tool", "tool_result"}:
-                        self._log(event.type, event.content)
+                        self._log_compact_event(
+                            compact_id,
+                            action="tool",
+                            phase="draft",
+                            kind=event.type,
+                            content=event.content,
+                            tool_use_id=event.metadata.get("tool_use_id", ""),
+                            tool_name=event.metadata.get("tool_name", ""),
+                            is_error=bool(event.metadata.get("is_error")),
+                        )
                     elif event.type == "provider_limit":
                         terminal_limit |= event.metadata.get("status") == "rejected"
                         self._handle_event(event)
                     elif event.type == "error":
                         summary_error = event.content or "provider error during compact"
                     elif event.type == "turn_end":
                         summary_turn = event
                         if event.metadata.get("session_id"):
                             self.session_id = event.metadata["session_id"]
                         self._cost.apply_turn_result(event.metadata, event.usage)
+                        compact_cost += self._turn_cost
                         self._last_turn_api_calls = max(
                             1, int(event.metadata.get("num_turns") or 1),
                         )
                         break
             except QuotaGateError:
                 abort_compact("weekly quota blocked compact summary", flush_pending=False)
                 raise
             except Exception as e:
                 last_error = str(e)
                 self._log("error", f"compact attempt {attempt}/{COMPACT_MAX_RETRIES} failed: {e}")
                 try:
                     await backend.disconnect()
                 except Exception:
                     pass
                 self._backend = None
                 if _is_terminal_compact_error(last_error):
                     # Пропавший каталог не заводится от ожидания: 27 из 38 ошибок
                     # компакта в базе — это 9 воркеров, каждый отретраенный трижды
                     # с бэкоффом 30 и 60 секунд.
                     return abort_compact(last_error)
@@ -2967,47 +3040,59 @@ class AgentSession:
             elif summary_turn is None:
                 last_error = "compact stream ended without turn_end"
             elif summary_turn.metadata.get("ok") is not True:
                 last_error = summary_error or "compact summary turn failed"
             elif summary_error:
                 last_error = summary_error
             elif not summary:
                 last_error = "empty summary"
             else:
                 last_error = ""
 
             if last_error:
                 self._log("error", f"compact attempt {attempt}/{COMPACT_MAX_RETRIES}: {last_error}")
                 self.session_id = pre_compact_session_id
                 if not terminal_limit and attempt < COMPACT_MAX_RETRIES:
                     self._log("status", f"compact retry in {COMPACT_RETRY_DELAY * attempt}s...")
                     await asyncio.sleep(COMPACT_RETRY_DELAY * attempt)
                     continue
                 return abort_compact(last_error)
 
+            self._log_compact_event(
+                compact_id,
+                action="step_done",
+                phase="draft",
+                summary=summary,
+                **({"cost_usd": round(compact_cost, 6)} if compact_cost else {}),
+            )
+
             if attempt > 1:
                 self._log("status", f"compact succeeded on attempt {attempt}")
             break
 
+        audit_fallback = False
         if keep_backend_open:
             try:
-                summary = await self._agentic_audit_summary(summary, compact_stop_gen, backend)
+                summary, audit_fallback, audit_cost = await self._agentic_audit_summary(
+                    summary, compact_stop_gen, backend, compact_id,
+                )
+                compact_cost += audit_cost
             finally:
                 try:
                     await backend.disconnect()
                 except Exception:
                     logger.warning("[%s] backend disconnect failed after compact audit", self.name)
                 self._backend = None
         if self._turn_start_cancel_gen != compact_stop_gen:
             return abort_compact("compaction cancelled by stop", flush_pending=False)
         tail = _preserved_tail(
             self.id,
             COMPACT_TAIL_CHARS,
             exclude_user_messages=tuple(self._pending_messages),
         )
         preamble = PREAMBLE.format(
             summary=summary,
             tail=(
                 f"\n[VERBATIM TAIL — last messages before compaction, unabridged]\n\n"
                 f"{tail}\n\n[END OF TAIL]\n"
                 if tail else ""
             ),
@@ -3118,40 +3203,53 @@ class AgentSession:
         self._persist()
         await self._drain_persist()
         if LOG_COMPACT_SUMMARY:
             self._log(
                 "text",
                 f"📋 **Compact summary:**\n\n{summary}",
                 provenance=MessageProvenance(
                     origin="platform", senders=("Orchestra",),
                     subtype="compact_summary",
                 ),
             )
         # Расход ack-хода — СУММА по всем его обращениям к модели. 23.09 у katya-work ход из
         # 4 обращений по ~77 тыс. дал «post 307564» и «20% → 31%», хотя контекст ужался в 2.6 раза.
         ack_calls = max(1, getattr(self, "_last_turn_api_calls", 1))
         post_tokens = max(0, self._context_token_total() - tokens_before_ack) // ack_calls
         if post_tokens and max_tokens:
             after_pct = round(post_tokens * 100 / max_tokens)
         else:
             after_pct = self._last_context.get("percentage", 0)
         dropped = max(0, pre_tokens - post_tokens)
+        self._log_compact_event(
+            compact_id,
+            action="finish",
+            status="fallback_draft" if keep_backend_open and audit_fallback else "complete",
+            before_pct=before_pct,
+            after_pct=after_pct,
+            pre_tokens=pre_tokens,
+            post_tokens=post_tokens,
+            dropped_tokens=dropped,
+            summary=summary,
+            seconds=round(time.monotonic() - compact_started, 1),
+            **({"cost_usd": round(compact_cost, 6)} if compact_cost else {}),
+        )
         self._log(
             "status",
             f"compact done: {before_pct}% → {after_pct}% "
             f"(pre {pre_tokens} → post {post_tokens} tokens, dropped {dropped}, "
             f"summary {len(summary)} chars)",
         )
         return {
             "ok": True, "before_pct": before_pct, "after_pct": after_pct,
             "pre_tokens": pre_tokens, "post_tokens": post_tokens,
             "dropped_tokens": dropped,
             "summary_chars": len(summary), "summary": summary,
         }
 
     async def commit_archive(
         self,
         *,
         project_id: str,
         archive_id: str,
         idempotency_key: str,
         retention: str,
diff --git a/app/static/js/app.js b/app/static/js/app.js
index f1c40ae3c..6e17ca849 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2490,66 +2490,68 @@ async function onOrchestratorChange() {
     saveDraft();
     _captureChatReadFrontier();
     if (eventSource) { eventSource.close(); eventSource = null; }
     if (_chatLoadController) _chatLoadController.abort();
     _chatSnapshotReady = false;
     const picker = $('#orch-picker');
     const opt = picker.selectedOptions[0];
     currentScope = picker.value || null;
     window.OrchestraOwnerActivity?.setScope(currentScope);
     // V-621: чипы тегов другого оркестратора не должны пережить переключение scope.
     _taskTagFilter.clear();
     const restoreUnreadAnchor = _unreadTabs.delete(currentScope);
     chatLogs = {};
     currentSessions = [];
     resetChatTransientState();
     selectedAgent = opt?.dataset?.name || null;
     if (currentScope && selectedAgent) {
         localStorage.setItem('lastOrchScope', currentScope);
         localStorage.setItem('lastOrchName', selectedAgent);
     }
+    resetCompactEventCards();
     $('#chat').innerHTML = '';
     $('#agent-list')?.replaceChildren();
     _prepareChatAnchorRestore(restoreUnreadAnchor);
     updateAgentInfo(null);
     updateInputState();
     restoreDraft();
     refreshQueuedMessages();
     // История и поток идут первыми и не ждут refreshSessions: тому нужно два круга
     // (sessions+stats, затем orchestrators), а нам для показа чата не нужно ни одного (D2).
     _showChatFor(selectedAgent, currentScope);
     refreshSessions();
     initFilePanel();
     if (_tasksTabActive) loadTasks();
     if (_jobsTabActive) loadJobs();
 }
 
 // === Agent Selection ===
 async function selectAgent(name) {
     if (name === selectedAgent && (_chatSnapshotReady || _chatLoading)) return;
     saveDraft();
     _captureChatReadFrontier();
     if (eventSource) { eventSource.close(); eventSource = null; }
     resetChatTransientState();
     selectedAgent = name;
     _hideRateLimitBanner();
     _showChatDropError('');
+    resetCompactEventCards();
     $('#chat').innerHTML = '';
     _prepareChatAnchorRestore(false);
     updateInputState();
     restoreDraft();
     refreshQueuedMessages();
     const hadContext = Boolean(contextCache[`${currentScope}:${name}`]);
     renderAgentList(currentSessions);
     if (hadContext) fetchAgentContext(name);
     await _showChatFor(name, currentScope);
 }
 
 function updateInputState() {
     const input = $('#chat-input');
     const btn = $('#send-btn');
     const afterTurnBtn = $('#send-after-turn-btn');
     if (!selectedAgent) {
         input.placeholder = 'Message...';
         input.disabled = false;
         btn.disabled = false;
         if (afterTurnBtn) afterTurnBtn.disabled = false;
diff --git a/app/static/js/chat.js b/app/static/js/chat.js
index 32d35fced..9cc7605c6 100644
--- a/app/static/js/chat.js
+++ b/app/static/js/chat.js
@@ -1941,40 +1941,41 @@ function _renderCompactToolEntry(type, content, ts, payload, chat, anchor, inser
     if (!window.compactMode || (type !== 'tool' && type !== 'tool_result')) return false;
     if (type === 'tool_result') {
         const card = _toolForResult(chat, payload, anchor, true);
         if (card) {
             _updateCompactToolResult(card, content, isBase64Image);
             return true;
         }
     }
 
     const line = buildCompactToolLine(type, content, ts, payload);
     insertAndFollow(line, () => {
         _trimChatNodes(chat);
         if (type === 'tool') _adoptOrphanResults(chat, line.dataset.toolUseId);
     });
     return true;
 }
 
 function _renderStatusEntry(type, content, ts, anchor, insertAndFollow, payload) {
     if (type !== 'status') return false;
     if (payload?.status_hidden === true) return true;
+    if (/^(?:compact started \(context |compact done:|agentic compact )/i.test(content || '')) return true;
     // A status row may beat the authoritative `text` row through async logging.
     // Never finalize streamBubble here or the later text becomes a duplicate answer.
     if (content?.startsWith('precompact timer')) return true;
     if (/^codex hook .+: (?:running|started|completed)(?: · \d+ms)?$/i.test(content || '')) return true;
     if (/^codex mcp .+: (?:starting|ready)$/i.test(content || '')) return true;
     if (/^compact started \(native Codex,/i.test(content || '')) return true;
 
     if (/^grok mcp ready\b/i.test(content || '')) {
         const badge = document.createElement('div');
         badge.className = 'text-center text-xs py-1 text-emerald-400 italic';
         badge.dataset.i18nSkip = '1';  // строка приходит готовой с сервера
         badge.textContent = `🔌 ${content}`;
         addTimestamp(badge, ts);
         insertAndFollow(badge);
         return true;
     }
 
     const nativeCodexCompact = (content || '').match(
         /^compact done \(native Codex\):\s*(\d+)%\s*→\s*(\d+)%/i
     );
@@ -3932,77 +3933,296 @@ function _renderFullToolResult(content, ts, payload, anchor, div, _insertAndFoll
 
 // Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
 // anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
 // payload = full SSE log object (carries subagent_id for sub-agent nesting)
 // The header already names the sender, so the agent-facing "[from:X]" prefix is dropped,
 // and an auto-report's English service header and "[tool] ..." echo lines are replaced by
 // one localized line (V-636: they were the only English text in the stand's chat).
 function _agentMessageDisplay(text, subtype) {
     const out = text.replace(/^\[from:[^\]]+\]\s*/, '');
     if (subtype !== 'auto_report') return out;
     const m = out.match(/^\[auto-report\](?: \(stop_reason=[^)]*\))? (Finished without explicit report|Turn failed before an explicit report)\. Last output:\n?/);
     if (!m) return out;
     const head = m[1].startsWith('Finished')
         ? T('Worker finished its turn without a separate report. Last output:')
         : T('Worker turn failed before a report. Last output:');
     const rest = out.slice(m[0].length).split('\n').filter(line => !line.startsWith('[tool] '))
         .map(line => line === '(no output)' ? T('(no output)') : line).join('\n');
     return `${head}\n\n${rest}`;
 }
 
+const _compactEventCards = new Map();
+
+function resetCompactEventCards() {
+    _compactEventCards.clear();
+}
+
+function _addCompactFullOutputButton(target, row, compactId, chat) {
+    if (!row.content_truncated_bytes || !row._log_id) return;
+    const button = document.createElement('button');
+    button.type = 'button';
+    button.className = 'ml-2 text-xs text-sky-400 hover:text-sky-300';
+    button.textContent = T('load full');
+    button.addEventListener('click', async () => {
+        button.disabled = true;
+        button.textContent = T('loading…');
+        try {
+            const full = await api(`/api/logs/${row._log_id}`);
+            _renderCompactEvent('compact_event', full.content, full.ts, null,
+                element => element, {...full, event_id: compactId}, chat);
+        } catch (error) {
+            button.disabled = false;
+            button.textContent = T('failed ({name}) — try again', {name: error.name});
+        }
+    });
+    target.appendChild(button);
+}
+
+function _renderCompactEvent(type, content, ts, anchor, insertAndFollow, payload, chat) {
+    if (type !== 'compact_event') return false;
+    let event;
+    try { event = JSON.parse(content); } catch { return true; }
+    const compactId = payload?.event_id;
+    if (!compactId || !event || typeof event !== 'object') return true;
+    let state = _compactEventCards.get(compactId);
+    if (!state) {
+        const card = document.createElement('details');
+        card.className = 'compact-event-card mx-2 my-2 rounded-lg border border-violet-500/40 bg-slate-900/70 text-sm';
+        card.dataset.compactId = compactId;
+        const heading = document.createElement('summary');
+        heading.className = 'cursor-pointer list-none px-3 py-2 font-semibold text-violet-200';
+        card.appendChild(heading);
+        const body = document.createElement('div');
+        body.className = 'space-y-2 px-3 pb-3';
+        card.appendChild(body);
+        insertAndFollow(card);
+        state = {card, heading, body, events: new Map(), openPhases: new Set()};
+        _compactEventCards.set(compactId, state);
+    }
+    if (payload?.id != null) {
+        event._log_id = Number(payload.id);
+        state.events.set(Number(payload.id), event);
+    }
+    else state.events.set(`${Date.now()}-${Math.random()}`, event);
+
+    const entries = [...state.events.entries()].sort((a, b) => {
+        if (typeof a[0] === 'number' && typeof b[0] === 'number') return a[0] - b[0];
+        return String(a[0]).localeCompare(String(b[0]));
+    }).map(([, value]) => value);
+    const finish = [...entries].reverse().find(item => item.action === 'finish');
+    const started = entries.find(item => item.action === 'start') || {};
+    const status = finish?.status === 'complete' ? T('Ready')
+        : finish?.status === 'fallback_draft' ? T('Draft restored')
+        : finish ? T('Rolled back') : T('In progress');
+    const percent = started.before_pct == null ? '' : ` · ${started.before_pct}%`;
+    state.heading.textContent = `${T('Context compaction')}: ${status}${percent}`;
+
+    const opened = new Set([...state.body.querySelectorAll('details[open]')]
+        .map(node => node.dataset.phase).filter(Boolean));
+    state.body.replaceChildren();
+    const phases = ['draft', 'audit', 'final'];
+    const labels = {draft: T('Draft summary'), audit: 'AUDIT', final: 'FINAL'};
+    const descriptions = {
+        draft: T('Builds a working summary from the session journal.'),
+        audit: T('Checks the draft against the journal and identifies omissions.'),
+        final: T('Writes the reviewed summary used to continue the session.'),
+    };
+    for (const phase of phases) {
+        const rows = entries.filter(item => item.phase === phase
+            || (phase === 'draft' && item.action === 'start'));
+        if (!rows.length) continue;
+        const details = document.createElement('details');
+        details.dataset.phase = phase;
+        details.open = opened.has(phase) || state.openPhases.has(phase);
+        details.addEventListener('toggle', () => {
+            if (details.open) state.openPhases.add(phase);
+            else state.openPhases.delete(phase);
+        });
+        details.className = 'rounded border border-slate-700 px-2 py-1';
+        const summary = document.createElement('summary');
+        summary.className = 'cursor-pointer font-medium';
+        const done = rows.some(item => item.action === 'step_done');
+        const failed = rows.some(item => item.action === 'step_failed');
+        summary.textContent = `${labels[phase]} · ${failed ? T('Failed') : done ? T('Ready') : T('In progress')}`;
+        details.appendChild(summary);
+        const description = document.createElement('p');
+        description.className = 'my-1 text-xs text-slate-400';
+        description.textContent = descriptions[phase];
+        details.appendChild(description);
+
+        const calls = new Map();
+        for (const row of rows.filter(item => item.action === 'tool')) {
+            const key = row.tool_use_id || `row-${entries.indexOf(row)}`;
+            const pair = calls.get(key) || {call: null, result: null};
+            pair[row.kind === 'tool_result' ? 'result' : 'call'] = row;
+            calls.set(key, pair);
+        }
+        for (const pair of calls.values()) {
+            const tool = document.createElement('details');
+            tool.className = 'ml-2 rounded bg-slate-950/70 px-2 py-1';
+            const toolSummary = document.createElement('summary');
+            toolSummary.className = 'cursor-pointer text-xs';
+            const name = pair.call?.tool_name || pair.result?.tool_name || T('Tool');
+            const marker = pair.call && pair.result ? '✓' : pair.call ? '…' : '↳';
+            toolSummary.textContent = `${marker} ${name}`;
+            tool.appendChild(toolSummary);
+            for (const [label, row] of [[T('Call'), pair.call], [T('Result'), pair.result]]) {
+                if (!row) continue;
+                const title = document.createElement('div');
+                title.className = 'mt-1 text-xs text-slate-400';
+                title.textContent = label;
+                const text = document.createElement('pre');
+                text.className = 'max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs';
+                text.textContent = row.content || '';
+                tool.append(title, text);
+                if (row.content_truncated_bytes) {
+                    const clipped = document.createElement('p');
+                    clipped.className = 'text-xs text-slate-500';
+                    clipped.textContent = T('Output shortened for display ({n} source bytes)', {
+                        n: row.content_truncated_bytes,
+                    });
+                    tool.appendChild(clipped);
+                    _addCompactFullOutputButton(tool, row, compactId, chat);
+                }
+            }
+            details.appendChild(tool);
+        }
+        for (const row of rows.filter(item => ['step_done', 'step_failed'].includes(item.action))) {
+            if (row.summary) {
+                const finalSummary = document.createElement('pre');
+                finalSummary.className = 'max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950/70 p-2 text-xs';
+                finalSummary.textContent = row.summary;
+                details.appendChild(finalSummary);
+                if (row.content_truncated_bytes) {
+                    const clipped = document.createElement('p');
+                    clipped.className = 'text-xs text-slate-500';
+                    clipped.textContent = T('Output shortened for display ({n} source bytes)', {
+                        n: row.content_truncated_bytes,
+                    });
+                    details.appendChild(clipped);
+                    _addCompactFullOutputButton(details, row, compactId, chat);
+                }
+            }
+            if (row.error) {
+                const error = document.createElement('p');
+                error.className = 'text-xs text-amber-300';
+                error.textContent = `${T('Fallback')}: ${row.error}`;
+                details.appendChild(error);
+            }
+            const metrics = [];
+            if (Number.isFinite(row.seconds)) metrics.push(`${row.seconds}s`);
+            if (Number.isFinite(row.cost_usd)) metrics.push(`$${row.cost_usd.toFixed(2)}`);
+            if (metrics.length) {
+                const metricLine = document.createElement('p');
+                metricLine.className = 'text-xs text-slate-400';
+                metricLine.textContent = metrics.join(' · ');
+                details.appendChild(metricLine);
+            }
+        }
+        state.body.appendChild(details);
+    }
+    if (finish) {
+        const metrics = [];
+        if (finish.before_pct != null && finish.after_pct != null)
+            metrics.push(`${T('Context')}: ${finish.before_pct}% → ${finish.after_pct}%`);
+        if (finish.pre_tokens != null && finish.post_tokens != null)
+            metrics.push(`${finish.pre_tokens.toLocaleString()} → ${finish.post_tokens.toLocaleString()} tokens`);
+        if (Number.isFinite(finish.seconds)) metrics.push(`${finish.seconds}s`);
+        if (Number.isFinite(finish.cost_usd)) metrics.push(`$${finish.cost_usd.toFixed(2)}`);
+        if (metrics.length) {
+            const footer = document.createElement('p');
+            footer.className = 'border-t border-slate-700 pt-2 text-xs text-slate-400';
+            footer.textContent = metrics.join(' · ');
+            state.body.appendChild(footer);
+        }
+        if (finish.error) {
+            const error = document.createElement('p');
+            error.className = 'text-xs text-amber-300';
+            error.textContent = finish.error;
+            state.body.appendChild(error);
+        }
+        if (finish.summary) {
+            const final = document.createElement('details');
+            final.className = 'rounded border border-violet-500/30 px-2 py-1';
+            const title = document.createElement('summary');
+            title.className = 'cursor-pointer';
+            title.textContent = T('Final summary');
+            const summaryText = document.createElement('pre');
+            summaryText.className = 'mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs';
+            summaryText.textContent = finish.summary;
+            final.append(title, summaryText);
+            if (finish.content_truncated_bytes) {
+                const clipped = document.createElement('p');
+                clipped.className = 'text-xs text-slate-500';
+                clipped.textContent = T('Output shortened for display ({n} source bytes)', {
+                    n: finish.content_truncated_bytes,
+                });
+                final.appendChild(clipped);
+                const finishRow = [...state.events.entries()].find(([, row]) => row.action === 'finish')?.[1];
+                _addCompactFullOutputButton(final, finishRow || finish, compactId, chat);
+            }
+            state.body.appendChild(final);
+        }
+    }
+    return true;
+}
+
 function addChatEntry(type, content, ts, anchor, payload) {
     if (type === 'provider_limit') return; // Runtime telemetry; the status/error row carries the user notice.
     if (type === 'done_gate_verdict') return; // V-614 shadow-only bookkeeping, not a chat event.
+    if (type === 'error' && /^compact attempt \d+\/\d+ failed:/.test(content || '')) return;
     if (_isSilentTurnMarker(type, content)) return;
     if (HIDE_THINKING && (type === 'thinking' || type === 'thinking_stream')) return;
     // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
     if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
         appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
         return;
     }
     if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
     const chat = $('#chat');
     let _insertedBeforeStream = false;
     const _insert = (el) => {
         _tagChatTimelineNode(el, type, ts);
         _stampChatLogNode(el, payload);
-        if (payload && payload.trunc) _attachTruncNotice(el, payload, type, ts);
+        if (payload && payload.trunc && type !== 'compact_event') _attachTruncNotice(el, payload, type, ts);
         if (anchor) return chat.insertBefore(el, anchor);
         const wasAtBottom = _chatAtBottom(chat);
         let inserted;
         if (streamBubble && streamBubble.parentNode === chat) {
             _insertedBeforeStream = true;
             inserted = chat.insertBefore(el, streamBubble);
         } else {
             inserted = chat.appendChild(el);
         }
         if (!scrollAfterLoad && !wasAtBottom) _markChatHasNewBelow();
         return inserted;
     };
     const _insertAndFollow = (el, afterInsert) => {
         const wasAtBottom = _chatAtBottom(chat);
         const inserted = _insert(el);
         if (afterInsert) afterInsert(inserted);
         if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return inserted;
     };
 
+    if (_renderCompactEvent(type, content, ts, anchor, _insertAndFollow, payload, chat)) return;
+
     // Heuristic: detect base64 image payloads from tool results (e.g. screenshot tools)
     const _isBase64Image = content.includes("'type': 'image'") || content.includes('"type": "image"') || content.includes('"type":"image"') || /['"]?data['"]?\s*[:=]\s*['"][A-Za-z0-9+/=\s]{500,}['"]/.test(content);
 
     if (type === 'thinking_stream') {
         const activity = (payload && payload.activity) || 'reasoning';
         const key = `${activity}:${(payload && payload.item_id) || ''}`;
         if (!_codexThinkingLive || _codexThinkingKey !== key) {
             _removeCodexThinkingLive();
             _codexThinkingLive = document.createElement('div');
             _codexThinkingLive.className = 'codex-activity-card codex-thinking-live';
             _codexThinkingLive.dataset.activity = activity;
             const label = document.createElement('div');
             label.className = 'codex-live-label';
             label.textContent = activity === 'plan'
                 ? T('▦ Planning live')
                 : activity === 'waiting'
                     ? T('⌁ Codex still working')
                     : T('◇ Reasoning live');
             const body = document.createElement('div');
             body.className = 'codex-live-thinking-body';
diff --git a/app/static/js/i18n.js b/app/static/js/i18n.js
index 15f354a4c..4ebaf5fc9 100644
--- a/app/static/js/i18n.js
+++ b/app/static/js/i18n.js
@@ -92,40 +92,56 @@
     'Close analytics': 'Закрыть аналитику',
     'Codex cache state unknown · {past} past the ≈{ttl}m reference window; actual ChatGPT TTL is not guaranteed': 'Состояние кеша Codex неизвестно · {past} сверх справочного окна ≈{ttl} мин; фактический TTL ChatGPT не гарантирован',
     'Codex cache ≈{rem}m within a {ttl}m reference window; actual ChatGPT TTL is not guaranteed': 'Кеш Codex ≈{rem} мин в справочном окне {ttl} мин; фактический TTL ChatGPT не гарантирован',
     'Codex context compacted natively': 'Контекст Codex уплотнён штатно',
     'Codex model rerouted': 'Модель Codex переключена',
     'Codex reconnecting': 'Codex переподключается',
     'Cold starts': 'Холодные старты',
     'Collapse': 'Свернуть',
     'Compact': 'Уплотнить',
     'Compact context': 'Уплотнить контекст',
     'Completed': 'Завершено',
     'Connection restored': 'Связь восстановлена',
     'Connection restored · data updated': 'Связь восстановлена · данные обновлены',
     'Connection unstable': 'Связь нестабильна',
     'Context': 'Контекст',
     'Cost': 'Стоимость',
     'Cost / priced turn': 'Стоимость платного хода',
     'Count source': 'Источник счёта',
     'Coverage': 'Покрытие',
     'Create Orchestrator': 'Создать оркестратора',
+    'Builds a working summary from the session journal.': 'Собирает черновую сводку по журналу сессии.',
+    'Checks the draft against the journal and identifies omissions.': 'Сверяет черновик с журналом и ищет пропуски.',
+    'Writes the reviewed summary used to continue the session.': 'Записывает проверенную сводку для продолжения сессии.',
+    'Call': 'Вызов',
+    'Context': 'Контекст',
+    'Context compaction': 'Сжатие контекста',
+    'Draft restored': 'Откат на черновик',
+    'Draft summary': 'Черновик',
+    'Fallback': 'Откат',
+    'Final summary': 'Итоговая сводка',
+    'In progress': 'Идёт',
+    'Ready': 'Готово',
+    'Result': 'Результат',
+    'Rolled back': 'Откат',
+    'Tool': 'Инструмент',
+    'Output shortened for display ({n} source bytes)': 'Показана часть вывода (исходный размер: {n} байт)',
     'Created': 'Создано',
     'Created:': 'Создана:',
     'Creating...': 'Создание…',
     'Critical': 'Критический',
     'Current turn': 'Текущий ход',
     'DESCRIPTION': 'ОПИСАНИЕ',
     'DONE': 'ГОТОВО',
     'Daily': 'Сутки',
     'Data unavailable': 'Данные недоступны',
     'Delegation': 'Делегирование',
     'Delete': 'Удалить',
     'Delete "{name}" and all its workers?': 'Удалить «{name}» и всех его воркеров?',
     'Delete Orchestrator': 'Удалить оркестратор',
     'Delete file': 'Удалить файл',
     'Desc': 'Описание',
     'Deviation': 'Отклонение',
     'Dispatcher': 'Диспетчер',
     'Done:': 'Завершена:',
     'Download file': 'Скачать файл',
     'Drawing': 'Рисует',
diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 18f6b74c4..179959d82 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -3455,40 +3455,50 @@ async def stream_logs(orch_name: str, thread_id: int):
     # Так же вне хода: якорь обнуляет состояние, а откат курсора переигрывает вызовы.
     _sent_messages: set[int] = set()
     # None — ни явного notify call, ни durable attention result в ходе не было.
     # Строка — есть хотя бы один из сигналов; explicit call остаётся fallback при сбое БД.
     _notify_reason = None
     _pending_turn_end_mention = False
     _idle_ticks = 0
     current_log_previous_id = last_id
 
     try:
         while True:
             try:
                 logs = get_logs(session_id, after_id=last_id, conn=_poll_conn)
                 _idle_ticks = 0 if logs else _idle_ticks + 1
                 for log in logs:
                     if log["id"] <= last_id:
                         continue
                     current_log_previous_id = last_id
                     last_id = log["id"]
                     t, c = log["type"], log["content"]
+                    if t == "compact_event" or (
+                        t == "status" and c.startswith((
+                            "compact started (context ",
+                            "compact done:",
+                            "agentic compact ",
+                        ))
+                    ) or (
+                        t == "error" and c.startswith("compact attempt ")
+                    ):
+                        continue
                     is_anchor = False
                     if t in ("text", "tool"):
                         _schedule_topic_status(orch_name, True)
                     if t == "user_message":
                         await _update_progress(turn, thread_id, orch_name, force=True)
                         turn.new_block()
                         c = user_message_display_content(log)
                         img_match = re.search(r'(/\S+\.(?:png|jpg|jpeg|gif|webp))', c, re.IGNORECASE)
                         if img_match and Path(img_match.group(1)).is_file():
                             img_path = img_match.group(1)
                             caption = c.replace(img_path, '').strip()[:1024] or None
                             try:
                                 await _tg_send_file_safe(
                                     config["group_id"], img_path, caption, thread_id,
                                     is_photo=True, important=True,
                                 )
                                 mirror = config.get("mirrors", {}).get(orch_name)
                                 if mirror and mirror.get("chat_id"):
                                     await _mirror_send_file(
                                         orch_name, img_path, caption, True,
diff --git a/tests/test_agentic_compact_650.py b/tests/test_agentic_compact_650.py
index d993095ca..1eb8c1faa 100644
--- a/tests/test_agentic_compact_650.py
+++ b/tests/test_agentic_compact_650.py
@@ -46,95 +46,120 @@ class _Backend:
         pass
 
     async def disconnect(self):
         self.disconnected = True
 
     async def interrupt(self):
         pass
 
     async def send(self, message):
         self.sent.append(message)
 
     async def events(self):
         from app.events import AgentEvent
 
         self.event_streams += 1
         next_prompt = max(0, len(self.sent) - 1)
         while next_prompt < len(self.sent):
             prompt = self.sent[next_prompt]
             next_prompt += 1
             if "[SYSTEM: Context compaction requested" in prompt:
+                yield AgentEvent(type="tool", content="Read: {\"path\":\"journal\"}", metadata={
+                    "tool_use_id": "draft-read", "tool_name": "Read",
+                })
+                yield AgentEvent(type="tool_result", content="draft journal excerpt", metadata={
+                    "tool_use_id": "draft-read", "tool_name": "Read",
+                })
                 yield AgentEvent(type="text", content=DRAFT)
                 yield AgentEvent(type="turn_end", metadata={
                     "ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "session_id": "same-session", "cost_usd": 0.1,
                 })
             elif "pass 1 — AUDIT" in prompt:
                 if self.mode == "fail":
                     yield AgentEvent(type="error", content="audit exploded")
                     return
                 if self.mode in ("limit_warning", "limit_rejected"):
                     status = "allowed_warning" if self.mode == "limit_warning" else "rejected"
                     yield AgentEvent(type="provider_limit", metadata={
                         "status": status, "rate_limit_type": "seven_day",
                     })
                 if self.on_audit_end:
                     self.on_audit_end()
+                yield AgentEvent(type="tool", content="Grep: {\"pattern\":\"omission\"}", metadata={
+                    "tool_use_id": "audit-grep", "tool_name": "Grep",
+                })
+                yield AgentEvent(type="tool_result", content="audit findings", metadata={
+                    "tool_use_id": "audit-grep", "tool_name": "Grep",
+                })
                 yield AgentEvent(type="text", content="AUDIT INTERNAL TEXT")
                 yield AgentEvent(type="turn_end", metadata={
                     "ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "session_id": "same-session", "cost_usd": 0.3,
                 })
             elif "last pass — FINALIZE" in prompt:
                 match = re.search(r"journal is in (.+?): INDEX", prompt)
                 assert match
                 final = "" if self.mode == "empty" else "x" * 30 if self.mode == "long" else FINAL
                 (self.root / match.group(1)).parent.joinpath("summary.md").write_text(final)
+                yield AgentEvent(type="tool", content="Edit: summary.md", metadata={
+                    "tool_use_id": "final-edit", "tool_name": "Edit",
+                })
+                yield AgentEvent(type="tool_result", content="summary written", metadata={
+                    "tool_use_id": "final-edit", "tool_name": "Edit",
+                })
                 yield AgentEvent(type="text", content="FINAL INTERNAL TEXT")
                 yield AgentEvent(type="turn_end", metadata={
                     "ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "session_id": "same-session", "cost_usd": 0.6,
                 })
             else:
                 raise AssertionError(f"unexpected backend prompt: {prompt[:100]}")
 
 
 def _compact(tmp_path, monkeypatch, *, mode="ok", enabled="1", stop_between=False):
     from app.session import AgentSession
 
     monkeypatch.setenv("AGENTIC_COMPACT_ENABLED", enabled)
     monkeypatch.setenv("AGENTIC_COMPACT_TIMEOUT", "0" if mode == "timeout" else "5")
     monkeypatch.setenv("AGENTIC_COMPACT_MAX_CHARS", "10" if mode == "long" else "25000")
     monkeypatch.setattr("app.session.save_session", MagicMock())
     monkeypatch.setattr("app.session._claude_subscription_limit_active", lambda: False)
     monkeypatch.setattr("app.session._preserved_tail", lambda *a, **k: "")
     monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
     monkeypatch.setattr("app.bg_jobs.bg_manager", None)
     audit_root = tmp_path / "data" / "compact-sandbox"
     monkeypatch.setattr(agentic_compact, "sandbox_root", lambda: audit_root)
     logs = []
     session = AgentSession(
         id="s-650", name="w650", scope=str(tmp_path), cwd=str(tmp_path),
         model="claude-opus-5[1m]", system_prompt="role",
         created_at=datetime.now(timezone.utc),
     )
-    session._log = lambda kind, content, **kwargs: logs.append((kind, content))
+    compact_events = []
+    def capture_log(kind, content, **kwargs):
+        logs.append((kind, content))
+        if kind == "compact_event":
+            compact_events.append({**json.loads(content), "event_id": kwargs.get("event_id"),
+                                   "tool_use_id": kwargs.get("tool_use_id")})
+    session._log = capture_log
+    session._compact_log_events = compact_events
     session._persist = lambda: None
     session._drain_persist = lambda: asyncio.sleep(0)
     session._wake_durable_message_deliveries = lambda: None
     backend = _Backend(
         tmp_path, mode=mode,
         on_audit_end=(lambda: setattr(session, "_turn_start_cancel_gen", 1))
         if stop_between else None,
     )
 
     async def prepare_journal(session_id, directory):
         journal = directory / "journal"
         journal.mkdir()
         return journal
 
     monkeypatch.setattr(agentic_compact, "prepare_journal", prepare_journal)
 
     async def ensure_backend(force_fresh=False):
         session._backend = backend
         if session._compact_ack_event:
             asyncio.get_running_loop().call_soon(session._compact_ack_event.set)
@@ -146,40 +171,52 @@ def _compact(tmp_path, monkeypatch, *, mode="ok", enabled="1", stop_between=Fals
             return await session.compact()
 
     result = asyncio.run(run())
     ack = next((prompt for prompt in backend.sent if "Acknowledge briefly." in prompt), "")
     return session, result, backend, logs, ack
 
 
 def test_final_replaces_draft_in_ack_and_pass_cost_is_accounted(tmp_path, monkeypatch):
     session, result, backend, logs, ack = _compact(tmp_path, monkeypatch)
 
     assert result["ok"] is True
     assert len([p for p in backend.sent if "pass 1 — AUDIT" in p]) == 1
     assert len([p for p in backend.sent if "last pass — FINALIZE" in p]) == 1
     assert "FINAL summary" in ack and "draft summary" not in ack
     assert backend.event_streams == 2  # draft stream plus one stream shared by AUDIT and FINAL
     assert session.cost_usd == 0.6
     assert any(content.startswith("agentic compact context summary (replaced):") for _, content in logs)
     assert any(f"summary {len(DRAFT)} → {len(FINAL)} chars" in content for _, content in logs)
     assert not any(kind == "text" and "FINAL summary" in content for kind, content in logs)
     assert not any(kind == "text" and "INTERNAL TEXT" in content for kind, content in logs)
+    assert not any(kind in {"tool", "tool_result"} for kind, _ in logs)
+    compact_rows = session._compact_log_events
+    assert {row.get("phase") for row in compact_rows if row.get("action") == "tool"} == {
+        "draft", "audit", "final",
+    }
+    tool_rows = [row for row in compact_rows if row.get("action") == "tool"]
+    assert len(tool_rows) == 6
+    assert all(row["event_id"] == compact_rows[0]["event_id"] for row in compact_rows)
+    assert {row["tool_use_id"] for row in tool_rows} == {
+        "draft-read", "audit-grep", "final-edit",
+    }
+    assert next(row for row in compact_rows if row.get("action") == "finish")["status"] == "complete"
     audit_root = tmp_path / "data" / "compact-sandbox"
     assert str(audit_root) in next(p for p in backend.sent if "pass 1 — AUDIT" in p)
     assert list(audit_root.iterdir()) == []
 
 
 def test_audit_failure_uses_draft_and_logs_reason(tmp_path, monkeypatch):
     session, result, backend, logs, ack = _compact(tmp_path, monkeypatch, mode="fail")
 
     assert result["ok"] is True
     assert "draft summary" in ack and "FINAL summary" not in ack
     assert not any("last pass — FINALIZE" in prompt for prompt in backend.sent)
     assert any("agentic compact audit skipped" in content and "audit exploded" in content
                for _, content in logs)
     assert list((tmp_path / "data" / "compact-sandbox").iterdir()) == []
 
 
 def test_timeout_empty_and_oversized_final_fall_back_to_draft(tmp_path, monkeypatch):
     for mode, reason in (("timeout", "timeout"), ("empty", "empty summary"), ("long", "too long")):
         case_dir = tmp_path / mode
         case_dir.mkdir()
diff --git a/tests/test_compact_chat_672.py b/tests/test_compact_chat_672.py
new file mode 100644
index 000000000..bb8ae78dc
--- /dev/null
+++ b/tests/test_compact_chat_672.py
@@ -0,0 +1,257 @@
+"""V-672 compaction event regression checks, isolated for the merge gate."""
+
+import asyncio
+import json
+from datetime import datetime, timezone
+from pathlib import Path
+
+import pytest
+from playwright.sync_api import Browser, expect
+
+pytest_plugins = (
+    "tests.test_frontend",
+    "tests.test_logs_sync",
+)
+
+from tests.test_frontend import _open_tool_correlation_page
+from tests.test_logs_sync import _session
+
+
+@pytest.fixture
+def tb(tmp_path, monkeypatch):
+    monkeypatch.setattr("app.tg_bridge.CONFIG_PATH", tmp_path / "tg_bridge.json")
+    from app import tg_bridge
+
+    tg_bridge.config = {"group_id": -100123456, "topics": {}, "token": "test"}
+    tg_bridge._topic_status = {}
+    tg_bridge.bot = None
+    tg_bridge._pil_available = None
+    for name, value in {
+        "_tasks": [], "_stream_tasks": {}, "_topic_status_tasks": {},
+        "_topic_status_desired": {}, "_topic_create_tasks": {},
+        "_bridge_tasks": {}, "_mirror_outboxes": {}, "_mirror_tasks": {},
+        "_mirror_dropped": {}, "_mirror_stopping": set(), "_buffers": {},
+        "_tg_delivery_states": {}, "_tg_dispatch_tasks": {},
+        "_tg_queue_loops": {}, "_tg_result_tasks": set(),
+        "_tg_result_wrappers": {}, "_tg_flood_until": {}, "_tg_last_send": {},
+        "_tg_call_sequence": 0,
+    }.items():
+        monkeypatch.setattr(tg_bridge, name, value, raising=False)
+    return tg_bridge
+
+
+async def _run_tg_logs(tb, monkeypatch, rows):
+    class FakeConn:
+        def close(self):
+            pass
+
+    calls = 0
+    sent = []
+    mirrored = []
+
+    def get_logs(_session_id, after_id=0, conn=None):
+        nonlocal calls
+        calls += 1
+        if calls == 1:
+            return []
+        if calls == 2:
+            return rows
+        raise asyncio.CancelledError
+
+    async def no_sleep(_delay):
+        return None
+
+    async def tg_send_safe(_chat_id, text, _thread_id, **_kwargs):
+        sent.append(text)
+
+    async def mirror_send(_orch_name, text, **_kwargs):
+        mirrored.append(text)
+
+    monkeypatch.setattr(tb, "TG_USER_MENTION", "@DrSeedon")
+    monkeypatch.setattr("app.db.get_all_sessions", lambda: [
+        {"name": "orch", "scope": "/scope", "role": "orchestrator"},
+    ])
+    monkeypatch.setattr("app.db.get_session_by_name", lambda *_: {"id": "sid"})
+    monkeypatch.setattr("app.db.get_logs", get_logs)
+    monkeypatch.setattr("app.db._conn", FakeConn)
+    monkeypatch.setattr(tb, "_schedule_topic_status", lambda *_: None)
+    monkeypatch.setattr(tb, "_any_running_in_scope", lambda *_: False)
+    monkeypatch.setattr(tb, "_tg_send_safe", tg_send_safe)
+    monkeypatch.setattr(tb, "_mirror_send", mirror_send)
+    monkeypatch.setattr(tb.asyncio, "sleep", no_sleep)
+
+    with pytest.raises(asyncio.CancelledError):
+        await tb.stream_logs("orch", 42)
+    return sent, mirrored
+
+
+@pytest.mark.asyncio
+async def test_compact_events_and_statuses_do_not_reach_telegram_or_mirror(tb, monkeypatch):
+    sent, mirrored = await _run_tg_logs(tb, monkeypatch, [
+        {"id": 1, "type": "compact_event", "event_id": "compact-1",
+         "content": '{"action":"tool","phase":"audit","kind":"tool_result"}'},
+        {"id": 2, "type": "status", "content": "compact started (context 95%, pre_session=x)"},
+        {"id": 3, "type": "status", "content": "compact done: 95% → 31%"},
+        {"id": 90, "type": "status",
+         "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
+    ])
+
+    assert sent == []
+    assert mirrored == []
+
+
+def test_compact_journal_rows_render_as_one_separate_collapsible_block(
+    dashboard_browser: Browser,
+):
+    fixture_path = Path(__file__).parent.parent / ".orchestra/tasks/V-672/compact-fixture.json"
+    fixture = json.loads(fixture_path.read_text())
+    assert fixture["source"]["legacy_tool_result_rows_without_tool_use_id"] == 34
+    page = _open_tool_correlation_page(dashboard_browser, compact_mode=False)
+    page.evaluate("""fixture => {
+        for (const row of fixture.events) {
+            addChatEntry('compact_event', JSON.stringify(row.content), null, null, {
+                id: row.id,
+                event_id: row.event_id,
+                tool_use_id: row.content.tool_use_id,
+                tool_name: row.content.tool_name,
+                tool_is_error: false,
+            });
+            if (row.id === 4) addChatEntry('text', 'ordinary message stays in the chat flow', null);
+        }
+        const card = document.querySelector('.compact-event-card');
+        return {
+            compactCards: document.querySelectorAll('.compact-event-card').length,
+            orphanResults: document.querySelectorAll('[data-unmatched-tool-result]').length,
+            compactText: card?.innerText || '',
+            ordinaryMessageCount: [...document.querySelectorAll('#chat .chat-bot')]
+                .filter(node => node.innerText.includes('ordinary message stays')).length,
+        };
+    }""", fixture)
+    card = page.locator(".compact-event-card")
+    expect(card).to_contain_text("Context compaction")
+    expect(card).to_contain_text("In progress")
+    card.evaluate("""card => {
+        card.open = true;
+        card.querySelector('details[data-phase="audit"]').open = true;
+        card.querySelector('details[data-phase="audit"] details').open = true;
+    }""")
+    assert card.evaluate("card => card.open && card.querySelector('details[data-phase=\"audit\"]').open")
+    screenshot = Path(__file__).parent.parent / ".orchestra/tasks/V-672/compact-card.png"
+    page.evaluate("""() => {
+        const clone = document.querySelector('.compact-event-card').cloneNode(true);
+        clone.id = 'compact-card-screenshot';
+        clone.style.cssText = 'position:fixed;top:8px;left:8px;width:900px;max-height:none;overflow:visible;z-index:99999;background:#0b1120';
+        document.body.appendChild(clone);
+    }""")
+    page.locator("#compact-card-screenshot").screenshot(path=str(screenshot))
+    page.locator("#compact-card-screenshot").evaluate("node => node.remove()")
+    page.evaluate("""() => {
+        addChatEntry('compact_event', JSON.stringify({
+            action: 'step_done', phase: 'draft', summary: 'Initial draft summary.',
+        }), null, null, {id: 96, event_id: 'fixture-compact'});
+        addChatEntry('compact_event', JSON.stringify({
+            action: 'step_done', phase: 'audit', seconds: 90, cost_usd: 0.47,
+        }), null, null, {id: 97, event_id: 'fixture-compact'});
+        addChatEntry('compact_event', JSON.stringify({
+            action: 'step_done', phase: 'final', seconds: 75, cost_usd: 0.51,
+            summary: 'Reviewed summary for the next session.',
+        }), null, null, {id: 98, event_id: 'fixture-compact'});
+        addChatEntry('compact_event', JSON.stringify({
+            action: 'finish', status: 'complete', before_pct: 95, after_pct: 31,
+            pre_tokens: 190000, post_tokens: 62000, seconds: 217.4,
+            cost_usd: 1.23, summary: 'Reviewed summary for the next session.',
+        }), null, null, {id: 99, event_id: 'fixture-compact'});
+        addChatEntry('compact_event', JSON.stringify({action: 'start', status: 'running', before_pct: 90}),
+            null, null, {id: 100, event_id: 'fixture-fallback'});
+        addChatEntry('compact_event', JSON.stringify({action: 'finish', status: 'fallback_draft',
+            summary: 'Kept draft summary.'}), null, null, {id: 101, event_id: 'fixture-fallback'});
+        window.api = async path => ({
+            id: 7, event_id: 'fixture-compact', type: 'compact_event', ts: null,
+            content: JSON.stringify({action: 'tool', phase: 'audit', kind: 'tool_result',
+                tool_use_id: 'fixture-audit-read', tool_name: 'Read',
+                content: 'FULL_RESULT_AFTER_EXPANSION'}),
+        });
+        addChatEntry('compact_event', JSON.stringify({action: 'tool', phase: 'audit',
+            kind: 'tool_result', tool_use_id: 'fixture-audit-read', tool_name: 'Read',
+            content: 'PARTIAL_RESULT', content_truncated_bytes: 9000}), null, null,
+            {id: 7, event_id: 'fixture-compact'});
+    }""")
+    compact_card = page.locator('.compact-event-card[data-compact-id="fixture-compact"]')
+    compact_card.evaluate("""card => {
+        card.querySelector('details[data-phase="audit"]').open = true;
+        card.querySelector('details[data-phase="audit"] details').open = true;
+        card.querySelector('details[data-phase="final"]').open = true;
+    }""")
+    compact_card.get_by_role("button", name="load full").click()
+    compact_card.evaluate("""card => {
+        card.open = true;
+        card.querySelectorAll('details').forEach(node => { node.open = true; });
+    }""")
+    expect(compact_card).to_contain_text("FULL_RESULT_AFTER_EXPANSION")
+    rendered = page.evaluate("""() => ({
+        compactCards: document.querySelectorAll('.compact-event-card').length,
+        orphanResults: document.querySelectorAll('[data-unmatched-tool-result]').length,
+        compactText: document.querySelector('.compact-event-card')?.innerText || '',
+        fallbackText: document.querySelector('[data-compact-id="fixture-fallback"]')?.innerText || '',
+        ordinaryMessageCount: [...document.querySelectorAll('#chat .chat-bot')]
+            .filter(node => node.innerText.includes('ordinary message stays in the chat flow')).length,
+    })""")
+    page.close()
+
+    assert rendered["compactCards"] == 2
+    assert rendered["orphanResults"] == 0
+    assert "FULL_RESULT_AFTER_EXPANSION" in rendered["compactText"]
+    assert "Ready" in rendered["compactText"]
+    assert "95% → 31%" in rendered["compactText"]
+    assert "Reviewed summary for the next session." in rendered["compactText"]
+    assert "Draft restored" in rendered["fallbackText"]
+    assert "ordinary message stays in the chat flow" not in rendered["compactText"]
+    assert rendered["ordinaryMessageCount"] == 1
+    assert screenshot.is_file()
+
+
+def test_compact_event_cap_preserves_json_pair_and_full_db_payload(db):
+    from app.db import add_log, get_log, get_logs_before, save_session
+
+    save_session(_session("s1", "compact"))
+    event = {
+        "action": "tool", "phase": "audit", "kind": "tool_result",
+        "tool_use_id": "audit-read", "tool_name": "Read",
+        "content": "строка\n" * 3000,
+    }
+    row_id = add_log(
+        "s1", datetime.now(timezone.utc), "compact_event",
+        json.dumps(event, ensure_ascii=False), event_id="compact-1",
+        tool_use_id="audit-read", tool_name="Read",
+    )
+    summary_event = {
+        "action": "finish", "status": "complete",
+        "summary": "итоговая сводка\n" * 3000,
+    }
+    summary_id = add_log(
+        "s1", datetime.now(timezone.utc), "compact_event",
+        json.dumps(summary_event, ensure_ascii=False), event_id="compact-1",
+    )
+
+    projected_rows = get_logs_before(
+        "s1", 2 ** 31 - 1, limit=10, max_bytes=0, cap=1024,
+    )
+    projected = next(row for row in projected_rows if row["id"] == row_id)
+    projected_summary = next(row for row in projected_rows if row["id"] == summary_id)
+    decoded = json.loads(projected["content"])
+    decoded_summary = json.loads(projected_summary["content"])


## Later history of the touched files on main (after this commit)

155 later commits touch these paths; the first 40 (oldest first):
a43f26866 2026-09-29 bg_create timer: без потолка 8 суток — срок жизни всегда позже срабатывания (баг seedon 29.09)
dc993debe 2026-09-30 V-614: убрать тень-гейт DONE без проверки — за неделю 0 совпадений с провалами мержа
bd958c8b4 2026-10-01 Платный маршрут OpenRouter DeepSeek V4.1 Flash по белому списку; песочница openrouter-lab в каталоге проектов
358fd6759 2026-10-01 Harness читает AGENTS.md/CLAUDE.md проекта как управляемый Codex, перечитывает на каждом ходу
662ee6356 2026-10-01 OpenRouter: открыть GLM-5.3 и GLM-5.3 Flash для экспериментов
810af66a9 2026-10-01 Показывать реальный кеш OpenRouter у Harness-агентов вместо нуля
53ebdaa91 2026-10-01 OpenRouter: закрепить дешёвых провайдеров по цене кеша с откатом
50a35f36d 2026-10-01 Компакт Harness: поднять таймаут ack-хода с 60 до 240 с (DeepSeek не успевал)
3c697a7ab 2026-10-02 TG: иконка простоя топика через 1 мин вместо 5, логировать успешные смены иконки
4321ff7a8 2026-10-02 V-621, V-679: разбить общий каталог проектов на файлы по scope
5222d6ef4 2026-10-02 V-678: durable-очередь доставок за гейтом квот (WAITING_QUOTA), релизер, отмена, без таймеров повтора
951d0d470 2026-10-02 V-680: durable сигнал конца хода воркера родителю вместо idle-сторожа
102fd30f2 2026-10-02 V-682: удалить тип bg-задания idle; старые idle-строки гасятся при старте
b09a8450e 2026-10-02 V-681: #V-681: MP4 в Telegram уходит видео с превью и откатом в документ
848cd8435 2026-10-02 Чат: маркер SILENT_TURN больше не оставляет живой пузырь с курсором
01eeb113a 2026-10-03 V-683: компакт по простою у katya-work-orchestrator только с 80% контекста
6883d3787 2026-10-03 V-684: #V-684: ролики ×1.5 по умолчанию, Manim вторым движком explainer-video, ролик «Оркестра не спит»
67b60528f 2026-10-03 V-685: #V-685: LaTeX (TinyTeX) для Manim с кириллицей, ролик «Почему агент сжимается на 55-й минуте»
6fc6a68ed 2026-10-03 V-684: CHANGELOG — темп по умолчанию 1.25, а не 1.5
dc881f5e5 2026-10-04 V-686: real-dashboard media for README (stand, GIF, narrated EN video) + English voice in explainer-video
8e150a46e 2026-10-04 V-689: rebuild README dashboard GIF
8155e9d1f 2026-10-04 V-688: add dashboard video playback and GIF previews
c6cc8a5dd 2026-10-04 V-692: keep live limits message updated
2db735dda 2026-10-04 V-695: spawn_worker resumes a cut-off spawn and delivers the initial task exactly once
bcd844068 2026-10-04 V-693: #V-693: record CI triage and confirmed CSS defect
1722bb82f 2026-10-04 V-696: #V-696: add RUAccent stress marking before Vosk TTS
3e82520ec 2026-10-05 дашборд: кнопка «открыть в новой вкладке» для PDF и прочих файлов, PDF во фрейме просмотрщика
8dd91d5e1 2026-10-05 V-700: #V-700: fix dashboard CI and i18n issues
43455e2b7 2026-10-05 V-707: #V-707: preserve exact provider rate limits
7e49195e6 2026-10-05 V-705: #V-705: bind orchestrator tasks and supersede stale runs
f163b3fa5 2026-10-05 V-704: #V-704: fix layout migration and run cwd defects
98238cb42 2026-10-05 V-718: #V-718: remove project memory search
6057d1e11 2026-10-05 V-706: #V-706: fix session API and delivery lifecycle
5365e1ab4 2026-10-05 V-701: #V-701: fix Telegram media routing
ea58b7dbe 2026-10-05 V-702: #V-702: fix merge gate outcomes and recovery routes
038f06b7b 2026-10-05 V-720: #V-720: add one-call dynamic workflows
2ee5279f0 2026-10-05 V-722: #V-701: stop replying in unmapped Telegram topics
4bc0a84b5 2026-10-05 V-703: #V-703: fix Codex runtime recovery and quota errors
3582eea67 2026-10-05 V-699: WIP #V-699: measure worktree bottleneck and clarify retries
607d566ee 2026-10-05 V-726: #V-726: document blocked Codex CLI upgrade

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### a43f26866 bg_create timer: без потолка 8 суток — срок жизни всегда позже срабатывания (баг seedon 29.09)

diff --git a/CHANGELOG.md b/CHANGELOG.md
index a2d2792da..6fbf7f32e 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -4,10 +4,13 @@
 > their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
+### Fixed
+- **Долгие таймеры `bg_create(type="timer")` больше не умирают молча** (`app/bg_jobs.py`). Срок жизни таймера (`delay + 1 ч`) обрезался потолком 8 суток, поэтому таймер дольше ~8 суток принимался с «OK», но истекал раньше своего срабатывания (баг-репорт seedon 29.09: bg-a0c0992639, срабатывание 27.10, истечение 07.10). Потолок для таймеров снят по решению владельца («без ограничений»): срок всегда позже `trigger_at`. Тест `test_long_timer_expires_after_it_fires`.
+
 ### Removed
 - **Скилл `vps-deploy` убран из продукта** (`prompts/skills/vps-deploy.md`, `pipeline.yaml` у оркестратора). Решение владельца 29.09: это было единственное место поставки с упоминанием хостинга, а перезапуск Orchestra и так инициирует только владелец.
 
 ### Fixed
 - **Инструменты AUDIT/FINAL больше не попадают в обычную ленту как сиротские результаты** (`AgentSession.compact`, `_agentic_audit_summary`, V-672). Черновик, AUDIT и FINAL записывают отдельные `compact_event` с общей принадлежностью и ID вызовов; дашборд собирает их в свёрнутый блок с результатами, итоговой сводкой и доступной статистикой. Telegram-мост пропускает эти служебные события. Ограничение объёма истории оставляет событие валидным JSON, показывает отметку и даёт загрузить полный текст, не меняя запись в БД. Триггер: после запуска компакта seedon-orchestrator записал 34 `tool_result` без ID и ни одного парного `tool`.
### dc993debe V-614: убрать тень-гейт DONE без проверки — за неделю 0 совпадений с провалами мержа

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 6fbf7f32e..fd56f7c23 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -8,10 +8,11 @@
 
 ### Fixed
 - **Долгие таймеры `bg_create(type="timer")` больше не умирают молча** (`app/bg_jobs.py`). Срок жизни таймера (`delay + 1 ч`) обрезался потолком 8 суток, поэтому таймер дольше ~8 суток принимался с «OK», но истекал раньше своего срабатывания (баг-репорт seedon 29.09: bg-a0c0992639, срабатывание 27.10, истечение 07.10). Потолок для таймеров снят по решению владельца («без ограничений»): срок всегда позже `trigger_at`. Тест `test_long_timer_expires_after_it_fires`.
 
 ### Removed
+- **Тень-гейт «DONE без проверки после последней правки» (V-614) удалён** (`app/done_gate.py`, вызов в `app/message_deliveries.py`, `scripts/done_gate_weekly_report.py`). Неделя в тени (23–30.09): отмечено 73 из 217 докладов DONE, ни один из отмеченных не упал на тест-гейте мержа, а 4 из 5 реальных провалов гейт не отметил; основная масса отметок — проекты без кода (презентации, тексты). Решение владельца 30.09 «убираем». Старые строки `done_gate_verdict` остаются в журнале; чат по-прежнему их не рисует.
 - **Скилл `vps-deploy` убран из продукта** (`prompts/skills/vps-deploy.md`, `pipeline.yaml` у оркестратора). Решение владельца 29.09: это было единственное место поставки с упоминанием хостинга, а перезапуск Orchestra и так инициирует только владелец.
 
 ### Fixed
 - **Инструменты AUDIT/FINAL больше не попадают в обычную ленту как сиротские результаты** (`AgentSession.compact`, `_agentic_audit_summary`, V-672). Черновик, AUDIT и FINAL записывают отдельные `compact_event` с общей принадлежностью и ID вызовов; дашборд собирает их в свёрнутый блок с результатами, итоговой сводкой и доступной статистикой. Telegram-мост пропускает эти служебные события. Ограничение объёма истории оставляет событие валидным JSON, показывает отметку и даёт загрузить полный текст, не меняя запись в БД. Триггер: после запуска компакта seedon-orchestrator записал 34 `tool_result` без ID и ни одного парного `tool`.
 
diff --git a/app/static/js/chat.js b/app/static/js/chat.js
index 9cc7605c6..b85e1dd32 100644
--- a/app/static/js/chat.js
+++ b/app/static/js/chat.js
@@ -4166,11 +4166,11 @@ function _renderCompactEvent(type, content, ts, anchor, insertAndFollow, payload
     return true;
 }
 
 function addChatEntry(type, content, ts, anchor, payload) {
     if (type === 'provider_limit') return; // Runtime telemetry; the status/error row carries the user notice.
-    if (type === 'done_gate_verdict') return; // V-614 shadow-only bookkeeping, not a chat event.
+    if (type === 'done_gate_verdict') return; // V-614 (removed 30.09): old rows stay in logs, never render them.
     if (type === 'error' && /^compact attempt \d+\/\d+ failed:/.test(content || '')) return;
     if (_isSilentTurnMarker(type, content)) return;
     if (HIDE_THINKING && (type === 'thinking' || type === 'thinking_stream')) return;
     // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
     if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
### bd958c8b4 Платный маршрут OpenRouter DeepSeek V4.1 Flash по белому списку; песочница openrouter-lab в каталоге проектов

diff --git a/CHANGELOG.md b/CHANGELOG.md
index fd56f7c23..2ee73ba69 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -4,10 +4,13 @@
 > their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
+### Added
+- **Платные маршруты OpenRouter по белому списку владельца** (`PAID_HARNESS_ROUTES` и `harness_route_allowed` в `app/models.py`; допуск в `validate_harness_model_spec`, `normalize_catalog_model`, `OpenRouterClient._validate_route`). Раньше Harness пускал только точные `:free` маршруты, и оркестратор на DeepSeek V4.1 Flash (бесплатного варианта нет) создать было нельзя. В списке один маршрут, `deepseek/deepseek-v4.1-flash`: владелец открыл его 01.10 для экспериментов с оркестраторами на OpenRouter. Остальные платные маршруты по-прежнему отклоняются. Требование нулевой стоимости `usage.cost` сохранено для `:free`; у платного маршрута стоимость идёт в учёт сессии. Тесты: `test_owner_listed_paid_route_is_billed_and_others_stay_blocked`, `test_catalog_admits_only_free_or_owner_listed_paid_routes`.
+
 ### Fixed
 - **Долгие таймеры `bg_create(type="timer")` больше не умирают молча** (`app/bg_jobs.py`). Срок жизни таймера (`delay + 1 ч`) обрезался потолком 8 суток, поэтому таймер дольше ~8 суток принимался с «OK», но истекал раньше своего срабатывания (баг-репорт seedon 29.09: bg-a0c0992639, срабатывание 27.10, истечение 07.10). Потолок для таймеров снят по решению владельца («без ограничений»): срок всегда позже `trigger_at`. Тест `test_long_timer_expires_after_it_fires`.
 
 ### Removed
 - **Тень-гейт «DONE без проверки после последней правки» (V-614) удалён** (`app/done_gate.py`, вызов в `app/message_deliveries.py`, `scripts/done_gate_weekly_report.py`). Неделя в тени (23–30.09): отмечено 73 из 217 докладов DONE, ни один из отмеченных не упал на тест-гейте мержа, а 4 из 5 реальных провалов гейт не отметил; основная масса отметок — проекты без кода (презентации, тексты). Решение владельца 30.09 «убираем». Старые строки `done_gate_verdict` остаются в журнале; чат по-прежнему их не рисует.
### 358fd6759 Harness читает AGENTS.md/CLAUDE.md проекта как управляемый Codex, перечитывает на каждом ходу

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 2ee73ba69..c234b757a 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -5,10 +5,11 @@
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
+- **Агенты Harness (OpenRouter, GigaChat) видят правила проекта** (`project_instructions` в `app/harness/prompts.py`, `HarnessBackend._refresh_system_prompt`). Claude и Codex читают CLAUDE.md/AGENTS.md сами, а Harness до сих пор собирал системное сообщение только из промпта роли. Правила проекта до его агентов не доходили: в первом ходе `openrouter-lab-orchestrator` их не было. Теперь правила читаются так же, как в управляемом Codex: от корня git до cwd, по одному файлу на каталог (AGENTS.md, иначе CLAUDE.md), симлинк на тот же файл не дублируется, потолок 32 KiB как у Codex. Личные глобальные файлы не читаются, по решению V-570. Перечитываются на каждом ходу: правка доходит со следующего хода. Пока файл не меняется, системное сообщение остаётся тем же, и кеш провайдера не сбивается. Тесты: `test_project_rules_reach_the_harness_like_managed_codex`, `test_edited_project_rules_apply_on_the_next_turn`.
 - **Платные маршруты OpenRouter по белому списку владельца** (`PAID_HARNESS_ROUTES` и `harness_route_allowed` в `app/models.py`; допуск в `validate_harness_model_spec`, `normalize_catalog_model`, `OpenRouterClient._validate_route`). Раньше Harness пускал только точные `:free` маршруты, и оркестратор на DeepSeek V4.1 Flash (бесплатного варианта нет) создать было нельзя. В списке один маршрут, `deepseek/deepseek-v4.1-flash`: владелец открыл его 01.10 для экспериментов с оркестраторами на OpenRouter. Остальные платные маршруты по-прежнему отклоняются. Требование нулевой стоимости `usage.cost` сохранено для `:free`; у платного маршрута стоимость идёт в учёт сессии. Тесты: `test_owner_listed_paid_route_is_billed_and_others_stay_blocked`, `test_catalog_admits_only_free_or_owner_listed_paid_routes`.
 
 ### Fixed
 - **Долгие таймеры `bg_create(type="timer")` больше не умирают молча** (`app/bg_jobs.py`). Срок жизни таймера (`delay + 1 ч`) обрезался потолком 8 суток, поэтому таймер дольше ~8 суток принимался с «OK», но истекал раньше своего срабатывания (баг-репорт seedon 29.09: bg-a0c0992639, срабатывание 27.10, истечение 07.10). Потолок для таймеров снят по решению владельца («без ограничений»): срок всегда позже `trigger_at`. Тест `test_long_timer_expires_after_it_fires`.
 
### 662ee6356 OpenRouter: открыть GLM-5.3 и GLM-5.3 Flash для экспериментов

diff --git a/CHANGELOG.md b/CHANGELOG.md
index c234b757a..02ce8beeb 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,11 +6,11 @@
 
 ## Unreleased
 
 ### Added
 - **Агенты Harness (OpenRouter, GigaChat) видят правила проекта** (`project_instructions` в `app/harness/prompts.py`, `HarnessBackend._refresh_system_prompt`). Claude и Codex читают CLAUDE.md/AGENTS.md сами, а Harness до сих пор собирал системное сообщение только из промпта роли. Правила проекта до его агентов не доходили: в первом ходе `openrouter-lab-orchestrator` их не было. Теперь правила читаются так же, как в управляемом Codex: от корня git до cwd, по одному файлу на каталог (AGENTS.md, иначе CLAUDE.md), симлинк на тот же файл не дублируется, потолок 32 KiB как у Codex. Личные глобальные файлы не читаются, по решению V-570. Перечитываются на каждом ходу: правка доходит со следующего хода. Пока файл не меняется, системное сообщение остаётся тем же, и кеш провайдера не сбивается. Тесты: `test_project_rules_reach_the_harness_like_managed_codex`, `test_edited_project_rules_apply_on_the_next_turn`.
-- **Платные маршруты OpenRouter по белому списку владельца** (`PAID_HARNESS_ROUTES` и `harness_route_allowed` в `app/models.py`; допуск в `validate_harness_model_spec`, `normalize_catalog_model`, `OpenRouterClient._validate_route`). Раньше Harness пускал только точные `:free` маршруты, и оркестратор на DeepSeek V4.1 Flash (бесплатного варианта нет) создать было нельзя. В списке один маршрут, `deepseek/deepseek-v4.1-flash`: владелец открыл его 01.10 для экспериментов с оркестраторами на OpenRouter. Остальные платные маршруты по-прежнему отклоняются. Требование нулевой стоимости `usage.cost` сохранено для `:free`; у платного маршрута стоимость идёт в учёт сессии. Тесты: `test_owner_listed_paid_route_is_billed_and_others_stay_blocked`, `test_catalog_admits_only_free_or_owner_listed_paid_routes`.
+- **Платные маршруты OpenRouter по белому списку владельца** (`PAID_HARNESS_ROUTES` и `harness_route_allowed` в `app/models.py`; допуск в `validate_harness_model_spec`, `normalize_catalog_model`, `OpenRouterClient._validate_route`). Раньше Harness пускал только точные `:free` маршруты, и оркестратор на DeepSeek V4.1 Flash (бесплатного варианта нет) создать было нельзя. В списке три маршрута: `deepseek/deepseek-v4.1-flash`, `z-ai/glm-5.3`, `z-ai/glm-5.3-flash` — владелец открыл их 01.10 для экспериментов с оркестраторами на OpenRouter (GLM-5.4 в каталоге нет, последняя GLM-5.3). Остальные платные маршруты по-прежнему отклоняются. Требование нулевой стоимости `usage.cost` сохранено для `:free`; у платного маршрута стоимость идёт в учёт сессии. Тесты: `test_owner_listed_paid_route_is_billed_and_others_stay_blocked`, `test_catalog_admits_only_free_or_owner_listed_paid_routes`.
 
 ### Fixed
 - **Долгие таймеры `bg_create(type="timer")` больше не умирают молча** (`app/bg_jobs.py`). Срок жизни таймера (`delay + 1 ч`) обрезался потолком 8 суток, поэтому таймер дольше ~8 суток принимался с «OK», но истекал раньше своего срабатывания (баг-репорт seedon 29.09: bg-a0c0992639, срабатывание 27.10, истечение 07.10). Потолок для таймеров снят по решению владельца («без ограничений»): срок всегда позже `trigger_at`. Тест `test_long_timer_expires_after_it_fires`.
 
 ### Removed
### 810af66a9 Показывать реальный кеш OpenRouter у Harness-агентов вместо нуля

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 02ce8beeb..5f2f37aa4 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -4,10 +4,13 @@
 > their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
+### Fixed
+- **Дашборд показывал «кеш 0.00%» у агентов OpenRouter, хотя провайдер кешировал до 99%** (`_cached_prompt_tokens`, `_cache_hit_pct` в `app/backend_harness.py`; `_accumulate`, `_turn_end`, `_error_turn_end`). OpenRouter возвращает `usage.prompt_tokens_details.cached_tokens`, но backend выбрасывал это число и жёстко писал `cache_hit: 0`, а весь `prompt_tokens` (включая кеш) шёл в `input_tokens`. Теперь кешированная часть вычитается из входа в `cache_read`, а `cache_hit` считается как её доля от промпта. Деньги не пересчитываются — стоимость берётся из ответа провайдера, где скидка за кеш уже применена. Триггер: `openrouter-lab-orchestrator` на DeepSeek V4.1 Flash, ход с 55 652 токенами промпта, 55 168 из них кеш (99.1%), в дашборде «кеш 0.00%». Тесты: `test_openrouter_cached_prompt_tokens_split_into_cache_read_and_hit_pct`, `test_turn_end_reports_cache_read_tokens_not_zero`.
+
 ### Added
 - **Агенты Harness (OpenRouter, GigaChat) видят правила проекта** (`project_instructions` в `app/harness/prompts.py`, `HarnessBackend._refresh_system_prompt`). Claude и Codex читают CLAUDE.md/AGENTS.md сами, а Harness до сих пор собирал системное сообщение только из промпта роли. Правила проекта до его агентов не доходили: в первом ходе `openrouter-lab-orchestrator` их не было. Теперь правила читаются так же, как в управляемом Codex: от корня git до cwd, по одному файлу на каталог (AGENTS.md, иначе CLAUDE.md), симлинк на тот же файл не дублируется, потолок 32 KiB как у Codex. Личные глобальные файлы не читаются, по решению V-570. Перечитываются на каждом ходу: правка доходит со следующего хода. Пока файл не меняется, системное сообщение остаётся тем же, и кеш провайдера не сбивается. Тесты: `test_project_rules_reach_the_harness_like_managed_codex`, `test_edited_project_rules_apply_on_the_next_turn`.
 - **Платные маршруты OpenRouter по белому списку владельца** (`PAID_HARNESS_ROUTES` и `harness_route_allowed` в `app/models.py`; допуск в `validate_harness_model_spec`, `normalize_catalog_model`, `OpenRouterClient._validate_route`). Раньше Harness пускал только точные `:free` маршруты, и оркестратор на DeepSeek V4.1 Flash (бесплатного варианта нет) создать было нельзя. В списке три маршрута: `deepseek/deepseek-v4.1-flash`, `z-ai/glm-5.3`, `z-ai/glm-5.3-flash` — владелец открыл их 01.10 для экспериментов с оркестраторами на OpenRouter (GLM-5.4 в каталоге нет, последняя GLM-5.3). Остальные платные маршруты по-прежнему отклоняются. Требование нулевой стоимости `usage.cost` сохранено для `:free`; у платного маршрута стоимость идёт в учёт сессии. Тесты: `test_owner_listed_paid_route_is_billed_and_others_stay_blocked`, `test_catalog_admits_only_free_or_owner_listed_paid_routes`.
 
 ### Fixed
### 53ebdaa91 OpenRouter: закрепить дешёвых провайдеров по цене кеша с откатом

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 5f2f37aa4..6d59c2dc6 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -4,10 +4,13 @@
 > their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
+### Added
+- **Закрепление провайдера OpenRouter по цене кеша** (`_provider_order` в `app/harness/llm.py`, поле `provider` в `_build_body`). Без пина OpenRouter сам маршрутизировал на дорогого Together ($0.006/1М чтения кеша, $1.20/1М выход). Теперь запрос несёт `provider.order = [DeepInfra, StreamLake, GMICloud]` с `allow_fallbacks: true`: порядок по стоимости чтения кеша (главная статья расхода при перечитывании контекста), откат не даёт агенту зависнуть, если провайдер не обслуживает модель (GLM у этих нет — уходит к дефолтным). Переопределяется `HARNESS_PROVIDER_ORDER` без правки кода; пустая строка возвращает авторутинг. На нашем профиле (99% кеша, ~1.7 млрд читаемых токенов/день) это ~$11/день против ~$19 на Together. Тест `test_provider_order_pins_cheap_providers_with_fallback`.
+
 ### Fixed
 - **Дашборд показывал «кеш 0.00%» у агентов OpenRouter, хотя провайдер кешировал до 99%** (`_cached_prompt_tokens`, `_cache_hit_pct` в `app/backend_harness.py`; `_accumulate`, `_turn_end`, `_error_turn_end`). OpenRouter возвращает `usage.prompt_tokens_details.cached_tokens`, но backend выбрасывал это число и жёстко писал `cache_hit: 0`, а весь `prompt_tokens` (включая кеш) шёл в `input_tokens`. Теперь кешированная часть вычитается из входа в `cache_read`, а `cache_hit` считается как её доля от промпта. Деньги не пересчитываются — стоимость берётся из ответа провайдера, где скидка за кеш уже применена. Триггер: `openrouter-lab-orchestrator` на DeepSeek V4.1 Flash, ход с 55 652 токенами промпта, 55 168 из них кеш (99.1%), в дашборде «кеш 0.00%». Тесты: `test_openrouter_cached_prompt_tokens_split_into_cache_read_and_hit_pct`, `test_turn_end_reports_cache_read_tokens_not_zero`.
 
 ### Added
 - **Агенты Harness (OpenRouter, GigaChat) видят правила проекта** (`project_instructions` в `app/harness/prompts.py`, `HarnessBackend._refresh_system_prompt`). Claude и Codex читают CLAUDE.md/AGENTS.md сами, а Harness до сих пор собирал системное сообщение только из промпта роли. Правила проекта до его агентов не доходили: в первом ходе `openrouter-lab-orchestrator` их не было. Теперь правила читаются так же, как в управляемом Codex: от корня git до cwd, по одному файлу на каталог (AGENTS.md, иначе CLAUDE.md), симлинк на тот же файл не дублируется, потолок 32 KiB как у Codex. Личные глобальные файлы не читаются, по решению V-570. Перечитываются на каждом ходу: правка доходит со следующего хода. Пока файл не меняется, системное сообщение остаётся тем же, и кеш провайдера не сбивается. Тесты: `test_project_rules_reach_the_harness_like_managed_codex`, `test_edited_project_rules_apply_on_the_next_turn`.
### 50a35f36d Компакт Harness: поднять таймаут ack-хода с 60 до 240 с (DeepSeek не успевал)

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 6d59c2dc6..5f4d415d0 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -4,10 +4,13 @@
 > their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
+### Fixed
+- **Сжатие контекста (компакт) срывалось у агентов OpenRouter: ack-ход не укладывался в 60 с** (`_compact_ack_timeout`, `COMPACT_ACK_TIMEOUT_SECONDS`/`_HARNESS` в `app/session.py`). После сжатия платформа поднимает свежую сессию без префикс-кеша и шлёт «Acknowledge briefly», ожидая завершения хода `asyncio.wait_for(..., timeout=60)`. DeepSeek V4.1 Flash на OpenRouter (7–83 tps у разных провайдеров) не отвечал за минуту на полном перечитывании системного промпта → таймаут → откат к несжатой сессии, агент залипал у потолка контекста. Триггер: `openrouter-lab-orchestrator`, компакт с 59% контекста — «compact ack turn did not complete (60s)». Лимит для Claude/Codex оставлен 60 с, для Harness поднят до 240 с; переопределяется `COMPACT_ACK_TIMEOUT_SECONDS`. Тест `test_compact_ack_timeout_is_longer_for_harness`.
+
 ### Added
 - **Закрепление провайдера OpenRouter по цене кеша** (`_provider_order` в `app/harness/llm.py`, поле `provider` в `_build_body`). Без пина OpenRouter сам маршрутизировал на дорогого Together ($0.006/1М чтения кеша, $1.20/1М выход). Теперь запрос несёт `provider.order = [DeepInfra, StreamLake, GMICloud]` с `allow_fallbacks: true`: порядок по стоимости чтения кеша (главная статья расхода при перечитывании контекста), откат не даёт агенту зависнуть, если провайдер не обслуживает модель (GLM у этих нет — уходит к дефолтным). Переопределяется `HARNESS_PROVIDER_ORDER` без правки кода; пустая строка возвращает авторутинг. На нашем профиле (99% кеша, ~1.7 млрд читаемых токенов/день) это ~$11/день против ~$19 на Together. Тест `test_provider_order_pins_cheap_providers_with_fallback`.
 
 ### Fixed
 - **Дашборд показывал «кеш 0.00%» у агентов OpenRouter, хотя провайдер кешировал до 99%** (`_cached_prompt_tokens`, `_cache_hit_pct` в `app/backend_harness.py`; `_accumulate`, `_turn_end`, `_error_turn_end`). OpenRouter возвращает `usage.prompt_tokens_details.cached_tokens`, но backend выбрасывал это число и жёстко писал `cache_hit: 0`, а весь `prompt_tokens` (включая кеш) шёл в `input_tokens`. Теперь кешированная часть вычитается из входа в `cache_read`, а `cache_hit` считается как её доля от промпта. Деньги не пересчитываются — стоимость берётся из ответа провайдера, где скидка за кеш уже применена. Триггер: `openrouter-lab-orchestrator` на DeepSeek V4.1 Flash, ход с 55 652 токенами промпта, 55 168 из них кеш (99.1%), в дашборде «кеш 0.00%». Тесты: `test_openrouter_cached_prompt_tokens_split_into_cache_read_and_hit_pct`, `test_turn_end_reports_cache_read_tokens_not_zero`.
diff --git a/app/session.py b/app/session.py
index 2133d5448..b71493848 100644
--- a/app/session.py
+++ b/app/session.py
@@ -533,10 +533,17 @@ class AgentSession:
     AUTO_CONTINUE_MAX = 5
     RATE_LIMIT_MAX_RETRIES = 3
     RATE_LIMIT_DELAY = 30
     SERVER_ERROR_MAX_RETRIES = 3
     SERVER_ERROR_RETRY_DELAY = 5
+    # Ack-ход после сжатия идёт в СВЕЖЕЙ сессии без префикс-кеша: системный промпт
+    # перечитывается целиком по полной цене. Harness-модели (OpenRouter) медленные —
+    # DeepSeek V4.1 Flash не укладывался в прежние 60 с и откатывал компакт (V-676).
+    # Claude/Codex успевают за минуту; остальным даём больше. Переопределяется
+    # COMPACT_ACK_TIMEOUT_SECONDS без правки кода.
+    COMPACT_ACK_TIMEOUT_SECONDS = 60
+    COMPACT_ACK_TIMEOUT_HARNESS = 240
     PRECOMPACT_DELAY_SECONDS = 55 * 60
     PRECOMPACT_CONTEXT_THRESHOLD = 20
     CODEX_PRECOMPACT_DELAY_SECONDS = 25 * 60
     CODEX_PRECOMPACT_CONTEXT_THRESHOLD = 60
     # Sessions come back from compact at 7-12% (prompt + handoff). Week to 25.09
@@ -1096,10 +1103,21 @@ class AgentSession:
                 require_worker_admission(decision)
             finally:
                 self._lifecycle_lock.release()
             return
 
+    def _compact_ack_timeout(self) -> float:
+        env = os.environ.get("COMPACT_ACK_TIMEOUT_SECONDS")
+        if env:
+            try:
+                return max(1.0, float(env))
+            except ValueError:
+                pass
+        if self.backend_type in ("claude", "codex"):
+            return float(self.COMPACT_ACK_TIMEOUT_SECONDS)
+        return float(self.COMPACT_ACK_TIMEOUT_HARNESS)
+
     def _start_turn_state(self, *, compact_ack: bool = False) -> None:
         """Publish the single in-memory/DB transition into a running turn."""
         self._manually_interrupted = False
         self._did_report = False
         self._turns.bump_turn_gen()
@@ -3139,14 +3157,15 @@ class AgentSession:
                 )
                 await backend.send(preamble + "Acknowledge briefly.")
 
             await self._run_compaction_start(permit, start_ack_turn)
 
+            ack_timeout = self._compact_ack_timeout()
             try:
-                await asyncio.wait_for(ack_event.wait(), timeout=60)
+                await asyncio.wait_for(ack_event.wait(), timeout=ack_timeout)
             except asyncio.TimeoutError:
-                self._log("error", "compact ack turn did not complete (60s)")
+                self._log("error", f"compact ack turn did not complete ({ack_timeout:.0f}s)")
                 # stop the still-running ack turn so it can't interleave with the next send
                 await self._disconnect_backend()
                 self.session_id = pre_compact_session_id
                 self.status = AgentStatus.IDLE
                 self._persist()
diff --git a/tests/test_session.py b/tests/test_session.py
index 83f45743e..9b0404229 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -5683,5 +5683,21 @@ async def test_t1_385_message_during_deferred_interrupt_queues_until_native_term
     finally:
         release_interrupt.set()
         if not listener.done():
             listener.cancel()
         await asyncio.gather(listener, return_exceptions=True)
+
+
+def test_compact_ack_timeout_is_longer_for_harness(session, monkeypatch):
+    """V-676: DeepSeek on OpenRouter couldn't finish the ack turn in 60s and rolled back."""
+    monkeypatch.delenv("COMPACT_ACK_TIMEOUT_SECONDS", raising=False)
+    session.backend_type = "claude"
+    assert session._compact_ack_timeout() == 60
+    session.backend_type = "codex"
+    assert session._compact_ack_timeout() == 60
+    session.backend_type = "harness"
+    assert session._compact_ack_timeout() == 240
+
+    monkeypatch.setenv("COMPACT_ACK_TIMEOUT_SECONDS", "123")
+    assert session._compact_ack_timeout() == 123
+    session.backend_type = "claude"
+    assert session._compact_ack_timeout() == 123