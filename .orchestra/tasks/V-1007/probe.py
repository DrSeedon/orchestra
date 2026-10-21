import asyncio, sys, json
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
mode = sys.argv[1]
async def main():
    th = {"type":"adaptive","display":"summarized"} if mode=="summ" else ({"type":"enabled","budget_tokens":4000,"display":"summarized"} if mode=="en" else {"type":"adaptive"})
    o = ClaudeAgentOptions(model="claude-sonnet-5-5", thinking=th, effort="high", include_partial_messages=True, max_turns=1, tools=[], cwd="/tmp")
    out=[]
    async with ClaudeSDKClient(o) as c:
        await c.query("How many positive integers n<200 satisfy that n^2+n+41 is composite? Reason it through step by step before answering; give just the count.")
        async for m in c.receive_response():
            n=type(m).__name__
            if n=="StreamEvent":
                d=(m.event.get("delta") or {})
                if d.get("type")=="thinking_delta": out.append(("delta",len(d.get("thinking") or ""),d.get("estimated_tokens")))
            elif n=="AssistantMessage":
                for b in m.content:
                    print("BLOCK",type(b).__name__, len(getattr(b,"thinking",getattr(b,"text",""))), repr(getattr(b,"thinking",getattr(b,"text",""))[:80]))
            elif n=="ResultMessage":
                print("USAGE",json.dumps(m.usage), m.total_cost_usd)
    print("deltas",out[:3],len(out))
asyncio.run(main())
