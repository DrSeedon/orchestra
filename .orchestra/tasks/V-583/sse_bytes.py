"""V-583: attribute streamed SSE bytes to the recording window they arrived in.

A stream opened in one phase keeps delivering in later ones, so per-request totals
would charge all of it to the phase it started in. Chunk timestamps fix that.
"""

import json
import sys

path = sys.argv[1]
d = json.load(open(path))

bounds = []  # (phase, cdp_start)
for r in sorted(d["requests"], key=lambda r: r.get("start") or 0):
    ph = r.get("phase")
    if ph and (not bounds or bounds[-1][0] != ph) and r.get("start"):
        if ph not in [b[0] for b in bounds]:
            bounds.append((ph, r["start"]))

print("phase boundaries (CDP monotonic seconds):")
for ph, t in bounds:
    print("  %-34s %.2f" % (ph, t))


def phase_of(ts):
    cur = bounds[0][0]
    for ph, t in bounds:
        if ts >= t:
            cur = ph
        else:
            break
    return cur


agg = {}
for r in d["requests"]:
    u = r.get("url") or ""
    if "/stream?" not in u:
        continue
    for ts, enc, dl in r.get("chunks") or []:
        ph = phase_of(ts)
        a = agg.setdefault(ph, [0, 0])
        a[0] += dl
        a[1] += 1

print("\nSSE bytes delivered per phase (dataLength, uncompressed):")
for ph, _ in bounds:
    if ph in agg:
        print("  %-34s %8d B in %3d chunks" % (ph, agg[ph][0], agg[ph][1]))
    else:
        print("  %-34s %8d B" % (ph, 0))
