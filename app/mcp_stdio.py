"""External stdio MCP server for Orchestra.

Runs as a separate process, communicates with Orchestra via HTTP API.
Avoids the in-process SDK control_request deadlock (issue #425/#701).

Usage: python -m app.mcp_stdio
"""

import json
import logging
import os
import shlex
import sys

import httpx
from mcp.server.fastmcp import FastMCP

# Logs go to stderr so they don't pollute the JSON-RPC stdout stream
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("orchestra-mcp")

ORCHESTRA_URL = os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8888")
SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")
ROLE = os.environ.get("ORCHESTRA_ROLE", "orchestrator")
WORKER_NAME = os.environ.get("WORKER_NAME", "worker")
PARENT_NAME = os.environ.get("PARENT_NAME", "")
_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
ACCESS_MODE = os.environ.get("ORCHESTRA_ACCESS_MODE", "full").strip().lower()

READ_ONLY_MCP_TOOLS = frozenset({
    "test_lock_status",
    "list_agents",
    "list_orchestrators",
    "get_worker_logs",
    "list_jobs",
    "check_conflict",
    "worker_wip",
    "get_worker_info",
    "task_list",
    "task_get",
    "payment_status",
    "bg_list",
    "search_memory",
})

mcp = FastMCP("orchestra")


def _tool_names_for_access_mode(names: set[str], mode: str) -> set[str]:
    normalized = mode.strip().lower()
    if normalized in {"read-only", "readonly", "read"}:
        return names & READ_ONLY_MCP_TOOLS
    if normalized == "full":
        return set(names)
    raise ValueError(f"Unknown ORCHESTRA_ACCESS_MODE: {mode!r}")


def _apply_access_mode() -> None:
    registered = {tool.name for tool in mcp._tool_manager.list_tools()}
    visible = _tool_names_for_access_mode(registered, ACCESS_MODE)
    for name in registered - visible:
        mcp.remove_tool(name)
    logger.info(
        "Orchestra MCP access=%s tools=%d/%d",
        ACCESS_MODE,
        len(visible),
        len(registered),
    )


def _auth_headers() -> dict:
    if _INTERNAL_TOKEN:
        return {"Authorization": f"Bearer {_INTERNAL_TOKEN}"}
    return {}


async def _api(method: str, path: str, **kwargs) -> dict | list | None:
    # New client per call: avoids shared state across tool invocations in the same MCP session
    t = kwargs.pop("timeout", 30)
    headers = _auth_headers()
    async with httpx.AsyncClient(base_url=ORCHESTRA_URL, timeout=t, headers=headers) as client:
        if method == "GET":
            r = await client.get(path, params=kwargs.get("params"))
        elif method == "POST":
            r = await client.post(path, json=kwargs.get("json"))
        elif method == "PUT":
            r = await client.put(path, json=kwargs.get("json"), params=kwargs.get("params"))
        elif method == "DELETE":
            r = await client.delete(path, params=kwargs.get("params"))
        else:
            return None
        if r.status_code >= 400:
            return {"error": r.text}
        try:
            return r.json()
        except Exception as e:
            return {"error": f"invalid JSON response (status={r.status_code}): {r.text[:200]}"}


@mcp.tool()
async def spawn_worker(name: str, task: str, repo_path: str,
                       model: str = "",
                       system_prompt: str = "",
                       task_id: str = "",
                       description: str = "",
                       base_branch: str = "",
                       role: str = "worker",
                       mcp_servers: str = "",
                       owned_dirs: str = "",
                       tg_topic: bool = False) -> str:
    """Spawn a new worker agent in a git worktree. Model is REQUIRED — choose it by the `<model-routing>` block in your own prompt, which is the single source of truth for routing (model ids are deliberately not repeated here: a duplicated list rots).
    base_branch — от какой локальной ветки ответвить worktree. Пусто ("") = авто по
    стратегии пайплайна: parent → ветка родителя, main → проверяемый mainline репозитория.
    При неоднозначности spawn требует явную ветку.
    mcp_servers — JSON-объект с доп. MCP-серверами для воркера (формат как в .mcp.json: {"name": {"command": ..., "args": [...]}}). Мерджится с дефолтным Orchestra MCP; ключ "orchestra" игнорируется. Переживает рестарт.
    owned_dirs — JSON-массив директорий которыми владеет воркер, напр. ["app/api/", "app/models/"]. Инжектится в промпт воркера ("трогай только это"). Пересечение с owned_dirs другого живого воркера → БЛОК (spawn fails).
    tg_topic — если True, агент получит собственный TG топик для логов и сообщений."""
    if not model:
        return "Error: model is required. Choose it by the <model-routing> block in your prompt."
    scope = SCOPE or repo_path
    body = {
        "name": name, "scope": scope, "cwd": repo_path,
        "model": model, "system_prompt": system_prompt,
        "use_worktree": True, "repo_path": repo_path,
        "base_branch": base_branch,
        "role": role,
        "parent_name": WORKER_NAME,
    }
    if mcp_servers:
        import json
        try:
            parsed = json.loads(mcp_servers)
            if isinstance(parsed, dict):
                body["mcp_servers"] = parsed
            else:
                return "Error: mcp_servers must be a JSON object, e.g. {\"playwright\": {\"command\": \"npx\", \"args\": [...]}}"
        except json.JSONDecodeError as e:
            return f"Error: mcp_servers is not valid JSON: {e}"
    if owned_dirs:
        import json
        try:
            parsed = json.loads(owned_dirs)
            if isinstance(parsed, list):
                body["owned_dirs"] = parsed
            else:
                return "Error: owned_dirs must be a JSON array, e.g. [\"app/api/\", \"app/models/\"]"
        except json.JSONDecodeError as e:
            return f"Error: owned_dirs is not valid JSON: {e}"
    if task_id:
        body["task_id"] = task_id
    if description:
        body["description"] = description
    if tg_topic:
        body["tg_topic"] = True
    result = await _api("POST", "/api/sessions", json=body)
    if isinstance(result, dict) and result.get("error"):
        return f"Spawn failed: {result['error']}"
    required = ("worktree_path", "branch", "repo_path", "git_common_dir")
    missing = [
        field for field in required
        if (
            not isinstance(result, dict)
            or not isinstance(result.get(field), str)
            or not result[field].strip()
        )
    ]
    if missing:
        return (
            "Spawn failed: malformed API response after session creation "
            f"(missing: {', '.join(missing)}); worker may have been created — "
            "inspect list_agents before retrying."
        )
    mapping = (
        f"Worktree: {result['worktree_path']}"
        f"\nRepository: {result['repo_path']}"
        f"\nGit common dir: {result['git_common_dir']}"
        f"\nBranch: {result['branch']}"
    )
    send_result = await _api("POST", f"/api/sessions/{name}/send", json={
        "message": task, "scope": scope, "sender": WORKER_NAME or ROLE,
    })
    if (
        not isinstance(send_result, dict)
        or send_result.get("ok") is not True
        or send_result.get("error")
    ):
        detail = (
            send_result.get("error", "malformed API response")
            if isinstance(send_result, dict)
            else "malformed API response"
        )
        return (
            f"Worker '{name}' was created, but initial task delivery failed: {detail}.\n"
            f"{mapping}\nUse send_message to deliver the task before retrying spawn."
        )
    out = f"Worker '{name}' spawned. Model: {model}. Task sent."
    out += f"\n{mapping}"
    if isinstance(result, dict) and result.get("spawn_warning"):
        out += f"\n⚠️ {result['spawn_warning']}"
    return out


