# Candidate cand-61

## ORIGIN commit 2346bd703e (2026-07-29): #101: #101: record quota state on each turn
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/db.py b/app/db.py
index fffc2c226..e4050a38b 100644
--- a/app/db.py
+++ b/app/db.py
@@ -1,12 +1,13 @@
 """SQLite storage for sessions and logs."""
 
 import json
 import logging
+import math
 import os
 import sqlite3
 from datetime import datetime, timedelta, timezone
 from pathlib import Path
 
 logger = logging.getLogger("db")
 
 _DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "orchestra.db"
@@ -275,17 +276,21 @@ def init_db() -> None:
                 runtime TEXT NOT NULL,
                 model TEXT NOT NULL,
                 ok INTEGER NOT NULL,
                 stop_reason TEXT NOT NULL,
                 cost_usd REAL NOT NULL,
                 input_tokens INTEGER NOT NULL,
                 output_tokens INTEGER NOT NULL,
                 cache_read_tokens INTEGER NOT NULL,
-                cache_create_tokens INTEGER NOT NULL
+                cache_create_tokens INTEGER NOT NULL,
+                quota_five_hour_pct REAL,
+                quota_seven_day_pct REAL,
+                quota_primary_pct REAL,
+                quota_sampled_at TEXT
             );
             CREATE INDEX IF NOT EXISTS idx_turn_usage_ts ON turn_usage(ts);
             CREATE INDEX IF NOT EXISTS idx_turn_usage_session ON turn_usage(session_id, ts);
 
             CREATE TABLE IF NOT EXISTS improvement_rules (
                 id INTEGER PRIMARY KEY,
                 rule_text TEXT,
                 source_signal TEXT,
@@ -563,16 +568,24 @@ def _migrate(c) -> None:
     if turn_usage_cols and "scope" not in turn_usage_cols:
         c.execute(
             "ALTER TABLE turn_usage ADD COLUMN scope TEXT NOT NULL DEFAULT ''"
         )
     if turn_usage_cols and "task_id" not in turn_usage_cols:
         c.execute(
             "ALTER TABLE turn_usage ADD COLUMN task_id TEXT NOT NULL DEFAULT ''"
         )
+    if turn_usage_cols and "quota_five_hour_pct" not in turn_usage_cols:
+        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_five_hour_pct REAL")
+    if turn_usage_cols and "quota_seven_day_pct" not in turn_usage_cols:
+        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_seven_day_pct REAL")
+    if turn_usage_cols and "quota_primary_pct" not in turn_usage_cols:
+        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_primary_pct REAL")
+    if turn_usage_cols and "quota_sampled_at" not in turn_usage_cols:
+        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_sampled_at TEXT")
     # Идемпотентный сид профиля 'personal' (config_dir="" → env процесса, как сегодня).
     # INSERT OR IGNORE: повторная миграция не падает и не перетирает существующую строку.
     c.execute("INSERT OR IGNORE INTO profiles (name, config_dir) VALUES ('personal', '')")
     collector_started_at = datetime.now(timezone.utc).isoformat()
     c.execute(
         """INSERT OR IGNORE INTO kv(key, value)
            VALUES ('tool_error_collector_started_at', ?)""",
         (collector_started_at,),
@@ -1428,45 +1441,73 @@ def turn_usage_add(
     model: str,
     ok: bool,
     stop_reason: str,
     cost_usd: float,
     input_tokens: int,
     output_tokens: int,
     cache_read_tokens: int,
     cache_create_tokens: int,
+    quota_five_hour_pct: float | None = None,
+    quota_seven_day_pct: float | None = None,
+    quota_primary_pct: float | None = None,
+    quota_sampled_at: str | None = None,
     ts: str | None = None,
 ) -> bool:
     """Persist one provider-identified terminal turn; return false on replay."""
     if not event_id:
         return False
+    quota_pcts = (
+        quota_five_hour_pct,
+        quota_seven_day_pct,
+        quota_primary_pct,
+    )
+    if any(
+        isinstance(value, bool)
+        or not isinstance(value, (int, float))
+        or not math.isfinite(value)
+        or not 0 <= value <= 100
+        for value in quota_pcts
+        if value is not None
+    ):
+        raise ValueError("quota percentages must be finite numbers from 0 to 100")
+    if any(value is not None for value in quota_pcts) and not quota_sampled_at:
+        raise ValueError("quota_sampled_at is required with quota percentages")
+    if all(value is None for value in quota_pcts):
+        quota_sampled_at = None
     observed_at = ts or datetime.now(timezone.utc).isoformat()
     with _conn() as c:
         cursor = c.execute(
             """INSERT OR IGNORE INTO turn_usage
                (event_id, ts, session_id, scope, task_id,
                 runtime, model, ok, stop_reason,
                 cost_usd, input_tokens, output_tokens,
-                cache_read_tokens, cache_create_tokens)
-               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
+                cache_read_tokens, cache_create_tokens,
+                quota_five_hour_pct, quota_seven_day_pct,
+                quota_primary_pct, quota_sampled_at)
+               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
             (
                 event_id,
                 observed_at,
                 session_id,
                 scope,
                 task_id,
                 runtime,
                 model,
                 int(bool(ok)),
                 stop_reason,
                 max(0.0, float(cost_usd or 0)),
                 max(0, int(input_tokens or 0)),
                 max(0, int(output_tokens or 0)),
                 max(0, int(cache_read_tokens or 0)),
                 max(0, int(cache_create_tokens or 0)),
+                quota_five_hour_pct,
+                quota_seven_day_pct,
+                quota_primary_pct,
+                quota_sampled_at,
             ),
         )
         return cursor.rowcount == 1
 
 
 def rule_propose(
     rule_text: str,
     source_signal: str,
diff --git a/app/session_turns.py b/app/session_turns.py
index e8c6e7b79..85bf3fb24 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -1,16 +1,19 @@
 """TurnManager — turn lifecycle system over AgentSession state.
 
 Stateless method-holder: turn generation, auto-report, turn-end processing.
 All state stays on the session (persistence and event loop read it directly).
 """
 
 import asyncio
 import logging
+import math
+import time
+from datetime import datetime, timezone
 from typing import TYPE_CHECKING
 
 from app.db import turn_usage_add
 from app.events import AgentEvent
 from app.session_state import AgentStatus
 
 if TYPE_CHECKING:
     from app.session import AgentSession
@@ -59,16 +62,94 @@ def _format_limits() -> str:
             parts.append(f"7d:{sd_pct:.0f}%{reset_s}")
         return " | " + " ".join(parts) if parts else ""
     except Exception:
         return ""
 
 logger = logging.getLogger("app.session")
 
 
+def _unknown_quota_state() -> dict:
+    return {
+        "quota_five_hour_pct": None,
+        "quota_seven_day_pct": None,
+        "quota_primary_pct": None,
+        "quota_sampled_at": None,
+    }
+
+
+def _cached_quota_state(
+    runtime: str,
+    model: str,
+    *,
+    now: float | None = None,
+) -> dict:
+    from app.routes import system
+
+    if runtime in {"claude", "anthropic"}:
+        cache = system._usage_cache
+        data = cache.get("data")
+        windows = {
+            "quota_five_hour_pct": (data or {}).get("five_hour"),
+            "quota_seven_day_pct": (data or {}).get("seven_day"),
+            "quota_primary_pct": None,
+        }
+    elif runtime in {"codex", "codex_spark"}:
+        cache = system._codex_usage_cache
+        data = cache.get("data")
+        if runtime == "codex_spark" or model == "gpt-5.3-codex-spark":
+            data = (data or {}).get("spark")
+        windows = {
+            "quota_five_hour_pct": None,
+            "quota_seven_day_pct": None,
+            "quota_primary_pct": (data or {}).get("primary"),
+        }
+    elif runtime == "grok":
+        cache = system._grok_usage_cache
+        data = cache.get("data")
+        windows = {
+            "quota_five_hour_pct": None,
+            "quota_seven_day_pct": None,
+            "quota_primary_pct": (data or {}).get("primary"),
+        }
+    else:
+        return _unknown_quota_state()
+
+    sampled_ts = cache.get("ts")
+    if (
+        isinstance(sampled_ts, bool)
+        or not isinstance(sampled_ts, (int, float))
+        or not math.isfinite(sampled_ts)
+    ):
+        return _unknown_quota_state()
+    age = (time.time() if now is None else now) - sampled_ts
+    if not math.isfinite(age) or age < 0 or age >= system._USAGE_CACHE_TTL:
+        return _unknown_quota_state()
+
+    state = _unknown_quota_state()
+    for column, window in windows.items():
+        value = window.get("utilization") if isinstance(window, dict) else None
+        if (
+            not isinstance(value, bool)
+            and isinstance(value, (int, float))
+            and math.isfinite(value)
+            and 0 <= value <= 100
+        ):
+            state[column] = value
+    if all(value is None for key, value in state.items() if key != "quota_sampled_at"):
+        return _unknown_quota_state()
+    try:
+        state["quota_sampled_at"] = datetime.fromtimestamp(
+            sampled_ts, timezone.utc,
+        ).isoformat()
+    except (OSError, OverflowError, ValueError):
+        return _unknown_quota_state()
+    return state
+
+
 class TurnManager:
     def __init__(self, s: "AgentSession") -> None:
         self.s = s
 
     def cancel_auto_report(self) -> None:
         s = self.s
         if s._auto_report_task and not s._auto_report_task.done():
             s._auto_report_task.cancel()
@@ -123,31 +204,40 @@ class TurnManager:
 
     def handle_turn_end(self, event: AgentEvent) -> None:
         s = self.s
         meta = event.metadata
         s._turn_start = 0
         ok, sr, nt = s._cost.apply_turn_result(meta, event.usage)
         event_id = str(meta.get("event_id") or "")
         if event_id:
+            try:
+                quota_state = _cached_quota_state(s.backend_type, s.model)
+            except Exception as error:
+                logger.warning(
+                    f"[{s.name}] quota cache read failed: "
+                    f"{type(error).__name__}: {error}"
+                )
+                quota_state = _unknown_quota_state()
             s._submit_db_write(
                 turn_usage_add,
                 event_id=event_id,
                 session_id=s.id,
                 scope=s.scope,
                 task_id=s.task_id,
                 runtime=s.backend_type,
                 model=s.model,
                 ok=ok,
                 stop_reason=sr,
                 cost_usd=s._turn_cost,
                 input_tokens=meta.get("input_tokens", 0),
                 output_tokens=meta.get("output_tokens", 0),
                 cache_read_tokens=meta.get("cache_read", 0),
                 cache_create_tokens=meta.get("cache_create", 0),
+                **quota_state,
             )
         context_known, context_reason = s._cost.update_context_from_turn(
             meta, event.usage,
         )
         if context_reason:
             s._log(
                 "status",
                 f"context unknown ({context_reason}); automatic compaction skipped",
diff --git a/tests/test_session.py b/tests/test_session.py
index a439dba44..1c34edbf8 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -2226,16 +2226,25 @@ class TestRateLimitClassification:
     async def test_turn_end_persists_normalized_structured_usage(
         self, session, monkeypatch
     ):
         from app.events import AgentEvent
 
         monkeypatch.setattr("app.bg_jobs.bg_manager", None)
         add_usage = MagicMock(return_value=True)
         monkeypatch.setattr("app.session_turns.turn_usage_add", add_usage)
+        monkeypatch.setattr(
+            "app.session_turns._cached_quota_state",
+            lambda runtime, model: {
+                "quota_five_hour_pct": 12.5,
+                "quota_seven_day_pct": 41,
+                "quota_primary_pct": None,
+                "quota_sampled_at": "2026-07-29T08:00:00+00:00",
+            },
+        )
         self._capture_coroutines(session)
         session._hibernate.schedule = MagicMock()
 
         session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
             "event_id": "result-uuid-1",
             "ok": True,
             "stop_reason": "end_turn",
             "num_turns": 1,
@@ -2259,16 +2268,20 @@ class TestRateLimitClassification:
             task_id="",
             ok=True,
             stop_reason="end_turn",
             cost_usd=2.5,
             input_tokens=100,
             output_tokens=20,
             cache_read_tokens=75,
             cache_create_tokens=5,
+            quota_five_hour_pct=12.5,
+            quota_seven_day_pct=41,
+            quota_primary_pct=None,
+            quota_sampled_at="2026-07-29T08:00:00+00:00",
         )
 
     @pytest.mark.asyncio
     async def test_turn_telemetry_failure_does_not_skip_terminal_lifecycle(
         self, session, monkeypatch, caplog
     ):
         from app.events import AgentEvent
         from app.session import AgentStatus
diff --git a/tests/test_turn_usage.py b/tests/test_turn_usage.py
index d9213da1b..2956427ac 100644
--- a/tests/test_turn_usage.py
+++ b/tests/test_turn_usage.py
@@ -1,8 +1,10 @@
+import sqlite3
+import time
 from datetime import datetime, timezone
 
 import pytest
 
 
 @pytest.fixture
 def usage_db(tmp_path, monkeypatch):
     db_path = tmp_path / "turn-usage.db"
@@ -22,35 +24,188 @@ def test_turn_usage_requires_durable_event_id_and_deduplicates(usage_db):
         "model": "claude-opus-5[1m]",
         "ok": True,
         "stop_reason": "end_turn",
         "cost_usd": 1.25,
         "input_tokens": 100,
         "output_tokens": 20,
         "cache_read_tokens": 80,
         "cache_create_tokens": 5,
+        "quota_five_hour_pct": 12.5,
+        "quota_seven_day_pct": 41,
+        "quota_primary_pct": None,
+        "quota_sampled_at": "2026-07-29T08:00:00+00:00",
     }
 
     assert turn_usage_add(event_id="", **common) is False
     assert turn_usage_add(event_id="result-uuid-1", **common) is True
     assert turn_usage_add(
         event_id="result-uuid-1",
         **{**common, "cost_usd": 99.0},
     ) is False
 
     with _conn() as conn:
         rows = conn.execute("SELECT * FROM turn_usage").fetchall()
     assert len(rows) == 1
     assert rows[0]["event_id"] == "result-uuid-1"
     assert rows[0]["cost_usd"] == 1.25
     assert rows[0]["cache_read_tokens"] == 80
+    assert rows[0]["quota_five_hour_pct"] == 12.5
+    assert rows[0]["quota_seven_day_pct"] == 41
+    assert rows[0]["quota_primary_pct"] is None
+    assert rows[0]["quota_sampled_at"] == "2026-07-29T08:00:00+00:00"
     assert rows[0]["scope"] == ""
     assert rows[0]["task_id"] == ""
 
 
+def test_cached_quota_state_selects_fresh_runtime_window(monkeypatch):
+    from app.routes import system
+    from app.session_turns import _cached_quota_state
+
+    sampled_ts = 1785312000.0
+    sampled_at = datetime.fromtimestamp(sampled_ts, timezone.utc).isoformat()
+    monkeypatch.setattr(system, "_usage_cache", {
+        "data": {
+            "five_hour": {"utilization": 12.5},
+            "seven_day": {"utilization": 41},
+        },
+        "ts": sampled_ts,
+        "token": None,
+    })
+    monkeypatch.setattr(system, "_codex_usage_cache", {
+        "data": {
+            "primary": {"utilization": 63},
+            "spark": {"primary": {"utilization": 9}},
+        },
+        "ts": sampled_ts,
+    })
+    monkeypatch.setattr(system, "_grok_usage_cache", {
+        "data": {"primary": {"utilization": 27}},
+        "ts": sampled_ts,
+    })
+
+    assert _cached_quota_state(
+        "claude", "claude-opus-5[1m]", now=sampled_ts + 30,
+    ) == {
+        "quota_five_hour_pct": 12.5,
+        "quota_seven_day_pct": 41,
+        "quota_primary_pct": None,
+        "quota_sampled_at": sampled_at,
+    }
+    assert _cached_quota_state(
+        "codex", "gpt-5.6-sol", now=sampled_ts + 30,
+    )["quota_primary_pct"] == 63
+    assert _cached_quota_state(
+        "codex", "gpt-5.3-codex-spark", now=sampled_ts + 30,
+    )["quota_primary_pct"] == 9
+    assert _cached_quota_state(
+        "grok", "grok-4.5", now=sampled_ts + 30,
+    )["quota_primary_pct"] == 27
+
+
+@pytest.mark.parametrize("cache_data,cache_ts", [
+    (None, time.time()),
+    ({"primary": {"utilization": 88}}, time.time() - 301),
+])
+def test_cached_quota_state_returns_null_without_fresh_data(
+    usage_db, monkeypatch, cache_data, cache_ts,
+):
+    from app.routes import system
+    from app.db import _conn, turn_usage_add
+    from app.session_turns import _cached_quota_state
+
+    monkeypatch.setattr(system, "_codex_usage_cache", {
+        "data": cache_data,
+        "ts": cache_ts,
+    })
+
+    quota_state = _cached_quota_state("codex", "gpt-5.6-sol")
+    assert quota_state == {
+        "quota_five_hour_pct": None,
+        "quota_seven_day_pct": None,
+        "quota_primary_pct": None,
+        "quota_sampled_at": None,
+    }
+    assert turn_usage_add(
+        event_id="turn-without-quota",
+        session_id="session-1",
+        runtime="codex",
+        model="gpt-5.6-sol",
+        ok=True,
+        stop_reason="end_turn",
+        cost_usd=0.1,
+        input_tokens=10,
+        output_tokens=2,
+        cache_read_tokens=5,
+        cache_create_tokens=0,
+        **quota_state,
+    )
+    with _conn() as conn:
+        row = conn.execute(
+            "SELECT * FROM turn_usage WHERE event_id = 'turn-without-quota'"
+        ).fetchone()
+    assert row["quota_five_hour_pct"] is None
+    assert row["quota_seven_day_pct"] is None
+    assert row["quota_primary_pct"] is None
+    assert row["quota_sampled_at"] is None
+
+
+def test_turn_usage_migrates_existing_rows_with_unknown_quota(tmp_path, monkeypatch):
+    db_path = tmp_path / "old-turn-usage.db"
+    with sqlite3.connect(db_path) as conn:
+        conn.execute("""
+            CREATE TABLE turn_usage (
+                id INTEGER PRIMARY KEY,
+                event_id TEXT NOT NULL UNIQUE,
+                ts TEXT NOT NULL,
+                session_id TEXT NOT NULL,
+                scope TEXT NOT NULL DEFAULT '',
+                task_id TEXT NOT NULL DEFAULT '',
+                runtime TEXT NOT NULL,
+                model TEXT NOT NULL,
+                ok INTEGER NOT NULL,
+                stop_reason TEXT NOT NULL,
+                cost_usd REAL NOT NULL,
+                input_tokens INTEGER NOT NULL,
+                output_tokens INTEGER NOT NULL,
+                cache_read_tokens INTEGER NOT NULL,
+                cache_create_tokens INTEGER NOT NULL
+            )
+        """)
+        conn.execute("""
+            INSERT INTO turn_usage
+            (event_id, ts, session_id, runtime, model, ok, stop_reason,
+             cost_usd, input_tokens, output_tokens,
+             cache_read_tokens, cache_create_tokens)
+            VALUES ('old-turn', '2026-07-29T08:00:00+00:00', 'session-1',
+                    'codex', 'gpt-5.6-sol', 1, 'end_turn', 1, 10, 2, 5, 0)
+        """)
+    monkeypatch.setattr("app.db.DB_PATH", db_path)
+    from app.db import init_db
+
+    init_db()
+
+    with sqlite3.connect(db_path) as conn:
+        conn.row_factory = sqlite3.Row
+        columns = {row[1] for row in conn.execute("PRAGMA table_info(turn_usage)")}
+        row = conn.execute(
+            "SELECT * FROM turn_usage WHERE event_id = 'old-turn'"
+        ).fetchone()
+    assert {
+        "quota_five_hour_pct",
+        "quota_seven_day_pct",
+        "quota_primary_pct",
+        "quota_sampled_at",
+    } <= columns
+    assert row["quota_five_hour_pct"] is None
+    assert row["quota_seven_day_pct"] is None
+    assert row["quota_primary_pct"] is None
+    assert row["quota_sampled_at"] is None
+
+
 def test_turn_usage_records_collection_start_without_claiming_history(usage_db):
     from app.db import turn_usage_add
     from app.usage_analytics import build_usage_analytics
 
     observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
     turn_usage_add(
         event_id="turn-1",
         session_id="session-1",


## LATER FIX aa7a76100c (77.3 days later): V-847: #V-847: parallelize full pytest and isolate fixtures
lines of origin it changed/deleted: 4
(code only, capped 400 lines)

V-847: #V-847: parallelize full pytest and isolate fixtures

Orchestra-Operation: e3d2b274-4da5-46c5-a019-d0b959632090


diff --git a/app/manager.py b/app/manager.py
index 1cd684757..ef4963f54 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -70,24 +70,25 @@ from app.errtext import err_text
 from app.tasks import spawn_supervised
 
 logger = logging.getLogger(__name__)
 
 _adhoc_serial = itertools.count(1)
 
 
 def enc_cli_dir(cwd: str) -> str:
-    """~/.claude/projects/<this> — cwd with '/' and '.' mapped to '-'. Case preserved.
+    """~/.claude/projects/<this> — path separators, dots, and underscores map to '-'.
+    Case is preserved.
 
     The leading '-' (from the leading '/') is part of the name and must stay:
     stripping it produced a directory the CLI never reads. The CLI also maps
-    dots in temporary paths to '-'. scripts/migrate_agent.py re-exports this
+    dots and underscores in temporary paths to '-'. scripts/migrate_agent.py re-exports this
     function so the encoding cannot drift a second time.
     """
-    return cwd.replace("/", "-").replace(".", "-")
+    return cwd.replace("/", "-").replace(".", "-").replace("_", "-")
 
 
 # Клиент MCP отваливается по таймауту через 30 с (mcp_stdio.py). Ждём заведомо меньше,
 # чтобы вызывающий получил внятный отказ, а не ReadTimeout, неотличимый от мёртвого сервера.
 LOCK_WAIT_LIMIT_SECONDS = 25.0
 class LockBusy(RuntimeError):
     """Лок сессии занят дольше отведённого: у вызова есть кто уступить и кому повторить."""
 
diff --git a/app/merge_test_gate.py b/app/merge_test_gate.py
index 5a5a192c4..0562484a6 100644
--- a/app/merge_test_gate.py
+++ b/app/merge_test_gate.py
@@ -286,50 +286,71 @@ def pytest_argv(
 # сюда не попадают и провал не считается дважды.
 # Вердикт берётся ПОСЛЕДНИЙ на строке, а не первый: nodeid параметризованного теста содержит
 # произвольный текст, в том числе пробелы и сами эти слова. Замер #336 — на строке
 # `tests/test_a.py::t2[a b PASSED c] FAILED [2%]` нежадный разбор возвращал PASSED, то есть
 # КРАСНЫЙ тест читался как зелёный; это ровно то направление ошибки, которого быть не должно.
 # Требование пробела перед вердиктом отсекает `nodeid[FAILED]` у теста, который ещё идёт.
 _NODEID_RE = re.compile(r"^\S+\.py::\S")
 _VERDICT_RE = re.compile(r"\s(?P<verdict>PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)(?=\s|$)")
+_XDIST_VERDICT_RE = re.compile(
+    r"^\[gw\d+\]\s+\[\s*\d+%\]\s+"
+    r"(?P<verdict>PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)\s+"
+    r"(?P<nodeid>\S+\.py::.+)$"
+)
 
 
 def _partial_progress(output: str, tests: list[str]) -> dict:
     """Что pytest успел сообщить до убийства по таймауту.
 
     Обе неудачи приходят одним и тем же `TimeoutExpired`, и без разбора этого выхода они
     неразличимы. Замер #336 на живых операциях: у #248 в убитом выходе стояли девять `F`
     (настоящая краснота), у #329 — сплошные точки (набор зелёный, просто не доехал); гейт
     доложил обоим одно и то же «inconclusive».
     """
     failed: list[str] = []
     passed_tests: list[str] = []
     passed = 0
     seen_files: set[str] = set()
     stopped_in = ""
+    running: set[str] = set()
     for raw in output.splitlines():
         line = raw.rstrip()
+        xdist_verdict = _XDIST_VERDICT_RE.match(line)
+        if xdist_verdict:
+            nodeid = xdist_verdict.group("nodeid").strip()
+            verdict = xdist_verdict.group("verdict")
+            running.discard(nodeid)
+            seen_files.add(nodeid.split("::", 1)[0])
+            if verdict in {"FAILED", "ERROR"}:
+                failed.append(nodeid)
+            elif verdict == "PASSED":
+                passed += 1
+                passed_tests.append(nodeid)
+            stopped_in = sorted(running)[-1] if running else ""
+            continue
         if not _NODEID_RE.match(line):
             continue
         verdicts = list(_VERDICT_RE.finditer(line))
         if not verdicts:
             # Имя напечатано, вердикта ещё нет — на этом тесте нас и прервали.
             stopped_in = line.strip()
+            running.add(stopped_in)
             seen_files.add(stopped_in.split("::", 1)[0])
             continue
         last = verdicts[-1]
         nodeid = line[:last.start()].strip()
+        running.discard(nodeid)
         seen_files.add(nodeid.split("::", 1)[0])
         if last.group("verdict") in {"FAILED", "ERROR"}:
             failed.append(nodeid)
         elif last.group("verdict") == "PASSED":
             passed += 1
             passed_tests.append(nodeid)
-        stopped_in = ""
+        stopped_in = sorted(running)[-1] if running else ""
     return {
         "failed_tests": failed,
         "passed_tests": passed_tests,
         "passed_count": passed,
         "stopped_in": stopped_in,
         "unreached": [test for test in tests if test not in seen_files],
     }
 
diff --git a/pyproject.toml b/pyproject.toml
index 9979e2609..4bb986433 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -52,17 +52,17 @@ exclude-newer = "2026-10-07T00:00:00Z"
 [tool.pytest.ini_options]
 # Живые пробы сняты со ВСЯКОГО прогона, а не только с команды merge-gate (#328 закрыл
 # лишь гейт). Плоский `uv run pytest -q` собирал их обратно и вис до упора на исчерпанной
 # квоте Codex: замер #336 — прогон убит по общему таймауту с EXIT=124 на 78%, окно потеряно
 # молча. Защита, действующая только когда запускающий помнит про флаг, в автоматике не
 # исполняется. CLI перебивает эту строку, а не складывается с ней (`-m` — одно значение,
 # побеждает последнее): `pytest -m live_probe tests/` собирает 3 пробы из 3214, обычный
 # прогон — 3211 из 3214, ровно столько же, сколько командой гейта.
-addopts = ["-m", "not live_probe"]
+addopts = ["-m", "not live_probe", "-n", "2", "--dist=loadscope"]
 testpaths = ["tests"]
 norecursedirs = ["worktrees", ".venv", "data", "docs"]
 markers = [
     "needs_two_users: требует беспарольного sudo — владение файлами не моделируется заглушками",
     "needs_model: требует эмбеддер (orchestra[rag]) — индексация и поиск не моделируются заглушками",
     "browser: поднимает НАСТОЯЩИЙ Chromium через Playwright. Снят с блокирующего набора merge-гейта (`-m \"not live_probe and not browser\"`), но продолжает гоняться в CI отдельной джобой и вручную: `uv run pytest -m browser tests/`. Маркер ставится автоматически по факту запроса браузерной фикстуры (`tests/conftest.py`), списком файлов не задаётся. Состав закреплён `test_browser_inventory_is_explicit`",
     "live_probe: тратит настоящий ход провайдера (поднимает CLI, шлёт запрос). Краснеет от квоты и капризов провайдера, а не от диффа, поэтому merge-gate его не гоняет — запускать вручную `uv run pytest -m live_probe tests/`. Новую такую пробу заводить только вместе с записью в test_live_probe_inventory_is_explicit",
 ]
diff --git a/scripts/migrate_agent.py b/scripts/migrate_agent.py
index 63c9d6704..463db9295 100755
--- a/scripts/migrate_agent.py
+++ b/scripts/migrate_agent.py
@@ -13,17 +13,17 @@ target's orchestra root / scope root.
         --name ParsingMaxim \
         --from root@laptop --to root@<VPS_IP> \
         --from-orchestra /mnt/data/Projects/Python/orchestra \
         --to-orchestra   /home/kesha/orchestra \
         --from-scope /mnt/data/Projects/Python/Parsing \
         --to-scope   /home/kesha/projects/Parsing
 
 Two path encodings are handled (matching the app):
-  - CLI transcript dir : app.manager.enc_cli_dir (leading '-' kept, '.' → '-')
+  - CLI transcript dir : app.manager.enc_cli_dir (leading '-' kept, '.', '_' → '-')
   - worktree subdir    : <root>/worktrees/<slugify(scope)>/<name>   (lowercased)
 
 Everything is created over ssh as root, but Orchestra and the Claude CLI run as the
 service user — so every path we write is handed over with chown and verified.
 
 Preconditions (fail loud): the orchestrator and every non-archived worker must be IDLE.
 """
 
diff --git a/tests/test_audit0901_delivery.py b/tests/test_audit0901_delivery.py
index d8105b245..908a7a3e8 100644
--- a/tests/test_audit0901_delivery.py
+++ b/tests/test_audit0901_delivery.py
@@ -93,44 +93,53 @@ async def _accept(*, delivery_id, message):
 class _FakeRequest:
     def __init__(self):
         self.disconnected = False
 
     async def is_disconnected(self):
         return self.disconnected
 
 
+@pytest.fixture
+def live_broker(monkeypatch):
+    from app import live_broker as live_broker_module
+    from app.live_broker import LiveBroker
+
+    broker = LiveBroker()
+    monkeypatch.setattr(live_broker_module, "broker", broker)
+    return broker
+
+
 async def _next_event(events):
     raw = await events.__anext__()
     return json.loads(raw.removeprefix("data: ").strip())
 
 
 @pytest.mark.asyncio
 async def test_stream_reports_the_live_status_after_the_session_loads(
-    delivery_db, monkeypatch,
+    delivery_db, monkeypatch, live_broker,
 ):
     """Стрим, открытый на НЕ загруженной сессии, обязан догнать её реальный статус."""
     from app.deps import manager
-    from app.live_broker import broker
     from app.routes.sessions import stream_session_logs
 
     assert manager.get(TARGET_ID) is None, "сессия не должна быть загружена на коннекте"
     response = await stream_session_logs(TARGET_NAME, SCOPE, _FakeRequest())
     events = response.body_iterator
     try:
         opened = await _next_event(events)
         assert opened["type"] == "__session"
         assert opened["agent_status"] == "idle"
 
         # Воркеру пришло сообщение: сессию загрузили, пошёл ход, логи идут в ТОТ ЖЕ стрим.
         monkeypatch.setitem(
             manager.sessions, TARGET_ID,
             SimpleNamespace(status=SimpleNamespace(value="running")),
         )
-        broker.publish(TARGET_ID, {"type": "stream", "content": "работаю"})
+        live_broker.publish(TARGET_ID, {"type": "stream", "content": "работаю"})
 
         live = await _next_event(events)
         assert live["type"] == "stream"
         assert live["agent_status"] == "running", (
             "статус заморожен на коннекте: событие идущего хода штампуется 'idle', "
             "и клиент затирает им верный статус из опроса"
         )
     finally:
diff --git a/tests/test_compact_chat_672.py b/tests/test_compact_chat_672.py
index bb8ae78dc..b7d1fe5ea 100644
--- a/tests/test_compact_chat_672.py
+++ b/tests/test_compact_chat_672.py
@@ -96,17 +96,17 @@ async def test_compact_events_and_statuses_do_not_reach_telegram_or_mirror(tb, m
          "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
     ])
 
     assert sent == []
     assert mirrored == []
 
 
 def test_compact_journal_rows_render_as_one_separate_collapsible_block(
-    dashboard_browser: Browser,
+    dashboard_browser: Browser, tmp_path: Path,
 ):
     fixture_path = Path(__file__).parent.parent / ".orchestra/tasks/V-672/compact-fixture.json"
     fixture = json.loads(fixture_path.read_text())
     assert fixture["source"]["legacy_tool_result_rows_without_tool_use_id"] == 34
     page = _open_tool_correlation_page(dashboard_browser, compact_mode=False)
     page.evaluate("""fixture => {
         for (const row of fixture.events) {
             addChatEntry('compact_event', JSON.stringify(row.content), null, null, {
@@ -131,17 +131,17 @@ def test_compact_journal_rows_render_as_one_separate_collapsible_block(
     expect(card).to_contain_text("Context compaction")
     expect(card).to_contain_text("In progress")
     card.evaluate("""card => {
         card.open = true;
         card.querySelector('details[data-phase="audit"]').open = true;
         card.querySelector('details[data-phase="audit"] details').open = true;
     }""")
     assert card.evaluate("card => card.open && card.querySelector('details[data-phase=\"audit\"]').open")
-    screenshot = Path(__file__).parent.parent / ".orchestra/tasks/V-672/compact-card.png"
+    screenshot = tmp_path / "compact-card.png"
     page.evaluate("""() => {
         const clone = document.querySelector('.compact-event-card').cloneNode(true);
         clone.id = 'compact-card-screenshot';
         clone.style.cssText = 'position:fixed;top:8px;left:8px;width:900px;max-height:none;overflow:visible;z-index:99999;background:#0b1120';
         document.body.appendChild(clone);
     }""")
     page.locator("#compact-card-screenshot").screenshot(path=str(screenshot))
     page.locator("#compact-card-screenshot").evaluate("node => node.remove()")
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 466dc31a4..5e84f7151 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -1036,17 +1036,19 @@ def test_hidden_orchestrator_menu_shares_tab_status_and_cache_builders():
     assert "_updateHiddenBtn()" in live_update
 
 
 def test_hidden_orchestrator_list_reuses_tab_status_and_cache(dashboard_browser: Browser):
     page = dashboard_browser.new_page()
     try:
         _goto_dashboard(page)
         result = page.evaluate("""() => {
-            const turn = new Date(Date.now() - 5 * 60_000).toISOString();
+            const now = Date.now();
+            Date.now = () => now;
+            const turn = new Date(now - 5 * 60_000).toISOString();
             const rows = [
                 {name: 'running-orchestrator', status: 'running', any_running: true, any_waiting: false},
                 {name: 'waiting-orchestrator', status: 'idle', any_running: false, any_waiting: true},
                 {name: 'idle-orchestrator', status: 'idle', any_running: false, any_waiting: false},
             ].map((row, index) => ({
                 id: `hidden-${index}`, scope: `/hidden/${index}`, ...row,
                 cache_ttl_seconds: 3600, last_turn_ts: turn,
             }));
diff --git a/tests/test_grok_usage_frontend.py b/tests/test_grok_usage_frontend.py
index 7295cf020..8f5d6d0d8 100644
--- a/tests/test_grok_usage_frontend.py
+++ b/tests/test_grok_usage_frontend.py
@@ -4,19 +4,16 @@ import pytest
 from playwright.sync_api import Browser, expect, sync_playwright
 
 
 ROOT = Path(__file__).parent.parent
 UTILS_JS = ROOT / "app/static/js/utils.js"
 CONNECTION_JS = ROOT / "app/static/js/connection.js"
 USAGE_JS = ROOT / "app/static/js/usage.js"
 STYLE_CSS = ROOT / "app/static/css/style.css"
-USAGE_SHOT_DIR = ROOT / ".orchestra/tasks/356"
-
-
 @pytest.fixture(scope="module")
 def browser():
     with sync_playwright() as playwright:
         instance = playwright.chromium.launch(headless=True)
         yield instance
         instance.close()
 
 
@@ -204,18 +201,17 @@ def test_usage_bar_shows_spark_label_and_release_statuses(browser):
         spark: _quotaMapLaneRelease(_usageData.codex.spark.primary, 'codex_spark').status,
     })""")
     assert release_states == {"short": "open", "gated": "opens_in", "spark": "open"}
     for provider in ("claude", "codex", "codex-spark"):
         expect(page.locator(f'[data-usage-compact-provider="{provider}"]')).to_have_count(1)
     page.close()
 
 
-def test_usage_bar_renders_each_provider_as_two_columns(browser):
-    USAGE_SHOT_DIR.mkdir(parents=True, exist_ok=True)
+def test_usage_bar_renders_each_provider_as_two_columns(browser, tmp_path):
     usage = {
         "anthropic": {
             "five_hour": {"utilization": 38, "window_minutes": 300, "resets_at": "2099-01-01T00:00:00.000Z"},
             "seven_day": {"utilization": 60, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
         },
         "codex": {
             "primary": {"utilization": 40, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
             "spark": {"primary": {"utilization": 57, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"}},
@@ -309,17 +305,17 @@ def test_usage_bar_renders_each_provider_as_two_columns(browser):
 
         for provider in ("claude", "codex", "codex-spark", "grok"):
             expect(page.locator(f'[data-usage-compact-provider="{provider}"]')).to_have_count(1)
 
         bounds = page.locator("#usage-bar").bounding_box()
         assert bounds is not None
         assert bounds["height"] < 63
 
-        page.locator("#usage-bar").screenshot(path=str(USAGE_SHOT_DIR / f"usage-bar-provider-grid-{width}.png"))
+        page.locator("#usage-bar").screenshot(path=str(tmp_path / f"usage-bar-provider-grid-{width}.png"))
         page.close()
 
 
 def test_usage_controls_stay_visible_across_desktop_widths(browser):
     for width in (1280, 1440, 1680, 1920):
         page = _page(browser, True)
         page.set_viewport_size({"width": width, "height": 900})
         page.add_style_tag(path=str(STYLE_CSS))
diff --git a/tests/test_live_tool_activity_831.py b/tests/test_live_tool_activity_831.py
index f470d6521..eb096e7b8 100644
--- a/tests/test_live_tool_activity_831.py
+++ b/tests/test_live_tool_activity_831.py
@@ -40,16 +40,25 @@ def session(monkeypatch):
 @pytest.fixture
 def published(monkeypatch):
     from app.live_broker import broker
     out = []
     monkeypatch.setattr(broker, "publish", lambda sid, payload: out.append(payload))
     return out
 
 
+@pytest.fixture
+def live_broker(monkeypatch):
+    from app import live_broker as live_broker_module
+
+    broker = LiveBroker()
+    monkeypatch.setattr(live_broker_module, "broker", broker)
+    return broker
+
+
 # ── session: partials go to the broker, never to the DB ──
 
 def test_tool_arguments_and_thinking_are_brokered_not_persisted(session, published):
     session._log = MagicMock()
     session._submit_db_write = MagicMock()
     meta = {"tool_use_id": "toolu_A", "tool_name": "Bash", "short_name": "Bash"}
 
     session._handle_event(AgentEvent("tool_input_stream", "", meta))
@@ -72,27 +81,25 @@ def test_subagent_partials_nest_under_their_subagent(session, published):
 
     assert published == [{"type": "subagent_stream", "event_type": "tool_input_stream",
                           "content": '{"file_path"', "subagent_id": "task-1",
                           "item_id": "toolu_S", "tool_name": "Read"}]
     session._log.assert_not_called()
 
 
 @pytest.mark.asyncio
-async def test_final_tool_call_is_persisted_and_retires_the_live_replay(session):
-    from app.live_broker import broker
-    broker.clear_live(session.id)
+async def test_final_tool_call_is_persisted_and_retires_the_live_replay(session, live_broker):
     session._handle_event(AgentEvent("tool_input_stream", '{"command": "ls"}',
                                      {"tool_use_id": "toolu_F", "tool_name": "Bash"}))
-    assert ("tool_input_stream", "toolu_F") in broker._live.get(session.id, {})
+    assert ("tool_input_stream", "toolu_F") in live_broker._live.get(session.id, {})
 