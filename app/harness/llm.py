"""OpenRouterClient — streaming chat-completions over httpx (OpenAI wire format).

This module is the SINGLE owner of stream accumulation (plan B4). It consumes the
raw SSE `data:` chunks and yields structured `LLMEvent`s — the loop never sees a raw
delta. tool_calls stream as fragments (id / function.name / function.arguments split
across many chunks, keyed by index); we reassemble them here and emit one
`tool_call_done` per completed call. Argument JSON is NOT parsed here — we hand the
loop the full string and let it parse + fail-soft into a tool error (plan B4).

Retry policy (plan suggestions): retry 429/5xx ONLY before the first stream byte. Once
any content has streamed, a mid-stream failure discards the whole attempt and retries
from scratch (never resume a half-stream — that would duplicate text/tool_calls).
"""

import asyncio
import base64
import json
import logging
import os
import random
import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable
from uuid import uuid4

import httpx

from app import openrouter_counter as _counter

logger = logging.getLogger(__name__)

GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
GIGACHAT_REQUEST_TIMEOUT = 600


def tools_to_gigachat_functions(tools: list[dict]) -> list[dict]:
    """Translate the loop's OpenAI tool envelopes to GigaChat functions."""
    functions: list[dict] = []
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            raise ValueError("tool must contain a function object")
        clean = {key: value for key, value in function.items()
                 if key in {"name", "description", "parameters"}}
        if "parameters" in clean:
            clean["parameters"] = _gigachat_schema(clean["parameters"])
        functions.append(clean)
    return functions


def _gigachat_schema(node):
    """Rewrite a JSON schema into the subset GigaChat validates.

    GigaChat answers 422 to the whole request when ONE function has a nullable union
    (``anyOf``/``type`` list with ``null`` → "Type properties.X.type is wrong") or an
    object without ``properties`` ("Field 'properties.X.properties' is missing"). An
    optional argument is already expressed by leaving it out of ``required``.
    """
    if isinstance(node, list):
        return [_gigachat_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    node = dict(node)
    for key in ("anyOf", "oneOf"):
        variants = node.get(key)
        if not isinstance(variants, list):
            continue
        concrete = [v for v in variants if not (isinstance(v, dict) and v.get("type") == "null")]
        if len(concrete) == 1 and isinstance(concrete[0], dict):
            del node[key]
            node = {**concrete[0], **node}
        elif concrete:
            node[key] = concrete
    if isinstance(node.get("type"), list):
        concrete = [t for t in node["type"] if t != "null"]
        node["type"] = concrete[0] if concrete else "string"
    if "default" in node and node["default"] is None:
        del node["default"]
    if node.get("type") == "object" and not isinstance(node.get("properties"), dict):
        node["properties"] = {}
    if node.get("type") == "array" and not isinstance(node.get("items"), dict):
        node["items"] = {"type": "string"}
    return {key: _gigachat_schema(value) for key, value in node.items()}


def functions_to_openai_tools(functions: list[dict]) -> list[dict]:
    """Translate GigaChat function definitions into the loop's tool envelopes."""
    return [{"type": "function", "function": dict(function)} for function in (functions or [])]


# GigaChat links a function result to its call through ``functions_state_id``; without
# it Max re-issued the same call round after round (V-636: 12 identical list_agents).
# The loop keeps OpenAI-shaped history, so the id rides inside the tool call id.
_STATE_ID_PREFIX = "gigachat-fs-"


def _gigachat_call_id(functions_state_id: str) -> str:
    suffix = uuid4().hex[:8]
    if functions_state_id:
        return f"{_STATE_ID_PREFIX}{functions_state_id}-{suffix}"
    return f"gigachat-{uuid4()}"


def _functions_state_id(call_id: str) -> str:
    if not call_id.startswith(_STATE_ID_PREFIX):
        return ""
    return call_id[len(_STATE_ID_PREFIX):].rsplit("-", 1)[0]


_FENCED = re.compile(r"\A\s*```[\w+-]*[ \t]*\n(?P<body>.*?)\n?```\s*\Z", re.S)


def _repair_file_arguments(name: str, arguments: dict) -> dict:
    """Undo two GigaChat artifacts in file contents before the write tool sees them.

    Measured on GigaChat-2-Max (V-636): ``content`` arrived as one line with literal
    ``\\n`` sequences instead of line breaks, and wrapped in a markdown code fence.
    The write tool's syntax guard then rejected the file a dozen times in a row.
    """
    fields = {"write": ("content",), "edit": ("old", "new")}.get(name, ())
    repaired = dict(arguments)
    for field in fields:
        value = repaired.get(field)
        if not isinstance(value, str):
            continue
        if "\n" not in value and value.count("\\n") >= 2:
            value = value.replace("\\n", "\n").replace("\\t", "\t")
        path = str(repaired.get("path") or "")
        fenced = _FENCED.match(value)
        if name == "write" and fenced and not path.lower().endswith((".md", ".markdown")):
            value = fenced.group("body") + "\n"
        if name == "write" and path.endswith(".py"):
            value = _first_compiling_python(value, repaired[field])
        repaired[field] = value
    return repaired


def _first_compiling_python(repaired: str, original: str) -> str:
    """Python from GigaChat-2-Max arrived in several broken shapes (V-636): every quote as
    ``\\"``; one line of literal ``\\n`` inside a code fence followed by stray JSON
    (``",`` and a real line break), which also defeated the one-line check above. Try the
    plausible undoings and keep the first that compiles; nothing compiles → keep the input
    so the write tool's syntax guard reports it."""
    unescaped = original.replace("\\n", "\n").replace("\\t", "\t")
    fence = re.search(r"```[\w+-]*[ \t]*\n(?P<body>.*?)\n?```", unescaped, re.S)
    body = fence.group("body") + "\n" if fence else unescaped
    for candidate in (repaired, repaired.replace('\\"', '"'), body, body.replace('\\"', '"')):
        try:
            compile(candidate, "<write>", "exec")
        except SyntaxError:
            continue
        return candidate
    return repaired


def openai_messages_to_gigachat(messages: list[dict]) -> list[dict]:
    """Translate persisted OpenAI history to GigaChat's function-call history.

    AgentLoop keeps one stable OpenAI-shaped history for all providers. GigaChat uses
    an assistant ``function_call`` object and a following ``function`` message instead
    of ``tool_calls`` and ``tool`` messages, so the conversion happens at the boundary.
    """
    call_names: dict[str, str] = {}
    result: list[dict] = []
    for message in messages:
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            calls = message["tool_calls"]
            if len(calls) != 1:
                raise ValueError("GigaChat supports one function call per assistant message")
            call = calls[0]
            function = call.get("function") or {}
            name = function.get("name") or ""
            if not name:
                raise ValueError("assistant tool call has no function name")
            call_id = call.get("id") or ""
            if call_id:
                call_names[call_id] = name
            raw_args = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid arguments for function {name}: {exc}") from exc
            if not isinstance(arguments, dict):
                raise ValueError(f"arguments for function {name} must be an object")
            converted = {
                "role": "assistant",
                "content": message.get("content") or "",
                "function_call": {"name": name, "arguments": arguments},
            }
            state_id = _functions_state_id(call_id)
            if state_id:
                converted["functions_state_id"] = state_id
            result.append(converted)
            continue
        if role == "tool":
            call_id = message.get("tool_call_id") or ""
            name = call_names.get(call_id)
            if not name:
                raise ValueError(f"tool result refers to unknown call {call_id!r}")
            result.append({
                "role": "function",
                "name": name,
                # GigaChat validates function results as JSON values. A tool emits
                # ordinary text, so encode it as a JSON string at this boundary.
                "content": json.dumps(str(message.get("content") or ""), ensure_ascii=False),
            })
            continue
        result.append(dict(message))
    return result

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
REQUEST_TIMEOUT = 600        # per-HTTP-request ceiling (distinct from turn timeout)
CONNECT_TIMEOUT = 30
MAX_RETRIES = 3
BACKOFF_BASE = 1.5           # seconds; exponential with jitter
# #368 T5: потолок ОЖИДАНИЯ одной паузы (не числа попыток). Платформенная минутная
# стена важнее занятого провайдера — ей позволено ждать дольше.
RETRY_CEILING_PLATFORM = 120.0
RETRY_CEILING_UPSTREAM = 30.0


@dataclass
class LLMEvent:
    """One structured event from the stream. kind ∈ {text_delta, tool_call_done, final}.

    - text_delta:     text=<chunk>
    - tool_call_done: tool_id, tool_name, arguments (raw JSON string, may be "")
    - final:          finish_reason, usage (dict), reasoning_details (list, may be empty)
    """
    kind: str
    text: str = ""
    tool_id: str = ""
    tool_name: str = ""
    arguments: str = ""
    finish_reason: str = ""
    usage: dict = field(default_factory=dict)
    # Reasoning blocks the model emitted this round. MUST be replayed UNMODIFIED on the next
    # request alongside the assistant tool_calls, or reasoning models break across tool rounds
    # (OpenRouter reasoning-tokens docs). Empty when the model returned no reasoning.
    reasoning_details: list = field(default_factory=list)


class _ToolCallAccumulator:
    """Reassembles streamed tool_call fragments keyed by their delta index.

    OpenAI streams a tool call across chunks: the first carries id + function.name,
    later chunks append function.arguments fragments. index is the stable key.
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict] = {}
        self._order: list[int] = []

    def add(self, delta_tool_calls: list[dict]) -> None:
        for tc in delta_tool_calls or []:
            idx = tc.get("index", 0)
            slot = self._by_index.get(idx)
            if slot is None:
                slot = {"id": "", "name": "", "arguments": ""}
                self._by_index[idx] = slot
                self._order.append(idx)
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["arguments"] += fn["arguments"]

    def finished(self) -> list[dict]:
        """Completed tool calls in stream order."""
        return [self._by_index[i] for i in self._order]


class _ReasoningAccumulator:
    """Reassembles streamed `delta.reasoning_details` fragments in arrival order.

    The assembled sequence must be replayed to the provider UNMODIFIED (no rearrange, no
    reshape) or reasoning models break across tool rounds (OpenRouter reasoning-tokens docs).
    So we keep each block VERBATIM: fragments sharing an `index` are merged by concatenating
    their `text` (the only field OpenRouter fragments) and by overlaying any later fields
    (e.g. a `signature`/`data` arriving in a trailing chunk) — never dropping or inventing a
    field. Signed/encrypted/summary blocks (no `text`) pass through unchanged.
    """

    def __init__(self) -> None:
        self._by_index: dict[int | str, dict] = {}
        self._order: list[int | str] = []
        self._auto = 0

    def add(self, deltas: list[dict]) -> None:
        for d in deltas or []:
            if not isinstance(d, dict):
                continue
            idx = d.get("index")
            if idx is None:
                idx = f"_a{self._auto}"    # no index → treat each as its own block, keep order
                self._auto += 1
            slot = self._by_index.get(idx)
            if slot is None:
                self._by_index[idx] = dict(d)    # verbatim copy, no injected fields
                self._order.append(idx)
            else:
                text = d.get("text")
                for k, v in d.items():
                    if k == "text":
                        slot["text"] = (slot.get("text") or "") + (text or "")
                    elif k != "index":
                        slot[k] = v          # overlay later fields (signature/data/...), never drop

    def finished(self) -> list[dict]:
        return [self._by_index[i] for i in self._order]


class OpenRouterClient:
    def __init__(self, api_key: str, model: str, base_url: str = DEFAULT_BASE_URL,
                 http: httpx.AsyncClient | None = None,
                 supported_parameters: Iterable[str] = ()):
        self.api_key = api_key
        self.model = model
        self.supported_parameters = frozenset(str(p) for p in supported_parameters)
        self.base_url = base_url.rstrip("/")
        # Allow injecting a client (tests); otherwise own one.
        self._http = http
        self._owns_http = http is None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT))
        return self._http

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    def retarget(self, model: str, supported_parameters: Iterable[str]) -> None:
        """Change the exact route and its request contract together.

        Keeping these fields atomic prevents a seamless model switch from sending the
        previous provider's optional parameters to the new one.
        """
        self.model = model
        self.supported_parameters = frozenset(str(p) for p in supported_parameters)

    def _validate_route(self) -> None:
        # Provider-side atomic zero-spend does not exist for an unsuffixed preview.
        # The explicit suffix is therefore the last-line guard immediately before POST.
        if not self.model.endswith(":free"):
            raise ValueError(
                f"OpenRouter Harness accepts exact :free routes only, got '{self.model}'"
            )

    def _build_body(self, messages: list[dict], tools: list[dict],
                    effort: str | None = None) -> dict:
        self._validate_route()
        body: dict = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "usage": {"include": True},   # OpenRouter: emit usage in the final chunk
        }
        if tools:
            if "tools" not in self.supported_parameters:
                raise ValueError(f"OpenRouter model '{self.model}' does not support tools")
            body["tools"] = tools
            if "tool_choice" in self.supported_parameters:
                body["tool_choice"] = "auto"
        if effort and ({"reasoning", "reasoning_effort"} & self.supported_parameters):
            # OpenRouter unified reasoning knob (provider-agnostic). Omitted → body unchanged.
            body["reasoning"] = {"effort": effort}
        return body

    async def stream(self, messages: list[dict], tools: list[dict],
                     abort=None, effort: str | None = None) -> AsyncIterator[LLMEvent]:
        """Yield LLMEvents for one completion. Retries only before the first byte.

        abort: optional callable () -> bool; checked between retry attempts. Mid-stream
        abort is handled by the loop (it stops consuming), not here.
        effort: OpenRouter reasoning effort for this turn (None → no reasoning field).
        """
        body = self._build_body(messages, tools, effort)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES):
            if abort and abort():
                return
            started = False  # True once we yield anything — disables retry (no resume)
            # #368: каждая попытка = единица квоты, считаем ДО исхода (ретраи и
            # неудачи тоже). Сбой счётчика не роняет стрим — вызовы тотальны,
            # но страхуемся try/except: оплаченный результат дороже учёта.
            try:
                attempt_row = _counter.record_attempt_start()
            except Exception as e:  # pragma: no cover — страховка от любого сбоя учёта
                logger.warning(f"openrouter counter hook failed: {e}")
                try:
                    _counter.mark_unhealthy(f"start hook: {e}")
                except Exception:
                    pass
                attempt_row = None
            try:
                async for ev in self._one_attempt(body, headers, attempt_row):
                    started = True
                    yield ev
                return  # stream completed
            except _RetryableStatus as e:
                last_err = e
                if started:
                    # mid-stream is impossible here (status checked before reading body),
                    # but guard anyway: never resume a partially-yielded attempt.
                    raise
                ceiling = RETRY_CEILING_PLATFORM if e.kind == "platform" else RETRY_CEILING_UPSTREAM
                if e.retry_after is not None and e.retry_after > ceiling:
                    raise RuntimeError(
                        f"OpenRouter {e.kind} rate limit: нужно ждать {e.retry_after:.0f}s, "
                        f"потолок ожидания {ceiling:.0f}s исчерпан — повторите запрос позже"
                    )
                if attempt == MAX_RETRIES - 1:
                    break
                delay = self._retry_delay(attempt, e.retry_after, ceiling)
                logger.warning(
                    f"OpenRouter {e.kind} rate limit (attempt {attempt + 1}/{MAX_RETRIES}), retry in {delay:.1f}s")
                await asyncio.sleep(delay)
            except _StreamError as e:
                last_err = e
                # Отдав хоть одно событие, повторять нельзя: текст и вызовы инструментов
                # уехали в ход и продублируются. Нетранзиентную ошибку не повторяем вовсе.
                if started or not e.transient:
                    raise
                if attempt == MAX_RETRIES - 1:
                    break
                delay = self._retry_delay(attempt, None, RETRY_CEILING_UPSTREAM)
                logger.warning(
                    f"OpenRouter stream error (attempt {attempt + 1}/{MAX_RETRIES}): {e}, retry in {delay:.1f}s")
                await asyncio.sleep(delay)
            except (httpx.TransportError, httpx.StreamError) as e:
                last_err = e
                if started:
                    raise  # mid-stream network failure → discard, surface to loop
                if attempt == MAX_RETRIES - 1:
                    break
                delay = self._retry_delay(attempt, None)
                logger.warning(f"OpenRouter transport error (attempt {attempt + 1}): {e}, retry in {delay:.1f}s")
                await asyncio.sleep(delay)
        raise RuntimeError(f"OpenRouter request failed after {MAX_RETRIES} attempts: {last_err}")

    @staticmethod
    def _retry_delay(attempt: int, retry_after: float | None,
                     ceiling: float | None = None) -> float:
        if retry_after is not None:
            return min(retry_after, ceiling) if ceiling else retry_after
        delay = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.5)
        return min(delay, ceiling) if ceiling else delay

    async def _one_attempt(self, body: dict, headers: dict,
                           attempt_row: int | None = None) -> AsyncIterator[LLMEvent]:
        http = await self._client()
        acc = _ToolCallAccumulator()
        racc = _ReasoningAccumulator()
        finish_reason = ""
        usage: dict = {}
        emitted_content = False
        emitted_tool_calls = False
        async with http.stream("POST", f"{self.base_url}/chat/completions",
                               json=body, headers=headers) as resp:
            try:
                _counter.record_attempt_status(attempt_row, resp.status_code)
            except Exception as e:  # pragma: no cover — сбой учёта не роняет стрим (#368)
                logger.warning(f"openrouter counter hook failed: {e}")
                try:
                    _counter.mark_unhealthy(f"status hook: {e}")
                except Exception:
                    pass
            if resp.status_code == 429 or resp.status_code >= 500:
                await resp.aread()
                kind = _classify_rate_limit(resp.headers) if resp.status_code == 429 else "upstream"
                raise _RetryableStatus(resp.status_code, _parse_retry_after(resp), kind)
            if resp.status_code >= 400:
                detail = (await resp.aread()).decode(errors="replace")[:500]
                raise httpx.HTTPStatusError(
                    f"OpenRouter {resp.status_code}: {detail}",
                    request=resp.request, response=resp)
            async for line in resp.aiter_lines():
                parsed = _parse_sse(line)
                if parsed is _DONE:
                    break
                if not isinstance(parsed, dict):
                    continue
                chunk: dict = parsed
                if chunk.get("error") is not None:
                    error = chunk["error"]
                    if isinstance(error, dict):
                        message = error.get("message") or error.get("code") or error
                        code = error.get("code")
                    else:
                        message, code = error, None
                    raise _StreamError(f"OpenRouter stream error: {message}", code)
                # usage-only chunk (OpenRouter sends a trailing chunk with empty choices)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                if len(choices) > 1:
                    logger.warning("OpenRouter returned multiple choices — using choices[0]")
                choice = choices[0]
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if content:
                    emitted_content = True
                    yield LLMEvent("text_delta", text=content)
                if delta.get("tool_calls"):
                    acc.add(delta["tool_calls"])
                if delta.get("reasoning_details"):
                    racc.add(delta["reasoning_details"])
                fr = choice.get("finish_reason")
                if fr:
                    finish_reason = fr
        reported_cost = usage.get("cost")
        if reported_cost is not None:
            try:
                billed = float(reported_cost)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"OpenRouter returned invalid usage.cost: {reported_cost!r}"
                ) from exc
            if billed != 0:
                raise RuntimeError(
                    f"OpenRouter zero-spend contract violated: usage.cost={billed}"
                )
        # emit accumulated tool calls (one per completed call), then final
        for tc in acc.finished():
            if not tc["id"] or not tc["name"]:
                raise RuntimeError("OpenRouter returned a malformed tool call without id or name")
            emitted_tool_calls = True
            yield LLMEvent("tool_call_done", tool_id=tc["id"],
                           tool_name=tc["name"], arguments=tc["arguments"])
        # finish_reason "tool_calls" wins when tool calls were emitted (plan: tool_calls win)
        if emitted_tool_calls and finish_reason != "tool_calls":
            finish_reason = "tool_calls"
        if not emitted_content and not emitted_tool_calls:
            raise RuntimeError("OpenRouter returned an empty completion")
        yield LLMEvent("final", finish_reason=finish_reason or "stop", usage=usage,
                       reasoning_details=racc.finished())


# Перегрузка провайдера приходит НЕ статусом, а обычным SSE-чанком с полем error уже
# внутри открытого потока: 200 OK, а затем «Upstream error from Nvidia: Service temporarily
# overloaded». До #V-592 такой чанк убивал ход целиком, хотя повторить запрос было безопасно —
# ни одного события ещё не отдано, ни один инструмент не выполнен.
_TRANSIENT_STREAM_RE = re.compile(
    r"overload|temporarily|timeout|timed out|unavailable|try again|capacity|"
    r"internal server error|bad gateway|503|502|504",
    re.IGNORECASE)


class _StreamError(RuntimeError):
    def __init__(self, message: str, code=None):
        self.code = code
        super().__init__(message)

    @property
    def transient(self) -> bool:
        """Повторять только заведомо временное. Нет кредитов, нет модели, битый запрос и
        отказ авторизации повтором не лечатся — это трата попытки и суточного лимита."""
        try:
            code = int(self.code)
        except (TypeError, ValueError):
            code = None
        if code is not None:
            return code >= 500 or code in (408, 409, 429)
        return bool(_TRANSIENT_STREAM_RE.search(str(self)))


class _RetryableStatus(Exception):
    def __init__(self, status: int, retry_after: float | None, kind: str = "upstream"):
        self.status = status
        self.retry_after = retry_after
        self.kind = kind  # "platform" (наша минутная/суточная стена) | "upstream" (занят провайдер)
        super().__init__(f"retryable {kind} rate limit, status {status}")


# V-636: the stand's GigaChat account serves one request at a time. An orchestrator and its
# worker asking together got HTTP 429 until retries ran out and the worker's turn failed.
# One in-flight request per endpoint in this process queues them instead.
_GIGACHAT_SLOTS: dict[str, asyncio.Lock] = {}


def _gigachat_slot(chat_url: str) -> asyncio.Lock:
    return _GIGACHAT_SLOTS.setdefault(chat_url, asyncio.Lock())


class GigaChatClient:
    """GigaChat transport implementing the same event contract as OpenRouterClient."""

    def __init__(self, model: str, *, http: httpx.AsyncClient | None = None,
                 auth_url: str = GIGACHAT_AUTH_URL,
                 chat_url: str = GIGACHAT_CHAT_URL):
        self.model = model
        self.auth_url = auth_url.rstrip("/")
        self.chat_url = chat_url.rstrip("/")
        self._http = http
        self._owns_http = http is None
        self._access_token = ""
        self._token_expires_at = 0.0

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(GIGACHAT_REQUEST_TIMEOUT, connect=30),
                trust_env=False,
                verify=os.environ.get("GIGACHAT_CA_BUNDLE") or True,
            )
        return self._http

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    def retarget(self, model: str, supported_parameters: Iterable[str] = ()) -> None:
        self.model = model

    def _auth_headers(self) -> dict[str, str]:
        auth_key = os.environ.get("GIGACHAT_AUTH_KEY", "").strip()
        if not auth_key:
            client_id = os.environ.get("GIGACHAT_CLIENT_ID", "").strip()
            client_secret = os.environ.get("GIGACHAT_CLIENT_SECRET", "").strip()
            if client_id and client_secret:
                auth_key = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        if not auth_key:
            raise RuntimeError(
                "No GigaChat credentials found (checked GIGACHAT_AUTH_KEY or "
                "GIGACHAT_CLIENT_ID/GIGACHAT_CLIENT_SECRET)"
            )
        return {
            "Authorization": f"Basic {auth_key}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid4()),
        }

    async def _fetch_token(self) -> None:
        scope = os.environ.get("GIGACHAT_SCOPE", "").strip()
        if not scope:
            raise RuntimeError("GIGACHAT_SCOPE is required")
        http = await self._client()
        response = await http.post(
            self.auth_url,
            data={"scope": scope},
            headers=self._auth_headers(),
        )
        if response.status_code >= 400:
            detail = response.text[:500]
            raise RuntimeError(f"GigaChat OAuth failed ({response.status_code}): {detail}")
        try:
            payload = response.json()
            token = str(payload["access_token"])
            lifetime = float(payload.get("expires_in", 1800))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("GigaChat OAuth returned an invalid token response") from exc
        if not token:
            raise RuntimeError("GigaChat OAuth returned an empty access token")
        self._access_token = token
        self._token_expires_at = asyncio.get_running_loop().time() + max(0.0, lifetime) - 30.0

    async def _token(self) -> str:
        if not self._access_token or asyncio.get_running_loop().time() >= self._token_expires_at:
            await self._fetch_token()
        return self._access_token

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error") or payload.get("message")
                if isinstance(error, dict):
                    return str(error.get("message") or error.get("code") or error)
                if error:
                    return str(error)
        except (ValueError, json.JSONDecodeError):
            pass
        return response.text[:500]

    @staticmethod
    def _usage(payload: dict) -> dict:
        usage = payload.get("usage") or {}
        return {
            key: usage[key]
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if key in usage
        }

    async def _post_with_retry(self, body: dict, abort=None) -> httpx.Response | None:
        """POST a completion; a dropped connection or 429/5xx is retried before failing.

        V-636: the first turn after a restart failed with an empty ``httpx`` transport
        error and the user saw a bare "llm round failed:" — one blip ended the turn.
        """
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with _gigachat_slot(self.chat_url):
                    token = await self._token()
                    http = await self._client()
                    response = await http.post(
                        self.chat_url,
                        json=body,
                        headers={"Authorization": f"Bearer {token}",
                                 "Content-Type": "application/json"},
                    )
                    if response.status_code == 401:
                        self._access_token = ""
                        token = await self._token()
                        response = await http.post(
                            self.chat_url,
                            json=body,
                            headers={"Authorization": f"Bearer {token}",
                                     "Content-Type": "application/json"},
                        )
            except httpx.TransportError as exc:
                if attempt == MAX_RETRIES:
                    raise RuntimeError(
                        f"GigaChat connection failed: {type(exc).__name__} {exc}".rstrip()
                    ) from exc
                logger.warning("GigaChat transport error, retrying: %s %s", type(exc).__name__, exc)
            else:
                if response.status_code not in (429, 500, 502, 503, 504) or attempt == MAX_RETRIES:
                    return response
                logger.warning("GigaChat HTTP %s, retrying", response.status_code)
            if abort and abort():
                return None
            await asyncio.sleep(BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1))
        raise AssertionError("unreachable")

    async def stream(self, messages: list[dict], tools: list[dict],
                     abort=None, effort: str | None = None) -> AsyncIterator[LLMEvent]:
        """Issue one non-streaming request; GigaChat returns function_call as an object."""
        if abort and abort():
            return
        body = {
            "model": self.model,
            "messages": openai_messages_to_gigachat(messages),
            "stream": False,
        }
        if tools:
            body["functions"] = tools_to_gigachat_functions(tools)
            body["function_call"] = "auto"
        response = await self._post_with_retry(body, abort)
        if response is None:
            return
        if response.status_code >= 400:
            raise RuntimeError(
                f"GigaChat request failed ({response.status_code}): {self._error_detail(response)}"
            )
        try:
            payload = response.json()
            choice = (payload.get("choices") or [])[0]
            message = choice.get("message") or {}
        except (IndexError, AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("GigaChat returned an invalid completion") from exc
        function_call = message.get("function_call")
        content = message.get("content")
        if function_call:
            if not isinstance(function_call, dict) or not function_call.get("name"):
                raise RuntimeError("GigaChat returned a malformed function_call")
            arguments = function_call.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise RuntimeError("GigaChat returned invalid function_call arguments") from exc
            if not isinstance(arguments, dict):
                raise RuntimeError("GigaChat function_call arguments must be an object")
            arguments = _repair_file_arguments(str(function_call["name"]), arguments)
            # The text beside a function_call is dropped: GigaChat puts a textual
            # imitation of the call there ("write path=... content=...") that differs
            # from the call it actually makes (V-636).
            yield LLMEvent(
                "tool_call_done",
                tool_id=_gigachat_call_id(str(message.get("functions_state_id") or "")),
                tool_name=str(function_call["name"]),
                arguments=json.dumps(arguments, ensure_ascii=False),
            )
            yield LLMEvent("final", finish_reason="tool_calls", usage=self._usage(payload))
            return
        if not content:
            raise RuntimeError("GigaChat returned an empty completion")
        yield LLMEvent("text_delta", text=str(content))
        yield LLMEvent(
            "final",
            finish_reason=str(choice.get("finish_reason") or "stop"),
            usage=self._usage(payload),
        )


def _classify_rate_limit(headers) -> str:
    """Платформенный 429 несёт X-RateLimit-*; upstream-429 провайдера модели — нет (#368 F6)."""
    for name in headers.keys():
        if name.lower().startswith("x-ratelimit"):
            return "platform"
    return "upstream"


_DONE = object()


def _parse_sse(line: str):
    """Parse one SSE line → chunk dict, the _DONE sentinel, or None to skip.

    Lines without a `data:` prefix (comments/blank/event:) are ignored. `[DONE]`
    terminates. A `data:` line is a complete SSE record; invalid JSON is a protocol
    error and must be loud instead of turning into an apparently successful empty reply.
    """
    if not line or not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload:
        return None
    if payload == "[DONE]":
        return _DONE
    try:
        return json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"invalid OpenRouter SSE JSON: {payload[:120]}") from exc


def _parse_retry_after(resp: httpx.Response) -> float | None:
    val = resp.headers.get("retry-after")
    if not val:
        return None
    try:
        return float(val)  # seconds form; HTTP-date form is rare for OpenRouter
    except ValueError:
        return None