@mcp.tool()
async def acquire_test_lock(reason: str = "") -> str:
    """Захватить ГЛОБАЛЬНЫЙ эксклюзивный лок на ПОЛНЫЙ прогон тестов (фулл-сьют) для проекта.
    Бери его ТОЛЬКО перед полным прогоном и ТОЛЬКО с согласия PM. Узкие тесты этапа лока НЕ требуют.
    Занято другим агентом → вернётся отказ с именем держателя — НЕ запускай фулл-сьют, жди и попробуй позже.
    Всегда вызывай release_test_lock() после прогона."""
    result = await _api("POST", "/api/test-lock/acquire", json={
        "scope": SCOPE, "holder": WORKER_NAME, "reason": reason,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Lock error: {result['error']}"
    if result.get("acquired"):
        return f"Test lock ACQUIRED for '{WORKER_NAME}' (reason: {reason or 'n/a'}). Release it when done."
    return (f"Test lock BUSY — held by '{result.get('holder')}'. "
            f"Do NOT run the full suite. Wait and retry, or coordinate via PM.")


@mcp.tool()
async def release_test_lock() -> str:
    """Освободить глобальный тест-лок (если ты его держишь). Вызывай сразу после полного прогона."""
    result = await _api("POST", "/api/test-lock/release", json={
        "scope": SCOPE, "holder": WORKER_NAME,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Lock error: {result['error']}"
    if result.get("released"):
        return "Test lock released."
    return "Test lock was not held by you (nothing to release)."


@mcp.tool()
async def test_lock_status() -> str:
    """Кто сейчас держит глобальный тест-лок проекта (или свободен)."""
    result = await _api("GET", "/api/test-lock", params={"scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Lock error: {result['error']}"
    if not result.get("held"):
        return "Test lock is FREE."
    return (f"Test lock HELD by '{result.get('holder')}' "
            f"(reason: {result.get('reason') or 'n/a'}, since {result.get('acquired_at')}).")


@mcp.tool()
async def send_message(to: str, message: str) -> str:
    """Send a message to any agent by name. Triggers a new turn."""
    result = await _api("POST", f"/api/sessions/{to}/send", json={
        "message": message, "sender": WORKER_NAME or ROLE, "scope": SCOPE,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Send failed: {result['error']}"
    parent = result.get("parent_name", "") if isinstance(result, dict) else ""
    if parent and parent != WORKER_NAME:
        return f"Message sent to '{to}'\n⚠️ This worker belongs to '{parent}'. Consider messaging '{parent}' instead."
    return f"Message sent to '{to}'"


_ORCH_ROLES = frozenset({"orchestrator", "sub-orchestrator"})


def _cache_pill(s: dict) -> str:
    """Prompt-cache warmth as a short exact/approximate text pill."""
    from datetime import datetime, timezone
    from app.models import cache_policy_for_runtime, runtime_for_record

    policy = cache_policy_for_runtime(runtime_for_record(s))
    raw_ttl = s.get("cache_ttl_seconds")
    raw_ttl = policy["cache_ttl_seconds"] if raw_ttl is None else raw_ttl
    try:
        ttl = int(raw_ttl)
    except (TypeError, ValueError):
        return ""
    if ttl <= 0:
        return ""
    approximate = bool(s.get("cache_ttl_approximate", policy["cache_ttl_approximate"]))

    if s.get("status") in ("running", "starting"):
        return f"🔥 hot ≈{ttl // 60}m" if approximate else "🔥 hot"
    ts = s.get("last_turn_ts")
    if not ts:
        return ""
    try:
        last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return ""
    now = datetime.now(timezone.utc)
    elapsed_min = max(0, int((now.timestamp() - last.timestamp()) // 60))
    rem_min = (ttl // 60) - elapsed_min
    if rem_min <= 0:
        if approximate:
            past_reference = max(0, elapsed_min - ttl // 60)
            if past_reference < 60:
                past_label = f"{past_reference}m"
            elif past_reference < 1440:
                hours, minutes = divmod(past_reference, 60)
                past_label = f"{hours}h{f'{minutes}m' if minutes else ''}"
            else:
                days, hours = divmod(past_reference // 60, 24)
                past_label = f"{days}d{f'{hours}h' if hours else ''}"
            return f"🧊? unknown (+{past_label} past ≈{ttl // 60}m)"
        return "🧊 cold"
    marker = "≈" if approximate else ""
    ttl_min = ttl / 60
    if rem_min > ttl_min * 0.5:
        return f"🔥 hot {marker}{rem_min}m"
    if rem_min >= ttl_min * 0.2:
        return f"🟡 warm {marker}{rem_min}m"
    return f"🔴 cooling {marker}{rem_min}m"


@mcp.tool()
async def list_agents() -> str:
    """List all agents in your project (orchestrators and workers)."""
    sessions = await _api("GET", "/api/sessions", params={"scope": SCOPE} if SCOPE else None)
    if not isinstance(sessions, list):
        return f"Error: {sessions}"
    if not sessions:
        return "No agents"
    icons_data = await _api("GET", "/api/role-icons")
    _icons = icons_data if isinstance(icons_data, dict) else {}

    def _fmt(s, show_owner=False):
        r = s.get("role", "worker")
        role = _icons.get(r, "⚙️")
        st = "🟢" if s.get("status") in ("running", "idle") else "⚪"
        ctx = s.get('context_pct', 0)
        ctx_str = f" | ctx:{ctx}%" if ctx else ""
        cache = _cache_pill(s)
        cache_str = f" | {cache}" if cache else ""
        task = s.get('task_id', '')
        task_str = f" | {task}" if task else ""
        desc = s.get('description', '')
        desc_str = f' | "{desc}"' if desc else ""
        owner = s.get('parent_name', '')
        owner_str = f" | owner: {owner}" if show_owner and owner else ""
        return f"{st} {role} **{s['name']}** | {s.get('status','?')} | {s.get('model','?')}{ctx_str}{cache_str}{task_str}{desc_str}{owner_str}"

    is_worker = ROLE not in _ORCH_ROLES
    orchestrators, my_workers, other_workers = [], [], []
    for s in sessions:
        if s.get("role", "worker") in _ORCH_ROLES:
            if is_worker and PARENT_NAME and s["name"] != PARENT_NAME:
                continue
            orchestrators.append(s)
        else:
            pn = s.get("parent_name", "")
            if pn == WORKER_NAME or not pn:
                my_workers.append(s)
            else:
                other_workers.append(s)

    lines = []
    if orchestrators:
        lines.append("## Orchestrators")
        lines.extend(_fmt(s) for s in orchestrators)
    if my_workers:
        lines.append("## Your workers")
        lines.extend(_fmt(s) for s in my_workers)
    if other_workers:
        lines.append("## Other orchestrators' workers")
        lines.append("⚠️ These workers belong to other orchestrators. Avoid sending them tasks directly.")
        lines.extend(_fmt(s, show_owner=True) for s in other_workers)
    return "\n".join(lines)


@mcp.tool()
async def list_orchestrators() -> str:
    """List ALL orchestrators across all projects. Use to find agents you can talk to from other projects."""
    orchs = await _api("GET", "/api/orchestrators")
    if not isinstance(orchs, list):
        return f"Error: {orchs}"
    if not orchs:
        return "No orchestrators"
    lines = []
    for o in orchs:
        scope_short = o.get("scope", "").rstrip("/").split("/")[-1]
        ctx = o.get('context_pct', 0)
        ctx_str = f" | ctx:{ctx}%" if ctx else ""
        desc = o.get('description', '')
        desc_str = f' | "{desc}"' if desc else ""
        lines.append(f"🎯 **{o['name']}** | {o.get('status','?')} | {scope_short} | ${o.get('cost_usd',0):.4f}{ctx_str}{desc_str}")
    return "\n".join(lines)


@mcp.tool()
async def get_worker_logs(name: str, limit: int = 20) -> str:
    """Get recent logs from a worker."""
    logs = await _api("GET", f"/api/sessions/{name}/logs", params={"scope": SCOPE, "after_id": 0})
    if isinstance(logs, dict) and logs.get("error"):
        return f"Error: {logs['error']}"
    if not logs:
        return f"No logs for '{name}'"
    lines = []
    for l in logs[-limit:]:
        t, c = l['type'], l['content'][:200]
        if t == 'text':
            lines.append(f"💬 {c}")
        elif t == 'user_message':
            lines.append(f"👤 {c}")
        elif t == 'tool':
            lines.append(f"🔧 {c}")
        elif t == 'error':
            lines.append(f"❌ {c}")
    return "\n".join(lines) if lines else f"No meaningful logs for '{name}'"


@mcp.tool()
async def compact_worker(name: str) -> str:
    """Compact a worker's context — summarize, reset session, continue fresh. Use when worker context >80%. Returns summary. Takes ~30-60s."""
    result = await _api("POST", f"/api/sessions/{name}/compact", json={"scope": SCOPE}, timeout=120)
    if isinstance(result, dict) and result.get("error"):
        return f"Compact failed: {result['error']}"
    if isinstance(result, dict) and result.get("ok"):
        return f"Compact done: {result.get('before_pct', '?')}% → {result.get('after_pct', '?')}%. Summary ({result.get('summary_chars', 0)} chars): {result.get('summary', '')}"
    return f"Compact result: {result}"


@mcp.tool()
async def kill_worker(name: str, force: bool = False) -> str:
    """Stop and archive a worker. Blocked if worker has uncommitted changes or unmerged commits — pass force=True to override."""
    result = await _api("DELETE", f"/api/sessions/{name}", params={"scope": SCOPE, "force": str(force).lower()})
    if isinstance(result, dict) and result.get("error"):
        return f"Kill failed: {result['error']}"
    return f"Worker '{name}' stopped and archived."


@mcp.tool()
async def stop_worker(name: str) -> str:
    """Interrupt a worker and set it to idle. Worktree and session are preserved — can be resumed later with send_message."""
    result = await _api("POST", f"/api/sessions/{name}/stop", json={"scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Stop failed: {result['error']}"
    return f"Worker '{name}' interrupted and set to idle."


@mcp.tool()
async def rename_worker(old_name: str, new_name: str) -> str:
    """Rename a worker agent."""
    result = await _api("POST", f"/api/sessions/{old_name}/rename", json={"new_name": new_name, "scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Rename failed: {result['error']}"
    return f"Worker '{old_name}' renamed to '{new_name}'."


@mcp.tool()
async def list_jobs() -> str:
    """List recent spawn/kill jobs."""
    jobs = await _api("GET", "/api/jobs", params={"scope": SCOPE} if SCOPE else None)
    if not isinstance(jobs, list):
        return f"Error: {jobs}"
    if not jobs:
        return "No jobs"
    return "\n".join(f"- {j['id']}: {j['type']} {j['name']} = {j['status']}" for j in jobs)


@mcp.tool()
async def send_file(path: str, caption: str = "", as_document: bool = False) -> str:
    """Send a file to the user via Telegram. Path must be absolute. Images are sent as inline photos by default; set as_document=True to force file attachment."""
    try:
        # Delivery goes through the reliable TG queue, which waits out flood control
        # (429 retry_after is routinely 20-30s) — 30s here timed out mid-retry.
        result = await _api("POST", "/api/tg/send_file", json={
            "path": path, "caption": caption, "scope": SCOPE, "sender": WORKER_NAME or ROLE,
            "as_document": as_document,
        }, timeout=180)
    except Exception as e:
        # httpx timeouts stringify to "" — without the class name the report says nothing.
        return f"Send failed: network error: {type(e).__name__}: {e}"
    if not isinstance(result, dict):
        return f"Send failed: unexpected response type={type(result).__name__} value={result!r}"
    if result.get("error"):
        return f"Send failed: {result['error']}"
    if result.get("ok"):
        msg_id = result.get("message_id")
        chat_id = result.get("chat_id")
        return f"File sent to TG: {path} (msg_id={msg_id} chat_id={chat_id})"
    return f"Send failed: unexpected response (no ok/error): {result!r}"


@mcp.tool()
async def update_progress(percent: int, status: str) -> str:
    """Update task progress. percent: 0-100, status: short description of current step."""
    result = await _api("POST", f"/api/sessions/{WORKER_NAME}/progress", json={
        "percent": percent, "status": status, "scope": SCOPE,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Progress update failed: {result['error']}"
    return f"Progress: {percent}% — {status}"


@mcp.tool()
async def change_worker_model(name: str, model: str) -> str:
    """Change a worker's model (e.g. sonnet→opus) without losing context. Worker must be idle."""
    result = await _api("POST", f"/api/sessions/{name}/change-model", json={"scope": SCOPE, "model": model})
    if isinstance(result, dict) and result.get("error"):
        return f"Model change failed: {result['error']}"
    if isinstance(result, dict) and result.get("changed"):
        return f"Model changed: {result.get('old_model')} → {result.get('model')}"
    return f"Model already {result.get('model', model)}"


@mcp.tool()
async def merge_worker(name: str, target: str = "", next_task_id: str = "") -> str:
    """Squash a worker branch into its persisted base branch.
    Pass target only to override that base, and next_task_id to auto-switch afterwards."""
    body = {"scope": SCOPE, "squash": True}
    if target:
        body["target"] = target
    if next_task_id:
        body["next_task_id"] = next_task_id
    result = await _api("POST", f"/api/sessions/{name}/merge", json=body)
    if isinstance(result, dict) and result.get("error"):
        return f"Merge failed: {result['error']}"
    if isinstance(result, dict) and result.get("ok"):
        n = result.get("commits_merged", 0)
        branch = result.get("branch", "?")
        parts = [f"Merged {n} commit{'s' if n != 1 else ''} from branch {branch}"]
        for par, info in result.get("linked_tasks", {}).items():
            if isinstance(info, dict) and info.get("ok"):
                parts.append(f"  → {par}: {info.get('added', 0)} commits linked")
            elif isinstance(info, dict) and info.get("id"):
                parts.append(f"  → {par}: commits linked")
            elif isinstance(info, dict):
                error = info.get("error") or "link failed without error detail"
                parts.append(f"  ⚠️ {par}: FAILED — {error}")
            elif info is None:
                parts.append(f"  ⚠️ {par}: FAILED — task not found")
            else:
                parts.append(f"  ⚠️ {par}: FAILED — invalid link result")
        switch = result.get("switch")
        if switch:
            if switch.get("ok"):
                parts.append(f"  → switched to branch {switch.get('branch', '?')}")
            else:
                parts.append(f"  ⚠️ switch failed: {switch.get('error', 'unknown')}")
        return "\n".join(parts)
    if isinstance(result, dict) and not result.get("ok"):
        conflicts = result.get("conflicts", [])
        if conflicts:
            return f"Conflicts in: {', '.join(conflicts)}"
        return f"Merge failed: {result.get('error', 'unknown error')}"
    return f"Merge result: {result}"


@mcp.tool()
async def switch_worker_branch(name: str, task_id: str, from_ref: str = "") -> str:
    """After merge, switch worker to a new branch for a new task.
    from_ref — optional local base override; empty uses the worker's persisted base.
    Worker must be idle with clean working tree."""
    result = await _api("POST", f"/api/sessions/{name}/switch-branch",
                        json={"scope": SCOPE, "task_id": task_id, "from_ref": from_ref})
    if isinstance(result, dict) and result.get("error"):
        return f"Switch failed: {result['error']}"
    if isinstance(result, dict) and result.get("ok"):
        return f"Switched to branch {result.get('branch', '?')}"
    if isinstance(result, dict) and result.get("conflicts"):
        return f"Merge conflict with base branch on: {', '.join(result['conflicts'])}"
    return f"Switch result: {result}"


@mcp.tool()
async def check_conflict(worker_a: str, worker_b: str) -> str:
    """Dry-run: would merging these two workers' branches conflict? Both must have committed work.
    Use to decide merge order or whether two parallel workers collided. No changes made."""
    result = await _api("POST", "/api/sessions/check-conflict",
                        json={"scope": SCOPE, "worker_a": worker_a, "worker_b": worker_b})
    if isinstance(result, dict) and result.get("error"):
        return f"Check failed: {result['error']}"
    if isinstance(result, dict) and result.get("ok"):
        conflicts = result.get("conflicts", [])
        if conflicts:
            return f"⚠️ {worker_a} and {worker_b} would CONFLICT in: {', '.join(conflicts)}"
        return f"✅ No conflict between {worker_a} and {worker_b} — safe to merge both"
    return f"Cannot simulate: {result.get('error', 'unknown') if isinstance(result, dict) else result}"


@mcp.tool()
async def worker_wip(name: str, base_ref: str = "") -> str:
    """Show a worker's WIP: uncommitted files + unmerged commits. Call before resuming to see what's left.
    Empty base_ref uses the worker's persisted base branch."""
    result = await _api("GET", f"/api/sessions/{name}/wip",
                        params={"scope": SCOPE, "base_ref": base_ref})
    if isinstance(result, dict) and result.get("error"):
        return f"WIP check failed: {result['error']}"
    if not isinstance(result, dict):
        return f"WIP result: {result}"
    uncommitted = result.get("uncommitted", [])
    unmerged = result.get("unmerged_commits", [])
    changed_files = result.get("changed_files", [])
    ctx = result.get("context_pct", 0)
    status = result.get("status", "?")
    effective_base = result.get("base_ref") or base_ref or "persisted base"
    ctx_str = f" | ctx:{ctx}% | {status}" if ctx else f" | {status}"
    if not uncommitted and not unmerged:
        return f"'{name}'{ctx_str}: clean — no uncommitted changes, no unmerged commits (vs {effective_base})"
    parts = [f"WIP for '{name}'{ctx_str} (vs {effective_base}):"]
    if uncommitted:
        parts.append(f"  Uncommitted ({len(uncommitted)}): " + ", ".join(uncommitted[:20]))
    if unmerged:
        parts.append(f"  Unmerged commits ({len(unmerged)}):")
        parts.extend(f"    - {s}" for s in unmerged[:20])
    if changed_files:
        insertions = result.get("insertions", 0)
        deletions = result.get("deletions", 0)
        parts.append(f"  Changed files ({len(changed_files)}): +{insertions} -{deletions}")
        for file in changed_files[:10]:
            path = file.get("path", "?")
            if file.get("binary"):
                suffix = " (binary)"
            elif file.get("insertions") is None or file.get("deletions") is None:
                suffix = ""
            else:
                suffix = f" (+{file['insertions']} -{file['deletions']})"
            parts.append(f"    {path}{suffix}")
        remaining = len(changed_files) - 10
        if remaining > 0:
            noun = (
                "файл" if remaining % 10 == 1 and remaining % 100 != 11
                else "файла" if 2 <= remaining % 10 <= 4 and not 12 <= remaining % 100 <= 14
                else "файлов"
            )
            parts.append(f"    ...и ещё {remaining} {noun}")
    return "\n".join(parts)


@mcp.tool()
async def report_bug(title: str, description: str) -> str:
    """Report a bug or issue with the Orchestra platform. Saves to bugs.md for the developer."""
    r = await _api("POST", "/api/report_bug", json={"title": title, "description": description, "reporter": WORKER_NAME, "scope": SCOPE})
    return r.get("result", f"Bug reported: {title}")


@mcp.tool()
async def update_worker_description(name: str, description: str) -> str:
    """Update a worker's description. Use to set/change the role description shown in list_agents."""
    result = await _api("POST", f"/api/sessions/{name}/description", json={"description": description, "scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return f"Description updated for '{name}'"


@mcp.tool()
async def update_worker_prompt(name: str, system_prompt: str) -> str:
    """Update a worker's custom system prompt."""
    result = await _api("POST", f"/api/sessions/{name}/prompt", json={"system_prompt": system_prompt, "scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return f"System prompt updated for '{name}'"


@mcp.tool()
async def get_worker_info(name: str) -> str:
    """Get full worker info including system_prompt, description, model, status, context, task_id."""
    result = await _api("GET", f"/api/sessions/{name}", params={"scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    if isinstance(result, dict):
        result["cache_status"] = _cache_pill(result)  # 🔥 hot Nm / 🟡 warm / 🧊 cold
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def task_create(title: str, project: str, price: int = 0,
                      description: str = "", assignee: str = "",
                      status: str = "new", priority: int = 2) -> str:
    """Create a new task. Returns task number and details.
    price in exact currency units (e.g. 20000 = 20 000). 0 is valid (no price).
    priority: 0=critical, 1=high, 2=medium (default), 3=low."""
    result = await _api("POST", "/api/tm/tasks", json={
        "title": title, "project": project, "price": price,
        "description": description, "assignee": assignee, "status": status,
        "scope": SCOPE, "priority": priority,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def task_update(par: str, title: str = "", description: str = "",
                      price: int = -1, status: str = "",
                      assignee: str = "", priority: int = -1) -> str:
    """Update an existing task. Only provided fields are changed.
    par: '42' or 'PAR-42' (legacy). price in exact currency units (-1 = don't change, 0 = set to zero).
    Empty string = don't change for text fields. priority: 0-3 or -1=don't change."""
    body: dict = {}
    if title:
        body["title"] = title
    if description:
        body["description"] = description
    if price >= 0:
        body["price"] = price
    if status:
        body["status"] = status
    if assignee:
        body["assignee"] = assignee
    if 0 <= priority <= 3:
        body["priority"] = priority
    if not body:
        return "Nothing to update"
    result = await _api("PUT", f"/api/tm/tasks/{par}", json=body, params={"scope": SCOPE} if SCOPE else None)
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def task_list(project: str = "", status: str = "",
                    assignee: str = "") -> str:
    """List tasks with optional filters. Returns summary per task."""
    params = {}
    if project:
        params["project"] = project
    elif SCOPE:
        params["scope"] = SCOPE
    if status:
        params["status"] = status
    if assignee:
        params["assignee"] = assignee
    result = await _api("GET", "/api/tm/tasks", params=params)
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def task_get(par: str) -> str:
    """Get full task details including payment history and linked commits."""
    result = await _api("GET", f"/api/tm/tasks/{par}", params={"scope": SCOPE} if SCOPE else None)
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def payment_receive(amount: int, client: str = "",
                          date: str = "", note: str = "") -> str:
    """Record incoming payment. Auto-distributes to done tasks (smallest debt first).
    amount in exact currency units (e.g. 30000 = 30 000)."""
    result = await _api("POST", "/api/tm/payments", json={
        "amount": amount, "client": client, "date": date, "note": note,
        "scope": SCOPE,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def payment_status(client: str = "") -> str:
    """Get payment overview: balance, total debt, recent payments."""
    result = await _api("GET", "/api/tm/payments/status",
                        params={"client": client, "scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def bg_create(type: str, message: str = "", target: str = "",
                    delay_seconds: int = 0, path: str = "", pattern: str = "",
                    command: str = "", host: str = "", cron_expr: str = "",
                    interval_seconds: int = 60,
                    timeout_seconds: int = 3600) -> str:
    """Create a background job that wakes an agent when triggered. Survives hibernate.
    Types:
    - timer: fires after delay_seconds
    - file: watches file at path for pattern (regex)
    - command: runs command every interval_seconds, matches pattern in output
    - ssh: streams ssh command output, matches pattern
    - run: executes command, wakes agent when done with exit code + output
    - cron: periodically wakes the target agent on a cron schedule (cron_expr, 5-field, UTC).
            Recurring — stays active across firings. timeout_seconds=0 = no expiry (forever
            until cancelled). Missed fires during downtime are skipped (no backfill).
    - cron_command: runs command on cron_expr and wakes only when completed stdout/stderr
            matches pattern. Recurring, UTC, no backfill.
    target: agent name (default: you). timeout_seconds: max lifetime (default 1h,
            max 24h); 0 = no expiry for file/command/ssh/cron/cron_command."""
    config = {}
    if type == "timer":
        config = {"delay_seconds": delay_seconds}
    elif type == "file":
        config = {"path": path, "pattern": pattern}
    elif type == "command":
        config = {"command": command, "pattern": pattern, "interval_seconds": interval_seconds}
    elif type == "ssh":
        config = {"command": command, "host": host, "pattern": pattern}
    elif type == "run":
        config = {"command": command, "host": host} if host else {"command": command}
    elif type == "cron":
        config = {"cron_expr": cron_expr}
    elif type == "cron_command":
        config = {
            "cron_expr": cron_expr,
            "command": command,
            "pattern": pattern,
        }
    target_name = target or WORKER_NAME
    result = await _api("POST", "/api/bg/jobs", json={
        "type": type, "config": config, "message": message,
        "target_name": target_name, "target_scope": SCOPE,
        "timeout_seconds": timeout_seconds, "created_by": WORKER_NAME,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return f"Background job created: {result.get('id', '?')} (type={type}, target={target_name})"


@mcp.tool()
async def bg_list() -> str:
    """List active background jobs in your project."""
    jobs = await _api("GET", "/api/bg/jobs", params={"scope": SCOPE})
    if not isinstance(jobs, list):
        return f"Error: {jobs}"
    if not jobs:
        return "No background jobs"
    icons = {
        "timer": "⏰", "file": "📄", "command": "🖥️", "ssh": "🔗",
        "run": "🚀", "cron": "🔁", "cron_command": "🔎",
    }
    lines = []
    for j in jobs:
        icon = icons.get(j["type"], "❓")
        status = j["status"]
        target = j.get("target_name", "?")
        msg = j.get("message", "")[:60]
        lines.append(f"{icon} **{j['id']}** | {status} | → {target} | {msg}")
    return "\n".join(lines)


@mcp.tool()
async def bg_cancel(job_id: str) -> str:
    """Cancel an active background job."""
    result = await _api("DELETE", f"/api/bg/jobs/{job_id}")
    if isinstance(result, dict) and result.get("error"):
        return f"Cancel failed: {result['error']}"
    return f"Job {job_id} cancelled."


@mcp.tool()
async def search_memory(query: str, limit: int = 5, cross_project: bool = False) -> str:
    """Семантический поиск по ПАМЯТИ проекта — прошлые docs/tasks/*.md, CLAUDE.md, BUGS.md,
    отчёты и решения агентов (send_message DONE-репорты, обсуждения). Юзай когда потерял
    контекст после compact/restart, или ищешь как раньше решали похожую задачу — вместо того
    чтобы grep'ать вслепую. Ищет по СВОЕМУ проекту. cross_project=True — по всем проектам
    (редко нужно). limit — сколько результатов (default 5)."""
    # scope НЕ параметр: берём ORCHESTRA_SCOPE из env воркера → нельзя запросить чужой проект.
    if not SCOPE:
        return "search_memory: no project scope (orchestrator context) — nothing to search."
    body = {"scope": SCOPE, "query": query, "limit": limit, "cross_project": cross_project}
    result = await _api("POST", "/api/memory/search", json=body)
    if isinstance(result, dict) and result.get("error"):
        return f"search_memory failed: {result['error']}"
    hits = result.get("results", []) if isinstance(result, dict) else []
    if not hits:
        return f"No memory matches for: {query!r}"
    lines = []
    for h in hits:
        if h.get("source") == "file":
            head = f"[file: {h.get('path')}]"
        else:
            author = h.get("author")
            tag = f"{h.get('kind')}" + (f" from {author}" if author else "")
            head = f"[log: {tag}]"
        if cross_project:
            head = f"({h.get('project')}) {head}"
        lines.append(f"{head}\n{h.get('content', '').strip()}")
    return "\n\n---\n\n".join(lines)


# Wrapper reloads Orchestra .env on every invocation, so Codex review follows the same
# currently selected proxy as workers, Cursor, and the dashboard service.
_CODEX_BIN = "/home/maxim/.local/bin/codex"
_REVIEW_CONTEXT = (
    "PROJECT CONTEXT (calibrate review severity):\n"
    "- Scale: small team, MVP stage\n"
    "- Philosophy: simple, flat, minimal abstractions\n"
    "- blocking = crash/corrupt/security. suggestion = real improvement. nit = skip\n"
)


def _codex_sessions_path(output_abs: str) -> str:
    """codex_sessions.json lives next to the review output file (per worker/task dir)."""
    return f"{os.path.dirname(output_abs)}/codex_sessions.json"


def _codex_slug(output: str) -> str:
    """Slug = output filename stem. One slug = one session = one output file (matches skill)."""
    return os.path.splitext(os.path.basename(output))[0] or "review"


def _read_codex_uuid(sessions_path: str, slug: str) -> str:
    """Read stored thread UUID for a slug. Empty string = no session yet."""
    try:
        with open(sessions_path) as f:
            data = json.load(f)
        return (data.get("sessions", {}).get(slug, {}) or {}).get("uuid", "") or ""
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""


@mcp.tool()
async def codex_review(
    target: str = "",
    output: str = "CODEX_REVIEW.md",
    context: str = "",
    mode: str = "review",
    resume: bool = False,
) -> str:
    """Run Codex (GPT-5.6 Sol) cross-LLM review in background. Returns immediately.
    After calling, END YOUR TURN NOW; Orchestra wakes you when the job completes.
    target: file path for review, or empty for git diff review.
    output: where to write results (relative to your cwd). Also the session key — reuse the SAME
        output filename to continue a debate.
    context: extra instructions for the review prompt.
    mode: 'review' (git diff, default) or 'exec' (review specific file).
    resume: continue the previous Codex session for this output (debate round). Falls back to a
        fresh session if none stored. On a resumed round put your counter-arguments / changelog
        in context (e.g. 'I fixed X and Y, re-review')."""
    info = await _api("GET", f"/api/sessions/{WORKER_NAME}", params={"scope": SCOPE})
    if isinstance(info, dict) and info.get("error"):
        return f"Error resolving worker cwd: {info['error']}"
    cwd = info.get("worktree_path") or info.get("cwd") or info.get("scope", SCOPE)
    output_abs = f"{cwd}/{output}" if not output.startswith("/") else output

    sessions_path = _codex_sessions_path(output_abs)
    slug = _codex_slug(output)
    jsonl_file = f"/tmp/codex_review_{WORKER_NAME}_{slug}.jsonl"
    prompt_file = f"/tmp/codex_review_{WORKER_NAME}_{slug}.txt"
    rc_file = f"/tmp/codex_review_{WORKER_NAME}_{slug}.rc"
    # resume writes its last message here; the persist snippet appends it as a ## Round to
    # output_abs so prior rounds are never overwritten.
    round_tmp = f"{output_abs}.round"

    prev_uuid = _read_codex_uuid(sessions_path, slug) if resume else ""
    is_resume = bool(prev_uuid)
    if resume and not prev_uuid:
        logger.info(f"codex_review: resume requested but no stored session for slug={slug} → fresh")

    # Never let `codex -o` write the durable artifact directly: -o stores the final
    # agent_message and can overwrite a richer file created during the turn. Capture every
    # run in a temporary round, validate it, then atomically persist it.
    codex_out = round_tmp
    q = shlex.quote

    if mode == "review":
        # Fresh review → codex_out: output_abs on a first run, round_tmp on a resume-fallback
        # (so the stale-session recovery is APPENDED as a round, never overwrites prior rounds).
        fresh_review = (
            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} exec review"
            f" --uncommitted --skip-git-repo-check --full-auto --json"
            f" -o {q(codex_out)}"
        )
        if is_resume:
            # resume inherits sandbox from original session — do NOT pass -s. Re-review the diff.
            resume_prompt = (
                "Re-review the current uncommitted diff (run git diff yourself). "
                "For each prior finding: FIXED / STILL BROKEN / NEW BUG. "
                "Output a concise re-review (Re-review status, new findings, verdict)."
            )
            if context:
                resume_prompt += f"\nAuthor notes: {context}"
            # Stale/invalid UUID → resume fails → fall back to a fresh review (recovery).
            codex = (
                f"printf '%s' {q(resume_prompt)} > {q(prompt_file)}; "
                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} exec resume {q(prev_uuid)}"
                f" --skip-git-repo-check --full-auto --json"
                f" -o {q(codex_out)} - < {q(prompt_file)}"
                f" || {{ echo '[resume failed — stale session, starting fresh review]'; {fresh_review}; }}"
            )
        else:
            codex = fresh_review
    elif mode == "exec":
        if not target and not is_resume:
            return "Error: target file required for mode='exec'"
        prompt_parts_exec = [_REVIEW_CONTEXT]
        if context:
            prompt_parts_exec.append(f"Additional context: {context}\n")
        # Keep the target in the prompt even on resume — the stale-UUID fresh-exec fallback
        # reuses this same prompt file and would otherwise review nothing concrete.
        if target:
            prompt_parts_exec.append(f"Review the file: {target}")
        if is_resume:
            prompt_parts_exec.append("Re-review after the author's changes above. "
                                     "Output a concise re-review (status of prior findings, new findings, verdict).")
        else:
            prompt_parts_exec.append("Return the complete review in your final response. Do not edit files.")
        prompt_parts_exec.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
        exec_prompt = "\n".join(prompt_parts_exec)

        # resume inherits sandbox — do NOT pass -s; fresh exec writes with workspace-write.
        sandbox = "" if is_resume else " -s workspace-write"
        subcmd = f"exec resume {prev_uuid}" if is_resume else "exec"
        codex = (
            f"printf '%s' {q(exec_prompt)} > {q(prompt_file)}; "
            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} {subcmd}"
            f"{sandbox} --skip-git-repo-check --full-auto --json"
            f" -o {q(codex_out)} - < {q(prompt_file)}"
        )
        if is_resume and target:
            # Stale/invalid UUID → resume fails → fresh exec. Only when a target exists —
            # without one the prompt has nothing concrete to review, so let resume fail loud.
            # Writes to codex_out (=round_tmp) so the recovery is appended, not overwriting history.
            fresh_exec = (
                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {q(_CODEX_BIN)} exec"
                f" -s workspace-write --skip-git-repo-check --full-auto --json"
                f" -o {q(codex_out)} - < {q(prompt_file)}"
            )
            codex += f" || {{ echo '[resume failed — stale session, starting fresh]'; {fresh_exec}; }}"
    else:
        return f"Error: unknown mode '{mode}'. Use 'review' or 'exec'."

    # Ensure codex_sessions.json / *.round are git-ignored in THIS worktree before writing them,
    # so they never dirty the tree / block merge_worker — regardless of how old the worktree is
    # (create_worktree only excludes on spawn; long-lived workers need this at use-time too).
    exclude_setup = (
        f"cd {q(cwd)} && GD=$(git rev-parse --git-common-dir 2>/dev/null)"
        f" && {{ case \"$GD\" in /*) ;; *) GD={q(cwd)}/$GD;; esac;"
        f" mkdir -p \"$GD/info\";"
        f" for p in 'codex_sessions.json' '*.round'; do"
        f" grep -qxF \"$p\" \"$GD/info/exclude\" 2>/dev/null || echo \"$p\" >> \"$GD/info/exclude\";"
        f" done; }}; "
    )

    finalizer = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "codex_review_artifact.py")
    finalize_args = [
        q(sys.executable), q(finalizer),
        "--output", q(output_abs),
        "--round-file", q(round_tmp),
        "--sessions-file", q(sessions_path),
        "--slug", q(slug),
        "--jsonl-file", q(jsonl_file),
    ]
    if is_resume:
        finalize_args.append("--resume")
    if mode == "exec":
        finalize_args.append("--require-verdict")
    finalize = " ".join(finalize_args)

    # Remove stale temp state before each attempt. A service restart can kill the shell after
    # an old .rc=0 was written but before the artifact was persisted; reusing that file caused
    # false success. Codex's real exit code and the artifact validator must both pass.
    cmd = (
        f"{exclude_setup}"
        f"mkdir -p {q(os.path.dirname(output_abs))}; "
        f"rm -f {q(rc_file)} {q(jsonl_file)} {q(round_tmp)} {q(prompt_file)}; "
        f"{{ {codex} ; echo $? > {q(rc_file)} ; }} | tee {q(jsonl_file)}; "
        f"RC=$(cat {q(rc_file)} 2>/dev/null || echo 1); "
        f"[ \"$RC\" -eq 0 ] || exit \"$RC\"; "
        f"{finalize}"
    )

    action = "resume" if is_resume else mode
    logger.info(f"codex_review: mode={mode} resume={is_resume} slug={slug} cwd={cwd} output={output_abs}")
    result = await _api("POST", "/api/bg/jobs", json={
        "type": "run",
        "config": {
            "command": cmd,
            "success_file": output_abs,
            "success_pattern": r"(?im)^##\s+Verdict\b" if mode == "exec" else "",
        },
        "message": f"Codex {action} done. Results in {output}",
        "target_name": WORKER_NAME,
        "target_scope": SCOPE,
        "timeout_seconds": 600,
        "created_by": WORKER_NAME,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Error creating bg job: {result['error']}"
    job_id = result.get("id", "?")
    resumed_note = f" (resumed session {prev_uuid[:8]})" if is_resume else ""
    return (
        f"Codex {action} started{resumed_note} (bg job {job_id}, 10-min timeout). "
        f"END YOUR TURN NOW — this is required, not optional. Orchestra will wake you "
        f"when the job succeeds, times out, or fails. "
        f"On success: read {output}. To continue this debate, call codex_review again with the "
        f"SAME output and resume=True. Do not start another codex_review until this one reports back."
    )


if __name__ == "__main__":
    _apply_access_mode()
    logger.info(f"Orchestra MCP stdio (url={ORCHESTRA_URL}, scope={SCOPE})")
    mcp.run(transport="stdio")
