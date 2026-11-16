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


def trace(method, **extra):
    with TRACE.open("a") as f:
        f.write(json.dumps({"pid": os.getpid(), "method": method, "time": time.monotonic(), **extra}) + "\n")


def emit(value):
    print(json.dumps({"jsonrpc": "2.0", **value}), flush=True)


def result(request, value):
    emit({"id": request["id"], "result": value})


def update(sid, kind, **extra):
    emit({"method": "session/update", "params": {
        "sessionId": sid, "update": {"sessionUpdate": kind, **extra}}})


def models(sid):
    if MODE == "config-options":
        return {"sessionId": sid, "configOptions": [{"id": "choose-model", "category": "model",
            "name": "Model", "type": "select", "currentValue": "gemini-4-carbon-medium",
            "options": [{"group": "Gemini", "options": [
                {"value": m, "name": m} for m in ("gemini-4-carbon-medium", "gemini-4-argon-medium")]}]}]}
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
    if text in {"BLOCK", "IGNORE_CANCEL", "COST_BLOCK"}:
        if text == "IGNORE_CANCEL":
            await asyncio.Event().wait()
        else:
            await cancel[sid].wait()
        result(request, {"stopReason": "cancelled"})
    else:
        # Deliberately interleave an unrelated session update to prove routing.
        update("wrong-session", "agent_message_chunk", content={"type": "text", "text": "WRONG"})
        update(sid, "agent_thought_chunk", content={"type": "text", "text": "thinking:" + sid})
        update(sid, "tool_call", toolCallId="tool-1", title="mock-tool", status="in_progress")
        await asyncio.sleep(0.03)
        update(sid, "tool_call_update", toolCallId="tool-1", status="in_progress", content=[{"type":"content", "content":{"type":"text", "text":"tool progress"}}])
        update(sid, "tool_call_update", toolCallId="tool-1", title="mock-result", status="completed")
        update(sid, "usage_update", used=True if text == "INVALID_CONTEXT" else 200, size=1000)
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
            if future and not future.done(): future.set_result(request.get("result"))
            continue
        method = request.get("method")
        trace(method, params=request.get("params", {}) if method != "session/prompt" else {})
        if method == "initialize":
            if MODE == "init-death":
                os._exit(18)
            result(request, {"protocolVersion": 1,
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
