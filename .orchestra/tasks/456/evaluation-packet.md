# Blinded design-stop evaluation packet

Judge only the supplied excerpts. Case letters are in a fixed pre-registered order.

## Case A

### Changed excerpt

```diff
diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 90d1276c..36f29a70 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -154,31 +154,39 @@ function _quotaMapLaneStatusText(windowData, bucketId = null) {
 }
 
 function _quotaMapLaneHeadroomText(windowData, bucketId = null) {
     if (!_quotaMapData || !Array.isArray(_quotaMapData.buckets) || !windowData) return '';
     const bucket = _quotaMapData.buckets.find(item =>
         (!bucketId || item.bucket === bucketId)
         && item.data_available
         && item.fresh !== false
         && item.window
         && _quotaWindowMatch(item.window, windowData)
     );
     const lane = bucket?.lanes?.find(item => item?.gated);
-    const headroom = Number(lane?.headroom_pp);
-    if (!lane || !Number.isFinite(headroom)) return '';
-    const value = headroom.toFixed(1);
-    const laneName = lane.lane === 'claude' ? 'Claude' : String(lane.label || lane.lane);
-    return headroom < 0
-        ? `воркеры ${laneName}: порог пройден, запас ${value} п.п.`
-        : `воркеры ${laneName}: запас ${value} п.п. до порога`;
+    if (!lane || lane.headroom_pp == null) return '';
+    const headroom = Number(lane.headroom_pp);
+    if (!Number.isFinite(headroom)) return '';
+    const value = Math.abs(headroom).toFixed(1);
+    const signed = headroom < 0 ? `−${value}` : `+${value}`;
+    let text = `🎯 ${signed}`;
+    if (headroom < 0) {
+        const release = _quotaMapLaneRelease(windowData, bucketId);
+        const seconds = Number(release.release_in_seconds);
+        if ((release.status === 'opens_in' || release.status === 'at_reset')
+            && Number.isFinite(seconds)) {
+            text += ` · 🕐 ${_releaseDurationFromSeconds(seconds)}`;
+        }
+    }
+    return text;
 }
 
 function _etaToLimit(currentPct, isoStr, windowMs) {
     if (!isoStr || currentPct <= 0) return '';
     const remainMs = Math.max(0, new Date(isoStr) - Date.now());
     const elapsedMs = windowMs - remainMs;
     if (elapsedMs <= 0) return '';
... later lines omitted ...
```

## Case B

### Changed excerpt

```diff
... earlier lines omitted ...
+        raise ValueError(f"{path}: expected a JSON object")
+    return value
+
+
+def load_facts(directory: Path) -> list[SourceFact]:
+    result: list[SourceFact] = []
+    paths = sorted(directory.glob("part-*.json"))
+    if not paths:
+        raise ValueError(f"no part-*.json files in {directory}")
+    for path in paths:
+        match = re.fullmatch(r"part-(\d+)\.json", path.name)
+        if match is None:
+            continue
+        part = int(match.group(1))
+        values = json.loads(path.read_text(encoding="utf-8"))
+        if not isinstance(values, list):
+            raise ValueError(f"{path}: expected a JSON array")
+        for position, value in enumerate(values, start=1):
+            if not isinstance(value, dict):
+                raise ValueError(f"{path}:{position}: expected a JSON object")
+            result.append(SourceFact(part=part, position=position, value=value))
+    return result
+
+
+def stable_fact_id(value: dict[str, Any]) -> str:
+    identity = "\n".join((
+        str(value.get("source_file") or ""),
+        str(value.get("source_lines") or ""),
+        str(value.get("statement") or ""),
+    ))
+    return str(uuid.uuid5(FACT_NAMESPACE, identity))
+
+
+def stable_evidence_id(fact_id: str) -> str:
+    return str(uuid.uuid5(EVIDENCE_NAMESPACE, fact_id))
+
+
+def _topic_base(value: str) -> str:
+    transliterated = value.casefold().translate(CYRILLIC)
+    cleaned = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
+    if not cleaned:
+        cleaned = hashlib.sha256(value.encode()).hexdigest()[:12]
+    return f"kb-{cleaned[:52].rstrip('-')}"
+
+
+def topic_slugs(labels: set[str]) -> dict[str, str]:
+    groups: dict[str, list[str]] = collections.defaultdict(list)
+    for label in labels:
+        groups[_topic_base(label)].append(label)
... later lines omitted ...
```

