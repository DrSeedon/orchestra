"""V-583: turn a raw CDP capture into per-phase request tables."""

import json
import sys
from collections import defaultdict


def short(url):
    return url.replace("http://127.0.0.1:8888", "")


def load(path):
    d = json.load(open(path))
    rows = []
    for r in d["requests"]:
        if not r.get("url"):
            continue
        chunks = r.get("chunks") or []
        enc = r.get("encoded_total")
        if not enc:
            # Streaming responses (EventSource) report encodedDataLength=0 per chunk;
            # only dataLength is available, so wire bytes ≈ headers + decoded body.
            enc = r.get("headers_bytes", 0) + sum(c[2] for c in chunks)
        start = r.get("start")
        fin = r.get("finish") or (chunks[-1][0] if chunks else r.get("response_at"))
        dur = (fin - start) * 1000 if (start and fin) else None
        rows.append({
            "phase": r.get("phase", "?"),
            "method": r.get("method", "?"),
            "url": short(r["url"]),
            "status": r.get("status"),
            "bytes": enc,
            "body_bytes": sum(c[2] for c in chunks),
            "ms": dur,
            "start": start,
            "cache": bool(r.get("from_disk_cache") or r.get("served_from_memory_cache")),
            "failed": r.get("failed"),
            "chunks": chunks,
        })
    rows.sort(key=lambda x: x["start"] or 0)
    return d, rows


def table(rows, phase_filter=None):
    out = []
    t0 = None
    for r in rows:
        if phase_filter and r["phase"] != phase_filter:
            continue
        if t0 is None:
            t0 = r["start"]
        out.append(
            "%-6s %-72s %-4s %9s %8s %7s %s"
            % (
                r["method"],
                r["url"][:72],
                r["status"] if r["status"] else "-",
                r["bytes"],
                ("%.0f" % r["ms"]) if r["ms"] is not None else "-",
                "%.2f" % ((r["start"] - t0)) if t0 else "0",
                ("CACHE" if r["cache"] else "") + (" FAIL:" + str(r["failed"]) if r["failed"] else ""),
            )
        )
    return "\n".join(out)


if __name__ == "__main__":
    path = sys.argv[1]
    d, rows = load(path)
    phases = []
    for r in rows:
        if r["phase"] not in phases:
            phases.append(r["phase"])
    print("== %s (%s) ==" % (path, d.get("captured_at")))
    print("%-6s %-72s %-4s %9s %8s %7s" % ("METHOD", "URL", "ST", "BYTES", "MS", "T+"))
    for ph in phases:
        sub = [r for r in rows if r["phase"] == ph]
        tot = sum(r["bytes"] for r in sub)
        print("\n--- phase %s: %d requests, %d bytes ---" % (ph, len(sub), tot))
        print(table(rows, ph))
    print("\n=== totals by phase ===")
    agg = defaultdict(lambda: [0, 0])
    for r in rows:
        agg[r["phase"]][0] += 1
        agg[r["phase"]][1] += r["bytes"]
    for ph in phases:
        print("%-32s %3d req %9d bytes" % (ph, agg[ph][0], agg[ph][1]))
