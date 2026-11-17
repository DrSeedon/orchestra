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


def canonical_name(state):
    raw=state.get("rawInput")
    if isinstance(raw,dict) and isinstance(raw.get("ServerName"),str) and isinstance(raw.get("ToolName"),str):
        return "mcp__"+raw["ServerName"].strip()+"__"+raw["ToolName"].strip()
    if isinstance(state.get("name"),str) and state["name"].strip(): return state["name"].strip()
    # Title describes an invocation, never a canonical executable name.
    # Kind is a presentation category, not evidence of a programmatic name.
    return "tool"


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
    def __init__(self):self.states={};self.started=set();self.emitted={};self.revisions={}

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
        meta={"tool_use_id":tid,"tool_name":name,"status":state.get("status"),
              "title":state.get("title",""),"kind":state.get("kind"),"is_error":state.get("status")=="failed",
              "unsupported":unsupported,"acp_revision":self.revisions[tid]}
        result=[]
        if tid not in self.started:
            self.started.add(tid);result.append(("tool_use",name+": "+body,dict(meta)))
        if state.get("status") in {"completed","failed"}:
            result.append(("tool_result",output or str(state.get("title",name)),dict(meta)))
        elif tid in self.started:
            result.append(("tool_stream",output or str(state.get("title",name)),dict(meta)))
        return result
