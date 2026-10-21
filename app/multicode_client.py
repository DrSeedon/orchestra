"""Small client for the MultiCode Hub's official streamable HTTP MCP endpoint."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_INSTANCE = "claudeAgent"
DEFAULT_MODEL = "claude-sonnet-5-5"
CLIENT_INFO = {"name": "orchestra", "version": "1.0.0"}


class MultiCodeError(RuntimeError):
    """A safe-to-display MultiCode transport or protocol error."""


class MultiCodeClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0,
                 client: httpx.AsyncClient | None = None):
        if not base_url.strip():
            raise ValueError("MULTICODE_MCP_BASE is required")
        if not token.strip():
            raise ValueError("MULTICODE_MCP_TOKEN is required")
        self.base_url = base_url.rstrip("/") + "/mcp"
        self._token = token
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None
        self._session_id: str | None = None
        self._next_id = 1
        self._initialized = False

    @classmethod
    def from_env(cls) -> "MultiCodeClient":
        return cls(os.environ.get("MULTICODE_MCP_BASE", ""),
                   os.environ.get("MULTICODE_MCP_TOKEN", ""))

    async def __aenter__(self) -> "MultiCodeClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, message: dict[str, Any]) -> tuple[dict[str, Any] | None, httpx.Headers]:
        if self._client is None:
            raise MultiCodeError("MultiCode client must be used as an async context manager")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            response = await self._client.post(self.base_url, headers=headers, json=message)
        except httpx.HTTPError as exc:
            raise MultiCodeError(f"MultiCode MCP request failed: {type(exc).__name__}") from None
        if response.status_code >= 400:
            raise MultiCodeError(f"MultiCode MCP returned HTTP {response.status_code}")
        self._session_id = response.headers.get("Mcp-Session-Id", self._session_id)
        if not response.content:
            return None, response.headers
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            data = [line[5:].strip() for line in response.text.splitlines()
                    if line.startswith("data:") and line[5:].strip() != "[DONE]"]
            if not data:
                return None, response.headers
            raw = data[-1]
        else:
            raw = response.text
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            raise MultiCodeError("MultiCode MCP returned invalid JSON") from None
        if not isinstance(result, dict):
            raise MultiCodeError("MultiCode MCP returned an invalid JSON-RPC response")
        if result.get("error"):
            error = result["error"]
            raise MultiCodeError(f"MultiCode MCP error {error.get('code', 'unknown')}: "
                                 f"{self._redact(str(error.get('message', 'request failed')))}")
        return result, response.headers

    async def initialize(self) -> None:
        if self._initialized:
            return
        request_id = self._next_id
        self._next_id += 1
        result, _ = await self._post({
            "jsonrpc": "2.0", "id": request_id, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": CLIENT_INFO},
        })
        if not result or result.get("id") != request_id or not isinstance(result.get("result"), dict):
            raise MultiCodeError("MultiCode MCP initialize handshake failed")
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True

    async def tool_call(self, name: str, arguments: dict[str, Any]) -> Any:
        await self.initialize()
        request_id = self._next_id
        self._next_id += 1
        response, _ = await self._post({
            "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        if not response or response.get("id") != request_id:
            raise MultiCodeError(f"MultiCode MCP {name} returned no result")
        result = response.get("result")
        if not isinstance(result, dict):
            raise MultiCodeError(f"MultiCode MCP {name} returned an invalid result")
        if result.get("isError"):
            detail = " ".join(item.get("text", "") for item in result.get("content", [])
                               if isinstance(item, dict))
            raise MultiCodeError(f"MultiCode tool {name} failed: "
                                 f"{self._redact(detail) if detail else 'tool error'}")
        if "structuredContent" in result:
            return self._redact_value(result["structuredContent"])
        content = result.get("content", [])
        texts = [item["text"] for item in content if isinstance(item, dict) and
                 item.get("type") == "text" and isinstance(item.get("text"), str)]
        if len(texts) == 1:
            try:
                return self._redact_value(json.loads(texts[0]))
            except json.JSONDecodeError:
                return self._redact(texts[0])
        return [self._redact(item) for item in texts]

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "[redacted]") if self._token else text

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact(value)
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._redact_value(item) for key, item in value.items()}
        return value

    async def run(self, prompt: str, *, title: str = "Orchestra task",
                  timeout_ms: int = 300_000, wait_slice_ms: int = 10_000,
                  instance: str | None = None, model: str | None = None,
                  effort: str | None = None) -> str:
        if not prompt.strip():
            raise ValueError("prompt is required")
        if timeout_ms <= 0 or wait_slice_ms <= 0:
            raise ValueError("timeouts must be positive")
        selection: dict[str, Any] = {
            "instanceId": instance or os.environ.get("MULTICODE_MCP_INSTANCE") or DEFAULT_INSTANCE,
            "model": model or os.environ.get("MULTICODE_MCP_MODEL") or DEFAULT_MODEL,
        }
        if effort:
            selection["options"] = {"effort": effort}
        launched = await self.tool_call("t3_thread_launch", {
            "title": title, "message": prompt, "scratch": True,
            "runtimeMode": "approval-required", "modelSelection": selection,
        })
        thread_id = launched.get("threadId") if isinstance(launched, dict) else None
        if not isinstance(thread_id, str) or not thread_id:
            raise MultiCodeError("MultiCode launch returned no threadId")
        remaining = timeout_ms
        while remaining > 0:
            current_wait = min(wait_slice_ms, remaining)
            waited = await self.tool_call("t3_thread_wait", {
                "threadId": thread_id, "timeoutMs": current_wait,
            })
            if not isinstance(waited, dict) or not waited.get("timedOut"):
                break
            remaining -= current_wait
        else:
            raise MultiCodeError(f"MultiCode thread {thread_id} timed out")
        read_result = await self.tool_call("t3_thread_read", {
            "threadId": thread_id, "view": "messages", "limit": 100,
        })
        reply = _last_assistant_text(read_result)
        if reply is None:
            raise MultiCodeError("MultiCode thread has no assistant reply")
        await self.tool_call("t3_thread_organize", {"threadId": thread_id, "action": "archive"})
        return self._redact(reply)

    async def send_follow_up(self, thread_id: str, message: str) -> Any:
        if not thread_id.strip() or not message.strip():
            raise ValueError("thread_id and message are required")
        return await self.tool_call("t3_thread_send", {
            "threadId": thread_id, "message": message, "mode": "queue",
        })


def _last_assistant_text(value: Any) -> str | None:
    items = value.get("messages", []) if isinstance(value, dict) else value
    if isinstance(items, dict):
        items = items.get("items", [])
    if not isinstance(items, list):
        return None
    for item in reversed(items):
        if isinstance(item, dict) and item.get("role") == "assistant" and isinstance(item.get("text"), str):
            return item["text"]
    return None
