# Frozen blind review corpus

The four cases below are independent compact historical patch excerpts. Treat
each case as a separate review. The excerpts contain every call-site fact needed
for the intended blocker classification; do not infer unseen code.

## Case K2

```diff
 async def create_worker(request):
+    try:
+        policy = await worker_model_policy(request.model)
+    except (TimeoutError, RuntimeError) as error:
+        logger.error("worker model policy unavailable; fail-open: %s", error)
+        policy = PolicyDecision(state="unknown")
+    if policy.state == "blocked":
+        raise ModelPolicyError(policy.reason)

     session = await manager.create_session(
         name=request.name,
         model=request.model,
         worktree=request.worktree,
     )

     # Existing delivery admission remains unchanged.
     admission = await get_worker_admission(request.model)
     require_worker_admission(admission)  # rejects blocked and unknown
     await session.send(request.initial_task)
     return session
```

Contract: model-policy telemetry failure is intentionally loud fail-open. A
successful return means the worker exists and received its initial task.

## Case M7

```diff
 register_runtime(RuntimeDefinition(
     id="codex",
     capabilities=RuntimeCapabilities(
         event_stream="per_turn",
         mid_turn_inject=True,
         reconnect=False,
         hibernate=True,
         process_liveness=True,
-        resume_across_models=False,
+        resume_across_models=True,
     ),
     factory=_codex_factory,
 ))

-async def test_codex_model_switch_starts_fresh_native_thread(session):
+async def test_codex_model_switch_preserves_native_thread(session):
     session.model = "model-old"
     session.backend_type = "codex"
     session.session_id = "native-thread"
     result = await session.change_model("model-new")

     assert result["runtime_changed"] is False
-    assert result["native_session_reset"] is True
-    assert session.session_id is None
+    assert result["native_session_reset"] is False
+    assert session.session_id == "native-thread"
+    with patch("app.session.build_backend") as build:
+        session._make_backend()
+    _, context = build.call_args.args
+    assert context.model == "model-new"
+    assert context.resume_session_id == "native-thread"
```

Contract: this runtime's native API supports resuming the same thread after a
model change; cross-runtime changes still reset the native thread elsewhere.

## Case Q4

```diff
+_chat_locks: dict[int, asyncio.Lock] = {}
+_flood_until: dict[int, float] = {}
+_last_send: dict[int, float] = {}
+
+async def call_safe(chat_id: int, call, *, important: bool = False):
+    loop = asyncio.get_running_loop()
+    lock = _chat_locks.setdefault(chat_id, asyncio.Lock())
+    attempts = 3 if important else 1
+
+    async with lock:
+        for attempt in range(1, attempts + 1):
+            wait = max(
+                0,
+                _flood_until.get(chat_id, 0) - loop.time(),
+                3.05 - (loop.time() - _last_send.get(chat_id, 0)),
+            )
+            if wait:
+                await asyncio.sleep(wait)
+            _last_send[chat_id] = loop.time()
+            try:
+                return await call()
+            except RetryAfter as error:
+                _flood_until[chat_id] = loop.time() + error.retry_after + 0.25
+                if not important or attempt == attempts:
+                    break
+            except (NetworkError, ServerError):
+                if important and attempt < attempts:
+                    await asyncio.sleep(attempt)
+                    continue
+                return None
+        return None
```

Contract: all outbound operations for one group chat share this helper and
lock. `RetryAfter.retry_after` observed in production is 3–40 seconds. Important
messages must not be lost; low-value messages may be shed.

## Case T9

```diff
-def is_safe_path(base: Path, candidate: Path) -> bool:
-    return str(candidate.resolve()).startswith(str(base.resolve()))
+def is_safe_path(base: Path, candidate: Path) -> bool:
+    base_resolved = base.resolve()
+    candidate_resolved = candidate.resolve()
+    try:
+        candidate_resolved.relative_to(base_resolved)
+    except ValueError:
+        return False
+    return True

 def test_sibling_prefix_is_not_inside(tmp_path):
     base = tmp_path / "scope"
     sibling = tmp_path / "scope-escape" / "payload"
     assert is_safe_path(base, sibling) is False

+def test_traversal_is_not_inside(tmp_path):
+    base = tmp_path / "scope"
+    assert is_safe_path(base, base / ".." / "outside") is False
```

Contract: this predicate validates local filesystem paths before a read. The
consumer opens the same resolved path immediately after the check; creation or
mutation by an untrusted concurrent local process is outside the threat model.