## Case C

### Changed excerpt

```diff
diff --git a/app/tm.py b/app/tm.py
index 88577b64..3406bd2b 100644
--- a/app/tm.py
+++ b/app/tm.py
@@ -299,25 +299,38 @@ def create_task(conn: sqlite3.Connection, project_id: str, title: str,
                 status: str = "new",
                 par_number: int | None = None, priority: int = 2,
                 acceptance_command: str = "",
                 acceptance_manifest: list[str] | None = None,
                 acceptance_required: bool = False,
                 acceptance_actor: dict | None = None) -> dict:
     if status not in VALID_STATUSES:
         raise ValueError(f"Invalid status: {status}")
     if price_rub < 0:
         raise ValueError("price_rub must be >= 0")
 
     now = _now()
-    par = par_number if par_number is not None else _next_par(conn, project_id)
+    # Номер выдаёт ОДИН владелец — `api_create_task`, который согласует его с canonical и
+    # передаёт сюда явно. Собственная выдача номера здесь и есть механизм, которым
+    # открывается новая дверь мимо canonical: legacy-счётчик уезжает вперёд, гейт
+    # `task display counter mismatch` заклинивает проект насмерть (28.08, comfy: разрыв 3 → 8
+    # за три часа, ни одной новой задачи). Fail loud вместо тихого расхождения.
+    if par_number is None:
+        if _ia_context() is not None:
+            raise RuntimeError(
+                "create_task cannot allocate a task number: call api_create_task, "
+                "which agrees the number with the canonical store first"
+            )
+        par = _next_par(conn, project_id)
+    else:
+        par = par_number
 
     command = (acceptance_command or "").strip()
     from app.acceptance import parse_acceptance_command
 
     parse_acceptance_command(command)
     manifest = _normalize_acceptance_manifest(acceptance_manifest)
     oracle_json = "{}"
     if acceptance_required or manifest:
         if not command:
             raise ValueError("required acceptance oracle has no command")
         actor = _normalize_acceptance_actor(acceptance_actor)
         oracle_json = _acceptance_oracle_json(
diff --git a/tests/test_task_par_collision_406.py b/tests/test_task_par_collision_406.py
index 0749fe56..36e9cd78 100644
--- a/tests/test_task_par_collision_406.py
+++ b/tests/test_task_par_collision_406.py
@@ -72,12 +72,35 @@ def test_spawn_task_allocation_keeps_both_stores_in_step(canonical_tasks):
         "SELECT scope FROM tm_projects WHERE id='orchestra'"
     ).fetchone()[0])
 
     created = tm.create_task_for_scope(scope, "spawned by fan-out")
 
     # Потребитель строит имя ветки из par_number — форма ответа обязана сохраниться.
     assert created["par_number"] == 1
 
     # И, главное, обе стороны согласны: следующий task_create проходит, а не упирается в гейт.
... later lines omitted ...
```

## Case D

### Changed excerpt

