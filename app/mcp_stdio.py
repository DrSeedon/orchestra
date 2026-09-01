"""External stdio MCP server for Orchestra.

Runs as a separate process, communicates with Orchestra via HTTP API.
Avoids the in-process SDK control_request deadlock (issue #425/#701).

Usage: python -m app.mcp_stdio
"""

import asyncio
import json
import logging
import math
import os
import shutil
import re
import shlex
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

# Единственный владелец правила «ошибка обязана назвать себя». Модуль на голой
# stdlib — этот процесс запускается как СКРИПТ (runtime_env: python mcp_stdio.py)
# и ничего больше из app/ не тянет.
from app.errtext import err_text

# Logs go to stderr so they don't pollute the JSON-RPC stdout stream
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("orchestra-mcp")

ORCHESTRA_URL = os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8888")
SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")
# Дедлайн ТОЛЬКО для search_memory (общий дефолт _api = 30 с не трогаем).
# 5 с = 1.9× от худшего здорового наблюдения 2659 мс при 8 одновременных клиентах,
# замер 03.08.2026 docs/tasks/18/measurements/search-latency-p8.log. Привязан к 8 ядрам
# и текущему размеру индекса — меняется железо, перемеряй, а не подкручивай.
SEARCH_DEADLINE_S = 5.0
ROLE = os.environ.get("ORCHESTRA_ROLE", "orchestrator")
WORKER_NAME = os.environ.get("WORKER_NAME", "worker")
# Имя агента меняется и может быть переиспользовано; id — нет. Нужен там, где
# идентичность СОХРАНЯЕТСЯ и сравнивается позже: держатель тест-лока (#82).
SESSION_ID = os.environ.get("ORCHESTRA_SESSION_ID", "")
PARENT_NAME = os.environ.get("PARENT_NAME", "")
_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
_MCP_PROOF = os.environ.get("ORCHESTRA_MCP_PROOF", "")
ACCESS_MODE = os.environ.get("ORCHESTRA_ACCESS_MODE", "full").strip().lower()
# Backend plants this nonce in our env. We write a proof file so Grok's same-name
# MCP merge cannot pass off a foreign `orchestra` server as ours.
ORCHESTRA_MCP_CANARY_ENV = "ORCHESTRA_MCP_CANARY"
_ORCHESTRA_MCP_CANARY_RE = re.compile(r"^[0-9a-f]{32}$")


def mcp_canary_proof_path(nonce: str) -> Path:
    return Path(tempfile.gettempdir()) / f"orchestra-mcp-canary-{nonce}"


