# Candidate cand-45

## ORIGIN commit 6dac7dcbff (2026-08-12): #220: #220: план фазы 2 — T1 пересборка промпта, T2/T3 дренаж, красные тесты тикетов
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/manager.py b/app/manager.py
index 83b47560c..8b18e5dd7 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -432,16 +432,32 @@ def _crosses_repo_boundary(parent_dir: str, child_repo: str) -> bool:
 
 class SessionManager:
     def __init__(self):
         self.sessions: dict[str, AgentSession] = {}
         self._session_locks: dict[str, asyncio.Lock] = {}
         self._spawn_locks: dict[tuple[str, str], asyncio.Lock] = {}
         # wired callback (set by tg_bridge.start_bridge) — manager does not import tg_bridge
         self.tg_topics_remover: Optional[Callable[[list[str]], Awaitable[dict]]] = None
+        # #220 T2: рестарт закрывает приём новых ходов, пока дренажит уже идущие
+        self.draining = False
+
+    def begin_drain(self) -> None:
+        """Закрыть приём новых ходов. СИНХРОННО — в этом весь смысл.
+
+        Ни одного `await` здесь быть не должно: флаг обязан встать раньше, чем цикл
+        событий отдаст управление кому-то ещё. Иначе ход, уже прошедший проверку
+        гейта, успеет присвоить себе RUNNING после того, как дренаж снял снимок
+        живых ходов, и попадёт под сигнал как раз тот, кого дренаж защищал.
+        """
+        self.draining = True
+
+    def end_drain(self) -> None:
+        """Открыть приём обратно. Нужен тестам и отменённому рестарту."""
+        self.draining = False
 
     def get_session_lock(self, session_id: str) -> asyncio.Lock:
         if session_id not in self._session_locks:
             self._session_locks[session_id] = asyncio.Lock()
         return self._session_locks[session_id]
 
     def start_background_tasks(self) -> None:
         # log retention REMOVED by owner decision: agent history is research data. The old
@@ -1412,16 +1428,60 @@ class SessionManager:
         for s in self.sessions.values():
             if s.name == name:
                 return s
         for row in get_all_sessions():
             if row["name"] == name:
                 return await self._load_from_db(row)
         return None
 
+    def assemble_prompt(
+        self, *, pipeline: str, role: str, scope: str, is_orch: bool, name: str,
+        owned_dirs, branch: str, stored_overlay: str | None, old_prompt: str,
+    ) -> tuple[str, str | None]:
+        """Собрать системный промпт из файлов ролей — один владелец на двух вызывающих.
+
+        Зовётся из `_load_from_db` (восстановление сессии при старте) и из переинжекта
+        в `session.py`: без второго вызывающего правка `pipelines/**` доезжала до живого
+        агента только рестартом (#220 T1, медиана задержки выката 3.3 ч).
+
+        Возвращает (собранный промпт, восстановленный overlay). `overlay is None` на
+        выходе означает полную замену промпта оператором — у неё нет границы
+        компонентов, и пересобирать её нельзя.
+        """
+        current_base = ROLE_SYSTEM_PROMPT(
+            pipeline, role, scope
+        ) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role)
+        if not is_orch:
+            orch_name = self._find_orchestrator_name(scope)
+            current_base = safe_format_prompt(
+                current_base,
+                worker_name=name, orchestrator_name=orch_name or "orchestrator",
+                scope=scope, branch=branch,
+            )
+        if stored_overlay is None:
+            old_without_memory = strip_worker_memory(old_prompt)
+            if not old_without_memory:
+                prompt_overlay = self._ownership_prompt(parse_owned_dirs(owned_dirs))
+                prompt_without_memory = current_base + prompt_overlay
+            elif old_without_memory.startswith(current_base):
+                prompt_overlay = old_without_memory[len(current_base):]
+                prompt_without_memory = current_base + prompt_overlay
+            else:
+                # A legacy/full-prompt override has no component boundary to recover.
+                # Preserve it byte-for-byte instead of guessing and dropping authority.
+                prompt_overlay = None
+                prompt_without_memory = old_without_memory
+        else:
+            prompt_overlay = strip_worker_memory(stored_overlay)
+            prompt_without_memory = current_base + prompt_overlay
+        return refresh_worker_memory(
+            prompt_without_memory, name, role, scope,
+        ), prompt_overlay
+
     async def _load_from_db(self, db_row: dict) -> AgentSession:
         role = db_row.get("role") or ("orchestrator" if db_row.get("is_orchestrator") else "worker")
         # Old rows (migrated) store pipeline='' → normalize to DEFAULT_PIPELINE.
         # Without this, ROLE_SYSTEM_PROMPT('') now fails loud (legacy fallback removed)
         # and resume/load of pre-pipeline sessions would break.
         # Нормализованное значение обязано доехать и до самой сессии (см. AgentSession
         # ниже): пока в объект клался сырой db_row, промпт брал 'default', а
         # _refresh_skills — '', падал на «pipeline name is empty», и корневой
@@ -1431,19 +1491,16 @@ class SessionManager:
         # колонка is_orchestrator (денормализована при спавне); иначе frozenset.
         is_orch = self._role_is_orchestrator(pipeline, role)
         try:
             if get_role(pipeline, role) is None:
                 is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
         except FileNotFoundError:
             is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
         old_prompt = db_row.get("system_prompt", "")
-        current_base = ROLE_SYSTEM_PROMPT(
-            pipeline, role, db_row["scope"]
-        ) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role)
         cwd = db_row.get("cwd") or db_row["scope"]
         if not Path(cwd).is_dir():
             cwd = db_row["scope"]
         expected_bt = backend_for_model(db_row["model"])
         stored_bt = db_row.get("backend_type") or expected_bt
         if stored_bt != expected_bt:
             logger.warning(f"backend mismatch for {db_row['name']}: stored={stored_bt}, model implies={expected_bt}. Using {expected_bt}.")
             stored_bt = expected_bt
@@ -1458,46 +1515,21 @@ class SessionManager:
             )
             if actual.returncode == 0:
                 actual_branch = actual.stdout.strip()
                 if actual_branch != db_branch:
                     db_branch = actual_branch
                     m = _TASK_BRANCH_RE.match(actual_branch)
                     db_task_id = m.group(1) if m else ""
 
