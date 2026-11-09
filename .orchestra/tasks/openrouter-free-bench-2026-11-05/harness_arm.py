"""Sandbox-only Harness evaluation arm; key and prompt arrive on stdin."""
import asyncio
import ctypes
import json
import logging
import os
import sys
import time

ALLOWED = frozenset({
    "recursive/flint-v1.0:free", "dots-studio/dots-3-note-preview:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free", "cohere/north-mini-code:free",
    "nvidia/nemotron-3.5-super-vl:free",
})


def emit(kind, **values):
    print(json.dumps({"type": kind, **values}, ensure_ascii=False, default=str), flush=True)


async def main():
    logging.basicConfig(level=logging.ERROR)
    # Shell tools must not be able to inspect the parent's credential memory.
    if ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) != 0:
        raise RuntimeError("cannot protect credential memory")
    payload = json.loads(sys.stdin.read())
    key = payload.pop("api_key")
    model = payload["model"]
    if model not in ALLOWED or not model.endswith(":free"):
        raise ValueError("model outside the exact free evaluation allowlist")
    from app import db
    db.init_db()
    from app.model_catalog import normalize_catalog_model, apply_model_catalog
    rows = [normalize_catalog_model(row) for row in payload["catalog"]]
    db.kv_set("model_catalog_cache", json.dumps({"fetched_at": time.time(), "models": rows}))
    apply_model_catalog()
    from app.models import get_model_spec, validate_harness_model_spec, is_provider_disabled
    spec = get_model_spec(model)
    if is_provider_disabled("harness") or is_provider_disabled("openrouter"):
        raise ValueError("provider disabled")
    validate_harness_model_spec(spec)
    from app.quota_gate import get_worker_admission, require_worker_admission
    decision = await get_worker_admission(model)
    require_worker_admission(decision)
    emit("bench.admission", state=decision.state, reason=decision.reason)

    import httpx
    from app.harness import llm as llm_module, tools
    from app.harness.loop import AgentLoop
    llm_module.MAX_RETRIES = 1  # Explicit evaluation policy: no provider retries.
    requests = 0
    last_started = float(payload.get("not_before", 0)) - 3.2

    async def guard(request):
        nonlocal requests, last_started
        body = json.loads(request.content)
        if (request.url.host != "openrouter.ai" or request.url.path != "/api/v1/chat/completions"
                or body.get("model") != model or "models" in body or requests >= 3):
            raise ValueError("evaluation request guard refused the request")
        await asyncio.sleep(max(0, last_started + 3.2 - time.time()))
        requests += 1
        last_started = time.time()
        emit("bench.request", model=model, number=requests, started=last_started)

    class EvaluationClient(llm_module.OpenRouterClient):
        def _validate_route(self):
            if self.model != model or self.model not in ALLOWED:
                raise ValueError("retargeting outside the free evaluation is forbidden")
            super()._validate_route()

        def _build_body(self, *args, **kwargs):
            body = super()._build_body(*args, **kwargs)
            body["max_tokens"] = 1536
            return body

    class NoMCP:
        def has_tool(self, name): return False
        def display_name(self, name): return name

    http = httpx.AsyncClient(timeout=httpx.Timeout(65, connect=15), event_hooks={"request": [guard]})
    client = EvaluationClient(api_key=key, model=model, http=http,
                              supported_parameters=spec.supported_parameters)
    schemas = [tool for tool in tools.tool_schemas()
               if tool["function"]["name"] in {"read", "write", "edit", "bash"}]
    loop = AgentLoop(
        llm=client, mcp=NoMCP(), cwd="/work", max_context=spec.context_length,
        history=[{"role": "system", "content":
                  "Complete the supplied synthetic benchmark task using the tools. "
                  "Only inspect /work and only change files explicitly allowed by the task. "
                  "Do not inspect the host runtime or credentials. Return the requested final answer."}],
        tool_schemas=schemas, max_rounds=3, effort="medium",
        readonly_mode=payload["case"] != "repair",
    )
    text = []
    try:
        async for event in loop.run(payload["prompt"]):
            emit("bench.event", event_type=event.type, content=event.content, metadata=event.metadata)
            if event.type == "text":
                text.append(event.content)
        usage = loop.round_usages
        costs = [item.get("cost") for item in usage]
        cost = sum(costs) if len(usage) == requests and all(isinstance(c, (int, float)) for c in costs) else None
        emit("bench.final", model=model, text="".join(text), ok=loop.ok,
             stop_reason=loop.stop_reason, error=loop.error_detail.replace(key, "<credential>"),
             requests=requests, last_http_started=last_started,
             round_usages=usage, cost_usd=cost)
    finally:
        await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