```diff
... earlier lines omitted ...
+from fastapi import APIRouter
+from fastapi.responses import JSONResponse
+
+from app.db import get_subagents, get_session
+
+logger = logging.getLogger("orchestra.subagent")
+
+router = APIRouter(tags=["subagent"])
+
+_SAFE_ID = re.compile(r"^[\w-]+$")  # agent_id goes into a filename — no path traversal
+
+
+@router.get("/api/subagents/{session_id}")
+async def subagents_list(session_id: str):
+    """Telemetry rows for a session's sub-agents (from Task* messages)."""
+    return {"subagents": get_subagents(session_id)}
+
+
+@router.get("/api/subagent-transcripts/{session_id}")
+async def subagent_transcript_ids(session_id: str):
+    """SDK agent_ids of sub-agents whose transcripts exist for this session."""
+    sess = get_session(session_id)
+    if not sess:
+        return JSONResponse({"error": "session not found"}, status_code=404)
+    sdk_id = sess.get("session_id") or ""
+    if not sdk_id:
+        return {"agent_ids": [], "note": "no sdk_session_id yet"}
+    from claude_agent_sdk import list_subagents
+    try:
+        agent_ids = list_subagents(sdk_id, sess.get("cwd") or None)
+    except Exception as e:
+        logger.warning(f"list_subagents failed: {e}")
+        return {"agent_ids": [], "error": str(e)}
+    return {"agent_ids": agent_ids, "sdk_session_id": sdk_id}
+
+
+@router.get("/api/subagent-transcript/{session_id}/{agent_id}")
+async def subagent_transcript(session_id: str, agent_id: str, limit: int = 200, offset: int = 0):
+    """Full conversation of one sub-agent (lazy read from SDK JSONL store)."""
+    if not _SAFE_ID.match(agent_id):
+        return JSONResponse({"error": "invalid agent_id"}, status_code=400)
+    sess = get_session(session_id)
+    if not sess:
+        return JSONResponse({"error": "session not found"}, status_code=404)
+    sdk_id = sess.get("session_id") or ""
+    if not sdk_id:
+        return {"messages": [], "note": "no sdk_session_id yet"}
+    from claude_agent_sdk import get_subagent_messages
+    try:
... later lines omitted ...
```

### Pre-existing consumer context

```python
... earlier lines omitted ...
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "current_session_id": session.session_id,
        "history": session.session_id_history,
    }


@router.post("/api/sessions/{name}/rollback-session")
async def rollback_session(name: str, req: ScopeRequest, index: int = -1):
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    if session.status.value == "running":
        return JSONResponse({"error": "agent is running"}, status_code=400)
    if not session.session_id_history:
        return JSONResponse({"error": "no session history"}, status_code=400)
    try:
        entry = session.session_id_history[index]
    except IndexError:
        return JSONResponse({"error": f"invalid index {index}"}, status_code=400)
    old_sid = session.session_id
    session.session_id = entry["session_id"]
    await session._disconnect_backend()
    session._persist()
    return {
        "ok": True,
        "rolled_back_to": entry["session_id"],
        "previous": old_sid,
        "compacted_at": entry.get("compacted_at"),
    }


@router.post("/api/sessions/{name}/restart-cli")
async def restart_cli(name: str, req: ScopeRequest):
    session = await manager.ensure_loaded(name, req.scope)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    await session._disconnect_backend()
    session.status = AgentStatus.IDLE
    session._persist()
    return {"ok": True}


@router.post("/api/sessions/{name}/interrupt")
... later lines omitted ...
```

## Case E

### Changed excerpt