-        orch_name = self._find_orchestrator_name(db_row["scope"]) if not is_orch else None
-        if not is_orch:
-            current_base = safe_format_prompt(
-                current_base,
-                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
-                scope=db_row["scope"],
-                branch=db_row.get("branch") or db_row.get("base_branch") or "",
-            )
-        stored_overlay = db_row.get("prompt_overlay")
-        if stored_overlay is None:
-            old_without_memory = strip_worker_memory(old_prompt)
-            if not old_without_memory:
-                prompt_overlay = self._ownership_prompt(
-                    parse_owned_dirs(db_row.get("owned_dirs"))
-                )
-                prompt_without_memory = current_base + prompt_overlay
-            elif old_without_memory.startswith(current_base):
-                prompt_overlay = old_without_memory[len(current_base):]
-                prompt_without_memory = current_base + prompt_overlay
-            else:
-                # A legacy/full-prompt override has no component boundary to recover.
-                # Preserve it byte-for-byte instead of guessing and dropping authority.
-                prompt_overlay = None
-                prompt_without_memory = old_without_memory
-        else:
-            prompt_overlay = strip_worker_memory(stored_overlay)
-            prompt_without_memory = current_base + prompt_overlay
-        current_prompt = refresh_worker_memory(
-            prompt_without_memory,
-            db_row["name"], role, db_row["scope"],
+        current_prompt, prompt_overlay = self.assemble_prompt(
+            pipeline=pipeline, role=role, scope=db_row["scope"], is_orch=is_orch,
+            name=db_row["name"], owned_dirs=db_row.get("owned_dirs"),
+            branch=db_row.get("branch") or db_row.get("base_branch") or "",
+            stored_overlay=db_row.get("prompt_overlay"), old_prompt=old_prompt,
         )
 
         custom_mcp = _parse_custom_mcp(db_row.get("mcp_servers_custom"))
         session = AgentSession(
             id=db_row["id"], name=db_row["name"], scope=db_row["scope"], cwd=cwd,
             model=db_row["model"], system_prompt=current_prompt,
             prompt_overlay=prompt_overlay,
             session_id=db_row.get("session_id"), cost_usd=db_row.get("cost_usd", 0),
diff --git a/app/routes/system.py b/app/routes/system.py
index ada24c5d0..9f4ed33ac 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -1691,23 +1691,79 @@ async def release_lock_endpoint(req: TestLockRequest):
     ok = release_test_lock(
         req.scope, req.holder, holder_session_id=req.holder_session_id,
     )
     return {"released": ok}
 
 
 _restart_tasks: set[asyncio.Task] = set()
 
+# 15 минут: замер #220 — дренаж сходится за это время в 80% случаев (p50 1.2 мин).
+# Дедлайн БЕЗУСЛОВНЫЙ: гарантии сходимости нет вовсе, потому что ходы порождаются
+# изнутри контура (send_message между агентами, автоотчёт родителю).
+_DRAIN_DEADLINE_S = 900
 
-async def _restart_service_after_response() -> None:
-    """Let the response flush, then exit cleanly; systemd Restart=always revives us."""
+
+def _drain_sessions() -> list:
+    """Живые сессии одним местом — тест подменяет именно её."""
+    return list(manager.sessions.values())
+
+
+def _record_restart_outcome(outcome: dict) -> None:
+    """Записать итог дренажа ДО сигнала: после него отчитываться уже некому.
+
+    Процесс умирает внутри workflow, поэтому ни HTTP-ответ, ни живой TG-канал итог
+    не донесут — переживает рестарт только запись на диск. Потребитель — существующий
+    журнал сессии в дашборде; нового эндпоинта и таблицы не заводим (#220 T3).
+    """
+    from app.db import add_log
+
+    ts = datetime.now(timezone.utc)
+    summary = (
+        f"[system] рестарт: дренаж {outcome['waited_s']:.1f} с, "
+        f"разорвано ходов: {outcome['cut_turns']}"
+    )
+    logger.warning(summary)
+    for session_id in outcome["cut_ids"]:
+        add_log(session_id, ts, "system",
+                f"{summary}. Твой ход разорван — автоматического повтора нет.")
+
+
+async def _restart_service_after_response() -> dict:
+    """Дренаж → запись итога → SIGINT; systemd Restart=always поднимает нас обратно.
+
+    Порядок обязателен: дренаж идёт ДО сигнала, а `shutdown_merge_operations()`,
+    `bg_manager.shutdown()` и `manager.shutdown_all()` — уже ПОСЛЕ него, внутри
+    lifespan (`app/main.py:114,126,127`).
+    """
     await asyncio.sleep(0.5)
+    manager.begin_drain()
+    started = time.monotonic()
+    while time.monotonic() - started < _DRAIN_DEADLINE_S:
+        if not [s for s in _drain_sessions() if s.is_busy]:
+            break
+        await asyncio.sleep(1)
+    cut = [s for s in _drain_sessions() if s.is_busy]
+    outcome = {
+        "waited_s": time.monotonic() - started,
+        "cut_turns": len(cut),
+        "cut_names": [s.name for s in cut],
+        "cut_ids": [s.id for s in cut],
+    }
+    try:
+        _record_restart_outcome(outcome)
+    except Exception as error:
+        # Побочный учёт не имеет права отменить основное действие: дедлайн назван
+        # безусловным, и сбой записи не делает рестарт менее обязательным (класс #215).
+        logger.warning("could not record restart outcome: %s: %s",
+                       type(error).__name__, error)
     from app.live_broker import broker
     broker.close_subscribers()
     os.kill(os.getpid(), signal.SIGINT)
+    return outcome
 
 
 @router.post("/api/restart")
 async def restart_server():
     task = asyncio.create_task(_restart_service_after_response())
     _restart_tasks.add(task)
     task.add_done_callback(_restart_tasks.discard)
     return {"ok": True, "scheduled": True}
diff --git a/app/session.py b/app/session.py
index 7ac155b38..c1d415572 100644
--- a/app/session.py
+++ b/app/session.py
@@ -45,23 +45,52 @@ from app.session_state import (  # noqa: F401 — re-exported: importers use app
     AgentStatus, IDLE_TIMEOUT_ORCHESTRATOR, IDLE_TIMEOUT_WORKER,
 )
 from app.session_turns import TurnManager
 from app.usage_contract import KnownContext, current_context
 
 if TYPE_CHECKING:
     from app.backend_protocol import BackendLike
     from app.quota_gate import QuotaDecision
-from app.db import add_log, get_history_logs, get_logs, save_session, tool_error_add
+from app.db import (
+    add_log, enqueue_fact, get_history_logs, get_logs, save_session, tool_error_add,
+)
 from app.errtext import err_text
 
 
 logger = logging.getLogger(__name__)
 
 
+class DrainingRefused(RuntimeError):
+    """Ход не начат: идёт дренаж перед рестартом (#220 T2).
+
+    Отказ громкий намеренно. Durable-очереди СООБЩЕНИЙ в проекте нет: `enqueue_fact`
+    хранит ФАКТ недоставки, а не само сообщение (`_attach_pending_facts` ниже), поэтому
+    «тихо положить и доставить потом» было бы обещанием, которого система не выполняет.
+    Внешний отправитель — агент, человек в TG, дашборд — видит ошибку и повторяет сам.
+    """
+
+
+def _refuse_if_draining(session: "AgentSession") -> None:
+    """Гейт допуска. СИНХРОННЫЙ и вызывается вплотную к присвоению RUNNING.
+
+    Ни здесь, ни между этим вызовом и `status = RUNNING` не должно быть ни одного
+    `await`: `send()` держит `_lifecycle_lock` через несколько await'ов
+    (`_apply_pending_identity_restart`, `_apply_manifest_effort`), и ранняя проверка
+    позволила бы ходу стартовать ПОСЛЕ того, как дренаж снял снимок живых ходов.
+    """
+    from app.deps import manager
+
+    if manager.draining:
+        raise DrainingRefused(
+            f"[{session.name}] Orchestra перезапускается: идёт дренаж, новый ход не "
+            f"начинается. Повтори через минуту."
+        )
+
+
 def _subscription_limit_kind(text: str) -> str | None:
     """Classify the canonical non-transient subscription-limit messages."""
     lowered = text.lower()
     if "monthly spend limit" in lowered:
         return "monthly"
     if any(marker in lowered for marker in (
         "session limit",
         "hit your session",
@@ -718,16 +747,43 @@ class AgentSession:
             codex_skill_index_fallback=(
                 self.backend_type == "codex"
                 and getattr(self, "_codex_skill_index_fallback", False)
             ),
             history_import=history_import,
         )
         return build_backend(self.backend_type, context)
 
+    @property
+    def is_busy(self) -> bool:
+        """Идёт ли работа, которую рестарт разорвёт (#220 T3).
+
+        Одного `status == RUNNING` мало: компактификация генерирует summary при
+        `_compacting = True`, а `RUNNING` присваивается только на ack-ходе в самом
+        конце. Дренаж по одному статусу срезал бы оплаченную сводку, не заметив её.
+        """
+        return self.status == AgentStatus.RUNNING or self._compacting
+
+    def _queue_drain_fact(self, kind: str, what: str) -> None:
+        """Оставить агенту факт о продолжении, срезанном дренажом (#220 T2).
+
+        Только для внутренних стартеров хода: у них нет отправителя, которому можно
+        отказать громко, поэтому единственный способ не потерять событие молча — тот
+        же механизм недоставки (#50). Ключ дедупа один на вид продолжения: за окно
+        дренажа повтор схлопывается в одну строку.
+        """
+        try:
+            enqueue_fact(
+                self.id, f"drain:{kind}",
+                f"{what}; Orchestra перезапускалась, автоматического повтора нет",
+            )
+        except Exception as error:
+            logger.warning(f"[{self.name}] could not queue drain fact {kind}: "
+                           f"{type(error).__name__}: {error}")
+
     def _attach_pending_facts(self, message: str) -> tuple[str, list[str]]:
         """Приписать к сообщению ФАКТЫ о недоставке, накопленные для этой сессии (#50).
 
         Это НЕ ретрай: исходные сообщения не пересылаются, едет только факт, что они не
         дошли. Иначе ждущий агент не узнаёт о недоставке никогда — запись в `logs` типа
         `system` в контекст не попадает (измерено в #47).
 
         Не бросает НИЧЕГО: сообщение важнее факта. Сбой очереди → уходит как раньше.
@@ -930,26 +986,59 @@ class AgentSession:
                 # Only on first message after resume; subsequent turns use cached prompt.
                 current_th = prompt_template_hash(self.role)
                 old_th = self._template_hash or current_th
                 templates_changed = old_th != current_th
                 pending_th = current_th
                 # Personal memory is re-read here, not reused from the assembled string:
                 # the prompt is built at spawn / _load_from_db, so anything the agent
                 # wrote to its own memory since then would otherwise wait for a restart.
-                self._current_prompt = refresh_worker_memory(
-                    self._current_prompt, self.name, self.role, self.scope
-                )
+                # The same argument applies to the ROLE text itself (#220 T1): rebuild it
+                # from pipelines/** instead of replaying the string assembled at startup,
+                # otherwise a rule edit waits for a restart (median 3.3h, p75 22.9h).
+                if self.prompt_overlay is None:
+                    # A full prompt set by the operator has no component boundary —
+                    # rebuilding it would silently drop the authority they gave.
+                    self._current_prompt = refresh_worker_memory(
+                        self._current_prompt, self.name, self.role, self.scope
+                    )
+                else:
+                    from app.deps import manager
+                    try:
+                        self._current_prompt, _ = manager.assemble_prompt(
+                            pipeline=self.pipeline, role=self.role, scope=self.scope,
+                            is_orch=self.is_orchestrator, name=self.name,
+                            owned_dirs=self.owned_dirs,
+                            branch=self.branch or self.base_branch or "",
+                            stored_overlay=self.prompt_overlay,
+                            old_prompt=self._current_prompt,
+                        )
+                    except Exception as error:
+                        # Пересборка читает pipelines/** на ГОРЯЧЕМ пути, а
+                        # ROLE_SYSTEM_PROMPT падает громко (ValueError) на битом
+                        # манифесте. До T1 этого вызова здесь не было вовсе, поэтому
+                        # опечатка в роли теперь убивала бы следующий ход У ВСЕХ
+                        # агентов сразу. Откат к прежнему поведению — со старым
+                        # промптом, но вслух: горячее применение не имеет права быть
+                        # хуже своего отсутствия.
+                        self._log("error", f"prompt rebuild failed, using the prompt "
+                                           f"from startup: {err_text(error)}")
+                        logger.error(f"[{self.name}] prompt rebuild failed: "
+                                     f"{err_text(error)}")
+                        self._current_prompt = refresh_worker_memory(
+                            self._current_prompt, self.name, self.role, self.scope
+                        )
                 message = f"[Orchestra platform note: {'your role instructions were updated.' if templates_changed else 'refreshed context (worker list, etc.).'} This is from the server, not another agent.]\n{self._current_prompt}\n\n---\n\n{message}"
                 did_inject = True
 
             await self._apply_pending_identity_restart()
             await self._apply_manifest_effort()
 
             if self.status in (AgentStatus.IDLE, AgentStatus.WAITING):
+                _refuse_if_draining(self)  # no await between here and RUNNING below
                 self._manually_interrupted = False
                 self._did_report = False
                 self._turns.bump_turn_gen()
                 self._turn_logs = []
                 self._turn_start = asyncio.get_event_loop().time()
                 self._last_msg_time = self._turn_start
                 self.status = AgentStatus.RUNNING
                 self._persist()
@@ -1638,16 +1727,17 @@ class AgentSession:
                 # Batch queued messages into one turn to avoid spawning N sequential turns —
                 # each turn has ~3s round-trip overhead and occupies the lifecycle lock
                 combined = "\n".join(
                     f"--- message {i+1}/{len(msgs)} ---\n{m}"
                     for i, m in enumerate(msgs)
                 )
             self._log("status", f"delivering {len(msgs)} queued message(s)")
             try:
+                _refuse_if_draining(self)  # no await between here and RUNNING below
                 self._manually_interrupted = False
                 self._did_report = False
                 self._turns.bump_turn_gen()
                 self._turn_logs = []
                 self._turn_start = asyncio.get_event_loop().time()
                 self._last_msg_time = self._turn_start
                 self.status = AgentStatus.RUNNING
                 self._persist()
@@ -1663,16 +1753,29 @@ class AgentSession:
                     )
                 combined, fact_keys = self._attach_pending_facts(combined)
                 await backend.send(combined)
                 self._ack_pending_facts(fact_keys)
                 if get_runtime(self.backend_type).capabilities.event_stream == "per_turn":
                     self._listen_task = asyncio.create_task(self._turn_event_loop())
                     self._listen_task.add_done_callback(self._on_task_done)
                 self._quota_block_notice_signature = ""
+            except DrainingRefused as refusal:
+                # Отправителя, которому можно отказать, здесь нет — ход начинал сам
+                # `_flush_pending`. Сообщения возвращаются в память (умрут с процессом),
+                # поэтому агенту остаётся ФАКТ: после рестарта он узнает, что до него
+                # не доехало, вместо тишины (#220 T2).
+                self._log("status", f"drain: {refusal}")
+                self._pending_messages[0:0] = msgs
+                self.status = AgentStatus.IDLE
+                self._persist()
+                self._turns.publish_turn_finished()
+                self._queue_drain_fact(
+                    "flush", f"не доехало отложенных сообщений: {len(msgs)}",
+                )
             except Exception as e:
                 logger.error(f"[{self.name}] flush pending failed: {e}")
                 self._pending_messages[0:0] = msgs
                 self.status = AgentStatus.IDLE
                 self._persist()
                 self._turns.publish_turn_finished()
         finally:
             self._lifecycle_lock.release()
@@ -2073,16 +2176,17 @@ class AgentSession:
             }
         if permit[2] != compact_stop_gen:
             return abort_compact("compaction cancelled by stop", flush_pending=False)
         self._compact_ack_event = asyncio.Event()
         ack_event = self._compact_ack_event
         ack_deferred = False
         try:
             async def start_ack_turn():
+                _refuse_if_draining(self)  # no await between here and RUNNING below
                 self._manually_interrupted = False
                 self._did_report = False
                 self._turns.bump_turn_gen()
                 self._compact_ack_gen = self._turn_gen
                 self._turn_logs = []
                 self._turn_start = asyncio.get_event_loop().time()
                 self._last_msg_time = self._turn_start
                 self.status = AgentStatus.RUNNING
@@ -2176,16 +2280,22 @@ class AgentSession:
         except Exception as e:
             logger.warning(f"[{self.name}] TG scope-running notify failed: {e}")
 
     async def _rate_limit_retry(self, delay: int) -> None:
         await asyncio.sleep(delay)
         try:
             await self.send("[system] Retrying after rate limit. Continue where you left off.")
             logger.info(f"[{self.name}] rate-limit retry after {delay}s")
+        except DrainingRefused as refusal:
+            self._log("status", f"drain: {refusal}")
+            self.status = AgentStatus.IDLE
+            self._persist()
+            self._turns.publish_turn_finished()
+            self._queue_drain_fact("rate-limit-retry", "повтор после rate limit срезан")
         except Exception as e:
             logger.warning(f"[{self.name}] rate-limit retry failed: {e}")
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
 
     async def _retry_after_server_error(self, delay: int, expected_turn_gen: int) -> None:
         """Resume through a fresh SDK transport after an upstream stream failure."""
@@ -2198,27 +2308,43 @@ class AgentSession:
                     return
                 await self._disconnect_backend()
             await self.send(
                 "[system] Retrying after transient server error. Continue where you "
                 "left off. Do not repeat completed research; execute the pending "
                 "deliverable now."
             )
             logger.info(f"[{self.name}] server-error retry after {delay}s")
+        except DrainingRefused as refusal:
+            self._log("status", f"drain: {refusal}")
+            self.status = AgentStatus.IDLE
+            self._persist()
+            self._turns.publish_turn_finished()
+            self._queue_drain_fact(
+                "server-error-retry", "повтор после сбоя апстрима срезан",
+            )
         except Exception as e:
             logger.warning(f"[{self.name}] server-error retry failed: {e}")
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
 
     async def _auto_continue(self) -> None:
         await asyncio.sleep(1)
         try:
             await self.send("[system] Turn limit reached. Continue where you left off.")
             logger.info(f"[{self.name}] auto-continue after max_turns")
+        except DrainingRefused as refusal:
+            self._log("status", f"drain: {refusal}")
+            self.status = AgentStatus.IDLE
+            self._persist()
+            self._turns.publish_turn_finished()
+            self._queue_drain_fact(
+                "auto-continue", "автопродолжение после лимита ходов срезано",
+            )
         except Exception as e:
             logger.warning(f"[{self.name}] auto-continue failed: {e}")
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
 
     async def _refresh_context_from_api(
         self, *, schedule_compaction_on_success: bool = False,
diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 72794d75b..fa13b09d5 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -3411,19 +3411,26 @@ async def handle_limits(msg: types.Message):
 @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text, lambda msg: msg.text and msg.text.strip() == "/restart")
 async def handle_restart(msg: types.Message):
     if msg.chat.id != config.get("group_id"):
         return
     member = await msg.chat.get_member(msg.from_user.id)
     if member.status not in ("administrator", "creator"):
         await msg.reply("⛔ Only admins can restart.")
         return
-    await msg.reply("🔄 Перезапуск Orchestra...")
-    import subprocess
-    subprocess.Popen(["sudo", "systemctl", "restart", "orchestra"])
+    # Прямой `systemctl` отсюда убивал живые ходы мимо дренажа: мост живёт в ТОМ ЖЕ
+    # процессе, поэтому зовём тот же серверный workflow, что и кнопка дашборда (#220 T4).
+    # Второго пути рестарта не оставляем — именно из-за него дренаж и обходили бы.
+    from app.routes import system
+
+    await msg.reply(
+        "🔄 Перезапуск Orchestra: дренаж запущен, ждём живые ходы. "
+        "Кого всё-таки разорвало — узнает из своего журнала после старта."
+    )
+    await system.restart_server()
 
 
 @dp.message(F.chat.type.in_({"group", "supergroup"}), F.voice)
 async def handle_voice(msg: types.Message):
     orch_name, session = await _resolve_orch(msg)
     if not session:
         return
     t_total = time.monotonic()
diff --git a/tests/test_hot_apply.py b/tests/test_hot_apply.py
new file mode 100644
index 000000000..7a958458c
--- /dev/null
+++ b/tests/test_hot_apply.py
@@ -0,0 +1,465 @@
+"""#220 — применение правок без разрушительного рестарта.
+
+Тесты названы по тикетам плана (docs/tasks/220/plan.md). Написаны ДО реализации и
+коммитятся красными: падают на отсутствующем поведении, а не на импорте.
+
+Бэкенд берётся из `tests.test_session._MockBackend`, а НЕ из `make_backend_mock`:
+у последнего `events()` ждёт вечно, и тест на регрессии зависал бы вместо падения.
+"""
+
+import asyncio
+import os
+import signal
+from unittest.mock import AsyncMock, MagicMock, patch
+
+import pytest
+
+from tests.test_session import _MockBackend
+
+
+@pytest.fixture(autouse=True)
+def _restore_drain_gate():
+    """Гейт дренажа — состояние ЖИВОГО синглтона `manager`, а не фикстуры.
+
+    Прод рассчитывает, что после `begin_drain()` процесс умрёт, поэтому сам гейт
+    обратно не открывается. В тестах `os.kill` подменён — без этой уборки
+    `manager.draining` утекает в следующие файлы, и там всё падает на
+    `DrainingRefused` (поймано pre-mortem: 2 упавших теста при прогоне
+    test_system_restart.py перед test_hot_apply.py).
+    """
+    yield
+    from app.deps import manager
+    manager.end_drain()
+
+
+@pytest.fixture
+def mock_db(monkeypatch):
+    monkeypatch.setattr("app.session.save_session", MagicMock())
+    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
+    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
+
+
+def _worker(**kw):
+    from app.session import AgentSession
+    s = AgentSession(
+        id="t220", name="w1", scope="/s", cwd="/tmp", role="worker",
+        pipeline="default", **kw,
+    )
+    s.session_id = "sid-220"
+    return s
+
+
+async def _run_one_turn(session, backend, message="do the thing"):
+    """Прогнать ровно один ход и вернуть то, что доехало до бэкенда."""
+    with patch.object(session, "_make_backend", return_value=backend):
+        task = asyncio.create_task(session.send(message))
+        for _ in range(200):
+            await asyncio.sleep(0.01)
+            if backend.sent:
+                break
+        backend.finish()
+        try:
+            await asyncio.wait_for(task, timeout=5)
+        finally:
+            await session.stop()
+    assert backend.sent, "бэкенд не получил сообщения — тест не дошёл до проверяемого места"
+    return backend.sent[0]
+
+
+class _FakeSession:
+    """Двойник сессии для дренажа — НЕ `MagicMock`.
+
+    У `MagicMock` любой неизвестный атрибут существует и истинен, поэтому предикат
+    занятости (`is_busy` = ход ИЛИ компактификация) на нём всегда True, и дренаж
+    «не сходится» по вине двойника, а не кода. Поймано ровно так: после добавления
+    `_compacting` в предикат тест завис на дедлайне.
+    """
+
+    def __init__(self, name="w", status=None, compacting=False):
+        from app.session import AgentStatus
+        self.id = f"sid-{name}"
+        self.name = name
+        self.status = status or AgentStatus.RUNNING
+        self._compacting = compacting
+
+    @property
+    def is_busy(self):
+        from app.session import AgentStatus
+        return self.status == AgentStatus.RUNNING or self._compacting
+
+
+# ── T1: промпт пересобирается из файлов на переинжекте ──
+
+@pytest.mark.asyncio
+async def test_t1_reinjected_prompt_rebuilds_role_text_from_disk(mock_db, monkeypatch):
+    """Правка роли в pipelines/ обязана доехать до ЖИВОГО агента без рестарта.
+
+    Сегодня ROLE_SYSTEM_PROMPT зовётся только на spawn/_load_from_db
+    (docs/tasks/220/research.md, F1), поэтому переинжект отдаёт строку, собранную
+    при старте сервера.
+    """
+    import app.manager as manager
+    monkeypatch.setattr(manager, "ROLE_SYSTEM_PROMPT", lambda *a, **k: "NEW-BASE-FROM-DISK")
+
+    s = _worker(prompt_overlay="\n\nOVERLAY-KEEP")
+    s._current_prompt = "OLD-BASE-FROM-STARTUP\n\nOVERLAY-KEEP"
+    s._prompt_injected = False
+
+    sent = await _run_one_turn(s, _MockBackend())
+
+    assert "NEW-BASE-FROM-DISK" in sent, "роль перечитана с диска"
+    assert "OVERLAY-KEEP" in sent, "overlay сохранён при пересборке"
+
+
+@pytest.mark.asyncio
+async def test_t1_guard_custom_full_prompt_is_not_overwritten_by_rebuild(mock_db, monkeypatch):
+    """СТОРОЖ, а не приёмка: зелёный сегодня и обязан остаться зелёным после T1.
+
+    prompt_overlay is None = полная замена промпта через update_worker_prompt.
+
+    Границы компонентов у неё нет (manager.py:1486-1491), поэтому пересборка обязана
+    её НЕ трогать — иначе горячее применение молча снесёт заданную оператором роль.
+    """
+    import app.manager as manager
+    monkeypatch.setattr(manager, "ROLE_SYSTEM_PROMPT", lambda *a, **k: "NEW-BASE-FROM-DISK")
+
+    s = _worker(prompt_overlay=None)
+    s._current_prompt = "CUSTOM-OPERATOR-PROMPT"
+    s._prompt_injected = False
+
+    sent = await _run_one_turn(s, _MockBackend())
+
+    assert "CUSTOM-OPERATOR-PROMPT" in sent
+    assert "NEW-BASE-FROM-DISK" not in sent, "кастомный промпт не перезаписан шаблоном"
+
+
+@pytest.mark.asyncio
+async def test_t1_broken_role_file_falls_back_to_the_startup_prompt(mock_db, monkeypatch):
+    """Битый `pipelines/**` не имеет права убить следующий ход У ВСЕХ агентов.
+
+    Pre-mortem: до T1 живая сессия НЕ звала `ROLE_SYSTEM_PROMPT` после старта, а он
+    падает громко (`ValueError` на нерезолвящейся роли, `manager.py:314`). T1 ставит
+    этот вызов на горячий путь переинжекта — то есть опечатка ровно в тех файлах,
+    редактировать которые фича и поощряет, ломала бы всех сразу. Откат к промпту со
+    старта, но с записью в журнал агента.
+    """
+    import app.manager as manager
+
+    def _explode(*a, **kw):
+        raise ValueError("role 'worker' not resolvable in pipeline 'typo'")
+
+    monkeypatch.setattr(manager, "ROLE_SYSTEM_PROMPT", _explode)
+
+    s = _worker(prompt_overlay="\n\nOVERLAY-KEEP")
+    s._current_prompt = "OLD-BASE-FROM-STARTUP\n\nOVERLAY-KEEP"
+    s._prompt_injected = False
+    logged = []
+    monkeypatch.setattr(s, "_log", lambda kind, text, **kw: logged.append((kind, text)))
+
+    sent = await _run_one_turn(s, _MockBackend())
+
+    assert "OLD-BASE-FROM-STARTUP" in sent, "ход не сорвался, промпт со старта"
+    assert any(k == "error" and "prompt rebuild failed" in t for k, t in logged), \
+        f"провал пересборки назван вслух в журнале агента: {logged}"
+
+
+# ── T2: admission gate на время дренажа ──
+#
+# Контракт после ревью Codex (round 1, blocking #1): `enqueue_fact` — очередь ФАКТОВ,
+# а не сообщений; `_attach_pending_facts` (session.py:731) прямо пишет «исходные
+# сообщения НЕ пересылались» и приписывает факт к какому-то будущему сообщению, сам
+# хода не начиная. Поэтому «положил в очередь = не потеряно» — ложь. Отказ громкий:
+# отправитель получает исключение и повторяет сам; факт кладётся только там, где
+# отправителя нет (внутренние стартеры хода).
+
+
+def _gate(manager):
+    begin = getattr(manager, "begin_drain", None)
+    assert begin is not None, "T2: у SessionManager нет admission-гейта дренажа"
+    return begin
+
+
+@pytest.mark.asyncio
+async def test_t2_new_turn_is_refused_loudly_while_draining(mock_db, monkeypatch):
+    """В режиме дренажа новый ход не начинается, а отправитель узнаёт об этом.
+
+    Тихая постановка в очередь запрещена: durable-очереди СООБЩЕНИЙ в проекте нет,
+    а `enqueue_fact` её не заменяет (см. комментарий выше).
+    """
+    from app.session import AgentStatus
+    import app.session as session_mod
+    from app.deps import manager
+
+    refused = getattr(session_mod, "DrainingRefused", None)
+    assert refused is not None, "T2: нет типа отказа DrainingRefused"
+
+    s = _worker()
+    s.status = AgentStatus.IDLE
+    backend = _MockBackend()
+
+    _gate(manager)()
+    try:
+        with patch.object(s, "_make_backend", return_value=backend):
+            with pytest.raises(refused):
+                await asyncio.wait_for(s.send("work that must not start now"), timeout=5)
+    finally:
+        manager.end_drain()
+
+    assert s.status is AgentStatus.IDLE, "ход не начат"
+    assert backend.sent == [], "в бэкенд ничего не ушло"
+
+
+@pytest.mark.asyncio
+async def test_t2_gate_closes_atomically_against_turn_start(mock_db, monkeypatch):
+    """Гейт обязан проверяться ВПЛОТНУЮ к присвоению RUNNING, без await между ними.
+
+    Дыра, которую тест закрывает: `send()` держит `_lifecycle_lock` от session.py:840
+    до присвоения `status = RUNNING` на 954, но между ними есть await
+    (`_apply_pending_identity_restart`, `_apply_manifest_effort`). Ранняя проверка
+    гейта + await = ход стартует ПОСЛЕ того, как дренаж снял снимок RUNNING-сессий,
+    и попадает ровно под нож.
+    """
+    from app.session import AgentStatus
+    import app.session as session_mod
+    from app.deps import manager
+
+    refused = getattr(session_mod, "DrainingRefused", None)
+    assert refused is not None, "T2: нет типа отказа DrainingRefused"
+
+    s = _worker()
+    s.status = AgentStatus.IDLE
+    backend = _MockBackend()
+
+    async def _close_gate_mid_flight():
+        manager.begin_drain()
+        return False
+
+    _gate(manager)
+    monkeypatch.setattr(s, "_apply_manifest_effort", _close_gate_mid_flight)
+    try:
+        with patch.object(s, "_make_backend", return_value=backend):
+            with pytest.raises(refused):
+                await asyncio.wait_for(s.send("started before the gate closed"), timeout=5)
+    finally:
+        manager.end_drain()
+
+    assert s.status is AgentStatus.IDLE, "ход, начатый в гонке с дренажом, не стартовал"
+    assert backend.sent == [], "в бэкенд ничего не ушло"
+
+
+@pytest.mark.parametrize("starter", [
+    "_flush_pending", "_auto_continue", "_rate_limit_retry", "_retry_after_server_error",
+])
+@pytest.mark.asyncio
+async def test_t2_internal_starter_queues_a_fact_instead_of_starting(
+    mock_db, monkeypatch, starter,
+):
+    """Внутренние стартеры хода начинают его САМИ, без внешнего отправителя.
+
+    `_flush_pending` (session.py:1561) достаёт из `_pending_messages`; `_auto_continue`
+    (:2215), `_rate_limit_retry` (:2179) и `_retry_after_server_error` (:2190) — это
+    автоматические продолжения. Все четверо ловят широкий `except Exception` и гасят
+    сессию в IDLE с одним warning, поэтому голый `DrainingRefused` в них = тихая потеря
+    продолжения (Codex round 2, blocking #1). Отказывать тут некому → факт для агента.
+
+    Два следствия: (1) без гейта дренаж не сходится — конец хода порождает следующий;
+    (2) `enqueue_fact` уместен ровно здесь и больше нигде.
+    """
+    from app.session import AgentStatus
+    import app.session as session_mod
+    from app.deps import manager
+
+    enqueued = []
+    monkeypatch.setattr(
+        session_mod, "enqueue_fact",
+        lambda sid, key, text: (enqueued.append((sid, key, text)), True)[1],
+        raising=False,
+    )
+    # asyncio.sleep НЕ подменяем: подмена в модуле `asyncio` глобальна и утекла бы в
+    # чужие тесты. Секунда из `_auto_continue` дешевле такого риска.
+    s = _worker()
+    s.status = AgentStatus.IDLE
+    s._pending_messages = ["queued before the drain"]
+    backend = _MockBackend()
+
+    _gate(manager)()
+    try:
+        with patch.object(s, "_make_backend", return_value=backend):
+            # у каждого стартера свои аргументы; задержки нулевые, чтобы тест
+            # не подрабатывал измерением времени
+            args = {
+                "_flush_pending": (),
+                "_auto_continue": (),
+                "_rate_limit_retry": (0,),
+                "_retry_after_server_error": (0, s._turn_gen),
+            }[starter]
+            await asyncio.wait_for(getattr(s, starter)(*args), timeout=10)
+    finally:
+        manager.end_drain()
+
+    assert s.status is AgentStatus.IDLE, "ход не начат"
+    assert backend.sent == [], "в бэкенд ничего не ушло"
+    assert enqueued and enqueued[0][0] == s.id, \
+        f"{starter}: агенту оставлен факт о недоставленном, а не тишина"
+
+
+# ── T3: рестарт ждёт живые ходы и имеет безусловный дедлайн ──
+
+@pytest.mark.asyncio
+async def test_t3_restart_drains_before_signalling(monkeypatch):
+    """`/api/restart` обязан дождаться живых ходов, а не убить их через 0.5 с."""
+    from app.routes import system
+    from app.session import AgentStatus
+
+    running = _FakeSession("running", AgentStatus.RUNNING)
+    idle = _FakeSession("idle", AgentStatus.IDLE)
+    monkeypatch.setattr(system, "_drain_sessions", lambda: [running, idle], raising=False)
+    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 30, raising=False)
+    kill = MagicMock()
+    monkeypatch.setattr(system.os, "kill", kill)
+
+    task = asyncio.create_task(system._restart_service_after_response())
+    # сегодня рестарт спит 0.5 с и стреляет; ждём заведомо дольше
+    await asyncio.sleep(1.5)
+    assert not kill.called, "пока идёт ход, сигнала быть не должно"
+
+    running.status = AgentStatus.IDLE
+    await asyncio.wait_for(task, timeout=5)
+    kill.assert_called_once_with(os.getpid(), signal.SIGINT)
+
+
+@pytest.mark.asyncio
+async def test_t3_drain_deadline_is_unconditional_and_reports_cut_turns(monkeypatch):
+    """Ход может не кончиться никогда (research.md F7: цепочки agent→agent).
+
+    Поэтому дедлайн безусловный, а число разорванных ходов называется вслух.
+    """
+    from app.routes import system
+    from app.session import AgentStatus
+
+    stuck = _FakeSession("stuck", AgentStatus.RUNNING)
+    monkeypatch.setattr(system, "_drain_sessions", lambda: [stuck], raising=False)
+    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 0.2, raising=False)
+    kill = MagicMock()
+    monkeypatch.setattr(system.os, "kill", kill)
+
+    result = await asyncio.wait_for(
+        system._restart_service_after_response(), timeout=5,
+    )
+
+    kill.assert_called_once_with(os.getpid(), signal.SIGINT)
+    assert isinstance(result, dict) and result.get("cut_turns") == 1, \
+        "рестарт сообщает, сколько ходов разорвал"
+
+
+@pytest.mark.asyncio
+async def test_t3_drain_outcome_is_persisted_before_the_signal(monkeypatch):
+    """После SIGINT процесса нет — значит отчитаться ПОСЛЕ него физически нельзя.
+
+    Дыра, которую тест закрывает (Codex round 1, blocking #3): `restart_server()`
+    отвечает `{"ok": True, "scheduled": True}` (system.py:1713) и уезжает, а результат
+    дренажа возвращается из фоновой `_restart_service_after_response()`, которую никто
+    не читает. Единственный канал, переживающий рестарт, — запись на диск ДО сигнала.
+    """
+    from app.routes import system
+    from app.session import AgentStatus
+
+    order = []
+    stuck = _FakeSession("stuck", AgentStatus.RUNNING)
+    monkeypatch.setattr(system, "_drain_sessions", lambda: [stuck], raising=False)
+    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 0.2, raising=False)
+    monkeypatch.setattr(system.os, "kill", lambda *a: order.append("kill"))
+
+    record = getattr(system, "_record_restart_outcome", None)
+    assert record is not None, "T3: результат дренажа некуда записать до сигнала"
+    monkeypatch.setattr(
+        system, "_record_restart_outcome",
+        lambda outcome: order.append(("record", outcome.get("cut_turns"))),
+    )
+
+    await asyncio.wait_for(system._restart_service_after_response(), timeout=5)
+
+    assert order == [("record", 1), "kill"], \
+        f"итог дренажа записан до SIGINT, а не после: {order}"
+
+
+@pytest.mark.asyncio
+async def test_t3_broken_recorder_does_not_cancel_the_signal(monkeypatch):
+    """Сбой ПОБОЧНОГО учёта не отменяет рестарт.
+
+    Дедлайн назван безусловным, значит исключение из `_record_restart_outcome()` не
+    имеет права съесть `os.kill` (Codex round 2, suggestion). Это тот же класс, что
+    #215: сбой учёта уничтожал оплаченный результат.
+    """
+    from app.routes import system
+    from app.session import AgentStatus
+
+    kill = MagicMock()
+    monkeypatch.setattr(system, "_drain_sessions",
+                        lambda: [_FakeSession("stuck")], raising=False)
+    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 0.2, raising=False)
+    monkeypatch.setattr(system.os, "kill", kill)
+
+    record = getattr(system, "_record_restart_outcome", None)
+    assert record is not None, "T3: результат дренажа некуда записать до сигнала"
+
+    def _boom(outcome):
+        raise RuntimeError("disk is on fire")
+
+    monkeypatch.setattr(system, "_record_restart_outcome", _boom)
+
+    await asyncio.wait_for(system._restart_service_after_response(), timeout=5)
+
+    kill.assert_called_once_with(os.getpid(), signal.SIGINT)
+
+
+# ── T4: обе точки рестарта ходят через дренаж ──
+
+@pytest.mark.asyncio
+async def test_t4_tg_restart_goes_through_drain_not_systemctl(monkeypatch):
+    """TG `/restart` сегодня зовёт `sudo systemctl restart orchestra` напрямую
+    (`app/tg_bridge.py:3421`) — мимо `/api/restart` и мимо будущего дренажа.
+
+    Мост живёт в ТОМ ЖЕ процессе (`app/main.py:44`), поэтому маршрут — прямой вызов
+    того же серверного workflow, без HTTP-петли на себя.
+    """
+    import subprocess as sp
+    import app.tg_bridge as tg
+    from app.routes import system
+
+    popen = MagicMock()
+    monkeypatch.setattr(sp, "Popen", popen)
+    # AsyncMock, а не MagicMock: `restart_server` — `async def` (system.py:1709), и
+    # хендлер, зовущий её БЕЗ await, в проде не запустил бы ничего, а обычный MagicMock
+    # всё равно отметился бы как `.called` — тест был бы ложнозелёным
+    # (Codex round 2, blocking #2).
+    drained = AsyncMock(return_value={"waited_s": 0.0, "cut_turns": 0})
+    monkeypatch.setattr(system, "restart_server", drained, raising=False)
+
+    msg = MagicMock()
+    msg.chat.id = tg.config.get("group_id")
+    msg.text = "/restart"
+    msg.reply = _AsyncNoop()
+    msg.chat.get_member = _AsyncReturn(MagicMock(status="administrator"))
+
+    await asyncio.wait_for(tg.handle_restart(msg), timeout=5)
+
+    assert not popen.called, \
+        f"TG всё ещё дёргает systemctl напрямую: {popen.call_args_list}"
+    drained.assert_awaited_once_with()
+
+
+class _AsyncNoop:
+    def __init__(self):
+        self.calls = []
+
+    async def __call__(self, *a, **kw):
+        self.calls.append((a, kw))
+
+
+class _AsyncReturn:
+    def __init__(self, value):
+        self.value = value
+
+    async def __call__(self, *a, **kw):
+        return self.value
diff --git a/tests/test_system_restart.py b/tests/test_system_restart.py
index 3ebfd7ab6..50244b18b 100644
--- a/tests/test_system_restart.py
+++ b/tests/test_system_restart.py
@@ -3,35 +3,62 @@
 import asyncio
 import os
 import signal
 from unittest.mock import AsyncMock, MagicMock
 
 import pytest
 
 
+@pytest.fixture(autouse=True)
+def _restore_drain_gate():
+    """Гейт дренажа — состояние ЖИВОГО синглтона `manager`, а не фикстуры.
+
+    Прод рассчитывает, что после `begin_drain()` процесс умрёт, поэтому сам гейт
+    обратно не открывается. В тестах `os.kill` подменён — без этой уборки
+    `manager.draining` утекает в следующие файлы, и там всё падает на
+    `DrainingRefused` (поймано pre-mortem: 2 упавших теста при прогоне
+    test_system_restart.py перед test_hot_apply.py).
+    """
+    yield
+    from app.deps import manager
+    manager.end_drain()
+
+
 @pytest.mark.asyncio
 async def test_restart_endpoint_responds_before_scheduling_service_restart(monkeypatch):
     from app.routes import system
 
     restart = AsyncMock()
     monkeypatch.setattr(system, "_restart_service_after_response", restart)
 
     result = await system.restart_server()
     await asyncio.sleep(0)
 
     assert result == {"ok": True, "scheduled": True}
     restart.assert_awaited_once_with()
 
 
 @pytest.mark.asyncio
 async def test_deferred_restart_signals_current_process_after_response(monkeypatch):
+    """Контракт СМЕНИЛСЯ в #220 T3: между ответом и сигналом теперь дренаж.
+
+    Было: `sleep.assert_awaited_once_with(0.5)` — «единственное ожидание перед
+    сигналом это сброс HTTP-ответа». Это утверждение стало неверным по существу:
+    рестарт ждёт живые ходы до `_DRAIN_DEADLINE_S`. Формально ассерт остался бы
+    зелёным на пустом реестре сессий (цикл выходит сразу), то есть проверял бы
+    ровно то, чего больше нет, — поэтому он заменён, а не подогнан.
+
+    Что проверяется теперь: сигнал по-прежнему уходит, и уходит ПОСЛЕ дренажа,
+    а не вместо него. Ожидание живого хода закрыто отдельно в
+    `tests/test_hot_apply.py::test_t3_restart_drains_before_signalling`.
+    """
     from app.routes import system
 
-    sleep = AsyncMock()
     kill = MagicMock()
-    monkeypatch.setattr(system.asyncio, "sleep", sleep)
     monkeypatch.setattr(system.os, "kill", kill)
+    monkeypatch.setattr(system, "_drain_sessions", lambda: [], raising=False)
 
-    await system._restart_service_after_response()
+    outcome = await system._restart_service_after_response()
 
-    sleep.assert_awaited_once_with(0.5)
     kill.assert_called_once_with(os.getpid(), signal.SIGINT)
+    assert outcome["cut_turns"] == 0, "дренаж на пустом реестре никого не режет"
+    assert outcome["waited_s"] >= 0


## LATER FIX e2e83139f4 (23.9 days later): fix: complete scoped recovery and continuation lifecycle safeguards
lines of origin it changed/deleted: 10
(code only, capped 400 lines)

fix: complete scoped recovery and continuation lifecycle safeguards


diff --git a/app/manager.py b/app/manager.py
index 9ba94dbb6..758a1f3a4 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -2356,28 +2356,33 @@ class SessionManager:
     # промпт берётся отдельным роутом `GET /api/sessions/{name}/prompt` по кнопке 📜,
     # а `last_summary` нужен только серверу (`runtime_handoff`).
     # Понадобилось поле в списке — добавляй осознанно и перемеряй вес: tests/test_manager.py::TestListSessions
     # держит потолок.
     _LIST_OMIT = ("system_prompt", "prompt_overlay", "last_summary")
 
     def list_sessions(self, scope: str | None = None) -> list[dict]:
         from app.db import get_last_turn_map
+        from app.message_deliveries import targets_with_uncertain_delivery
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
+        uncertain_targets = targets_with_uncertain_delivery()
         for r in result:
+            r.setdefault("runtime_connection", "not_loaded")
+            if r["id"] in uncertain_targets:
+                r["delivery_uncertain"] = True
             r["last_turn_ts"] = turn_map.get(r["id"])
             r.update(cache_policy_for_runtime(runtime_for_record(r)))
             lifecycle = self.lifecycle_quarantine(r)
             if lifecycle:
                 r["status"] = "quarantined"
                 r["lifecycle_status"] = lifecycle
             for omit in self._LIST_OMIT:
                 r.pop(omit, None)
diff --git a/app/message_deliveries.py b/app/message_deliveries.py
index cef9d49b0..650047e6e 100644
--- a/app/message_deliveries.py
+++ b/app/message_deliveries.py
@@ -79,17 +79,18 @@ def _queue_block(row: sqlite3.Row | dict) -> dict:
         "arguments": {"delivery_id": head["delivery_id"]},
         "blocked_since": head["updated_at"],
         "retryable": False,
         "message": (
             f"Message accepted but NOT delivered: the target queue has been blocked "
             f"since {head['updated_at']} by delivery {head['delivery_id']}, whose "
             "provider outcome is still unknown. Nothing queued after it moves while "
             "that outcome could still change. Do not resend this message: the next "
-            "restart settles the head and the queue drains on its own."
+                "operator can restart only the target CLI to release the queue; "
+                "the ambiguous message will NOT be resent."
         ),
     }
 
 
 def _next_action(row: sqlite3.Row | dict) -> dict:
     # Блокировка очереди едет в `next_action`, а не отдельным ключом: это единственное
     # поле receipt'а, которое читают потребители остальных доставок и мержей, — второй
     # носитель той же мысли просто никто бы не открыл.
@@ -493,16 +494,24 @@ class MessageDeliveryContext:
 # который мог дослать сообщение, мёртв, поэтому переставить порядок оно уже не может —
 # а именно перестановки и дубля барьер и не допускает. Исход так и остался неизвестным,
 # и запись об этом хранит состояние; блокировать очередь ему больше незачем.
 _TERMINAL_DELIVERY_STATES = (
     "SUBMITTED", "FAILED_BEFORE_SUBMIT", "DELIVERY_UNKNOWN_ORPHANED",
 )
 
 
+def targets_with_uncertain_delivery() -> set[str]:
+    """One batch projection for the session list, not one DB query per worker."""
+    with db._conn() as connection:
+        return {row[0] for row in connection.execute(
+            "SELECT DISTINCT target_session_id FROM message_deliveries WHERE state='DELIVERY_UNKNOWN'"
+        )}
+
+
 def _next_target_delivery(target_session_id: str) -> sqlite3.Row | None:
     placeholders = ",".join("?" * len(_TERMINAL_DELIVERY_STATES))
     with db._conn() as connection:
         return connection.execute(
             f"""SELECT * FROM message_deliveries
                WHERE target_session_id=? AND state NOT IN ({placeholders})
                ORDER BY accept_seq LIMIT 1""",
             (target_session_id, *_TERMINAL_DELIVERY_STATES),
@@ -620,43 +629,59 @@ def _observe_target_runner(task: asyncio.Task[bool]) -> None:
             logger.exception("message delivery runner failed")
     if target is None or not drained:
         return
     head = _next_target_delivery(target)
     if head is not None and head["state"] in {"QUEUED", "PREPARING"}:
         ensure_target_runner(target)
 
 
-async def recover_message_deliveries() -> None:
+def _recover_message_deliveries(target_session_id: str | None) -> tuple[set[str], int]:
+    if target_session_id == "":
+        raise ValueError("target session id must not be empty")
     with db._conn() as connection:
         connection.execute("BEGIN IMMEDIATE")
         orphan_error = RuntimeError("orphaned provider dispatch")
         orphan_error_json = json.dumps(
             {
                 "code": "DELIVERY_OUTCOME_UNKNOWN",
                 "message": (
-                    "Server restarted while provider acceptance was in flight; delivery may "
+                    "Dispatch runtime was stopped while provider acceptance was uncertain; delivery may "
                     "already have been accepted."
                 ),
                 "retryable": False,
                 "outcome_unknown": True,
                 "details": {
                     "phase": "PROVIDER_CALL_STARTED",
                     "exception_type": type(orphan_error).__name__,
                 },
             },
             ensure_ascii=False,
             sort_keys=True,
             separators=(",", ":"),
         )
-        connection.execute(
+        scope_sql = " AND target_session_id=?" if target_session_id is not None else ""
+        scope_args = (target_session_id,) if target_session_id is not None else ()
+        settled = connection.execute(
             """UPDATE message_deliveries
                SET state='DELIVERY_UNKNOWN_ORPHANED', error_json=?, updated_at=?
-               WHERE state IN ('DISPATCHING','DELIVERY_UNKNOWN')""",
-            (orphan_error_json, _now()),
-        )
+               WHERE state IN ('DISPATCHING','DELIVERY_UNKNOWN')""" + scope_sql,
+            (orphan_error_json, _now(), *scope_args),
+        ).rowcount
         rows = connection.execute(
             """SELECT target_session_id FROM message_deliveries
-               WHERE state IN ('QUEUED','PREPARING') ORDER BY accept_seq"""
+               WHERE state IN ('QUEUED','PREPARING')""" + scope_sql + " ORDER BY accept_seq",
+            scope_args,
         ).fetchall()
         targets = {row["target_session_id"] for row in rows}
+    return targets, settled
+
+
+async def recover_message_deliveries(*, target_session_id: str | None = None) -> int:
+    """After runtime teardown, release ambiguous barriers without retrying their payloads.
+
+    Targeted callers must exclude dispatch and new sends until teardown and this
+    transaction finish. The unscoped caller is startup, before dispatch starts.
+    """
+    targets, settled = await asyncio.to_thread(_recover_message_deliveries, target_session_id)
     for target in targets:
         ensure_target_runner(target)
+    return settled
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 93a71b2d0..e2752fd05 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -1284,25 +1284,48 @@ async def rollback_session(name: str, req: ScopeRequest, index: int = -1):
         "runtime": session.backend_type,
         "model": session.model,
         "compacted_at": entry.get("compacted_at"),
     }
 
 
 @router.post("/api/sessions/{name}/restart-cli")
 async def restart_cli(name: str, req: ScopeRequest):
+    from app import message_deliveries
+    from app.manager import _wait_owned_task
+
     session = await manager.ensure_loaded(name, req.scope)
     if not session:
         return JSONResponse({"error": "not found"}, status_code=404)
-    await session._disconnect_backend()
-    session.status = AgentStatus.IDLE
-    session._persist()
-    if session._pending_messages:
-        session._spawn_bg(session._flush_pending())
-    return {"ok": True}
+    delivery_lock = message_deliveries._target_delivery_locks.setdefault(session.id, asyncio.Lock())
+    manager_lock = manager.get_session_lock(session.id)
+    # Fail before mutation, rather than queue a restart behind a send and then
+    # unexpectedly interrupt the newly started turn. Uncontended asyncio locks
+    # acquire without yielding; this order matches the delivery runner.
+    async def restart_locked():
+        locks = (delivery_lock, manager_lock, session._lifecycle_lock)
+        if any(lock.locked() for lock in locks):
+            return JSONResponse({"error": "target is busy; CLI restart made no changes"}, status_code=409)
+        async with delivery_lock, manager_lock, session._lifecycle_lock:
+            session._turn_start_cancel_gen += 1
+            session._manually_interrupted = True
+            session._cancel_precompact_timer("restart_cli")
+            await session._disconnect_backend()
+            settled = await message_deliveries.recover_message_deliveries(target_session_id=session.id)
+            session.status = AgentStatus.IDLE
+            session._persist()
+        if session._pending_messages:
+            session._spawn_bg(session._flush_pending())
+        return {"ok": True, "unreconciled_deliveries": settled}
+
+    # A disconnected HTTP client must not release the locks while a SQLite
+    # recovery thread or runtime teardown is still operating on this session.
+    task = asyncio.create_task(restart_locked())
+    await _wait_owned_task(task)
+    return task.result()
 
 
 @router.post("/api/sessions/{name}/clear-session")
 async def clear_session(name: str, req: ScopeRequest):
     """Drop the conversation thread: next turn starts with an empty history.
 
     Unlike restart-cli (reconnects the backend but keeps session_id), this
     forgets the thread entirely. The worktree, branch and prompt are untouched.
diff --git a/app/session.py b/app/session.py
index 2f1237e80..9e9715686 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1307,17 +1307,19 @@ class AgentSession:
 
         while True:
             await self._lifecycle_lock.acquire()
             # Recheck after admission too: Stop or a newer turn can win while
             # this sender is outside the lock waiting for quota data.
             if retry_generation is not None and (
                 retry_generation != (self._turn_gen, self._turn_start_cancel_gen)
                 or self._manually_interrupted
-                or self.status != AgentStatus.IDLE
+                or (self.status != AgentStatus.IDLE
+                    and not (provenance.subtype in {"turn_limit_continue", "runtime_reconnect"}
+                             and self.status == AgentStatus.RUNNING))
                 or self._compacting
             ):
                 self._lifecycle_lock.release()
                 return
             if self._handoff_recovery_required:
                 self._lifecycle_lock.release()
                 raise RuntimeError(
                     "handoff_recovery_required: operator recovery is required before sends"
@@ -1358,17 +1360,17 @@ class AgentSession:
             if (
                 delivery is not None
                 and not allow_running_delivery
                 and (self._compacting or self.status == AgentStatus.RUNNING)
             ):
                 raise RuntimeError("initial delivery requires an idle session")
             # Both failure classes share the logical request: alternating upstream
             # errors must not replenish each other's retry budget.
-            if provenance.subtype not in {"rate_limit_retry", "server_error_retry"}:
+            if provenance.subtype not in {"rate_limit_retry", "server_error_retry", "runtime_reconnect"}:
                 self._rate_limit_retries = 0
                 self._server_error_retries = 0
             if provenance.subtype != "server_error_retry":
                 self._session_limit_hit = False
             self._safeguard_refusal = ""
 
             self._note_next_precompact_activity()
             capabilities = get_runtime(self.backend_type).capabilities
@@ -2336,35 +2338,46 @@ class AgentSession:
                 self._finish_failed_running_turn(
                     "backend unstable after repeated listener failures"
                 )
                 return
 
             try:
                 if self._backend is None:
                     return
+                generation = (self._turn_gen, self._turn_start_cancel_gen)
                 await self._reconnect_backend()
+                if generation != (self._turn_gen, self._turn_start_cancel_gen) or self._manually_interrupted:
+                    continue
                 logger.info(f"[{self.name}] listener reconnected after error")
                 self._log("status", "listener reconnected")
                 backend = self._backend
                 if (
                     self.status == AgentStatus.RUNNING
                     and hasattr(backend, "active_turn_id")
                     and not getattr(backend, "active_turn_id", None)
                 ):
                     self._finish_failed_running_turn(
                         "listener recovered without an active Codex turn"
                     )
                     return
                 if self.status == AgentStatus.RUNNING:
-                    await self._backend.send("[system] Connection was restored after interruption. Continue your work.")
+                    await self.send(
+                        "[system] Connection was restored after interruption. Continue your work.",
+                        provenance=MessageProvenance(
+                            origin="system", senders=("system",), subtype="runtime_reconnect",
+                        ),
+                        retry_generation=generation,
+                    )
                 continue
             except Exception as re_err:
                 logger.error(f"[{self.name}] listener reconnect failed: {err_text(re_err)}")
                 self._log("error", f"listener reconnect failed: {err_text(re_err)}")
+                if generation != (self._turn_gen, self._turn_start_cancel_gen):
+                    continue
                 self._backend = None
                 self._finish_failed_running_turn(
                     f"listener reconnect failed: {err_text(re_err)}"
                 )
                 return
 
     async def _turn_event_loop(self) -> None:
         logger.info(f"[{self.name}] {self.backend_type} turn started")
@@ -3214,45 +3227,47 @@ class AgentSession:
     async def _notify_scope_running(self) -> None:
         if on_scope_running is None:
             return
         try:
             await on_scope_running(self)
         except Exception as e:
             logger.warning(f"[{self.name}] TG scope-running notify failed: {e}")
 
+    def _finish_failed_continuation(self, generation: tuple[int, int]) -> bool:
+        """An old automatic attempt cannot finish a newer or manually stopped turn."""
+        if generation != (self._turn_gen, self._turn_start_cancel_gen):
+            return False
+        self.status = AgentStatus.IDLE
+        self._persist()
+        self._turns.publish_turn_finished()
+        return True
+
     async def _rate_limit_retry(self, delay: int, expected_turn_gen: int) -> None:
         generation = (expected_turn_gen, self._turn_start_cancel_gen)
         await asyncio.sleep(delay)
         if self._manually_interrupted or self._turn_gen != expected_turn_gen:
             return
         try:
             provenance = MessageProvenance(
                 origin="system", senders=("system",), subtype="rate_limit_retry",
             )
             await self.send(
                 "[system] Retrying after rate limit. Continue where you left off.",
                 provenance=provenance,
                 retry_generation=generation,
             )
         except DrainingRefused as refusal:
-            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+            if not self._finish_failed_continuation(generation):
                 return
             self._log("status", f"drain: {refusal}")
-            self.status = AgentStatus.IDLE
-            self._persist()
-            self._turns.publish_turn_finished()
             self._queue_drain_fact("rate-limit-retry", "повтор после rate limit срезан")
         except Exception as e:
             logger.warning(f"[{self.name}] rate-limit retry failed: {e}")
-            if generation != (self._turn_gen, self._turn_start_cancel_gen):
-                return
-            self.status = AgentStatus.IDLE
-            self._persist()
-            self._turns.publish_turn_finished()
+            self._finish_failed_continuation(generation)
 
     async def _retry_after_server_error(self, delay: int, expected_turn_gen: int) -> None:
         """Resume through a fresh SDK transport after an upstream stream failure."""
         generation = (expected_turn_gen, self._turn_start_cancel_gen)
         await asyncio.sleep(delay)
         try:
             async with self._lifecycle_lock:
                 # A real user message already started a newer turn; it supersedes this
@@ -3269,57 +3284,50 @@ class AgentSession:
             await self.send(
                 "[system] Retrying after transient server error. Continue where you "
                 "left off. Do not repeat completed research; execute the pending "
                 "deliverable now.",
                 provenance=provenance,
                 retry_generation=generation,
             )
         except DrainingRefused as refusal:
-            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+            if not self._finish_failed_continuation(generation):
                 return
             self._log("status", f"drain: {refusal}")
-            self.status = AgentStatus.IDLE
-            self._persist()
-            self._turns.publish_turn_finished()
             self._queue_drain_fact(
                 "server-error-retry", "повтор после сбоя апстрима срезан",
             )
         except Exception as e:
             logger.warning(f"[{self.name}] server-error retry failed: {e}")
-            if generation != (self._turn_gen, self._turn_start_cancel_gen):
-                return
-            self.status = AgentStatus.IDLE
-            self._persist()
-            self._turns.publish_turn_finished()
+            self._finish_failed_continuation(generation)
 
-    async def _auto_continue(self) -> None:
+    async def _auto_continue(self, expected_turn_gen: int) -> None:
+        generation = (expected_turn_gen, self._turn_start_cancel_gen)
         await asyncio.sleep(1)
+        if self._manually_interrupted or self._turn_gen != expected_turn_gen:
+            return
         try: