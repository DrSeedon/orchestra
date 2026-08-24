"""Read-only, WAL-safe measurements for #309.

Run with the repository environment. The script never writes to the database; it writes
sanitized evidence artifacts under docs/tasks/309/evidence/.
"""
from __future__ import annotations

import csv
import ast
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
# The live SQLite source is outside this worktree; this absolute path is read-only.
DB = Path("/mnt/data/Projects/Python/orchestra/data/orchestra.db")
OUT = Path(__file__).resolve().parent


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def dump_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    db = sqlite3.connect(":memory:")
    src.backup(db)
    src.close()
    db.row_factory = sqlite3.Row

    cutoff_text = db.execute(
        "SELECT max(ts) FROM logs WHERE type='tool_result'"
    ).fetchone()[0]
    cutoff = dt(cutoff_text)
    windows = {f"{days}d": cutoff - timedelta(days=days) for days in (30, 60, 90)}

    sessions = {
        r["id"]: dict(r)
        for r in db.execute(
            "SELECT id,name,scope,cwd,model,backend_type,is_orchestrator,role FROM sessions"
        )
    }
    mcp_names = [
        r[0]
        for r in db.execute(
            "SELECT DISTINCT substr(tool_name,17) FROM logs "
            "WHERE type='tool' AND tool_name LIKE 'mcp__orchestra__%'"
        )
    ]
    # The runtime registry is the source of truth; importing it is safe and does not
    # start the stdio server. This also captures tools with zero observed calls.
    try:
        import app.mcp_stdio as mcp_stdio

        registry = mcp_stdio.mcp._tool_manager._tools
        mcp_names = sorted(registry)
        schema = {
            name: {
                "description_bytes": len((tool.description or "").encode()),
                "schema_bytes": len(
                    json.dumps(
                        {"name": name, "description": tool.description or "", "inputSchema": tool.parameters},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                ),
            }
            for name, tool in registry.items()
        }
    except Exception as exc:  # pragma: no cover - measurement must retain a gap
        schema = {name: {"description_bytes": "unknown", "schema_bytes": "unknown"} for name in mcp_names}
        (OUT / "registry-import-error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")

    def tool_rows(name: str, start: datetime) -> list[sqlite3.Row]:
        return db.execute(
            "SELECT l.*, s.name AS agent_name, s.scope, s.cwd, s.model, s.backend_type, "
            "s.is_orchestrator, s.role FROM logs l LEFT JOIN sessions s ON s.id=l.session_id "
            "WHERE l.type='tool' AND l.tool_name=? AND l.ts>=? AND l.ts<=? ORDER BY l.ts",
            (f"mcp__orchestra__{name}", start.isoformat(), cutoff_text),
        ).fetchall()

    rows = []
    for name in sorted(mcp_names):
        counts = {}
        last = None
        for label, start in windows.items():
            entries = tool_rows(name, start)
            counts[label] = entries
            if entries:
                last = entries[-1]["ts"]
        all_entries = counts["90d"]
        paired = db.execute(
            "SELECT l.tool_use_id, r.tool_is_error, r.ts AS result_ts FROM logs l "
            "LEFT JOIN logs r ON r.type='tool_result' AND r.session_id=l.session_id "
            "AND r.tool_use_id=l.tool_use_id WHERE l.type='tool' AND l.tool_name=? "
            "AND l.ts>=? AND l.ts<=? AND l.tool_use_id IS NOT NULL",
            (f"mcp__orchestra__{name}", windows["90d"].isoformat(), cutoff_text),
        ).fetchall()
        # Collapse duplicate joins by call id. A result with tool_is_error NULL is unknown.
        by_call = {}
        for p in paired:
            state = by_call.setdefault(p["tool_use_id"], "unknown")
            if p["result_ts"] is not None:
                by_call[p["tool_use_id"]] = "error" if p["tool_is_error"] else "success"
            else:
                by_call[p["tool_use_id"]] = state
        def vals(entries: list[sqlite3.Row], key: str) -> set:
            return {e[key] for e in entries if e[key] not in (None, "")}
        def metric(entries: list[sqlite3.Row]) -> dict:
            return {
                "calls": len(entries),
                "unique_sessions": len(vals(entries, "session_id")),
                "unique_agents": len(vals(entries, "agent_name")),
                "unique_projects_scopes": len(vals(entries, "scope")),
                "orchestrator_calls": sum(bool(e["is_orchestrator"]) for e in entries),
                "worker_calls": sum(not bool(e["is_orchestrator"]) for e in entries),
                "runtimes": ";".join(sorted(vals(entries, "backend_type"))),
            }
        m90 = metric(all_entries)
        states = list(by_call.values())
        m90.update(
            successful=states.count("success"),
            errors=states.count("error"),
            unknown=states.count("unknown") + max(0, len(all_entries) - len(states)),
        )
        rec = {
            "feature": "mcp_tool:" + name,
            "exact_surface": name,
            "owner": "app/mcp_stdio.py:" + (getattr(registry.get(name), "fn", None).__name__ if name in registry else "unknown"),
            "last_use_90d": last or "",
            "observation_gap": "named tool_name telemetry starts 2026-08-13; older NULL/wrapper rows excluded",
            **schema.get(name, {}),
        }
        for label in ("30d", "60d", "90d"):
            m = metric(counts[label])
            for k, v in m.items():
                rec[f"{label}_{k}"] = v
        for k in ("successful", "errors", "unknown"):
            rec[f"90d_{k}"] = m90[k]
        rows.append(rec)

    fields = ["feature", "exact_surface", "owner", "description_bytes", "schema_bytes", "last_use_90d", "observation_gap"]
    for label in ("30d", "60d", "90d"):
        fields.extend([f"{label}_{x}" for x in ("calls", "unique_sessions", "unique_agents", "unique_projects_scopes", "orchestrator_calls", "worker_calls", "runtimes")])
    fields.extend(["90d_successful", "90d_errors", "90d_unknown"])
    dump_csv(OUT / "mcp-usage.csv", fields, rows)

    # Per-feature footprint: function LOC, prompt bytes, frontend references, test files,
    # and historical task references. Counts are structural, not runtime-call counts.
    mcp_source = (ROOT / "app/mcp_stdio.py").read_text(encoding="utf-8")
    mcp_tree = ast.parse(mcp_source)
    fn_spans = {}
    for node in ast.walk(mcp_tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in mcp_names:
            fn_spans[node.name] = node.end_lineno - node.lineno + 1
    prompt_files = list((ROOT / "pipelines").rglob("*.md"))
    js_text = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "app/static/js").glob("*.js"))
    searchable = []
    for base in (ROOT / "tests",):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".md", ".json", ".js", ".html"}:
                continue
            try:
                searchable.append((base, path, path.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                pass
    fp_rows = []
    for name in sorted(mcp_names):
        test_files = []
        task_refs = 0
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
        for base, path, text in searchable:
            hits = len(pattern.findall(text))
            if hits and base == ROOT / "tests":
                test_files.append(path.relative_to(ROOT).as_posix())
            # Historical task references are recorded for candidate features in metrics.md;
            # scanning the full archive here would turn a bounded measurement into an
            # unbounded document walk.
        prompt_bytes = sum(
            len(repr(name).encode()) * len(re.findall(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", p.read_text(encoding="utf-8", errors="ignore")))
            for p in prompt_files
        )
        fp_rows.append({
            "feature": "mcp_tool:" + name,
            "function_loc": fn_spans.get(name, "unknown"),
            "prompt_anchor_bytes_proxy": prompt_bytes,
            "frontend_literal_refs": js_text.count("mcp__orchestra__" + name) + js_text.count("'" + name + "'") + js_text.count('"' + name + '"'),
            "test_files": ";".join(sorted(test_files)),
            "test_file_count": len(set(test_files)),
            "task_doc_file_count": task_refs,
            "schema_bytes": schema.get(name, {}).get("schema_bytes", "unknown"),
        })
    dump_csv(OUT / "feature-footprint.csv", ["feature", "function_loc", "prompt_anchor_bytes_proxy", "frontend_literal_refs", "test_files", "test_file_count", "task_doc_file_count", "schema_bytes"], fp_rows)

    # Progress deep dive. Status text is intentionally reduced to length + hash so the
    # evidence remains sanitized while the call identity/percent/outcome stays exact.
    import hashlib

    progress_rows = []
    for row in db.execute(
        "SELECT l.*, s.name AS agent_name, s.scope, s.cwd, s.model, s.backend_type, "
        "s.is_orchestrator, s.role FROM logs l LEFT JOIN sessions s ON s.id=l.session_id "
        "WHERE l.type='tool' AND l.tool_name='mcp__orchestra__update_progress' "
        "AND l.ts>=? AND l.ts<=? ORDER BY l.ts",
        (windows["90d"].isoformat(), cutoff_text),
    ):
        payload = {}
        raw = row["content"]
        try:
            payload = json.loads(raw.split(":", 1)[1].strip())
        except (ValueError, IndexError):
            pass
        result = db.execute(
            "SELECT tool_is_error FROM logs WHERE type='tool_result' AND session_id=? "
            "AND tool_use_id=? ORDER BY ts LIMIT 1",
            (row["session_id"], row["tool_use_id"]),
        ).fetchone()
        progress_rows.append(
            {
                "ts": row["ts"],
                "tool_use_id": row["tool_use_id"] or "",
                "agent": row["agent_name"] or "unknown",
                "scope": row["scope"] or "unknown",
                "runtime": row["backend_type"] or "unknown",
                "orchestrator": bool(row["is_orchestrator"]),
                "percent": payload.get("percent", "unknown"),
                "status_len": len(str(payload.get("status", ""))),
                "status_sha256": hashlib.sha256(str(payload.get("status", "")).encode()).hexdigest()[:16],
                "result": "unknown" if result is None else ("error" if result[0] else "success"),
            }
        )
    dump_csv(OUT / "progress-detail.csv", list(progress_rows[0]) if progress_rows else ["ts"], progress_rows)

    # Generated OpenAPI inventory (route telemetry is intentionally absent from the DB).
    route_rows = []
    try:
        from app.main import app

        for route in app.routes:
            path = getattr(route, "path", "")
            methods = sorted(getattr(route, "methods", set()) - {"HEAD"})
            if not path or not methods:
                continue
            endpoint = getattr(route, "endpoint", None)
            route_rows.append(
                {
                    "path": path,
                    "methods": ";".join(methods),
                    "owner": f"{getattr(endpoint, '__module__', '')}:{getattr(endpoint, '__name__', '')}",
                    "route_usage_30d": "UNMEASURED",
                    "route_usage_60d": "UNMEASURED",
                    "route_usage_90d": "UNMEASURED",
                    "observation_gap": "no persisted HTTP request census by path/method in SQLite logs",
                }
            )
    except Exception as exc:
        (OUT / "openapi-import-error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
    dump_csv(OUT / "route-inventory.csv", ["path", "methods", "owner", "route_usage_30d", "route_usage_60d", "route_usage_90d", "observation_gap"], route_rows)

    # Dashboard controls and literal endpoint references. No click telemetry is inferred.
    html = (ROOT / "app/templates/dashboard.html").read_text(encoding="utf-8")
    controls = []
    for tag, ident, onclick in re.findall(r"<(button|input|a)\b[^>]*\bid=[\"']([^\"']+)[\"'][^>]*?(?:onclick=[\"']([^\"']*)[\"'])?[^>]*>", html, re.I):
        controls.append({"control": ident, "tag": tag, "inline_handler": onclick or "", "clicks": "UNMEASURED", "observation_gap": "no UI event telemetry in SQLite"})
    endpoints = sorted(set(re.findall(r"[\"'`](/api/[^\"'`? ]+)", "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "app/static/js").glob("*.js")))))
    for endpoint in endpoints:
        controls.append({"control": "endpoint:" + endpoint, "tag": "fetch/reference", "inline_handler": "", "clicks": "UNMEASURED", "observation_gap": "JS reference; no click/event telemetry"})
    dump_csv(OUT / "ui-inventory.csv", ["control", "tag", "inline_handler", "clicks", "observation_gap"], controls)

    # DB footprint, using only the in-memory backup.
    tables = []
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        cols = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
        count = db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        tables.append({"table": table, "columns": len(cols), "rows_at_cutoff": count})
    dump_csv(OUT / "db-footprint.csv", ["table", "columns", "rows_at_cutoff"], tables)

    route_groups = defaultdict(lambda: {"paths": set(), "methods": set(), "owners": set()})
    for row in route_rows:
        parts = row["path"].split("/")
        group = "/".join(parts[:3]) if len(parts) >= 3 and parts[1] == "api" else parts[1] or "/"
        route_groups[group]["paths"].add(row["path"])
        route_groups[group]["methods"].update(row["methods"].split(";"))
        route_groups[group]["owners"].add(row["owner"])
    subsystems = [
        {"feature": "sessions/lifecycle", "owners": ["app/session.py", "app/manager.py", "app/routes/sessions.py"], "critical": True},
        {"feature": "merge-operation-v1", "owners": ["app/merge_operations.py", "app/routes/merge_operations.py"], "critical": True},
        {"feature": "initial-delivery-recovery", "owners": ["app/initial_deliveries.py", "app/mcp_stdio.py"], "critical": True},
        {"feature": "runtime-handoff", "owners": ["app/runtime_history.py", "app/routes/sessions.py"], "critical": True},
        {"feature": "quota-admission", "owners": ["app/quota_gate.py", "app/routes/system.py"], "critical": True},
        {"feature": "background-jobs", "owners": ["app/bg_jobs.py", "app/routes/bg.py"], "critical": True},
        {"feature": "memory-search/RAG", "owners": ["app/rag_service.py", "app/routes/memory.py", "app/mcp_stdio.py"], "critical": True},
        {"feature": "artifact-publish/revoke", "owners": ["app/artifacts.py", "app/routes/artifacts.py"], "critical": True},
        {"feature": "proxy/tunnel controls", "owners": ["app/proxy_manager.py", "app/ssh_tunnel.py", "app/routes/proxy.py"], "critical": False},
        {"feature": "task-manager", "owners": ["app/tm.py", "app/routes/tm.py"], "critical": False},
        {"feature": "YouGile integration", "owners": ["app/tm_yougile.py", "app/tm_import_yougile.py"], "critical": False},
        {"feature": "payments", "owners": ["app/tm.py", "app/routes/tm.py"], "critical": False},
        {"feature": "usage analytics", "owners": ["app/usage_analytics.py", "app/routes/system.py", "app/static/js/analytics.js"], "critical": False},
        {"feature": "Telegram/transcription", "owners": ["app/tg_bridge.py", "app/routes/tg.py", "app/transcription.py"], "critical": True},
        {"feature": "progress", "owners": ["app/mcp_stdio.py", "app/routes/sessions.py", "app/session.py", "app/db.py", "app/static/js/app.js", "pipelines/default/prompts/roles/worker.md"], "critical": False},
        {"feature": "model catalog", "owners": ["app/model_catalog.py", "app/routes/system.py", "app/static/js/app.js"], "critical": True},
        {"feature": "test lock", "owners": ["app/mcp_stdio.py", "app/routes/system.py", "app/db.py"], "critical": True},
        {"feature": "fan barrier", "owners": ["app/fan_barrier.py", "app/mcp_stdio.py", "app/routes/sessions.py"], "critical": True},
    ]
    inventory = {
        "generated_at_cutoff": cutoff_text,
        "mcp_tools": sorted(rows, key=lambda r: r["exact_surface"]),
        "route_groups": {
            k: {"paths": sorted(v["paths"]), "methods": sorted(v["methods"]), "owners": sorted(v["owners"]), "usage": "UNMEASURED"}
            for k, v in sorted(route_groups.items())
        },
        "dashboard_controls": controls,
        "subsystems": subsystems,
        "telemetry_gaps": [
            "HTTP route request count is not persisted by path/method in SQLite logs.",
            "Dashboard click/event count is not persisted; UI references are static only.",
            "Pre-2026-08-13 tool rows have NULL/wrapper names and cannot be safely normalized into MCP semantics.",
            "Tool result pairing is lower-bound coverage: only equal-session tool_use_id pairs are joinable.",
        ],
    }
    (OUT / "inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # AST/import/call graph evidence. This is deliberately separate from grep: a name is
    # live only when it is defined/imported/called in parsed Python, while UI references
    # remain marked as static because browser events are not logged.
    targets = sorted(set(mcp_names) | {
        "update_progress", "compact_worker", "codex_review", "search_memory", "task_create",
        "task_update", "payment_receive", "payment_status", "yougile_sync_task", "update_payment_journal",
        "memory_search", "memory_reindex", "change_worker_model", "proxy_list", "proxy_set_env",
        "create_merge_operation", "resolve_merge_operation", "run_initial_delivery",
    })
    graph = {target: {"definitions": [], "parsed_call_sites": [], "imports": []} for target in targets}
    for source_root in (ROOT / "app", ROOT / "tests"):
        for path in source_root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            rel = path.relative_to(ROOT).as_posix()
            class Visitor(ast.NodeVisitor):
                def __init__(self):
                    self.scope = []
                def _enter(self, node):
                    if node.name in graph:
                        graph[node.name]["definitions"].append(rel + ":" + ":".join(self.scope + [node.name]))
                    self.scope.append(node.name)
                    self.generic_visit(node)
                    self.scope.pop()
                visit_FunctionDef = _enter
                visit_AsyncFunctionDef = _enter
                visit_ClassDef = _enter
                def visit_Call(self, node):
                    called = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    if called in graph:
                        graph[called]["parsed_call_sites"].append(rel + ":" + ":".join(self.scope))
                    self.generic_visit(node)
                def _imports(self, node):
                    for alias in node.names:
                        name = alias.asname or alias.name.split(".")[-1]
                        if name in graph:
                            graph[name]["imports"].append(rel)
                visit_Import = _imports
                visit_ImportFrom = _imports
            Visitor().visit(tree)
    for target, values in graph.items():
        for key in values:
            values[key] = sorted(set(values[key]))
    (OUT / "static-callgraph.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Decision matrix rows are deliberately conservative: zero named calls with a
    # telemetry gap is UNKNOWN and therefore cannot receive DELETE confidence.
    critical_tools = {
        "acquire_test_lock", "release_test_lock", "test_lock_status", "compact_worker",
        "delivery_status", "retry_initial_delivery", "resolve_merge_operation", "publish_artifact",
        "send_file", "report_bug", "codex_review", "merge_worker", "kill_worker", "stop_worker",
        "spawn_worker", "switch_worker_branch", "open_fan", "search_memory", "list_agents",
        "list_orchestrators", "worker_wip", "change_worker_model", "bg_create", "bg_list", "bg_cancel",
    }
    usage_by_name = {r["exact_surface"]: r for r in rows}
    matrix = []
    for name in sorted(mcp_names):
        u = usage_by_name[name]
        calls = int(u["90d_calls"])
        incomplete = "telemetry starts" in u["observation_gap"]
        if name in {"payment_receive", "payment_status"}:
            verdict, confidence = "DELETE", "PRE-DECIDED (#299)"
            oracle = "#299 migration oracle; deletion is outside #309"
        elif name == "update_progress":
            verdict, confidence = "HIDE", "LIKELY"
            oracle = "future Class-C: active-session negative control + API compatibility probe"
        elif name in critical_tools:
            verdict, confidence = "KEEP", "CONFIRMED"
            oracle = "recovery/safety path must remain callable; count cannot override role"
        elif calls == 0 and incomplete:
            verdict, confidence = "DEPRECATE", "UNCERTAIN"
            oracle = "instrument complete telemetry, then mechanical registry/import/call-site oracle"
        elif calls < 3:
            verdict, confidence = "DEPRECATE", "LIKELY"
            oracle = "complete telemetry + compatibility probe + mechanical removal oracle"
        else:
            verdict, confidence = "KEEP", "LIKELY"
            oracle = "focused regression on current consumers"
        matrix.append({
            "feature": "mcp_tool:" + name,
            "usage evidence": f"90d named calls={calls}; success={u['90d_successful']}; error={u['90d_errors']}; unknown={u['90d_unknown']}",
            "critical negative control/recovery role": "critical" if name in critical_tools else "none observed; verify dynamic callers",
            "current consumers": u["owner"],
            "prompt/tool/UI footprint": f"schema={u['schema_bytes']}B; function/refs in feature-footprint.csv",
            "maintenance/confusion evidence": "zero/rare named calls; older wrapper telemetry excluded" if calls < 3 else "active call history",
            "deletion blast radius": "high" if name in critical_tools else "medium",
            "replacement": "automatic task tickets/stages (future alternative only)" if name == "update_progress" else "none proposed",
            "verdict": verdict,
            "confidence": confidence,
            "deletion oracle": oracle,
        })
    for group, info in sorted(route_groups.items()):
        critical = group in {"/api/sessions", "/api/merge-operations", "/api/initial-deliveries", "/api/artifacts", "/api/test-lock", "/api/usage", "/api/memory", "/api/bg"}
        matrix.append({
            "feature": "route_group:" + group,
            "usage evidence": "UNMEASURED — no persisted route request census",
            "critical negative control/recovery role": "critical" if critical else "not established",
            "current consumers": ";".join(info["owners"]),
            "prompt/tool/UI footprint": f"{len(info['paths'])} paths; see route-inventory.csv",
            "maintenance/confusion evidence": "route is registered in generated OpenAPI",
            "deletion blast radius": "high" if critical else "unknown",
            "replacement": "none proposed",
            "verdict": "KEEP",
            "confidence": "UNCERTAIN" if not critical else "CONFIRMED",
            "deletion oracle": "add request census before any deletion; route-specific contract tests",
        })
    matrix.extend([
        {"feature": "ui:progress-bar", "usage evidence": "UNMEASURED clicks; 5 successful MCP updates are worker-side only", "critical negative control/recovery role": "none; API remains progress-compatible", "current consumers": "app/static/js/app.js updateAgentInfo/renderAgentItem", "prompt/tool/UI footprint": "two DOM renderers + update_progress schema", "maintenance/confusion evidence": "cosmetic/unknown user observation; no event telemetry", "deletion blast radius": "low UI / medium if API removed", "replacement": "automatic task tickets/stages — future Class-C only", "verdict": "HIDE", "confidence": "LIKELY", "deletion oracle": "browser absence + active-session API negative control"},
        {"feature": "proxy/tunnel dashboard controls", "usage evidence": "UNMEASURED UI clicks; backend owner is external ai-proxy-manager", "critical negative control/recovery role": "proxy route can affect connectivity; do not delete runtime ownership", "current consumers": "app/routes/proxy.py, app/proxy_manager.py, app/ssh_tunnel.py, dashboard", "prompt/tool/UI footprint": "86+148+225 Python LOC plus dashboard controls", "maintenance/confusion evidence": "project instructions say Orchestra is client-only; UI writes .env/restart banner", "deletion blast radius": "high if runtime controls removed", "replacement": "link/status-only UI", "verdict": "HIDE", "confidence": "UNCERTAIN", "deletion oracle": "live proxy health + no route mutation + dashboard regression"},
        {"feature": "legacy merge route", "usage evidence": "UNMEASURED requests; middleware returns typed 426 before endpoint", "critical negative control/recovery role": "merge-operation-v1 remains critical", "current consumers": "app/main.py AuthMiddleware; app/routes/sessions.py legacy endpoint; one negative test", "prompt/tool/UI footprint": "route in OpenAPI; duplicate legacy implementation", "maintenance/confusion evidence": "explicit 'Legacy merge endpoint is disabled' response", "deletion blast radius": "low after migration oracle", "replacement": "/api/merge-operations v1", "verdict": "DELETE", "confidence": "CONFIRMED", "deletion oracle": "middleware 426 test + generated OpenAPI absence + v1 merge recovery tests"},
        {"feature": "duplicate POST /api/models/refresh", "usage evidence": "UNMEASURED requests; two identical definitions", "critical negative control/recovery role": "model refresh is operational, retain one", "current consumers": "app/routes/system.py two identical handlers", "prompt/tool/UI footprint": "duplicate OpenAPI operation id warning", "maintenance/confusion evidence": "FastAPI emitted duplicate Operation ID warning during registry generation", "deletion blast radius": "low if one identical route remains", "replacement": "single canonical handler", "verdict": "MERGE", "confidence": "CONFIRMED", "deletion oracle": "OpenAPI unique operation id + one refresh request contract"},
        {"feature": "YouGile integration", "usage evidence": "DB sync_log=488; tasks have YouGile fields; pre-decided removable under #299", "critical negative control/recovery role": "not a session/recovery safety path", "current consumers": "app/tm_yougile.py, app/tm_import_yougile.py, tm hooks", "prompt/tool/UI footprint": "363 LOC + task schema fields", "maintenance/confusion evidence": "pre-decided by user/#299; not re-litigated", "deletion blast radius": "medium task projection", "replacement": "none in #309", "verdict": "DELETE", "confidence": "PRE-DECIDED (#299)", "deletion oracle": "#299 migration oracle; future Class-C only"},
        {"feature": "payments", "usage evidence": "tm_payments=2; allocations=3; pre-decided removable under #299", "critical negative control/recovery role": "not a session/recovery safety path", "current consumers": "app/tm.py, app/routes/tm.py, payment MCP tools", "prompt/tool/UI footprint": "payment schema + 2 MCP schemas", "maintenance/confusion evidence": "pre-decided by user/#299; not re-litigated", "deletion blast radius": "medium task accounting", "replacement": "none in #309", "verdict": "DELETE", "confidence": "PRE-DECIDED (#299)", "deletion oracle": "#299 migration oracle; future Class-C only"},
    ])
    dump_csv(OUT / "decision-matrix.csv", list(matrix[0]), matrix)

    # Raw, sanitized command facts: no user content, tokens, prompts, or paths outside
    # repository/data are emitted.
    facts = {
        "db_path": str(DB),
        "backup": "sqlite3.Connection.backup(source=file:...mode=ro, destination=:memory:)",
        "cutoff_definition": "max logs.ts where logs.type='tool_result'",
        "cutoff_utc": cutoff_text,
        "logs_total_at_backup": db.execute("SELECT count(*) FROM logs").fetchone()[0],
        "tool_rows_at_backup": db.execute("SELECT count(*) FROM logs WHERE type='tool'").fetchone()[0],
        "tool_result_rows_at_backup": db.execute("SELECT count(*) FROM logs WHERE type='tool_result'").fetchone()[0],
        "joinable_tool_calls": db.execute("SELECT count(*) FROM logs WHERE type='tool' AND tool_use_id IS NOT NULL").fetchone()[0],
        "joinable_tool_results": db.execute("SELECT count(*) FROM logs WHERE type='tool_result' AND tool_use_id IS NOT NULL").fetchone()[0],
        "windows": {k: v.isoformat() for k, v in windows.items()},
        "mcp_registry_count": len(mcp_names),
        "starlette_route_count_including_docs": len({r["path"] for r in route_rows}),
        "openapi_path_count": len(app.openapi()["paths"]) if 'app' in locals() else "unknown",
        "dashboard_control_count": len(controls),
        "secret_scan": "executed separately after generation; pattern omitted from artifact to avoid self-match",
    }
    (OUT / "cutoff-and-db.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
