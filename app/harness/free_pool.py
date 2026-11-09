"""Two-contour $0 Free Worker Pool for Orchestra Harness.

Contour 1 — Local CPU+RAM inference on Contabo (`llama-server` on `127.0.0.1:8091`):
- Unified `Qwen3.5-35B-A3B-Heretic-v2` (`i1-IQ3_M`, 35B total / 3B active MoE, uncensored + tools)
- Strictly bounded to `--threads 6 --threads-batch 6 --parallel 1 -cb --ctx-size 65536 --repeat-penalty 1.15`, `nice -n 10`
- Deployment uses `--cache-type-k q8_0 --cache-type-v q8_0`; one dedicated slot has the full 65536-token context window.
- Handles private tasks (1C, EDO, SberBusiness, Diadoc, Kesha, D&D) and serves as the
  unbreakable local fallback when cloud free tiers return HTTP 429/5xx.

Contour 2 — Cloud Free Pool ($0, 150–2200 tok/s) + cascading `FreeWorkerRouter`:
1. Cerebras Inference Free Tier (`https://api.cerebras.ai/v1`, `CEREBRAS_API_KEY`)
2. Groq Cloud Free Tier (`https://api.groq.com/openai/v1`, `GROQ_API_KEY`)
3. Mistral La Plateforme Free Tier (`https://api.mistral.ai/v1`, `MISTRAL_API_KEY` / `CODESTRAL_API_KEY`)
4. Google AI Studio Free Tier (`https://generativelanguage.googleapis.com/v1beta/openai`, `GEMINI_API_KEY` / `GOOGLE_API_KEY`)
5. OpenRouter `:free` Pool (`https://openrouter.ai/api/v1`, `OPENROUTER_API_KEY`)
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import AsyncIterator, Iterable

import httpx

from app.harness.llm import LLMEvent, OpenRouterClient

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_LLAMA_URL = "http://127.0.0.1:8091/v1"
DEFAULT_LOCAL_UPSTREAM_MODEL = "qwen3.5-35b-a3b-heretic"

LOCAL_HERETIC_MODEL_ID = "local/qwen3.5-35b-a3b-heretic:free"
FREE_ROUTER_MODEL_ID = "free/auto:free"

# Private / sensitive markers that must stay strictly on Contour 1 (Local Contabo RAM)
_PRIVATE_TASK_RE = re.compile(
    r"(\[private\]|\b1[cс]\b|эдо|диадок|diadoc|сбис|sbis|сбербизнес|sberbusiness|"
    r"укэп|криптопро|cryptopro|kesha|кеша|\bd&d\b|\bднд\b|heretic|uncensored|без\s+цензуры)",
    re.IGNORECASE,
)

# Cloud provider endpoint configurations
CLOUD_FREE_PROVIDERS: dict[str, dict[str, str]] = {
    "cerebras": {
        "base_url_env": "CEREBRAS_BASE_URL",
        "default_base_url": "https://api.cerebras.ai/v1",
        "key_envs": "CEREBRAS_API_KEY",
    },
    "groq": {
        "base_url_env": "GROQ_BASE_URL",
        "default_base_url": "https://api.groq.com/openai/v1",
        "key_envs": "GROQ_API_KEY",
    },
    "mistral": {
        "base_url_env": "MISTRAL_BASE_URL",
        "default_base_url": "https://api.mistral.ai/v1",
        "key_envs": "MISTRAL_API_KEY,CODESTRAL_API_KEY",
    },
    "aistudio": {
        "base_url_env": "AISTUDIO_BASE_URL",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_envs": "GEMINI_API_KEY,GOOGLE_API_KEY,AISTUDIO_API_KEY",
    },
}

# Default OpenRouter :free tool-capable fallback candidates (in priority order)
DEFAULT_OPENROUTER_FREE_CANDIDATES: tuple[str, ...] = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "cohere/north-mini-code:free",
    "xingchen-agi/xing4.0-29b-a4b:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3.5-super-vl:free",
)

# Per-route cooldown tracker (monotonic timestamp until which a rate-limited route is skipped)
_ROUTE_COOLDOWN_UNTIL: dict[str, float] = {}
DEFAULT_COOLDOWN_SECONDS = 60.0


def mark_route_cooldown(route_id: str, seconds: float = DEFAULT_COOLDOWN_SECONDS) -> None:
    _ROUTE_COOLDOWN_UNTIL[route_id] = time.monotonic() + max(1.0, seconds)


def is_route_cooled_down(route_id: str) -> bool:
    until = _ROUTE_COOLDOWN_UNTIL.get(route_id, 0.0)
    if until <= 0.0:
        return False
    if time.monotonic() >= until:
        _ROUTE_COOLDOWN_UNTIL.pop(route_id, None)
        return False
    return True


def clear_route_cooldowns() -> None:
    _ROUTE_COOLDOWN_UNTIL.clear()


def local_llama_base_url() -> str:
    url = (os.environ.get("LOCAL_LLAMA_BASE_URL") or DEFAULT_LOCAL_LLAMA_URL).strip().rstrip("/")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    return url


def cloud_provider_api_key(prefix: str) -> str:
    cfg = CLOUD_FREE_PROVIDERS.get(prefix)
    if not cfg:
        return ""
    for env_name in cfg["key_envs"].split(","):
        val = os.environ.get(env_name.strip(), "").strip()
        if val:
            return val
    return ""


def cloud_provider_base_url(prefix: str) -> str:
    cfg = CLOUD_FREE_PROVIDERS[prefix]
    url = (os.environ.get(cfg["base_url_env"]) or cfg["default_base_url"]).strip().rstrip("/")
    return url


def is_private_conversation(messages: list[dict]) -> bool:
    """Return True when the conversation contains private/sensitive or uncensored markers."""
    for msg in messages or []:
        role = msg.get("role")
        if role not in ("user", "system"):
            continue
        content = msg.get("content")
        if isinstance(content, str) and _PRIVATE_TASK_RE.search(content):
            return True
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    if _PRIVATE_TASK_RE.search(part["text"]):
                        return True
    return False


def upstream_model_name(model_id: str) -> tuple[str, str]:
    """Return (provider_prefix, upstream_model) for a free-pool model id."""
    stripped = model_id[:-5] if model_id.endswith(":free") else model_id
    if "/" not in stripped:
        return ("local", DEFAULT_LOCAL_UPSTREAM_MODEL)
    prefix, rest = stripped.split("/", 1)
    if prefix == "local":
        return ("local", rest or DEFAULT_LOCAL_UPSTREAM_MODEL)
    if prefix == "free":
        return ("free", rest or "auto")
    if prefix in CLOUD_FREE_PROVIDERS:
        return (prefix, rest)
    return ("openrouter", model_id)


LOCAL_LLAMA_REQUEST_TIMEOUT = 1800.0

# Ultra-compact 6-tool core for local CPU orchestrators/workers when >6 tools are attached.
# Keeps total system + tool schema prefix under ~700 tokens (~14s cold prefill, <2s warm cache).
_LOCAL_CORE_TOOLS: frozenset[str] = frozenset({
    "bash", "read", "write", "edit",
    "read_file", "write_file", "edit_file",
    "spawn_worker", "list_agents", "send_message",
})

_LOCAL_CORE_PARAMS: dict[str, set[str]] = {
    "bash": {"command"},
    "read": {"path", "offset", "limit"},
    "write": {"path", "content"},
    "edit": {"path", "old_string", "new_string"},
    "read_file": {"path", "offset", "limit"},
    "write_file": {"path", "content"},
    "edit_file": {"path", "old_string", "new_string"},
    "spawn_worker": {"name", "task", "model"},
    "list_agents": set(),
    "send_message": {"to", "message"},
}


def _compact_local_tools(tools: list[dict]) -> list[dict]:
    """Trim 60-tool MCP schemas down to 6-7 core tools (~300 tokens total) for fast CPU prefill."""
    if len(tools) <= 6:
        return tools
    compacted: list[dict] = []
    for t in tools:
        fn = t.get("function") or {}
        name = fn.get("name", "")
        if name not in _LOCAL_CORE_TOOLS:
            continue
        desc = (fn.get("description") or "").strip().splitlines()[0][:60]
        params = fn.get("parameters") or {"type": "object", "properties": {}}
        allowed_p = _LOCAL_CORE_PARAMS.get(name)
        props = {}
        for pk, pv in (params.get("properties") or {}).items():
            if allowed_p is not None and pk not in allowed_p:
                continue
            if isinstance(pv, dict):
                props[pk] = {"type": pv.get("type", "string")}
            else:
                props[pk] = pv
        req_list = [r for r in (params.get("required") or []) if r in props]
        new_params: dict = {"type": "object", "properties": props}
        if req_list:
            new_params["required"] = req_list
        compacted.append({
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": new_params,
            },
        })
    return compacted or tools[:6]


def _compact_local_messages(messages: list[dict]) -> list[dict]:
    """Compact giant (>1.5 KB) system prompts and strip CLI platform-note replays for ~700-token CPU prefill."""
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "system" and isinstance(content, str) and len(content) > 1500:
            cwd_match = re.search(r"Working directory:\s*([^\n]+)", content)
            cwd_str = cwd_match.group(1).strip() if cwd_match else "/home/kesha/local-heretic-lab"
            orch_match = re.search(r"Orchestrator:\s*([^\n]+)", content)
            worker_match = re.search(r"Worker name:\s*([^\n]+)", content)
            ident = (
                f"Orchestrator: {orch_match.group(1).strip()}"
                if orch_match
                else (f"Worker: {worker_match.group(1).strip()}" if worker_match else "Orchestra Agent")
            )
            compacted_sys = (
                f"Ты — {ident} в платформе Orchestra (локальная модель Qwen3.5-35B-A3B-Heretic-v2 IQ3_M без цензуры, "
                f"окно контекста 65536 токенов, 1 слот).\n"
                f"Рабочая папка (scope/cwd): {cwd_str}\n"
                "Отвечай по-русски, чётко, коротко и по делу, без лишней воды. "
                "Вызывай инструменты (bash, read, write, edit, spawn_worker, list_agents, send_message) "
                "только когда это реально нужно для выполнения задачи пользователя."
            )
            out.append({**m, "content": compacted_sys})
        elif (
            role == "user"
            and isinstance(content, str)
            and content.startswith("[Orchestra platform note:")
            and "\n\n---\n\n" in content
        ):
            actual_user_msg = content.rsplit("\n\n---\n\n", 1)[-1]
            out.append({**m, "content": actual_user_msg})
        else:
            out.append(m)
    return out


class LocalLlamaClient(OpenRouterClient):
    """OpenAI-compatible streaming client for Contabo local `llama-server` (127.0.0.1:8091)."""

    counts_openrouter_attempts = False

    def __init__(
        self,
        model: str = LOCAL_HERETIC_MODEL_ID,
        *,
        base_url: str | None = None,
        http: httpx.AsyncClient | None = None,
        supported_parameters: Iterable[str] = ("tools", "tool_choice"),
        input_modalities: Iterable[str] = ("text",),
        workspace_root: str | None = None,
    ):
        _, upstream = upstream_model_name(model)
        self.upstream_model = upstream
        super().__init__(
            api_key=os.environ.get("LOCAL_LLAMA_API_KEY", "local-no-key"),
            model=model,
            base_url=base_url or local_llama_base_url(),
            http=http,
            supported_parameters=supported_parameters,
            input_modalities=input_modalities,
            workspace_root=workspace_root,
        )

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(LOCAL_LLAMA_REQUEST_TIMEOUT, connect=30.0)
            )
        return self._http

    def retarget(
        self,
        model: str,
        supported_parameters: Iterable[str] = ("tools", "tool_choice"),
        input_modalities: Iterable[str] = ("text",),
    ) -> None:
        _, upstream = upstream_model_name(model)
        self.upstream_model = upstream
        super().retarget(model, supported_parameters, input_modalities)

    def _build_body(
        self, messages: list[dict], tools: list[dict], effort: str | None = None
    ) -> dict:
        self._validate_route()
        compact_msgs = _compact_local_messages(messages)
        compact_tools = _compact_local_tools(tools)
        body: dict = {
            "model": self.upstream_model,
            "messages": compact_msgs,
            "stream": True,
            "cache_prompt": True,
            "stream_options": {"include_usage": True},
        }
        if compact_tools:
            if "tools" not in self.supported_parameters:
                raise ValueError(f"Local model '{self.model}' does not support tools")
            body["tools"] = compact_tools
            if "tool_choice" in self.supported_parameters:
                body["tool_choice"] = "auto"
        # Always disable <think> on CPU local model so it immediately outputs text/tool_calls at 13 tok/s
        body["chat_template_kwargs"] = {"enable_thinking": False}
        return body


class CloudOpenAIClient(OpenRouterClient):
    """OpenAI-compatible streaming client for direct free cloud tiers (Cerebras, Groq, Mistral, AI Studio)."""

    counts_openrouter_attempts = False

    def __init__(
        self,
        provider_prefix: str,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        http: httpx.AsyncClient | None = None,
        supported_parameters: Iterable[str] = ("tools", "tool_choice"),
        input_modalities: Iterable[str] = ("text",),
        workspace_root: str | None = None,
    ):
        self.provider_prefix = provider_prefix
        _, upstream = upstream_model_name(model)
        self.upstream_model = upstream
        resolved_key = (api_key if api_key is not None else cloud_provider_api_key(provider_prefix)).strip()
        if not resolved_key:
            cfg = CLOUD_FREE_PROVIDERS.get(provider_prefix, {})
            raise RuntimeError(
                f"No API key found for free cloud provider '{provider_prefix}' "
                f"(checked {cfg.get('key_envs', provider_prefix.upper() + '_API_KEY')})"
            )
        resolved_url = base_url or cloud_provider_base_url(provider_prefix)
        super().__init__(
            api_key=resolved_key,
            model=model,
            base_url=resolved_url,
            http=http,
            supported_parameters=supported_parameters,
            input_modalities=input_modalities,
            workspace_root=workspace_root,
        )

    def retarget(
        self,
        model: str,
        supported_parameters: Iterable[str] = ("tools", "tool_choice"),
        input_modalities: Iterable[str] = ("text",),
    ) -> None:
        prefix, upstream = upstream_model_name(model)
        self.provider_prefix = prefix
        self.upstream_model = upstream
        super().retarget(model, supported_parameters, input_modalities)

    def _build_body(
        self, messages: list[dict], tools: list[dict], effort: str | None = None
    ) -> dict:
        self._validate_route()
        body: dict = {
            "model": self.upstream_model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            if "tools" not in self.supported_parameters:
                raise ValueError(f"Cloud free model '{self.model}' does not support tools")
            body["tools"] = tools
            if "tool_choice" in self.supported_parameters:
                body["tool_choice"] = "auto"
        return body


class FreeWorkerRouter:
    """Cascading $0 router across Cloud Free Pools + Local Contabo `llama-server` fallback.

    Routing rules:
    1. Private/sensitive or uncensored tasks (`1C`, `ЭДО`, `СберБизнес`, `Kesha`, `D&D`, `[private]`)
       are routed strictly to Contour 1 (`LocalLlamaClient` on `127.0.0.1:8091`) — never sent to cloud.
    2. General tasks cascade through configured cloud free providers (Cerebras -> Groq -> Mistral ->
       Google AI Studio -> OpenRouter `:free`) and fall back to Local Contabo `llama-server` on
       HTTP 429 / 5xx / transport errors before the first streamed event.
    """

    def __init__(
        self,
        model: str = FREE_ROUTER_MODEL_ID,
        *,
        http: httpx.AsyncClient | None = None,
        supported_parameters: Iterable[str] = ("tools", "tool_choice", "reasoning"),
        input_modalities: Iterable[str] = ("text",),
        workspace_root: str | None = None,
    ):
        self.model = model
        self.supported_parameters = frozenset(str(p) for p in supported_parameters)
        self.input_modalities = frozenset(str(m) for m in input_modalities)
        self.workspace_root = workspace_root
        self._http = http
        self.last_routed_model: str | None = None

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def retarget(
        self,
        model: str,
        supported_parameters: Iterable[str] = ("tools", "tool_choice", "reasoning"),
        input_modalities: Iterable[str] = ("text",),
    ) -> None:
        self.model = model
        self.supported_parameters = frozenset(str(p) for p in supported_parameters)
        self.input_modalities = frozenset(str(m) for m in input_modalities)

    def _openrouter_candidates(self) -> list[str]:
        from app.model_catalog import cached_catalog, harness_capable
        from app.models import BLOCKED_HARNESS_ROUTES

        live = [
            entry["id"]
            for entry in cached_catalog()
            if harness_capable(entry)
            and entry.get("is_free")
            and entry.get("available", True)
            and entry.get("id") not in BLOCKED_HARNESS_ROUTES
        ]
        ordered: list[str] = []
        for pref in DEFAULT_OPENROUTER_FREE_CANDIDATES:
            if pref in live and pref not in ordered:
                ordered.append(pref)
        for mid in live:
            if mid not in ordered:
                ordered.append(mid)
        if not ordered:
            ordered = list(DEFAULT_OPENROUTER_FREE_CANDIDATES[:3])
        return ordered[:4]

    def build_candidates(self, messages: list[dict], tools: list[dict]) -> list[tuple[str, OpenRouterClient]]:
        """Build the ordered cascade of (route_id, client) for this request."""
        local_client = LocalLlamaClient(
            LOCAL_HERETIC_MODEL_ID,
            http=self._http,
            supported_parameters=("tools", "tool_choice"),
            workspace_root=self.workspace_root,
        )
        if is_private_conversation(messages):
            return [(LOCAL_HERETIC_MODEL_ID, local_client)]

        candidates: list[tuple[str, OpenRouterClient]] = []

        # 1. Cerebras Free Tier (1000-2200 tok/s)
        if cloud_provider_api_key("cerebras"):
            for cid in ("cerebras/qwen-3-32b:free", "cerebras/llama-3.3-70b:free"):
                if not is_route_cooled_down(cid):
                    candidates.append((
                        cid,
                        CloudOpenAIClient("cerebras", cid, http=self._http, workspace_root=self.workspace_root),
                    ))

        # 2. Groq Cloud Free Tier (300-800 tok/s)
        if cloud_provider_api_key("groq"):
            for gid in ("groq/llama-3.3-70b-versatile:free", "groq/qwen-qwq-32b:free"):
                if not is_route_cooled_down(gid):
                    candidates.append((
                        gid,
                        CloudOpenAIClient("groq", gid, http=self._http, workspace_root=self.workspace_root),
                    ))

        # 3. Mistral Free Tier (Codestral / Mistral Small)
        if cloud_provider_api_key("mistral"):
            for mid in ("mistral/codestral-latest:free", "mistral/mistral-small-latest:free"):
                if not is_route_cooled_down(mid):
                    candidates.append((
                        mid,
                        CloudOpenAIClient("mistral", mid, http=self._http, workspace_root=self.workspace_root),
                    ))

        # 4. Google AI Studio Free Tier (Gemini 2.5 Flash)
        if cloud_provider_api_key("aistudio"):
            aid = "aistudio/gemini-2.5-flash:free"
            if not is_route_cooled_down(aid):
                candidates.append((
                    aid,
                    CloudOpenAIClient("aistudio", aid, http=self._http, workspace_root=self.workspace_root),
                ))

        # 5. OpenRouter :free Pool
        or_key = (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_KEY", "")).strip()
        if or_key:
            base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            if base_url and not base_url.endswith("/v1"):
                base_url = base_url.rstrip("/") + "/v1"
            for or_model in self._openrouter_candidates():
                if not is_route_cooled_down(or_model):
                    candidates.append((
                        or_model,
                        OpenRouterClient(
                            api_key=or_key,
                            model=or_model,
                            base_url=base_url,
                            http=self._http,
                            supported_parameters=("tools", "tool_choice"),
                            workspace_root=self.workspace_root,
                        ),
                    ))

        # 6. Always append Local Contabo Qwen3.5-35B-A3B-Heretic as the final 100% autonomous fallback
        candidates.append((LOCAL_HERETIC_MODEL_ID, local_client))
        return candidates

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        abort=None,
        effort: str | None = None,
    ) -> AsyncIterator[LLMEvent]:
        candidates = self.build_candidates(messages, tools)
        errors: list[str] = []

        for idx, (route_id, client) in enumerate(candidates):
            if abort and abort():
                return
            started = False
            try:
                async for ev in client.stream(messages, tools, abort=abort, effort=effort):
                    started = True
                    self.last_routed_model = route_id
                    if ev.kind == "final" and isinstance(ev.usage, dict):
                        ev.usage.setdefault("routed_model", route_id)
                    yield ev
                return
            except Exception as exc:
                if started:
                    # Never retry or switch providers mid-stream once tokens/tool_calls were emitted
                    raise
                mark_route_cooldown(route_id)
                errors.append(f"{route_id}: {exc}")
                if idx < len(candidates) - 1:
                    logger.warning(
                        "FreeWorkerRouter fallback from %s (%s) -> trying next candidate (%s)",
                        route_id,
                        exc,
                        candidates[idx + 1][0],
                    )
            finally:
                if self._http is None:
                    await client.aclose()

        raise RuntimeError(
            "FreeWorkerRouter exhausted all free candidates: " + "; ".join(errors)
        )


def create_free_pool_llm_client(
    model_id: str,
    *,
    supported_parameters: Iterable[str] = ("tools", "tool_choice"),
    input_modalities: Iterable[str] = ("text",),
    workspace_root: str | None = None,
):
    """Instantiate the right Harness LLM client for a Free Worker Pool model id."""
    prefix, _ = upstream_model_name(model_id)
    if prefix == "local":
        return LocalLlamaClient(
            model=model_id,
            supported_parameters=supported_parameters,
            input_modalities=input_modalities,
            workspace_root=workspace_root,
        )
    if prefix == "free":
        return FreeWorkerRouter(
            model=model_id,
            supported_parameters=supported_parameters,
            input_modalities=input_modalities,
            workspace_root=workspace_root,
        )
    if prefix in CLOUD_FREE_PROVIDERS:
        return CloudOpenAIClient(
            provider_prefix=prefix,
            model=model_id,
            supported_parameters=supported_parameters,
            input_modalities=input_modalities,
            workspace_root=workspace_root,
        )
    return None
