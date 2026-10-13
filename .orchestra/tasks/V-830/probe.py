import asyncio, json, sys, shutil
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
model, fast = sys.argv[1], sys.argv[2]=="1"
async def main():
    o = ClaudeAgentOptions(model=model, cli_path=shutil.which("claude"), permission_mode="default",
        max_turns=1, tools=[], setting_sources=["local"], env={"ANTHROPIC_API_KEY":"","DISABLE_TELEMETRY":"1"},
        settings=json.dumps({"fastMode":True}) if fast else None, extra_args={})
    async with ClaudeSDKClient(o) as c:
        await c.query("Reply with the single word: ok")
        async for m in c.receive_messages():
            d = getattr(m,"__dict__",{})
            dd=d.get("data") or {}; print(type(m).__name__, {k:v for k,v in dd.items() if "fast" in k.lower() or k in ("model",)}, (d.get("usage") or {}).get("speed") if isinstance(d.get("usage"),dict) else "", d.get("fast_mode_state"))
            if type(m).__name__=="ResultMessage": break
asyncio.run(main())
