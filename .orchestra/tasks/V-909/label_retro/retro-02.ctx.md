# Context for retro-02

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/backend_codex.py b/app/backend_codex.py
index d8c5fa894..e663c3318 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -433,97 +433,169 @@ def _orchestra_full_mcp_tools() -> tuple[str, ...]:
         raise RuntimeError(
             f"Orchestra MCP exclusions are not registered: {sorted(stale_exclusions)}"
         )
     # resolve_merge_operation and send_chart were absent only because their registrations
     # postdated the deleted static allowlist; neither omission expressed an access policy.
     return tuple(sorted(registered - _ORCHESTRA_MCP_TOOL_EXCLUSIONS))
 
 
 class CodexProtocolError(RuntimeError):
     """JSON-RPC error returned by Codex app-server."""
 
     def __init__(self, method: str, error: dict):
         self.method = method
         self.error = error
         super().__init__(f"{method}: {error.get('message', 'Codex app-server error')}")
 
 
 class CodexWriterConflictError(RuntimeError):
     """The native thread has an owner this session cannot submit through."""
 
-    def __init__(self, thread_id: str):
+    def __init__(self, thread_id: str, writer_pid: int = 0):
         self.thread_id = thread_id
+        self.writer_pid = writer_pid
         super().__init__(f"Codex thread {thread_id} already has an active writer")
 
     def envelope(self) -> dict:
         return {
             "code": "CODEX_WRITER_CONFLICT",
             "message": str(self),
             "retryable": True,
             "outcome_unknown": False,
             "details": {"thread_id": self.thread_id},
         }
 
 
 def codex_writer_conflict(session_id: str, thread_id: str):
     """Observe Linux's native writer lock without acquiring or unlinking it."""
     if not _SAFE_HOME_KEY.fullmatch(session_id) or not _SAFE_HOME_KEY.fullmatch(thread_id):
         return None
     path = _CODEX_HOME_ROOT / session_id / "thread-writer-locks" / f"{thread_id}.lock"
     try:
         stat = path.stat()
         identity = (os.major(stat.st_dev), os.minor(stat.st_dev), stat.st_ino)
         for line in Path("/proc/locks").read_text().splitlines():
             fields = line.split()
             if len(fields) < 6 or fields[1:4] != ["FLOCK", "ADVISORY", "WRITE"]:
                 continue
             major, minor, inode = fields[5].split(":")
             if (int(major, 16), int(minor, 16), int(inode)) == identity:
-                return CodexWriterConflictError(thread_id)
+                return CodexWriterConflictError(thread_id, int(fields[4]))
     except (OSError, ValueError):
         # An unavailable observation is not permission to take another writer's lock.
         # The native resume remains the authoritative check.
         pass
     return None
 
 
+def stopped_writer_tree(pid: int, *, proc_root: Path = Path("/proc")) -> tuple | None:
+    """Require positive kernel group-stop state for every writer thread and descendant."""
+    if pid <= 0:
+        return None
+    pending = [pid]
+    seen = set()
+    snapshot = []
+    try:
+        while pending:
+            current = pending.pop()
+            if current in seen:
+                continue
+            seen.add(current)
+            tasks = sorted((proc_root / str(current) / "task").iterdir())
+            if not tasks:
+                return None
+            for task in tasks:
+                fields = (task / "stat").read_text().rpartition(")")[2].split()
+                if len(fields) < 20 or fields[0] != "T":
+                    return None
+                started_at = int(fields[19])
+                if started_at <= 0:
+                    return None
+                children = tuple(sorted(int(child) for child in (task / "children").read_text().split()))
+                snapshot.append((current, int(task.name), started_at, children))
+                pending.extend(children)
+        return tuple(sorted(snapshot))
+    except (OSError, ValueError):
+        return None
+
+
+def stopped_codex_writer(session_id: str, thread_id: str) -> tuple | None:
+    """Observe a stopped native-lock owner twice; unavailable evidence never permits a fork."""
+    before = codex_writer_conflict(session_id, thread_id)
+    if before is None or not before.writer_pid:
+        return None
+    tree = stopped_writer_tree(before.writer_pid)
+    if tree is None:
+        return None
+    after = codex_writer_conflict(session_id, thread_id)
+    if after is None or after.writer_pid != before.writer_pid:
+        return None
+    return tree if stopped_writer_tree(after.writer_pid) == tree else None
+
+
+def writer_recovery_notice(history: list) -> dict | None:
+    """Project the durable copy record for both receipt and dashboard consumers."""
+    if isinstance(history, str):
+        try:
+            history = json.loads(history)
+        except (ValueError, TypeError):
+            return None
+    if not isinstance(history, list):
+        return None
+    for entry in reversed(history):
+        if not isinstance(entry, dict) or entry.get("reason") != "writer_conflict_recovery":
+            continue
+        source, target = entry.get("session_id"), entry.get("new_thread_id")
+        return {**entry, "message": (
+            f"Codex thread rebuilt by copying {source} → {target}; "
+            f"persisted snapshot at {entry.get('copied_at')}, "
+            f"last recorded turn {entry.get('through_turn_id') or 'unavailable'}. "
+            "The old writer tree was kernel-stopped and was not killed. "
+            "Unpersisted work is not recovered; native fork may mark a partial turn interrupted. "
+            "Do not resume the old writer alongside the copy."
+        )}
+    return None
+
+
 class CodexBackend(JsonRpcStdioTransport):
     """Persistent Codex app-server client with native turn steering.
 
     One app-server process owns one resumable thread. `send()` starts a turn while idle
     and uses `turn/steer` while that turn is in flight, matching the native Codex TUI.
     """
 
     RUNTIME_LABEL = "Codex app-server"
 
     def __init__(self, model: str, cwd: str, system_prompt: str = "",
                  resume_thread_id: str | None = None,
                  mcp_env: dict[str, str] | None = None,
                  mcp_servers: dict | None = None,
                  reasoning_effort: str = "high",
                  is_orchestrator: bool = False,
                  history_import: object | None = None,
                  validation_profile: bool = False):
         self.model = model
         self.cwd = cwd
         self.system_prompt = system_prompt
         self._thread_id: str | None = resume_thread_id
+        self.writer_fork_proof: tuple | None = None
+        self.writer_fork_recovery: dict | None = None
         self._mcp_env: dict[str, str] = mcp_env or {}
         self._mcp_servers: dict = mcp_servers or {}
         # #224: приватный CODEX_HOME этого агента; готовится лениво в _prepare_codex_home,
         # чтобы конструктор оставался безопасным для вызова без session id.
         self._codex_home: Path | None = None
         # Digest of the managed config actually loaded by the current app-server.
         # Adopted pre-restart processes deliberately start unknown and reconnect before
         # their next idle turn, so config/context upgrades cannot leave them behind.
         self._loaded_config_sha256: str | None = None
         self._is_orchestrator = is_orchestrator
         if history_import is not None and not isinstance(history_import, CodexHistoryImport):
             raise TypeError("history_import must be CodexHistoryImport")
         self._history_import = history_import
         self._validation_profile = validation_profile
         self.reasoning_effort = (
             reasoning_effort if reasoning_effort in CODEX_REASONING_EFFORTS else "high"
         )
         self._proc: Optional[asyncio.subprocess.Process] = None
         self._reader_task: Optional[asyncio.Task] = None
         self._stderr_task: Optional[asyncio.Task] = None
@@ -837,61 +909,94 @@ class CodexBackend(JsonRpcStdioTransport):
                 "model": self.model,
                 "approvalPolicy": "never",
                 "sandbox": "danger-full-access",
             }
             history_import = self._history_import
             developer_instructions = self.system_prompt
             if history_import:
                 developer_instructions = "\n\n".join(filter(None, (
                     developer_instructions,
                     HISTORICAL_TOOL_INSTRUCTION,
                 )))
             if developer_instructions:
                 params["developerInstructions"] = developer_instructions
             requested_thread_id = self._thread_id
             if history_import:
                 params["threadId"] = history_import.thread_id
                 params["history"] = list(history_import.history)
                 resume_started = time.monotonic()
                 result = await self._request("thread/resume", params)
                 self._log_connect_stage("cli_thread_resume_import", resume_started)
