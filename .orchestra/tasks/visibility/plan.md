# Plan: Worker Visibility Between Orchestrators

## Change 1: `manager.py` — `_workers_block(scope, orchestrator_name)`

**Current**: `_workers_block(scope: str)` filters workers by `scope == scope` only.

**Change**: Add `orchestrator_name: str = ""` param. Split workers into two groups:
- **Your workers**: `parent_name == orchestrator_name` OR `parent_name == ""` (legacy/unowned)
- **Other workers**: everyone else — show with `(owner: {parent_name})` attribution

**Callers** (`ROLE_SYSTEM_PROMPT`): doesn't have orchestrator name. Add `name: str = ""` param to `ROLE_SYSTEM_PROMPT()`. Thread from `create_session()` and `_load_from_db()` where name is available.

```python
def _workers_block(scope: str, orchestrator_name: str = "") -> str:
    workers = [s for s in get_all_sessions(scope)
               if not is_orchestrator_role(s.get("role", "worker"))]
    if not workers:
        return ""
    
    mine = []
    others = []
    for w in workers:
        pn = w.get("parent_name", "")
        if not orchestrator_name or pn == orchestrator_name or not pn:
            mine.append(w)
        else:
            others.append(w)
    
    lines = ["## Your current workers", "...existing instructions..."]
    for w in mine:
        # same format as now
    
    if others:
        lines.append("")
        lines.append("## Other orchestrators' workers")
        lines.append("⚠️ These belong to other orchestrators. Do NOT send them tasks directly — message their orchestrator instead.")
        for w in others:
            parent = w.get("parent_name", "?")
            lines.append(f"- **{name}** — owner: {parent} | ...")
    
    return "\n".join(lines)
```

## Change 2: `mcp_stdio.py` — `list_agents()` grouping

**Current**: Flat list of all agents.

**Change**: Group output using `WORKER_NAME` (env var = calling agent's name) and each session's `parent_name` field (available via API response).

Need `parent_name` in API response — check if `/api/sessions` returns it. Looking at `list_sessions()` → calls `s.to_dict()` for loaded sessions (has `parent_name`) and raw DB rows (has `parent_name` column). Both should have it.

```python
@mcp.tool()
async def list_agents() -> str:
    sessions = await _api("GET", "/api/sessions", ...)
    
    orchestrators = []
    my_workers = []
    other_workers = []
    
    for s in sessions:
        role = s.get("role", "worker")
        if is_orchestrator_role(role):  # Need to import or inline check
            orchestrators.append(s)
        elif s.get("parent_name", "") == WORKER_NAME or not s.get("parent_name"):
            my_workers.append(s)
        else:
            other_workers.append(s)
    
    # Format each group with headers
```

**Note**: `is_orchestrator_role` lives in `app.prompting` — MCP stdio is a separate process, can't import it. Inline the check: `role in ("orchestrator", "sub-orchestrator")`.

## Change 3: `mcp_stdio.py` — `send_message()` warning

**Current**: Returns `"Message sent to '{to}'"` unconditionally.

**Change**: After successful send, look up target's `parent_name`. If it differs from `WORKER_NAME` and is non-empty, append warning.

Need to fetch target info. Option A: extra API call (`GET /api/sessions/{to}`). Option B: have the send API return `parent_name` in response.

**Choice**: Option B — add `parent_name` to send response in `main.py`. Cheaper (no extra call), and the data is already loaded.

```python
# main.py send_message endpoint — add to response:
return {"ok": True, "parent_name": session.parent_name if hasattr(session, 'parent_name') else ""}

# mcp_stdio.py send_message:
parent = result.get("parent_name", "")
if parent and parent != WORKER_NAME:
    return f"Message sent to '{to}'\n⚠️ This worker belongs to '{parent}'. Consider messaging '{parent}' instead."
return f"Message sent to '{to}'"
```

## Change 4: `main.py` — expose `parent_name` in send response

Minimal: add `parent_name` to the JSON response of `POST /api/sessions/{name}/send`.

## Files Changed

| File | Lines changed (est.) | What |
|------|---------------------|------|
| `app/manager.py` | ~25 | `_workers_block` + `ROLE_SYSTEM_PROMPT` signature |
| `app/mcp_stdio.py` | ~30 | `list_agents` grouping + `send_message` warning |
| `app/main.py` | ~3 | expose parent_name in send response |

## What NOT to touch
- `app/session.py` — no changes needed
- `app/db.py` — no schema changes
- spawn logic — parent_name already set correctly
- Dashboard / frontend — not affected

## Edge Cases
- `parent_name == ""` (legacy) → treat as "mine" for root orchestrators
- Orchestrator calling `list_agents` with `WORKER_NAME` matching no parent → all workers show as "other" (correct for new orchestrator in existing scope)
- Worker calling `list_agents` → no special grouping needed, workers don't manage other workers