```diff
diff --git a/scripts/secret_scan.py b/scripts/secret_scan.py
new file mode 100644
index 00000000..436cf8ce
--- /dev/null
+++ b/scripts/secret_scan.py
@@ -0,0 +1,201 @@
+#!/usr/bin/env python3
+"""Гейт на попадание секрета в git — единственный владелец списка ФОРМ (#453).
+
+Список форм в проекте до этого жил только прозой (`CLAUDE.md`, `.orchestra/kb/repo-ops.md`)
+и в замороженных однократных скриптах задач (`.orchestra/tasks/*/verify.py`). Прозу
+исполнить нельзя, замороженные артефакты никто не зовёт — поэтому владелец заводится здесь,
+а хуки остаются тонкими шимами без собственных шаблонов.
+
+Правило отделения ЗНАЧЕНИЯ от УПОМИНАНИЯ — по НАГРУЗКЕ, а не по префиксу: совпадением
+считается точная длина и алфавит формата провайдера. `CLAUDE.md` пишет `y0_`, `AIza`,
+`gh[pousr]_` без нагрузки; регулярка в чужом скрипте пишет `y0_[A-Za-z0-9_-]+` — после
+префикса стоит `[`, которого в алфавите нагрузки нет. Слой заглушек (`example`, `test`, …)
+применяется ТОЛЬКО к двум правилам без собственного формата — `bearer` и телу PEM. К форматам
+с провайдерским префиксом он не применяется намеренно: `ghp_<36 base62, содержащих "test">` —
+валидный токен, и глушить его словом внутри нагрузки нельзя (найдено ревью Luna, #453).
+
+Отбор по ПУТИ (пропускать `tests/`, `.orchestra/tasks/`) сознательно НЕ применяется:
+единственная реальная утечка проекта, `docs/tasks/sol-efficiency/calls_strict.tsv`
+(12.08.2026, два боевых OAuth-токена в публичном origin), лежала ровно в каталоге задач —
+путевой аллоулист пропустил бы её.
+"""
+
+import argparse
+import re
+import subprocess
+import sys
+
+_ZERO = "0" * 40
+_GITLINK = "160000"
+
+# Разделители внутри нагрузки: настоящий пробельный символ ИЛИ его JSON-экранирование.
+# Ключ Google service-account живёт в JSON именно так: `-----BEGIN PRIVATE KEY-----\nMIIE…`,
+# где `\n` — два символа, и правило на настоящий перевод строки его не видит (ревью Luna).
+_SEP = re.compile(r"\s|\\[nrt]")
+
+# Одно правило = формат одного провайдера ЦЕЛИКОМ; `mentions` = применять ли слой заглушек.
+# Границы (?<!…)/(?!…) делают длину точной: значение на символ длиннее — уже не ключ.
+RULES: tuple[tuple[str, re.Pattern[str], int, bool], ...] = tuple(
+    (name, re.compile(pattern), group, mentions)
+    for name, pattern, group, mentions in (
+        ("yandex-oauth", r"(?<![A-Za-z0-9_-])y0_[A-Za-z0-9_-]{40,}", 0, False),
+        ("openrouter", r"(?<![A-Za-z0-9-])sk-or-v1-([0-9a-f]{64})(?![0-9a-f])", 1, False),
+        ("anthropic", r"(?<![A-Za-z0-9-])sk-ant-(?:api|oat)[0-9]{2}-([A-Za-z0-9_-]{80,})", 1, False),
+        ("google-oauth", r"(?<![A-Za-z0-9_-])ya29\.([A-Za-z0-9_-]{50,})", 1, False),
+        ("github", r"(?<![A-Za-z0-9_])gh[pousr]_([A-Za-z0-9]{36})(?![A-Za-z0-9])", 1, False),
+        ("github-pat", r"(?<![A-Za-z0-9_])github_pat_([A-Za-z0-9_]{70,})", 1, False),
+        ("google-api-key", r"(?<![A-Za-z0-9_-])AIza([0-9A-Za-z_-]{35})(?![0-9A-Za-z_-])", 1, False),
+        ("bearer", r"(?i:bearer)\s+([A-Za-z0-9._~+/=-]{25,})", 1, True),
+        # Заголовок PEM без тела — упоминание: так он и написан в `tests/test_secret_mask.py`
+        # и в `app/runtime_history.py`. Значение обязано нести тело base64.
+        (
+            "pem-private-key",
+            r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----((?:[A-Za-z0-9+/=]|\\[nrt]|\s){40,})",
+            1,
+            True,
+        ),
+    )
+)
+
+# Слово-заглушка внутри нагрузки означает, что значение написано рукой как пример.
+_PLACEHOLDERS = (
+    "example", "placeholder", "your", "fake", "dummy", "redacted",
+    "secret", "sample", "changeme", "notreal", "test", "xxxx",
+)
+
+
+def _is_mention(core: str) -> bool:
+    """Нагрузка написана как пример, а не выдана провайдером."""
+    low = core.lower()
+    if any(word in low for word in _PLACEHOLDERS):
+        return True
+    # `AAAA…`, `xxxx…`, `0000…`: у выданного ключа алфавит богаче.
+    return len(set(core)) < 8
+
+
+def scan_text(text: str, origin: str) -> list[str]:
+    """Список находок вида `<файл>:<строка>: <правило> (N символов)`. Значение НЕ печатаем."""
+    findings = []
+    for name, pattern, group, mentions in RULES:
+        for m in pattern.finditer(text):
+            core = _SEP.sub("", m.group(group))
+            if len(core) < 20:
... later lines omitted ...
```

## Case F

### Changed excerpt

```diff
diff --git a/app/status_policy.py b/app/status_policy.py
new file mode 100644
index 00000000..8baaf804
--- /dev/null
+++ b/app/status_policy.py
@@ -0,0 +1,11 @@
+"""Audience classification for persisted status events."""
+
+import re
+
+
+_RAW_TELEMETRY_STATUS = re.compile(r"^[A-Z][A-Z0-9_]*_RAW\s+\{")
+
+
+def is_internal_telemetry_status(content: str) -> bool:
+    """Return whether a structured provider telemetry status is not user-facing."""
+    return bool(_RAW_TELEMETRY_STATUS.match(str(content)))
```

## Case G

### Changed excerpt

```diff
... earlier lines omitted ...
+
+def resolve_scoped_task_identity(scope: str, ref: str) -> TaskIdentity:
+    legacy = _legacy_resolve_scoped_task_identity(scope, ref)
+    context = _ia_context()
+    if context is None:
+        return legacy
+    store = context.store
+    assert store is not None
+    candidate = store.task_get(str(legacy["par_number"]), project=legacy["project_id"])
+    return {
+        **legacy,
+        "stable_id": candidate["stable_id"],
+        "canonical_head": candidate["canonical_head"],
+    }
+
+
+def api_create_task(project_id: str, title: str, price: int = 0,
+                    description: str = "", assignee: str = "",
+                    status: str = "new", scope: str = "",
+                    priority: int = 2, acceptance_command: str = "",
+                    acceptance_manifest: list[str] | None = None,
+                    acceptance_required: bool = False,
+                    acceptance_actor: dict | None = None) -> dict:
+    context = _ia_context()
+    if context is None:
+        return _legacy_api_create_task(
+            project_id, title, price, description, assignee, status,
+            scope=scope, priority=priority,
+            acceptance_command=acceptance_command,
+            acceptance_manifest=acceptance_manifest,
+            acceptance_required=acceptance_required,
+            acceptance_actor=acceptance_actor,
+        )
+    store = context.store
+    assert store is not None
+
+    if context.mode == "shadow":
+        legacy = _legacy_api_create_task(
+            project_id, title, price, description, assignee, status,
+            scope=scope, priority=priority,
+            acceptance_command=acceptance_command,
+            acceptance_manifest=acceptance_manifest,
+            acceptance_required=acceptance_required,
+            acceptance_actor=acceptance_actor,
+        )
+        candidate = store.task_create(
+            project_id=legacy["project"],
+            title=title,
+            price=price,
+            description=description,
+            assignee=assignee,
+            status=status,
+            priority=priority,
+            acceptance_command=acceptance_command,
+            acceptance_manifest=acceptance_manifest,
+            acceptance_required=acceptance_required,
+            expected_head=store.canonical_head,
+        )
+        return _shadow_result(legacy, candidate, context, _CREATE_COMPARE_FIELDS)
+
+    with _conn() as conn:
+        project = resolve_project_selector(conn, project_id) if project_id else None
+        if project is None and scope:
+            project = _project_for_session_scope(conn, scope)
+        if not project or not str(project.get("scope") or "").strip():
+            raise ValueError(f"project '{project_id or scope}' is not registered")
+        resolved_project_id = project["id"]
+    candidate = store.task_create(
+        project_id=resolved_project_id,
+        title=title,
+        price=price,
+        description=description,
+        assignee=assignee,
+        status=status,
+        priority=priority,
+        acceptance_command=acceptance_command,
+        acceptance_manifest=acceptance_manifest,
+        acceptance_required=acceptance_required,
+        expected_head=store.canonical_head,
+    )
+    legacy = _legacy_api_create_task(
+        resolved_project_id, title, price, description, assignee, status,
+        priority=priority,
+        acceptance_command=acceptance_command,
+        acceptance_manifest=acceptance_manifest,
+        acceptance_required=acceptance_required,
+        acceptance_actor=acceptance_actor,
+    )
+    candidate["id"] = legacy["id"]
+    return _canonical_result(candidate, legacy, context, _CREATE_COMPARE_FIELDS)
+
... later lines omitted ...
```

### Pre-existing consumer context

```python
... earlier lines omitted ...
        )
    conn.execute(
        """INSERT INTO tm_tasks
           (par_number, project_id, title, description, price_rub, paid_rub,
            status, assignee, yougile_task_id, sync_revision,
            git_commits, created_at, updated_at, priority, acceptance_command,
            acceptance_oracle_json)
           VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 0, '[]', ?, ?, ?, ?, ?)""",
        (par, project_id, title, description, price_rub,
         status, assignee, yougile_task_id, now, now, priority, command, oracle_json),
    )
    task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {
        "id": task_id,
        "par_number": par,
        "project_id": project_id,
        "title": title,
        "description": description,
        "price_rub": price_rub,
        "paid_rub": 0,
        "status": status,
        "assignee": assignee,
        "yougile_task_id": yougile_task_id,
        "sync_revision": 0,
        "priority": priority,
        "acceptance_command": command,
        "acceptance_oracle_json": oracle_json,
        "created_at": now,
        "updated_at": now,
        "worker_session_id": None,
        "sync_revision": 0,
    }


def create_task_for_scope(scope: str, title: str) -> dict:
    """Create an unbound task in the project owning ``scope``."""
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            project = get_project_by_scope(conn, scope.rstrip("/"))
            if not project:
                raise ValueError(f"scope '{scope}' has no task project")
            task = create_task(conn, project["id"], title, status="new")
            conn.commit()
            return task
        except Exception:
            conn.rollback()
            raise


def discard_unbound_task(task_id: int) -> bool:
    """Remove a task allocated for a spawn that never published its worker."""
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "DELETE FROM tm_tasks WHERE id=? AND worker_session_id IS NULL AND status='new' "
            "AND NOT EXISTS (SELECT 1 FROM tm_task_reservations WHERE task_id=tm_tasks.id)",
            (task_id,),
        )
        conn.commit()
        return cur.rowcount == 1


def update_task(conn: sqlite3.Connection, task_id: int, *,
                title: str | None = None, description: str | None = None,
                price_rub: int | None = None, status: str | None = None,
                assignee: str | None = None, worker_session_id: str | None = None,
                git_commits: str | None = None,
                yougile_task_id: str | None = None,
... later lines omitted ...
```

## Case H

### Changed excerpt

```diff
... earlier lines omitted ...
 @router.get("/api/subagent-transcripts/{session_id}")
 async def subagent_transcript_ids(session_id: str):
-    """SDK agent_ids of sub-agents whose transcripts exist for this session."""
+    """SDK agent_ids represented by telemetry, including older SDK sessions."""
     sess = get_session(session_id)
     if not sess:
         return JSONResponse({"error": "session not found"}, status_code=404)
-    sdk_id = sess.get("session_id") or ""
-    if not sdk_id:
+    rows = get_subagents(session_id)
+    if not rows and not (sess.get("session_id") or ""):
         return {"agent_ids": [], "note": "no sdk_session_id yet"}
-    from claude_agent_sdk import list_subagents
-    try:
-        agent_ids = list_subagents(sdk_id, sess.get("cwd") or None)
-    except Exception as e:
-        logger.warning(f"list_subagents failed: {e}")
-        return {"agent_ids": [], "error": str(e)}
-    return {"agent_ids": agent_ids, "sdk_session_id": sdk_id}
+    agent_ids = _transcript_ids(rows, sess.get("cwd") or "")
+    current_sdk_id = sess.get("session_id") or ""
+    if current_sdk_id:
+        from claude_agent_sdk import list_subagents
+        try:
+            agent_ids.update(list_subagents(
+                current_sdk_id,
+                sess.get("cwd") or None,
+            ))
+        except Exception as e:
+            logger.warning("list_subagents failed for %s: %s", current_sdk_id, e)
+    return {"agent_ids": sorted(agent_ids), "sdk_session_id": current_sdk_id}
 
 
 @router.get("/api/subagent-transcript/{session_id}/{agent_id}")
 async def subagent_transcript(session_id: str, agent_id: str, limit: int = 200, offset: int = 0):
     """Full conversation of one sub-agent (lazy read from SDK JSONL store)."""
     if not _SAFE_ID.match(agent_id):
         return JSONResponse({"error": "invalid agent_id"}, status_code=400)
     sess = get_session(session_id)
     if not sess:
         return JSONResponse({"error": "session not found"}, status_code=404)
-    sdk_id = sess.get("session_id") or ""
+    telemetry = get_subagent(session_id, agent_id)
+    if telemetry and telemetry.get("task_type") == "local_bash":
+        return {
+            "messages": [],
+            "note": "background tasks do not have transcripts",
+        }
+    sdk_id = (
+        (telemetry or {}).get("sdk_session_id")
+        or sess.get("session_id")
+        or ""
+    )
     if not sdk_id:
         return {"messages": [], "note": "no sdk_session_id yet"}
     from claude_agent_sdk import get_subagent_messages
     try:
         msgs = get_subagent_messages(sdk_id, agent_id, sess.get("cwd") or None,
                                      limit=limit, offset=offset)
     except Exception as e:
         logger.warning(f"get_subagent_messages failed: {e}")
         return {"messages": [], "error": str(e)}
     out = []
     for m in msgs:
         content = m.message.get("content") if isinstance(m.message, dict) else m.message
diff --git a/tests/test_subagent_routes.py b/tests/test_subagent_routes.py
index ecf3bebd..70d14c23 100644
--- a/tests/test_subagent_routes.py
+++ b/tests/test_subagent_routes.py
@@ -13,48 +13,131 @@ async def test_transcript_rejects_path_traversal():
         assert r.status_code == 400
 
 
 @pytest.mark.asyncio
 async def test_transcript_ids_missing_session(monkeypatch):
     monkeypatch.setattr(sr, "get_session", lambda sid: None)
     r = await sr.subagent_transcript_ids("nope")
     assert r.status_code == 404
 
 
 @pytest.mark.asyncio
 async def test_transcript_ids_no_sdk_session(monkeypatch):
+    monkeypatch.setattr(sr, "get_subagents", lambda sid: [])
     monkeypatch.setattr(sr, "get_session", lambda sid: {"session_id": "", "cwd": "/c"})
     r = await sr.subagent_transcript_ids("sess-1")
... later lines omitted ...
```

## Case I

### Changed excerpt

```diff
... earlier lines omitted ...
index e01ec22b..1d203a5a 100644
--- a/.gitignore
+++ b/.gitignore
@@ -11,12 +11,15 @@ worktrees/
 data/
 .claude/
 .serena/
 .codex
 ..bfg-report/
 _screenshots/
 artifacts/
 docs/proxy-*.md
 docs/vps-*.md
 # Orchestra project state is canonical Git data.
 !.orchestra/
 !.orchestra/**
+
+# локальные инфра-заметки контура, не для публичного репозитория
+.orchestra/infra/
```
