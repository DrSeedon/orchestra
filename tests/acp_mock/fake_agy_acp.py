#!/usr/bin/python3
"""Credential-free ACP v1 peer. Only this executable is allowed by offline runner."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

assert sys.argv[1:] == ["acp", "--disable-telemetry", "--gemini-dir",
                       str(Path(os.environ["HOME"]) / ".gemini"),
                       "--app-data-dir", "antigravity-acp"]
TRACE = Path(os.environ["AGY_MOCK_TRACE"])
MODE = os.environ.get("AGY_MOCK_MODE", "normal")
HOME = Path(os.environ["HOME"])
assert not list(HOME.rglob("*token*")), "fake profile must contain no credentials"
active = set()
cancel = {}
costs = {}
client_requests = {}
permission_serial = 0
current_models = {}


def trace(method, **extra):
    with TRACE.open("a") as f:
        f.write(json.dumps({"pid": os.getpid(), "method": method, "time": time.monotonic(), **extra}) + "\n")


def emit(value):
    print(json.dumps({"jsonrpc": "2.0", **value}), flush=True)


def result(request, value):
    emit({"id": request["id"], "result": value})


def update(sid, update_kind, **extra):
    emit({"method": "session/update", "params": {
        "sessionId": sid, "update": {"sessionUpdate": update_kind, **extra}}})


def models(sid):
    if MODE == "only-argon":
        return {"sessionId":sid,"models":{"currentModelId":"gemini-4-argon-medium",
            "availableModels":[{"modelId":"gemini-4-argon-medium","name":"Argon"}]}}
    if MODE.startswith("config-"):
        return {"sessionId": sid, "configOptions": [{"id": "choose-model", "category": "model",
            "name": "Model", "type": "select", "currentValue": current_models.get(sid, "gemini-4-argon-medium" if MODE != "config-options" else "gemini-4-carbon-medium"),
            "options": [{"group": "Gemini", "options": [
                {"value": m, "name": m} for m in ("gemini-4-carbon-medium", "gemini-4-argon-medium")]}]}]}
    if MODE=="effort-variants":
        return {"sessionId":sid,"models":{"currentModelId":"gemini-4-carbon-medium","availableModels":[{"modelId":m,"name":m} for m in ("gemini-4-carbon-medium","gemini-4-carbon-high")]}}
    return {"sessionId": sid, "models": {"currentModelId": "gemini-4-carbon-medium",
        "availableModels": [{"modelId": m, "name": m} for m in
                            ("gemini-4-carbon-medium", "gemini-4-argon-medium")]}}


async def prompt(request):
    p = request["params"]
    sid = p["sessionId"]
    text = p["prompt"][-1]["text"]
    assert not active, "profile-wide concurrency exceeded one prompt"
    active.add(sid)
    cancel[sid] = asyncio.Event()
    trace("prompt_start", session=sid, text=text,
          role=p["prompt"][0]["text"] if len(p["prompt"]) > 1 else "")
    if text.endswith("FG_LIVE_THOUGHT"):
        update(sid,"agent_thought_chunk",content={"type":"text","text":"live thought segment"})
        await cancel[sid].wait()
        result(request,{"stopReason":"cancelled"});active.clear();trace("prompt_end",session=sid);return
    if text.endswith("FG_TRANSCRIPT"):
        update(sid,"agent_message_chunk",content={"type":"text","text":"before tool "})
        update(sid,"agent_thought_chunk",content={"type":"text","text":"checking"})
        update(sid,"tool_call",toolCallId="fg-command",name="run_command",title="Analyze: source",kind="execute",status="in_progress",rawInput={"CommandLine":"echo synthetic"})
        update(sid,"tool_call_update",toolCallId="fg-command",content=[{"type":"content","content":{"type":"text","text":"early output"}}])
        update(sid,"tool_call_update",toolCallId="fg-command",status="completed")
        for _ in range(2):update(sid,"tool_call_update",toolCallId="fg-command",status="completed",content=[{"type":"content","content":{"type":"text","text":"late output"}}])
        update(sid,"tool_call",toolCallId="fg-mcp",name="call_mcp_tool",title="Read task",kind="read",status="failed",rawInput={"ServerName":"orchestra","ToolName":"task_get","Arguments":{"id":"synthetic"}},content=[{"type":"diff","path":"synthetic.txt","oldText":"a","newText":"b"},{"type":"content","content":{"type":"resource","resource":{"uri":"file:///synthetic","text":"resource preview"}}}])
        update(sid,"agent_message_chunk",content={"type":"text","text":"after "})
        update(sid,"agent_message_chunk",content={"type":"text","text":"tool"})
        update(sid,"usage_update",used=200,size=1000)
        result(request,{"stopReason":"end_turn"});active.clear();trace("prompt_end",session=sid);return
    if "FG_PERMISSION" in text or text.endswith("FG_QUESTION") or text.endswith("FG_NATIVE_EOF"):
        global permission_serial
        count=2 if text.endswith("FG_PERMISSION_TWO") else 1
        waiting=[]
        for i in range(count):
            permission_serial+=1;rid="native-"+str(permission_serial)
            future=asyncio.get_running_loop().create_future();client_requests[rid]=future;waiting.append(future)
            tool_id=("interaction_" if text.endswith("FG_QUESTION") else "native-tool-")+str(permission_serial)
            options=[{"optionId":"allow-"+str(i),"kind":"allow_once","name":"Allow once"},{"optionId":"deny-"+str(i),"kind":"reject_once","name":"Deny"}]
            if text.endswith("FG_PERMISSION_BAD"):options[1]["optionId"]=options[0]["optionId"]
            method="unknown/native_request" if text.endswith("FG_PERMISSION_UNKNOWN") else "session/request_permission"
            emit({"id":rid,"method":method,"params":{"sessionId":sid,"toolCall":{"toolCallId":tool_id,"title":"Synthetic choice "+str(i),"rawInput":{"command":"echo synthetic"}},"options":options}})
            if text.endswith("FG_PERMISSION_DUPLICATE") or text.endswith("FG_PERMISSION_MUTATED"):
                emit({"id":rid,"method":method,"params":{"sessionId":sid,"toolCall":{"toolCallId":tool_id,"title":"Synthetic choice "+str(i),"rawInput":{"command":"changed" if text.endswith("FG_PERMISSION_MUTATED") else "echo synthetic"}},"options":options}})
            update(sid,"agent_thought_chunk",content={"type":"text","text":"reader remains responsive"})
        if text.endswith("FG_NATIVE_EOF"):
            await asyncio.sleep(.05);os._exit(19)
        replies=await asyncio.gather(*waiting)
        trace("native_responses",session=sid,replies=replies)
        update(sid,"agent_message_chunk",content={"type":"text","text":"continued after native response"})
        result(request,{"stopReason":"end_turn"});active.clear();trace("prompt_end",session=sid);return
    if text == "PERMISSION":
        future = asyncio.get_running_loop().create_future()
        client_requests["permission-request"] = future
        emit({"id":"permission-request", "method":"session/request_permission", "params":{
            "sessionId":sid, "toolCall":{"toolCallId":"restricted-tool", "title":"synthetic write"},
            "options":[{"optionId":"allow", "kind":"allow_once", "name":"Allow"}]}})
        reply = await future
        assert reply == {"outcome":{"outcome":"cancelled"}}
        trace("permission_denied", session=sid)
        result(request, {"stopReason":"cancelled"})
        active.clear(); trace("prompt_end", session=sid)
        return
    if text == "CONFIG":
        update(sid, "config_option_update", configOptions=[{"id":"choose-model", "category":"model",
            "type":"select", "currentValue":"gemini-4-argon-medium", "options":[
            {"value":"gemini-4-carbon-medium", "name":"Carbon"}, {"value":"gemini-4-argon-medium", "name":"Argon"}]}])
    if text == "MULTI":
        for chunk in ("hello ", "complete ", "reply"):
            update(sid, "agent_message_chunk", content={"type":"text", "text":chunk})
        result(request, {"stopReason":"end_turn"})
        active.clear(); trace("prompt_end", session=sid)
        return
    if text.endswith("HTTP_RPC_MODEL"):
        emit({"id":request["id"],"error":{"code":-32602,"message":"Synthetic model refused after prompt write"}})
        active.clear(); trace("prompt_end",session=sid); return
    if text.startswith("RPC_") or text.startswith("BAN_"):
        ban = "This service has been disabled in this account for violation of Terms of Service. synthetic-secret-never-persist"
        payloads = {
            "BAN_ROOT": {"code":403, "message":ban},
            "BAN_NESTED": {"code":-32603, "message":"Internal error", "data":{"error":{"message":ban}}},
            "BAN_LIST": {"code":-32603, "data":{"errors":[{"message":ban}]}},
            "BAN_CAUSE": {"code":-32603, "data":{"cause":{"innerError":{"detail":ban}}}},
            "RPC_AUTH": {"code":-32000, "message":"Authentication required"},
            "RPC_QUOTA": {"code":429, "data":{"error":{"message":"Quota exhausted"}}},
            "RPC_MODEL": {"code":-32602, "message":"Invalid model"},
            "RPC_INTERNAL": {"code":-32603, "message":"Internal error", "data":{"response":ban}},
        }
        emit({"id":request["id"], "error":payloads[text]})
        active.clear(); trace("prompt_end", session=sid); return
    if MODE == "ack-error" and text.endswith("Acknowledge briefly."):
        emit({"id":request["id"], "error":{"code":-32603, "message":"Synthetic ACK refusal"}})
        active.clear(); trace("prompt_end", session=sid); return
    if text == "BAN":
        update(sid, "agent_message_chunk", content={"type":"text", "text":"partial before ban"})
        emit({"id": request["id"], "error":{"code":403,
            "message":"This service has been disabled in this account for violation of Terms of Service. synthetic-secret-never-persist"}})
        active.clear(); return
    if text == "DIE":
        os._exit(17)
    if text == "MALFORMED":
        print("not-json", flush=True)
        return
    if text in {"PARTIAL_ERROR", "PARTIAL_CANCEL", "RECOVERED", "COST", "COST_ERROR", "COST_CREDITS", "INVALID_CONTEXT"}:
        update(sid, "agent_message_chunk", content={"type": "text", "text": "partial-output"})
    if text == "COST_RESET":
        costs[sid] = 0.005
        update(sid, "usage_update", used=200, size=1000, cost={"amount":0.005,"currency":"USD"})
    if text.startswith("COST_INVALID_"):
        invalid = {"NULL":None,"BOOL":True,"NEGATIVE":-1,"TEXT":"not-a-cost"}[text.removeprefix("COST_INVALID_")]
        update(sid, "usage_update", used=200, size=1000, cost={"amount":invalid,"currency":"USD"})
    if text in {"COST", "COST_ERROR", "COST_CREDITS", "COST_BLOCK"}:
        costs[sid] = round(costs.get(sid, 0.0) + 0.01, 8)
        update(sid, "usage_update", used=200, size=1000,
               cost={"amount": costs[sid], "currency": "credits" if text == "COST_CREDITS" else "USD"})
    if text == "RECOVERED":
        update(sid, "tool_call", toolCallId="retry-tool", title="first attempt", status="in_progress")
        update(sid, "tool_call_update", toolCallId="retry-tool", title="transient tool failure", status="failed", content=[{"type":"content", "content":{"type":"text", "text":"synthetic failure details"}}], rawOutput={"exitCode":1})
        update(sid, "tool_call_update", toolCallId="retry-tool", title="retry succeeded", status="completed")
    if text == "PARTIAL_CANCEL":
        result(request, {"stopReason": "cancelled"})
        active.clear()
        trace("prompt_end", session=sid)
        return
    if text in {"ERROR", "PARTIAL_ERROR", "COST_ERROR"} or MODE == "all-error":
        emit({"id": request["id"], "error": {"code": -32000,
            "message": "synthetic-secret-must-not-leak"}})
        active.clear()
        return
    if text in {"BLOCK", "IGNORE_CANCEL", "COST_BLOCK"} or text.endswith("HTTP_BLOCK"):
        if text == "IGNORE_CANCEL":
            await asyncio.Event().wait()
        else:
            await cancel[sid].wait()
        result(request, {"stopReason": "cancelled"})
    else:
        # Deliberately interleave an unrelated session update to prove routing.
        update("wrong-session", "agent_message_chunk", content={"type": "text", "text": "WRONG"})
        update(sid, "agent_thought_chunk", content={"type": "text", "text": "thinking:" + sid})
        update(sid, "tool_call", toolCallId="tool-1", name="mock-tool", title="mock-tool", status="in_progress")
        await asyncio.sleep(0.03)
        update(sid, "tool_call_update", toolCallId="tool-1", status="in_progress", content=[{"type":"content", "content":{"type":"text", "text":"tool progress"}}])
        update(sid, "tool_call_update", toolCallId="tool-1", title="mock-result", status="completed")
        if not (MODE == "ack-unknown" and text.endswith("Acknowledge briefly.")):
            update(sid, "usage_update", used=True if text == "INVALID_CONTEXT" else (700 if "INITIAL_CONTEXT" in text and not text.endswith("Acknowledge briefly.") else 200), size=1000)
        update(sid, "agent_message_chunk", content={"type": "text", "text": sid + ":" + text})
        result(request, {"stopReason": "end_turn"})
    active.remove(sid)
    trace("prompt_end", session=sid)


async def main():
    trace("spawn", home=str(HOME))
    tasks = []
    number = 0
    while line := await asyncio.to_thread(sys.stdin.readline):
        request = json.loads(line)
        if "method" not in request:
            future = client_requests.pop(request.get("id"), None)
            if future and not future.done():
                trace("native_reply",request_id=request.get("id"),result=request.get("result"))
                future.set_result(request.get("result"))
            continue
        method = request.get("method")
        trace(method, params=request.get("params", {}) if method != "session/prompt" else {})
        if method == "initialize":
            if MODE == "init-death":
                os._exit(18)
            result(request, {"protocolVersion": 2 if MODE=="wire-v2" else 1,
                "agentCapabilities": {"sessionCapabilities": {"resume": {}}} if MODE != "no-resume" else {},
                "authMethods": [{"id": "oauth-personal", "name": "Synthetic cached OAuth"}]})
        elif method == "authenticate":
            if MODE == "auth-error":
                emit({"id": request["id"], "error": {"code": -32000, "message": "synthetic-auth-error"}})
            else:
                result(request, {})
        elif method in {"session/new", "session/resume"}:
            number += 1
            sid = request["params"].get("sessionId", "mock-session-" + str(1 if MODE == "collision" else number))
            result(request, models(sid))
        elif method in {"session/set_model", "session/set_config_option"}:
            sid = request["params"]["sessionId"]
            wanted = request["params"].get("value", request["params"].get("modelId"))
            if method == "session/set_config_option":
                if MODE == "config-unknown":
                    result(request, {})
                else:
                    current_models[sid] = "gemini-4-argon-medium" if MODE == "config-mismatch" else wanted
                    result(request, models(sid))
            else:
                current_models[sid] = wanted
                result(request, {})
        elif method == "session/prompt":
            tasks.append(asyncio.create_task(prompt(request)))
        elif method == "session/cancel":
            sid = request["params"]["sessionId"]
            if sid in cancel:
                cancel[sid].set()
        else:
            emit({"id": request.get("id"), "error": {"code": -32601, "message": "Unknown method"}})
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


asyncio.run(main())