+            elif requested_thread_id and self.writer_fork_proof is not None:
+                home = self._managed_codex_home_path()
+                if home is None or stopped_codex_writer(home.name, requested_thread_id) != self.writer_fork_proof:
+                    raise CodexWriterConflictError(requested_thread_id)
+                point = datetime.now(timezone.utc).isoformat()
+                latest = await asyncio.wait_for(self._request("thread/turns/list", {
+                    "threadId": requested_thread_id, "limit": 1, "itemsView": "notLoaded",
+                    "sortDirection": "desc",
+                }), timeout=10)
+                turns = latest.get("data")
+                if (not isinstance(turns, list) or len(turns) > 1 or
+                        (turns and (not isinstance(turns[0], dict) or not turns[0].get("id") or
+                                    turns[0].get("status") not in {"completed", "interrupted", "failed", "inProgress"}))):
+                    raise CodexWriterConflictError(requested_thread_id)
+                if stopped_codex_writer(home.name, requested_thread_id) != self.writer_fork_proof:
+                    raise CodexWriterConflictError(requested_thread_id)
+                params.update(threadId=requested_thread_id, excludeTurns=True)
+                result = await asyncio.wait_for(self._request("thread/fork", params), timeout=10)
+                if stopped_codex_writer(home.name, requested_thread_id) != self.writer_fork_proof:
+                    raise CodexWriterConflictError(requested_thread_id)
+                self.writer_fork_recovery = {
+                    "reason": "writer_conflict_recovery",
+                    "session_id": requested_thread_id,
+                    "new_thread_id": (result.get("thread") or {}).get("id"),
+                    "copied_at": point,
+                    "through_turn_id": turns[0].get("id") if turns else None,
+                    "source_turn_status": turns[0].get("status") if turns else None,
+                    "proof": "kernel_stopped_tree",
+                    "writer_tree": self.writer_fork_proof,
+                }
             elif requested_thread_id:
                 params["threadId"] = requested_thread_id
                 # The app-server otherwise reconstructs and serializes the complete native
                 # history into one JSONL response. Image-heavy threads have exceeded 16 MiB
                 # in production; Orchestra only needs the live subscription and thread id.
                 params["excludeTurns"] = True
                 resume_started = time.monotonic()
                 result = await self._request("thread/resume", params)
                 self._log_connect_stage("cli_thread_resume", resume_started)
             else:
                 start_started = time.monotonic()
                 result = await self._request("thread/start", params)
                 self._log_connect_stage("cli_thread_start", start_started)
             thread_id = ((result.get("thread") or {}).get("id"))
             if not thread_id:
                 raise RuntimeError("Codex app-server returned no thread id")
-            if requested_thread_id and not history_import and thread_id != requested_thread_id:
+            if (requested_thread_id and not history_import and self.writer_fork_recovery is None
+                    and thread_id != requested_thread_id):
                 raise RuntimeError(
                     "Codex app-server resumed a different thread: "
                     f"requested={requested_thread_id}, returned={thread_id}"
                 )
+            if self.writer_fork_recovery is not None and thread_id == requested_thread_id:
+                raise RuntimeError("Codex writer recovery did not create a new thread")
             self._thread_id = thread_id
             if history_import or requested_thread_id:
                 # App-server pins the MCP tool snapshot to a native thread.  Restarting
                 # the CLI and resuming that thread applies removals, but newly added
                 # tools stay absent until the supported reload RPC queues a refresh for
                 # the next active turn.  This preserves thread/context continuity while
                 # making restart-cli a real tool-registry refresh.
                 reload_started = time.monotonic()
                 await self._request("config/mcpServer/reload", None)
                 self._log_connect_stage("mcp_reload", reload_started)
             self._history_import = None
             self._rollout_path = None
             self._teardown_error = None
         except BaseException:
             # Raw descriptors that never reached a transport are ours alone to close; the
             # ones already handed to `attach_owned_pipes` are cleared above and closed by
             # `disconnect()`, so nothing is closed twice.
             for fd in (child_stdin, child_stdout, our_stdin, our_stdout):
                 if fd is not None:
                     try:
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 35e9e1238..1143fafdf 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1387,40 +1387,43 @@ def _message_delivery_receipt_text(
                 "logical message."
             )
         output = (
             f"Message was NOT delivered{target}; delivery_id={delivery_id}; "
             f"state={state}; code={code or 'DELIVERY_NOT_SUBMITTED'}: "
             f"{message or 'Provider submission did not begin'}.\n"
             f"Nothing reached the target: {next_step}"
         )
     elif state == "DELIVERY_UNKNOWN_ORPHANED":
         # Рестарт снял БЛОКИРОВКУ очереди, а не выяснил судьбу сообщения: процесс, который
         # мог его дослать, мёртв, но дошло оно или нет — так и неизвестно. «Accepted» здесь
         # читается как доставка, которой никто не подтверждал.
         output = (
             f"Message delivery outcome is STILL unknown{target}; delivery_id={delivery_id}; "
             f"state={state}: a restart settled this delivery and released the queue, "
             "which did not deliver this message.\n"
             "Do not read this as delivered; confirm with the target before acting."
         )
     else:
         output = f"Message accepted{target}; delivery_id={delivery_id}; state={state}."
+    recovery = receipt.get("runtime_recovery")
+    if isinstance(recovery, dict) and recovery.get("message"):
+        output += "\n" + _safe_response_text(str(recovery["message"]))
     if parent_name and parent_name != WORKER_NAME:
         output += (
             f"\n⚠️ This worker belongs to '{parent_name}'. "
             f"Consider messaging '{parent_name}' instead."
         )
     return output
 
 
 def _ambiguous_message_delivery_error(
     cause: ApiToolError,
     delivery_id: str,
     *,
     status: Any = None,
     status_error: ApiToolError | None = None,
 ) -> ApiToolError:
     reconciliation: Any
     if status_error is not None:
         reconciliation = status_error.envelope()
     else:
         reconciliation = {"status": "missing", "response": status}
diff --git a/app/message_deliveries.py b/app/message_deliveries.py
index fb295e3f0..221aaa30b 100644
--- a/app/message_deliveries.py
+++ b/app/message_deliveries.py
@@ -28,51 +28,56 @@ def _now() -> str:
     return datetime.now(timezone.utc).isoformat()
 
 
 def _validate_id(value: str) -> str:
     value = str(value)
     return str(uuid.UUID(value))
 
 
 def _payload_hash(**payload: object) -> str:
     encoded = json.dumps(
         {"protocol": "direct-message/v1", **payload},
         ensure_ascii=False,
         sort_keys=True,
         separators=(",", ":"),
     ).encode("utf-8")
     return hashlib.sha256(encoded).hexdigest()
 
 
 def _resource(row: sqlite3.Row | dict, *, acceptance: str = "ACCEPTED") -> dict:
     error = json.loads(row["error_json"]) if row["error_json"] else None
