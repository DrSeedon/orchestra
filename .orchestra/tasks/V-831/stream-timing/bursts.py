"""Group deltas of each block into bursts (arrivals within 15 ms) and summarize."""
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
q = lambda xs, p: sorted(xs)[int(p * (len(xs) - 1))] if xs else None
cur = {}
for r in rows:
    d = r["line"]
    if d.get("type") != "stream_event":
        continue
    e = d["event"]
    if e["type"] == "content_block_start":
        cur[e["index"]] = (e["content_block"]["type"], [])
    elif e["type"] == "content_block_delta":
        dl = e["delta"]
        cur[e["index"]][1].append((r["t"], len(dl.get("text") or dl.get("partial_json") or dl.get("thinking") or "")))
    elif e["type"] == "content_block_stop":
        typ, ds = cur.pop(e["index"])
        bursts = []
        for t, s in ds:
            if bursts and t - bursts[-1][1] <= 0.015:
                bursts[-1][1] = t; bursts[-1][2] += s
            else:
                bursts.append([t, t, s])
        sizes = [b[2] for b in bursts]
        gaps = [round((b[0] - a[1]) * 1000) for a, b in zip(bursts, bursts[1:])]
        print(f"{typ}: deltas={len(ds)} bursts={len(bursts)} chars/burst p50/p90/max={q(sizes,.5)}/{q(sizes,.9)}/{max(sizes) if sizes else 0} "
              f"gap_between_bursts_ms p50/p90/max={q(gaps,.5)}/{q(gaps,.9)}/{max(gaps) if gaps else 0}")
