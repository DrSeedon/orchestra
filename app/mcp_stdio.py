"""External stdio MCP server for Orchestra.

Runs as a separate process, communicates with Orchestra via HTTP API.
Avoids the in-process SDK control_request deadlock (issue #425/#701).

Usage: python -m app.mcp_stdio
"""

import json
import logging
import os
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

mcp = FastMCP("orchestra")


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
    """Spawn a new worker agent in a git worktree. Model is REQUIRED — choose explicitly: claude-opus-4-8[1m] for research/planning/long-lived, claude-sonnet-5[1m] for implementation from spec, gpt-5.5 for Codex.
    base_branch — от какой ветки ответвить worktree воркера. Пусто ("") = авто по стратегии пайплайна (parent → от ветки родителя, иначе main); явно указанная ветка переопределяет стратегию.
    mcp_servers — JSON-объект с доп. MCP-серверами для воркера (формат как в .mcp.json: {"name": {"command": ..., "args": [...]}}). Мерджится с дефолтным Orchestra MCP; ключ "orchestra" игнорируется. Переживает рестарт.
    owned_dirs — JSON-массив директорий которыми владеет воркер, напр. ["app/api/", "app/models/"]. Инжектится в промпт воркера ("трогай только это"). Пересечение с owned_dirs другого живого воркера → БЛОК (spawn fails).
    tg_topic — если True, агент получит собственный TG топик для логов и сообщений."""
    if not model:
        return "Error: model is required. Choose: claude-opus-4-8[1m] (think), claude-sonnet-5[1m] (type), gpt-5.5 (codex)"
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
    await _api("POST", f"/api/sessions/{name}/send", json={
        "message": task, "scope": scope,
    })
    out = f"Worker '{name}' spawned. Model: {model}. Task sent."
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
        task = s.get('task_id', '')
        task_str = f" | {task}" if task else ""
        desc = s.get('description', '')
        desc_str = f' | "{desc}"' if desc else ""
        owner = s.get('parent_name', '')
        owner_str = f" | owner: {owner}" if show_owner and owner else ""
        return f"{st} {role} **{s['name']}** | {s.get('status','?')} | {s.get('model','?')}{ctx_str}{task_str}{desc_str}{owner_str}"

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
        result = await _api("POST", "/api/tg/send_file", json={
            "path": path, "caption": caption, "scope": SCOPE, "sender": WORKER_NAME or ROLE,
            "as_document": as_document,
        })
    except Exception as e:
        return f"Send failed: network error: {e}"
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
async def merge_worker(name: str, target: str = "main", next_task_id: str = "") -> str:
    """Merge a worker's branch into target branch (default main). Always squash — one clean commit per task. Returns commit count or conflict file list. Pass next_task_id to auto-switch to new branch after merge."""
    body = {"scope": SCOPE, "target": target, "squash": True}
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
            elif isinstance(info, dict):
                parts.append(f"  ⚠️ {par}: FAILED — {info.get('error', 'unknown')}")
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
async def switch_worker_branch(name: str, task_id: str, from_ref: str = "refs/heads/main") -> str:
    """After merge, switch worker to a new branch for a new task.
    from_ref — ветка, от которой ответвляется новая (default refs/heads/main; воркер feature-ветки → refs/heads/feature/<...>).
    Worker must be idle with clean working tree."""
    result = await _api("POST", f"/api/sessions/{name}/switch-branch",
                        json={"scope": SCOPE, "task_id": task_id, "from_ref": from_ref})
    if isinstance(result, dict) and result.get("error"):
        return f"Switch failed: {result['error']}"
    if isinstance(result, dict) and result.get("ok"):
        return f"Switched to branch {result.get('branch', '?')}"
    if isinstance(result, dict) and result.get("conflicts"):
        return f"Merge conflict with main on: {', '.join(result['conflicts'])}"
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
async def worker_wip(name: str, base_ref: str = "refs/heads/main") -> str:
    """Show a worker's WIP: uncommitted files + unmerged commits. Call before resuming to see what's left.
    base_ref default refs/heads/main — pass the worker's actual base branch if it was spawned from a feature branch."""
    result = await _api("GET", f"/api/sessions/{name}/wip",
                        params={"scope": SCOPE, "base_ref": base_ref})
    if isinstance(result, dict) and result.get("error"):
        return f"WIP check failed: {result['error']}"
    if not isinstance(result, dict):
        return f"WIP result: {result}"
    uncommitted = result.get("uncommitted", [])
    unmerged = result.get("unmerged_commits", [])
    ctx = result.get("context_pct", 0)
    status = result.get("status", "?")
    ctx_str = f" | ctx:{ctx}% | {status}" if ctx else f" | {status}"
    if not uncommitted and not unmerged:
        return f"'{name}'{ctx_str}: clean — no uncommitted changes, no unmerged commits (vs {base_ref})"
    parts = [f"WIP for '{name}'{ctx_str} (vs {base_ref}):"]
    if uncommitted:
        parts.append(f"  Uncommitted ({len(uncommitted)}): " + ", ".join(uncommitted[:20]))
    if unmerged:
        parts.append(f"  Unmerged commits ({len(unmerged)}):")
        parts.extend(f"    - {s}" for s in unmerged[:20])
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
    target: agent name (default: you). timeout_seconds: max lifetime (default 1h, max 24h)."""
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
    icons = {"timer": "⏰", "file": "📄", "command": "🖥️", "ssh": "🔗", "run": "🚀", "cron": "🔁"}
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


# Wrapper at ~/.local/bin/codex sets HTTPS_PROXY for Ёжик tunnel
_CODEX_BIN = "/home/maxim/.local/bin/codex"
_REVIEW_CONTEXT = (
    "PROJECT CONTEXT (calibrate review severity):\n"
    "- Scale: small team, MVP stage\n"
    "- Philosophy: simple, flat, minimal abstractions\n"
    "- blocking = crash/corrupt/security. suggestion = real improvement. nit = skip\n"
)


@mcp.tool()
async def codex_review(
    target: str = "",
    output: str = "CODEX_REVIEW.md",
    context: str = "",
    mode: str = "review",
) -> str:
    """Run Codex (GPT-5.5) cross-LLM review in background. Returns immediately, notifies when done.
    target: file path for review, or empty for git diff review.
    output: where to write results (relative to your cwd).
    context: extra instructions for the review prompt.
    mode: 'review' (git diff, default) or 'exec' (review specific file)."""
    info = await _api("GET", f"/api/sessions/{WORKER_NAME}", params={"scope": SCOPE})
    if isinstance(info, dict) and info.get("error"):
        return f"Error resolving worker cwd: {info['error']}"
    cwd = info.get("worktree_path") or info.get("cwd") or info.get("scope", SCOPE)
    output_abs = f"{cwd}/{output}" if not output.startswith("/") else output

    prompt_parts = [_REVIEW_CONTEXT]
    if context:
        prompt_parts.append(f"Additional context: {context}\n")
    prompt_parts.append(f"Write your review to {output}.")
    prompt_parts.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
    review_prompt = "\n".join(prompt_parts)

    prompt_file = f"/tmp/codex_review_{WORKER_NAME}.txt"

    if mode == "review":
        cmd = (
            f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec review"
            f" --uncommitted --skip-git-repo-check --full-auto --ephemeral"
            f" -o {output_abs}"
        )
    elif mode == "exec":
        if not target:
            return "Error: target file required for mode='exec'"
        prompt_parts_exec = [_REVIEW_CONTEXT]
        if context:
            prompt_parts_exec.append(f"Additional context: {context}\n")
        prompt_parts_exec.append(f"Review the file: {target}")
        prompt_parts_exec.append(f"Write your findings to {output}.")
        prompt_parts_exec.append("Format: ## Summary, ## Findings (blocking/suggestion/question), ## Verdict")
        exec_prompt = "\n".join(prompt_parts_exec)

        cmd = (
            f"cat > {prompt_file} << 'CODEX_PROMPT_EOF'\n{exec_prompt}\nCODEX_PROMPT_EOF\n"
            f"cd {cwd} && UV_CACHE_DIR=/tmp/uv-cache {_CODEX_BIN} exec"
            f" -s workspace-write --skip-git-repo-check --full-auto --ephemeral"
            f" -o {output_abs}"
            f" - < {prompt_file}"
        )
    else:
        return f"Error: unknown mode '{mode}'. Use 'review' or 'exec'."

    logger.info(f"codex_review: mode={mode} cwd={cwd} output={output_abs} cmd={cmd[:300]}")
    result = await _api("POST", "/api/bg/jobs", json={
        "type": "run",
        "config": {"command": cmd},
        "message": f"Codex {mode} done. Results in {output}",
        "target_name": WORKER_NAME,
        "target_scope": SCOPE,
        "timeout_seconds": 300,
        "created_by": WORKER_NAME,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Error creating bg job: {result['error']}"
    job_id = result.get("id", "?")
    return (
        f"Codex {mode} started (bg job {job_id}, 5-min timeout). "
        f"You WILL be notified on success, timeout, or failure — do NOT poll, just wait. "
        f"On success: read {output}. Do not start another codex_review until this one reports back."
    )


if __name__ == "__main__":
    logger.info(f"Orchestra MCP stdio (url={ORCHESTRA_URL}, scope={SCOPE})")
    mcp.run(transport="stdio")
