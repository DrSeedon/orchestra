"""Stateless capability-scoped entry point for one Harness turn."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.harness import prompts, tools
from app.harness.llm import OpenRouterClient
from app.harness.loop import AgentLoop
from app.harness.mcp import MCPClient
from app.models import get_model_spec, validate_harness_model_spec


async def run_oneshot(
    *, prompt: str, model: str, cwd: Path, tools_level: str = "read",
    network: bool = True, mcp: bool = True, system_prompt: str = "", llm=None,
) -> dict:
    spec = get_model_spec(model)
    validate_harness_model_spec(spec)
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_KEY", "")
    if not key:
        raise RuntimeError("No API key found (checked OPENROUTER_API_KEY, OPENROUTER_KEY)")
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    if not base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    llm = llm or OpenRouterClient(
        api_key=key, model=model, base_url=base_url,
        supported_parameters=spec.supported_parameters,
    )
    mcp_client = MCPClient()
    try:
        if mcp and tools_level == "all" and network:
            from app.runtime_registry import _load_scope_mcp_servers

            await mcp_client.connect(_load_scope_mcp_servers(str(cwd)))
        own_schemas = (
            tools.tool_schemas() if tools_level == "all" else tools.readonly_tool_schemas()
        )
        if not network:
            own_schemas = [
                item
                for item in own_schemas
                if item.get("function", {}).get("name") != "bash"
            ]
        schemas = prompts.merge_tool_schemas(own_schemas, mcp_client.tool_schemas())
        loop = AgentLoop(
            llm=llm,
            mcp=mcp_client,
            cwd=str(cwd),
            history=[{"role": "system", "content": system_prompt.strip()}],
            tool_schemas=schemas,
            max_context=spec.context_length,
            readonly_mode=tools_level != "all",
        )
        text: list[str] = []
        async for event in loop.run(prompt):
            if event.type == "text":
                text.append(event.content)
        usages = loop.round_usages
        return {
            "text": "".join(text).strip(),
            "ok": loop.ok,
            "stop_reason": loop.stop_reason,
            "error": loop.error_detail,
            "cost_usd": sum(float(item.get("cost") or 0) for item in usages),
            "usage": {
                "input_tokens": sum(int(item.get("prompt_tokens") or 0) for item in usages),
                "output_tokens": sum(
                    int(item.get("completion_tokens") or 0) for item in usages
                ),
            },
        }
    finally:
        await mcp_client.disconnect()
        await llm.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    args = parser.parse_args()
    row = asyncio.run(
        run_oneshot(prompt=os.sys.stdin.read(), model=args.model, cwd=args.cwd.resolve())
    )
    print(json.dumps(row, ensure_ascii=False))
    return 0 if row["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
