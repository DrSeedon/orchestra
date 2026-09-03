# #25 — validate_spawn — PLAN

## Decision recap (from orchestrator)
- spawn_worker sends `parent_name=WORKER_NAME`; `create_session` resolves parent role from DB and validates.
- **`can_spawn` ABSENT (no field) = NO restriction (allow all).**
- **`can_spawn: []` (empty list present) = allow NOTHING (terminal role).**
- Fail-open when parent is unknown/unresolvable (e.g. top-level orchestrator with no parent).
- Do NOT add `can_spawn` to orchestrator.md (leave absent = allow all).

## Semantics table
| parent `can_spawn` | meaning | child allowed? |
|---|---|---|
| field absent | no restriction | always allowed |
| `[]` (empty list) | terminal role | never allowed → error |
| `["a","b"]` | whitelist | only if child role ∈ list |
| parent unresolvable | fail-open | allowed |

The distinction "absent vs empty list" requires reading the raw frontmatter dict. **Codex caught a sharp edge:** `meta.get("can_spawn", None)` does NOT distinguish "field absent" from "field present but YAML null" (`can_spawn:` with no value → `yaml.safe_load` gives `{"can_spawn": None}`). Must use **`"can_spawn" not in meta`** to detect absence. YAML null and malformed (non-list) values → fail-open (unrestricted), with a warning.

## Security note (advisory, not a boundary)
`can_spawn` is an **advisory guardrail**, not a security boundary. `parent_name` arrives from the caller (MCP `spawn_worker` sends `WORKER_NAME`; `/api/sessions` is internal-token-gated). A malicious caller could spoof a permissive parent — but the threat model is a single trusted operator + local MCP processes, so this is acceptable. Documented here so future-readers don't mistake it for enforcement. (Codex #25-2 — acknowledged, by design.)

## Changes

### 1. `app/manager.py` — new helper
Add near `_load_role_skills`:
```python
def _role_can_spawn(role: str):
    """Return the can_spawn whitelist for a role, or None if unrestricted.
    None  = field absent  -> no restriction (spawn anything)
    []    = empty list    -> terminal role (spawn nothing)
    [...] = whitelist of allowed child roles
    """
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if not role_path.exists():
        return None
    meta, _ = _parse_role_frontmatter(role_path.read_text())
    if "can_spawn" not in meta:
        return None  # field absent -> no restriction
    val = meta["can_spawn"]
    if not isinstance(val, list):
        # YAML null (`can_spawn:`) or malformed -> fail-open (unrestricted)
        logger.warning(f"role '{role}' has non-list can_spawn ({val!r}); treating as unrestricted")
        return None
    return [str(x) for x in val]
```

### 2. `app/manager.py` — `create_session` validation
After parent_name/parent_id resolution (after current lines ~328-333), before building the AgentSession, add:
```python
# Validate parent's can_spawn whitelist (fail-open if parent unknown)
if parent_name:
    parent_role = self._resolve_role(parent_name, scope)
    if parent_role:
        whitelist = _role_can_spawn(parent_role)
        if whitelist is not None and role not in whitelist:
            allowed = ", ".join(whitelist) if whitelist else "(none — terminal role)"
            raise ValueError(
                f"role '{parent_role}' is not allowed to spawn role '{role}'. "
                f"Allowed: {allowed}"
            )
```
Add helper `_resolve_role(name, scope)`:
```python
def _resolve_role(self, name: str, scope: str) -> str | None:
    for s in self.sessions.values():
        if s.name == name and s.scope == scope:
            return s.role
    row = get_session_by_name(name, scope)
    return row.get("role") if row else None
```

**Placement note:** validation must run BEFORE `create_worktree` / DB insert so a rejected spawn leaves no artifacts. Current code does `save_session` at line 345 then worktree at 356. Put the check right after parent resolution (~line 333), which is before the first `save_session`. Good.

### 3. `app/mcp_stdio.py` — `spawn_worker` sends parent_name
In the POST body (around line 67), add:
```python
body = {
    ...,
    "role": role,
    "parent_name": WORKER_NAME,   # spawner = caller; create_session resolves its role
}
```
`WORKER_NAME` is the calling agent's name (orchestrator's own name for orchestrator, worker name for a worker). `CreateSessionRequest.parent_name` already exists → flows through.

**Edge:** if the caller is the top-level orchestrator, `parent_name=WORKER_NAME` = orchestrator name. `_resolve_role` finds it → role "orchestrator" → no `can_spawn` field → unrestricted. Correct. If the orchestrator session somehow isn't in DB yet, `_resolve_role` returns None → fail-open. Correct.

## What NOT to touch
- Do NOT add `can_spawn` to any existing role file.
- Do NOT change orchestrator/worker/full-cycle frontmatter.
- Do NOT enforce in the API endpoint separately — single enforcement point in `create_session`.

## Tests (`tests/test_manager.py`)
New class `TestCanSpawn`:
1. `test_no_can_spawn_field_allows_any` — parent role file without can_spawn → child spawns OK. (Use a temp role file via monkeypatching `_PROMPTS_DIR`, OR test `_role_can_spawn` returns None directly + a create_session integration test using existing orchestrator role.)
2. `test_empty_can_spawn_blocks_all` — parent with `can_spawn: []` → ValueError.
3. `test_whitelist_allows_listed` — parent `can_spawn: [worker]`, child `worker` → OK.
4. `test_whitelist_blocks_unlisted` — parent `can_spawn: [worker]`, child `full-cycle` → ValueError.
5. `test_unknown_parent_fails_open` — parent_name that resolves to nothing → child spawns OK.
6. Unit-test `_role_can_spawn` directly for absent / YAML-null / [] / [list] / non-list by writing temp role .md files into a patched roles dir. Explicitly cover the `can_spawn:` (null) case → returns None (unrestricted).

**Test strategy for role files:** monkeypatch `app.manager._PROMPTS_DIR` to a tmp dir with custom `roles/*.md`, OR add a focused unit test that calls `_role_can_spawn` with files written to a patched dir. For the create_session integration, seed a parent session in DB with a known role and patch the role file.

## Risks
- Reading frontmatter on every spawn = a file read; negligible (spawns are rare).
- `_resolve_role` may return a dict-row role key missing → use `.get("role")`, returns None → fail-open.
- Malformed `can_spawn` (string instead of list) → fail-open (return None). Defensible: don't block spawns on a typo'd role file.
