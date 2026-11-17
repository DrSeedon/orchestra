"""Foreground ordered durable records through actual loopback HTTP chat SSE."""
import asyncio,json
from pathlib import Path
import pytest
from tests.test_antigravity_acp import stand
from tests.test_antigravity_acp_r2 import real_session
from tests.test_antigravity_acp_submission import http_stand

EVIDENCE=Path(__file__).resolve().parents[1]/".orchestra/tasks/agy-acp-safe-20261117"


@pytest.mark.asyncio
async def test_ordered_native_journal_reaches_real_http_sse(stand,http_stand):
    s,client,_=http_stand;frames=[]
    async with client.stream("GET","/api/sessions/"+s.name+"/stream",params={"scope":s.scope}) as response:
        assert response.status_code==200
        submitted=asyncio.create_task(client.post("/api/sessions/"+s.name+"/send",json={"scope":s.scope,"message":"FG_TRANSCRIPT"}))
        async for line in response.aiter_lines():
            if not line.startswith("data: "):continue
            frame=json.loads(line[6:]);frames.append(frame)
            if frame.get("type")=="text" and frame.get("content")=="after tool":break
        assert (await submitted).status_code==200
    await s._listen_task;await s._await_log_futures()
    durable=[x for x in frames if x.get("type") in {"text","thinking","tool","tool_result"}]
    assert [x["type"] for x in durable]==["text","thinking","tool","tool_result","tool_result","tool","tool_result","text"]
    assert [x["id"] for x in durable]==sorted(x["id"] for x in durable)
    assert all(x.get("event_id") for x in durable)
    (EVIDENCE/"foreground-http-sse.json").write_text(json.dumps({"frames":frames,"single_prompt":sum(x["method"]=="session/prompt" for x in stand.trace())==1},ensure_ascii=False,indent=2))
