"""Summarize per-block delta timing in a timestamped CLI stream-json capture."""
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
q = lambda xs, p: sorted(xs)[int(p * (len(xs) - 1))] if xs else None
blocks = {}
for r in rows:
    d = r["line"]
    if d.get("type") != "stream_event":
        continue
    e = d["event"]
    if e["type"] == "content_block_start":
        blocks[e["index"]] = {"type": e["content_block"]["type"], "start": r["t"], "deltas": []}
    elif e["type"] == "content_block_delta":
        dl = e["delta"]
        size = len(dl.get("text") or dl.get("partial_json") or dl.get("thinking") or "")
        blocks.setdefault(e["index"], {"type": "?", "start": r["t"], "deltas": []})["deltas"].append((r["t"], size, dl["type"]))
    elif e["type"] == "message_start":
        for k, b in list(blocks.items()):
            print_block = b
        blocks_done = None
    if e["type"] == "content_block_stop":
        b = blocks.pop(e["index"])
        ds = b["deltas"]
        gaps = [round((y[0] - x[0]) * 1000) for x, y in zip(ds, ds[1:])]
        sizes = [s for _, s, _ in ds]
        first = round((ds[0][0] - b["start"]) * 1000) if ds else None
        print(f"{b['type']:9} deltas={len(ds):4} chars={sum(sizes):5} span={round(ds[-1][0]-b['start'],2) if ds else 0}s "
              f"first_delta_after={first}ms size p50/p90/max={q(sizes,.5)}/{q(sizes,.9)}/{max(sizes) if sizes else 0} "
              f"gap_ms p50/p90/max={q(gaps,.5)}/{q(gaps,.9)}/{max(gaps) if gaps else 0}")