+    from app.backend_codex import writer_recovery_notice
+
+    target = db.get_session(row["target_session_id"])
+    recovery = writer_recovery_notice(target.get("session_id_history") or "[]") if target else None
     return {
         "ok": True,
         "acceptance": acceptance,
         "delivery_id": row["delivery_id"],
         "delivery_state": row["state"],
         "payload_hash": row["payload_hash"],
         "accept_seq": row["accept_seq"],
         "status_url": f"/api/message-deliveries/{row['delivery_id']}",
         "provider_ref": row["provider_ref"],
         "error": error,
         "next_action": _next_action(row),
+        "runtime_recovery": recovery,
     }
 
 
 def _queue_block(row: sqlite3.Row | dict) -> dict:
     """Почему принятое сообщение никуда не поедет: неразобранная голова очереди.
 
     Барьер `DELIVERY_UNKNOWN` намеренный (#380 R7), но молчать про него нельзя:
     отправитель получал бодрый `state=QUEUED` на каждое следующее сообщение, воркер
     выглядел живым и глухим, и так простояли 25 часов и три задания.
     """
     head = _next_target_delivery(row["target_session_id"])
     if (
         head is None
         or head["state"] != "DELIVERY_UNKNOWN"
         or head["delivery_id"] == row["delivery_id"]
     ):
         return {}
     return {
         "code": "TARGET_QUEUE_BLOCKED",
         "tool": "message_delivery_status",
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index def4f5b9b..f13449201 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -1139,40 +1139,45 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
                         await manager.send(
                             target.id, fan_barrier.manifest_text(fan_id),
                             provenance=provenance,
                         )
                 return {"ok": True, "buffered": not released,
                         "parent_name": session.parent_name or ""}
         msg = f"[from:{req.sender}] {req.message}" if req.sender else req.message
         if req.sender:
             msg += manager._context_warning(req.sender)
             if hasattr(session, 'last_task_sender'):
                 session.last_task_sender = req.sender
         # Время ставится КАЖДОМУ входящему, включая агентские: юзер требует видеть,
         # когда сообщение написано, а не только от кого (28.08). Раньше метку получал
         # только он сам, и в ленте нельзя было отличить свежий отчёт от вчерашнего.
         msg = add_user_message_time_prefix(msg)
         await manager.send(
             session.id, msg, provenance=provenance,
         )
         pn = session.parent_name or ""
         result = {"ok": True, "parent_name": pn}
+        from app.backend_codex import writer_recovery_notice
+
+        recovery = writer_recovery_notice(getattr(session, "session_id_history", []))
+        if recovery is not None:
+            result["runtime_recovery"] = recovery
         if task_state:
             result["task"] = task_state
         return result
     except LifecycleQuarantineError as e:
         return JSONResponse({"ok": False, "error": e.envelope()}, status_code=409)
     except CodexWriterConflictError as e:
         return JSONResponse({"ok": False, "error": e.envelope()}, status_code=409)
     except QuotaGateError as e:
         return JSONResponse(e.envelope(), status_code=e.status_code)
     except sqlite3.DatabaseError:
         from app import message_deliveries
 
         verification_succeeded = False
         try:
             delivery_id = message_deliveries._validate_id(req.delivery_id)
             committed = message_deliveries._row(delivery_id)
         except (ValueError, sqlite3.DatabaseError):
             committed = None
         else:
             verification_succeeded = True
diff --git a/app/session.py b/app/session.py
index c95b872d3..27d046f6d 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1156,56 +1156,103 @@ class AgentSession:
     async def _worker_admission(self, model: str) -> "QuotaDecision":
         started = time.monotonic()
         try:
             if self._admission_service is not None:
                 return await self._admission_service(model)
             from app.quota_gate import get_worker_admission
 
             return await get_worker_admission(model)
         finally:
             self._log_codex_connect_stage("quota_gate", started)
 
     def codex_writer_error(self):
         if self.backend_type != "codex" or not self.session_id:
             return None
         if self._backend is not None and getattr(self._backend, "is_alive", False):
             return None
         from app.backend_codex import codex_writer_conflict
 
         return codex_writer_conflict(self.id, self.session_id)
 
+    async def _recover_stopped_codex_writer(self, error) -> None:
+        from app.backend_codex import stopped_codex_writer
+
+        if self._backend is not None or self._handoff_recovery_required:
+            raise error
+        proof = await asyncio.to_thread(stopped_codex_writer, self.id, self.session_id)
+        if proof is None:
+            raise error
+        try:
+            backend = await self._ensure_backend(writer_fork_proof=proof, activate=False)
+        except Exception as recovery_error:
+            self._codex_writer_error = error
+            raise error from recovery_error
+        recovery = getattr(backend, "writer_fork_recovery", None)
+        if not isinstance(recovery, dict) or not recovery.get("new_thread_id"):
+            raise error
+        await self._drain_persist()
+        history = (self.session_id_history + [recovery])[-10:]
+        snapshot = self._to_db_dict()
+        snapshot.update(session_id=recovery["new_thread_id"], status="idle",
+                        session_id_history=json.dumps(history))
+        try:
+            await asyncio.get_running_loop().run_in_executor(_db_executor(), save_session, snapshot)
+        except Exception as persistence_error:
+            # This backend was created only for the copy and has never run a turn.
+            await backend.disconnect()
+            if not getattr(backend, "has_owned_processes", False):
+                self._backend = None
+            self._codex_writer_error = error
+            raise error from persistence_error
+        self.session_id_history = history
+        self.session_id = recovery["new_thread_id"]
+        self.status = AgentStatus.IDLE
+        self._turns.publish_turn_finished()
+        self._codex_writer_error = None
+        self._prompt_injected = False
+        self._log("warning", self.writer_recovery_notice()["message"])
+        self._activate_backend_tasks()
+
+    def writer_recovery_notice(self) -> dict | None:
+        from app.backend_codex import writer_recovery_notice
+
+        return writer_recovery_notice(self.session_id_history)
+
     async def preflight_delivery_admission(self) -> None:
         """Check a new direct delivery before its durable receipt is accepted."""
         decision = None
         admitted_model = ""
         admitted_stop_gen = -1
         while True:
             await self._lifecycle_lock.acquire()
             try:
                 await self._recover_adopted_turn()
             except BaseException:
                 self._lifecycle_lock.release()
                 raise
             writer_error = self.codex_writer_error()
             if writer_error is not None:
-                self._lifecycle_lock.release()
-                raise writer_error
+                try:
+                    await self._recover_stopped_codex_writer(writer_error)
+                except BaseException:
+                    self._lifecycle_lock.release()
+                    raise
             if self._handoff_recovery_required:
                 self._lifecycle_lock.release()
                 raise RuntimeError(
                     "handoff_recovery_required: operator recovery is required before sends"
                 )
             # Direct delivery can be injected into an existing turn.  In that case
             # the normal send path intentionally does not consume a new-turn quota.
             if self._compacting or self.status == AgentStatus.RUNNING or self.is_orchestrator:
                 self._lifecycle_lock.release()
                 return
             if decision is None:
                 admitted_model = self.model
                 admitted_stop_gen = self._turn_start_cancel_gen
                 self._lifecycle_lock.release()
                 decision = await self._worker_admission(admitted_model)
                 continue
             if admitted_stop_gen != self._turn_start_cancel_gen or self.model != admitted_model:
                 decision = None
                 self._lifecycle_lock.release()
                 continue
@@ -1265,77 +1312,85 @@ class AgentSession:
         while True:
             await self._lifecycle_lock.acquire()
             # Recheck after admission too: Stop or a newer turn can win while
             # this sender is outside the lock waiting for quota data.
             if retry_generation is not None and (
                 retry_generation != (self._turn_gen, self._turn_start_cancel_gen)
                 or self._manually_interrupted
                 or (self._session_limit_hit and provenance.subtype in {"rate_limit_retry", "server_error_retry"})
                 or (self.status != AgentStatus.IDLE
                     and not (provenance.subtype in {"turn_limit_continue", "runtime_reconnect"}
                              and self.status == AgentStatus.RUNNING))
                 or self._compacting
             ):
                 self._lifecycle_lock.release()
                 return
             if self._handoff_recovery_required:
                 self._lifecycle_lock.release()
                 raise RuntimeError(
                     "handoff_recovery_required: operator recovery is required before sends"
                 )
+            try:
+                await self._recover_adopted_turn()
+                writer_error = self.codex_writer_error()
+                if writer_error is not None:
+                    await self._recover_stopped_codex_writer(writer_error)
+            except BaseException:
+                self._lifecycle_lock.release()
+                raise
             if self._compacting or self.status == AgentStatus.RUNNING or self.is_orchestrator:
                 break
             if decision is None:
                 admitted_model = self.model
                 admitted_stop_gen = self._turn_start_cancel_gen
                 self._lifecycle_lock.release()
                 decision = await self._worker_admission(admitted_model)
                 continue
             if admitted_stop_gen != self._turn_start_cancel_gen:
                 self._lifecycle_lock.release()
                 raise RuntimeError("new worker turn cancelled by stop")
             if self.model != admitted_model:
                 decision = None
                 self._lifecycle_lock.release()
                 continue
             if (
                 decision.state in {"available", "blocked"}
                 and decision.valid_until is not None
                 and time.time() >= decision.valid_until
             ):
                 decision = None
                 self._lifecycle_lock.release()
                 continue
             try:
                 from app.quota_gate import require_worker_admission
 
                 require_worker_admission(decision)
             except BaseException:
                 self._lifecycle_lock.release()
                 raise
             break
 
         try:
             await self._recover_adopted_turn()
             writer_error = self.codex_writer_error()
             if writer_error is not None:
-                raise writer_error
+                await self._recover_stopped_codex_writer(writer_error)
             if (
                 delivery is not None
                 and not allow_running_delivery
                 and (self._compacting or self.status == AgentStatus.RUNNING)
             ):
                 raise RuntimeError("initial delivery requires an idle session")
             # Both failure classes share the logical request: alternating upstream
             # errors must not replenish each other's retry budget.
             if provenance.subtype not in {"rate_limit_retry", "server_error_retry", "runtime_reconnect"}:
                 self._rate_limit_retries = 0
                 self._server_error_retries = 0
             if provenance.subtype != "server_error_retry":
                 self._session_limit_hit = False
 
             self._note_next_precompact_activity()
             capabilities = get_runtime(self.backend_type).capabilities
             if self._compacting:
                 if delivery is not None and allow_running_delivery:
                     return
                 self._pending_messages.append(message)
@@ -2009,40 +2064,41 @@ class AgentSession:
             handoff_id=record["handoff_id"],
             packet=packet,
             packet_sha256=record["packet_sha256"],
             snapshot_log_id=int(record["snapshot_log_id"]),
             pending_effects=0,
             unresolved_effects=unresolved,
             expected_capability_sha256=capability_sha,
             expected_capability=stored_capability,
             project_docs=frozen_project_docs,
             operation_status=str(record["status"]),
             operation_failure_code=record.get("failure_code"),
         )
 
     async def _ensure_backend(
         self,
         force_fresh: bool = False,
         history_import=None,
         exclude_history_users: tuple[str, ...] = (),
         activate: bool = True,
         _allow_codex_oversize_retry: bool = True,
+        writer_fork_proof: tuple | None = None,
     ):
         if self._backend is not None:
             if not force_fresh:
                 if self._runtime_error:
                     raise RuntimeError(f"runtime connection failed; reconnect this CLI before sending: {self._runtime_error}")
                 return self._backend
             await self._disconnect_backend()
         project_path = self.worktree_path or self.cwd
         if self.backend_type == "codex" and project_path:
             # Codex reads AGENTS.md, not CLAUDE.md. Refresh the mirror before the CLI starts,
             # otherwise a long-lived worker keeps the project rules from its spawn day.
             # Orchestrators have no worktree, so cwd must be included too; omitting it left
             # every root Codex orchestrator without its repository's CLAUDE.md rules.
             agents_started = time.monotonic()
             try:
                 from app.workspace import sync_agents_md
                 await asyncio.to_thread(sync_agents_md, project_path)
             except Exception as e:
                 logger.warning(f"[{self.name}] AGENTS.md mirror refresh failed: {e}")
             finally:
@@ -2056,40 +2112,42 @@ class AgentSession:
         if (
             history_import is None
             and not force_fresh
             and self.backend_type == "claude"
             and self.history_import_source == CLAUDE_HISTORY_SOURCE
             and self.session_id
         ):
             history_import = await self._build_claude_history_import(
                 self.session_id,
                 self.model,
                 exclude_history_users,
             )
         if history_import is None:
             self._backend = self._make_backend(force_fresh=force_fresh)
         else:
             self._backend = self._make_backend(
                 force_fresh=force_fresh,
                 history_import=history_import,
             )
         candidate = self._backend
