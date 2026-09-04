"""Stateless read-only entry point for one Harness turn."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.harness import tools
from app.harness.llm import OpenRouterClient
from app.harness.loop import AgentLoop
from app.harness.mcp import MCPClient
from app.models import get_model_spec, validate_harness_model_spec


async def run_oneshot(*, prompt: str, model: str, cwd: Path) -> dict:
    spec = get_model_spec(model)
    validate_harness_model_spec(spec)
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_KEY", "")
    if not key:
        raise RuntimeError("No API key found (checked OPENROUTER_API_KEY, OPENROUTER_KEY)")
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    if not base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    llm = OpenRouterClient(
        api_key=key,
        model=model,
        base_url=base_url,
        supported_parameters=spec.supported_parameters,
    )
    loop = AgentLoop(
        llm=llm,
        mcp=MCPClient(),
        cwd=str(cwd),
        history=[{
            "role": "system",
            "content": (
                "You are a read-only workflow agent. Use read, glob, and grep only when needed. "
                "Return the requested result and do not modify files."
            ),
        }],
        tool_schemas=tools.readonly_tool_schemas(),
        max_context=spec.context_length,
        readonly_mode=True,
    )
    text: list[str] = []
    try:
        async for event in loop.run(prompt):
            if event.type == "text":
                text.append(event.content)
    finally:
        await llm.aclose()
    usages = loop.round_usages
    return {
        "text": "".join(text).strip(),
        "ok": loop.ok,
        "stop_reason": loop.stop_reason,
        "error": loop.error_detail,
        "cost_usd": sum(float(item.get("cost") or 0) for item in usages),
        "usage": {
            "input_tokens": sum(int(item.get("prompt_tokens") or 0) for item in usages),
            "output_tokens": sum(int(item.get("completion_tokens") or 0) for item in usages),
        },
    }


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