def publish_mcp_identity_canary(environ: dict[str, str] | None = None) -> Path | None:
    """Prove this process is Orchestra's mcp_stdio, not a same-name impostor.

    Returns the proof path, or None when no canary was planted (non-Grok launch).
    """
    env = os.environ if environ is None else environ
    nonce = str(env.get(ORCHESTRA_MCP_CANARY_ENV) or "").strip()
    if not nonce:
        return None
    if not _ORCHESTRA_MCP_CANARY_RE.fullmatch(nonce):
        raise RuntimeError("ORCHESTRA_MCP_CANARY is not a 32-char hex nonce")
    path = mcp_canary_proof_path(nonce)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(nonce, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path

READ_ONLY_MCP_TOOLS = frozenset({
    "test_lock_status",
    "list_agents",
    "list_orchestrators",
    "get_worker_logs",
    "check_conflict",
    "worker_wip",
    "get_worker_info",
    "task_list",
    "task_get",
    "bg_list",
    "search_memory",
    "delivery_status",
    "message_delivery_status",
    "file_delivery_status",
})

REDUCER_MCP_TOOLS = frozenset({
    "send_message",
    "update_progress",
    "list_agents",
    "search_memory",
})


@dataclass
class ApiToolError(RuntimeError):
    code: str
    message: str
    status: int | None = None
    retryable: bool = False
    request_id: str | None = None
    retry_after_seconds: int | float | None = None
    outcome_unknown: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    result: Any = None

    def __post_init__(self) -> None:
        self.message = self.message.strip() or self.code or "ApiToolError"
        RuntimeError.__init__(self, self.message)

    def envelope(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "status": self.status,
            "retryable": self.retryable,
            "request_id": self.request_id,
            "retry_after_seconds": self.retry_after_seconds,
            "outcome_unknown": self.outcome_unknown,
            "details": self.details,
        }


def _canonical_error(error: ApiToolError | dict[str, Any]) -> dict[str, Any]:
    source = error.envelope() if isinstance(error, ApiToolError) else error
    details = source.get("details")
    if not isinstance(details, dict):
        details = {"value": details}
    code = str(source.get("code") or "tool_error")
    message = _safe_response_text(str(source.get("message") or code).strip() or code)
    outcome_unknown = bool(source.get("outcome_unknown", False))
    return {
        "code": code,
        "message": message,
        "status": source.get("status") if isinstance(source.get("status"), int) else None,
        "retryable": bool(source.get("retryable", False)) and not outcome_unknown,
        "request_id": str(source["request_id"]) if source.get("request_id") else None,
        "retry_after_seconds": _retry_after_seconds(source.get("retry_after_seconds")),
        "outcome_unknown": outcome_unknown,
        "details": _safe_detail(details),
    }


def mcp_tool_result(
    result: Any = None,
    *,
    error: ApiToolError | dict[str, Any] | None = None,
    is_error: bool = False,
    text: str = "",
) -> CallToolResult:
    """Build the shared shape; partial domain results may carry error with isError false."""
    if is_error and error is None:
        raise ValueError("is_error=True requires an error envelope")
    envelope = _canonical_error(error) if error is not None else None
    if not text:
        if envelope:
            text = f"{envelope['code']}: {envelope['message']}"
        elif isinstance(result, str):
            text = result
        else:
            text = json.dumps(result, ensure_ascii=False)
    if envelope:
        text = _safe_response_text(text)
    return CallToolResult(
        content=[TextContent(type="text", text=text or "OK")],
        structuredContent={"result": result, "error": envelope},
        isError=is_error,
    )


def _find_api_tool_error(exc: BaseException) -> ApiToolError | None:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ApiToolError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _root_exception(exc: BaseException) -> BaseException:
    seen: set[int] = set()
    current = exc
    while id(current) not in seen:
        seen.add(id(current))
        next_exc = current.__cause__ or current.__context__
        if next_exc is None:
            break
        current = next_exc
    return current


def _result_from_content(content: list[Any]) -> Any:
    if len(content) != 1 or not isinstance(content[0], TextContent):
        return None
    text = content[0].text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


class OrchestraMCP(FastMCP):
    async def call_tool(self, name: str, arguments: dict[str, Any]):
        try:
            converted = await super().call_tool(name, arguments)
        except Exception as exc:
            error = _find_api_tool_error(exc)
            if error is None:
                root = _root_exception(exc)
                error = ApiToolError(
                    code="tool_error",
                    message=err_text(root),
                    details={"exception_type": type(root).__name__, "tool": name},
                )
            envelope = _canonical_error(error)
            logger.warning(
                "MCP tool %s failed: code=%s request_id=%s message=%s",
                name,
                envelope["code"],
                envelope["request_id"],
                envelope["message"],
            )
            return mcp_tool_result(
                result=error.result,
                error=envelope,
                is_error=True,
            )

        if isinstance(converted, CallToolResult):
            structured = converted.structuredContent
            if isinstance(structured, dict) and "result" in structured and "error" in structured:
                raw_error = structured["error"]
                if raw_error is None and converted.isError:
                    text = "\n".join(
                        item.text for item in converted.content if isinstance(item, TextContent)
                    )
                    raw_error = ApiToolError(code="tool_error", message=text or "MCP tool failed")
                envelope = _canonical_error(raw_error) if raw_error is not None else None
                content = list(converted.content)
                if envelope:
                    content = [
                        item.model_copy(update={"text": _safe_response_text(item.text)})
                        if isinstance(item, TextContent)
                        else item
                        for item in content
                    ]
                return CallToolResult(
                    content=content,
                    structuredContent={"result": structured["result"], "error": envelope},
                    isError=converted.isError,
                )
            result = structured if structured is not None else _result_from_content(list(converted.content))
            if converted.isError:
                text = "\n".join(
                    item.text for item in converted.content if isinstance(item, TextContent)
                )
                error = ApiToolError(code="tool_error", message=text or "MCP tool failed")
                return mcp_tool_result(result=result, error=error, is_error=True, text=text)
            return CallToolResult(
                content=list(converted.content),
                structuredContent={"result": result, "error": None},
                isError=False,
            )

        if isinstance(converted, tuple):
            content, structured = converted
            tool = self._tool_manager.get_tool(name)
            if (
                tool is not None
                and tool.fn_metadata.wrap_output
                and isinstance(structured, dict)
                and set(structured) == {"result"}
            ):
                result = structured["result"]
            else:
                result = structured
            return CallToolResult(
                content=list(content),
                structuredContent={"result": result, "error": None},
                isError=False,
            )

        content = list(converted)
        return CallToolResult(
            content=content,
            structuredContent={"result": _result_from_content(content), "error": None},
            isError=False,
        )


mcp = OrchestraMCP("orchestra")


def _tool_names_for_access_mode(names: set[str], mode: str) -> set[str]:
    normalized = mode.strip().lower()
    if normalized in {"read-only", "readonly", "read"}:
        return names & READ_ONLY_MCP_TOOLS
    if normalized == "reducer":
        return names & REDUCER_MCP_TOOLS
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
    headers = {}
    if _INTERNAL_TOKEN:
        headers["Authorization"] = f"Bearer {_INTERNAL_TOKEN}"
    if SESSION_ID:
        headers["X-Orchestra-Session-Id"] = SESSION_ID
    if _MCP_PROOF:
        headers["X-Orchestra-Mcp-Proof"] = _MCP_PROOF
    return headers


def _retry_after_seconds(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return int(parsed) if parsed.is_integer() else parsed


_SENSITIVE_DETAIL_KEYS = ("authorization", "token", "password", "secret", "api_key", "api-key")


def _safe_detail(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(key): (
                "[redacted]"
                if any(marker in str(key).lower() for marker in _SENSITIVE_DETAIL_KEYS)
                else _safe_detail(item, depth + 1)
            )
            for key, item in list(value.items())[:50]
        }
    if isinstance(value, list):
        return [_safe_detail(item, depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return _safe_response_text(value)
    return value


def _safe_response_text(value: str) -> str:
    text = re.sub(
        r"(?i)\b(Bearer|Basic)\s+[^\s,;}\]]+",
        r"\1 [redacted]",
        value[:4000],
    )
    text = re.sub(
        r"(?i)((?:authorization|token|password|secret|api[_-]?key)[\"']?\s*[:=]\s*)"
        r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^,;}&\r\n]+)",
        r"\1[redacted]",
        text,
    )
    return text[:1000]


def _response_error(
    method: str,
    path: str,
    response: httpx.Response,
    payload: Any,
    request_id: str,
) -> ApiToolError:
    body = payload if isinstance(payload, dict) else {}
    raw_error = body.get("error")
    server_error = raw_error if isinstance(raw_error, dict) else {}

    message_value: Any = None
    if isinstance(raw_error, str):
        message_value = raw_error
    elif server_error:
        message_value = server_error.get("message") or server_error.get("detail")
    if message_value is None:
        message_value = body.get("message") or body.get("detail")
    if message_value is None and not isinstance(payload, dict):
        message_value = _safe_response_text(response.text)
    if isinstance(message_value, str):
        message = _safe_response_text(message_value.strip())
    elif message_value is not None:
        message = json.dumps(message_value, ensure_ascii=False)[:1000]
    else:
        message = ""
    if not message:
        message = f"HTTP {response.status_code}" if response.status_code >= 400 else "API returned an error"

    if server_error.get("code"):
        code = str(server_error["code"])
    elif body.get("code"):
        code = str(body["code"])
    elif response.status_code == 429:
        code = "http_429"
    elif response.status_code >= 500:
        code = "http_5xx"
    elif response.status_code >= 400:
        code = "http_4xx"
    else:
        code = "domain_error"

    response_request_id = (
        server_error.get("request_id")
        or body.get("request_id")
        or response.headers.get("X-Request-ID")
        or response.headers.get("X-Correlation-ID")
        or request_id
    )
    retry_after = _retry_after_seconds(
        server_error.get("retry_after_seconds")
        or body.get("retry_after_seconds")
        or response.headers.get("Retry-After")
    )
    transient_status = response.status_code in {408, 425, 429} or response.status_code >= 500
    outcome_unknown = method != "GET" and response.status_code >= 500
    if isinstance(server_error.get("outcome_unknown"), bool):
        outcome_unknown = server_error["outcome_unknown"]
    retryable = method == "GET" and transient_status
    if isinstance(server_error.get("retryable"), bool):
        retryable = server_error["retryable"]
    if outcome_unknown:
        retryable = False

    details: dict[str, Any] = {"method": method, "path": path}
    server_details = server_error.get("details")
    if isinstance(server_details, dict):
        details["server"] = _safe_detail(server_details)
    elif response.text:
        details["response_body"] = _safe_response_text(response.text)
    return ApiToolError(
        code=code,
        message=message,
        status=response.status_code,
        retryable=retryable,
        request_id=str(response_request_id),
        retry_after_seconds=retry_after,
        outcome_unknown=outcome_unknown,
        details=details,
        result=body.get("result"),
    )


def _transport_error(
    method: str,
    path: str,
    exc: httpx.RequestError,
    request_id: str,
) -> ApiToolError:
    connect_failure = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
    no_request_sent = connect_failure or isinstance(exc, httpx.PoolTimeout)
    timeout = isinstance(exc, httpx.TimeoutException)
    return ApiToolError(
        code="connect_error" if connect_failure else ("transport_timeout" if timeout else "transport_error"),
        message=err_text(exc),
        retryable=method == "GET" or no_request_sent,
        request_id=request_id,
        outcome_unknown=method != "GET" and not no_request_sent,
        details={
            "method": method,
            "path": path,
            "exception_type": type(exc).__name__,
            "request_not_sent": no_request_sent,
        },
    )


async def _api(method: str, path: str, **kwargs) -> dict | list | None:
    # New client per call: avoids shared state across tool invocations in the same MCP session
    method = method.upper()
    request_id = str(kwargs.pop("request_id", "") or uuid.uuid4().hex)
    idempotency_key = str(kwargs.pop("idempotency_key", "") or "")
    if method not in {"GET", "POST", "PUT", "DELETE"}:
        raise ApiToolError(
            code="unsupported_method",
            message=f"Unsupported HTTP method: {method}",
            request_id=request_id,
            details={"method": method, "path": path},
        )
    t = kwargs.pop("timeout", 30)
    headers = _auth_headers()
    headers["X-Request-ID"] = request_id
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        async with httpx.AsyncClient(base_url=ORCHESTRA_URL, timeout=t, headers=headers) as client:
            if method == "GET":
                response = await client.get(path, params=kwargs.get("params"))
            elif method == "POST":
                response = await client.post(path, json=kwargs.get("json"))
            elif method == "PUT":
                response = await client.put(path, json=kwargs.get("json"), params=kwargs.get("params"))
            else:
                response = await client.delete(path, params=kwargs.get("params"))
    except httpx.RequestError as exc:
        raise _transport_error(method, path, exc, request_id) from exc

    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        if response.status_code >= 400:
            raise _response_error(method, path, response, None, request_id) from exc
        raise ApiToolError(
            code="invalid_response",
            message=f"Invalid JSON response (status={response.status_code})",
            status=response.status_code,
            retryable=False,
            request_id=(response.headers.get("X-Request-ID") or request_id),
            outcome_unknown=method != "GET",
            details={
                "method": method,
                "path": path,
                "response_body": _safe_response_text(response.text),
                "exception_type": type(exc).__name__,
            },
        ) from exc

    if response.status_code >= 400:
        raise _response_error(method, path, response, payload, request_id)
    if isinstance(payload, dict) and payload.get("error") is not None:
        raise _response_error(method, path, response, payload, request_id)
    return payload


def _spawn_delivery_error(
    name: str,
    mapping: dict[str, str],
    cause: ApiToolError,
    *,
    task: str,
    delivery_id: str,
) -> ApiToolError:
    if cause.code == "IDEMPOTENCY_CONFLICT" or cause.status == 409:
        next_action = {
            "code": "RESOLVE_IDEMPOTENCY_CONFLICT",
            "tool": "delivery_status",
            "arguments": {"delivery_id": delivery_id},
            "message": (
                "This delivery id belongs to another payload; inspect it and do not retry "
                "the changed task."
            ),
        }
        delivery = "failed"
    elif cause.outcome_unknown:
        delivery = "unknown"
        next_action = {
            "code": "CHECK_DELIVERY_STATUS",
            "tool": "delivery_status",
            "arguments": {"delivery_id": delivery_id},
            "message": "Check this delivery id; do not resend the task with a new id.",
        }
    elif (
        cause.code == "DELIVERY_ACCEPT_REJECTED" and cause.status == 503
    ) or cause.details.get("request_not_sent") is True or cause.code == "connect_error":
        delivery = "failed"
        next_action = {
            "code": "RETRY_SAME_DELIVERY",
            "tool": "retry_initial_delivery",
            "arguments": {"name": name, "task": task, "delivery_id": delivery_id},
            "message": "Retry only this delivery id; do not create a new logical task.",
        }
    else:
        delivery = "failed"
        next_action = {
            "code": "RESOLVE_DELIVERY_REJECTION",
            "message": "Resolve this typed delivery rejection; do not resend automatically.",
        }
    result = {
        "worker_name": name,
        "created": True,
        "delivery": delivery,
        "delivery_id": delivery_id,
        **mapping,
        "next_action": next_action,
    }
    details = dict(cause.details)
    details.update({"phase": "initial_task_delivery", "next_action": next_action})
    return ApiToolError(
        code=cause.code,
        message=f"Worker '{name}' was created, but initial task delivery {delivery}: {cause.message}",
        status=cause.status,
        retryable=False,
        request_id=cause.request_id,
        retry_after_seconds=cause.retry_after_seconds,
        outcome_unknown=cause.outcome_unknown,
        details=details,
        result=result,
    )


def _delivery_payload(
    name: str,
    task: str,
    delivery_id: str,
    scope: str,
) -> dict[str, str]:
    return {
        "delivery_id": delivery_id,
        "message": task,
        "scope": scope,
        "sender": WORKER_NAME,
    }


def _delivery_status_path(delivery_id: str) -> str:
    return f"/api/initial-deliveries/{delivery_id}"


def _message_delivery_status_path(delivery_id: str) -> str:
    return f"/api/message-deliveries/{delivery_id}"


def _file_delivery_status_path(event_id: str) -> str:
    return f"/api/tg/file-deliveries/{event_id}"


def _delivery_receipt_text(
    name: str,
    model: str,
    mapping: dict[str, str],
    delivery: dict[str, Any],
) -> str:
    delivery_id = str(delivery.get("delivery_id") or "?")
    state = str(delivery.get("delivery_state") or delivery.get("state") or "UNKNOWN")
    status_url = str(delivery.get("status_url") or _delivery_status_path(delivery_id))
    out = (
        f"Worker '{name}' spawned. Model: {model}. Task accepted. "
        f"delivery_id={delivery_id}; state={state}. "
        f"Check delivery status with delivery_status('{delivery_id}') or GET {status_url}."
    )
    out += (
        f"\nWorktree: {mapping['worktree_path']}"
        f"\nRepository: {mapping['repo_path']}"
        f"\nGit common dir: {mapping['git_common_dir']}"
        f"\nBranch: {mapping['branch']}"
    )
    return out


def _is_delivery_receipt(value: Any, delivery_id: str) -> bool:
    return (
        isinstance(value, dict)
        and value.get("delivery_id") == delivery_id
        and bool(value.get("delivery_state") or value.get("state"))
    )


def _normalize_delivery_receipt(
    value: Any,
    delivery_id: str,
    *,
    require_state: bool = True,
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("ok") is not True:
        return None
    response_delivery_id = value.get("delivery_id")
    if response_delivery_id is not None and response_delivery_id != delivery_id:
        return None
    delivery_state = value.get("delivery_state") or value.get("state")
    if require_state and not delivery_state:
        return None
    return {
        **value,
        "delivery_id": response_delivery_id or delivery_id,
        "delivery_state": delivery_state or "UNKNOWN",
    }


async def _reconcile_initial_delivery(
    cause: ApiToolError,
    delivery_id: str,
    scope: str,
    *,
    allow_legacy_status: bool = False,
) -> tuple[dict[str, Any] | None, ApiToolError]:
    is_conflict = cause.code == "IDEMPOTENCY_CONFLICT" or cause.status == 409
    should_reconcile = (
        not is_conflict and cause.outcome_unknown
        or (cause.status is not None and cause.status >= 500
            and not is_conflict
            and not (cause.code == "DELIVERY_ACCEPT_REJECTED"
                     and cause.status == 503
                     and not cause.outcome_unknown))
    )
    if not should_reconcile:
        return None, cause
    try:
        status = await _api(
            "GET", _delivery_status_path(delivery_id), params={"scope": scope},
        )
    except ApiToolError as status_error:
        reconciliation: Any = status_error.envelope()
    else:
        if _is_delivery_receipt(status, delivery_id):
            return status, cause
        if allow_legacy_status:
            status_receipt = _normalize_delivery_receipt(
                status, delivery_id, require_state=False,
            )
            if status_receipt is not None:
                return status_receipt, cause
        reconciliation = {"status": "missing", "response": status}
    details = dict(cause.details)
    details["reconciliation"] = reconciliation
    return None, ApiToolError(
        code=cause.code,
        message=cause.message,
        status=cause.status,
        retryable=False,
        request_id=cause.request_id,
        retry_after_seconds=cause.retry_after_seconds,
        outcome_unknown=True,
        details=details,
    )


async def _post_initial_delivery(
    name: str,
    task: str,
    delivery_id: str,
    scope: str = SCOPE,
) -> dict[str, Any]:
    payload = _delivery_payload(name, task, delivery_id, scope)
    try:
        result = await _api(
            "POST", f"/api/sessions/{name}/initial-deliveries", json=payload,
        )
    except ApiToolError as cause:
        status, cause = await _reconcile_initial_delivery(cause, delivery_id, scope)
        if status is not None:
            return status
        raise cause
    if isinstance(result, dict) and result.get("error") is not None:
        raw_error = result["error"]
        if isinstance(raw_error, dict):
            cause = ApiToolError(
                code=str(raw_error.get("code") or "domain_error"),
                message=str(raw_error.get("message") or raw_error.get("detail") or "delivery rejected"),
                status=raw_error.get("status") if isinstance(raw_error.get("status"), int) else 200,
                retryable=bool(raw_error.get("retryable", False)),
                request_id=raw_error.get("request_id"),
                outcome_unknown=bool(raw_error.get("outcome_unknown", False)),
                details=raw_error.get("details") if isinstance(raw_error.get("details"), dict) else {},
            )
        else:
            cause = ApiToolError(
                code="domain_error",
                message=str(raw_error),
                status=200,
                retryable=False,
                outcome_unknown=False,
                details={"response": result},
            )
        status, cause = await _reconcile_initial_delivery(cause, delivery_id, scope)
        if status is not None:
            return status
        raise cause
    normalized = _normalize_delivery_receipt(result, delivery_id)
    if normalized is None:
        cause = ApiToolError(
            code="invalid_response",
            message="Initial delivery API returned an invalid acceptance receipt",
            status=200,
            outcome_unknown=True,
            details={"phase": "initial_task_delivery", "response": result},
        )
        status, cause = await _reconcile_initial_delivery(
            cause, delivery_id, scope, allow_legacy_status=True,
        )
        if status is not None:
            return status
        raise cause
    return normalized


# Server-owned default: Luna is always the Fast lane, and omitted-model reviews
# take it. Sol is an explicit, opt-in choice.
_CODEX_REVIEW_DEFAULT_MODEL = "gpt-5.6-luna"


def _resolve_codex_review_model(model: str) -> str:
    """Resolve registry aliases, then enforce the explicit-review runtime policy."""
    from app.models import get_model_spec, resolve_model
    from app.quota_gate import quota_bucket_for_model

    if not isinstance(model, str) or not model.strip():
        raise ApiToolError(
            code="invalid_argument",
            message="model must name a registered Codex reviewer",
            details={"field": "model"},
        )
    try:
        resolved = resolve_model(model)
    except ValueError as error:
        raise ApiToolError(
            code="invalid_argument",
            message=str(error),
            details={"field": "model", "requested_model": model},
        ) from error

    spec = get_model_spec(resolved)
    if spec.runtime != "codex":
        raise ApiToolError(
            code="invalid_argument",
            message=(
                f"model '{resolved}' uses runtime '{spec.runtime}'; "
                "codex_review requires a registered Codex-runtime model"
            ),
            details={
                "field": "model",
                "requested_model": model,
                "resolved_model": resolved,
                "runtime": spec.runtime,
            },
        )
    if quota_bucket_for_model(resolved) != "codex":
        raise ApiToolError(
            code="invalid_argument",
            message=(
                f"model '{resolved}' is not review-capable; "
                "Codex Spark is forbidden for review by policy"
            ),
            details={
                "field": "model",
                "requested_model": model,
                "resolved_model": resolved,
                "runtime": spec.runtime,
            },
        )
    return resolved


def _quota_refusal_from_readiness(model: str, readiness: object) -> ApiToolError | None:
    """Отказать только состоявшемуся блоку.

    Неизвестная и неразбираемая квота ПРОПУСКАЕТ — тем же сквозным решением, что и
    `app/quota_gate.require_worker_admission`: иначе разные точки одного правила
    расходятся, и ревью упирается в 429 там, где спавн прошёл (#227).
    """
    if not isinstance(readiness, dict) or readiness.get("state") != "blocked":
        return None
    label = str(readiness.get("provider_label") or readiness.get("provider") or "provider")
    utilization = readiness.get("utilization")
    if isinstance(utilization, bool) or not isinstance(utilization, (int, float)):
        return None
    return ApiToolError(
        code="weekly_quota_blocked",
        message=(
            f"New Codex worker turn blocked: {label} quota is {utilization:g}% — "
            f"{readiness.get('reason') or 'above the admission line'}. "
            "Stop/model change remain available."
        ),
        retryable=False,
        details={"model": model, **readiness},
    )


async def _quota_refusal(model: str) -> ApiToolError | None:
    """Consume the central worker admission decision; unknown fails open."""
    try:
        readiness = await _api("GET", "/api/usage/readiness", params={"model": model})
    except Exception as error:
        logger.warning(
            "quota readiness unavailable for %s; allowing: %s: %s",
            model, type(error).__name__, err_text(error),
        )
        return None
    return _quota_refusal_from_readiness(model, readiness)


def _cross_repo_note(scope: str, mapping: dict) -> str:
    """Предупреждение, когда воркер заведён в РЕПОЗИТОРИИ, отличном от проекта родителя.

    Сравнение идёт по git common dir, а не по строкам путей: worktree всегда лежит внутри
    каталога Orchestra, поэтому сравнение `worktree_path` со `scope` даёт ложные
    срабатывания на каждом обычном воркере.
    """
    if not scope:
        return ""
    common = str(mapping.get("git_common_dir") or "")
    if not common:
        return ""
    scope_git = os.path.join(scope.rstrip("/"), ".git")
    try:
        same = os.path.realpath(common) == os.path.realpath(scope_git)
    except OSError:
        same = common.rstrip("/") == scope_git
    if same:
        return ""
    return (
        f"⚠️ ДРУГОЙ РЕПОЗИТОРИЙ: воркер коммитит в {mapping.get('repo_path')}, "
        f"а проект этой сессии — {scope}. Это законно для портфеля из нескольких "
        "проектов, но помни: задачи и их номера остаются в проекте родителя, а "
        "merge_worker сливает ветку в main ТОГО репозитория, где воркер работает. "
        "Не сливай сюда чужую работу и не ищи её в проекте родителя."
    )


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
                       tg_topic: bool = False,
                       delivery_id: str = "") -> str:
    """Spawn a new worker agent in a git worktree. Model is REQUIRED — choose it by the `<model-routing>` block in your own prompt, which is the single source of truth for routing (model ids are deliberately not repeated here: a duplicated list rots).
    base_branch — от какой локальной ветки ответвить worktree. Пусто ("") = авто по
    стратегии пайплайна: parent → ветка родителя, main → проверяемый mainline репозитория.
    При неоднозначности spawn требует явную ветку.
    mcp_servers — JSON-объект с доп. MCP-серверами для воркера (формат как в .mcp.json: {"name": {"command": ..., "args": [...]}}). Мерджится с дефолтным Orchestra MCP; ключ "orchestra" игнорируется. Переживает рестарт.
    owned_dirs — JSON-массив директорий которыми владеет воркер, напр. ["app/api/", "app/models/"]. Инжектится в промпт воркера ("трогай только это"). Пересечение с owned_dirs другого живого воркера → БЛОК (spawn fails).
    tg_topic — если True, агент получит собственный TG топик для логов и сообщений."""
    if not model:
        raise ApiToolError(
            code="invalid_argument",
            message="model is required; choose it by the <model-routing> block in your prompt",
            details={"field": "model"},
        )
    scope = SCOPE or repo_path
    body = {
        "name": name, "scope": scope, "cwd": repo_path,
        "model": model, "system_prompt": system_prompt,
        "use_worktree": True, "repo_path": repo_path,
        "base_branch": base_branch,
        "role": role,
        "parent_name": WORKER_NAME,
        "planned_initial_turn": True,
        "initial_task_title": task,
    }
    if mcp_servers:
        import json
        try:
            parsed = json.loads(mcp_servers)
            if isinstance(parsed, dict):
                body["mcp_servers"] = parsed
            else:
                raise ApiToolError(
                    code="invalid_argument",
                    message="mcp_servers must be a JSON object",
                    details={"field": "mcp_servers"},
                )
        except json.JSONDecodeError as e:
            raise ApiToolError(
                code="invalid_argument",
                message=f"mcp_servers is not valid JSON: {e}",
                details={"field": "mcp_servers"},
            ) from e
    if owned_dirs:
        import json
        try:
            parsed = json.loads(owned_dirs)
            if isinstance(parsed, list):
                body["owned_dirs"] = parsed
            else:
                raise ApiToolError(
                    code="invalid_argument",
                    message="owned_dirs must be a JSON array",
                    details={"field": "owned_dirs"},
                )
        except json.JSONDecodeError as e:
            raise ApiToolError(
                code="invalid_argument",
                message=f"owned_dirs is not valid JSON: {e}",
                details={"field": "owned_dirs"},
            ) from e
    if task_id:
        body["task_id"] = task_id
    if description:
        body["description"] = description
    if tg_topic:
        body["tg_topic"] = True
    result = await _api("POST", "/api/sessions", json=body)
    if isinstance(result, dict) and result.get("error"):
        raise ApiToolError(code="domain_error", message=f"Spawn failed: {result['error']}")
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
        next_action = {
            "code": "INSPECT_BEFORE_RETRY",
            "message": "Inspect list_agents before retrying; creation outcome is unknown.",
        }
        raise ApiToolError(
            code="invalid_response",
            message=(
                "Malformed API response after session creation "
                f"(missing: {', '.join(missing)}); worker may have been created"
            ),
            status=200,
            outcome_unknown=True,
            details={"phase": "create", "missing": missing, "next_action": next_action},
            result={"worker_name": name, "created": "unknown", "next_action": next_action},
        )
    mapping_data = {field: result[field] for field in required}
    mapping = (
        f"Worktree: {mapping_data['worktree_path']}"
        f"\nRepository: {mapping_data['repo_path']}"
        f"\nGit common dir: {mapping_data['git_common_dir']}"
        f"\nBranch: {mapping_data['branch']}"
    )
    delivery_id = delivery_id.strip() if isinstance(delivery_id, str) else ""
    if not delivery_id:
        delivery_id = str(uuid.uuid4())
    try:
        # Предупреждение уходит и САМОМУ воркеру, а не только вызывающему: сегодня в
        # чужой репозиторий закоммитил именно ребёнок, который своего расхождения не знал.
        worker_task = task
        note_for_worker = _cross_repo_note(scope, mapping_data)
        if note_for_worker:
            worker_task = f"{task}\n\n{note_for_worker}"
        delivery = await _post_initial_delivery(name, worker_task, delivery_id, scope)
    except ApiToolError as exc:
        raise _spawn_delivery_error(
            name, mapping_data, exc, task=task, delivery_id=delivery_id,
        ) from exc
    out = _delivery_receipt_text(name, model, mapping_data, delivery)
    # Воркер заведён в ДРУГОМ репозитории, чем проект родителя. Это законно для портфеля
    # из нескольких проектов у одного оркестратора, но молчать нельзя: 28.08.2026 три
    # ребёнка отработали research по pitch-ball и закоммитили его в репозиторий
    # comfy-image-pipeline — расхождения не видел никто, ни родитель, ни дети.
    cross_repo = _cross_repo_note(scope, mapping_data)
    if cross_repo:
        out += f"\n{cross_repo}"
    if isinstance(result, dict) and result.get("spawn_warning"):
        out += f"\n⚠️ {result['spawn_warning']}"
    if isinstance(result, dict) and isinstance(result.get("task"), dict):
        out += f"\nTask: #{result['task'].get('par_number')} [{result['task'].get('status')}]"
    return out


@mcp.tool()
async def delivery_status(delivery_id: str) -> dict[str, Any]:
    """Look up one durable initial-task delivery by its immutable id."""
    delivery_id = delivery_id.strip() if isinstance(delivery_id, str) else ""
    if not delivery_id:
        raise ApiToolError(
            code="invalid_argument",
            message="delivery_id is required",
            details={"field": "delivery_id"},
        )
    result = await _api(
        "GET", _delivery_status_path(delivery_id), params={"scope": SCOPE},
    )
    if not isinstance(result, dict):
        raise ApiToolError(
            code="invalid_response",
            message="Delivery status API returned a non-object response",
            status=200,
            details={"response_type": type(result).__name__},
        )
    return result


@mcp.tool()
async def retry_initial_delivery(name: str, task: str, delivery_id: str) -> dict[str, Any]:
    """Retry one known-not-sent initial task, preserving its delivery id and payload key."""
    delivery_id = delivery_id.strip() if isinstance(delivery_id, str) else ""
    if not delivery_id:
        raise ApiToolError(
            code="invalid_argument",
            message="delivery_id is required; retry cannot mint a replacement key",
            details={"field": "delivery_id"},
        )
    return await _post_initial_delivery(name, task, delivery_id, SCOPE)


@mcp.tool()
async def acquire_test_lock(reason: str = "") -> str:
    """Захватить ГЛОБАЛЬНЫЙ эксклюзивный лок на ПОЛНЫЙ прогон тестов (фулл-сьют) для проекта.
    Бери его ТОЛЬКО перед полным прогоном и ТОЛЬКО с согласия PM. Узкие тесты этапа лока НЕ требуют.
    Занято другим агентом → вернётся отказ с именем держателя — НЕ запускай фулл-сьют, жди и попробуй позже.
    Всегда вызывай release_test_lock() после прогона."""
    result = await _api("POST", "/api/test-lock/acquire", json={
        "scope": SCOPE, "holder": WORKER_NAME, "reason": reason,
        "holder_session_id": SESSION_ID,
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
        "scope": SCOPE, "holder": WORKER_NAME, "holder_session_id": SESSION_ID,
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
async def send_message(to: str, message: str, delivery_id: str = "") -> str:
    """Send a message to any agent by name. Triggers a new turn."""
    delivery_id = delivery_id.strip() if isinstance(delivery_id, str) else ""
    if not delivery_id:
        delivery_id = str(uuid.uuid4())
    else:
        try:
            delivery_id = str(uuid.UUID(delivery_id))
        except ValueError as error:
            raise ApiToolError(
                code="invalid_argument",
                message="delivery_id must be a UUID",
                details={"field": "delivery_id"},
            ) from error
    payload = {
        "message": message,
        "sender": WORKER_NAME or ROLE,
        "scope": SCOPE,
        "delivery_id": delivery_id,
    }
    try:
        result = await _api("POST", f"/api/sessions/{to}/send", json=payload)
    except ApiToolError as cause:
        if not cause.outcome_unknown:
            raise
        try:
            status = await _api("GET", _message_delivery_status_path(delivery_id))
        except ApiToolError as status_error:
            if status_error.details.get("method") == "POST":
                raise cause from status_error
            raise _ambiguous_message_delivery_error(
                cause, delivery_id, status_error=status_error,
            ) from cause
        if not _is_message_delivery_receipt(status, delivery_id):
            raise _ambiguous_message_delivery_error(
                cause, delivery_id, status=status,
            ) from cause
        return _message_delivery_receipt_text(status)
    if isinstance(result, dict) and result.get("error"):
        return f"Send failed: {result['error']}"
    if _is_message_delivery_receipt(result, delivery_id):
        return _message_delivery_receipt_text(
            result, to=to, parent_name=result.get("parent_name", ""),
        )
    parent = result.get("parent_name", "") if isinstance(result, dict) else ""
    if parent and parent != WORKER_NAME:
        return f"Message sent to '{to}'\n⚠️ This worker belongs to '{parent}'. Consider messaging '{parent}' instead."
    return f"Message sent to '{to}'"


def _is_message_delivery_receipt(value: Any, delivery_id: str) -> bool:
    return (
        isinstance(value, dict)
        and value.get("ok") is True
        and value.get("delivery_id") == delivery_id
        and bool(value.get("acceptance"))
    )


def _message_delivery_receipt_text(
    receipt: dict[str, Any], *, to: str = "", parent_name: str = "",
) -> str:
    delivery_id = str(receipt["delivery_id"])
    state = str(receipt.get("delivery_state") or receipt.get("state") or "UNKNOWN")
    target = f" to '{to}'" if to else ""
    if state == "DELIVERY_UNKNOWN":
        error = receipt.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        code = str(code or "DELIVERY_OUTCOME_UNKNOWN")
        message = _safe_response_text(str(message or "Provider outcome is unknown"))
        output = (
            f"Message delivery outcome is unknown{target}; delivery_id={delivery_id}; "
            f"code={code}: {message}.\n"
            f"Check with message_delivery_status(delivery_id=\"{delivery_id}\") "
            "before acting; if retrying, reuse the same delivery_id and never use a new id."
        )
        if parent_name and parent_name != WORKER_NAME:
            output += (
                f"\n⚠️ This worker belongs to '{parent_name}'. "
                f"Consider messaging '{parent_name}' instead."
            )
        return output
    output = f"Message accepted{target}; delivery_id={delivery_id}; state={state}."
    if parent_name and parent_name != WORKER_NAME:
        output += (
            f"\n⚠️ This worker belongs to '{parent_name}'. "
            f"Consider messaging '{parent_name}' instead."
        )
    return output


def _ambiguous_message_delivery_error(
    cause: ApiToolError,
    delivery_id: str,
    *,
    status: Any = None,
    status_error: ApiToolError | None = None,
) -> ApiToolError:
    reconciliation: Any
    if status_error is not None:
        reconciliation = status_error.envelope()
    else:
        reconciliation = {"status": "missing", "response": status}
    next_action = {
        "tool": "message_delivery_status",
        "arguments": {"delivery_id": delivery_id},
        "message": (
            "Delivery outcome is ambiguous; inspect this delivery id or retry only "
            "with the same id. Do not retry with a new id."
        ),
    }
    details = dict(cause.details)
    details["reconciliation"] = reconciliation
    return ApiToolError(
        code=cause.code,
        message=f"Message delivery outcome is ambiguous: {cause.message}",
        status=cause.status,
        retryable=False,
        request_id=cause.request_id,
        retry_after_seconds=cause.retry_after_seconds,
        outcome_unknown=True,
        details=details,
        result={
            "acceptance": "AMBIGUOUS",
            "delivery_id": delivery_id,
            "next_action": next_action,
        },
    )


@mcp.tool()
async def message_delivery_status(delivery_id: str) -> dict[str, Any]:
    """Look up one direct-message delivery by its immutable id."""
    delivery_id = delivery_id.strip() if isinstance(delivery_id, str) else ""
    if not delivery_id:
        raise ApiToolError(
            code="invalid_argument",
            message="delivery_id is required",
            details={"field": "delivery_id"},
        )
    try:
        delivery_id = str(uuid.UUID(delivery_id))
    except ValueError as error:
        raise ApiToolError(
            code="invalid_argument",
            message="delivery_id must be a UUID",
            details={"field": "delivery_id"},
        ) from error
    result = await _api("GET", _message_delivery_status_path(delivery_id))
    if not isinstance(result, dict):
        raise ApiToolError(
            code="invalid_response",
            message="Message delivery status API returned a non-object response",
            status=200,
            details={"response_type": type(result).__name__},
        )
    return result


@mcp.tool()
async def open_fan(children: list[str], deadline_seconds: float = 1800.0,
                   reducer: str = "") -> str:
    """Low-level compatibility entry: open a barrier without launching workers.

    Prefer ``run_fan``: it opens the barrier before launch and owns spawn/reuse plumbing.
    This tool remains for old connected clients and specialized reducers.
    """
    kids = [c for c in (children or []) if isinstance(c, str) and c.strip()]
    if len(kids) < 2:
        return "open_fan needs at least 2 children; for one child just wait for its report."
    fan_id = f"{WORKER_NAME or ROLE}-{uuid.uuid4().hex[:8]}"
    result = await _api("POST", "/api/fan/open", json={
        "fan_id": fan_id,
        "parent_name": WORKER_NAME or ROLE,
        "scope": SCOPE,
        "children": kids,
        "deadline_seconds": deadline_seconds,
        "reducer": reducer,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"open_fan failed: {result['error']}"
    return (f"Fan '{fan_id}' open for {len(kids)} children (deadline {deadline_seconds}s). "
            f"END YOUR TURN NOW — you will be woken once, when the last child reports.")


def _fan_task(spec: object) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ApiToolError(code="invalid_argument", message="each tasks item must be an object")
    required = ("name", "model", "role", "task", "owned_dirs")
    missing = [key for key in required if key not in spec]
    if missing:
        raise ApiToolError(
            code="invalid_argument",
            message=f"fan task is missing: {', '.join(missing)}",
        )
    normalized = {key: spec[key] for key in required}
    if not all(
        isinstance(normalized[key], str) and normalized[key].strip()
        for key in ("name", "model", "role", "task")
    ):
        raise ApiToolError(
            code="invalid_argument",
            message="fan task name, model, role, and task must be non-empty strings",
        )
    owned_dirs = normalized["owned_dirs"]
    if not isinstance(owned_dirs, list) or not all(
        isinstance(path, str) and path.strip() for path in owned_dirs
    ):
        raise ApiToolError(
            code="invalid_argument",
            message="fan task owned_dirs must be a list of non-empty strings",
        )
    normalized["owned_dirs"] = owned_dirs
    return normalized


def _fan_reuse(spec: object) -> dict[str, str]:
    if not isinstance(spec, dict):
        raise ApiToolError(code="invalid_argument", message="each reuse item must be an object")
    name = spec.get("name")
    message = spec.get("message")
    if not isinstance(name, str) or not name.strip():
        raise ApiToolError(code="invalid_argument", message="reuse name must be non-empty")
    if not isinstance(message, str) or not message.strip():
        raise ApiToolError(code="invalid_argument", message=f"reuse message for {name} is empty")
    return {"name": name.strip(), "message": message}


async def _mark_fan_launch_failed(fan_id: str, child: str, error: Exception) -> None:
    try:
        await _api("POST", "/api/fan/member/terminal", json={
            "fan_id": fan_id,
            "child": child,
            "state": "failed",
            "summary": f"launch failed: {type(error).__name__}: {err_text(error)}",
        })
    except Exception as mark_error:
        logger.error(
            "fan %s could not mark %s failed: %s: %s",
            fan_id, child, type(mark_error).__name__, err_text(mark_error),
        )


@mcp.tool()
async def run_fan(
    tasks: list[dict[str, Any]] | None = None,
    reuse: list[dict[str, Any]] | None = None,
    deadline_seconds: float = 1800.0,
    repo_path: str = "",
) -> str:
    """Start one completion fan without manual open/spawn/message plumbing.

    ``tasks`` items contain ``name``, ``model``, ``role``, ``task``, and
    ``owned_dirs``.  ``reuse`` items contain the name of an already-live idle worker
    and the message for its next turn.  The barrier opens before any child is started,
    stays durable until every child finishes (or the deadline expires), and wakes the
    caller once with the manifest.  Workers remain normal live workers afterward.

    ``repo_path`` — git-репозиторий для детей, как у ``spawn_worker``; пусто = scope
    вызывающего. Задавать ОБЯЗАТЕЛЬНО, когда задача правит другой репозиторий: без него
    дети создаются в scope родителя, их worktree уезжает в чужой проект, и работа потом
    не мержится (28.08.2026, `pitch-game`: три отработавших воркера легли в
    comfy-image-pipeline, `merge_worker` отвечал "task '1' not found in session project").
    """
    if not math.isfinite(deadline_seconds) or deadline_seconds <= 0:
        raise ApiToolError(
            code="invalid_argument",
            message="deadline_seconds must be finite and greater than zero",
        )
    spawned = [_fan_task(item) for item in (tasks or [])]
    reused = [_fan_reuse(item) for item in (reuse or [])]
    names = [item["name"] for item in spawned] + [item["name"] for item in reused]
    if len(names) < 2:
        raise ApiToolError(
            code="invalid_argument",
            message="run_fan needs at least two total workers",
        )
    if len(set(names)) != len(names):
        raise ApiToolError(code="invalid_argument", message="fan worker names must be unique")
    target_repo = (repo_path or "").strip() or SCOPE
    if spawned and not target_repo:
        raise ApiToolError(
            code="invalid_argument",
            message="run_fan cannot spawn without an Orchestra scope/repository path",
        )
    if reused:
        sessions = await _api("GET", "/api/sessions", params={"scope": SCOPE})
        live = {
            str(row.get("name")): row
            for row in sessions
            if isinstance(row, dict) and row.get("status") != "archived"
        } if isinstance(sessions, list) else {}
        invalid = [
            name for name in (item["name"] for item in reused)
            if name not in live
            or str(live[name].get("status") or "").lower() != "idle"
            or bool(live[name].get("is_orchestrator"))
        ]
        if invalid:
            raise ApiToolError(
                code="invalid_argument",
                message="reuse workers must be live, idle, non-orchestrators: "
                + ", ".join(invalid),
            )

    fan_id = f"{WORKER_NAME or ROLE}-{uuid.uuid4().hex[:8]}"
    opened = await _api("POST", "/api/fan/open", json={
        "fan_id": fan_id,
        "parent_name": WORKER_NAME or ROLE,
        "scope": SCOPE,
        "children": names,
        "deadline_seconds": deadline_seconds,
        "reducer": "",
    })
    if isinstance(opened, dict) and opened.get("error"):
        raise ApiToolError(code="domain_error", message=f"run_fan open failed: {opened['error']}")

    launched: list[str] = []
    failures: list[str] = []
    for item in spawned:
        try:
            await spawn_worker(
                name=item["name"],
                task=item["task"],
                repo_path=target_repo,
                model=item["model"],
                role=item["role"],
                owned_dirs=json.dumps(item["owned_dirs"], ensure_ascii=False),
            )
            launched.append(item["name"])
        except Exception as error:
            failures.append(f"{item['name']}: {type(error).__name__}: {err_text(error)}")
            if not isinstance(error, ApiToolError) or not error.outcome_unknown:
                await _mark_fan_launch_failed(fan_id, item["name"], error)
    for item in reused:
        try:
            await send_message(item["name"], item["message"])
            launched.append(item["name"])
        except Exception as error:
            failures.append(f"{item['name']}: {type(error).__name__}: {err_text(error)}")
            if not isinstance(error, ApiToolError) or not error.outcome_unknown:
                await _mark_fan_launch_failed(fan_id, item["name"], error)

    result = (
        f"Fan '{fan_id}' opened before launch; started {len(launched)}/{len(names)} workers "
        f"with deadline {deadline_seconds}s."
    )
    if failures:
        result += "\nLaunch failures:\n- " + "\n- ".join(failures)
    return result + "\nEND YOUR TURN NOW — the fan will wake you exactly once with its manifest."


_ORCH_ROLES = frozenset({"orchestrator", "sub-orchestrator"})


def _acceptance_command_from_caller(requested: str) -> str:
    """Кто пишет команду приёмки. Закрывает ЛЁГКИЙ путь: заполнить параметр
    `task_create`/`task_update` и закрыть свой пункт самообъявленным `true`.

    HTTP больше не верит одному INTERNAL_TOKEN + поддельному session-id:
    privileged-поля требуют MCP-proof (см. app/mcp_proof.py). НЕ закрывает
    агента с bash: ~/.orchestra/mcp-config, CODEX_HOME/*/config.toml,
    /proc/<mcp>/environ, прямой UPDATE по data/orchestra.db, правка
    app/acceptance.py. Против исполнителя, который целенаправленно обходит
    проверку, защиты нет — у него шелл под kesha с полным sudo, он и код
    проверки перепишет. bash/curl/SQL вне модели.
    """
    if ROLE not in _ORCH_ROLES:
        return ""
    return (requested or "").strip()


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
        raise ApiToolError(
            code="invalid_response",
            message="Session list API returned a non-list response",
            status=200,
            details={"response_type": type(sessions).__name__},
        )
    task_lines: list[str] = []
    if ROLE in _ORCH_ROLES:
        try:
            task_payload = await _api(
                "GET", "/api/tm/tasks", params={"project": SCOPE} if SCOPE else None,
            )
            tasks = (
                task_payload.get("tasks", [])
                if isinstance(task_payload, dict) else task_payload
            )
            if isinstance(tasks, list):
                active = [task for task in tasks if task.get("status") == "in_progress"]
                queued = [task for task in tasks if task.get("status") == "new"]
                shown = [*active, *queued[:5]]
                if shown:
                    task_lines.append("## Project tasks")
                    for task in shown:
                        number = task.get("par_number") or task.get("par") or "?"
                        status = str(task.get("status") or "?")
                        title = " ".join(str(task.get("title") or "(untitled)").split())
                        if len(title) > 120:
                            title = title[:117] + "…"
                        owner = str(task.get("worker_session_id") or "")
                        owner_suffix = f" | worker: {owner}" if owner else ""
                        task_lines.append(
                            f"• #{number} [{status}] {title}{owner_suffix}"
                        )
                    omitted = max(0, len(queued) - 5)
                    if omitted:
                        task_lines.append(
                            f"… {omitted} more new tasks; use task_list for the full queue."
                        )
        except ApiToolError as exc:
            logger.warning(
                "list_agents optional task view failed: %s: %s", exc.code, exc.message,
            )
    if not sessions and not task_lines:
        return "No agents"
    icon_warning = ""
    try:
        icons_data = await _api("GET", "/api/role-icons")
        if isinstance(icons_data, dict):
            _icons = icons_data
        else:
            _icons = {}
            icon_warning = (
                "⚠️ Role icons unavailable: invalid response "
                f"({type(icons_data).__name__}); using defaults."
            )
    except ApiToolError as exc:
        _icons = {}
        icon_warning = f"⚠️ Role icons unavailable: {exc.code}: {exc.message}; using defaults."
        logger.warning("list_agents optional role icons failed: %s", icon_warning)

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

    lines = [icon_warning] if icon_warning else []
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
    if task_lines:
        lines.extend(task_lines)
    return "\n".join(lines)


@mcp.tool()
async def list_orchestrators() -> str:
    """List ALL orchestrators across all projects. Use to find agents you can talk to from other projects."""
    orchs = await _api("GET", "/api/orchestrators")
    if not isinstance(orchs, list):
        raise ApiToolError(
            code="invalid_response",
            message="Orchestrator list API returned a non-list response",
            status=200,
            details={"response_type": type(orchs).__name__},
        )
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
    """Manually compact an idle worker's context. Codex compacts natively in the same thread;
    Claude creates a summary, reconnects fresh, and retains that handoff. This is a manual escape
    hatch, not the auto-compact policy. Returns the runtime result; may take 30-60s."""
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


def _is_file_delivery_receipt(value: Any, event_id: str) -> bool:
    return (
        isinstance(value, dict)
        and value.get("ok") is True
        and value.get("event_id") == event_id
        and bool(value.get("acceptance"))
        and bool(value.get("delivery_state"))
    )


def _is_legacy_file_delivery_success(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("ok") is True
        and type(value.get("message_id")) is int
        and value["message_id"] != 0
        and type(value.get("chat_id")) is int
        and value["chat_id"] != 0
    )


def _legacy_file_delivery_text(result: dict[str, Any]) -> str:
    return (
        "File sent via legacy synchronous route; "
        f"message_id={result['message_id']}; chat_id={result['chat_id']}. "
        "No durable event receipt exists."
    )


def _file_delivery_receipt_text(receipt: dict[str, Any]) -> str:
    event_id = str(receipt["event_id"])
    state = str(receipt.get("delivery_state") or "UNKNOWN")
    return (
        f"File accepted; event_id={event_id}; state={state}. "
        f"Check with file_delivery_status('{event_id}'); do not retry with a new id."
    )


def _file_batch_receipt_text(receipt: dict[str, Any]) -> str:
    event_id = str(receipt["event_id"])
    state = str(receipt.get("delivery_state") or "UNKNOWN")
    count = len(receipt.get("files") or [])
    return (
        f"Files accepted; event_id={event_id}; state={state}; {count} files. "
        f"Check with file_delivery_status('{event_id}'); do not retry with a new id."
    )


def _ambiguous_file_delivery_error(
    cause: ApiToolError,
    event_id: str,
    *,
    status: Any = None,
    status_error: ApiToolError | None = None,
) -> ApiToolError:
    reconciliation = (
        status_error.envelope()
        if status_error is not None
        else {"status": "missing", "response": status}
    )
    details = dict(cause.details)
    details["reconciliation"] = reconciliation
    return ApiToolError(
        code="FILE_DELIVERY_OUTCOME_UNKNOWN",
        message=(
            f"File delivery outcome is ambiguous for event_id={event_id}: "
            f"{cause.message}"
        ),
        status=cause.status,
        retryable=False,
        request_id=cause.request_id,
        retry_after_seconds=cause.retry_after_seconds,
        outcome_unknown=True,
        details=details,
        result={
            "event_id": event_id,
            "next_action": {
                "tool": "file_delivery_status",
                "arguments": {"event_id": event_id},
                "message": "Check this event id; never retry with a fresh id.",
            },
        },
    )


@mcp.tool()
async def file_delivery_status(event_id: str) -> dict[str, Any]:
    """Look up one durable Telegram file delivery by its immutable event id."""
    event_id = event_id.strip() if isinstance(event_id, str) else ""
    if not event_id:
        raise ApiToolError(
            code="invalid_argument",
            message="event_id is required",
            details={"field": "event_id"},
        )
    try:
        event_id = str(uuid.UUID(event_id))
    except ValueError as error:
        raise ApiToolError(
            code="invalid_argument",
            message="event_id must be a UUID",
            details={"field": "event_id"},
        ) from error
    result = await _api("GET", _file_delivery_status_path(event_id))
    if not isinstance(result, dict):
        raise ApiToolError(
            code="invalid_response",
            message="File delivery status API returned a non-object response",
            status=200,
            details={"response_type": type(result).__name__},
        )
    return result


@mcp.tool()
async def send_file(
    path: str,
    caption: str = "",
    as_document: bool = False,
    event_id: str = "",
) -> str:
    """Accept a file for durable Telegram delivery and return its status id."""
    event_id = event_id.strip() if isinstance(event_id, str) else ""
    if event_id:
        try:
            event_id = str(uuid.UUID(event_id))
        except ValueError as error:
            raise ApiToolError(
                code="invalid_argument",
                message="event_id must be a UUID",
                details={"field": "event_id"},
            ) from error
    else:
        event_id = str(uuid.uuid4())
    payload = {
        "path": path,
        "caption": caption,
        "scope": SCOPE,
        "sender": WORKER_NAME or ROLE,
        "as_document": as_document,
        "event_id": event_id,
    }
    try:
        result = await _api("POST", "/api/tg/send_file", json=payload, timeout=180)
    except ApiToolError as cause:
        if not cause.outcome_unknown and not (
            cause.status is not None and cause.status >= 500
        ):
            raise
        try:
            status = await _api("GET", _file_delivery_status_path(event_id))
        except ApiToolError as status_error:
            raise _ambiguous_file_delivery_error(
                cause, event_id, status_error=status_error,
            ) from cause
        if _is_file_delivery_receipt(status, event_id):
            return _file_delivery_receipt_text(status)
        raise _ambiguous_file_delivery_error(
            cause, event_id, status=status,
        ) from cause
    if _is_legacy_file_delivery_success(result):
        return _legacy_file_delivery_text(result)
    if not _is_file_delivery_receipt(result, event_id):
        raise ApiToolError(
            code="invalid_response",
            message=(
                "Send file API returned no matching durable receipt for "
                f"event_id={event_id}. Check file_delivery_status('{event_id}'); "
                "do not retry with a new id."
            ),
            status=200,
            outcome_unknown=True,
            details={"event_id": event_id, "response": result},
            result={
                "event_id": event_id,
                "next_action": {
                    "tool": "file_delivery_status",
                    "arguments": {"event_id": event_id},
                },
            },
        )
    return _file_delivery_receipt_text(result)


@mcp.tool()
async def send_files(
    paths: list[str],
    caption: str = "",
    as_document: bool = False,
    event_id: str = "",
) -> str:
    """Accept an ordered file batch for durable Telegram album delivery."""
    if (
        not isinstance(paths, list)
        or not paths
        or not all(isinstance(path, str) and path for path in paths)
    ):
        raise ApiToolError(
            code="invalid_argument",
            message="paths must be a non-empty string list",
            details={"field": "paths"},
        )
    event_id = event_id.strip() if isinstance(event_id, str) else ""
    if event_id:
        try:
            event_id = str(uuid.UUID(event_id))
        except ValueError as error:
            raise ApiToolError(
                code="invalid_argument",
                message="event_id must be a UUID",
                details={"field": "event_id"},
            ) from error
    else:
        event_id = str(uuid.uuid4())
    payload = {
        "paths": paths,
        "caption": caption,
        "scope": SCOPE,
        "sender": WORKER_NAME or ROLE,
        "as_document": as_document,
        "event_id": event_id,
    }
    try:
        result = await _api("POST", "/api/tg/send_file", json=payload, timeout=180)
    except ApiToolError as cause:
        if not cause.outcome_unknown and not (
            cause.status is not None and cause.status >= 500
        ):
            raise
        try:
            status = await _api("GET", _file_delivery_status_path(event_id))
        except ApiToolError as status_error:
            raise _ambiguous_file_delivery_error(
                cause, event_id, status_error=status_error,
            ) from cause
        if _is_file_delivery_receipt(status, event_id):
            return _file_batch_receipt_text(status)
        raise _ambiguous_file_delivery_error(
            cause, event_id, status=status,
        ) from cause
    if not _is_file_delivery_receipt(result, event_id):
        raise ApiToolError(
            code="invalid_response",
            message=(
                "Send files API returned no matching durable receipt for "
                f"event_id={event_id}. Check file_delivery_status('{event_id}'); "
                "do not retry with a new id."
            ),
            status=200,
            outcome_unknown=True,
            details={"event_id": event_id, "response": result},
            result={
                "event_id": event_id,
                "next_action": {
                    "tool": "file_delivery_status",
                    "arguments": {"event_id": event_id},
                },
            },
        )
    return _file_batch_receipt_text(result)


@mcp.tool()
async def publish_artifact(path: str, caption: str = "", ttl_seconds: int | None = None) -> str:
    """Publish a private immutable HTML artifact; document fallback stays explicit."""
    payload = {"path": path, "caption": caption}
    if ttl_seconds is not None:
        payload["ttl_seconds"] = ttl_seconds
    result = await _api("POST", "/api/artifacts/publish", json=payload)
    if isinstance(result, dict) and result.get("error"):
        raise ApiToolError(
            code="domain_error",
            message="Artifact link failed; use send_file(path, as_document=True)",
        )
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise ApiToolError(
            code="invalid_response",
            message="Artifact publication returned an invalid response; use send_file(path, as_document=True)",
            outcome_unknown=True,
        )
    return f"Artifact published (id={result.get('artifact_id', '?')}, expires_at={result.get('expires_at', '?')})."


@mcp.tool()
async def send_chart(kind: str, title: str, data: dict, caption: str = "") -> str:
    """Draw a chart from data and send it to the user's Telegram as a picture. One call.

    Use it when the point is a SHAPE the reader should see: before/after across several
    categories, values spanning orders of magnitude, a series over time, or a final state
    in 2-4 numbers. Do not use it for a single number, a yes/no verdict, a list of files
    or a status line — those read better as one line of text.

    title — the punchline in words. Do NOT put numbers about the data in it: the tool
    computes a factual line from what it actually drew and prints it under the title.

    kind and the shape of `data`:
      "bars"     — compare categories. Linear scale.
      "bars_log" — same, when values differ by 100× or more (log scale; zero renders as
                   an explicit "0", negatives are rejected).
        {"unit": "МБ", "categories": ["1 сут", "год"],
         "series": [{"name": "до", "values": [0.18, 4.25], "tone": "bad"},
                    {"name": "после", "values": [0.17, 0.86], "tone": "good"}]}
      "series"   — values over time; data gaps are detected and shaded, never bridged.
        {"unit": "%", "series": [{"name": "5h", "points": [["2026-08-01T10:00:00", 12.3]]}]}
      "cards"    — 2 to 4 big numbers as a final state. Values are strings.
        {"metrics": [{"label": "на диске", "value": "401", "note": "5.54 МБ"},
                     {"label": "в индексе", "value": "315", "tone": "bad"}]}

    tone is optional: "good" | "bad" | "neutral" (default: palette colour by index).
    Limits, enforced loudly: 2-8 categories, <=3 bar series, <=3 lines, <=4 cards.
    """
    from app.charts import ChartError, render_chart

    try:
        path = render_chart(kind, title, data)
    except ChartError as exc:
        raise ApiToolError(code="domain_error", message=f"Chart not drawn: {exc}")
    except Exception as exc:
        raise ApiToolError(
            code="render_failed",
            message=f"Chart render failed: {type(exc).__name__}: {exc}",
            details={"kind": kind},
        )
    try:
        sent = await send_file(path, caption or title)
    except ApiToolError as exc:
        # картинка нарисована и лежит на диске — путь обязан дойти до агента,
        # иначе работа потеряна из-за сбоя доставки
        exc.message = f"{exc.message} | chart kept at {path}"
        exc.details = {**exc.details, "chart_path": path}
        raise
    return f"{sent} | chart: {path}"


@mcp.tool()
async def notify_user(reason: str, project: str = "", kind: str = "legacy") -> str:
    """Дёрнуть юзера тегом в Telegram на границе ЭТОГО хода. Только для оркестраторов.

    Молчание — нормальный режим: без этого вызова тега не будет, и это не забывчивость.
    СНАЧАЛА recency gate: НЕ зови, если юзер сам начал текущий ход, написал сообщение
    во время хода или писал последние 10 минут. Он уже смотрит — обычного ответа достаточно.
    Зови после долгой/фоновой работы, когда юзер ушёл и должен вернуться: нужно его РЕШЕНИЕ
    (развилка, которую ты не вправе закрыть сам); ВЫВОД РАЗВЕРНУЛСЯ (сделали не то, о чём
    договаривались, или отозвано ранее сказанное); ИНЦИДЕНТ на живых системах; РЕЗУЛЬТАТ
    с числом, меняющий план. НЕ зови на блокеры ревью, мержи, статусы, промежуточные шаги,
    «воркер начал/закончил» — на это он смотреть не хочет.

    `reason` — одна короткая фраза, ЗАЧЕМ дёрнули; она уедет юзеру вместе с тегом.
    kind: legacy | incident | reversal | plan_change. Решения пользователя фиксируются
    только через project_wait — kind=waiting здесь запрещён. `project` опционален.
    Тег ставится один раз за ход, только после durable result marker.
    """
    reason = reason.strip()
    if not reason:
        return "notify_user needs a non-empty reason — one short phrase saying WHY."
    kind = kind.strip().casefold()
    if kind == "waiting":
        raise ValueError("Use project_wait for decisions; notify_user(kind='waiting') is forbidden")
    if kind not in {"legacy", "incident", "reversal", "plan_change"}:
        raise ValueError("kind must be legacy|incident|reversal|plan_change")
    project = project.strip()
    path = (
        f"/api/portfolio/projects/{project}/attention"
        if project
        else "/api/portfolio/attention"
    )
    result = await _api("POST", path, json={"reason": reason, "kind": kind})
    event_id = str(result.get("event_id") or "") if isinstance(result, dict) else ""
    if not event_id:
        raise ApiToolError(
            code="invalid_response",
            message="attention API returned no durable event id",
            status=200,
        )
    return f"ATTENTION_DURABLE:{event_id}\n{json.dumps(result, ensure_ascii=False)}"


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
    """Change an idle worker's model and start a fresh dialog on the target runtime."""
    result = await _api("POST", f"/api/sessions/{name}/change-model", json={"scope": SCOPE, "model": model, "fresh": True, "via": "mcp"})
    if isinstance(result, dict) and result.get("error"):
        return f"Model change failed: {result['error']}"
    if isinstance(result, dict) and result.get("changed"):
        return f"Model changed: {result.get('old_model')} → {result.get('model')}"
    return f"Model already {result.get('model', model)}"


def _merge_local_result(
    operation_id: str,
    state: str,
    *,
    code: str,
    message: str,
    retryable: bool,
    outcome_unknown: bool,
    target: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    envelope = _canonical_error({
        "code": code,
        "message": message or code,
        "status": None,
        "retryable": retryable,
        "request_id": operation_id,
        "retry_after_seconds": None,
        "outcome_unknown": outcome_unknown,
        "details": details,
    })
    return {
        "schema_version": 1,
        "operation_id": operation_id,
        "operation_state": state,
        "retryable": envelope["retryable"],
        "commit_point": "UNKNOWN" if outcome_unknown else "NOT_REACHED",
        "git": {
            "status": "UNKNOWN" if outcome_unknown else "NOT_STARTED",
            "target_branch": target,
            "target_before": None,
            "target_after": None,
            "worker_branch": "",
            "worker_head": None,
            "conflicts": [],
        },
        "task_links": {"status": "NOT_RUN", "items": {}},
        "rag": {"status": "NOT_RUN"},
        "lifecycle": {"status": "NOT_RUN"},
        "next_task": {"status": "NOT_REQUESTED"},
        "error": envelope,
        "next_action": {
            "code": "RECONCILE_SAME_OPERATION" if outcome_unknown else "RETRY_SAME_OPERATION",
            "message": (
                f"Check operation {operation_id} before any retry; do not merge manually."
                if outcome_unknown
                else f"Retry merge_worker with operation_id={operation_id}; do not merge manually."
            ),
        },
    }


def _merge_payload_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
        raise ValueError("merge operation response has no domain result")
    return payload["result"]


def _merge_tool_result(result: dict[str, Any]) -> CallToolResult:
    operation_id = str(result.get("operation_id") or "unknown")
    state = str(result.get("operation_state") or "UNKNOWN").upper()
    error = result.get("error")
    action = result.get("next_action") if isinstance(result.get("next_action"), dict) else {}
    action_message = _safe_response_text(str(action.get("message") or ""))
    if state in {"PENDING", "RUNNING"}:
        # a blocking reason (dirty tree, conflict) already sits in `error` — surfacing it
        # here saves the caller two blind retries before the cause finally shows up
        reason = ""
        if isinstance(error, dict):
            reason = str(error.get("message") or error.get("code") or "")
        elif error:
            reason = str(error)
        # Формулировка — это и есть фикс. Раньше здесь было сухое «RUNNING, retry with
        # the same operation_id», и агенты рапортовали «merge worker failed» на живом
        # мерже, который через секунды успешно завершался. Нетерминальное состояние
        # обязано читаться как «ещё идёт», а не как отказ, — причём с первой строки,
        # потому что дальше неё модель может и не дочитать.
        text = (
            f"STILL {state} — NOT a failure, nothing was lost, do NOT report an error. "
            f"Merge operation {operation_id} is still running on the server after "
            f"{int(_MERGE_WAIT_SECONDS)}s of waiting. "
            f"Current stage and elapsed time are reported in the progress fields. "
            f"Call merge_worker again with operation_id='{operation_id}' and the original "
            f"payload (including task_outcome, next_task_id, target, and waive_diff_budget) "
            f"to pick up this same operation; if the payload differs, the server rejects "
            f"it as a different merge request. "
            f"Do NOT start a new merge and do NOT merge manually. "
            f"If that call is refused because the worker moved to another branch, the "
            f"refusal names the actual branch — check worker_wip there and start a new "
            f"operation without operation_id."
            + (f" Server note: {_safe_response_text(reason)}" if reason else "")
        )
        progress = result.get("progress") if isinstance(result.get("progress"), dict) else {}
        if progress.get("stage"):
            elapsed = float(progress.get("elapsed_seconds") or 0)
            text += f" Current stage: {progress['stage']}; elapsed {elapsed:.0f}s."
        return mcp_tool_result(result, text=text)
    if state == "SUCCEEDED":
        git = result.get("git") if isinstance(result.get("git"), dict) else {}
        count = int(git.get("commits_merged") or 0)
        branch = git.get("worker_branch") or "?"
        # Про добавку оркестратор обязан узнать из ПЕРВЫХ строк, а не найти в полях потом.
        # Поля может не быть вовсе (старый сервер до рестарта) — тогда текст прежний.
        drift = ""
        if git.get("head_drift") == "BENIGN_ADVANCE":
            pinned = str(git.get("worker_head_pinned") or "?")[:12]
            merged_head = str(git.get("worker_head") or "?")[:12]
            drift = (
                f" NOTE: the worker committed after this operation was accepted — "
                f"merged its branch as of {merged_head}, not the pinned {pinned}."
            )
        # Предупреждение, не попавшее в первые строки, исчезает молча: структурный
        # результат читают не всегда, текст — всегда.
        warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
        notes = "; ".join(
            str(warning.get("message") or warning.get("code") or "")
            for warning in warnings if isinstance(warning, dict)
        )
        text = (
            f"Merged {count} commit{'s' if count != 1 else ''} from branch {branch}. "
            f"Operation {operation_id}: SUCCEEDED.{drift}"
            + (
                f" WARNINGS (the merge itself needs no retry): {_safe_response_text(notes)}"
                if notes else ""
            )
        )
        return mcp_tool_result(result, text=text)
    if state == "PARTIAL":
        message = ""
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "")
        text = (
            f"Merge operation {operation_id}: PARTIAL — "
            f"{_safe_response_text(message) or 'a post-merge stage failed'}. "
            f"{action_message or 'Finalize this same operation; do not merge manually.'}"
        )
        return mcp_tool_result(result, text=text)
    if state not in {"FAILED", "UNKNOWN"}:
        raise ValueError(f"unknown merge operation state: {state}")
    if not isinstance(error, dict):
        error = {
            "code": "UNKNOWN_OUTCOME" if state == "UNKNOWN" else "UPSTREAM_EMPTY_ERROR",
            "message": f"Merge operation {operation_id} returned {state} without error detail",
            "status": None,
            "retryable": False,
            "request_id": operation_id,
            "retry_after_seconds": None,
            "outcome_unknown": state == "UNKNOWN",
            "details": {"exception_type": "MissingMergeError"},
        }
        result = {**result, "error": error}
    message = _safe_response_text(str(error.get("message") or error.get("code") or "merge failed"))
    text = (
        f"Merge operation {operation_id}: {state} — {message}. "
        f"{action_message or 'Do not merge manually; follow next_action.'}"
    )
    return mcp_tool_result(result, error=error, is_error=True, text=text)


# Сколько ждать терминального состояния внутри ОДНОГО вызова merge_worker.
# Это ручка ЧАСТОТЫ, а не корректности: у времени операции длинный хвост, поэтому
# любой потолок рано или поздно будет превышен. Корректность держится на том, что
# нетерминальный ответ невозможно прочитать как отказ (см. _merge_tool_result), а
# не на угаданном числе. Замер 03.08 по 31 живой операции: все дошли до терминала,
# максимум 58.3 с. 90 с покрывает их все и вдвое ниже уже работающих в этом файле
# длинных вызовов (compact_worker=120 с, spawn=180 с).
_MERGE_WAIT_SECONDS = 90.0


async def _await_merge_terminal(operation_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Дождаться терминального состояния, чтобы один вызов давал один ответ.

    Прежний бюджет был 2 с (0.0+0.5+1.5), а 9 операций из 31 (29%) шли дольше —
    вызывающий получал RUNNING на РАБОТАЮЩЕМ мерже и рапортовал провал.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _MERGE_WAIT_SECONDS
    delay = 0.2
    while True:
        recovered = await _recover_merge_status(operation_id)
        if recovered is not None:
            result = recovered
            if result.get("operation_state") not in {"PENDING", "RUNNING"}:
                return result
        remaining = deadline - loop.time()
        if remaining <= 0:
            return result
        await asyncio.sleep(min(delay, remaining))
        delay = min(delay * 1.5, 2.0)


async def _recover_merge_status(operation_id: str) -> dict[str, Any] | None:
    try:
        payload = await _api("GET", f"/api/merge-operations/{operation_id}")
    except ApiToolError as lookup_error:
        if isinstance(lookup_error.result, dict):
            return lookup_error.result
        return None
    return _merge_payload_result(payload)


@mcp.tool()
async def merge_worker(
    name: str,
    target: str = "",
    next_task_id: str = "",
    operation_id: str = "",
    waive_diff_budget: bool = False,
    task_outcome: str = "",
) -> CallToolResult:
    """Durably squash a worker branch. Waits for the merge to finish and returns the outcome.

    A reply starting with "STILL RUNNING" is NOT a failure: the merge is still going on the
    server and nothing was lost. Call this tool again with the SAME operation_id to pick it
    up. Only FAILED / PARTIAL / UNKNOWN mean something went wrong.

    Reusing operation_id picks up THAT operation, not the worker's current state: if the
    worker moved to another branch meanwhile, the call is refused and names the actual
    branch — start a new operation without operation_id. Verifying what actually landed
    (target branch, worker_wip) is always expected and never counts as merging manually.

    waive_diff_budget: orchestrator-only. Skip the insertion ceiling for this merge.
    The result records diff_budget_waived so the bypass is visible after the fact.
    """
    if waive_diff_budget and ROLE not in _ORCH_ROLES:
        return mcp_tool_result(
            result={
                "operation_state": "FAILED",
                "error": {
                    "code": "DIFF_BUDGET_WAIVE_FORBIDDEN",
                    "message": "waive_diff_budget is orchestrator-only",
                },
            },
            error=ApiToolError(
                code="DIFF_BUDGET_WAIVE_FORBIDDEN",
                message="waive_diff_budget is orchestrator-only",
            ),
            is_error=True,
            text="waive_diff_budget is orchestrator-only",
        )
    operation_id = operation_id or str(uuid.uuid4())
    merge_schema_version: int | None = None
    if task_outcome:
        try:
            capability = await _api("GET", "/api/merge-operations/capabilities")
        except ApiToolError as capability_error:
            result = _merge_local_result(
                operation_id,
                "FAILED",
                code="MERGE_API_UPGRADE_REQUIRED",
                message=(
                    "Cannot verify task-lifecycle-v2 merge support; no merge was attempted."
                ),
                retryable=False,
                outcome_unknown=False,
                target=target,
                details={
                    "exception_type": type(capability_error).__name__,
                    **capability_error.details,
                },
            )
            return _merge_tool_result(result)
        capabilities = (
            capability.get("capabilities", [])
            if isinstance(capability, dict) else []
        )
        if (
            not isinstance(capability, dict)
            or capability.get("merge_schema_version") != 2
            or "task-lifecycle-v2" not in capabilities
        ):
            result = _merge_local_result(
                operation_id,
                "FAILED",
                code="MERGE_API_UPGRADE_REQUIRED",
                message=(
                    "The live server does not support task-lifecycle-v2; "
                    "no merge was attempted."
                ),
                retryable=False,
                outcome_unknown=False,
                target=target,
                details={"server_capability": capability},
            )
            return _merge_tool_result(result)
        merge_schema_version = 2
    body = {
        "operation_id": operation_id,
        "name": name,
        "scope": SCOPE,
        "target": target,
        "next_task_id": next_task_id,
        "waive_diff_budget": bool(waive_diff_budget),
        "waived_by": WORKER_NAME if waive_diff_budget else "",
    }
    if merge_schema_version is not None:
        body["merge_schema_version"] = merge_schema_version
        body["task_outcome"] = task_outcome
    try:
        try:
            payload = await _api("POST", "/api/merge-operations", json=body)
            result = _merge_payload_result(payload)
        except ApiToolError as api_error:
            if isinstance(api_error.result, dict):
                result = api_error.result
            elif api_error.status in {404, 426}:
                result = _merge_local_result(
                    operation_id,
                    "FAILED",
                    code="MERGE_API_UPGRADE_REQUIRED",
                    message=(
                        "Merge operation-v1 is unavailable in the live server; "
                        "restart Orchestra before merging. No legacy merge was attempted."
                    ),
                    retryable=False,
                    outcome_unknown=False,
                    target=target,
                    details={"exception_type": type(api_error).__name__, **api_error.details},
                )
            else:
                recovered = await _recover_merge_status(operation_id)
                if recovered is not None and recovered.get("operation_state") != "FAILED":
                    result = recovered
                else:
                    unknown = api_error.outcome_unknown
                    result = _merge_local_result(
                        operation_id,
                        "UNKNOWN" if unknown else "FAILED",
                        code="UNKNOWN_OUTCOME" if unknown else "TRANSPORT_ERROR",
                        message=(
                            f"Merge request failed and status could not be confirmed: "
                            f"{api_error.message or type(api_error).__name__}"
                        ),
                        retryable=not unknown and api_error.retryable,
                        outcome_unknown=unknown,
                        target=target,
                        details={"exception_type": type(api_error).__name__, **api_error.details},
                    )
        if result.get("operation_state") in {"PENDING", "RUNNING"}:
            result = await _await_merge_terminal(
                str(result.get("operation_id") or operation_id), result,
            )
        return _merge_tool_result(result)
    except Exception as exc:
        result = _merge_local_result(
            operation_id,
            "UNKNOWN",
            code="UNKNOWN_OUTCOME",
            message=f"Merge result handling failed: {err_text(exc)}",
            retryable=False,
            outcome_unknown=True,
            target=target,
            details={"exception_type": type(exc).__name__},
        )
        return _merge_tool_result(result)


@mcp.tool()
async def resolve_merge_operation(operation_id: str, reason: str) -> CallToolResult:
    """Close a PARTIAL/UNKNOWN merge operation you have already reconciled.

    This is the ONLY way to unblock merges for a worker held by such an operation.
    Reconcile FIRST (check what actually landed in the target branch), then call this
    with what you found in `reason`. The operation keeps its state as the record; only
    the block is lifted. SUCCEEDED/FAILED operations are refused — they block nothing.
    """
    body = {"reason": reason, "actor": "mcp"}
    try:
        payload = await _api(
            "POST", f"/api/merge-operations/{operation_id}/resolve", json=body,
        )
        result = _merge_payload_result(payload)
    except ApiToolError as api_error:
        if isinstance(api_error.result, dict):
            result = api_error.result
            error = result.get("error") if isinstance(result.get("error"), dict) else None
            resolution = result.get("resolution") if isinstance(result.get("resolution"), dict) else None
            if resolution is not None and result.get("operation_state") in {"PARTIAL", "UNKNOWN"}:
                if error is not None:
                    resolution = {**resolution, "previous_error": error}
                    result = {**result, "resolution": resolution}
                result.pop("error", None)
                return mcp_tool_result(
                    result,
                    text=(
                        f"Merge operation {operation_id} resolved (state stays "
                        f"{result.get('operation_state')}); merges for this worker are "
                        f"unblocked. Reason: {_safe_response_text(str(resolution.get('reason') or reason))}"
                    ),
                )
            message = str((error or {}).get("message") or api_error.message)
            return mcp_tool_result(
                result, error=error, is_error=True,
                text=f"Merge operation {operation_id} was not resolved: {message}",
            )
        if api_error.status == 404:
            # Роут живёт в памяти systemd до рестарта: старый сервер молча проигнорировал
            # бы запрос, и вызывающий решил бы, что снял блокировку.
            return mcp_tool_result(
                {"operation_id": operation_id, "resolved": False},
                error={
                    "code": "RESOLVE_API_UPGRADE_REQUIRED",
                    "message": (
                        "resolve route is unavailable in the live server; "
                        "the operation is still blocking"
                    ),
                    "status": api_error.status,
                    "retryable": False,
                    "request_id": operation_id,
                    "retry_after_seconds": None,
                    "outcome_unknown": False,
                    "details": {"method": "POST", "path": api_error.details.get("path", "")},
                },
                is_error=True,
                text=(
                    f"This Orchestra server cannot resolve merge operations yet "
                    f"(no /api/merge-operations/{{id}}/resolve route). Operation "
                    f"{operation_id} is still blocking; a server restart is required."
                ),
            )
        raise
    resolution = result.get("resolution") if isinstance(result.get("resolution"), dict) else {}
    state = str(result.get("operation_state") or "?")
    return mcp_tool_result(
        result,
        text=(
            f"Merge operation {operation_id} resolved (state stays {state}); merges for "
            f"this worker are unblocked. Reason: {_safe_response_text(str(resolution.get('reason') or reason))}"
        ),
    )


@mcp.tool()
async def switch_worker_branch(
    name: str,
    task_id: str,
    from_ref: str = "",
    force: bool = False,
    owned_dirs: str = "",
) -> str:
    """After merge, switch worker to a new branch for a new task.
    from_ref — optional local base override; empty uses the worker's persisted base.
    force=True explicitly discards committed content not verified in the base.
    owned_dirs — optional JSON array replacing the worker's ownership on a new task;
    omitted or [] clears it.
    Worker must be idle with clean working tree."""
    payload = {
        "scope": SCOPE,
        "task_id": task_id,
        "from_ref": from_ref,
        "force": force,
    }
    if owned_dirs:
        try:
            parsed_owned_dirs = json.loads(owned_dirs)
        except (TypeError, ValueError) as error:
            return f"Switch failed: owned_dirs is not valid JSON: {error}"
        if not isinstance(parsed_owned_dirs, list):
            return "Switch failed: owned_dirs must be a JSON array"
        payload["owned_dirs"] = parsed_owned_dirs
    result = await _api("POST", f"/api/sessions/{name}/switch-branch",
                        json=payload)
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
    """Report an Orchestra platform bug immediately; do not ask for approval.

    ``description`` is complete only when it contains every field below:
    - Location: exact file:line, function, and commit.
    - Error (verbatim): original text; include stop_reason, HTTP/status code, or tool result.
    - Exception class: exact class ALWAYS (``N/A`` only when no exception object exists).
      Some exceptions such as ``httpx.ReadTimeout`` stringify to empty text.
    - Reproduction: exact steps or command.
    - Ruled out: checks already run and causes excluded.
    - Resource impact: turns/tokens/cost/counts, or N/A when none.
    - Environment: model, runtime, version/commit, and project.

    Missing trace = not reported. Project-code bugs go to ``docs/tasks/<id>/`` and
    the orchestrator instead of this tool.
    """
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


# Статусы, которыми владеет платформа: их ставит spawn/send/merge/archive, а не агент.
# Ручной `done` закрывал живые задачи и задачи чужих воркеров — это и есть забывчивость,
# которую #248 убирает. Человек и YouGile правят статус своим контуром, мимо этих тулов.
_PLATFORM_OWNED_STATUSES = frozenset({"in_progress", "done"})


def _reject_lifecycle_status(status: str, tool: str) -> None:
    if status.strip().lower() in _PLATFORM_OWNED_STATUSES:
        raise ApiToolError(
            code="lifecycle_platform_owned",
            message=(
                f"{tool}: status '{status}' is owned by the platform — it is set by "
                "spawn/send, merge_worker(task_outcome=...) and archive. Merge with "
                "task_outcome='complete' to close a task."
            ),
            status=409,
        )


async def _current_project_goal(project: str, goal_id: str = "") -> tuple[str, dict]:
    if goal_id.strip():
        return goal_id.strip(), {}
    current = await _api("GET", f"/api/portfolio/projects/{project}/goal")
    goal = current.get("goal") if isinstance(current, dict) else None
    if not isinstance(goal, dict) or not str(goal.get("id") or "").strip():
        raise ApiToolError(
            code="project_goal_missing",
            message=f"portfolio project '{project}' has no current goal",
            status=409,
        )
    return str(goal["id"]), goal


@mcp.tool()
async def project_goal(
    project: str,
    action: str = "get",
    objective: str = "",
    goal_id: str = "",
    note: str = "",
    watchdog_enabled: bool | None = None,
    stall_after_seconds: int = 0,
) -> str:
    """Read or advance a durable project-owned goal.

    Actions: get, set, progress, pause, resume, complete, cancel, watchdog.
    `set` needs objective. `progress` accepts note. Policy actions are owner-only;
    contributors may get/progress. The server atomically updates revision, generation
    and activity lease, which is why this is a tool rather than a file edit.
    """
    project = project.strip()
    action = action.strip().casefold()
    if not project:
        raise ApiToolError(code="invalid_argument", message="project is required")
    if action == "get":
        result = await _api("GET", f"/api/portfolio/projects/{project}/goal")
    elif action == "set":
        if not objective.strip():
            raise ApiToolError(code="invalid_argument", message="objective is required for set")
        body: dict[str, Any] = {"objective": objective.strip()}
        if watchdog_enabled is not None:
            body["watchdog_enabled"] = watchdog_enabled
        if stall_after_seconds > 0:
            body["stall_after_seconds"] = stall_after_seconds
        result = await _api("POST", f"/api/portfolio/projects/{project}/goals", json=body)
    elif action == "progress":
        resolved_goal_id, _goal = await _current_project_goal(project, goal_id)
        result = await _api(
            "POST",
            f"/api/portfolio/projects/{project}/goals/{resolved_goal_id}/progress",
            json={"note": note.strip()},
        )
    elif action in {"pause", "resume", "complete", "cancel", "watchdog"}:
        resolved_goal_id, _goal = await _current_project_goal(project, goal_id)
        if action == "watchdog":
            if watchdog_enabled is None and stall_after_seconds <= 0:
                raise ApiToolError(
                    code="invalid_argument",
                    message="watchdog needs watchdog_enabled or stall_after_seconds",
                )
            body = {}
            if watchdog_enabled is not None:
                body["watchdog_enabled"] = watchdog_enabled
            if stall_after_seconds > 0:
                body["stall_after_seconds"] = stall_after_seconds
        else:
            body = {
                "status": {
                    "pause": "paused",
                    "resume": "active",
                    "complete": "completed",
                    "cancel": "cancelled",
                }[action]
            }
        result = await _api(
            "PUT",
            f"/api/portfolio/projects/{project}/goals/{resolved_goal_id}",
            json=body,
        )
    else:
        raise ApiToolError(
            code="invalid_argument",
            message=(
                "unknown project_goal action; use get|set|progress|pause|resume|"
                "complete|cancel|watchdog"
            ),
        )
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def project_wait(
    project: str,
    action: str,
    question: str = "",
    wait_id: str = "",
    task_ref: str = "",
) -> str:
    """Open, resolve or cancel a durable project blocker without tagging the user.

    `open` needs question; `resolve`/`cancel` need wait_id. Owner and explicit
    sub-orchestrator contributors are allowed. The server owns authenticated membership,
    goal suppression and duplicate-safe claim CAS.
    """
    project = project.strip()
    action = action.strip().casefold()
    if not project:
        raise ApiToolError(code="invalid_argument", message="project is required")
    if action == "open":
        if not question.strip():
            raise ApiToolError(code="invalid_argument", message="question is required for open")
        result = await _api(
            "POST",
            f"/api/portfolio/projects/{project}/waits",
            json={"question": question.strip(), "task_ref": task_ref.strip()},
        )
    elif action in {"resolve", "cancel"}:
        if not wait_id.strip():
            raise ApiToolError(code="invalid_argument", message=f"wait_id is required for {action}")
        result = await _api(
            "POST",
            f"/api/portfolio/projects/{project}/waits/{wait_id.strip()}/{action}",
            json={},
        )
    else:
        raise ApiToolError(
            code="invalid_argument",
            message="unknown project_wait action; use open|resolve|cancel",
        )
    durable_id = str(result.get("id") or "") if isinstance(result, dict) else ""
    if not durable_id:
        raise ApiToolError(
            code="invalid_response",
            message="project_wait response has no durable wait id",
            status=200,
        )
    return f"PROJECT_WAIT_DURABLE:{durable_id}\n{json.dumps(result, ensure_ascii=False)}"


@mcp.tool()
async def task_create(title: str, project: str = "", price: int = 0,
                      description: str = "", assignee: str = "",
                      status: str = "new", priority: int = 2,
                      acceptance_command: str = "",
                      acceptance_manifest: list[str] | None = None,
                      acceptance_required: bool = False,
                      request_key: str = "") -> str:
    """Create a new task. Returns task number and details.
    project: registered project scope or id; omitted uses the caller's mapped scope.
    price in exact currency units (e.g. 20000 = 20 000). 0 is valid (no price).
    priority: 0=critical, 1=high, 2=medium (default), 3=low.
    status: lifecycle statuses (in_progress/done) are platform-owned and rejected."""
    _reject_lifecycle_status(status, "task_create")
    request_key = request_key.strip() or uuid.uuid4().hex
    command = _acceptance_command_from_caller(acceptance_command)
    payload = {
        "title": title, "price": price,
        "description": description, "assignee": assignee, "status": status,
        "scope": SCOPE, "priority": priority,
        "acceptance_command": command,
    }
    if ROLE in _ORCH_ROLES and (acceptance_manifest or acceptance_required):
        payload["acceptance_manifest"] = list(acceptance_manifest or [])
        payload["acceptance_required"] = bool(acceptance_required)
    if project:
        payload["project"] = project
    result = await _api(
        "POST",
        "/api/tm/tasks",
        json=payload,
        request_id=request_key,
        idempotency_key=request_key,
    )
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    if isinstance(result, dict):
        result = dict(result)
        result.setdefault("description", description)
        result.setdefault("assignee", assignee)
        result.setdefault("priority", priority)
        result.setdefault("task_id", result.get("id"))
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def task_create_status(request_key: str, project: str = "") -> str:
    """Resolve a task_create outcome after a timeout without creating another task."""

    params = {"project": project} if project else {"scope": SCOPE}
    result = await _api(
        "GET",
        f"/api/tm/task-create-requests/{request_key}",
        params=params,
    )
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def task_update(par: str, title: str = "", description: str = "",
                      price: int = -1, status: str = "",
                      assignee: str = "", priority: int = -1,
                      project: str = "", acceptance_command: str = "",
                      acceptance_manifest: list[str] | None = None,
                      acceptance_required: bool | None = None,
                      clear_acceptance_command: bool = False,
                      clear_acceptance_oracle: bool = False,
                      portfolio_project: str = "") -> str:
    """Update an existing task. Only provided fields are changed.
    par: '42' or 'PAR-42' (legacy). price in exact currency units (-1 = don't change, 0 = set to zero).
    Empty string = don't change for text fields. priority: 0-3 or -1=don't change.
    acceptance_command is orchestrator-only; empty means don't change.
    clear_acceptance_command=true explicitly clears it.
    project: explicit project returned by task_list; omitted uses the caller's mapped scope.
    portfolio_project: optional authoritative human project to link this task to.
    status: lifecycle statuses (in_progress/done) are platform-owned and rejected."""
    _reject_lifecycle_status(status, "task_update")
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
    command = _acceptance_command_from_caller(acceptance_command)
    if (clear_acceptance_command or clear_acceptance_oracle) and command:
        return "Error: acceptance_command and clear_acceptance_command are mutually exclusive"
    if ROLE in _ORCH_ROLES:
        if command:
            body["acceptance_command"] = command
        elif clear_acceptance_command:
            body["clear_acceptance_command"] = True
        if clear_acceptance_oracle:
            body["clear_acceptance_oracle"] = True
        else:
            if acceptance_manifest is not None:
                body["acceptance_manifest"] = list(acceptance_manifest)
            if acceptance_required is not None:
                body["acceptance_required"] = bool(acceptance_required)
    if not body and not portfolio_project.strip():
        return "Nothing to update"
    params = {"project": project} if project else ({"scope": SCOPE} if SCOPE else None)
    if body:
        result = await _api("PUT", f"/api/tm/tasks/{par}", json=body, params=params)
    else:
        result = await _api("GET", f"/api/tm/tasks/{par}", params=params)
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    if portfolio_project.strip():
        task_project = project.strip() or (
            str(result.get("project") or "") if isinstance(result, dict) else ""
        )
        if not task_project:
            raise ApiToolError(
                code="invalid_response",
                message="task response has no technical project identity",
                status=200,
            )
        link = await _api(
            "POST",
            f"/api/portfolio/projects/{portfolio_project.strip()}/tasks",
            json={"task_project": task_project, "task_ref": par},
        )
        return json.dumps({"task": result, "portfolio_link": link}, ensure_ascii=False)
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
async def task_get(par: str, project: str = "") -> str:
    """Get task details. project overrides scope and should come from task_list output."""
    params = {"project": project} if project else ({"scope": SCOPE} if SCOPE else None)
    result = await _api("GET", f"/api/tm/tasks/{par}", params=params)
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
        raise ApiToolError(
            code="invalid_response",
            message="Background job API returned a non-list response",
            status=200,
            details={"response_type": type(jobs).__name__},
        )
    if not jobs:
        return "No background jobs"
    icons = {
        "timer": "⏰", "file": "📄", "command": "🖥️", "ssh": "🔗",
        "run": "🚀", "cron": "🔁", "cron_command": "🔎",
    }

    def _when(job: dict) -> str:
        """Когда сработает — в абсолютном виде и «через сколько».

        Раньше тул печатал только id, статус, адресата и 60 символов сообщения. Понять
        «что этот джоб делает и когда» по такой строке нельзя, поэтому агенты шли читать
        `bg_jobs` напрямую в боевой БД (21.08, seedon-orchestrator). Все поля ниже API
        отдавал и тогда — их просто выбрасывали.
        """
        raw = job.get("trigger_at")
        if not raw:
            return ""
        try:
            moment = datetime.fromisoformat(str(raw))
        except ValueError:
            return str(raw)[:16]
        left = moment - datetime.now(moment.tzinfo)
        hours = left.total_seconds() / 3600
        if hours < 0:
            near = "просрочен"
        elif hours < 48:
            near = f"через {hours:.1f} ч"
        else:
            near = f"через {hours / 24:.0f} сут"
        return f"{moment.isoformat()[:16]} ({near})"

    lines = []
    for j in jobs:
        icon = icons.get(j["type"], "❓")
        try:
            cfg = json.loads(j.get("config") or "{}")
        except (TypeError, ValueError):
            cfg = {}
        rule = cfg.get("cron_expr") or cfg.get("pattern") or ""
        if not rule and cfg.get("delay_seconds"):
            rule = f"+{int(cfg['delay_seconds']) // 3600} ч"
        head = f"{icon} **{j['id']}** | {j['type']}"
        if rule:
            head += f" `{rule}`"
        when = _when(j)
        if when:
            head += f" | {when}"
        head += f" | {j['status']} | → {j.get('target_name', '?')}"
        lines.append(head)
        command = str(cfg.get("command") or cfg.get("path") or "")
        if command:
            lines.append(f"   ⚙ {command[:110]}")
        msg = " ".join((j.get("message") or "").split())
        if msg:
            lines.append(f"   {msg[:180]}")
    return "\n".join(lines)


@mcp.tool()
async def bg_cancel(job_id: str) -> str:
    """Cancel an active background job."""
    result = await _api("DELETE", f"/api/bg/jobs/{job_id}")
    if isinstance(result, dict) and result.get("error"):
        return f"Cancel failed: {result['error']}"
    return f"Job {job_id} cancelled."


async def knowledge(
    operation: str,
    detail: str = "summary",
    payload: dict[str, Any] | None = None,
) -> str:
    """Promote, query, or import canonical structured knowledge.

    ``detail`` progressively expands ``summary`` → ``record`` → ``evidence``.
    Direct file, SQLite, and vector operations are intentionally unsupported.
    """

    body = {
        "operation": operation,
        "detail": detail,
        "payload": payload or {},
    }
    try:
        result = await _api("POST", "/api/knowledge", json=body)
    except ApiToolError as exc:
        result = {"error": _canonical_error(exc)}
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


@mcp.tool()
async def search_memory(query: str, limit: int = 5, cross_project: bool = False) -> str:
    """Compatibility callable for old in-process consumers; not an agent MCP tool."""
    # scope НЕ параметр: берём ORCHESTRA_SCOPE из env воркера → нельзя запросить чужой проект.
    if not SCOPE:
        return "search_memory: no project scope (orchestrator context) — nothing to search."
    body = {"scope": SCOPE, "query": query, "limit": limit, "cross_project": cross_project}
    # Подсказка одна на все отказы: агент обязан уйти в grep, а не ждать и не повторять вызов.
    grep = f'ищи grep\'ом: rg "{query}" docs/ CLAUDE.md BUGS.md'
    try:
        result = await _api("POST", "/api/memory/search", json=body,
                            timeout=SEARCH_DEADLINE_S)
    except ApiToolError as e:
        # _api поднимает ApiToolError и на 5xx, и на payload["error"] — ловить надо ЗДЕСЬ.
        # Раньше исключение улетало наружу, и агент получал голое имя класса после 30 с.
        if e.code in ("transport_timeout", "search_busy", "search_stale"):
            reason = {"transport_timeout": f"поиск не уложился в {SEARCH_DEADLINE_S:.0f} с",
                      "search_busy": "очередь поиска переполнена",
                      "search_stale": "запрос протух в очереди"}[e.code]
            return f"search_memory: {reason}. Не жди и не повторяй — {grep}"
        if "RAG disabled" in e.message:
            return f"search_memory: семантический поиск выключен (RAG_ENABLED=false) — {grep}"
        return f"search_memory: {e.code} — {e.message}. {grep}"
    hits = result.get("results", []) if isinstance(result, dict) else []
    # `index` появился позже самого эндпоинта: старый роут его не отдаёт → .get, а не [].
    index = (result.get("index") or {}) if isinstance(result, dict) else {}
    pending = index.get("pending_files") or 0
    debt = (f"\n\n[индекс не догнан: {pending} файлов ещё не проиндексированы — "
            f"пустой ответ не доказывает отсутствие факта]") if pending else ""
    if not hits:
        # «долг 0» и «долга не знаем» — РАЗНОЕ: index_status отдаёт пустой словарь, пока в
        # процессе не было ни одного прохода, и молчание честнее нуля
        if "pending_files" not in index:
            debt = ("\n\n[состояние индекса неизвестно: в этом процессе ещё не было прохода — "
                    "пустой ответ ничего не доказывает]")
        return f"No memory matches for: {query!r}. Проверь — {grep}{debt}"
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
    return "\n\n---\n\n".join(lines) + debt


# Wrapper reloads Orchestra .env on every invocation, so Codex review follows the same
# currently selected proxy as workers, Cursor, and the dashboard service.
def _codex_bin() -> str:
    """Путь к codex, разрешаемый В МОМЕНТ ВЫЗОВА, а не константой при импорте.

    Была константа `/home/maxim/.local/bin/codex` — путь с ноутбука. После переезда на VPS
    (пользователь kesha) такого каталога нет вовсе, и каждый вызов падал в
    `/bin/sh: ...: not found`, exit 127 — до самого codex дело не доходило. Снаружи это
    выглядело как «Codex сломался», хотя бинарник стоит и работает.

    Порядок: `CODEX_BIN` из окружения (явное переопределение) -> `which codex` -> пусто.
    Пусто здесь НЕ исключение: решает вызывающий, ему нужен внятный текст, а не падение из
    середины сборки shell-команды."""
    override = os.environ.get("CODEX_BIN", "").strip()
    if override:
        return override
    return shutil.which("codex") or ""


_CODEX_MISSING_HINT = (
    "codex не найден: ни CODEX_BIN в окружении, ни `codex` в PATH. "
    "Поставь Codex CLI или задай CODEX_BIN=/путь/к/codex в .env сервиса. "
    "Проверить: `which codex`"
)
_REVIEW_RUBRIC = (
    "Review calibration: blocking = crash/corrupt/security; "
    "suggestion = real improvement; nit = skip."
)
_CODEX_EXECUTION_FAILURE_PATTERN = (
    r"bwrap:|failed rtm_newaddr|setting up uid map: permission denied|"
    r"sandbox.{0,80}(fail|reject)|no files were read|"
    r"(every|all) (local )?commands? failed|"
    r"(could not|unable to) (read|inspect|execute|review).{0,120}(sandbox|file)"
)
_CODEX_EXECUTION_FAILURE_JSONL_CHECK = """\
import json
import re
import sys

pattern = re.compile(sys.argv[2], re.IGNORECASE)
with open(sys.argv[1], encoding="utf-8", errors="replace") as source:
    for line in source:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if (isinstance(item, dict) and item.get("type") == "agent_message"
                and pattern.search(str(item.get("text", "")))):
            raise SystemExit(0)
raise SystemExit(1)
"""
_CODEX_EXECUTION_FAILURE_NOTE = (
    "\n\n> **Execution guard failed:** Codex reported that it could not execute "
    "workspace commands. The review above is preserved for diagnosis.\n"
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
    context: str,
    target: str = "",
    output: str = "CODEX_REVIEW.md",
    mode: str = "review",
    resume: bool = False,
    model: str = _CODEX_REVIEW_DEFAULT_MODEL,
) -> CallToolResult:
    """Run a registered Codex model review in background. Returns immediately.
    After calling, END YOUR TURN NOW; Orchestra wakes you when the job completes.
    target: file path for review, or empty for git diff review.
    output: where to write results (relative to your cwd). Also the session key — reuse the SAME
        output filename to continue a debate.
    context: task instructions plus a caller-supplied PROJECT CONTEXT block from the current repo.
    mode: 'review' (git diff, default) or 'exec' (review specific file).
    resume: continue the previous Codex session for this output (debate round). Falls back to a
        fresh session if none stored. On a resumed round put your counter-arguments / changelog
        in context (e.g. 'I fixed X and Y, re-review').
    model: reviewer model or registry alias. Omitted means the server-owned gpt-5.6-luna Fast tier.
        Registered Codex-runtime models are accepted except Codex Spark, which policy forbids for
        review. Pass the model again on resume; it is applied to the resumed Codex thread."""
    review_model = _resolve_codex_review_model(model)
    context = context.strip()
    if not context or "PROJECT CONTEXT" not in context.upper():
        raise ApiToolError(
            code="invalid_argument",
            message="context must include caller-supplied task instructions and PROJECT CONTEXT",
            details={"field": "context"},
        )
    review_context = (
        "CALLER-SUPPLIED PROJECT CONTEXT AND REVIEW INSTRUCTIONS:\n"
        f"{context}\n\n{_REVIEW_RUBRIC}"
    )

    # Первым делом после валидации: не создавать фоновую джобу, которая гарантированно упадёт по квоте.
    refusal = await _quota_refusal(review_model)
    if refusal:
        raise refusal
    info = await _api("GET", f"/api/sessions/{WORKER_NAME}", params={"scope": SCOPE})
    if isinstance(info, dict) and info.get("error"):
        return mcp_tool_result(
            result=None,
            text=f"Error resolving worker cwd: {info['error']}",
        )
    requesting_session_id = str(info.get("id") or "").strip()
    if not requesting_session_id:
        return mcp_tool_result(
            result=None,
            text="Error resolving worker session id: respawn the worker",
        )
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

    # Разрешаем бинарник ДО сборки команды: иначе несуществующий путь уезжает в shell и
    # возвращается голым exit 127 из фоновой джобы, где его никто не связывает с причиной.
    codex_bin = _codex_bin()
    if not codex_bin:
        return mcp_tool_result(result=None, text=_CODEX_MISSING_HINT)
    codex_cli = f"{q(codex_bin)} -m {q(review_model)}"

    if mode == "review":
        review_prompt = (
            f"{review_context}\n\nReview all current uncommitted changes in this worktree "
            "(staged, unstaged, and untracked). Inspect them with git status and git diff. "
            "Find bugs, security issues, breaking changes, and race conditions."
        )
        # Fresh review → codex_out: output_abs on a first run, round_tmp on a resume-fallback
        # (so the stale-session recovery is APPENDED as a round, never overwrites prior rounds).
        fresh_review = (
            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {codex_cli}"
            f" -s danger-full-access -a never exec review"
            f" --skip-git-repo-check --json"
            f" -o {q(codex_out)} - < {q(prompt_file)}"
        )
        if is_resume:
            # Override the original session policy: old reviews may have stored workspace-write.
            resume_prompt = (
                f"{review_context}\n\n"
                "Re-review the current uncommitted diff (run git diff yourself). "
                "For each prior finding: FIXED / STILL BROKEN / NEW BUG. "
                "Output a concise re-review (Re-review status, new findings, verdict)."
            )
            # Stale/invalid UUID → resume fails → fall back to a fresh review (recovery).
            codex = (
                f"printf '%s' {q(resume_prompt)} > {q(prompt_file)}; "
                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {codex_cli}"
                f" -s danger-full-access -a never exec resume {q(prev_uuid)}"
                f" --skip-git-repo-check --json"
                f" -o {q(codex_out)} - < {q(prompt_file)}"
                f" || {{ echo '[resume failed — stale session, starting fresh review]'; {fresh_review}; }}"
            )
        else:
            codex = f"printf '%s' {q(review_prompt)} > {q(prompt_file)}; {fresh_review}"
    elif mode == "exec":
        if not target and not is_resume:
            raise ApiToolError(
                code="invalid_argument",
                message="target file required for mode='exec'",
                details={"field": "target"},
            )
        prompt_parts_exec = [review_context]
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

        subcmd = f"exec resume {q(prev_uuid)}" if is_resume else "exec"
        codex = (
            f"printf '%s' {q(exec_prompt)} > {q(prompt_file)}; "
            f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {codex_cli}"
            f" -s danger-full-access -a never {subcmd}"
            f" --skip-git-repo-check --json"
            f" -o {q(codex_out)} - < {q(prompt_file)}"
        )
        if is_resume and target:
            # Stale/invalid UUID → resume fails → fresh exec. Only when a target exists —
            # without one the prompt has nothing concrete to review, so let resume fail loud.
            # Writes to codex_out (=round_tmp) so the recovery is appended, not overwriting history.
            fresh_exec = (
                f"cd {q(cwd)} && UV_CACHE_DIR=/tmp/uv-cache {codex_cli}"
                f" -s danger-full-access -a never exec"
                f" --skip-git-repo-check --json"
                f" -o {q(codex_out)} - < {q(prompt_file)}"
            )
            codex += f" || {{ echo '[resume failed — stale session, starting fresh]'; {fresh_exec}; }}"
    else:
        raise ApiToolError(
            code="invalid_argument",
            message=f"unknown mode '{mode}'; use 'review' or 'exec'",
            details={"field": "mode"},
        )

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
    usage_event_id = f"codex-review:{uuid.uuid4()}"
    finalize_args = [
        q(sys.executable), q(finalizer),
        "--output", q(output_abs),
        "--round-file", q(round_tmp),
        "--sessions-file", q(sessions_path),
        "--slug", q(slug),
        "--jsonl-file", q(jsonl_file),
        "--usage-event-id", q(usage_event_id),
        "--usage-session-id", q(requesting_session_id),
        "--usage-scope", q(SCOPE),
        "--usage-task-id", q(str(info.get("task_id") or "")),
        "--usage-model", q(review_model),
    ]
    if is_resume:
        finalize_args.append("--resume")
    if mode == "exec":
        finalize_args.append("--require-verdict")
    finalize = " ".join(finalize_args)
    failure_check = " ".join([
        q(sys.executable), "-c", q(_CODEX_EXECUTION_FAILURE_JSONL_CHECK),
        q(jsonl_file), q(_CODEX_EXECUTION_FAILURE_PATTERN),
    ])

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
        f"{finalize}; FINALIZE_RC=$?; "
        f"[ \"$FINALIZE_RC\" -eq 0 ] || exit \"$FINALIZE_RC\"; "
        f"if {failure_check}; then "
        f"printf '%s' {q(_CODEX_EXECUTION_FAILURE_NOTE)} >> {q(output_abs)}; "
        f"echo 'codex_review failed: Codex could not execute workspace commands' >&2; "
        f"exit 70; fi"
    )

    action = "resume" if is_resume else mode
    logger.info(
        f"codex_review: model={review_model} mode={mode} resume={is_resume} "
        f"slug={slug} cwd={cwd} output={output_abs}"
    )
    result = await _api("POST", "/api/bg/jobs", json={
        "type": "run",
        "config": {
            "command": cmd,
            "success_file": output_abs,
            "success_pattern": r"(?im)^##\s+Verdict\b" if mode == "exec" else "",
        },
        # Без слова "done": то же поле подставляется в провал как
        # "[Background job FAILED] <message>", и "Codex exec done" читалось как успех.
        "message": f"Codex {action} ({review_model}) → {output}",
        "target_name": WORKER_NAME,
        "target_scope": SCOPE,
        "timeout_seconds": 600,
        "created_by": WORKER_NAME,
    })
    if isinstance(result, dict) and result.get("error"):
        return mcp_tool_result(
            result=None,
            text=f"Error creating bg job: {result['error']}",
        )
    job_id = str(result.get("id") or "").strip()
    if not job_id:
        return mcp_tool_result(
            result=None,
            text="Error creating bg job: response has no job id",
        )
    resumed_note = f" (resumed session {prev_uuid[:8]})" if is_resume else ""
    text = (
        f"Codex {action} started with reviewer model {review_model}{resumed_note} "
        f"(bg job {job_id}, 10-min timeout). "
        f"END YOUR TURN NOW — this is required, not optional. Orchestra will wake you "
        f"when the job succeeds, times out, or fails. "
        f"On success: read {output}. To continue this debate, call codex_review again with the "
        f"SAME output and resume=True. Do not start another codex_review until this one reports back."
    )
    return mcp_tool_result(
        result={
            "kind": "deferred_job",
            "origin": "orchestra.bg_jobs",
            "job_id": job_id,
            "event_id": f"bgjob:v1:{job_id}:completed",
            "turn_control": "interrupt",
        },
        text=text,
    )


if __name__ == "__main__":
    publish_mcp_identity_canary()
    _apply_access_mode()
    logger.info(f"Orchestra MCP stdio (url={ORCHESTRA_URL}, scope={SCOPE})")
    mcp.run(transport="stdio")
