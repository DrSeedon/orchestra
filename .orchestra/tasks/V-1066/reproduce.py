"""Offline legacy/current comparison. Run with the pinned uv; no external I/O."""

import asyncio
import json
import os
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import app
from app import backend_hub as hub, hub_workspace as hw, mcp_stdio as m
from app.multicode_client import MultiCodeClient, MultiCodeError


class LocalSsh(hw.HubSsh):
    def _argv(self, remote):
        return ["/bin/bash", "-c", remote]


async def legacy_start(backend, mc, state, prompt):
    """Original no-effort send/fallback branch, reconstructed from inspected source."""
    selection = await backend._model_selection(mc, backend.model, backend._effort)
    if state.thread_id:
        try:
            sent = await mc.tool_call("t3_thread_send", {
                "threadId": state.thread_id, "message": prompt, "mode": "auto"})
        except MultiCodeError as exc:
            if exc.retryable:
                raise
            state.thread_id = ""
            prompt = backend._preamble() + prompt
        else:
            return sent["runId"]
    return await mc.tool_call("t3_thread_launch", {
        "title": state.ws_id, "projectId": state.project_id, "message": prompt,
        "runtimeMode": "full-access", "modelSelection": selection})


def sizes(value):
    return {"codepoints": len(value), "utf16_units": len(value.encode("utf-16-le")) // 2,
            "utf8_bytes": len(value.encode("utf-8"))}


async def main():
    scratch = ROOT / ".orchestra/tasks/V-1066/tmp/reproduction"
    scratch.mkdir(parents=True, exist_ok=True)
    attachment = "# Synthetic public docs\nКириллица 😀\r\n"
    attachment += "x" * (53_710 - len(attachment.encode("utf-8")))
    (scratch / "publicdocs.md").write_bytes(attachment.encode("utf-8"))
    api = AsyncMock(return_value={"ok": True})
    original_cwd = Path.cwd()
    try:
        os.chdir(scratch)
        with patch.object(m, "_api", api), patch.object(m, "WORKER_NAME", "synthetic-parent"):
            await m.send_message("synthetic-worker", "Read the complete attachment.",
                                 file_path="publicdocs.md")
    finally:
        os.chdir(original_cwd)
    accepted = api.await_args.kwargs["json"]["message"]
    system = "<system>\n" + "S" * 42_000 + "\n</system>"
    context = "<context>\n" + "C" * 30_000 + "\n</context>"
    message = system + "\n\n" + context + "\n\n" + accepted
    backend = hub.HubBackend("hub-gpt-6.1-sol", str(scratch))
    backend._early_steer = ["Apply all acceptance checks.\n" + "U" * 1_000]
    prompt = backend._prompt(message, first=False)
    output = {"app_import": "/remote/workspace/" + str(Path(app.__file__).relative_to(ROOT)),
              "attachment": sizes(attachment), "accepted_native_message": sizes(accepted),
              "system": sizes(system), "context": sizes(context),
              "early_steers": sizes(backend._early_steer[0]),
              "resume_composed": sizes(prompt), "preamble": sizes(backend._preamble())}
    with patch.object(hw, "known_secret_values", lambda extra=None: []):
        for mode in ("legacy", "fixed"):
            ws_id = hw.WorkspaceState.new_id()
            remote = scratch / ws_id
            remote.mkdir()
            state = hw.WorkspaceState(ws_id, str(scratch), str(remote),
                                      project_id="synthetic-project", thread_id="existing-thread")
            backend._ssh = LocalSsh("unused", "unused", str(scratch))
            calls = []
            recovered = []

            async def handler(request):
                body = json.loads(request.content)
                params = body["params"]
                wire = params["arguments"]["message"]
                calls.append({"tool": params["name"], **sizes(wire)})
                if sizes(wire)["utf16_units"] > 120_000:
                    return httpx.Response(200, json={"id": body["id"], "error": {
                        "code": -32602, "message": "Expected value length at most 120000 at message"}})
                rel = wire.split()[1][2:]
                recovered.append((remote / rel).read_bytes().decode("utf-8") == prompt)
                return httpx.Response(200, json={"id": body["id"], "result": {
                    "structuredContent": {"runId": "synthetic-run"}}})

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                mc = MultiCodeClient("http://mock", "synthetic-mcp-value", client=http)
                mc._initialized = True
                try:
                    run = await (legacy_start(backend, mc, state, prompt) if mode == "legacy"
                                 else backend._start(mc, state, prompt))
                    result = {"run": run}
                except MultiCodeError as exc:
                    result = {"error": str(exc)}
            output[mode] = {**result, "calls": calls, "thread_preserved": state.thread_id == "existing-thread",
                            "full_content_equal": recovered}
    print(json.dumps(output, indent=2))
    assert len(output["legacy"]["calls"]) == 2 and "error" in output["legacy"]
    assert len(output["fixed"]["calls"]) == 1 and output["fixed"]["full_content_equal"] == [True]


asyncio.run(main())
