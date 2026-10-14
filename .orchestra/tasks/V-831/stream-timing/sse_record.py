"""Record live SSE frames of one session with arrival timestamps (V-831 timing study).

Usage: python sse_record.py <agent-name> <scope> <seconds> <out.jsonl>
Stores type, length and arrival time per frame; content kept only for live partial types.
"""
import json, os, sys, time, urllib.request

name, scope, seconds, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
url = (f"http://127.0.0.1:8888/api/sessions/{name}/stream?scope={urllib.parse.quote(scope)}"
       f"&after_id=999999999")
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {os.environ['INTERNAL_TOKEN']}"})
start = time.time()
with urllib.request.urlopen(req, timeout=seconds + 30) as resp, open(out, "w") as fh:
    for raw in resp:
        now = time.time()
        if now - start > seconds:
            break
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[6:])
        typ = payload.get("type")
        rec = {"t": round(now, 4), "type": typ, "len": len(payload.get("content") or ""),
               "key": payload.get("tool_use_id") or payload.get("item_id") or payload.get("id")}
        if typ in ("stream", "tool_input_stream", "thinking_stream"):
            rec["content"] = payload.get("content")
            rec["chars"] = payload.get("chars")
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