+        if writer_fork_proof is not None:
+            candidate.writer_fork_proof = writer_fork_proof
         try:
             await candidate.connect()
         except NativeHistoryImportError as error:
             self._runtime_error = err_text(error)
             logger.warning("[%s] native history import failed", self.name)
             if not getattr(candidate, "has_owned_processes", False):
                 self._backend = None
             self._finish_failed_running_turn("native history import failed")
             raise
         except Exception as e:
             self._runtime_error = err_text(e)
             logger.error(f"[{self.name}] backend connect failed: {err_text(e)}")
             self._log("error", f"connect failed: {err_text(e)}")
             from app.backend_codex import CodexProtocolError, CodexWriterConflictError
 
             if (self.backend_type == "codex" and isinstance(e, CodexProtocolError)
                     and "already has an active writer" in str(e)):
                 e = CodexWriterConflictError(self.session_id or "")
                 self._codex_writer_error = e
             oversized_failure = (
@@ -5329,40 +5387,41 @@ class AgentSession:
         writer_error = self._writer_health_error()
         if self._adopted_recovery_pending:
             runtime_connection = "recovering"
         elif writer_error is not None:
             runtime_connection = "writer_conflict"
         elif self._runtime_error:
             runtime_connection = "failed"
         elif self._hibernated:
             runtime_connection = "hibernated"
         elif self._backend is None:
             runtime_connection = "detached"
         elif self._listen_task is not None and not self._listen_task.done():
             runtime_connection = "listening"
         else:
             runtime_connection = "attached"
         return {
             "id": self.id, "name": self.name, "scope": self.scope,
             "cwd": self.cwd, "worktree_path": self.worktree_path,
             "status": "broken" if writer_error is not None else self._display_status(), "model": self.model,
             "runtime_connection": runtime_connection,
+            "runtime_recovery": self.writer_recovery_notice(),
             "runtime_error": writer_error.envelope() if writer_error else self._runtime_error or None,
             "cost_usd": round(self.cost_usd, 4),
             "cost_usd_cached": round(self.cost_usd_cached, 4),
             "branch": self.branch,
             "base_branch": self.base_branch,
             "needs_switch": self.needs_switch,
             "is_orchestrator": self.is_orchestrator,
             "role": self.role, "parent_id": self.parent_id, "parent_name": self.parent_name,
             "color": self.color,
             "created_at": self.created_at.isoformat(),
             "context_pct": self._last_context.get("percentage", 0),
             "progress_pct": self.progress_pct,
             "progress_status": self.progress_status,
             "backend_type": self.backend_type,
             "runtime": self.backend_type,
             "provider": get_model_spec(self.model).provider,
             "hibernated": self._hibernated,
             "task_id": self.task_id,
             "description": self.description,
             "disabled_tools": self.disabled_tools,
diff --git a/app/static/js/utils.js b/app/static/js/utils.js
index 33a5cfb65..6d87601ed 100644
--- a/app/static/js/utils.js
+++ b/app/static/js/utils.js
@@ -1,33 +1,33 @@
 /* utils.js — pure helpers, marked setup, autolink. Loaded before app.js. */
 
 function _runtimeStatusDetail(session) {
     const labels = {
         not_loaded: 'runtime не загружен',
         hibernated: 'runtime в гибернации',
         detached: 'runtime отключён',
         attached: 'runtime подключён; читатель событий не активен',
         listening: 'читатель событий активен',
         failed: 'ошибка подключения runtime',
         writer_conflict: 'тред занят другим процессом',
     };
-    return [labels[session.runtime_connection], (typeof session.runtime_error === 'object' ? session.runtime_error?.message : session.runtime_error), session.lifecycle_status?.message,
+    return [labels[session.runtime_connection], (typeof session.runtime_error === 'object' ? session.runtime_error?.message : session.runtime_error), session.lifecycle_status?.message, session.runtime_recovery?.message,
         session.delivery_uncertain
             ? 'доставка не подтверждена; для освобождения очереди перезапусти CLI этого агента (без повторной отправки)' : '']
         .filter(Boolean).join(' · ');
 }
 
 // Client task/payment amounts use the configured billing currency; model costs are stored in USD.
 const CUR = document.body.dataset.currency || '₽';
 const MODEL_COST_CURRENCY = '$';
 const $ = (s) => document.querySelector(s);
 const taskNum = (par) => String(par || '').replace(/^[A-Z]+-/, '');
 
 const _PROVIDER_COLORS = {
     anthropic: '#fb923c', openai: '#22c55e', 'x-ai': '#e2e8f0',
     openrouter: '#a78bfa', deepseek: '#60a5fa',
     unknown: '#94a3b8',
 };
 
 // === Кеш последнего успешного ответа (#197) ===
 // Канал юзера теряет ~17% TLS-хендшейков. Провал в середине сессии переживают те панели,
 // что держат данные в памяти, а вот ЗАГРУЗКА страницы не переживает ничего: память пуста,
diff --git a/tests/test_writer_fork_537.py b/tests/test_writer_fork_537.py
new file mode 100644
index 000000000..3f9c426c2
--- /dev/null
+++ b/tests/test_writer_fork_537.py
@@ -0,0 +1,219 @@
+"""Recovery must not mistake a sleeping writer or its running child for a stopped tree."""
+import asyncio
+from types import SimpleNamespace
+from unittest.mock import AsyncMock
+
+import pytest
+
+from app import backend_codex, db as database, message_deliveries
+from app.backend_codex import CodexBackend, CodexWriterConflictError, stopped_writer_tree
+from tests.test_backend_codex import _FakeProcess
+from tests.test_fd_adopt import db, _save_running_session
+from tests.test_session import mock_db, session
+
+
+def _task(root, pid, tid=None, state='T', children='', start=123):
+    directory = root / str(pid) / 'task' / str(tid or pid)
+    directory.mkdir(parents=True)
+    fields = [state] + ['0'] * 18 + [str(start)]
+    (directory / 'stat').write_text(f'{tid or pid} (worker with spaces) ' + ' '.join(fields))
+    (directory / 'children').write_text(children)
+
+
+def test_only_positive_group_stop_allows_copy(tmp_path):
+    _task(tmp_path, 10, children='20')
+    _task(tmp_path, 10, tid=11)
+    _task(tmp_path, 20)
+    assert stopped_writer_tree(10, proc_root=tmp_path) == (
+        (10, 10, 123, (20,)), (10, 11, 123, ()), (20, 20, 123, ()))
+
+
+def test_sleeping_writer_is_not_inactive_proof(tmp_path):
+    _task(tmp_path, 10, state='S')
+    assert stopped_writer_tree(10, proc_root=tmp_path) is None
+
+
+def test_live_descendant_denies_copy_even_if_writer_stopped(tmp_path):
+    _task(tmp_path, 10, children='20')
+    _task(tmp_path, 20, state='R')
+    assert stopped_writer_tree(10, proc_root=tmp_path) is None
+
+
+def test_one_live_thread_denies_copy(tmp_path):
+    _task(tmp_path, 10)
+    _task(tmp_path, 10, tid=11, state='S')
+    assert stopped_writer_tree(10, proc_root=tmp_path) is None
+
+
+def test_missing_descendant_and_unknown_identity_deny_copy(tmp_path):
+    _task(tmp_path, 10, children='20')
+    assert stopped_writer_tree(10, proc_root=tmp_path) is None
+    assert stopped_writer_tree(0, proc_root=tmp_path) is None
+
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize('stopped', [True, False, 'revoked', 'query_timeout', 'fork_timeout'])
+async def test_admission_forks_only_positive_stopped_proof_and_exposes_copy(
+    db, session, monkeypatch, tmp_path, stopped,
+):
+    _save_running_session(session.id, thread='source-537')
+    monkeypatch.setattr('app.session.save_session', database.save_session)
+    session.backend_type = 'codex'
+    session.session_id = 'source-537'
+    session.is_orchestrator = True
+    session._refresh_skills = AsyncMock()
+    session._refresh_codex_project_doc = AsyncMock()
+    session._activate_backend_tasks = lambda: None
+    proof = ((99, 99, 123, ()),)
+    observations = iter([proof, proof, None]) if stopped == 'revoked' else None
+    monkeypatch.setattr(backend_codex, 'stopped_codex_writer',
+                        lambda *args: next(observations) if observations is not None else (proof if stopped else None))
+    monkeypatch.setattr(backend_codex, 'codex_writer_conflict',
+                        lambda sid, tid: CodexWriterConflictError(tid, 99) if tid == 'source-537' else None)
+    monkeypatch.setattr(backend_codex, '_codex_scope_support',
+                        AsyncMock(return_value=(True, {'XDG_RUNTIME_DIR': '/test', 'DBUS_SESSION_BUS_ADDRESS': 'test'}, 'test scope')))
+    spawn = AsyncMock(return_value=_FakeProcess())
+    monkeypatch.setattr(backend_codex.asyncio, 'create_subprocess_exec', spawn)
+    backend = CodexBackend(model='gpt-5.6-luna', cwd='/tmp', resume_thread_id='source-537')
+    monkeypatch.setattr(backend, '_managed_codex_home_path', lambda: tmp_path / session.id)
+    backend._build_env = lambda: {}
+    backend._read_stdout = AsyncMock()
+    backend._drain_stderr = AsyncMock()
+    backend._notify = AsyncMock()
+    backend._reload_stale_managed_config_before_turn = AsyncMock()
+    backend.disconnect = AsyncMock()
+    if stopped in ('query_timeout', 'fork_timeout'):
+        original_wait_for = asyncio.wait_for
+        async def bounded_test_wait(awaitable, timeout):
+            return await original_wait_for(awaitable, 0.01 if timeout == 10 else timeout)
+        monkeypatch.setattr(asyncio, 'wait_for', bounded_test_wait)
+    async def request(method, params):
+        if ((stopped == 'query_timeout' and method == 'thread/turns/list') or
+                (stopped == 'fork_timeout' and method == 'thread/fork')):
+            await asyncio.Event().wait()
+        if method == 'thread/turns/list':
+            return {'data': [{'id': 'old-turn', 'status': 'completed'}]}
+        if method == 'thread/fork':
+            assert params['threadId'] == 'source-537'
+            return {'thread': {'id': 'copy-537'}}
+        if method == 'turn/start':
+            assert params['threadId'] == 'copy-537'
+            return {'turn': {'id': 'new-turn'}}
+        return {}
+    backend._request = AsyncMock(side_effect=request)
+    backend.connect = backend._connect_unlocked
+    session._make_backend = lambda **kwargs: backend
+    if stopped is not True:
+        with pytest.raises(CodexWriterConflictError):
+            await session.preflight_delivery_admission()
+        if stopped is False:
+            spawn.assert_not_awaited()
+            backend._request.assert_not_awaited()
+        else:
+            spawn.assert_awaited_once()
+            methods = [call.args[0] for call in backend._request.await_args_list]
+            assert methods.count('thread/fork') == (1 if stopped == 'fork_timeout' else 0)
+            assert 'turn/start' not in methods
+            for task in (backend._reader_task, backend._stderr_task):
+                if task:
+                    await asyncio.gather(task, return_exceptions=True)
+        assert session.to_dict()['runtime_error']['code'] == 'CODEX_WRITER_CONFLICT'
+        assert session.session_id == 'source-537'
+        return
+    try:
+        await session.preflight_delivery_admission()
+        assert session.session_id == 'copy-537'
+        assert session.status.value == 'idle'
+        assert [c.args[0] for c in backend._request.await_args_list].count('thread/fork') == 1
+        assert 'thread/resume' not in [c.args[0] for c in backend._request.await_args_list]
+        await backend.send('new delivery')
+        assert backend.active_turn_id == 'new-turn'
+        notice = session.to_dict()['runtime_recovery']
+        assert notice['session_id'] == 'source-537'
+        assert notice['new_thread_id'] == 'copy-537'
+        assert notice['through_turn_id'] == 'old-turn'
+        assert notice['proof'] == 'kernel_stopped_tree'
+        assert notice['message']
+        # The durable receipt reads the same committed provenance, surviving a restart.
+        monkeypatch.setattr(message_deliveries, '_next_action', lambda row: {})
+        receipt = message_deliveries._resource({
+            'target_session_id': session.id, 'error_json': None, 'delivery_id': 'delivery-537',
+            'state': 'SUBMITTED', 'payload_hash': 'hash', 'accept_seq': 1, 'provider_ref': 'new-turn',
+        })
+        assert receipt['runtime_recovery']['new_thread_id'] == 'copy-537'
+        assert receipt['runtime_recovery']['copied_at'] == notice['copied_at']
+        from app.mcp_stdio import _message_delivery_receipt_text
+        rendered = _message_delivery_receipt_text(receipt)
+        assert 'source-537' in rendered and 'copy-537' in rendered
+        backend.disconnect.assert_not_awaited()
+    finally:
+        for task in (backend._reader_task, backend._stderr_task):
+            if task:
+                await asyncio.gather(task, return_exceptions=True)
+        await session._drain_persist()
+
+
+def test_changed_lock_owner_denies_copy(monkeypatch):
+    owners = iter([CodexWriterConflictError('source', 10), CodexWriterConflictError('source', 20)])
+    monkeypatch.setattr(backend_codex, 'codex_writer_conflict', lambda *args: next(owners))
+    monkeypatch.setattr(backend_codex, 'stopped_writer_tree', lambda pid: ((pid, pid, 123, ()),))
+    assert backend_codex.stopped_codex_writer('session', 'source') is None
+
+
+def test_changed_process_generation_denies_copy(monkeypatch):
+    monkeypatch.setattr(backend_codex, 'codex_writer_conflict',
+                        lambda *args: CodexWriterConflictError('source', 10))
+    snapshots = iter([((10, 10, 123, ()),), ((10, 10, 456, ()),)])
+    monkeypatch.setattr(backend_codex, 'stopped_writer_tree', lambda pid: next(snapshots))
+    assert backend_codex.stopped_codex_writer('session', 'source') is None
+
+
+@pytest.mark.asyncio
+async def test_copy_not_published_when_durable_provenance_fails(session, monkeypatch):
+    session.backend_type = 'codex'
+    session.session_id = 'source-537'
+    monkeypatch.setattr(backend_codex, 'stopped_codex_writer', lambda *args: ((99, 99, 123, ()),))
+    copied = SimpleNamespace(writer_fork_recovery={
+        'reason': 'writer_conflict_recovery', 'session_id': 'source-537',
+        'new_thread_id': 'uncommitted-copy', 'copied_at': 'test-point',
+    }, disconnect=AsyncMock(), has_owned_processes=False)
+    async def create(**kwargs):
+        session._backend = copied
+        return copied
+    session._ensure_backend = create
+    def failed_save(snapshot):
+        assert snapshot['session_id'] == 'uncommitted-copy'
+        raise OSError('local checkpoint failed')
+    monkeypatch.setattr('app.session.save_session', failed_save)
+    with pytest.raises(CodexWriterConflictError):
+        await session._recover_stopped_codex_writer(CodexWriterConflictError('source-537'))
+    assert session.session_id == 'source-537'
+    assert not session.session_id_history
+    assert session._backend is None
+    copied.disconnect.assert_awaited_once()
+
+
+@pytest.mark.asyncio
+async def test_recovered_copy_requires_new_turn_quota_even_if_old_state_running(session):
+    from app.events import MessageProvenance
+    from app.session import AgentStatus
+
+    class AdmissionRefused(Exception):
+        pass
+
+    session.backend_type = 'codex'
+    session.session_id = 'source-537'
+    session.status = AgentStatus.RUNNING
+    session.codex_writer_error = lambda: CodexWriterConflictError('source-537') if session._backend is None else None
+    async def recover(error):
+        session._backend = SimpleNamespace(is_alive=True)
+        session.status = AgentStatus.IDLE
+    session._recover_stopped_codex_writer = AsyncMock(side_effect=recover)
+    session._worker_admission = AsyncMock(side_effect=AdmissionRefused())
+    session._ensure_backend = AsyncMock(side_effect=AssertionError('provider must not be reached'))
+    with pytest.raises(AdmissionRefused):
+        await session.send('delivery', provenance=MessageProvenance(origin='user', senders=('user',)))
+    session._worker_admission.assert_awaited_once()
+    session._ensure_backend.assert_not_awaited()
+    assert not session._lifecycle_lock.locked()


## Later history of the touched files on main (after this commit)

109 later commits touch these paths; the first 40 (oldest first):
ae30028d3 2026-09-08 Remove unreachable cross-runtime canary pipeline and retired rule API
f5713f4df 2026-09-08 Retire legacy review gates and fix adopted Codex writer release
98574f427 2026-09-08 Replace duplicate task stores with private Git and one versioned SQLite projection
59fe32bc4 2026-09-08 Merge remote-tracking branch 'origin/main' into codex/retire-legacy-review
fc0d5143d 2026-09-08 Merge current main into storage simplification
5f7e72c50 2026-09-08 Add reusable idle watches and label dashboard message channel
d9ce293fa 2026-09-08 Integrate current main before storage cutover
9a1735f16 2026-09-09 Simplify agent knowledge and retire mandatory memory paperwork
e6da7e30a 2026-09-10 #537: stop runtime trees with Orchestra and remove live adoption
3e068562f 2026-09-11 V-544: #V-544: тяжёлое фото уходит документом, отказ провайдера терминален, лимиты названы
360c846b7 2026-09-12 V-555: #V-555: replace retired fan launcher with dynamic workflows
156683d4a 2026-09-12 V-556: add dashboard after-turn queue
4c8cb1d70 2026-09-12 каталог: убрать неиспользуемые GPT-5.4 и 5.4 Mini вместе с их устаревшими тарифами
b15940ba5 2026-09-12 V-562: preserve steered messages after failed turns
0c3c0fcb0 2026-09-15 V-575: про ветку воркера при мерже спрашивают git, а не вторую запись платформы
b112d9b32 2026-09-17 #V-584: подписи окон Codex по длительности, как у Claude
0e6b568fe 2026-09-17 V-590: #V-590: analytics.js и utils.js на английском, русский перевод в словарь
902e86597 2026-09-19 #V-603: отказ привязки задачи объясняет причину, описание spawn_worker — правила
643d47211 2026-09-20 #V-597: модельное ревью заморожено — тул codex_review снят с регистрации, скилл и правила закомментированы
88c25b2a1 2026-09-20 #V-599: merge_worker снова синхронный — ждёт исход до 10 с и снимает лишнее пробуждение
f6d969c1c 2026-09-20 V-602: update MCP descriptions and parallelize agent listing
c70bb37e5 2026-09-20 #V-599: описание change_worker_model врало про потерю диалога — внутри рантайма история сохраняется
4bd1a5365 2026-09-21 V-603: clarify worker refusals and background receipts
7f291ae99 2026-09-21 V-606: #V-606: compact idle sessions before cache expiry
bff111c8e 2026-09-21 #V-607: окно синхронного мержа 10 → 25 с, иначе гейт мутации выталкивает 82% мержей в фон
b96627288 2026-09-21 #V-607: окно синхронного мержа 60 с — замер гейта мутации на реальных диффах дал 14-17 с
2dcbfba99 2026-09-22 V-609: #V-609: persist provider cost baseline across restart
bbfd3641c 2026-09-22 V-585: WIP V-585: GigaChat харнес-маршрут, незавершённая работа до смены модели
a6fe16bfc 2026-09-22 V-614: тень-гейт «DONE без прошедшей проверки после последней правки»
8941811c9 2026-09-22 V-610: rewrite third-party code in app/ with own implementation
de5d62a52 2026-09-22 V-576: #V-576: каталог проектов файлом и теги задач вместо второй сущности проекта
0f973de21 2026-09-23 V-620: switch_worker_branch releases a worker left bound after merge(continue)
f197e2958 2026-09-23 V-620: полный счёт токенов и денег по пяти моделям; ставки GPT-6 в таблице Codex
628ac2058 2026-09-23 Маршрут по умолчанию: luna → GPT-6 Luna, sol → GPT-6 Sol (Sol закрыт для агентов)
9c5e64087 2026-09-23 V-621: WIP #V-621: каталог проектов — файл на каждый scope вместо одного общего
6cfb55e08 2026-09-23 Отчёт о сжатии: контекст одного обращения вместо суммы за ход
b3aae161b 2026-09-24 V-627: allow scheduled precompact with background jobs
759b3be64 2026-09-24 V-628: collapse incoming Telegram topic messages
63fd7ac22 2026-09-24 V-631: #V-631: merge taskless adhoc work against explicit task
7ae410f8d 2026-09-24 V-621: разбить общий каталог проектов на файлы по scope

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### ae30028d3 Remove unreachable cross-runtime canary pipeline and retired rule API

diff --git a/app/session.py b/app/session.py
index 349dc4f78..ed088c499 100644
--- a/app/session.py
+++ b/app/session.py
@@ -42,18 +42,14 @@ from app.runtime_history import (
     NativeHistoryImportError,
     NativeHistoryRejected,
     PreparationResult,
     ModelVisibleManifest,
     build_model_visible_manifest,
-    build_runtime_delivery_packet,
-    build_runtime_packet_fallback,
     build_runtime_state_packet,
     classify_handoff_effects,
-    classify_handoff_failure,
     describe_handoff_effects,
     preflight_runtime_handoff,
-    runtime_packet_sha256,
     render_claude_history,
 )
 from app.session_cost import CostTracker
 from app.session_hibernate import HibernateManager
 from app.session_state import (  # noqa: F401 — re-exported: importers use app.session.AgentStatus
@@ -69,11 +65,11 @@ from app.usage_contract import KnownContext, current_context
 if TYPE_CHECKING:
     from app.backend_protocol import BackendLike
     from app.quota_gate import QuotaDecision
 from app.db import (
     add_log, allocate_runtime_handoff_attempt, confirm_runtime_handoff,
-    enqueue_fact, get_history_logs, get_logs, get_profile, get_runtime_handoff,
+    enqueue_fact, get_history_logs, get_logs, get_runtime_handoff,
     get_latest_runtime_handoff_for_session, list_runtime_handoff_attempts,
     prepare_runtime_handoff_snapshot, retire_runtime_handoff, save_session,
     tool_error_add, update_runtime_handoff_attempt, update_runtime_handoff_status,
 )
 from app.errtext import err_text
@@ -3589,30 +3585,10 @@ class AgentSession:
                 "path": relative,
                 "content": path.read_text(encoding="utf-8"),
             })
         return documents
 
-    def _handoff_preflight_manifest(
-        self,
-        target_model: str,
-        *,
-        prepared,
-        project_docs: list[dict],
-        native_context_tokens: int | None = 0,
-    ):
-        adapter = self._make_backend(
-            force_fresh=True,
-            validation_profile=False,
-            config_dir_override="",
-            model_override=target_model,
-        )
-        manifest = adapter.build_handoff_manifest(
-            prepared, validation_profile=True
-        )
-        return preflight_runtime_handoff(
-            manifest, native_context_tokens=native_context_tokens
-        )
 
     @staticmethod
     def _handoff_cleanup_locator(handoff_id: str, attempt_no: int) -> str:
         return str(_HANDOFF_STAGING_ROOT / handoff_id / str(attempt_no))
 
@@ -3710,432 +3686,10 @@ class AgentSession:
 
         self._handoff_recovery_required = False
         if self._backend is not None:
             self._activate_backend_tasks()
 
-    def _prepare_handoff_staging_dir(self, runtime: str, locator: str) -> str | None:
-        """Create the provider-owned staging home before any target process starts."""
-        path = Path(locator)
-        path.mkdir(parents=True, exist_ok=True, mode=0o700)
-        path.chmod(0o700)
-        if runtime != "claude":
-            return None
-        profile = get_profile(self.profile) if self.profile else None
-        source_root = Path(os.path.expanduser(
-            str((profile or {}).get("config_dir") or os.environ.get(
-                "CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")
-            ))
-        )).resolve()
-        credentials = source_root / ".credentials.json"
-        if not credentials.is_file():
-            return "authentication"
-        destination = path / ".credentials.json"
-        if not destination.exists():
-            destination.symlink_to(credentials)
-        return None
-
-    async def _retire_handoff_attempt(self, prepared, attempt, staged, code: str) -> None:
-        await self._retire_staged_handoff(staged)
-        locator = str(getattr(attempt, "cleanup_locator", ""))
-        if locator:
-            await asyncio.to_thread(self._remove_handoff_cleanup_locator, locator)
-        if get_runtime_handoff(prepared.handoff_id):
-            now = datetime.now(timezone.utc).isoformat()
-            update_runtime_handoff_attempt(
-                prepared.handoff_id,
-                int(attempt.attempt_no),
-                status="retired",
-                error_code=code,
-                retired_at=now,
-            )
-
-    async def _stage_runtime_handoff_target(
-        self,
-        prepared,
-        *,
-        target_model: str,
-        mode: str,
-    ) -> dict:
-        ledger_packet = prepared.packet
-        if ledger_packet.get("integrity") and runtime_packet_sha256(
-            ledger_packet
-        ) != getattr(prepared, "packet_sha256", ""):
-            return {
-                "ok": False,
-                "failure": {
-                    "kind": "packet_integrity_mismatch",
-                    "structured": False,
-                },
-            }
-        packet = build_runtime_delivery_packet(ledger_packet)
-        if mode != "packet":
-            packet = build_runtime_packet_fallback(packet)
-        candidate_sha256 = packet["integrity"]["canonical_sha256"]
-        candidate = SimpleNamespace(
-            **{
-                key: getattr(prepared, key)
-                for key in (
-                    "handoff_id", "expected_capability_sha256",
-                    "expected_capability", "pending_effects"
-                )
-                if hasattr(prepared, key)
-            },
-            packet=packet,
-            packet_sha256=candidate_sha256,
-            project_docs=getattr(prepared, "project_docs", ()),
-        )
-        durable = bool(get_runtime_handoff(prepared.handoff_id))
-        attempt_no = 1 if mode == "packet" else 2
-        cleanup_locator = self._handoff_cleanup_locator(
-            prepared.handoff_id, attempt_no
### f5713f4df Retire legacy review gates and fix adopted Codex writer release

diff --git a/app/backend_codex.py b/app/backend_codex.py
index 411070faf..b856e3786 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -1333,15 +1333,25 @@ class CodexBackend(JsonRpcStdioTransport):
             self._active_turn_id = None
             self._teardown_error = None
             return
         proc = self._proc
         if proc is None and self._scope_unit is None:
-            if self._adopted_fds is not None or self._adopted_writer is not None:
+            if self._adopted_fds is not None or self._adopted_writer is not None or self._teardown_error:
                 # An ADOPTED backend owns no Process, but it very much owns a running CLI:
                 # returning here left it alive next to its replacement (found in impl review).
                 self._disconnecting = True
-                await self.teardown_adopted()
+                try:
+                    await self.teardown_adopted()
+                    home = self._managed_codex_home_path()
+                    if home is not None and self._thread_id:
+                        async with asyncio.timeout(CODEX_PROCESS_TIMEOUT_SECONDS):
+                            while codex_writer_conflict(home.name, self._thread_id) is not None:
+                                await asyncio.sleep(0.05)
+                    self._teardown_error = None
+                except BaseException as error:
+                    self._teardown_error = f"{type(error).__name__}: {error}"
+                    raise
             return
         self._disconnecting = True
         try:
             if self._active_turn_id and proc and proc.returncode is None:
                 await self.interrupt()
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 35e9e1238..f7c972b51 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -4010,206 +4010,14 @@ def _read_codex_uuid(sessions_path: str, slug: str) -> str:
         return (data.get("sessions", {}).get(slug, {}) or {}).get("uuid", "") or ""
     except (FileNotFoundError, json.JSONDecodeError, OSError):
         return ""
 
 
-async def _receipt_author_session(receipt_id: str) -> tuple[dict, dict]:
-    """Квитанция + сессия ВЫЗЫВАЮЩЕГО, уже сверенные между собой.
 
-    Исход ревью подписывает автор — та сессия, которая ревью и заказывала. Оркестратор видит
-    не фактуру, а отчёт воркера о ней, поэтому его подпись доказывает только то, что ему
-    рассказали (требование юзера 04.09, #493).
-    """
-    from app.db import review_receipt_get
-
-    receipt = review_receipt_get(receipt_id)
-    if not receipt:
-        raise ApiToolError(
-            code="not_found",
-            message="review receipt not found",
-            details={"receipt_id": receipt_id},
-        )
-    if int(receipt.get("schema_version") or 1) >= 3:
-        raise ApiToolError(code="review_outcome_retired", message="New tasks use advisory review. Submit your result; no author-outcome or attestation is required.")
-    info = await _api("GET", f"/api/sessions/{WORKER_NAME}", params={"scope": SCOPE})
-    caller_session_id = str(info.get("id") or "").strip() if isinstance(info, dict) else ""
-    if not caller_session_id:
-        raise ApiToolError(
-            code="caller_session_unresolved",
-            message="cannot resolve your own session; respawn the worker",
-            details={"worker": WORKER_NAME},
-        )
-    # Подписывает ЗАКАЗЧИК. Обычно это владелец предмета и он же; при `target_worker` ревью
-    # заказал оркестратор — фактуру он запинил сам и артефакт читает сам, поэтому подпись его,
-    # а не воркера, чей код проверяли. Пустое поле — квитанция до #509, там роли совпадали.
-    signer_session_id = str(
-        receipt.get("requested_by_session_id") or receipt.get("session_id") or ""
-    )
-    if caller_session_id != signer_session_id:
-        raise ApiToolError(
-            code="review_outcome_forbidden",
-            message=(
-                "only the requester of the review records its outcome: receipt "
-                f"{receipt_id} was requested by "
-                f"'{receipt.get('requested_by_worker') or receipt.get('worker_name')}'"
-            ),
-            details={
-                "receipt_id": receipt_id,
-                "receipt_worker": str(receipt.get("worker_name") or ""),
-                "caller": WORKER_NAME,
-            },
-        )
-    return receipt, info
-
-
-async def _write_delta_attestation(
-    receipt_id: str, closed_findings: list[str], statement: str,
-) -> CallToolResult:
-    from app.review_coverage import (
-        attestation_path,
-        resolve_implementation_subject,
-        verify_delta_attestation,
-    )
 
-    receipt, info = await _receipt_author_session(receipt_id)
-    # Аттестация подписывает дельту в дереве ВЛАДЕЛЬЦА предмета и коммитится вместе с его
-    # работой, а подписант с #509 может быть другой сессией. Писать в чужой worktree мы
-    # решили не давать, поэтому такой случай отказывает ИМЕНЕМ, а не общим «нет задачи»:
-    # у оркестратора `task_id` пуст, и прежний отказ назвал бы неверную причину.
-    if str(receipt.get("requested_by_session_id") or "") not in {
-        "", str(receipt.get("session_id") or ""),
-    }:
-        raise ApiToolError(
-            code="attestation_cross_worker_unsupported",
-            message=(
-                "this review was requested for another worker's code: the delta must be "
-                f"attested in the worktree of '{receipt.get('worker_name')}', or reviewed "
-                "again"
-            ),
-            details={
-                "receipt_id": receipt_id,
-                "subject_worker": str(receipt.get("worker_name") or ""),
-                "requested_by": str(receipt.get("requested_by_worker") or ""),
-            },
-        )
-    cwd = str(info.get("worktree_path") or info.get("cwd") or SCOPE)
-    task_id = str(info.get("task_id") or "")
-    if not task_id:
-        raise ApiToolError(
-            code="invalid_argument",
-            message="attestation needs a bound task; the session has none",
-            details={"field": "task_id"},
-        )
-    try:
-        subject = resolve_implementation_subject(
-            cwd, str(info.get("base_branch") or "main"),
-        )
-    except ValueError as error:
-        raise ApiToolError(
-            code="invalid_argument", message=str(error), details={"field": "worktree"},
-        ) from error
-    path = attestation_path(cwd, task_id)
-    path.parent.mkdir(parents=True, exist_ok=True)
-    attestation = {
-        "receipt_id": receipt_id,
-        "reviewed_worker_head": str(receipt.get("worker_head") or ""),
-        "artifact_sha256": str(receipt.get("artifact_sha256") or ""),
-        "production_diff_sha256": str(subject["production_diff_sha256"]),
-        "closed_findings": list(closed_findings),
-        "statement": statement,
-        "recorded_at": datetime.now(timezone.utc).isoformat(),
-    }
### 98574f427 Replace duplicate task stores with private Git and one versioned SQLite projection

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 20b73a18e..8d4913794 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -3519,36 +3519,13 @@ async def bg_cancel(job_id: str) -> str:
     if isinstance(result, dict) and result.get("error"):
         return f"Cancel failed: {result['error']}"
     return f"Job {job_id} cancelled."
 
 
-async def knowledge(
-    operation: str,
-    detail: str = "summary",
-    payload: dict[str, Any] | None = None,
-) -> str:
-    """Promote, query, or import canonical structured knowledge.
-
-    ``detail`` progressively expands ``summary`` → ``record`` → ``evidence``.
-    Direct file, SQLite, and vector operations are intentionally unsupported.
-    """
-
-    body = {
-        "operation": operation,
-        "detail": detail,
-        "payload": payload or {},
-    }
-    try:
-        result = await _api("POST", "/api/knowledge", json=body)
-    except ApiToolError as exc:
-        result = {"error": _canonical_error(exc)}
-    return json.dumps(result, ensure_ascii=False, sort_keys=True)
-
-
 @mcp.tool()
 async def search_memory(query: str, limit: int = 5, cross_project: bool = False) -> str:
-    """Compatibility callable for old in-process consumers; not an agent MCP tool."""
+    """Search project Markdown and original session logs."""
     # scope НЕ параметр: берём ORCHESTRA_SCOPE из env воркера → нельзя запросить чужой проект.
     if not SCOPE:
         return "search_memory: no project scope (orchestrator context) — nothing to search."
     body = {"scope": SCOPE, "query": query, "limit": limit, "cross_project": cross_project}
     # Подсказка одна на все отказы: агент обязан уйти в grep, а не ждать и не повторять вызов.
@@ -3562,26 +3539,14 @@ async def search_memory(query: str, limit: int = 5, cross_project: bool = False)
         if e.code in ("transport_timeout", "search_busy", "search_stale"):
             reason = {"transport_timeout": f"поиск не уложился в {SEARCH_DEADLINE_S:.0f} с",
                       "search_busy": "очередь поиска переполнена",
                       "search_stale": "запрос протух в очереди"}[e.code]
             return f"search_memory: {reason}. Не жди и не повторяй — {grep}"
-        if "RAG disabled" in e.message:
-            return f"search_memory: семантический поиск выключен (RAG_ENABLED=false) — {grep}"
         return f"search_memory: {e.code} — {e.message}. {grep}"
     hits = result.get("results", []) if isinstance(result, dict) else []
-    # `index` появился позже самого эндпоинта: старый роут его не отдаёт → .get, а не [].
-    index = (result.get("index") or {}) if isinstance(result, dict) else {}
-    pending = index.get("pending_files") or 0
-    debt = (f"\n\n[индекс не догнан: {pending} файлов ещё не проиндексированы — "
-            f"пустой ответ не доказывает отсутствие факта]") if pending else ""
     if not hits:
-        # «долг 0» и «долга не знаем» — РАЗНОЕ: index_status отдаёт пустой словарь, пока в
-        # процессе не было ни одного прохода, и молчание честнее нуля
-        if "pending_files" not in index:
-            debt = ("\n\n[состояние индекса неизвестно: в этом процессе ещё не было прохода — "
-                    "пустой ответ ничего не доказывает]")
-        return f"No memory matches for: {query!r}. Проверь — {grep}{debt}"
+        return f"No memory matches for: {query!r}. Проверь — {grep}"
     lines = []
     for h in hits:
         if h.get("source") == "file":
             head = f"[file: {h.get('path')}]"
         else:
@@ -3589,11 +3554,11 @@ async def search_memory(query: str, limit: int = 5, cross_project: bool = False)
             tag = f"{h.get('kind')}" + (f" from {author}" if author else "")
             head = f"[log: {tag}]"
         if cross_project:
             head = f"({h.get('project')}) {head}"
         lines.append(f"{head}\n{h.get('content', '').strip()}")
-    return "\n\n---\n\n".join(lines) + debt
+    return "\n\n---\n\n".join(lines)
 
 
 # Wrapper reloads Orchestra .env on every invocation, so Codex review follows the same
 # currently selected proxy as workers, Cursor, and the dashboard service.
 def _codex_bin() -> str:
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 3a36f64af..c3a5c6632 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -1866,11 +1866,10 @@ async def _finalize_committed_merge(
     merged_commits: dict,
 ) -> dict:
     """Run the durable checkpoint and the DB stage of a merge that already committed."""
     from app import merge_operations as _ops
     from app.ia import merge_receipts
-    from app import rag_service
 
     finalization["commits"] = merged_commits
     finalization["target_after"] = result.get("target_after") or ""
     finalization["stage"] = "PENDING"
     if operation_id:
@@ -1934,11 +1933,10 @@ async def _finalize_committed_merge(
         await asyncio.to_thread(
             _ops.mark_finalization_applied, operation_id, finalization,
         )
     result.update(applied)
     result["finalization"] = finalization
-    result["rag_backfill_status"] = rag_service.schedule_backfill(row_scope)
     return result
 
 
 async def execute_merge_session(
     *,
@@ -2375,12 +2373,10 @@ async def execute_merge_session(
                         "ok": False,
                         "error": "task not updated because switch was skipped",
                     }
                 return result
 
-            from app import rag_service
-            result["rag_backfill_status"] = rag_service.schedule_backfill(row_scope)
 
             if task_identity:
                 par = public_task_ref(task_identity)
                 new_branch = f"task-{par}/{expected_name}"
                 try:
@@ -2625,25 +2621,15 @@ async def _promote_current_work_for_task(
             require_unreserved=True,
         )
     except Exception as error:
         task_error = error
 
-    debt = (task_status or {}).get("projection_debt") or {}
-    partial = bool(
-        task_error is not None
-        or debt
-        or (task_status or {}).get("shadow_match") is False
-    )
-    complete = bool(
-        task_error is None
-        and task_status
-        and task_status.get("ok")
-        and not partial
-    )
+    partial = task_error is not None
+    complete = bool(task_error is None and task_status and task_status.get('ok'))
     if not complete and partial:
         message = err_text(task_error) if task_error is not None else str(
-            (task_status or {}).get("error") or debt.get("message") or "task binding is partial"
+            (task_status or {}).get("error") or "task binding is partial"
### 59fe32bc4 Merge remote-tracking branch 'origin/main' into codex/retire-legacy-review

diff --cc app/session.py
index 3a0a23808,c95b872d3..14fa7a888
--- a/app/session.py
+++ b/app/session.py
@@@ -1088,16 -1116,18 +1112,20 @@@ class AgentSession
          The prompt is deliberately NOT rebuilt here: the re-inject path in `send()` already
          owns that (#220, `assemble_prompt`), and a second rebuild would be a second owner.
          """
          if not self.tools_are_stale:
              return
+         if getattr(self._backend, "can_replace_adopted_process", True) is False:
+             self._log("warning", "Keeping adopted CLI: process identity is unavailable; "
+                       "tool/config refresh is deferred until the writer exits")
+             return
          logger.info(f"[{self.name}] releasing adopted CLI at the turn boundary "
                      f"so new tools and prompt take effect")
          old = self._backend
          if old is not None:
 +            from app.manager import retire_backend_fds
 +            retire_backend_fds(self)
              try:
                  await old.disconnect()
              except Exception as error:
                  logger.warning(f"[{self.name}] releasing the stale CLI failed: "
                                 f"{err_text(error)}")
@@@ -4140,15 -5088,15 +4174,17 @@@
          if self._hibernate_task and not self._hibernate_task.done() and self._hibernate_task is not asyncio.current_task():
              self._hibernate_task.cancel()
              self._hibernate_task = None
          backend = self._backend
          if backend:
 +            from app.manager import retire_backend_fds
 +            retire_backend_fds(self)
              await backend.disconnect()
              if self._backend is backend:
                  self._backend = None
+         if self._backend is None:
+             self._adopted_recovery_pending = False
          if (self._heartbeat_task and not self._heartbeat_task.done()
                  and self._heartbeat_task is not asyncio.current_task()):
              self._heartbeat_task.cancel()
              try:
                  await self._heartbeat_task
### fc0d5143d Merge current main into storage simplification

### 5f7e72c50 Add reusable idle watches and label dashboard message channel

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index f7c972b51..0e7286c39 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -3400,10 +3400,13 @@ async def bg_create(type: str, message: str = "", target: str = "",
                     command: str = "", host: str = "", cron_expr: str = "",
                     interval_seconds: int = 60,
                     timeout_seconds: int = 3600) -> str:
     """Create a background job that wakes an agent when triggered. Survives hibernate.
     Types:
+    - idle: recurring watch of your own worker tree. Wakes you when idle with no running descendants
+            or other active background jobs. Fires once per new activity, not on every check.
+            Recreating it replaces your previous idle watch. timeout_seconds=0 keeps it until cancelled.
     - timer: fires after delay_seconds
     - file: watches file at path for pattern (regex)
     - command: runs command every interval_seconds, matches pattern in output
     - ssh: streams ssh command output, matches pattern
     - run: executes command, wakes agent when done with exit code + output
@@ -3411,11 +3414,13 @@ async def bg_create(type: str, message: str = "", target: str = "",
             Recurring — stays active across firings. timeout_seconds=0 = no expiry (forever
             until cancelled). Missed fires during downtime are skipped (no backfill).
     - cron_command: runs command on cron_expr and wakes only when completed stdout/stderr
             matches pattern. Recurring, UTC, no backfill.
     target: agent name (default: you). timeout_seconds: max lifetime (default 1h,
-            max 24h); 0 = no expiry for file/command/ssh/cron/cron_command."""
+            max 24h); 0 = no expiry for file/command/ssh/cron/cron_command/idle."""
+    if type == "idle" and (ROLE not in _ORCH_ROLES or (target and target != WORKER_NAME)):
+        raise ApiToolError(code="idle_watch_self_only", message="An orchestrator sets an idle watch on itself")
     config = {}
     if type == "timer":
         config = {"delay_seconds": delay_seconds}
     elif type == "file":
         config = {"path": path, "pattern": pattern}
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index a1fc9ee00..4cae7dceb 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -9,11 +9,11 @@ import re
 import sqlite3
 from app.task_refs import task_ref as public_task_ref
 
 from contextlib import AsyncExitStack
 from pathlib import Path
-from typing import Optional
+from typing import Optional, Literal
 
 from fastapi import APIRouter, Request
 from fastapi.responses import JSONResponse, Response
 from starlette.responses import StreamingResponse
 from pydantic import BaseModel, field_validator, model_validator
@@ -182,10 +182,11 @@ class CreateSessionRequest(BaseModel):
             raise ValueError("repo_path required when use_worktree=True")
         return self
 
 
 class SendRequest(BaseModel):
+    channel: Literal["", "dashboard"] = ""
     message: str
     scope: str
     sender: str | None = None
     wake: bool = True
     delivery_id: str = ""
@@ -947,12 +948,12 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
                 request is not None
                 and validate_session(request.cookies.get("session", ""))
             )
             provenance = MessageProvenance(
                 origin="user" if operator else "unknown",
-                senders=("user",) if operator else ("unknown",),
-                subtype="http_send",
+                senders=("user",) if operator else (("dashboard",) if req.channel == "dashboard" else ("unknown",)),
+                subtype="dashboard" if req.channel == "dashboard" else "http_send",
             )
         # A non-waking delivery must not load or activate the recipient.  The
         # requested scope is the mailbox address supplied by the sender.
         if not req.wake:
             # #231, находка ревью реализации (F3, раунд 2): ящик разгружается в КОНЦЕ
### d9ce293fa Integrate current main before storage cutover

### 9a1735f16 Simplify agent knowledge and retire mandatory memory paperwork

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index ffbdf6a00..d847ca01c 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -3529,11 +3529,13 @@ async def bg_cancel(job_id: str) -> str:
     return f"Job {job_id} cancelled."
 
 
 @mcp.tool()
 async def search_memory(query: str, limit: int = 5, cross_project: bool = False) -> str:
-    """Search project Markdown and original session logs."""
+    """Optional literal search: current KB, personal notes, task evidence, then source logs.
+    File hits identify their area and matching line. Archives require targeted file search.
+    """
     # scope НЕ параметр: берём ORCHESTRA_SCOPE из env воркера → нельзя запросить чужой проект.
     if not SCOPE:
         return "search_memory: no project scope (orchestrator context) — nothing to search."
     body = {"scope": SCOPE, "query": query, "limit": limit, "cross_project": cross_project}
     # Подсказка одна на все отказы: агент обязан уйти в grep, а не ждать и не повторять вызов.
@@ -3554,11 +3556,16 @@ async def search_memory(query: str, limit: int = 5, cross_project: bool = False)
     if not hits:
         return f"No memory matches for: {query!r}. Проверь — {grep}"
     lines = []
     for h in hits:
         if h.get("source") == "file":
-            head = f"[file: {h.get('path')}]"
+            location = str(h.get("path"))
+            if h.get("line"):
+                location += f":{h['line']}"
+            head = f"[file: {location}]"
+            if h.get("area"):
+                head += f" ({h['area']})"
         else:
             author = h.get("author")
             tag = f"{h.get('kind')}" + (f" from {author}" if author else "")
             head = f"[log: {tag}]"
         if cross_project: