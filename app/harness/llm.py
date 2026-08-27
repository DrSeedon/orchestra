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
import json
import logging
import math
import random
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable

import httpx

from app import openrouter_counter as _counter

logger = logging.getLogger(__name__)

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
        # Provider-side atomic zero-spend does not exist for paid routes. The exact
        # suffix or reviewed paid-route allowlist is therefore checked immediately before POST.
        from app.models import is_harness_route_admitted

        if not is_harness_route_admitted(self.model):
            raise ValueError(
                f"OpenRouter Harness accepts exact :free or explicitly approved paid "
                f"routes, got '{self.model}'"
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
                    else:
                        message = error
                    raise RuntimeError(f"OpenRouter stream error: {message}")
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
            if not math.isfinite(billed) or billed < 0:
                raise RuntimeError(
                    f"OpenRouter returned invalid usage.cost: {reported_cost!r}"
                )
            if self.model.endswith(":free") and billed != 0:
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


class _RetryableStatus(Exception):
    def __init__(self, status: int, retry_after: float | None, kind: str = "upstream"):
        self.status = status
        self.retry_after = retry_after
        self.kind = kind  # "platform" (наша минутная/суточная стена) | "upstream" (занят провайдер)
        super().__init__(f"retryable {kind} rate limit, status {status}")


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
