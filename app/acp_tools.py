"""ACP v1 tool snapshots and patches, deliberately bounded foreground reducer."""
import hashlib
import json
from copy import deepcopy


def bounded(value, depth=0):
    if depth > 10: return "[depth limit]"
    if isinstance(value,str): return value[:32000]
    if isinstance(value,list): return [bounded(x,depth+1) for x in value[:128]]
    if isinstance(value,dict):
        return {str(k)[:128]:bounded(v,depth+1) for k,v in list(value.items())[:128]
                if k not in {"data","blob"} or not str(value.get("mimeType","")).startswith("image/")}
    return value


_ORCHESTRA_MCP_TOOLS = frozenset({
    "multicode_run", "spawn_worker", "retry_initial_delivery", "send_message",
    "list_pending_deliveries", "cancel_message_delivery", "open_fan",
    "list_agents", "list_orchestrators", "get_worker_logs", "search_logs",
    "get_log_context", "compact_worker", "temp_rule_set", "temp_rule_list",
    "temp_rule_update", "temp_rule_remove", "kill_worker", "stop_worker",
    "rename_worker", "send_file", "send_files", "publish_artifact",
    "send_chart", "notify_user", "update_progress", "update_checklist",
    "change_worker_model", "merge_worker", "resolve_merge_operation",
    "bind_worker_task", "switch_worker_branch", "check_conflict", "worker_wip",
    "acquire_test_lock", "release_test_lock", "test_lock_status", "report_bug",
    "update_worker_description", "set_worker_owned_dirs", "update_worker_prompt",
    "get_worker_info", "task_create", "task_update", "task_list", "task_get",
    "eval_grant_issue", "dynamic_workflow", "bg_create", "bg_list", "bg_cancel",
    "codex_review", "set_timer", "list_timers", "cancel_timer",
    "request_approval", "list_approvals", "cancel_approval",
    "outbox_enqueue", "outbox_list", "kb_search",
})


def canonical_orchestra_tool_name(name: str) -> str | None:
    clean = str(name or "").strip()
    if not clean:
        return None
    import re as _re
    m = _re.fullmatch(
        r"(?:mcp__orchestra(?:_[0-9a-f]{4,16})?__|mcp_orchestra(?:_[0-9a-f]{4,16})?_|orchestra(?:__|[:._]))([A-Za-z0-9_]+)",
        clean,
    )
    if m and m.group(1) in _ORCHESTRA_MCP_TOOLS:
        return f"mcp__orchestra__{m.group(1)}"
    if clean in _ORCHESTRA_MCP_TOOLS:
        return f"mcp__orchestra__{clean}"
    return None


def _normalize_orchestra_wire_name(name: str) -> str:
    clean = str(name or "").strip()
    if not clean:
        return "tool"
    canonical = canonical_orchestra_tool_name(clean)
    return canonical if canonical is not None and (
        clean.startswith(("mcp__", "mcp_orchestra", "orchestra"))
    ) else clean


def canonical_name(state):
    raw=state.get("rawInput")
    if isinstance(raw,dict) and isinstance(raw.get("ServerName"),str) and isinstance(raw.get("ToolName"),str):
        server = raw["ServerName"].strip()
        tool = raw["ToolName"].strip()
        import re as _re
        if _re.fullmatch(r"orchestra(?:_[0-9a-f]{4,16})?", server) and tool in _ORCHESTRA_MCP_TOOLS:
            server = "orchestra"
        return "mcp__"+server+"__"+tool
    if isinstance(state.get("name"),str) and state["name"].strip():
        return _normalize_orchestra_wire_name(state["name"])
    # Title describes an invocation, never a canonical executable name.
    # Kind is a presentation category, not evidence of a programmatic name.
    return "tool"


def extract_diffs(state):
    diffs = []
    for block in state.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "diff":
            diffs.append({
                "path": str(block.get("path") or ""),
                "old_text": str(block.get("oldText") or ""),
                "new_text": str(block.get("newText") or ""),
            })
    return diffs


def display_content(state):
    result=[]; unsupported=[]
    for block in state.get("content") or []:
        if not isinstance(block,dict): continue
        kind=block.get("type")
        if kind=="content":
            content=block.get("content") or {}
            if content.get("type")=="text":result.append(content.get("text",""))
            elif content.get("type")=="resource" and isinstance(content.get("resource"),dict):
                resource=content["resource"];result.append(str(resource.get("text") or "[resource: "+str(resource.get("uri",""))+"]"))
            else:unsupported.append(str(content.get("type","unknown")))
        elif kind=="diff":
            result.append("--- "+str(block.get("path","file"))+"\n"+str(block.get("oldText") or "")+"\n+++\n"+str(block.get("newText") or ""))
        else:unsupported.append(str(kind))
    raw=state.get("rawOutput")
    if raw is not None:
        rendered=raw if isinstance(raw,str) else json.dumps(raw,ensure_ascii=False,sort_keys=True)
        if rendered not in result:result.append(rendered)
    if unsupported:result.append("[ACP display unsupported: "+", ".join(sorted(set(unsupported)))+"]")
    return "\n".join(str(x) for x in result),unsupported


class ToolReducer:
    def __init__(self):self.states={};self.started=set();self.emitted={};self.revisions={};self.inputs={}

    def apply(self,patch):
        tid=patch.get("toolCallId")
        if not isinstance(tid,str) or not tid or len(tid)>256:raise ValueError("Invalid ACP tool ID")
        state=deepcopy(self.states.get(tid,{"toolCallId":tid,"status":"pending"}))
        for key in ("name","title","kind","status","rawInput","rawOutput","content","locations","_meta"):
            if key in patch and patch[key] is not None:state[key]=bounded(patch[key])
        self.states[tid]=state
        digest=hashlib.sha256(json.dumps(state,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if self.emitted.get(tid)==digest:return []
        self.emitted[tid]=digest;self.revisions[tid]=self.revisions.get(tid,0)+1
        name=canonical_name(state);raw=state.get("rawInput",{})
        if name.startswith("mcp__") and isinstance(raw,dict) and "Arguments" in raw:raw=raw["Arguments"]
        body=json.dumps(raw,ensure_ascii=False) if not isinstance(raw,str) else raw
        output,unsupported=display_content(state)
        raw_diffs = extract_diffs(state)
        has_output = bool(str(output or "").strip())
        meta={"tool_use_id":tid,"tool_name":name,"status":state.get("status"),
              "tool_status":state.get("status"),"has_output":has_output,
              "title":state.get("title",""),"kind":state.get("kind"),"is_error":state.get("status")=="failed",
              "unsupported":unsupported,"acp_revision":self.revisions[tid],"raw_input":deepcopy(raw)}
        if raw_diffs:
            meta["raw_diffs"] = raw_diffs
        result=[]
        input_key = (name, body)
        if tid not in self.started:
            self.started.add(tid);result.append(("tool_use",name+": "+body,dict(meta)))
        elif self.inputs.get(tid) != input_key:
            result.append(("tool_update",name+": "+body,dict(meta)))
        self.inputs[tid] = input_key
        if state.get("status") in {"completed","failed"}:
            # Never fabricate fake answer from display title when tool emitted no output (B07).
            result.append(("tool_result",output if has_output else "",dict(meta)))
        elif tid in self.started:
            result.append(("tool_stream",output if has_output else str(state.get("title",name)),{**meta,"replace":True}))
        return result
